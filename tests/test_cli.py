from __future__ import annotations

import argparse
import json

import pytest

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


def test_mark_notification_read_parser_and_dry_run(monkeypatch, capsys) -> None:
    class GuardClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def mark_notification_read(self, notification_id, *, execute=False):
            assert execute is False
            return {
                "success": True,
                "dry_run": True,
                "operation": "mark_notification_read",
                "method": "PATCH",
                "url": f"https://community.example.com/internal_api/notifications/{notification_id}/mark_as_read",
                "notification_id": notification_id,
                "csrf_present": True,
                "cookie_present": True,
            }

    monkeypatch.setattr(cli, "load_settings", lambda _path: argparse.Namespace(csrf_token="fake-csrf"))
    monkeypatch.setattr(cli, "CircleClient", GuardClient)
    parser = cli.build_parser()
    args = parser.parse_args(["mark-notification-read", "9000001", "--json"])
    assert args.handler is cli.cmd_mark_notification_read
    cli.cmd_mark_notification_read(args)
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["notification_id"] == 9000001
    assert output["url"].endswith("/9000001/mark_as_read")

    positioned = parser.parse_args(["mark-notification-read", "9000002", "--env-file", ".env"])
    assert positioned.notification_id == 9000002
    assert positioned.env_file == ".env"


OPEN_DOCUMENT = {
    "fetched_at": "2026-01-01T00:00:00Z",
    "source": {"host": "community.example.com", "notification_group": "inbox"},
    "notifications": [
        {
            "id": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "action": "course_comment",
            "notifiable_title": "Alice posted a comment on your lesson",
            "action_web_url": "https://community.example.com/c/ai/lessons/1#message_11",
        },
        {
            "id": 2,
            "created_at": "2026-01-02T00:00:00Z",
            "action": "course_comment",
            "notifiable_title": "Bob posted a comment on your lesson",
            "action_web_url": "https://community.example.com/c/coding/lessons/2#message_22",
        },
    ],
}


def _open_args(tmp_path, **overrides):
    input_path = tmp_path / "notifications.json"
    input_path.write_text(json.dumps(OPEN_DOCUMENT), encoding="utf-8")
    defaults = dict(
        input=str(input_path),
        category="lesson_comments",
        interval=3.0,
        order="newest",
        dedupe=True,
        background=False,
        opener=None,
        execute=False,
        confirm=None,
        json=True,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_open_notifications_parser_defaults() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["open-notifications"])
    assert args.category == "lesson_comments"
    assert args.interval == 3.0
    assert args.dedupe is True
    assert args.execute is False
    assert args.background is False
    assert args.handler is cli.cmd_open_notifications


def test_open_notifications_defaults_to_dry_run(tmp_path, monkeypatch, capsys) -> None:
    called = {"opened": False}
    monkeypatch.setattr(cli, "open_sequentially", lambda *a, **k: called.update(opened=True))
    cli.cmd_open_notifications(_open_args(tmp_path))
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["category"] == "lesson_comments"
    assert len(output["targets"]) == 2
    assert called["opened"] is False


def test_open_notifications_execute_requires_confirmation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "open_sequentially", lambda *a, **k: {"opened": 0})
    with pytest.raises(ValueError):
        cli.cmd_open_notifications(_open_args(tmp_path, execute=True, confirm="WRONG"))


def test_open_notifications_execute_calls_opener(tmp_path, monkeypatch, capsys) -> None:
    captured = {}

    def fake_open(targets, *, interval, opener, background):
        captured.update(targets=targets, interval=interval, opener=opener, background=background)
        return {"opened": len(targets), "failed": 0, "urls": [], "failures": [],
                "interval": interval, "background": background}

    monkeypatch.setattr(cli, "open_sequentially", fake_open)
    monkeypatch.setattr(cli, "default_opener", lambda: "/usr/bin/open")
    cli.cmd_open_notifications(
        _open_args(tmp_path, execute=True, confirm="OPEN-NOTIFICATIONS")
    )
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is False
    assert output["opened"] == 2
    assert captured["opener"] == "/usr/bin/open"
    assert [target["url"] for target in captured["targets"]] == [
        "https://community.example.com/c/coding/lessons/2#message_22",
        "https://community.example.com/c/ai/lessons/1#message_11",
    ]


def test_open_notifications_execute_empty_is_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "default_opener", lambda: "/usr/bin/open")
    args = _open_args(tmp_path, category="comments", execute=True, confirm="OPEN-NOTIFICATIONS")
    with pytest.raises(ValueError):
        cli.cmd_open_notifications(args)

