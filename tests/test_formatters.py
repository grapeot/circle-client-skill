from __future__ import annotations

from circle_client_skill.formatters import (
    format_auth_status,
    format_chat_messages_table,
    format_count,
    format_fetch_summary,
    format_mutation_dryrun,
    format_mutation_result,
    format_post_card,
    format_posts_table,
    format_space_card,
    format_spaces_table,
    format_unreplied_table,
)

TIPTAP = {
    "body": {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Hello "}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "world"}]},
        ],
    }
}


def test_format_spaces_table() -> None:
    output = format_spaces_table(
        [{
            "id": 12,
            "name": "A" * 40,
            "slug": "general",
            "post_type": "basic",
            "posts_count": 3,
            "members_count": 8,
            "space_group": {"name": "Public"},
            "is_private": True,
        }]
    )
    assert output.startswith("ID  NAME")
    assert "AAA..." in output
    assert "priv" in output


def test_format_space_card() -> None:
    output = format_space_card(
        {
            "id": 12,
            "name": "Support",
            "slug": "support",
            "post_type": "chat",
            "space_group_name": "Public",
            "posts_count": 0,
            "members_count": 30,
            "chat_room_id": 99,
            "chat_room_uuid": "fake-room-uuid",
            "is_chat_participant": False,
        }
    )
    assert output.startswith("# Support  (id=12)")
    assert "chat_room_uuid: fake-room-uuid" in output
    assert "is_chat_participant: false" in output


def test_format_posts_table_compact_and_full() -> None:
    post = {
        "id": 1,
        "name": "Intro",
        "slug": "intro",
        "published_at": "2026-01-01T00:00:00Z",
        "community_member_id": 7,
        "topics": [{"name": "AI"}],
        "tiptap_body": TIPTAP,
    }
    assert "TOPICS" not in format_posts_table([post], False)
    full = format_posts_table([post], True)
    assert "TOPICS" in full
    assert "Hello world" in full


def test_format_posts_table_replies_column_only_when_counts_present() -> None:
    base = {
        "id": 1,
        "name": "Intro",
        "slug": "intro",
        "published_at": "2026-01-01T00:00:00Z",
        "community_member_id": 7,
    }
    # 无 comments_count -> 不出 REPLIES 列
    without = format_posts_table([{**base, "topics": []}], False)
    assert "REPLIES" not in without
    # 有 comments_count -> 出 REPLIES 列且数值正确
    with_counts = format_posts_table([{**base, "comments_count": 3, "topics": []}], False)
    assert "REPLIES" in with_counts
    assert "3" in with_counts
    # 混合时缺失 count 显示空
    mixed = format_posts_table(
        [{**base, "comments_count": 3, "topics": []}, {**base, "id": 2, "comments_count": None, "topics": []}],
        False,
    )
    assert "REPLIES" in mixed


def test_format_post_card_extracts_tiptap_text() -> None:
    output = format_post_card(
        {
            "id": 1,
            "name": "Intro",
            "slug": "intro",
            "space_id": 12,
            "space_name": "General",
            "published_at": "2026-01-01T00:00:00Z",
            "community_member_id": 7,
            "comments_count": 2,
            "likes_count": 4,
            "tiptap_body": TIPTAP,
        }
    )
    assert "space: General (12)" in output
    assert "replies: 2   likes: 4" in output
    assert "\nHello world\n" in output


def test_format_chat_messages_table_includes_pagination() -> None:
    output = format_chat_messages_table(
        [{
            "id": 10,
            "created_at": "2026-07-02T03:58:12Z",
            "chat_room_participant_id": 20,
            "replies_count": 2,
            "rich_text_body": TIPTAP,
        }],
        {
            "total_count": 4,
            "first_id": 10,
            "last_id": 13,
            "has_previous_page": True,
            "has_next_page": False,
        },
    )
    assert output.startswith("total: 4   page: first=10 last=13 has_prev=true has_next=false")
    assert "AUTHOR_PID" in output
    assert "Hello world" in output


def test_format_count() -> None:
    assert format_count(131) == "131"


def test_format_auth_status() -> None:
    output = format_auth_status(
        {
            "configured": True,
            "host": "community.example.com",
            "cookie_present": True,
            "csrf_present": True,
            "jwt_present": False,
        }
    )
    assert output == (
        "configured: yes   host: community.example.com\n"
        "cookie: yes   csrf: yes   jwt: no"
    )


def test_format_fetch_summary() -> None:
    output = format_fetch_summary(
        {
            "count": 5,
            "host": "community.example.com",
            "pages_fetched": 2,
            "per_page": 100,
            "output": "data/notifications.json",
        }
    )
    assert output == (
        "Fetched 5 unread notifications from community.example.com\n"
        "pages: 2   per_page: 100   saved: data/notifications.json"
    )


def test_format_mutation_dryrun() -> None:
    output = format_mutation_dryrun(
        {
            "success": True,
            "dry_run": True,
            "operation": "create_post",
            "space_id": 12,
            "name": "Test",
            "csrf_present": True,
            "cookie_present": True,
        }
    )
    assert output.startswith("DRY-RUN: create-post")
    assert 'name: "Test"' in output
    assert "csrf: present" in output
    assert output.endswith("--confirm CREATE-POST to perform.")
    reset = format_mutation_dryrun(
        {"operation": "reset_notification_count", "dry_run": True, "csrf_present": True}
    )
    assert reset.endswith("--confirm RESET-COUNT to perform.")


def test_format_mutation_result() -> None:
    output = format_mutation_result(
        {"post": {"id": 123, "name": "Test", "space_id": 12}},
        "create-post",
    )
    assert output == 'OK: created post #123 "Test" in space 12'


def test_format_unreplied_table() -> None:
    output = format_unreplied_table(
        [{
            "id": 10,
            "created_at": "2026-08-05T19:11:22Z",
            "replies_count": 1,
            "thread_participants_preview": [{"name": "Alice"}],
            "body": {"content": [{"type": "text", "text": "Need help"}]},
        }]
    )
    assert output.startswith("ID  CREATED_AT")
    assert "[Alice]" in output
    assert "Need help" in output
