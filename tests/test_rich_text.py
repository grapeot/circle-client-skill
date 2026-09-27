from __future__ import annotations

from typing import Any

import pytest

from circle_client_skill import cli
from circle_client_skill.client import CircleClient
from circle_client_skill.config import CircleSettings
from circle_client_skill.formatters import (
    _body_text,
    format_chat_messages_table,
    format_mention_sgids_table,
)
from circle_client_skill.rich_text import rich_text_message_text, rich_text_paragraphs

ROOM = "00000000-0000-0000-0000-000000000000"


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200, text: str | None = None) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.payload = payload
        self.text = text if text is not None else ("" if payload is None else str(payload))

    def json(self) -> Any:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse({})


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


def _doc(*blocks: dict[str, Any], members: list[dict[str, Any]] | None = None, fallback: str | None = None) -> dict[str, Any]:
    rich: dict[str, Any] = {"body": {"type": "doc", "content": list(blocks)}}
    if members is not None:
        rich["community_members"] = members
    if fallback is not None:
        rich["circle_ios_fallback_text"] = fallback
    return {"rich_text_body": rich}


def _paragraph(*nodes: dict[str, Any]) -> dict[str, Any]:
    if not nodes:
        return {"type": "paragraph"}
    return {"type": "paragraph", "content": list(nodes)}


def test_rich_text_paragraphs_splits_mentions_breaks_and_skips_empty() -> None:
    record = _doc(
        _paragraph(
            {"type": "mention", "attrs": {"sgid": "FAKE-SGID-0001"}},
            {"type": "text", "text": " hello"},
            {"type": "hardBreak"},
            {"type": "text", "text": "there"},
        ),
        _paragraph(),
        _paragraph({"type": "mention", "attrs": {"sgid": "FAKE-SGID-MISSING"}}),
        _paragraph({"type": "text", "text": "tail"}),
        members=[
            {"sgid": "FAKE-SGID-0001", "name": "Test User", "id": 9000100, "user_id": 9000200},
        ],
    )
    assert rich_text_paragraphs(record) == ["@Test User hello\nthere", "@…", "tail"]
    assert rich_text_message_text(record) == "@Test User hello\nthere\n\n@…\n\ntail"


def test_rich_text_paragraphs_without_doc_returns_empty_and_message_uses_fallback() -> None:
    missing = {"id": 9000001}
    assert rich_text_paragraphs(missing) == []
    assert rich_text_message_text(missing) == ""

    fallback_only = {"rich_text_body": {"circle_ios_fallback_text": "  flat text  "}}
    assert rich_text_paragraphs(fallback_only) == []
    assert rich_text_message_text(fallback_only) == "flat text"

    blank = _doc(_paragraph(), fallback="   ")
    assert rich_text_paragraphs(blank) == []
    assert rich_text_message_text(blank) == ""


def test_body_text_renders_mention_and_keeps_plain_text_regression() -> None:
    mentioned = _doc(
        _paragraph(
            {"type": "mention", "attrs": {"sgid": "FAKE-SGID-0001"}},
            {"type": "text", "text": " hello"},
        ),
        members=[{"sgid": "FAKE-SGID-0001", "name": "Test User"}],
    )
    assert _body_text(mentioned) == "@Test User hello"
    assert _body_text({"body": "  hello   world  "}) == "hello world"
    assert _body_text(
        {
            "rich_text_body": {
                "body": {
                    "type": "doc",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "hello world"}]}
                    ],
                }
            }
        }
    ) == "hello world"
    broken = _doc(
        _paragraph({"type": "text", "text": "line1"}, {"type": "hardBreak"}, {"type": "text", "text": "line2"}),
        _paragraph({"type": "text", "text": "next"}),
    )
    assert _body_text(broken) == "line1\nline2\n\nnext"


def test_chat_table_shows_mention_without_breaking_columns() -> None:
    message = {
        "id": 9000001,
        "created_at": "2026-01-01T00:00:00Z",
        "chat_room_participant_id": 9000010,
        "replies_count": 0,
        "rich_text_body": {
            "body": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "mention", "attrs": {"sgid": "FAKE-SGID-0001"}},
                            {"type": "text", "text": " hello"},
                        ],
                    },
                    {"type": "paragraph"},
                    {"type": "paragraph", "content": [{"type": "text", "text": "second line"}]},
                ],
            },
            "community_members": [
                {"sgid": "FAKE-SGID-0001", "name": "Test User", "id": 9000100, "user_id": 9000200}
            ],
        },
    }
    output = format_chat_messages_table([message], {"total_count": 1})
    lines = output.splitlines()
    header = lines[1]
    row = lines[2]
    assert header.index("BODY_PREVIEW") == row.index("@Test User")
    assert "@Test User hello second line" in row
    assert "\n" not in row


class RoutingSession(FakeSession):
    def __init__(self, roots: list[dict[str, Any]], replies: list[dict[str, Any]]) -> None:
        super().__init__()
        self._roots = roots
        self._replies = replies

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        if "parent_message_id=" in url:
            return FakeResponse({"records": self._replies})
        return FakeResponse({"records": self._roots})


def _room_fixtures() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    roots = [
        {
            "id": 9000001,
            "replies_count": 1,
            "rich_text_body": {
                "community_members": [
                    {"sgid": "FAKE-SGID-0001", "id": 9000100},
                    {"sgid": "FAKE-SGID-0002", "id": 9000101},
                ],
                "sgids_to_object_map": {
                    "FAKE-SGID-0001": {"id": 9000100, "user_id": 9000200},
                    "FAKE-SGID-0002": {
                        "name": "Other User",
                        "id": 9000101,
                        "user_id": 9000201,
                    },
                },
            },
        },
        {
            "id": 9000002,
            "replies_count": 0,
            "rich_text_body": {
                "community_members": [
                    {
                        "sgid": "FAKE-SGID-0001",
                        "name": "Test User",
                        "id": 9000100,
                        "user_id": 9000200,
                    }
                ],
                "sgids_to_object_map": {
                    "FAKE-SGID-0002": {"name": "Should Not Override", "id": 9000101},
                },
            },
        },
    ]
    replies = [
        {
            "id": 9000003,
            "parent_message_id": 9000001,
            "rich_text_body": {
                "community_members": [
                    {
                        "sgid": "FAKE-SGID-0003",
                        "name": "Reply User",
                        "id": 9000102,
                        "user_id": 9000202,
                    }
                ],
                "sgids_to_object_map": {
                    "FAKE-SGID-0001": {"name": "Later Name", "id": 9000100},
                },
            },
        }
    ]
    return roots, replies


def test_mention_sgids_in_room_dedupes_and_fills_name_from_later_message() -> None:
    roots, replies = _room_fixtures()
    session = RoutingSession(roots, replies)
    mapping = CircleClient(_settings(), session=session).mention_sgids_in_room(
        ROOM,
        previous_per_page=7,
        threads_per_page=3,
    )
    assert mapping == {
        "FAKE-SGID-0001": {
            "name": "Later Name",
            "community_member_id": 9000100,
            "user_id": 9000200,
            "seen_in_message_id": 9000001,
        },
        "FAKE-SGID-0002": {
            "name": "Other User",
            "community_member_id": 9000101,
            "user_id": 9000201,
            "seen_in_message_id": 9000001,
        },
        "FAKE-SGID-0003": {
            "name": "Reply User",
            "community_member_id": 9000102,
            "user_id": 9000202,
            "seen_in_message_id": 9000003,
        },
    }
    assert "previous_per_page=7" in session.calls[0]["url"]
    assert "next_per_page=0" in session.calls[0]["url"]
    assert any("parent_message_id=9000001" in call["url"] and "next_per_page=3" in call["url"] for call in session.calls)
    assert not any("parent_message_id=9000002" in call["url"] for call in session.calls)


def test_format_mention_sgids_table_truncates_sgid() -> None:
    sgid = "FAKE-SGID-" + ("a" * 30)
    table = format_mention_sgids_table(
        {
            sgid: {
                "name": "Test User",
                "community_member_id": 9000100,
                "user_id": 9000200,
                "seen_in_message_id": 9000001,
            }
        }
    )
    assert "NAME" in table and "COMMUNITY_MEMBER_ID" in table and "USER_ID" in table and "SGID" in table
    assert "Test User" in table
    assert "9000100" in table
    assert sgid not in table
    assert sgid[:24] + "…" in table


def test_mention_sgids_help_documents_reply_flow(capsys: pytest.CaptureFixture[str]) -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["mention-sgids", "--help"])
    assert caught.value.code == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "chat-send --mention-sgid <sgid> --parent-message-id <root-id>" in output
    assert "--no-threads" not in output
    assert "replies_count > 0" in output
    assert "--room-uuid" in output
    args = parser.parse_args(
        [
            "mention-sgids",
            "--room-uuid",
            ROOM,
            "--previous-per-page",
            "10",
        ]
    )
    assert not hasattr(args, "no_threads")
    assert args.previous_per_page == 10
    assert args.threads_per_page == 50
    assert args.handler is cli.cmd_mention_sgids


def test_mention_sgids_empty_hint(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class FakeClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None: ...

        def mention_sgids_in_room(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {}

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = cli.build_parser().parse_args(["mention-sgids", "--room-uuid", ROOM])
    cli.cmd_mention_sgids(args)
    assert capsys.readouterr().out.strip() == (
        "no mentions found in the fetched window; try `search-mentions --query <name>`"
    )
