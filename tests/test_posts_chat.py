from __future__ import annotations

from typing import Any

from circle_client_skill.client import CircleClient, CircleClientError
from circle_client_skill.config import CircleSettings


class FakeResponse:
    def __init__(
        self,
        payload: Any,
        status_code: int = 200,
        text: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.payload = payload
        self.text = text if text is not None else (
            "" if payload is None else str(payload)
        )

    def json(self) -> Any:
        return self.payload


class FakeSession:
    """Records all requests and returns configurable responses."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses: dict[str, FakeResponse] = {}
        self._default_response = FakeResponse({})

    def set_response(self, method_url: str, response: FakeResponse) -> None:
        self._responses[method_url] = response

    def _match(self, method: str, url: str) -> FakeResponse:
        # Try exact match first, then match by method + path (ignore query)
        key = f"{method} {url}"
        if key in self._responses:
            return self._responses[key]
        # Strip query string for matching
        base = url.split("?")[0]
        key2 = f"{method} {base}"
        return self._responses.get(key2, self._default_response)

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self._match(method, url)

    def get(self, url: str, **_: Any) -> FakeResponse:
        return self.request("GET", url)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("PUT", url, **kwargs)


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


def test_list_spaces() -> None:
    session = FakeSession()
    session.set_response(
        "GET https://community.example.com/internal_api/spaces",
        FakeResponse({"records": [{"id": 1, "name": "General"}, {"id": 2, "name": "Q&A"}]}),
    )
    result = CircleClient(_settings(), session=session).list_spaces()
    assert len(result["records"]) == 2
    assert result["records"][0]["name"] == "General"


def test_list_posts() -> None:
    session = FakeSession()
    session.set_response(
        "GET https://community.example.com/internal_api/spaces/1420182/posts",
        FakeResponse({"records": [{"id": 1, "name": "Test"}], "count": 1, "has_next_page": False}),
    )
    result = CircleClient(_settings(), session=session).list_posts(space_id=1420182, per_page=5)
    assert result["count"] == 1
    assert result["records"][0]["name"] == "Test"
    assert "per_page=5" in session.calls[0]["url"]


def test_create_post_dry_run_not_supported_offline() -> None:
    session = FakeSession()
    session.set_response(
        "POST https://community.example.com/internal_api/spaces/1420182/posts",
        FakeResponse({"id": 99, "name": "New Post", "slug": "new-post"}),
    )
    result = CircleClient(_settings(), session=session).create_post(
        space_id=1420182, name="New Post", user_id=21622670
    )
    assert result["id"] == 99
    body = session.calls[0]["json"]
    assert body["post"]["name"] == "New Post"
    assert body["post"]["space_id"] == 1420182
    assert body["post"]["status"] == "published"


def test_update_post_sends_patch() -> None:
    session = FakeSession()
    session.set_response(
        "PATCH https://community.example.com/internal_api/spaces/1420182/posts/my-slug",
        FakeResponse({"id": 99, "name": "Updated"}),
    )
    result = CircleClient(_settings(), session=session).update_post(
        space_id=1420182, slug="my-slug", post_id=99, name="Updated", user_id=21622670
    )
    assert result["name"] == "Updated"
    assert session.calls[0]["method"] == "PATCH"


def test_delete_post() -> None:
    session = FakeSession()
    session.set_response(
        "DELETE https://community.example.com/internal_api/spaces/1420182/posts/my-slug",
        FakeResponse(None, status_code=204, text=""),
    )
    result = CircleClient(_settings(), session=session).delete_post(space_id=1420182, slug="my-slug")
    assert result is None
    assert session.calls[0]["method"] == "DELETE"


def test_create_comment() -> None:
    session = FakeSession()
    session.set_response(
        "POST https://community.example.com/internal_api/posts/35204785/comments",
        FakeResponse({"id": 111192065, "post_id": 35204785}, status_code=201),
    )
    result = CircleClient(_settings(), session=session).create_comment(
        post_id=35204785, text="Test reply"
    )
    assert result["id"] == 111192065
    body = session.calls[0]["json"]
    assert body["comment"]["tiptap_body"]["body"]["content"][0]["content"][0]["text"] == "Test reply"


def test_create_comment_with_parent() -> None:
    session = FakeSession()
    session.set_response(
        "POST https://community.example.com/internal_api/posts/35204785/comments",
        FakeResponse({"id": 222}, status_code=201),
    )
    CircleClient(_settings(), session=session).create_comment(
        post_id=35204785, text="Nested reply", parent_comment_id=111192065
    )
    body = session.calls[0]["json"]
    assert body["comment"]["parent_comment_id"] == 111192065


def test_get_post_details() -> None:
    session = FakeSession()
    session.set_response(
        "GET https://community.example.com/internal_api/post_details",
        FakeResponse([{"id": 1, "policies": {"can_manage_post": True}}]),
    )
    result = CircleClient(_settings(), session=session).get_post_details([1, 2], space_id=1420182)
    assert len(result) == 1
    assert result[0]["policies"]["can_manage_post"] is True
    assert "post_ids=1%2C2" in session.calls[0]["url"] or "post_ids=1,2" in session.calls[0]["url"]


def test_send_chat_message() -> None:
    session = FakeSession()
    session.set_response(
        "POST https://community.example.com/internal_api/chat_rooms/abc-123/messages",
        FakeResponse({"id": 999}, status_code=202),
    )
    result = CircleClient(_settings(), session=session).send_chat_message(
        chat_room_uuid="abc-123", chat_room_participant_id=1133006966, text="Hello chat"
    )
    assert result["id"] == 999
    body = session.calls[0]["json"]
    assert body["chat_room_message"]["chat_room_participant_id"] == 1133006966


def test_send_chat_thread_reply() -> None:
    session = FakeSession()
    session.set_response(
        "POST https://community.example.com/internal_api/chat_rooms/abc-123/messages",
        FakeResponse({"creation_uuid": "test-uuid", "parent_message_id": 999}, status_code=202),
    )
    CircleClient(_settings(), session=session).send_chat_message(
        chat_room_uuid="abc-123",
        chat_room_participant_id=1133006966,
        text="Thread reply",
        parent_message_id=999,
    )
    body = session.calls[0]["json"]
    assert body["chat_room_message"]["parent_message_id"] == 999


def test_list_chat_messages() -> None:
    session = FakeSession()
    session.set_response(
        "GET https://community.example.com/internal_api/chat_rooms/abc-123/messages",
        FakeResponse({"records": [{"id": 1, "body": {}}], "total_count": 1}),
    )
    result = CircleClient(_settings(), session=session).list_chat_messages(
        chat_room_uuid="abc-123", next_per_page=5
    )
    assert result["total_count"] == 1
    assert "next_per_page=5" in session.calls[0]["url"]
    assert "previous_per_page=0" in session.calls[0]["url"]


def test_list_chat_messages_with_cursor() -> None:
    session = FakeSession()
    session.set_response(
        "GET https://community.example.com/internal_api/chat_rooms/abc-123/messages",
        FakeResponse({"records": []}),
    )
    CircleClient(_settings(), session=session).list_chat_messages(
        chat_room_uuid="abc-123", previous_per_page=50, before_creation_uuid="cursor-abc"
    )
    assert "before_creation_uuid=cursor-abc" in session.calls[0]["url"]
    assert "previous_per_page=50" in session.calls[0]["url"]


def test_fetch_chat_replies() -> None:
    session = FakeSession()
    session.set_response(
        "GET https://community.example.com/internal_api/chat_rooms/abc-123/messages",
        FakeResponse({"records": [{"id": 100, "parent_message_id": 999}]}),
    )
    replies = CircleClient(_settings(), session=session).fetch_chat_replies(
        chat_room_uuid="abc-123", parent_message_id=999
    )
    assert len(replies) == 1
    assert replies[0]["parent_message_id"] == 999
    assert "parent_message_id=999" in session.calls[0]["url"]


def test_error_includes_status_and_body() -> None:
    session = FakeSession()
    session.set_response(
        "GET https://community.example.com/internal_api/spaces/999/posts",
        FakeResponse({"error": "Not found"}, status_code=404, text='{"error":"Not found"}'),
    )
    try:
        CircleClient(_settings(), session=session).list_posts(space_id=999)
    except CircleClientError as exc:
        assert exc.status_code == 404
        assert "404" in str(exc)
    else:
        raise AssertionError("Expected CircleClientError")