from __future__ import annotations

import argparse
from typing import Any

import pytest

from circle_client_skill import cli
from circle_client_skill.client import CircleClient, CircleClientError
from circle_client_skill.config import CircleSettings
from circle_client_skill.formatters import format_mutation_dryrun, format_mutation_result
from circle_client_skill.reactions import resolve_unicode

BASE = "https://example.test/internal_api/reactions"


def _settings() -> CircleSettings:
    return CircleSettings(
        notifications_url="https://example.test/internal_api/notifications",
        count_url="https://example.test/internal_api/notifications/new_notifications_count",
        reset_count_url="https://example.test/internal_api/notifications/mark_all_as_read",
        authorization="Bearer fake",
        cookie="session=fake",
        csrf_token="fake-csrf",
        origin="https://example.test",
    )


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.text = text or (str(payload) if payload is not None else "")
        self.payload = payload

    def json(self) -> Any:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses: dict[str, FakeResponse] = {}
        self._default = FakeResponse({})
        self._get = FakeResponse({})

    def set_response(self, method_url: str, response: FakeResponse) -> None:
        self._responses[method_url] = response

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self._responses.get(f"{method} {url.split('?')[0]}", self._default)

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self._get


def _client(session: FakeSession) -> CircleClient:
    return CircleClient(_settings(), session=session)


def test_resolve_unicode_maps_semantic_names() -> None:
    assert resolve_unicode("heart") == "2764-fe0f"
    assert resolve_unicode("thumb_up") == "1f44d"
    assert resolve_unicode("star") == "2b50"
    assert resolve_unicode("2764-fe0f") == "2764-fe0f"


def test_unicode_glyph_computes_any_emoji() -> None:
    from circle_client_skill.reactions import unicode_glyph

    assert unicode_glyph("2764-fe0f") == "❤️"
    assert unicode_glyph("1f64f") == "🙏"
    assert unicode_glyph("1f64f-1f3fd") == "🙏🏽"
    assert unicode_glyph("2b50") == "⭐"
    assert unicode_glyph("zzz") == "🙂"
    assert unicode_glyph(None) == "🙂"


def test_reaction_glyph_falls_back_to_label_initial() -> None:
    from circle_client_skill.reactions import reaction_glyph

    assert reaction_glyph("1f64f", "pray") == "🙏"
    assert reaction_glyph("bogus-code", "pray") == "p"


def test_resolve_unicode_rejects_garbage() -> None:
    for bad in ("", "  ", "heart-eyes", "not-a-code!"):
        with pytest.raises(ValueError):
            resolve_unicode(bad)


def test_create_reaction_dry_run_preflight_without_request() -> None:
    session = FakeSession()
    result = _client(session).create_reaction("chat_room_message", 9000001, "2764-fe0f")
    assert result["dry_run"] is True
    assert result["target_kind"] == "chat_room_message"
    assert result["target_id"] == 9000001
    assert result["method"] == "POST"
    assert result["url"] == BASE
    assert len(session.calls) == 0


def test_create_reaction_payload_matches_captured_contract() -> None:
    session = FakeSession()
    _client(session).create_reaction("chat_room_message", 9000001, "2764-fe0f", execute=True)
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"].startswith(BASE)
    assert call["json"] == {"unicode": "2764-fe0f", "chat_room_message": 9000001}


def test_create_reaction_rejects_unknown_kind_and_bad_ids() -> None:
    client = _client(FakeSession())
    with pytest.raises(ValueError):
        client.create_reaction("lesson", 123, "2764-fe0f")
    with pytest.raises(ValueError):
        client.create_reaction("chat_room_message", 0, "2764-fe0f")
    with pytest.raises(ValueError):
        client.create_reaction("chat_room_message", 123, "")


def test_create_reaction_requires_credentials_when_live() -> None:
    settings = CircleSettings(
        notifications_url="https://example.test/internal_api/notifications",
        count_url="https://example.test/internal_api/notifications/new_notifications_count",
        reset_count_url="https://example.test/internal_api/notifications/mark_all_as_read",
        authorization="Bearer fake",
        cookie=None,
        csrf_token=None,
        origin="https://example.test",
    )
    session = FakeSession()
    with pytest.raises(CircleClientError):
        CircleClient(settings, session=session).create_reaction(
            "chat_room_message", 123, "2764-fe0f", execute=True
        )


def test_create_reaction_error_status_is_passed_through() -> None:
    session = FakeSession()
    session.set_response("POST https://example.test/internal_api/reactions", FakeResponse({}, status_code=422))
    with pytest.raises(CircleClientError) as excinfo:
        _client(session).create_reaction("chat_room_message", 123, "2764-fe0f", execute=True)
    assert excinfo.value.status_code == 422


def _react_args(**overrides: Any) -> Any:
    args = argparse.Namespace(
        env_file="unused.env",
        json=False,
        timeout=30,
        execute=False,
        confirm=None,
        message_id=9000001,
        emoji="heart",
        unicode_code=None,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_cli_react_dry_run_prints_preflight(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda _path: argparse.Namespace(csrf_token="fake-csrf", cookie="fake"))

    class GuardClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def create_reaction(self, kind, target_id, unicode_code, *, execute=False):
            assert execute is False
            return {
                "success": True,
                "dry_run": True,
                "operation": "create_reaction",
                "method": "POST",
                "url": BASE,
                "target_kind": kind,
                "target_id": target_id,
                "unicode": unicode_code,
                "csrf_present": True,
                "cookie_present": True,
            }

    monkeypatch.setattr(cli, "CircleClient", GuardClient)
    cli.cmd_react(_react_args())
    output = capsys.readouterr().out
    assert "DRY-RUN: react" in output
    assert "target_kind: chat_room_message" in output
    assert "target_id: 9000001" in output
    assert "unicode: 2764-fe0f" in output
    assert "--confirm REACT" in output


def test_cli_react_rejects_wrong_confirm_token() -> None:
    with pytest.raises(ValueError):
        cli.cmd_react(_react_args(execute=True, confirm="SEND"))


def test_cli_react_rejects_emoji_and_unicode_together() -> None:
    with pytest.raises(ValueError):
        cli.cmd_react(_react_args(unicode_code="2b50"))


def test_cli_react_rejects_missing_emoji_and_unicode() -> None:
    with pytest.raises(ValueError):
        cli.cmd_react(_react_args(emoji=None))


def test_react_result_formatter() -> None:
    result = {
        "target_kind": "chat_room_message",
        "target_id": 9000001,
        "unicode": "2764-fe0f",
        "reactions": None,
    }
    line = format_mutation_result(result, "react")
    assert line == "OK: reacted ❤️ on chat_room_message 9000001"


def test_react_dryrun_formatter_matches_confirm_token() -> None:
    text = format_mutation_dryrun({"operation": "react", "target_id": 1})
    assert "DRY-RUN: react" in text
    assert "--confirm REACT" in text