from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest
import requests

from circle_client_skill.client import CircleClient, CircleClientError
from circle_client_skill.config import CircleSettings


def record(status=None):
    return {"id": 11, "status": status, "flagged_contentable": {
        "id": 22, "space_id": 33, "type": "Post", "status": "published",
        "flagged_for_approval_at": None if status == "approved" else "2026-01-01T00:00:00Z",
        "removed_at": "2026-01-01T01:00:00Z" if status == "rejected" else None,
    }}


class Response:
    status_code = 200

    def __init__(self, payload):
        self.headers = {}
        self.payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self.payload


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return Response(copy.deepcopy(result))


def client(session):
    return CircleClient(CircleSettings(
        notifications_url="https://community.example.com/internal_api/notifications",
        count_url="https://community.example.com/internal_api/notifications/new_notifications_count",
        reset_count_url="https://community.example.com/internal_api/notifications/mark_all_as_read",
        cookie="session=fake", csrf_token="fake-csrf",
    ), session=session)


def moderate(c, action="approve", **kwargs):
    return c.moderate_post(11, action=action, expected_post_id=22, expected_space_id=33, **kwargs)


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_dry_run_is_offline_and_has_no_credentials(action):
    session = Session()
    result = moderate(client(session), action)
    assert result["dry_run"] is True
    assert result["operation"] == f"{action}-post"
    assert session.calls == []
    assert "fake-csrf" not in json.dumps(result)
    assert "session=fake" not in json.dumps(result)


@pytest.mark.parametrize("action, desired", [("approve", "approved"), ("reject", "rejected")])
def test_action_checks_identity_and_reads_back_including_retained_reject_pending_time(action, desired):
    session = Session(record(), {"success": True}, record(desired))
    result = moderate(client(session), action, execute=True)
    assert result["verified"] is True and result["status"] == desired
    assert [call[0] for call in session.calls] == ["GET", "PATCH", "GET"]
    patch = session.calls[1]
    assert patch[1].endswith(f"/flagged_contents/11/{action}")
    assert patch[2]["json"] == ({} if action == "approve" else {"action_reason_body": None})
    assert patch[2]["headers"]["X-CSRF-Token"] == "fake-csrf"


@pytest.mark.parametrize("field, value", [("id", 23), ("space_id", 34), ("type", "Comment")])
def test_mismatched_post_or_space_never_writes(field, value):
    before = record()
    before["flagged_contentable"][field] = value
    session = Session(before)
    with pytest.raises(CircleClientError, match="target does not match"):
        moderate(client(session), execute=True)
    assert [call[0] for call in session.calls] == ["GET"]


def test_mismatched_moderation_record_never_writes():
    before = record()
    before["id"] = 12
    session = Session(before)
    with pytest.raises(CircleClientError, match="target does not match"):
        moderate(client(session), execute=True)
    assert len(session.calls) == 1


@pytest.mark.parametrize("action, desired", [("approve", "approved"), ("reject", "rejected")])
def test_repeat_reads_and_skips_patch(action, desired):
    session = Session(record(desired))
    result = moderate(client(session), action, execute=True)
    assert result["already_moderated"] is True
    assert [call[0] for call in session.calls] == ["GET"]


def test_opposite_state_is_not_reversed():
    session = Session(record("rejected"))
    with pytest.raises(CircleClientError, match="not pending"):
        moderate(client(session), execute=True)
    assert len(session.calls) == 1


@pytest.mark.parametrize("field", ["cookie", "csrf_token"])
def test_missing_credentials_never_sends_a_request(field):
    session = Session()
    c = client(session)
    c = CircleClient(replace(c.settings, **{field: None}), session=session)
    with pytest.raises(CircleClientError, match="requires cookie and CSRF"):
        moderate(c, execute=True)
    assert session.calls == []


def test_inconsistent_removed_post_is_not_approved():
    before = record()
    before["flagged_contentable"]["removed_at"] = "2026-01-01T01:00:00Z"
    session = Session(before)
    with pytest.raises(CircleClientError, match="not pending"):
        moderate(client(session), execute=True)
    assert len(session.calls) == 1


@pytest.mark.parametrize("field", ["flagged_for_approval_at", "removed_at", "status"])
def test_incomplete_readback_is_not_success(field):
    after = record("approved")
    del (after if field == "status" else after["flagged_contentable"])[field]
    session = Session(record(), {"success": True}, after)
    with pytest.raises(CircleClientError, match="incomplete"):
        moderate(client(session), execute=True)
    assert [call[0] for call in session.calls] == ["GET", "PATCH", "GET"]


def test_uncertain_patch_is_reconciled_without_retry():
    session = Session(record(), requests.Timeout("fake timeout"), record("approved"))
    result = moderate(client(session), execute=True)
    assert result["reconciled"] is True and result["verified"] is True
    assert [call[0] for call in session.calls].count("PATCH") == 1


def test_acknowledgement_without_successful_readback_is_not_success():
    session = Session(record(), {"success": True}, record())
    with pytest.raises(CircleClientError, match="readback did not confirm"):
        moderate(client(session), execute=True)


def test_readback_transport_failure_keeps_outcome_unknown():
    session = Session(record(), {"success": True}, requests.Timeout("fake timeout"))
    with pytest.raises(CircleClientError, match="outcome unknown"):
        moderate(client(session), execute=True)
    assert [call[0] for call in session.calls].count("PATCH") == 1


@pytest.mark.parametrize("invalid", [-1, 0, True, "11/approve"])
def test_id_validation_precedes_network(invalid):
    session = Session()
    with pytest.raises(ValueError, match="positive integer"):
        client(session).moderate_post(invalid, action="approve", expected_post_id=22, expected_space_id=33, execute=True)
    assert session.calls == []
