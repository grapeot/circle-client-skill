from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

import pytest

from circle_client_skill.dashboard import (
    VERIFIED_REACTION_KINDS,
    ActionError,
    DashboardCache,
    DashboardServer,
    assemble_state,
    build_comment_rows,
    build_room_rows,
    context_key,
    group_notifications,
)
from circle_client_skill.dashboard_ui import PAGE

LESSON_ROOM = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
# Fake settings are only touched if a real client would be built; server tests
# inject a fake client instead, so values stay synthetic.
URL = "https://example.test/internal_api/reactions"


def _notification(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": 1,
        "notifiable_type": "Comment",
        "notifiable_id": 9001,
        "action": "comment",
        "created_at": "2026-10-15T10:00:00.000Z",
        "read_at": None,
        "notifiable_title": "Post A",
        "space_title": "Space A",
        "actor_name": "Alice",
        "post_id": 7001,
        "action_web_url": "https://community.example.com/c/space/post-a#comment_wrapper_9001",
    }
    base.update(overrides)
    return base


class FakeClient:
    def __init__(
        self,
        *,
        comments: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
        replies: list[dict[str, Any]] | None = None,
        participants: list[dict[str, Any]] | None = None,
        badge: int = 7,
    ) -> None:
        self.comments = comments or []
        self.messages = messages or []
        self.replies = replies or []
        self.participants = participants or []
        self.badge = badge
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_comments(self, post_id: int, *, page: int = 1, per_page: int = 15) -> dict[str, Any]:
        self.calls.append(("list_comments", {"post_id": post_id, "page": page}))
        return {"records": [] if page > 1 else self.comments, "has_next_page": False}

    def list_chat_messages(self, chat_room_uuid: str, **_: Any) -> dict[str, Any]:
        self.calls.append(("list_chat_messages", {"room": chat_room_uuid}))
        return {"records": self.messages, "first_id": 1, "last_id": 2}

    def fetch_chat_replies(self, chat_room_uuid: str, parent_message_id: int, **_: Any) -> dict[str, Any]:
        self.calls.append(("fetch_chat_replies", {"room": chat_room_uuid, "parent": parent_message_id}))
        return {"records": [m for m in self.replies if m.get("parent_message_id") == parent_message_id]}

    def list_room_participants(self, chat_room_uuid: str, *, page: int = 1) -> dict[str, Any]:
        self.calls.append(("participants", {"room": chat_room_uuid, "page": page}))
        return {"records": [] if page > 1 else self.participants, "has_next_page": False}

    def get_notification_count(self) -> dict[str, Any]:
        return {"count": self.badge, "raw": {"new_notifications_count": self.badge}}

    def create_reaction(self, kind: str, target_id: int, unicode_code: str, *, execute: bool = False) -> dict[str, Any]:
        assert execute is True
        self.calls.append(("create_reaction", {"kind": kind, "id": target_id, "unicode": unicode_code}))
        return {"success": True, "reactions": None}

    def create_comment_like(self, comment_id: int, *, reaction_type: str = "like", execute: bool = False) -> dict[str, Any]:
        assert execute is True
        self.calls.append(("create_comment_like", {"id": comment_id, "reaction_type": reaction_type}))
        return {"success": True, "response": None}

    def mark_notification_read(self, notification_id: int, *, execute: bool = False) -> dict[str, Any]:
        assert execute is True
        self.calls.append(("mark_read", {"id": notification_id}))
        return {"success": True}

    def fetch_notifications(self) -> dict[str, Any]:
        return {"notifications": [], "count": 0, "fetched_at": "2026-10-15T00:00:00Z", "source": {}}


def test_context_key_routing() -> None:
    room_notif = _notification(
        notifiable_type="ChatRoomMessage",
        action="course_comment",
        notifiable_id=9000002,
        action_inbox_path=f"/settings/inbox/course-comments/{LESSON_ROOM}",
        post_id=None,
    )
    assert context_key(room_notif) == ("room", LESSON_ROOM)
    assert context_key(_notification(action="like")) == ("like", 7001)
    assert context_key(_notification()) == ("post", 7001)
    assert context_key(_notification(notifiable_type="Post", action="like", post_id=7001)) == ("like", 7001)
    assert context_key(_notification(notifiable_type="Post", action="mention", post_id=7001)) == ("post_link",)
    assert context_key(_notification(notifiable_type="FlaggedContent", post_id=None)) == ("other",)
    bad_room = _notification(notifiable_type="ChatRoomMessage", action="x", notifiable_id=2, action_inbox_path="/settings/inbox/other", post_id=None)
    assert context_key(bad_room) == ("other",)


def test_group_and_dedupe_same_message() -> None:
    mention = _notification(id=2, action="comment_mention", notifiable_id=9001, created_at="2026-10-15T10:05:00.000Z")
    groups = group_notifications([_notification(), mention])
    assert list(groups) == [("post", 7001)]
    assert len(groups[("post", 7001)]) == 2


def _comment(comment_id: int, *, parent: int | None = None, created: str = "2026-10-15T09:00:00.000Z", text: str = "hi") -> dict[str, Any]:
    return {
        "id": comment_id,
        "parent_comment_id": parent,
        "created_at": created,
        "tiptap_body": {
            "body": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
            }
        },
        "community_member": {"name": f"Member{comment_id}"},
        "reactions": [{"emoji": "heart", "unicode": "2764-fe0f", "count": 1}],
    }


def test_build_comment_rows_includes_chain_and_replies() -> None:
    root = _comment(1, parent=None, created="2026-10-15T08:00:00.000Z")
    parent_reply = _comment(2, parent=1, created="2026-10-15T09:00:00.000Z")
    target = _comment(3, parent=2, created="2026-10-15T10:00:00.000Z", text="the target")
    other_target = _comment(9, parent=None, created="2026-10-15T07:00:00.000Z")
    client = FakeClient(comments=[root, parent_reply, target, other_target])
    rows = build_comment_rows(client, 7001, {3, 9})
    assert [row["id"] for row in rows] == [9, 1, 2, 3]
    assert rows[-1]["text"] == "the target"
    assert rows[0]["text"] == "hi"
    assert rows[-1]["depth"] == 2 and rows[-1]["reply_to"] == "Member2"
    assert rows[1]["depth"] == 0
    assert rows[-1]["reactions"][0]["unicode"] == "2764-fe0f"


def test_build_room_rows_includes_parents_and_thread_replies() -> None:
    root = {
        "id": 100,
        "chat_room_participant_id": 1,
        "created_at": "2026-10-15T08:00:00.000Z",
        "rich_text_body": {
            "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "root msg"}]}]},
            "attachments": [],
        },
        "replies_count": 1,
        "reactions": [],
    }
    reply = {
        "id": 101,
        "parent_message_id": 100,
        "chat_room_participant_id": 2,
        "created_at": "2026-10-15T09:00:00.000Z",
        "rich_text_body": {
            "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "mention", "attrs": {"sgid": "s1"}}, {"type": "text", "text": " reply"}]}]},
            "community_members": [{"sgid": "s1", "name": "Bob"}],
            "attachments": [],
        },
        "replies_count": 0,
        "reactions": [{"emoji": "heart", "unicode": "2764-fe0f", "count": 1, "community_member_ids": [9000042]}],
    }
    client = FakeClient(
        messages=[root],
        replies=[reply],
        participants=[{"id": 2, "name": "Bob", "community_member_id": 42}, {"id": 1, "name": "Amy", "community_member_id": 41}],
    )
    rows = build_room_rows(client, LESSON_ROOM, {101})
    assert [row["id"] for row in rows] == [100, 101]
    assert rows[-1]["actor_name"] == "Bob"
    assert rows[-1]["reply_to"] == "Amy" and rows[-1]["depth"] == 1
    assert "@Bob" in rows[-1]["text"]
    assert rows[-1]["reactions"][0] == {"unicode": "2764-fe0f", "emoji": "heart", "count": 1}
    assert rows[0]["text"] == "root msg"


def test_build_room_rows_walks_backwards_for_old_threads() -> None:
    window1 = [{
        "id": 9000010,
        "chat_room_participant_id": 5,
        "created_at": "2026-10-15T11:00:00.000Z",
        "rich_text_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "recent"}]}]}, "attachments": []},
        "replies_count": 0,
        "reactions": [],
    }]
    old_root = {
        "id": 9000000,
        "chat_room_participant_id": 5,
        "created_at": "2025-02-21T04:03:13.860Z",
        "rich_text_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "old thread root"}]}]}, "attachments": []},
        "replies_count": 2,
        "reactions": [],
    }
    replies = [
        {"id": 9000006, "parent_message_id": 9000000, "chat_room_participant_id": 6, "created_at": "2026-10-14T10:53:59.780Z", "rich_text_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "target A"}]}]}, "attachments": []}, "replies_count": 0, "reactions": []},
        {"id": 9000007, "parent_message_id": 9000000, "chat_room_participant_id": 6, "created_at": "2026-10-14T11:05:23.727Z", "rich_text_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "target B"}]}]}, "attachments": []}, "replies_count": 0, "reactions": []},
    ]
    participant = [{"id": 6, "name": "Drew", "community_member_id": 88}, {"id": 5, "name": "Hank", "community_member_id": 89}]
    feeds = {"first": {"records": window1}, "older": {"records": [old_root]}}

    class PagingClient(FakeClient):
        def __init__(self) -> None:
            super().__init__(replies=replies, participants=participant)

        def list_chat_messages(self, chat_room_uuid: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("list_chat_messages", {"room": chat_room_uuid, **kwargs}))
            return feeds["older"] if kwargs.get("cursor") is not None else feeds["first"]

    client = PagingClient()
    rows = build_room_rows(client, LESSON_ROOM, {9000006, 9000007})
    cursor_calls = [c for c in client.calls if c[1].get("cursor") is not None]
    assert len(cursor_calls) == 1  # the walk stops as soon as the walk page resolved the targets
    assert rows[0]["text"] == "old thread root"
    texts = [r["text"] for r in rows]
    assert texts == ["old thread root", "target A", "target B"]  # unrelated window roots stay hidden
    assert rows[0]["depth"] == 0
    assert rows[1]["depth"] == 1 and rows[1]["reply_to"] == "Hank"
    assert not any(row.get("missing") for row in rows)


def test_build_room_rows_backward_walk_is_bounded() -> None:
    class EndlessClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.next_id = 9000099

        def list_chat_messages(self, chat_room_uuid: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("list_chat_messages", {"room": chat_room_uuid, **kwargs}))
            self.next_id -= 1
            return {"records": [{
                "id": self.next_id,
                "chat_room_participant_id": 5,
                "created_at": "2026-10-15T11:00:00.000Z",
                "rich_text_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "recent"}]}]}, "attachments": []},
                "replies_count": 0,
                "reactions": [],
            }]}

    client = EndlessClient()
    rows = build_room_rows(client, LESSON_ROOM, {999999999})
    message_calls = [c for c in client.calls if c[0] == "list_chat_messages"]
    assert len(message_calls) == 1 + 12  # initial page + bounded walk ceiling
    assert any(row.get("missing") for row in rows)


def test_build_room_rows_groups_threads_over_chronology() -> None:
    root_a = {
        "id": 9000010,
        "chat_room_participant_id": 5,
        "created_at": "2026-10-14T08:00:00.000Z",
        "rich_text_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "root A"}]}]}, "attachments": []},
        "replies_count": 1,
        "reactions": [],
    }
    root_b = dict(root_a, id=9000011, created_at="2026-10-14T09:00:00.000Z", rich_text_body={"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "root B"}]}]}, "attachments": []}, replies_count=0)
    late_reply = {
        "id": 9000012,
        "parent_message_id": 9000010,
        "chat_room_participant_id": 6,
        "created_at": "2026-10-14T19:00:00.000Z",
        "rich_text_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "late reply to A"}]}]}, "attachments": []},
        "replies_count": 0,
        "reactions": [],
    }
    client = FakeClient(
        messages=[root_a, root_b],
        replies=[late_reply],
        participants=[{"id": 5, "name": "Hank", "community_member_id": 89}],
    )
    rows = build_room_rows(client, LESSON_ROOM, {9000012})
    assert [row["text"] for row in rows] == ["root A", "late reply to A"]  # unrelated roots stay hidden
    assert rows[1]["reply_to"] == "Hank" and rows[1]["depth"] == 1


def test_cache_skips_builder_on_hit() -> None:
    cache = DashboardCache()
    calls = {"n": 0}

    def builder(client: Any, key: tuple[Any, ...], target_ids: set[int]) -> list[dict[str, Any]]:
        calls["n"] += 1
        return [{"id": tid, "kind": "comment", "text": "x", "reactions": []} for tid in sorted(target_ids)]

    first = cache.rows_for(None, ("post", 1), {3}, builder)
    again = cache.rows_for(None, ("post", 1), {3}, builder)
    bigger = cache.rows_for(None, ("post", 1), {3, 4}, builder)
    assert first == again
    assert calls["n"] == 2
    assert [row["id"] for row in bigger] == [3, 4]


def _doc(notifications: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fetched_at": "2026-10-15T12:00:00.000Z",
        "source": {"host": "community.example.com"},
        "count": len(notifications),
        "notifications": notifications,
    }


def _room_notification(**overrides: Any) -> dict[str, Any]:
    return _notification(
        **{
            "notifiable_type": "ChatRoomMessage",
            "action": "course_comment",
            "notifiable_id": 9000002,
            "notifiable_title": "Lesson discussion",
            "space_title": "Space B",
            "action_inbox_path": f"/settings/inbox/course-comments/{LESSON_ROOM}",
            "action_web_url": "https://community.example.com/c/ai#message_9000002",
            "post_id": None,
            "id": 50,
            **overrides,
        }
    )


def test_assemble_state_sections_and_likes() -> None:
    client = FakeClient(
        comments=[_comment(3, parent=None, created="2026-10-15T10:00:00.000Z")],
        messages=[{
            "id": 9000002,
            "chat_room_participant_id": 5,
            "created_at": "2026-10-15T11:00:00.000Z",
            "rich_text_body": {
                "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "lesson msg"}]}]},
                "attachments": [],
            },
            "replies_count": 0,
            "reactions": [],
        }],
        participants=[{"id": 5, "name": "Cara", "community_member_id": 9}],
    )
    notifications = [
        _notification(id=1, notifiable_id=3),
        _room_notification(id=50),
        _notification(id=2, action="like", notifiable_id=8888, actor_name="Fan1", post_id=7001, created_at="2026-10-15T09:00:00.000Z"),
        _notification(
            id=3,
            notifiable_type="FlaggedContent",
            action="flagged_community_member_new_comment",
            notifiable_id=3126451,
            post_id=None,
            actor_name="James",
        ),
    ]
    state = assemble_state(client, _doc(notifications), cache=DashboardCache(), verified_kinds=VERIFIED_REACTION_KINDS)
    ids = {s["id"]: s for s in state["sections"]}
    assert list(ids) == ["discussions", "likes", "other"]
    discussions = ids["discussions"]["contexts"]
    room_ctx = next(c for c in discussions if c["kind"] == "room")
    post_ctx = next(c for c in discussions if c["kind"] == "post")
    assert room_ctx["title"] == "Lesson discussion"
    assert room_ctx["targets"][0]["notification_ids"] == [50]
    assert room_ctx["targets"][0]["target"] == {"kind": "chat_room_message", "id": 9000002}
    assert post_ctx["targets"][0]["notification_ids"] == [1]
    assert state["verified_reaction_kinds"] == list(VERIFIED_REACTION_KINDS)
    assert state["badge_count"] == 7
    assert any(e["name"] == "heart" for e in state["emotes"])
    like = ids["likes"]["groups"][0]
    assert like["count"] == 1 and like["actors"] == ["Fan1"] and like["notification_ids"] == [2]
    other = ids["other"]["items"][0]
    assert other["notifiable_type"] == "FlaggedContent" and other["allow_mark_read"] is False


def test_server_react_marks_read_and_logs(tmp_path) -> None:
    client = FakeClient(
        messages=[{
            "id": 9000002,
            "chat_room_participant_id": 5,
            "created_at": "2026-10-15T11:00:00.000Z",
            "rich_text_body": {
                "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "lesson msg"}]}]},
                "attachments": [],
            },
            "replies_count": 0,
            "reactions": [],
        }],
        participants=[{"id": 5, "name": "Cara", "community_member_id": 9}],
        badge=3,
    )
    notification = _room_notification(id=50)
    client.fetch_notifications = lambda: _doc([notification])  # type: ignore[method-assign]
    server = DashboardServer(
        {}, port=8999, state_dir=tmp_path, client=client
    )
    server.build_state()
    note = {"notification_id": 50, "kind": "chat_room_message", "target_id": 9000002, "unicode": "heart"}
    server.react(note)
    kinds = [c[0] for c in client.calls]
    assert kinds.count("create_reaction") == 1
    assert kinds.count("mark_read") == 1
    reaction_call = next(c for c in client.calls if c[0] == "create_reaction")[1]
    assert reaction_call == {"kind": "chat_room_message", "id": 9000002, "unicode": "2764-fe0f"}
    log_lines = (tmp_path / "dashboard_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(log_lines[0])
    assert entry["action"] == "react" and entry["marked_read"] is True


def test_server_react_without_notification_is_react_only(tmp_path) -> None:
    """Rows that are not unread-notification targets (e.g. older thread
    messages the user reads while triaging) get a reaction with no mark-read."""
    root = {
        "id": 9000002,
        "chat_room_participant_id": 5,
        "created_at": "2026-10-13T08:00:00.000Z",
        "rich_text_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "root"}]}]}, "attachments": []},
        "replies_count": 2,
        "reactions": [],
    }
    target_reply = {
        "id": 9000006,
        "parent_message_id": 9000002,
        "chat_room_participant_id": 6,
        "created_at": "2026-10-14T10:53:59.780Z",
        "rich_text_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "new homework"}]}]}, "attachments": []},
        "replies_count": 0,
        "reactions": [],
    }
    older_reply = {
        "id": 9000007,
        "parent_message_id": 9000002,
        "chat_room_participant_id": 6,
        "created_at": "2026-10-14T09:53:59.780Z",
        "rich_text_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "older note"}]}]}, "attachments": []},
        "replies_count": 0,
        "reactions": [],
    }
    client = FakeClient(
        messages=[root],
        replies=[target_reply, older_reply],
        participants=[{"id": 6, "name": "Drew", "community_member_id": 88}],
    )
    client.fetch_notifications = lambda: _doc([_room_notification(id=50)])  # type: ignore[method-assign]
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=client)
    server.build_state()
    server.react({"notification_id": None, "kind": "chat_room_message", "target_id": 9000007, "unicode": "heart"})
    assert ("create_reaction", {"kind": "chat_room_message", "id": 9000007, "unicode": "2764-fe0f"}) in client.calls
    assert not any(c[0] == "mark_read" for c in client.calls)
    with pytest.raises(ActionError) as excinfo:
        server.react({"notification_id": None, "kind": "chat_room_message", "target_id": 123456, "unicode": "heart"})
    assert excinfo.value.status == 404


def test_server_react_comment_kind_follows_the_gate(tmp_path) -> None:
    """Comment reactions open only once VERIFIED_REACTION_KINDS gains 'comment'
    (flipped after the live round-trip check; the default gate stays closed)."""
    client = FakeClient(comments=[_comment(3, parent=None)])
    client.fetch_notifications = lambda: _doc([_notification(id=1, notifiable_id=3)])  # type: ignore[method-assign]
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=client)
    server.verified_kinds = ("comment",)
    server.build_state()
    server.react({"notification_id": 1, "kind": "comment", "target_id": 3, "reaction_type": "love"})
    like_call = next(c for c in client.calls if c[0] == "create_comment_like")[1]
    assert like_call == {"id": 3, "reaction_type": "love"}


def test_server_react_gates_unverified_kinds(tmp_path) -> None:
    client = FakeClient()
    client.fetch_notifications = lambda: _doc([_room_notification(id=50)])  # type: ignore[method-assign]
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=client)
    server.verified_kinds = ()  # simulate the gate before verification
    with pytest.raises(ActionError) as excinfo:
        server.react({"notification_id": 50, "kind": "chat_room_message", "target_id": 9000002, "unicode": "heart"})
    assert excinfo.value.status == 409


def test_server_validate_target(tmp_path) -> None:
    client = FakeClient(comments=[_comment(3, parent=None)])
    client.fetch_notifications = lambda: _doc([_notification(id=1, notifiable_id=3), _notification(id=2, action="comment_mention", notifiable_id=3)])  # type: ignore[method-assign]
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=client)
    server.build_state()
    found = server._locate("comment", 3, notification_id=1)
    assert found["kind"] == "post"
    with pytest.raises(ActionError):
        server._locate("comment", 999, notification_id=1)


def test_react_invalidates_context_cache(tmp_path) -> None:
    root_msg = {
        "id": 9000002,
        "chat_room_participant_id": 5,
        "created_at": "2026-10-13T08:00:00.000Z",
        "rich_text_body": {"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "root"}]}]}, "attachments": []},
        "replies_count": 0,
        "reactions": [],
    }
    client = FakeClient(
        messages=[root_msg],
        participants=[{"id": 5, "name": "Drew", "community_member_id": 88}],
    )
    client.fetch_notifications = lambda: _doc([_room_notification(id=50)])  # type: ignore[method-assign]
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=client)
    server.build_state()

    def message_calls() -> int:
        return sum(1 for c in client.calls if c[0] == "list_chat_messages")

    assert message_calls() == 1
    server.react({"notification_id": 50, "kind": "chat_room_message", "target_id": 9000002, "unicode": "heart"})
    server.build_state()  # cache was invalidated for this context -> refetch
    assert message_calls() == 2


def _lesson_message_with_reactions(reactions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": 9000002,
        "chat_room_participant_id": 5,
        "created_at": "2026-10-15T11:00:00.000Z",
        "rich_text_body": {
            "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "lesson msg"}]}]},
            "attachments": [],
        },
        "replies_count": 0,
        "reactions": reactions,
    }


def test_verify_reads_back_reaction_after_react(tmp_path) -> None:
    """verify re-fetches the single context (react invalidated its cache) and
    returns the row's fresh reactions — read-back is the evidence, not the 200."""
    message = _lesson_message_with_reactions([])
    client = FakeClient(
        messages=[message],
        participants=[{"id": 5, "name": "Cara", "community_member_id": 9}],
    )
    client.fetch_notifications = lambda: _doc([_room_notification(id=50)])  # type: ignore[method-assign]

    def create_reaction_with_side_effect(kind: str, target_id: int, unicode_code: str, *, execute: bool = False) -> dict[str, Any]:
        assert execute is True
        client.calls.append(("create_reaction", {"kind": kind, "id": target_id, "unicode": unicode_code}))
        message["reactions"].append({"unicode": unicode_code, "count": 1})
        return {"success": True, "reactions": None}

    client.create_reaction = create_reaction_with_side_effect  # type: ignore[method-assign]
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=client)
    server.build_state()
    server.react({"notification_id": 50, "kind": "chat_room_message", "target_id": 9000002, "unicode": "heart"})

    def message_calls() -> int:
        return sum(1 for c in client.calls if c[0] == "list_chat_messages")

    before = message_calls()
    result = server.verify({"notification_id": 50, "kind": "chat_room_message", "target_id": 9000002})
    row = result["row"]
    assert row["id"] == 9000002
    assert row["is_target"] is True
    assert row["reactions"] == [{"unicode": "2764-fe0f", "emoji": None, "count": 1}]
    assert row["missing"] is False
    assert message_calls() == before + 1  # a real refetch, not a stale cache hit


def test_verify_is_read_only(tmp_path) -> None:
    client = FakeClient(
        messages=[_lesson_message_with_reactions([])],
        participants=[{"id": 5, "name": "Cara", "community_member_id": 9}],
    )
    client.fetch_notifications = lambda: _doc([_room_notification(id=50)])  # type: ignore[method-assign]
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=client)
    server.build_state()
    before = len(client.calls)
    server.verify({"notification_id": 50, "kind": "chat_room_message", "target_id": 9000002})
    new_calls = [name for name, _ in client.calls[before:] if name not in ("list_chat_messages", "participants")]
    assert new_calls == []
    assert not (tmp_path / "dashboard_log.jsonl").exists()  # read-back is not a logged action


def test_verify_gates_unverified_kinds(tmp_path) -> None:
    client = FakeClient()
    client.fetch_notifications = lambda: _doc([_room_notification(id=50)])  # type: ignore[method-assign]
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=client)
    server.verified_kinds = ()
    with pytest.raises(ActionError) as excinfo:
        server.verify({"notification_id": 50, "kind": "chat_room_message", "target_id": 9000002})
    assert excinfo.value.status == 409


def test_verify_unknown_target_404(tmp_path) -> None:
    client = FakeClient(
        messages=[_lesson_message_with_reactions([])],
        participants=[{"id": 5, "name": "Cara", "community_member_id": 9}],
    )
    client.fetch_notifications = lambda: _doc([_room_notification(id=50)])  # type: ignore[method-assign]
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=client)
    server.build_state()
    with pytest.raises(ActionError) as excinfo:
        server.verify({"notification_id": 50, "kind": "chat_room_message", "target_id": 123456})
    assert excinfo.value.status == 404


def test_server_state_persists_artifact(tmp_path) -> None:
    client = FakeClient()
    client.fetch_notifications = lambda: _doc([])  # type: ignore[method-assign]
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=client)
    state = server.build_state()
    assert state["count"] == 0
    assert (tmp_path / "dashboard.json").exists()


def test_assemble_state_orders_rooms_before_posts() -> None:
    client = FakeClient(
        comments=[_comment(3, parent=None, created="2026-10-15T10:00:00.000Z")],
        messages=[{
            "id": 9000002,
            "chat_room_participant_id": 5,
            "created_at": "2026-10-15T09:00:00.000Z",
            "rich_text_body": {
                "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "lesson msg"}]}]},
                "attachments": [],
            },
            "replies_count": 0,
            "reactions": [],
        }],
        participants=[{"id": 5, "name": "Cara", "community_member_id": 9}],
    )
    notifications = [
        _notification(id=1, notifiable_id=3, created_at="2026-10-15T10:00:00.000Z"),
        _room_notification(id=50, created_at="2026-10-15T09:00:00.000Z"),
    ]
    state = assemble_state(client, _doc(notifications), cache=DashboardCache(), verified_kinds=VERIFIED_REACTION_KINDS)
    contexts = state["sections"][0]["contexts"]
    assert [(c["kind"]) for c in contexts] == ["room", "post"]


def test_emotes_config_extends_and_warns(tmp_path) -> None:
    (tmp_path / "emotes.json").write_text(
        json.dumps({"clap": "1f44f", "bad": "not-a-code"}), encoding="utf-8"
    )
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=FakeClient())
    assert server.emotes["clap"] == "1f44f"
    assert server.emotes["heart"] == "2764-fe0f"
    assert server.emotes_warning and "bad" in server.emotes_warning
    state = server.build_state()
    glyphs = {e["name"]: e["glyph"] for e in state["emotes"]}
    assert "clap" in glyphs and "heart" in glyphs
    assert state["emotes_config_warning"]


def test_emotes_broken_file_falls_back(tmp_path) -> None:
    (tmp_path / "emotes.json").write_text("not json at all", encoding="utf-8")
    server = DashboardServer({}, port=8999, state_dir=tmp_path, client=FakeClient())
    assert server.emotes["heart"] == "2764-fe0f"
    assert server.emotes_warning


def test_server_state_has_no_credentials(tmp_path) -> None:
    client = FakeClient()
    client.fetch_notifications = lambda: _doc([_notification(id=1, notifiable_id=3)])  # type: ignore[method-assign]
    server = DashboardServer(
        {
            "notifications_url": "https://example.test/internal_api/notifications",
            "cookie": "session=secret-cookie",
            "csrf_token": "secret-csrf",
            "authorization": "Bearer secret-jwt",
        },
        port=8999,
        state_dir=tmp_path,
        client=client,
    )
    state = server.build_state()
    rendered = json.dumps(state, ensure_ascii=False)
    for secret in ("secret-cookie", "secret-csrf", "secret-jwt", "Bearer fake"):
        assert secret not in rendered


def test_http_endpoints(tmp_path) -> None:
    from circle_client_skill.dashboard import create_dashboard_server

    client = FakeClient()
    client.fetch_notifications = lambda: _doc([_notification(id=1)])  # type: ignore[method-assign]
    server, url = create_dashboard_server({}, port=0, state_dir=tmp_path, timeout=5, client=client)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # 401-style: /api/react without the dashboard Origin is rejected.
        req = urllib.request.Request(url + "api/react", method="POST", data=b"{}")
        try:
            urllib.request.urlopen(req)
            raise AssertionError("expected 403")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            assert resp.headers["Content-Type"].startswith("text/html")
            body = resp.read().decode("utf-8")
        assert "one-stop" in body and PAGE[:20] in body

        req = urllib.request.Request(url + "api/state")
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["success"] is True
        assert payload["state"]["verified_reaction_kinds"] == list(VERIFIED_REACTION_KINDS)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_react_roundtrip(tmp_path) -> None:
    from circle_client_skill.dashboard import create_dashboard_server

    client = FakeClient(comments=[_comment(3, parent=None)])
    document = _doc([_notification(id=1)])

    def fetch_with_content() -> dict[str, Any]:
        return document

    client.fetch_notifications = fetch_with_content  # type: ignore[method-assign]
    server, url = create_dashboard_server({}, port=0, state_dir=tmp_path, timeout=5, client=client)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        dashboard = server.dashboard
        assert dashboard.port == int(url.split(":")[-1].split("/")[0])
        # The page loads state before actions exist; replicate that here.
        with urllib.request.urlopen(url + "api/state") as resp:
            state = json.loads(resp.read().decode("utf-8"))
        assert state["success"] is True and state["state"]["count"] == 1
        req = urllib.request.Request(
            url + "api/mark_read",
            method="POST",
            data=json.dumps({"notification_id": 1}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{dashboard.port}",
            },
        )
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["success"] is True and payload["marked_read"] is True
        assert ("mark_read", {"id": 1}) in client.calls
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_verify_roundtrip(tmp_path) -> None:
    from circle_client_skill.dashboard import create_dashboard_server

    client = FakeClient(
        messages=[_lesson_message_with_reactions([])],
        participants=[{"id": 5, "name": "Cara", "community_member_id": 9}],
    )
    client.fetch_notifications = lambda: _doc([_room_notification(id=50)])  # type: ignore[method-assign]
    server, url = create_dashboard_server({}, port=0, state_dir=tmp_path, timeout=5, client=client)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        dashboard = server.dashboard
        with urllib.request.urlopen(url + "api/state") as resp:
            state = json.loads(resp.read().decode("utf-8"))
        assert state["success"] is True
        body = json.dumps({"notification_id": 50, "kind": "chat_room_message", "target_id": 9000002}).encode()
        req = urllib.request.Request(
            url + "api/verify",
            method="POST",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{dashboard.port}",
            },
        )
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["success"] is True
        assert payload["row"]["id"] == 9000002 and payload["row"]["is_target"] is True
        bad = urllib.request.Request(
            url + "api/verify",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json", "Origin": "http://evil.example.com"},
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(bad)
        assert excinfo.value.code == 403
    finally:
        server.shutdown()
        thread.join(timeout=5)


def urlsplit_port(url: str) -> str:
    return url.rsplit(":", 1)[1].rstrip("/")