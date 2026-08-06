from __future__ import annotations

import argparse
import json

from circle_client_skill import cli


def test_unreplied_resolves_space_filters_member_and_limits(monkeypatch, capsys) -> None:
    roots = [
        {
            "id": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "parent_message_id": None,
            "thread_participants_preview": [],
        },
        {
            "id": 2,
            "created_at": "2026-01-03T00:00:00Z",
            "parent_message_id": None,
            "thread_participants_preview": [{"community_member_id": 42}],
        },
        {
            "id": 3,
            "created_at": "2026-01-02T00:00:00Z",
            "parent_message_id": None,
            "thread_participants_preview": [{"community_member_id": 7}],
        },
    ]

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            self.scanned_room = None

        def get_space(self, space_id: int) -> dict:
            assert space_id == 12
            return {"chat_room_uuid": "fake-room-uuid"}

        def scan_chat_roots(self, room_uuid: str) -> list[dict]:
            assert room_uuid == "fake-room-uuid"
            return roots

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = argparse.Namespace(
        env_file="unused.env",
        timeout=30,
        room_uuid=None,
        space_id=12,
        member_id=42,
        limit=1,
        json=True,
    )

    cli.cmd_unreplied(args)

    output = json.loads(capsys.readouterr().out)
    assert [message["id"] for message in output] == [3]


def test_chat_parser_accepts_json_after_subcommand_and_direction_defaults() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["list-chat-messages", "--room-uuid", "fake-room", "--json"])
    assert args.json is True
    assert args.direction == "previous"
    assert args.previous_per_page == 50
    assert args.next_per_page == 0

    replies = parser.parse_args(
        ["list-chat-replies", "--room-uuid", "fake-room", "--parent-message-id", "1"]
    )
    assert replies.direction == "next"
    assert replies.previous_per_page == 0
    assert replies.next_per_page == 50


def test_list_chat_messages_renders_newest_first(monkeypatch, capsys) -> None:
    """Room-level list reverses ascending API order so newest is on top.

    Thread replies (list-chat-replies) intentionally keep ascending order.
    """
    ascending = [
        {"id": 1, "created_at": "2026-01-01T00:00:00Z", "body": {"old": True}},
        {"id": 2, "created_at": "2026-01-02T00:00:00Z", "body": {"new": True}},
    ]

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def get_space(self, space_id: int) -> dict:
            return {"chat_room_uuid": "fake-room-uuid"}

        def list_chat_messages(self, *, chat_room_uuid, previous_per_page, next_per_page, cursor):
            return {
                "records": list(ascending),
                "total_count": 2,
                "first_id": 1,
                "last_id": 2,
                "has_previous_page": False,
                "has_next_page": False,
            }

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = argparse.Namespace(
        env_file="unused.env",
        timeout=30,
        room_uuid=None,
        space_id=12,
        cursor=None,
        direction="previous",
        previous_per_page=50,
        next_per_page=0,
        json=True,
    )

    cli.cmd_list_chat_messages(args)
    output = json.loads(capsys.readouterr().out)
    assert [m["id"] for m in output["records"]] == [2, 1]
    # Pagination cursors stay anchored to the ascending API page.
    assert output["first_id"] == 1
    assert output["last_id"] == 2
