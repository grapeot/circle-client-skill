"""Open a human-visible Chrome window that is logged in with the saved Circle session.

This is the entry point for browser-driven write workflows (creating or editing a post):
the agent fills the composer through Chrome DevTools Protocol, then a human reviews the
editor and clicks Publish. This module itself never writes Circle data: it launches
Chrome, injects the cookies from the local credential store, opens one community page
and disconnects. The browser keeps running after the command exits.

Safety rules enforced here:

- Refuse when the debugging port is already accepting connections. Another browser
  (possibly one a human is working in) may own it; we never attach to it.
- Refuse when the profile directory is locked by a running Chrome. Chrome would hand
  the launch over to that instance and our window would land in someone else's session.
- Only navigate to HTTPS URLs on the community host derived from the credential store.
- Never print, log or return cookie values; the result only contains the endpoint,
  port, profile path, URL and process id.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from .config import CircleSettings, ConfigurationError
from .probe.session import cookies_for_browser

DEFAULT_PORT = 9333
DEFAULT_PROFILE_DIR = Path("data/visible_browser/profile")
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)
CHROME_COMMANDS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
SINGLETON_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie")


def find_chrome(
    explicit: str | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    exists: Callable[[str], bool] = os.path.exists,
) -> str | None:
    """Return a Chrome/Chromium executable: explicit path, then common installs, then PATH."""
    if explicit:
        return explicit if exists(explicit) else None
    for candidate in CHROME_CANDIDATES:
        if exists(candidate):
            return candidate
    for command in CHROME_COMMANDS:
        found = which(command)
        if found:
            return found
    return None


def port_in_use(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """True if something already accepts TCP connections on host:port.

    Only opens and closes a TCP socket; it sends nothing to whatever is listening.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def profile_in_use(profile_dir: Path) -> bool:
    """True if a Chrome instance holds this user-data-dir (Singleton* entries present).

    Uses lexists because SingletonLock is a symlink whose target is not a real file.
    """
    return any(os.path.lexists(profile_dir / name) for name in SINGLETON_FILES)


def resolve_target_url(base_url: str, *, path: str | None = None, url: str | None = None) -> str:
    """Build the page to open; it must be HTTPS on the community host."""
    if path and url:
        raise ValueError("pass --path or --url, not both")
    target = url or urljoin(base_url + "/", (path or "/").lstrip("/"))
    parts = urlsplit(target)
    base = urlsplit(base_url)
    if parts.scheme != "https":
        raise ValueError("target URL must use https")
    if (parts.hostname or "").lower() != (base.hostname or "").lower():
        raise ValueError(
            f"target host {parts.hostname!r} does not match the community host {base.hostname!r}"
        )
    return target


def chrome_command(
    chrome: str, *, port: int, profile_dir: Path, window_size: tuple[int, int]
) -> list[str]:
    return [
        chrome,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--window-size={window_size[0]},{window_size[1]}",
        "about:blank",
    ]


def _fetch_version(endpoint: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{endpoint}/json/version", timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_cdp(
    endpoint: str,
    process: Any,
    *,
    timeout: float = 20.0,
    interval: float = 0.25,
    fetch: Callable[[str], dict[str, Any]] = _fetch_version,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll the new browser's /json/version until it answers or the process dies."""
    deadline = clock() + timeout
    while True:
        if process.poll() is not None:
            raise ConfigurationError(
                "Chrome exited before its debugging endpoint came up "
                "(profile already open elsewhere, or a bad --chrome path)"
            )
        try:
            return fetch(endpoint)
        except (urllib.error.URLError, OSError, ValueError):
            pass
        if clock() >= deadline:
            raise ConfigurationError(f"Chrome debugging endpoint {endpoint} did not respond in time")
        sleep(interval)


def _default_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ConfigurationError(
            "Playwright is not installed. Install with: uv pip install -e '.[browser]' "
            "then run: python -m playwright install chromium"
        ) from None
    return sync_playwright()


def open_visible_browser(
    settings: CircleSettings,
    *,
    path: str | None = None,
    url: str | None = None,
    port: int = DEFAULT_PORT,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    chrome: str | None = None,
    window_size: tuple[int, int] = (1500, 1000),
    settle_ms: int = 3000,
    popen: Callable[..., Any] = subprocess.Popen,
    port_check: Callable[[int], bool] = port_in_use,
    chrome_finder: Callable[[str | None], str | None] = find_chrome,
    cdp_waiter: Callable[[str, Any], dict[str, Any]] = wait_for_cdp,
    playwright_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Launch a visible Chrome, inject the session cookies, open one page, disconnect."""
    if not settings.cookie:
        raise ConfigurationError(
            "No cookie in the credential store; run `circle-client configure-browser` first"
        )
    target = resolve_target_url(settings.base_url, path=path, url=url)
    if port_check(port):
        raise ConfigurationError(
            f"port {port} is already in use; another browser may own it. "
            "Pick a different --port; this command never attaches to an existing browser"
        )
    profile_dir = Path(profile_dir)
    if profile_in_use(profile_dir):
        raise ConfigurationError(
            f"profile {profile_dir} is locked by a running Chrome; close that window or "
            "pass a different --profile-dir"
        )
    executable = chrome_finder(chrome)
    if not executable:
        raise ConfigurationError(
            "Chrome not found; pass --chrome /path/to/chrome (Chrome or Chromium)"
        )
    profile_dir.mkdir(parents=True, exist_ok=True)
    endpoint = f"http://127.0.0.1:{port}"
    process = popen(
        chrome_command(executable, port=port, profile_dir=profile_dir.resolve(), window_size=window_size),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    cdp_waiter(endpoint, process)

    factory = playwright_factory or _default_playwright
    pw = factory().start()
    try:
        browser = pw.chromium.connect_over_cdp(endpoint)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        context.add_cookies(cookies_for_browser(settings.cookie, settings.base_url))
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(target, wait_until="domcontentloaded", timeout=60000)
        if settle_ms:
            page.wait_for_timeout(settle_ms)
        final_url = page.url
    finally:
        # Stopping Playwright drops the CDP connection; the Chrome process we spawned
        # keeps running so the human (and later agent scripts) can keep using it.
        pw.stop()

    return {
        "success": True,
        "cdp_endpoint": endpoint,
        "port": port,
        "profile_dir": str(profile_dir),
        "url": target,
        "final_url": final_url,
        "pid": getattr(process, "pid", None),
        "cookie_count": len(cookies_for_browser(settings.cookie, settings.base_url)),
        "next": "connect with playwright chromium.connect_over_cdp(cdp_endpoint); "
        "fill the composer, never click Publish",
    }
