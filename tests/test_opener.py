from __future__ import annotations

import subprocess

import pytest

from circle_client_skill.opener import (
    is_openable,
    open_sequentially,
    plan_targets,
    resolve_url,
)

DOCUMENT = {
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
            "action": "comment_mention",
            "notifiable_title": "Alice posted a comment on your lesson",
            "action_web_url": "https://community.example.com/c/ai/lessons/1#message_11",
        },
        {
            "id": 3,
            "created_at": "2026-01-03T00:00:00Z",
            "action": "course_comment",
            "notifiable_title": "Bob posted a comment on your lesson",
            "action_web_url": "https://community.example.com/c/coding/lessons/2#message_22",
        },
        {
            "id": 4,
            "created_at": "2026-01-04T00:00:00Z",
            "action": "comment",
            "notifiable_title": "Carol posted a comment in General",
            "action_web_url": "https://community.example.com/post/3",
        },
        {
            "id": 5,
            "created_at": "2026-01-05T00:00:00Z",
            "action": "comment",
            "notifiable_title": "Mallory posted a comment in Offsite",
            "action_web_url": "https://evil.example.com/post/9",
        },
    ],
}


def test_plan_targets_filters_category_and_dedupes() -> None:
    plan = plan_targets(DOCUMENT, category="lesson_comments")

    assert plan["available"] == 3
    assert plan["targets"] == [
        {"url": "https://community.example.com/c/coding/lessons/2#message_22",
         "category": "lesson_comments", "created_at": "2026-01-03T00:00:00Z"},
        {"url": "https://community.example.com/c/ai/lessons/1#message_11",
         "category": "lesson_comments", "created_at": "2026-01-02T00:00:00Z"},
    ]


def test_plan_targets_no_dedupe_keeps_duplicates() -> None:
    plan = plan_targets(DOCUMENT, category="lesson_comments", dedupe=False)
    assert len(plan["targets"]) == 3


def test_plan_targets_drops_offhost_url() -> None:
    plan = plan_targets(DOCUMENT, category="comments")
    assert [target["url"] for target in plan["targets"]] == [
        "https://community.example.com/post/3"
    ]
    assert plan["skipped"] == [{"url": "https://evil.example.com/post/9",
                                "reason": "url not on the community host"}]


def test_plan_targets_orders_oldest_first() -> None:
    plan = plan_targets(DOCUMENT, category="lesson_comments", order="oldest")
    assert [target["created_at"] for target in plan["targets"]] == [
        "2026-01-01T00:00:00Z",
        "2026-01-03T00:00:00Z",
    ]


def test_plan_targets_rejects_unknown_category() -> None:
    with pytest.raises(ValueError):
        plan_targets(DOCUMENT, category="nope")


def test_resolve_url_and_is_openable() -> None:
    assert resolve_url("/post/1", "community.example.com") == "https://community.example.com/post/1"
    assert resolve_url("https://community.example.com/post/1", "x") == "https://community.example.com/post/1"
    assert resolve_url("ftp://community.example.com/x", "community.example.com") == ""
    assert resolve_url("", "community.example.com") == ""
    assert is_openable("https://community.example.com/post/1", "community.example.com")
    assert not is_openable("https://evil.example.com/post/1", "community.example.com")
    assert not is_openable("ftp://community.example.com/post/1", "community.example.com")
    assert is_openable("https://anywhere.example.com/x", "")


def test_open_sequentially_calls_opener_and_sleeps_between() -> None:
    commands: list[list[str]] = []
    sleeps: list[float] = []

    def fake_run(command, check):
        commands.append(command)
        assert check is True

    result = open_sequentially(
        [{"url": "https://a/1"}, {"url": "https://a/2"}, {"url": "https://a/3"}],
        interval=2.5,
        opener="/usr/bin/open",
        sleep=sleeps.append,
        run=fake_run,
    )

    assert commands == [
        ["/usr/bin/open", "https://a/1"],
        ["/usr/bin/open", "https://a/2"],
        ["/usr/bin/open", "https://a/3"],
    ]
    assert sleeps == [2.5, 2.5]
    assert result["opened"] == 3
    assert result["failed"] == 0


def test_open_sequentially_background_uses_dash_g() -> None:
    commands: list[list[str]] = []

    open_sequentially(
        [{"url": "https://a/1"}],
        interval=0,
        opener="/usr/bin/open",
        background=True,
        sleep=lambda _seconds: None,
        run=lambda command, check: commands.append(command),
    )

    assert commands == [["/usr/bin/open", "-g", "https://a/1"]]


def test_open_sequentially_records_failures_and_continues() -> None:
    commands: list[list[str]] = []

    def fake_run(command, check):
        commands.append(command)
        if command[-1].endswith("/2"):
            raise subprocess.CalledProcessError(returncode=1, cmd=command)

    result = open_sequentially(
        [{"url": "https://a/1"}, {"url": "https://a/2"}, {"url": "https://a/3"}],
        interval=0,
        opener="/usr/bin/open",
        sleep=lambda _seconds: None,
        run=fake_run,
    )

    assert result["opened"] == 2
    assert result["failed"] == 1
    assert result["failures"][0]["url"] == "https://a/2"
    assert len(commands) == 3
