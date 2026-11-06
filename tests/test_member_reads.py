from __future__ import annotations

import json
from pathlib import Path

import pytest

from circle_client_skill import cli
from circle_client_skill.client import CircleClient, CircleClientError
from circle_client_skill.config import CircleSettings


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.payload = payload
        self.text = "" if payload is None else str(payload)

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self._responses: dict[str, FakeResponse] = {}

    def set_response(self, method_url: str, response: FakeResponse) -> None:
        self._responses[method_url] = response

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        base = url.split("?")[0]
        return self._responses[f"{method} {base}"]

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        return self.request("GET", url, **kwargs)


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


def test_event_attendees_request_shape() -> None:
    session = FakeSession()
    session.set_response(
        "GET https://community.example.com/internal_api/spaces/1111/events/example-event/event_attendees",
        FakeResponse({"records": [{"id": 1, "email": "a@example.com"}], "has_next_page": False, "count": 1}),
    )
    result = CircleClient(_settings(), session=session).list_event_attendees(1111, "example-event", per_page=20)
    assert result["records"][0]["id"] == 1
    url = str(session.calls[0]["url"])
    assert "role=participant" in url
    assert "per_page=20" in url


def test_event_attendees_rejects_path_injection() -> None:
    with pytest.raises(ValueError):
        CircleClient(_settings(), session=FakeSession()).list_event_attendees(1111, "../events")


def test_iter_event_attendees_stops_and_dedupes() -> None:
    session = FakeSession()
    pages = {
        1: {"records": [{"id": 1}, {"id": 2}], "has_next_page": True},
        2: {"records": [{"id": 2}, {"id": 3}], "has_next_page": False},
    }
    session.set_response(
        "GET https://community.example.com/internal_api/spaces/1111/events/example-event/event_attendees",
        FakeResponse({}),
    )

    def request(method: str, url: str, **kwargs: object) -> FakeResponse:
        session.calls.append({"url": url})
        page = int(url.split("page=")[1].split("&")[0])
        return FakeResponse(pages[page])

    session.request = request  # type: ignore[method-assign]
    client = CircleClient(_settings(), session=session)
    pages_out = list(client.iter_event_attendees(1111, "example-event", per_page=2, max_pages=5))
    ids = [record["id"] for page in pages_out for record in page["records"]]
    assert ids == [1, 2, 3]
    assert len(session.calls) == 2


def test_iter_stops_at_max_pages() -> None:
    session = FakeSession()

    def request(method: str, url: str, **kwargs: object) -> FakeResponse:
        page = int(url.split("page=", 1)[1].split("&", 1)[0])
        return FakeResponse({"records": [{"id": page}], "has_next_page": True})

    session.request = request  # type: ignore[method-assign]
    client = CircleClient(_settings(), session=session)
    with pytest.raises(CircleClientError, match="max_pages"):
        list(client.iter_member_posts("abc123", per_page=1, max_pages=2))


def test_member_profile_and_posts_urls() -> None:
    session = FakeSession()
    session.set_response(
        "GET https://community.example.com/internal_api/profiles/abc123",
        FakeResponse({"headline": "Builder", "posts_count": 2, "email": "hidden@example.com"}),
    )
    session.set_response(
        "GET https://community.example.com/internal_api/profiles/abc123/posts",
        FakeResponse({"records": [{"id": 9, "tiptap_body": {"body": {"text": "full"}}}], "has_next_page": False}),
    )
    client = CircleClient(_settings(), session=session)
    profile = client.get_member_profile("abc123")
    posts = client.list_member_posts("abc123", per_page=5)
    assert profile["headline"] == "Builder"
    assert "page_name=profile_view" in str(session.calls[0]["url"])
    assert posts["records"][0]["tiptap_body"]["body"]["text"] == "full"
    assert "per_page=5" in str(session.calls[1]["url"])


def test_cli_strips_email_and_writes_private_file(tmp_path: Path, monkeypatch, capsys) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def iter_event_attendees(self, *_args, **_kwargs):
            yield {
                "payload": {"total_confirmed_record_count": 1},
                "records": [{"id": 7, "public_uid": "abc123", "email": "person@example.com", "name": "Ada"}],
            }

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    output = tmp_path / "attendees.json"
    parser = cli.build_parser()
    args = parser.parse_args([
        "event-attendees", "-s", "1111", "--slug", "example-event", "--all",
        "--output", str(output), "--json",
    ])
    args.handler(args)
    saved = json.loads(output.read_text())
    printed = json.loads(capsys.readouterr().out)
    assert "email" not in saved["records"][0]
    assert printed["records"][0]["public_uid"] == "abc123"
    assert output.stat().st_mode & 0o777 == 0o600


def test_empty_page_with_next_does_not_skip_later_records() -> None:
    session = FakeSession()
    pages = {
        1: {"records": [{"id": 1}], "has_next_page": True},
        2: {"records": [], "has_next_page": True},
        3: {"records": [{"id": 3}], "has_next_page": False},
    }

    def request(method: str, url: str, **kwargs: object) -> FakeResponse:
        page = int(url.split("page=", 1)[1].split("&", 1)[0])
        return FakeResponse(pages[page])

    session.request = request  # type: ignore[method-assign]
    client = CircleClient(_settings(), session=session)
    with pytest.raises(CircleClientError, match="empty page"):
        list(client.iter_event_attendees(1111, "example-event", per_page=1, max_pages=5))


def test_repeated_page_does_not_claim_completion(monkeypatch, capsys) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_member_profile(self, _uid: str) -> dict[str, object]:
            return {"posts_count": 1, "headline": "x"}

        def iter_member_posts(self, *_args, **_kwargs):
            raise CircleClientError("page 2 repeated already seen records; pagination did not advance")

    monkeypatch.setattr(cli, "load_settings", lambda _path: object())
    monkeypatch.setattr(cli, "CircleClient", FakeClient)
    args = cli.build_parser().parse_args(["member-profile", "--public-uid", "abc123", "--all-posts", "--json"])
    with pytest.raises(CircleClientError, match="repeated"):
        args.handler(args)
    captured = capsys.readouterr()
    assert "has_next_page" not in captured.out


def test_private_write_replaces_wide_file_without_write_text(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "secret.json"
    target.write_text("old\n", encoding="utf-8")
    target.chmod(0o644)
    monkeypatch.setattr(Path, "write_text", lambda *a, **k: pytest.fail("write_text exposes content before chmod"))
    cli._write_private(target, "{\"ok\": true}\n")
    assert target.read_text() == "{\"ok\": true}\n"
    assert target.stat().st_mode & 0o777 == 0o600


def test_member_profile_cli_rejects_both_post_modes() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["member-profile", "--public-uid", "abc123", "--posts", "5", "--all-posts"])
    with pytest.raises(ValueError, match="only one"):
        args.handler(args)
