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


def test_list_posts_with_counts_injects_comment_count(monkeypatch, capsys) -> None:
    """`--with-counts` probes list_comments per post and injects comments_count."""
    calls = {"list_comments": []}

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def list_posts(self, *, space_id, page, per_page):
            return {
                "records": [{"id": 10, "name": "A", "slug": "a"}, {"id": 20, "name": "B", "slug": "b"}],
                "count": 2, "page": 1, "per_page": per_page, "has_next_page": False,
            }

        def list_comments(self, post_id, *, per_page=1, page=1):
            calls["list_comments"].append(post_id)
            # 第一个 post 3 条评论, 第二个 0 条
            return {"count": 3 if post_id == 10 else 0, "records": [], "has_next_page": False}

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = argparse.Namespace(
        env_file="unused.env", timeout=30, space_id=12, page=1, per_page=24,
        full=False, with_counts=True, json=True,
    )
    cli.cmd_list_posts(args)
    output = json.loads(capsys.readouterr().out)
    counts = {p["id"]: p["comments_count"] for p in output["posts"]}
    assert counts == {10: 3, 20: 0}
    assert calls["list_comments"] == [10, 20]


def test_list_posts_without_counts_does_not_probe_comments(monkeypatch, capsys) -> None:
    probed = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def list_posts(self, *, space_id, page, per_page):
            return {"records": [{"id": 1, "name": "X", "slug": "x"}], "count": 1, "page": 1,
                    "per_page": per_page, "has_next_page": False}

        def list_comments(self, *_a, **_kw):
            probed.append(1)
            return {"count": 0, "records": []}

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = argparse.Namespace(
        env_file="unused.env", timeout=30, space_id=12, page=1, per_page=24,
        full=False, with_counts=False, json=True,
    )
    cli.cmd_list_posts(args)
    assert probed == []


def test_list_posts_with_counts_tolerates_per_post_failure(monkeypatch, capsys) -> None:
    """A failed list_comments probe sets comments_count=None; later posts still probed."""
    from circle_client_skill.client import CircleClientError

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def list_posts(self, *, space_id, page, per_page):
            return {"records": [{"id": 10, "name": "A", "slug": "a"}, {"id": 20, "name": "B", "slug": "b"}],
                    "count": 2, "page": 1, "per_page": per_page, "has_next_page": False}

        def list_comments(self, post_id, *, per_page=1, page=1):
            if post_id == 10:
                raise CircleClientError("boom")
            return {"count": 5, "records": [], "has_next_page": False}

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = argparse.Namespace(
        env_file="unused.env", timeout=30, space_id=12, page=1, per_page=24,
        full=False, with_counts=True, json=True,
    )
    cli.cmd_list_posts(args)
    output = json.loads(capsys.readouterr().out)
    counts = {p["id"]: p["comments_count"] for p in output["posts"]}
    assert counts == {10: None, 20: 5}


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
