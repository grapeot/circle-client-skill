from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from circle_client_skill import cli
from circle_client_skill.client import CircleClient
from circle_client_skill.config import CircleSettings
from circle_client_skill.formatters import (
    format_comment_threads,
    format_course_lessons,
    format_lesson_card,
)


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.payload = payload
        self.text = "" if payload is None else str(payload)

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
        notifications_url="https://community.example.com/internal_api/notifications",
        count_url="https://community.example.com/internal_api/notifications/new_notifications_count",
        reset_count_url="https://community.example.com/internal_api/notifications/mark_all_as_read",
        authorization="Bearer fake",
        cookie="session=fake",
        csrf_token="fake-csrf",
        origin="https://community.example.com",
    )


def test_get_course_lesson_uses_sectioned_url() -> None:
    session = FakeSession()
    session.set_response(
        "GET https://community.example.com/internal_api/courses/9000000/sections/9000001/lessons/9000002",
        FakeResponse({"id": 9000002, "name": "Lesson", "chat_room_uuid": "fake-room-uuid"}),
    )
    result = CircleClient(_settings(), session=session).get_course_lesson(9000000, 9000001, 9000002)
    assert result["chat_room_uuid"] == "fake-room-uuid"
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"].startswith(
        "https://community.example.com/internal_api/courses/9000000/sections/9000001/lessons/9000002"
    )


def test_format_course_lessons_renders_sections_and_lessons() -> None:
    sections = [
        {
            "id": 9000001,
            "name": "Section One",
            "is_dripped": True,
            "lessons": [
                {"id": 9000002, "name": "Lesson A", "content_kind": "lesson", "completed": False},
                {"id": 9000003, "name": "Lesson B", "content_kind": "lesson", "completed": True},
            ],
        },
        {"id": 9000004, "name": "Section Two", "is_dripped": False, "lessons": []},
    ]
    text = format_course_lessons(sections)
    assert "SECTION" in text and "LESSON" in text
    assert "9000001" in text and "9000002" in text
    assert "Lesson A" in text and "Lesson B" in text
    assert text.count("yes") >= 2


def test_format_lesson_card_uses_fallback_text_files_and_room() -> None:
    lesson = {
        "id": 9000002,
        "name": "Lesson A",
        "status": "published",
        "completed": True,
        "is_dripped": False,
        "featured_media_enabled": True,
        "comments_enabled": True,
        "chat_room_uuid": "fake-room-uuid",
        "rich_text_body": {
            "circle_ios_fallback_text": "Lesson body text",
            "attachments": [
                {"filename": "slide.png", "content_type": "image/png"},
                {"content_type": "image/png"},
            ],
        },
    }
    text = format_lesson_card(lesson)
    assert "fake-room-uuid" in text
    assert "Lesson body text" in text
    assert "slide.png" in text
    assert "completed: true" in text


def test_format_lesson_card_falls_back_to_body_text() -> None:
    lesson = {
        "id": 9000002,
        "name": "Lesson A",
        "rich_text_body": {
            "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "raw body"}]}]}
        },
    }
    assert "raw body" in format_lesson_card(lesson)


def test_format_comment_threads_skips_empty() -> None:
    threads = {
        101: [{"id": 201, "created_at": "2026-01-01T00:00:00Z", "body": "reply one"}],
        102: [],
    }
    text = format_comment_threads(threads)
    assert "thread 101" in text
    assert "reply one" in text
    assert "thread 102" not in text
    assert format_comment_threads({}) == ""


def test_course_lessons_command_requires_course_space(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def get_space(self, space_id: int) -> dict:
            return {"id": space_id, "course_sections": None}

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = argparse.Namespace(env_file="unused.env", timeout=30, space_id=12, json=True)
    with pytest.raises(ValueError, match="no course_sections"):
        cli.cmd_course_lessons(args)


def test_lesson_comments_resolves_room_newest_first_and_threads(monkeypatch, capsys) -> None:
    reply_calls: list[int] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def get_course_lesson(self, space_id: int, section_id: int, lesson_id: int) -> dict:
            assert (space_id, section_id, lesson_id) == (9000000, 9000001, 9000002)
            return {"id": lesson_id, "name": "Lesson A", "chat_room_uuid": "fake-room-uuid"}

        def list_chat_messages(
            self,
            chat_room_uuid: str,
            *,
            previous_per_page: int,
            next_per_page: int,
            cursor: int | None = None,
        ) -> dict:
            assert chat_room_uuid == "fake-room-uuid"
            return {
                "total_count": 2,
                "first_id": 10,
                "last_id": 20,
                "has_previous_page": False,
                "has_next_page": False,
                "records": [
                    {"id": 10, "created_at": "2026-01-01T00:00:00Z", "body": "older", "replies_count": 2},
                    {"id": 20, "created_at": "2026-01-02T00:00:00Z", "body": "newer", "replies_count": 0},
                ],
            }

        def fetch_chat_replies(
            self,
            room_uuid: str,
            parent_message_id: int,
            *,
            previous_per_page: int = 0,
            next_per_page: int = 50,
            cursor: int | None = None,
        ) -> dict:
            assert room_uuid == "fake-room-uuid"
            reply_calls.append(parent_message_id)
            return {"records": [{"id": 101, "body": "r1"}, {"id": 102, "body": "r2"}]}

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = argparse.Namespace(
        env_file="unused.env",
        timeout=30,
        space_id=9000000,
        section_id=9000001,
        lesson_id=9000002,
        cursor=None,
        direction="previous",
        previous_per_page=20,
        next_per_page=0,
        with_threads=True,
        threads_per_page=50,
        json=True,
    )

    cli.cmd_lesson_comments(args)

    output = json.loads(capsys.readouterr().out)
    assert output["chat_room_uuid"] == "fake-room-uuid"
    assert [root["id"] for root in output["roots"]] == [20, 10]
    assert output["first_id"] == 10
    assert output["last_id"] == 20
    assert output["has_previous_page"] is False
    assert list(output["threads"].keys()) == ["10"]
    assert len(output["threads"]["10"]) == 2
    assert reply_calls == [10]


def test_lesson_comments_truncates_when_server_ignores_per_page(monkeypatch, capsys) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def get_course_lesson(self, space_id: int, section_id: int, lesson_id: int) -> dict:
            return {"id": lesson_id, "chat_room_uuid": "fake-room-uuid"}

        def list_chat_messages(self, chat_room_uuid: str, **_: Any) -> dict:
            return {
                "total_count": 5,
                "first_id": 1,
                "last_id": 5,
                "has_previous_page": False,
                "has_next_page": False,
                "records": [
                    {
                        "id": index,
                        "created_at": f"2026-01-{index:02d}T00:00:00Z",
                        "body": f"m{index}",
                        "replies_count": 0,
                    }
                    for index in range(1, 6)
                ],
            }

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = argparse.Namespace(
        env_file="unused.env",
        timeout=30,
        space_id=9000000,
        section_id=9000001,
        lesson_id=9000002,
        cursor=None,
        direction="previous",
        previous_per_page=2,
        next_per_page=0,
        with_threads=False,
        threads_per_page=50,
        json=True,
    )

    cli.cmd_lesson_comments(args)

    output = json.loads(capsys.readouterr().out)
    assert [root["id"] for root in output["records"]] == [5, 4]


def test_lesson_comments_without_threads_makes_single_request(monkeypatch, capsys) -> None:
    calls: dict[str, int] = {}

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def get_course_lesson(self, space_id: int, section_id: int, lesson_id: int) -> dict:
            calls["lesson"] = 1
            return {"id": lesson_id, "chat_room_uuid": "fake-room-uuid"}

        def list_chat_messages(self, chat_room_uuid: str, **_: Any) -> dict:
            calls["messages"] = 1
            return {
                "total_count": 1,
                "records": [{"id": 10, "created_at": "2026-01-01T00:00:00Z", "body": "only", "replies_count": 3}],
            }

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = argparse.Namespace(
        env_file="unused.env",
        timeout=30,
        space_id=9000000,
        section_id=9000001,
        lesson_id=9000002,
        cursor=None,
        direction="previous",
        previous_per_page=20,
        next_per_page=0,
        with_threads=False,
        threads_per_page=50,
        json=True,
    )

    cli.cmd_lesson_comments(args)

    assert calls == {"lesson": 1, "messages": 1}
    output = json.loads(capsys.readouterr().out)
    assert "threads" not in output


def test_lesson_comments_rejects_lesson_without_room(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        def get_course_lesson(self, space_id: int, section_id: int, lesson_id: int) -> dict:
            return {"id": lesson_id, "comments_enabled": False, "chat_room_uuid": None}

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = argparse.Namespace(
        env_file="unused.env",
        timeout=30,
        space_id=9000000,
        section_id=9000001,
        lesson_id=9000002,
        cursor=None,
        direction="previous",
        previous_per_page=20,
        next_per_page=0,
        with_threads=False,
        threads_per_page=50,
        json=True,
    )
    with pytest.raises(ValueError, match="no discussion room"):
        cli.cmd_lesson_comments(args)


def test_course_parser_defaults() -> None:
    parser = cli.build_parser()
    lessons = parser.parse_args(["course-lessons", "-s", "9000000", "--json"])
    assert lessons.space_id == 9000000
    assert lessons.json is True

    lesson = parser.parse_args(
        ["course-lesson", "-s", "9000000", "--section-id", "9000001", "--lesson-id", "9000002", "--json"]
    )
    assert lesson.section_id == 9000001 and lesson.lesson_id == 9000002
    assert lesson.json is True

    comments = parser.parse_args(
        ["lesson-comments", "-s", "9000000", "--section-id", "9000001", "--lesson-id", "9000002", "--json"]
    )
    assert comments.direction == "previous"
    assert comments.previous_per_page == 20
    assert comments.next_per_page == 0
    assert comments.with_threads is False
    assert comments.json is True
