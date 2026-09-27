from __future__ import annotations

from typing import Any

import pytest

from circle_client_skill.client import CircleClient, CircleClientError
from circle_client_skill.config import CircleSettings


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str, **_: Any) -> FakeResponse:
        self.calls.append(url)
        page = len(self.calls)
        return FakeResponse(
            {
                "notifications": [{"id": page, "title": f"Notification {page}"}],
                "has_next_page": page == 1,
            }
        )


def test_fetch_follows_explicit_pagination() -> None:
    settings = CircleSettings(
        notifications_url="https://community.example.com/internal_api/notifications",
        count_url="https://community.example.com/internal_api/notifications/new_notifications_count",
        reset_count_url="https://community.example.com/internal_api/notifications/mark_all_as_read",
        authorization="Bearer fake",
    )
    session = FakeSession()

    result = CircleClient(settings, session=session).fetch_notifications(per_page=100)

    assert result["count"] == 2
    assert result["source"]["unread_only"] is True
    assert result["source"]["records_scanned"] == 2
    assert result["source"]["pages_fetched"] == 2
    assert "per_page=100" in session.calls[0]
    assert "page=2" in session.calls[1]


def test_fetch_stops_at_consecutive_read_frontier() -> None:
    settings = CircleSettings(
        notifications_url="https://community.example.com/internal_api/notifications",
        count_url="https://community.example.com/internal_api/notifications/new_notifications_count",
        reset_count_url="https://community.example.com/internal_api/notifications/mark_all_as_read",
        authorization="Bearer fake",
    )

    class ReadFrontierSession:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, *_: Any, **__: Any) -> FakeResponse:
            self.calls += 1
            return FakeResponse(
                {
                    "records": [
                        {"id": 1, "read_at": None},
                        {"id": 2, "read_at": "2026-01-01T00:00:00Z"},
                        {"id": 3, "read_at": "2026-01-01T00:00:01Z"},
                        {"id": 4, "read_at": None},
                    ],
                    "has_next_page": True,
                }
            )

    session = ReadFrontierSession()
    result = CircleClient(settings, session=session).fetch_notifications(
        stop_after_consecutive_read=2
    )

    assert result["count"] == 1
    assert result["source"]["records_scanned"] == 3
    assert result["source"]["stop_reason"] == "consecutive_read_threshold"
    assert session.calls == 1


def test_count_extracts_nested_count() -> None:
    settings = CircleSettings(
        notifications_url="https://community.example.com/internal_api/notifications",
        count_url="https://community.example.com/internal_api/notifications/new_notifications_count",
        reset_count_url="https://community.example.com/internal_api/notifications/mark_all_as_read",
        authorization="Bearer fake",
    )

    class CountSession:
        def get(self, *_: Any, **__: Any) -> FakeResponse:
            return FakeResponse({"data": {"new_notifications_count": 42}})

    result = CircleClient(settings, session=CountSession()).get_notification_count()
    assert result["count"] == 42


def test_reset_count_is_dry_run_by_default_and_posts_only_when_executed() -> None:
    settings = CircleSettings(
        notifications_url="https://community.example.com/internal_api/notifications",
        count_url="https://community.example.com/internal_api/notifications/new_notifications_count",
        reset_count_url="https://community.example.com/internal_api/notifications/mark_all_as_read",
        authorization="Bearer fake",
        cookie="session=fake",
        csrf_token="fake-csrf",
        origin="https://community.example.com",
    )

    class MutationSession:
        def __init__(self) -> None:
            self.posts = 0

        def post(self, *_: Any, **kwargs: Any) -> FakeResponse:
            self.posts += 1
            assert kwargs["headers"]["X-CSRF-Token"] == "fake-csrf"
            return FakeResponse({"success": True})

    session = MutationSession()
    client = CircleClient(settings, session=session)

    preflight = client.reset_notification_count()
    assert preflight["dry_run"] is True
    assert session.posts == 0

    result = client.reset_notification_count(execute=True)
    assert result["dry_run"] is False
    assert session.posts == 1


def _mark_read_settings(**overrides: Any) -> CircleSettings:
    base: dict[str, Any] = {
        "notifications_url": "https://community.example.com/internal_api/notifications",
        "count_url": "https://community.example.com/internal_api/notifications/new_notifications_count",
        "reset_count_url": "https://community.example.com/internal_api/notifications/mark_all_as_read",
        "authorization": "Bearer fake",
        "cookie": "session=fake",
        "csrf_token": "fake-csrf",
        "origin": "https://community.example.com",
    }
    base.update(overrides)
    return CircleSettings(**base)


class PatchSession:
    def __init__(self, status_code: int = 204) -> None:
        self.status_code = status_code
        self.patches: list[tuple[str, dict[str, Any]]] = []

    def patch(self, url: str, **kwargs: Any) -> FakeResponse:
        self.patches.append((url, kwargs))
        response = FakeResponse({"success": True})
        response.status_code = self.status_code
        return response


def test_mark_notification_read_is_dry_run_by_default() -> None:
    session = PatchSession()
    client = CircleClient(_mark_read_settings(), session=session)

    preflight = client.mark_notification_read(9000001)

    assert preflight["dry_run"] is True
    assert preflight["method"] == "PATCH"
    assert preflight["url"].endswith("/9000001/mark_as_read")
    assert preflight["notification_id"] == 9000001
    assert session.patches == []


def test_mark_notification_read_executes_patch_with_csrf() -> None:
    session = PatchSession()
    client = CircleClient(_mark_read_settings(), session=session)

    result = client.mark_notification_read(9000001, execute=True)

    assert result["dry_run"] is False
    assert result["status_code"] == 204
    assert len(session.patches) == 1
    url, kwargs = session.patches[0]
    assert url == "https://community.example.com/internal_api/notifications/9000001/mark_as_read"
    assert kwargs["headers"]["X-CSRF-Token"] == "fake-csrf"


def test_mark_notification_read_accepts_200_and_strips_trailing_slash() -> None:
    settings = _mark_read_settings(
        notifications_url="https://community.example.com/internal_api/notifications/"
    )
    session = PatchSession(status_code=200)
    client = CircleClient(settings, session=session)

    result = client.mark_notification_read(9000001, execute=True)

    assert result["status_code"] == 200
    url, _ = session.patches[0]
    assert url == "https://community.example.com/internal_api/notifications/9000001/mark_as_read"


def test_mark_notification_read_rejects_non_positive_id() -> None:
    session = PatchSession()
    client = CircleClient(_mark_read_settings(), session=session)

    for bad_id in (0, -1):
        with pytest.raises(ValueError, match="must be positive"):
            client.mark_notification_read(bad_id, execute=True)
    assert session.patches == []


def test_mark_notification_read_requires_credentials_when_executed() -> None:
    client = CircleClient(_mark_read_settings(csrf_token=None), session=PatchSession())

    with pytest.raises(CircleClientError, match="Cookie and X-CSRF-Token"):
        client.mark_notification_read(9000001, execute=True)


def test_mark_notification_read_raises_on_non_success_status() -> None:
    session = PatchSession(status_code=422)
    client = CircleClient(_mark_read_settings(), session=session)

    with pytest.raises(CircleClientError) as excinfo:
        client.mark_notification_read(9000001, execute=True)
    assert excinfo.value.status_code == 422
