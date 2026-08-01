from __future__ import annotations

from typing import Any

from circle_client_skill.client import CircleClient
from circle_client_skill.config import CircleSettings


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str, **_: Any) -> FakeResponse:
        self.calls.append(url)
        page = len(self.calls)
        return FakeResponse(
            {
                "notifications": [{"id": page, "title": f"Notification {page}"}],
                "has_next_page": page == 1,
            }
        )


def test_fetch_follows_explicit_pagination() -> None:
    settings = CircleSettings(
        notifications_url="https://community.example.com/internal_api/notifications",
        count_url="https://community.example.com/internal_api/notifications/new_notifications_count",
        reset_count_url="https://community.example.com/internal_api/notifications/mark_all_as_read",
        authorization="Bearer fake",
    )
    session = FakeSession()

    result = CircleClient(settings, session=session).fetch_notifications(per_page=100)

    assert result["count"] == 2
    assert result["source"]["unread_only"] is True
    assert result["source"]["records_scanned"] == 2
    assert result["source"]["pages_fetched"] == 2
    assert "per_page=100" in session.calls[0]
    assert "page=2" in session.calls[1]


def test_fetch_stops_at_consecutive_read_frontier() -> None:
    settings = CircleSettings(
        notifications_url="https://community.example.com/internal_api/notifications",
        count_url="https://community.example.com/internal_api/notifications/new_notifications_count",
        reset_count_url="https://community.example.com/internal_api/notifications/mark_all_as_read",
        authorization="Bearer fake",
    )

    class ReadFrontierSession:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, *_: Any, **__: Any) -> FakeResponse:
            self.calls += 1
            return FakeResponse(
                {
                    "records": [
                        {"id": 1, "read_at": None},
                        {"id": 2, "read_at": "2026-01-01T00:00:00Z"},
                        {"id": 3, "read_at": "2026-01-01T00:00:01Z"},
                        {"id": 4, "read_at": None},
                    ],
                    "has_next_page": True,
                }
            )

    session = ReadFrontierSession()
    result = CircleClient(settings, session=session).fetch_notifications(
        stop_after_consecutive_read=2
    )

    assert result["count"] == 1
    assert result["source"]["records_scanned"] == 3
    assert result["source"]["stop_reason"] == "consecutive_read_threshold"
    assert session.calls == 1


def test_count_extracts_nested_count() -> None:
    settings = CircleSettings(
        notifications_url="https://community.example.com/internal_api/notifications",
        count_url="https://community.example.com/internal_api/notifications/new_notifications_count",
        reset_count_url="https://community.example.com/internal_api/notifications/mark_all_as_read",
        authorization="Bearer fake",
    )

    class CountSession:
        def get(self, *_: Any, **__: Any) -> FakeResponse:
            return FakeResponse({"data": {"new_notifications_count": 42}})

    result = CircleClient(settings, session=CountSession()).get_notification_count()
    assert result["count"] == 42


def test_reset_count_is_dry_run_by_default_and_posts_only_when_executed() -> None:
    settings = CircleSettings(
        notifications_url="https://community.example.com/internal_api/notifications",
        count_url="https://community.example.com/internal_api/notifications/new_notifications_count",
        reset_count_url="https://community.example.com/internal_api/notifications/mark_all_as_read",
        authorization="Bearer fake",
        cookie="session=fake",
        csrf_token="fake-csrf",
        origin="https://community.example.com",
    )

    class MutationSession:
        def __init__(self) -> None:
            self.posts = 0

        def post(self, *_: Any, **kwargs: Any) -> FakeResponse:
            self.posts += 1
            assert kwargs["headers"]["X-CSRF-Token"] == "fake-csrf"
            return FakeResponse({"success": True})

    session = MutationSession()
    client = CircleClient(settings, session=session)

    preflight = client.reset_notification_count()
    assert preflight["dry_run"] is True
    assert session.posts == 0

    result = client.reset_notification_count(execute=True)
    assert result["dry_run"] is False
    assert session.posts == 1
