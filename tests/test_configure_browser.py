"""Reproductions for the two `configure-browser` bugs reported in PR #45.

A local HTTPS server stands in for a Circle community that has public spaces:
the feed answers anonymous visitors (and hands them an anonymous session
cookie), while `/internal_api/notification_preferences` answers 401 until the
user has signed in. The command runs against it in a real headless Chromium.

Bug 1: a public feed means "the URL no longer says login", so the command
saves the anonymous cookie instead of waiting for a real login.

Bug 2: when the login redirect lands while the command reads page state,
`page.evaluate` raises "Execution context was destroyed" and the command
crashes without writing `.env`.
"""

from __future__ import annotations

import argparse
import shutil
import ssl
import subprocess
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from dotenv import dotenv_values

playwright_api = pytest.importorskip("playwright.async_api")

from circle_client_skill import cli  # noqa: E402
from circle_client_skill.config import ConfigurationError  # noqa: E402

ANON_SESSION = "anon-session-value"
ANON_CSRF = "anon-csrf-value"
MEMBER_SESSION = "member-session-value"
MEMBER_CSRF = "member-csrf-value"
COMMUNITY_ID = "4242"

FEED_HTML = "<!doctype html><html><body><h1>Public feed</h1>{script}</body></html>"
MEMBER_SCRIPT = (
    "<script>localStorage.setItem('V1-PunditUserContext', JSON.stringify("
    f"{{state: {{current_community: {{id: {COMMUNITY_ID}}}}}}}));</script>"
)


class FakeCommunity:
    """Public Circle community. `login_after` = seconds until the user finishes
    signing in (None: never). From then on every response upgrades the session."""

    def __init__(self, login_after: float | None) -> None:
        self.login_after = login_after
        self.started = time.monotonic()

    def logged_in_now(self) -> bool:
        return self.login_after is not None and time.monotonic() - self.started >= self.login_after


def make_handler(community: FakeCommunity):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # keep pytest output clean
            pass

        def _session(self) -> str | None:
            jar = SimpleCookie(self.headers.get("Cookie", ""))
            return jar["_circle_session"].value if "_circle_session" in jar else None

        def _signed_in(self) -> bool:
            return self._session() == MEMBER_SESSION or community.logged_in_now()

        def _send(self, status: int, body: str, content_type: str) -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if self._signed_in():
                if self._session() != MEMBER_SESSION:
                    self.send_header("Set-Cookie", f"_circle_session={MEMBER_SESSION}; Path=/")
                    self.send_header("Set-Cookie", f"csrf_token={MEMBER_CSRF}; Path=/")
            elif self._session() is None:
                self.send_header("Set-Cookie", f"_circle_session={ANON_SESSION}; Path=/")
                self.send_header("Set-Cookie", f"csrf_token={ANON_CSRF}; Path=/")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/internal_api/notification_preferences":
                if self._signed_in():
                    self._send(200, "{}", "application/json")
                else:
                    self._send(401, '{"message":"You cannot perform this action."}', "application/json")
            elif path in ("/", "/feed"):
                script = MEMBER_SCRIPT if self._signed_in() else ""
                self._send(200, FEED_HTML.format(script=script), "text/html")
            else:
                self._send(404, "not found", "text/plain")

    return Handler


@pytest.fixture(scope="module")
def tls_cert(tmp_path_factory) -> tuple[Path, Path]:
    if not shutil.which("openssl"):
        pytest.skip("openssl is required to create a throwaway TLS certificate")
    directory = tmp_path_factory.mktemp("tls")
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=127.0.0.1", "-keyout", str(key), "-out", str(cert)],
        check=True, capture_output=True,
    )
    return cert, key


@pytest.fixture
def serve(tls_cert):
    servers = []

    def start(login_after: float | None) -> str:
        community = FakeCommunity(login_after)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(community))
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(*tls_cert)
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"https://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def headless_test_browser(monkeypatch):
    """Run the command's browser headless and trust the throwaway certificate."""
    original_launch = playwright_api.BrowserType.launch
    original_new_context = playwright_api.Browser.new_context

    async def launch(self, *args, **kwargs):
        kwargs["headless"] = True
        try:
            return await original_launch(self, *args, **kwargs)
        except playwright_api.Error as exc:
            pytest.skip(f"Chromium is not available: {exc}")

    async def new_context(self, *args, **kwargs):
        kwargs["ignore_https_errors"] = True
        return await original_new_context(self, *args, **kwargs)

    monkeypatch.setattr(playwright_api.BrowserType, "launch", launch)
    monkeypatch.setattr(playwright_api.Browser, "new_context", new_context)


def run_configure_browser(url: str, env_file: Path, timeout: int) -> ConfigurationError | None:
    # `timeout` is the PR's new --timeout; the old code ignores the attribute.
    args = argparse.Namespace(url=url, env_file=str(env_file), timeout=timeout)
    try:
        cli.cmd_configure_browser(args)
    except ConfigurationError as exc:
        return exc
    return None


def test_bug1_does_not_save_anonymous_session_when_nobody_logs_in(serve, tmp_path):
    base = serve(login_after=None)
    env_file = tmp_path / ".env"

    run_configure_browser(f"{base}/feed", env_file, timeout=4)

    saved = env_file.read_text() if env_file.exists() else ""
    assert ANON_SESSION not in saved, "configure-browser saved the anonymous visitor's cookie"
    assert not env_file.exists(), "nobody logged in, so nothing should have been written"


def test_bug1_waits_for_login_and_saves_member_session(serve, tmp_path):
    base = serve(login_after=5)
    env_file = tmp_path / ".env"

    error = run_configure_browser(f"{base}/feed", env_file, timeout=30)

    assert error is None, f"configure-browser failed: {error}"
    values = dotenv_values(env_file)
    cookie = values.get("CIRCLE_CLIENT_COOKIE") or ""
    assert f"_circle_session={MEMBER_SESSION}" in cookie, f"saved cookie is not the member session: {cookie!r}"
    assert ANON_SESSION not in cookie
    assert values.get("CIRCLE_CLIENT_CSRF_TOKEN") == MEMBER_CSRF


def test_bug2_survives_navigation_while_reading_page_state(serve, tmp_path, monkeypatch):
    base = serve(login_after=0)
    env_file = tmp_path / ".env"

    original_evaluate = playwright_api.Page.evaluate
    calls = {"count": 0}

    async def evaluate(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            # What Playwright raises when an SSO redirect commits mid-evaluate.
            raise playwright_api.Error(
                "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
            )
        return await original_evaluate(self, *args, **kwargs)

    monkeypatch.setattr(playwright_api.Page, "evaluate", evaluate)

    try:
        error = run_configure_browser(f"{base}/feed", env_file, timeout=30)
    except playwright_api.Error as exc:
        pytest.fail(f"configure-browser crashed on a mid-evaluate navigation: {exc}")

    assert error is None, f"configure-browser failed: {error}"
    assert calls["count"] >= 1
    values = dotenv_values(env_file)
    assert f"_circle_session={MEMBER_SESSION}" in (values.get("CIRCLE_CLIENT_COOKIE") or "")
    assert f"community_id={COMMUNITY_ID}" in (values.get("CIRCLE_CLIENT_COUNT_URL") or "")
