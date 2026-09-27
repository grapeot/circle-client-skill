from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from circle_client_skill import cli
from circle_client_skill.client import CircleClient, CircleClientError
from circle_client_skill.config import CircleSettings
from circle_client_skill.formatters import format_mentions_table
from circle_client_skill.rich_text import build_rich_text_body

ROOM = "00000000-0000-0000-0000-000000000000"
LESSON_ROOM = "11111111-1111-1111-1111-111111111111"


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
        self._responses: dict[str, FakeResponse] = {}
        self._default = FakeResponse({})

    def set_response(self, method_url: str, response: FakeResponse) -> None:
        self._responses[method_url] = response

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        key = f"{method} {url}"
        if key in self._responses:
            return self._responses[key]
        base = f"{method} {url.split('?')[0]}"
        return self._responses.get(base, self._default)

    def get(self, url: str, **_: Any) -> FakeResponse:
        return self.request("GET", url)


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


def _legacy_rich(text: str) -> dict[str, Any]:
    return {
        "body": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": text}],
                }
            ],
        },
        "attachments": [],
    }


def test_build_rich_text_body_without_mentions_matches_legacy_single_paragraph() -> None:
    text = "hello\n\nworld"
    body = build_rich_text_body(text)
    assert body == _legacy_rich(text)
    assert body == build_rich_text_body(text, None)
    assert body == build_rich_text_body(text, [])
    assert json.dumps(body, ensure_ascii=False) == json.dumps(_legacy_rich(text), ensure_ascii=False)
    assert body["body"]["content"][0]["content"][0]["text"] == text


def test_build_rich_text_body_mentions_one_and_two_sgids() -> None:
    one = build_rich_text_body("hi", ["FAKE-SGID-0001"])
    assert one["body"]["content"] == [
        {
            "type": "paragraph",
            "content": [
                {"type": "mention", "attrs": {"sgid": "FAKE-SGID-0001"}},
                {"type": "text", "text": " hi"},
            ],
        }
    ]
    two = build_rich_text_body("hello\n\nworld", ["FAKE-SGID-0001", "FAKE-SGID-0002"])
    assert two == {
        "body": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "mention", "attrs": {"sgid": "FAKE-SGID-0001"}},
                        {"type": "mention", "attrs": {"sgid": "FAKE-SGID-0002"}},
                        {"type": "text", "text": " hello"},
                    ],
                },
                {"type": "paragraph"},
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "world"}],
                },
            ],
        },
        "attachments": [],
    }


def test_send_chat_message_without_mentions_matches_legacy_body() -> None:
    session = FakeSession()
    session.set_response(
        f"POST https://example.test/internal_api/chat_rooms/{ROOM}/messages",
        FakeResponse({"creation_uuid": "fake-creation"}, status_code=202),
    )
    text = "Hello chat\nsecond"
    CircleClient(_settings(), session=session).send_chat_message(
        chat_room_uuid=ROOM,
        chat_room_participant_id=9000010,
        text=text,
    )
    rich = session.calls[0]["json"]["chat_room_message"]["rich_text_body"]
    assert rich == _legacy_rich(text)
    assert json.dumps(rich, separators=(",", ":"), ensure_ascii=False) == json.dumps(
        _legacy_rich(text), separators=(",", ":"), ensure_ascii=False
    )


def test_send_chat_message_with_mentions_inserts_nodes() -> None:
    session = FakeSession()
    session.set_response(
        f"POST https://example.test/internal_api/chat_rooms/{ROOM}/messages",
        FakeResponse({"creation_uuid": "fake-creation"}, status_code=202),
    )
    CircleClient(_settings(), session=session).send_chat_message(
        chat_room_uuid=ROOM,
        chat_room_participant_id=9000010,
        text="hi",
        mention_sgids=["FAKE-SGID-0001"],
    )
    message = session.calls[0]["json"]["chat_room_message"]
    content = message["rich_text_body"]["body"]["content"][0]["content"]
    assert message["chat_room_participant_id"] == 9000010
    assert content[0] == {"type": "mention", "attrs": {"sgid": "FAKE-SGID-0001"}}
    assert content[1]["text"] == " hi"


def test_update_chat_message_patches_body_without_participant_id() -> None:
    session = FakeSession()
    message_id = 9000001
    url = f"https://example.test/internal_api/chat_rooms/{ROOM}/messages/{message_id}"
    session.set_response("PATCH " + url, FakeResponse({"id": message_id}))
    rich = build_rich_text_body("hi", ["FAKE-SGID-0001"])
    result = CircleClient(_settings(), session=session).update_chat_message(
        ROOM, message_id, rich_text_body=rich
    )
    assert result["id"] == message_id
    call = session.calls[0]
    assert call["method"] == "PATCH"
    assert call["url"].endswith(f"/messages/{message_id}")
    body = call["json"]
    assert body == {"chat_room_message": {"rich_text_body": rich, "attachments": []}}
    assert "participant" not in json.dumps(body)


def test_search_mentions_table_truncates_sgid() -> None:
    session = FakeSession()
    sgid = "FAKE-SGID-" + ("a" * 30)
    payload = [
        {
            "id": 9000010,
            "name": "<span>Member</span>",
            "just_name": "Member",
            "sgid": sgid,
            "content": "<span>Member</span>",
        }
    ]
    session.set_response("GET https://example.test/users/mentions.json", FakeResponse(payload))
    result = CircleClient(_settings(), session=session).search_mentions("Member", per_page=5)
    assert result == payload
    url = session.calls[0]["url"]
    assert url.startswith("https://example.test/users/mentions.json?")
    assert "query=Member" in url
    assert "per_page=5" in url
    table = format_mentions_table(result)
    assert "NAME" in table and "USER_ID" in table and "SGID" in table
    assert "Member" in table
    assert "9000010" in table
    assert sgid not in table
    assert sgid[:24] + "…" in table


def test_search_mentions_rejects_non_list() -> None:
    session = FakeSession()
    session.set_response(
        "GET https://example.test/users/mentions.json",
        FakeResponse({"records": []}),
    )
    with pytest.raises(CircleClientError, match="did not return a list"):
        CircleClient(_settings(), session=session).search_mentions("Member")


def test_update_chat_message_dry_run_does_not_call_client(monkeypatch, capsys) -> None:
    class GuardClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def update_chat_message(self, *_args, **_kwargs):
            raise AssertionError("dry-run must not patch")

        def get_space(self, *_args, **_kwargs):
            raise AssertionError("room uuid must not resolve a space")

        def get_course_lesson(self, *_args, **_kwargs):
            raise AssertionError("room uuid must not resolve a lesson")

    monkeypatch.setattr(cli, "load_settings", lambda _path: argparse.Namespace(csrf_token="fake-csrf"))
    monkeypatch.setattr(cli, "CircleClient", GuardClient)
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "update-chat-message",
            "--room-uuid",
            ROOM,
            "--message-id",
            "9000001",
            "--text",
            "hi " + ("x" * 120),
            "--mention-sgid",
            "FAKE-SGID-0001",
            "--mention-sgid",
            "FAKE-SGID-0002",
            "--json",
        ]
    )
    cli.cmd_update_chat_message(args)
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True
    assert output["operation"] == "update_chat_message"
    assert output["chat_room_uuid"] == ROOM
    assert output["message_id"] == 9000001
    assert output["text"] == ("hi " + ("x" * 120))[:100]
    assert output["mentions"] == 2
    assert output["csrf_present"] is True
    positioned = parser.parse_args(
        [
            "update-chat-message",
            "--room-uuid",
            ROOM,
            "--message-id",
            "9000001",
            "--text",
            "hi",
            "--env-file",
            ".env",
        ]
    )
    assert positioned.env_file == ".env"


def test_update_chat_message_tiptap_preview_and_rejects_mentions(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda _path: argparse.Namespace(csrf_token=None))
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "update-chat-message",
            "--room-uuid",
            ROOM,
            "--message-id",
            "9000001",
            "--tiptap-json",
            json.dumps(_legacy_rich("kept")),
            "--json",
        ]
    )
    cli.cmd_update_chat_message(args)
    output = json.loads(capsys.readouterr().out)
    assert output["text"] == "tiptap body"
    assert output["mentions"] == 0

    def boom(_path: object) -> object:
        raise AssertionError("invalid mention combo must fail before loading settings")

    monkeypatch.setattr(cli, "load_settings", boom)
    rejected = parser.parse_args(
        [
            "update-chat-message",
            "--room-uuid",
            ROOM,
            "--message-id",
            "9000001",
            "--tiptap-json",
            "{}",
            "--mention-sgid",
            "FAKE-SGID-0001",
        ]
    )
    with pytest.raises(ValueError, match="mention-sgid"):
        cli.cmd_update_chat_message(rejected)


def test_update_chat_message_execute_uses_lesson_room(monkeypatch, capsys) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def get_space(self, *_args, **_kwargs):
            raise AssertionError("lesson room must not use the space chat room")

        def get_course_lesson(self, space_id: int, section_id: int, lesson_id: int) -> dict:
            assert (space_id, section_id, lesson_id) == (9000000, 9000001, 9000002)
            return {"chat_room_uuid": LESSON_ROOM}

        def update_chat_message(self, chat_room_uuid: str, message_id: int, *, rich_text_body: dict) -> dict:
            captured["room"] = chat_room_uuid
            captured["message_id"] = message_id
            captured["body"] = rich_text_body
            return {"id": message_id}

    monkeypatch.setattr(cli, "load_settings", lambda _path: argparse.Namespace(csrf_token="fake-csrf"))
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = cli.build_parser().parse_args(
        [
            "update-chat-message",
            "-s",
            "9000000",
            "--section-id",
            "9000001",
            "--lesson-id",
            "9000002",
            "--message-id",
            "9000001",
            "--text",
            "hello",
            "--mention-sgid",
            "FAKE-SGID-0001",
            "--execute",
            "--confirm",
            "UPDATE-CHAT-MESSAGE",
            "--json",
        ]
    )
    cli.cmd_update_chat_message(args)
    assert captured["room"] == LESSON_ROOM
    assert captured["message_id"] == 9000001
    content = captured["body"]["body"]["content"][0]["content"]
    assert content[0]["type"] == "mention"
    assert "participant" not in json.dumps(captured["body"])
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is False
    assert output["message_id"] == 9000001


def test_chat_send_dry_run_resolves_lesson_room_and_counts_mentions(monkeypatch, capsys) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def get_space(self, *_args, **_kwargs):
            raise AssertionError("lesson room must not use the space chat room")

        def get_course_lesson(self, space_id: int, section_id: int, lesson_id: int) -> dict:
            assert (space_id, section_id, lesson_id) == (9000000, 9000001, 9000002)
            return {"chat_room_uuid": LESSON_ROOM}

        def send_chat_message(self, *_args, **_kwargs):
            raise AssertionError("dry-run must not send")

    monkeypatch.setattr(cli, "load_settings", lambda _path: argparse.Namespace(csrf_token="fake-csrf"))
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = cli.build_parser().parse_args(
        [
            "chat-send",
            "-s",
            "9000000",
            "--section-id",
            "9000001",
            "--lesson-id",
            "9000002",
            "--participant-id",
            "9000010",
            "--text",
            "hello",
            "--mention-sgid",
            "FAKE-SGID-0001",
            "--json",
        ]
    )
    cli.cmd_chat_send(args)
    output = json.loads(capsys.readouterr().out)
    assert output["chat_room_uuid"] == LESSON_ROOM
    assert output["mentions"] == 1
    assert output["participant_id"] == 9000010
    assert output["dry_run"] is True
