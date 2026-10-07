from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
from pathlib import Path

import pytest

from circle_client_skill import cli
from circle_client_skill.config import ConfigurationError, load_settings
from circle_client_skill.visible_browser import (
    chrome_command,
    find_chrome,
    open_visible_browser,
    port_in_use,
    profile_in_use,
    resolve_target_url,
    wait_for_cdp,
)

HOST = "community.example.com"
BASE = f"https://{HOST}"
FAKE_COOKIE = "session_id=fake-session-value-123; csrf_token=fake-csrf-value-456; theme=dark"
SECRETS = ("fake-session-value-123", "fake-csrf-value-456")


def write_env(path: Path, cookie: str | None = FAKE_COOKIE) -> Path:
    lines = [
        f"CIRCLE_CLIENT_NOTIFICATIONS_URL={BASE}/internal_api/notifications",
        "CIRCLE_CLIENT_CSRF_TOKEN=fake-csrf-value-456",
    ]
    if cookie:
        lines.append(f'CIRCLE_CLIENT_COOKIE="{cookie}"')
    path.write_text("\n".join(lines) + "\n")
    return path


class FakeProcess:
    pid = 4242

    def __init__(self, exit_code: int | None = None) -> None:
        self.exit_code = exit_code

    def poll(self) -> int | None:
        return self.exit_code


class FakePage:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.url = "about:blank"

    def goto(self, url: str, **_kwargs) -> None:
        self.log.append(f"goto {url}")
        self.url = url

    def wait_for_timeout(self, _ms: int) -> None:
        pass

    def close(self) -> None:  # must never be called: the human keeps the window
        self.log.append("page.close")


class FakeContext:
    def __init__(self, log: list[str], pages: int = 1) -> None:
        self.log = log
        self.cookies: list[dict] = []
        self.pages = [FakePage(log) for _ in range(pages)]

    def add_cookies(self, cookies: list[dict]) -> None:
        self.cookies.extend(cookies)

    def new_page(self) -> FakePage:
        page = FakePage(self.log)
        self.pages.append(page)
        return page


class FakePlaywright:
    def __init__(self, pages: int = 1, fail_goto: bool = False) -> None:
        self.log: list[str] = []
        self.context = FakeContext(self.log, pages)
        pw = self

        class Browser:
            def __init__(self) -> None:
                self.contexts = [pw.context]

            def close(self) -> None:
                pw.log.append("browser.close")

        class Chromium:
            def connect_over_cdp(self, endpoint: str):
                pw.log.append(f"connect {endpoint}")
                if fail_goto:
                    pw.context.pages[0].goto = _raise
                return Browser()

            def launch(self, **_kwargs):  # pragma: no cover - must not be used
                raise AssertionError("open-browser must not launch a Playwright-owned browser")

        self.chromium = Chromium()

    def start(self):
        return self

    def stop(self) -> None:
        self.log.append("playwright.stop")


def _raise(*_args, **_kwargs):
    raise RuntimeError("navigation failed")


def run_open(tmp_path: Path, **overrides):
    fake = overrides.pop("fake", None) or FakePlaywright()
    launched: list[tuple[list[str], dict]] = []

    def popen(cmd, **kwargs):
        launched.append((cmd, kwargs))
        return FakeProcess()

    kwargs = {
        "port": 9555,
        "profile_dir": tmp_path / "data" / "visible_browser" / "profile",
        "settle_ms": 0,
        "popen": popen,
        "port_check": lambda _port: False,
        "chrome_finder": lambda _explicit: "/opt/fake/chrome",
        "cdp_waiter": lambda endpoint, process: {"Browser": "Chrome/0"},
        "playwright_factory": lambda: fake,
    }
    kwargs.update(overrides)
    settings = load_settings(write_env(tmp_path / ".env"))
    result = open_visible_browser(settings, **kwargs)
    return result, fake, launched


def test_open_launches_detached_chrome_injects_cookies_and_disconnects(tmp_path: Path) -> None:
    result, fake, launched = run_open(tmp_path, path="/c/example-space")
    (cmd, popen_kwargs), = launched
    assert cmd[0] == "/opt/fake/chrome"
    assert "--remote-debugging-port=9555" in cmd
    assert any(arg.startswith("--user-data-dir=") and arg.endswith("profile") for arg in cmd)
    assert "--headless" not in " ".join(cmd)
    assert popen_kwargs["start_new_session"] is True
    assert {c["name"] for c in fake.context.cookies} == {"session_id", "csrf_token", "theme"}
    assert all(c["url"] == BASE for c in fake.context.cookies)
    assert fake.log == [
        "connect http://127.0.0.1:9555",
        f"goto {BASE}/c/example-space",
        "playwright.stop",
    ]
    assert result["cdp_endpoint"] == "http://127.0.0.1:9555"
    assert result["url"] == f"{BASE}/c/example-space"
    assert result["pid"] == 4242
    assert result["cookie_count"] == 3
    assert (tmp_path / "data" / "visible_browser" / "profile").is_dir()
    assert not any(secret in json.dumps(result) for secret in SECRETS)


def test_open_creates_page_when_context_has_none(tmp_path: Path) -> None:
    fake = FakePlaywright(pages=0)
    result, fake, _ = run_open(tmp_path, fake=fake)
    assert len(fake.context.pages) == 1
    assert result["final_url"] == f"{BASE}/"


def test_open_stops_playwright_even_when_navigation_fails(tmp_path: Path) -> None:
    fake = FakePlaywright(fail_goto=True)
    with pytest.raises(RuntimeError, match="navigation failed"):
        run_open(tmp_path, fake=fake)
    assert fake.log[-1] == "playwright.stop"
    assert "browser.close" not in fake.log and "page.close" not in fake.log


def test_open_refuses_busy_port_before_launching(tmp_path: Path) -> None:
    launched: list = []
    with pytest.raises(ConfigurationError, match="already in use"):
        run_open(tmp_path, port_check=lambda _port: True, popen=lambda *a, **k: launched.append(a))
    assert launched == []


def test_open_refuses_locked_profile(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    os.symlink("host-12345", profile / "SingletonLock")  # dangling, like Chrome's lock
    launched: list = []
    with pytest.raises(ConfigurationError, match="locked"):
        run_open(tmp_path, profile_dir=profile, popen=lambda *a, **k: launched.append(a))
    assert launched == []


def test_open_requires_cookie_and_chrome(tmp_path: Path) -> None:
    settings = load_settings(write_env(tmp_path / ".env", cookie=None))
    with pytest.raises(ConfigurationError, match="cookie"):
        open_visible_browser(settings, port_check=lambda _p: False)
    with pytest.raises(ConfigurationError, match="Chrome not found"):
        run_open(tmp_path, chrome_finder=lambda _explicit: None)


def test_resolve_target_url_stays_on_community_https_host() -> None:
    assert resolve_target_url(BASE) == f"{BASE}/"
    assert resolve_target_url(BASE, path="c/example-space") == f"{BASE}/c/example-space"
    assert resolve_target_url(BASE, url=f"{BASE}/c/x?post=1") == f"{BASE}/c/x?post=1"
    with pytest.raises(ValueError, match="https"):
        resolve_target_url(BASE, url=f"http://{HOST}/c/x")
    with pytest.raises(ValueError, match="does not match"):
        resolve_target_url(BASE, url="https://elsewhere.example.net/c/x")
    with pytest.raises(ValueError, match="not both"):
        resolve_target_url(BASE, path="/a", url=f"{BASE}/b")


def test_find_chrome_prefers_explicit_then_known_paths_then_path() -> None:
    assert find_chrome("/x/chrome", exists=lambda p: p == "/x/chrome") == "/x/chrome"
    assert find_chrome("/x/missing", exists=lambda _p: False) is None
    assert find_chrome(which=lambda _c: None, exists=lambda _p: False) is None
    assert (
        find_chrome(which=lambda c: f"/usr/bin/{c}" if c == "chromium" else None, exists=lambda _p: False)
        == "/usr/bin/chromium"
    )


def test_chrome_command_uses_dedicated_profile_and_loopback() -> None:
    cmd = chrome_command("/opt/chrome", port=9555, profile_dir=Path("/tmp/p"), window_size=(800, 600))
    assert cmd[0] == "/opt/chrome"
    assert "--remote-debugging-address=127.0.0.1" in cmd
    assert "--user-data-dir=/tmp/p" in cmd
    assert "--window-size=800,600" in cmd


def test_profile_in_use_detects_singleton_entries(tmp_path: Path) -> None:
    assert not profile_in_use(tmp_path)
    (tmp_path / "SingletonSocket").write_text("")
    assert profile_in_use(tmp_path)


def test_port_in_use_with_a_local_listener() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert port_in_use(port)
    assert not port_in_use(port)


def test_wait_for_cdp_retries_then_returns() -> None:
    calls = {"n": 0}

    def fetch(_endpoint: str) -> dict:
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("refused")
        return {"Browser": "Chrome/0"}

    result = wait_for_cdp("http://127.0.0.1:1", FakeProcess(), fetch=fetch, sleep=lambda _s: None)
    assert result == {"Browser": "Chrome/0"}
    assert calls["n"] == 3


def test_wait_for_cdp_fails_fast_when_chrome_exits() -> None:
    with pytest.raises(ConfigurationError, match="exited"):
        wait_for_cdp("http://127.0.0.1:1", FakeProcess(exit_code=0), fetch=_raise)


def test_wait_for_cdp_times_out() -> None:
    ticks = iter([0.0, 1.0, 5.0])

    def fetch(_endpoint: str) -> dict:
        raise urllib.error.URLError("refused")

    with pytest.raises(ConfigurationError, match="did not respond"):
        wait_for_cdp(
            "http://127.0.0.1:1",
            FakeProcess(),
            timeout=2.0,
            fetch=fetch,
            sleep=lambda _s: None,
            clock=lambda: next(ticks),
        )


def test_cli_open_browser_prints_result_without_credentials(tmp_path: Path, monkeypatch, capsys) -> None:
    env = write_env(tmp_path / ".env")
    seen: dict = {}

    def fake_open(settings, **kwargs):
        seen.update(kwargs)
        assert settings.cookie == FAKE_COOKIE
        return {"success": True, "cdp_endpoint": "http://127.0.0.1:9555", "url": f"{BASE}/c/x"}

    import circle_client_skill.visible_browser as vb

    monkeypatch.setattr(vb, "open_visible_browser", fake_open)
    monkeypatch.setattr(
        sys,
        "argv",
        ["circle-client", "open-browser", "--env-file", str(env), "--path", "/c/x", "--port", "9555"],
    )
    cli.main()
    out = capsys.readouterr().out
    assert json.loads(out)["cdp_endpoint"] == "http://127.0.0.1:9555"
    assert seen["path"] == "/c/x" and seen["port"] == 9555 and seen["url"] is None
    assert seen["profile_dir"] == Path("data/visible_browser/profile")
    assert not any(secret in out for secret in SECRETS)


def test_cli_open_browser_error_is_masked(tmp_path: Path, monkeypatch, capsys) -> None:
    env = write_env(tmp_path / ".env")
    import circle_client_skill.visible_browser as vb

    def boom(_settings, **_kwargs):
        raise ConfigurationError("bad cookie=fake-session-value-123")

    monkeypatch.setattr(vb, "open_visible_browser", boom)
    monkeypatch.setattr(sys, "argv", ["circle-client", "open-browser", "--env-file", str(env)])
    with pytest.raises(SystemExit):
        cli.main()
    err = capsys.readouterr().err
    assert "fake-session-value-123" not in err
