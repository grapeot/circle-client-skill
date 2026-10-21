from __future__ import annotations

from circle_client_skill.normalize import category_for_notification, normalize_notification


def test_normalization_supports_live_circle_field_names() -> None:
    row = normalize_notification(
        {
            "id": 7,
            "actor_name": "Alice",
            "display_action": "posted a comment in",
            "notifiable_title": "General",
            "action": "comment",
            "action_web_url": "https://community.example.com/post/1",
            "created_at": "2026-01-01T00:00:00Z",
            "read_at": None,
        }
    )

    assert row["id"] == "7"
    assert row["status"] == "未读"
    assert row["actor"] == "Alice"
    assert row["summary"] == "Alice posted a comment in General"
    assert row["url"] == "https://community.example.com/post/1"


def test_normalization_prefers_explicit_read_flag_and_body() -> None:
    row = normalize_notification(
        {
            "is_read": True,
            "actor": {"name": "Bob"},
            "title": "A title",
            "body": "line one\nline two",
            "url": "/post/2",
        }
    )

    assert row["status"] == "已读"
    assert row["summary"] == "Bob A title: line one\nline two"
    assert row["url"] == "/post/2"


def test_category_routes_notification_kinds() -> None:
    assert (
        category_for_notification({"title": "Alice posted a comment on your lesson"})
        == "lesson_comments"
    )
    assert category_for_notification({"title": "Bob posted a comment in General"}) == "comments"
    assert category_for_notification({"title": "Carol liked your post"}) == "likes"
    assert category_for_notification({"title": "Dan joined the community"}) == "members"
    assert category_for_notification({"title": "Something else happened"}) == "other"
