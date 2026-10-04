from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from circle_client_skill.probe import (
    REDACTED,
    AllowRule,
    ProbeSession,
    Redactor,
    RequestCapture,
    RouteGuard,
    cookies_for_browser,
    redact_headers,
    redact_url,
)
from circle_client_skill.probe.redact import secrets_from_cookie_header

HOST = "community.example.com"
BASE = f"https://{HOST}"
FAKE_COOKIE = "session_id=fake-session-value-123; csrf_token=fake-csrf-value-456; theme=dark"


class FakeRoute:
    def __init__(self, method: str, url: str) -> None:
        self.request = SimpleNamespace(method=method, url=url)
        self.outcome: str | None = None

    def continue_(self) -> None:
        self.outcome = "continue"

    def abort(self) -> None:
        self.outcome = "abort"


def run_guard(guard: RouteGuard, method: str, url: str) -> str | None:
    route = FakeRoute(method, url)
    guard.handle(route, route.request)
    return route.outcome


# --- guard -----------------------------------------------------------------


def test_guard_blocks_non_get_to_community_and_records_without_query() -> None:
    guard = RouteGuard(host=HOST)
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        assert run_guard(guard, method, f"{BASE}/internal_api/spaces/1111/events?x=1") == "abort"
    assert [b.method for b in guard.blocked] == ["POST", "PATCH", "PUT", "DELETE"]
    assert all(b.url == f"{BASE}/internal_api/spaces/1111/events" for b in guard.blocked)


def test_guard_allows_safe_methods() -> None:
    guard = RouteGuard(host=HOST)
    for method in ("GET", "HEAD", "OPTIONS", "get"):
        assert run_guard(guard, method, f"{BASE}/internal_api/spaces/1111/posts") == "continue"
    assert guard.blocked == []


def test_guard_leaves_other_hosts_untouched() -> None:
    guard = RouteGuard(host=HOST)
    assert run_guard(guard, "POST", "https://analytics.example.net/collect") == "continue"
    assert run_guard(guard, "PUT", "https://bucket.storage.example.org/upload") == "continue"
    # A sibling host is a different host.
    assert run_guard(guard, "POST", "https://app.example.com/internal_api/x") == "continue"
    assert guard.blocked == []


def test_guard_host_match_is_case_insensitive_and_ignores_port() -> None:
    guard = RouteGuard(host="Community.Example.com:443")
    assert run_guard(guard, "POST", "https://COMMUNITY.example.com:443/internal_api/x") == "abort"


def test_guard_allowlist_exact_path_and_method() -> None:
    guard = RouteGuard(host=HOST, allow=("POST /internal_api/spaces/1111/events",))
    assert run_guard(guard, "POST", f"{BASE}/internal_api/spaces/1111/events") == "continue"
    # Same path, other method: still blocked.
    assert run_guard(guard, "PATCH", f"{BASE}/internal_api/spaces/1111/events") == "abort"
    # Exact rule does not cover sub-paths or other spaces.
    assert run_guard(guard, "POST", f"{BASE}/internal_api/spaces/1111/events/slug") == "abort"
    assert run_guard(guard, "POST", f"{BASE}/internal_api/spaces/2222/events") == "abort"
    # Query string does not affect matching.
    assert run_guard(guard, "POST", f"{BASE}/internal_api/spaces/1111/events?a=b") == "continue"


def test_guard_allowlist_glob_and_any_method() -> None:
    guard = RouteGuard(
        host=HOST,
        allow=("/internal_api/direct_uploads", AllowRule("PATCH", "/internal_api/spaces/1111/events/*")),
    )
    assert run_guard(guard, "POST", f"{BASE}/internal_api/direct_uploads") == "continue"
    assert run_guard(guard, "PUT", f"{BASE}/internal_api/direct_uploads") == "continue"
    assert run_guard(guard, "PATCH", f"{BASE}/internal_api/spaces/1111/events/example-event") == "continue"
    assert run_guard(guard, "DELETE", f"{BASE}/internal_api/spaces/1111/events/example-event") == "abort"


def test_guard_default_allowlist_is_empty() -> None:
    assert RouteGuard(host=HOST).allow == ()
    assert RouteGuard.for_base_url(BASE).host == HOST


def test_allow_rule_parse_rejects_bad_specs() -> None:
    with pytest.raises(ValueError):
        AllowRule.parse("")
    with pytest.raises(ValueError):
        AllowRule.parse("POST internal_api/no-leading-slash")
    assert AllowRule.parse("post /x") == AllowRule("POST", "/x")


def test_guard_install_routes_everything() -> None:
    calls = []
    target = SimpleNamespace(route=lambda pattern, handler: calls.append((pattern, handler)))
    guard = RouteGuard(host=HOST)
    guard.install(target)
    assert calls == [("**/*", guard.handle)]


def test_guard_handle_falls_back_to_route_request() -> None:
    guard = RouteGuard(host=HOST)
    route = FakeRoute("POST", f"{BASE}/internal_api/x")
    guard.handle(route)
    assert route.outcome == "abort"


# --- redaction -------------------------------------------------------------


def test_redact_headers_masks_credentials_case_insensitively() -> None:
    out = redact_headers(
        {"Cookie": "a=b", "Authorization": "Bearer x", "X-CSRF-Token": "t", "Accept": "json"}
    )
    assert out == {"Cookie": REDACTED, "Authorization": REDACTED, "X-CSRF-Token": REDACTED, "Accept": "json"}


def test_redact_url_masks_sensitive_query_params_only() -> None:
    url = "https://bucket.storage.example.org/k?X-Amz-Signature=abc&X-Amz-Credential=def&part=1"
    out = redact_url(url)
    assert "abc" not in out and "def" not in out
    assert "part=1" in out
    plain = f"{BASE}/internal_api/spaces/1111/posts?per_page=50&past_events=true"
    assert redact_url(plain) == plain


def test_redactor_json_masks_keys_and_literal_secrets() -> None:
    redactor = Redactor(secrets_from_cookie_header(FAKE_COOKIE))
    data = {
        "event": {"name": "Example", "csrf_token": "anything"},
        "headers": {"Cookie": FAKE_COOKIE, "authorization": "Bearer abc.def.ghi"},
        "note": "leaked fake-session-value-123 in text",
        "list": [{"authenticity_token": "x"}, "Bearer zzz.yyy"],
        "tokens_count": 3,
    }
    out = redactor.json(data)
    dumped = json.dumps(out)
    assert "fake-session-value-123" not in dumped
    assert "fake-csrf-value-456" not in dumped
    assert "abc.def.ghi" not in dumped and "zzz.yyy" not in dumped
    assert out["event"] == {"name": "Example", "csrf_token": REDACTED}
    assert out["tokens_count"] == 3


def test_redactor_body_handles_json_and_text() -> None:
    redactor = Redactor(["fake-csrf-value-456"])
    body = json.dumps({"event": {"status": "draft"}, "authenticity_token": "fake-csrf-value-456"})
    out = json.loads(redactor.body(body))
    assert out == {"event": {"status": "draft"}, "authenticity_token": REDACTED}
    assert redactor.body("a=1&b=fake-csrf-value-456") == f"a=1&b={REDACTED}"
    assert redactor.body(None) is None


def test_secrets_from_cookie_header_includes_url_decoded_values() -> None:
    values = secrets_from_cookie_header("a=abc%3D%3D; b=plain")
    assert "abc%3D%3D" in values and "abc==" in values and "plain" in values


def make_request(method: str, url: str, post_data: str | None = None, rtype: str = "fetch"):
    return SimpleNamespace(method=method, url=url, post_data=post_data, resource_type=rtype)


def test_capture_filters_and_dump_is_redacted(tmp_path: Path) -> None:
    redactor = Redactor(secrets_from_cookie_header(FAKE_COOKIE))
    capture = RequestCapture(redactor, host=HOST, save_bodies=True)
    get = make_request("GET", f"{BASE}/internal_api/spaces/1111/posts?past_events=true")
    post = make_request(
        "POST",
        f"{BASE}/internal_api/spaces/1111/events",
        json.dumps({"event": {"status": "draft"}, "csrf_token": "fake-csrf-value-456"}),
    )
    capture.on_request(get)
    capture.on_request(post)
    capture.on_request(make_request("GET", f"{BASE}/c/space", rtype="document"))
    capture.on_request(make_request("GET", "https://other.example.net/internal_api/x"))
    capture.on_request(make_request("POST", f"{BASE}/internal_api/analytics/track"))
    capture.on_response(
        SimpleNamespace(
            request=get,
            url=get.url,
            status=200,
            json=lambda: {"records": [{"note": "fake-session-value-123"}]},
        )
    )
    capture.on_response(SimpleNamespace(request=post, url=post.url, status=200, json=lambda: {}))
    assert [r["method"] for r in capture.records] == ["GET", "POST"]

    written = capture.dump(tmp_path / "out", "t")
    assert [p.name for p in written] == ["t_requests.json", "t_bodies.json"]
    text = "".join(p.read_text() for p in written)
    assert "fake-session-value-123" not in text
    assert "fake-csrf-value-456" not in text
    records = json.loads(written[0].read_text())
    assert records[0]["status"] == 200
    assert json.loads(records[1]["post_data"])["event"] == {"status": "draft"}


# --- session ---------------------------------------------------------------


def write_env(path: Path, cookie: str | None = FAKE_COOKIE) -> Path:
    lines = [
        f"CIRCLE_CLIENT_NOTIFICATIONS_URL={BASE}/internal_api/notifications",
        "CIRCLE_CLIENT_USER_AGENT=Test Browser",
        "CIRCLE_CLIENT_CSRF_TOKEN=fake-csrf-value-456",
    ]
    if cookie:
        lines.append(f'CIRCLE_CLIENT_COOKIE="{cookie}"')
    path.write_text("\n".join(lines) + "\n")
    return path


class FakeObj:
    def __init__(self, log: list[str], name: str, fail_close: bool = False) -> None:
        self.log, self.name, self.fail_close = log, name, fail_close

    def close(self) -> None:
        self.log.append(f"{self.name}.close")
        if self.fail_close:
            raise RuntimeError("close failed")


class FakeContext(FakeObj):
    def __init__(self, log, kwargs, fail_new_page=False, fail_close=False):
        super().__init__(log, "context", fail_close)
        self.kwargs = kwargs
        self.cookies: list[dict] = []
        self.routes: list = []
        self.listeners: list[str] = []
        self.fail_new_page = fail_new_page

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))

    def add_cookies(self, cookies):
        self.cookies.extend(cookies)

    def on(self, event, handler):
        self.listeners.append(event)

    def new_page(self):
        if self.fail_new_page:
            raise RuntimeError("new_page failed")
        page = FakeObj(self.log, "page")
        page.url = f"{BASE}/feed"
        return page


class FakePlaywright:
    def __init__(self, fail_new_page=False, fail_context_close=False) -> None:
        self.log: list[str] = []
        self.fail_new_page = fail_new_page
        self.fail_context_close = fail_context_close
        self.context: FakeContext | None = None
        self.launch_kwargs: dict = {}
        pw = self

        class Browser(FakeObj):
            def new_context(self, **kwargs):
                pw.context = FakeContext(
                    pw.log, kwargs, pw.fail_new_page, pw.fail_context_close
                )
                return pw.context

        class Chromium:
            def launch(self, **kwargs):
                pw.launch_kwargs = kwargs
                return Browser(pw.log, "browser")

        self.chromium = Chromium()

    def start(self):
        return self

    def stop(self):
        self.log.append("playwright.stop")


def test_session_injects_cookies_installs_guard_and_closes(tmp_path: Path) -> None:
    fake = FakePlaywright()
    env = write_env(tmp_path / ".env")
    with ProbeSession(env_path=env, playwright_factory=lambda: fake) as probe:
        ctx = fake.context
        assert fake.launch_kwargs == {"headless": True}
        assert ctx.kwargs["service_workers"] == "block"
        assert ctx.kwargs["user_agent"] == "Test Browser"
        assert {c["name"] for c in ctx.cookies} == {"session_id", "csrf_token", "theme"}
        assert all(c["url"] == BASE for c in ctx.cookies)
        assert ctx.routes == [("**/*", probe.guard.handle)]
        assert probe.guard.allow == ()
        assert set(ctx.listeners) == {"request", "response"}
        assert probe.url("/c/space") == f"{BASE}/c/space"
        assert probe.looks_logged_in()
        assert "fake-session-value-123" not in repr(probe)
    assert fake.log == ["page.close", "context.close", "browser.close", "playwright.stop"]
    assert probe.page is None and probe.browser is None


def test_session_closes_when_body_raises(tmp_path: Path) -> None:
    fake = FakePlaywright()
    with pytest.raises(RuntimeError, match="boom"), ProbeSession(
        env_path=write_env(tmp_path / ".env"), playwright_factory=lambda: fake
    ):
        raise RuntimeError("boom")
    assert fake.log == ["page.close", "context.close", "browser.close", "playwright.stop"]


def test_session_closes_when_setup_fails(tmp_path: Path) -> None:
    fake = FakePlaywright(fail_new_page=True)
    with pytest.raises(RuntimeError, match="new_page"):
        ProbeSession(env_path=write_env(tmp_path / ".env"), playwright_factory=lambda: fake).__enter__()
    assert fake.log == ["context.close", "browser.close", "playwright.stop"]


def test_session_close_continues_after_a_failing_step(tmp_path: Path) -> None:
    fake = FakePlaywright(fail_context_close=True)
    with ProbeSession(env_path=write_env(tmp_path / ".env"), playwright_factory=lambda: fake):
        pass
    assert fake.log == ["page.close", "context.close", "browser.close", "playwright.stop"]


def test_session_passes_allowlist_and_never_prints_credentials(tmp_path: Path, capsys) -> None:
    fake = FakePlaywright()
    with ProbeSession(
        env_path=write_env(tmp_path / ".env"),
        allow=("POST /internal_api/spaces/1111/events",),
        playwright_factory=lambda: fake,
    ) as probe:
        assert probe.guard.allow == (AllowRule("POST", "/internal_api/spaces/1111/events"),)
    captured = capsys.readouterr()
    assert "fake-session-value-123" not in captured.out + captured.err
    assert "fake-csrf-value-456" not in captured.out + captured.err


def test_session_requires_cookie(tmp_path: Path) -> None:
    from circle_client_skill.config import ConfigurationError

    fake = FakePlaywright()
    with pytest.raises(ConfigurationError, match="cookie"):
        ProbeSession(env_path=write_env(tmp_path / ".env", cookie=None), playwright_factory=lambda: fake).__enter__()
    assert fake.log == []


def test_cookies_for_browser_skips_malformed_parts() -> None:
    cookies = cookies_for_browser("a=1; junk; =x; b=two=parts", BASE)
    assert cookies == [
        {"name": "a", "value": "1", "url": BASE},
        {"name": "b", "value": "two=parts", "url": BASE},
    ]
