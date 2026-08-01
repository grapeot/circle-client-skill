from __future__ import annotations

import csv
from pathlib import Path

from circle_client_skill.render import (
    category_for_notification,
    render_csv,
    render_html,
    render_markdown,
)

DOCUMENT = {
    "fetched_at": "2026-01-01T00:00:00+00:00",
    "source": {"notification_group": "inbox"},
    "notifications": [
        {
            "id": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "notification_type": "mention",
            "actor": {"name": "Alice"},
            "title": "A | title",
            "body": "line one\nline two",
            "url": "https://community.example.com/post/1",
            "read_at": None,
        }
    ],
}


def test_render_markdown_is_readable_and_escapes_table_cells() -> None:
    output = render_markdown(DOCUMENT)

    assert "Count: **1**" in output
    assert "A \\| title" in output
    assert "line one<br>line two" in output
    assert "[Open](https://community.example.com/post/1)" in output


def test_render_csv_uses_stable_columns(tmp_path: Path) -> None:
    output = tmp_path / "notifications.csv"
    render_csv(DOCUMENT, output)

    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["actor"] == "Alice"
    assert rows[0]["status"] == "未读"


def test_html_groups_and_folds_low_priority_categories() -> None:
    document = {
        **DOCUMENT,
        "source": {"host": "community.example.com", "notification_group": "inbox"},
        "notifications": [
            {"title": "Alice posted a comment on your lesson", "path": "/lesson/1"},
            {"title": "Bob posted a comment in General", "path": "/post/2"},
            {"title": "Carol liked your post", "path": "/post/3"},
            {"title": "Dan joined the community"},
        ],
    }

    output = render_html(document)

    assert 'class=" category highlight" open' in output
    assert "Post likes" in output
    assert "New members" in output
    assert 'href="https://community.example.com/lesson/1"' in output
    assert category_for_notification(document["notifications"][2]) == "likes"
    assert "visitedInThisPage" in output
    assert "classList.add('is-visited')" in output
    assert "localStorage" not in output
    assert "sessionStorage" not in output


def test_normalization_supports_live_circle_field_names() -> None:
    document = {
        "fetched_at": "2026-01-01T00:00:00Z",
        "source": {"host": "community.example.com", "notification_group": "inbox"},
        "notifications": [
            {
                "actor_name": "Alice",
                "display_action": "posted a comment in",
                "notifiable_title": "General",
                "action": "comment",
                "action_web_url": "https://community.example.com/post/1",
                "read_at": None,
            }
        ],
    }

    output = render_html(document)
    assert "Alice posted a comment in General" in output
    assert 'href="https://community.example.com/post/1"' in output
