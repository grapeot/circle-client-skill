"""Headless Chromium session logged in with the cookies from the local credential store.

Usage::

    with ProbeSession(env_path=Path(".env")) as probe:
        probe.page.goto(probe.url("/c/some-space"))
        probe.screenshot(Path("data/probe/space.png"))
    probe.capture.dump(Path("data/probe"), "space")

Guarantees:

- Cookies come from the existing `.env` (`CIRCLE_CLIENT_COOKIE`); they are injected
  into the browser context and never printed, logged or stored on the session.
- A `RouteGuard` is installed on the whole context before the first page opens.
  With the default empty `allow`, no non-GET request reaches the community.
- Service workers are blocked so they cannot bypass routing.
- Page, context, browser and Playwright are closed in `finally`, each step guarded so
  a failure in one does not skip the others.

Playwright is an optional dependency: `uv pip install -e '.[browser]'` and
`python -m playwright install chromium`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from ..config import CircleSettings, ConfigurationError, load_settings
from .capture import RequestCapture
from .guard import AllowRule, RouteGuard
from .redact import Redactor, secrets_from_cookie_header

LOGIN_MARKERS = ("sign_in", "/login", "sign-in")


def cookies_for_browser(cookie_header: str, base_url: str) -> list[dict[str, Any]]:
    """Turn a `name=value; ...` header into Playwright `add_cookies` entries."""
    cookies = []
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        name, value = part.strip().split("=", 1)
        if not name:
            continue
        cookies.append({"name": name, "value": value, "url": base_url})
    return cookies


def settings_redactor(settings: CircleSettings) -> Redactor:
    return Redactor(
        [
            *secrets_from_cookie_header(settings.cookie),
            settings.csrf_token,
            settings.authorization,
            settings.authorization.split(" ", 1)[-1] if settings.authorization else None,
        ]
    )


def _default_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ConfigurationError(
            "Playwright is not installed. Install with: uv pip install -e '.[browser]' "
            "then run: python -m playwright install chromium"
        ) from None
    return sync_playwright()


class ProbeSession:
    def __init__(
        self,
        env_path: Path = Path(".env"),
        *,
        allow: Iterable[str | AllowRule] = (),
        headless: bool = True,
        viewport: tuple[int, int] = (1440, 1000),
        locale: str | None = None,
        save_bodies: bool = False,
        playwright_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.env_path = env_path
        self.allow = tuple(allow)
        self.headless = headless
        self.viewport = viewport
        self.locale = locale
        self.save_bodies = save_bodies
        self._factory = playwright_factory or _default_playwright
        self.base_url: str | None = None
        self.guard: RouteGuard | None = None
        self.capture: RequestCapture | None = None
        self.redactor: Redactor | None = None
        self._pw: Any = None
        self.browser: Any = None
        self.context: Any = None
        self.page: Any = None

    def __repr__(self) -> str:
        return f"ProbeSession(base_url={self.base_url!r}, allow={len(self.allow)} rule(s))"

    def url(self, path: str) -> str:
        if self.base_url is None:
            raise RuntimeError("session is not open")
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def __enter__(self) -> ProbeSession:
        settings = load_settings(self.env_path)
        if not settings.cookie:
            raise ConfigurationError(
                "No cookie in the credential store; run `circle-client configure-browser` first"
            )
        self.base_url = settings.base_url
        self.redactor = settings_redactor(settings)
        self.guard = RouteGuard.for_base_url(self.base_url, tuple(self.allow))
        self.capture = RequestCapture(
            self.redactor, host=self.guard.host, save_bodies=self.save_bodies
        )
        try:
            self._pw = self._factory().start()
            self.browser = self._pw.chromium.launch(headless=self.headless)
            context_kwargs: dict[str, Any] = {
                "viewport": {"width": self.viewport[0], "height": self.viewport[1]},
                "service_workers": "block",
            }
            if settings.user_agent:
                context_kwargs["user_agent"] = settings.user_agent
            if self.locale:
                context_kwargs["locale"] = self.locale
            self.context = self.browser.new_context(**context_kwargs)
            self.guard.install(self.context)
            self.context.add_cookies(cookies_for_browser(settings.cookie, self.base_url))
            self.capture.attach(self.context)
            self.page = self.context.new_page()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close page, context, browser and Playwright; never raises."""
        steps = (
            (self.page, "close"),
            (self.context, "close"),
            (self.browser, "close"),
            (self._pw, "stop"),
        )
        try:
            for obj, method in steps:
                if obj is not None:
                    with contextlib.suppress(Exception):
                        getattr(obj, method)()
        finally:
            self.page = self.context = self.browser = self._pw = None

    def screenshot(self, path: Path, *, full_page: bool = True) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(path), full_page=full_page)
        return path

    def looks_logged_in(self) -> bool:
        """Heuristic: not on a login URL and no 401 from the internal API so far."""
        current = (self.page.url or "").lower()
        if any(marker in current for marker in LOGIN_MARKERS):
            return False
        records = self.capture.records if self.capture else []
        return not any(entry.get("status") == 401 for entry in records)
