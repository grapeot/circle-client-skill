"""Route guard for headless probes: observe by default, write only what is allowlisted.

The guard aborts every non-safe request (anything other than GET/HEAD/OPTIONS) that
targets the configured community host, unless the caller explicitly allowlists that
endpoint. Requests to other hosts (CDNs, analytics, S3 uploads) are left untouched.

The default allowlist is empty: a probe can open pages, click tabs and read state,
but the browser cannot create, edit or publish anything on the community.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class AllowRule:
    """One allowlisted non-GET endpoint.

    `method` is None when the rule applies to every non-GET method. `path` is matched
    against the request path (query string ignored) with `fnmatch` semantics: an exact
    path matches only itself, and `*` matches any characters including `/`.
    """

    method: str | None
    path: str

    @classmethod
    def parse(cls, spec: str) -> AllowRule:
        """Parse `"POST /internal_api/x"` or `"/internal_api/x"` into a rule."""
        text = spec.strip()
        if not text:
            raise ValueError("empty allow rule")
        parts = text.split(None, 1)
        if len(parts) == 2 and not parts[0].startswith("/"):
            method, path = parts[0].upper(), parts[1].strip()
        else:
            method, path = None, text
        if not path.startswith("/"):
            raise ValueError(f"allow rule path must start with '/': {spec!r}")
        return cls(method=method, path=path)

    def matches(self, method: str, path: str) -> bool:
        if self.method is not None and self.method != method.upper():
            return False
        return fnmatch.fnmatchcase(path, self.path)


@dataclass
class BlockedRequest:
    method: str
    url: str


def _strip_query(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


@dataclass
class RouteGuard:
    """Block non-GET requests to `host` unless they match an allow rule.

    `host` is a bare host name such as `community.example.com`; comparison is
    case-insensitive and ignores the port. `blocked` records every aborted request
    with the query string removed.
    """

    host: str
    allow: tuple[AllowRule, ...] = ()
    blocked: list[BlockedRequest] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.host = self.host.lower().split(":", 1)[0]
        self.allow = tuple(
            rule if isinstance(rule, AllowRule) else AllowRule.parse(rule) for rule in self.allow
        )

    @classmethod
    def for_base_url(cls, base_url: str, allow: tuple[str | AllowRule, ...] = ()) -> RouteGuard:
        hostname = urlsplit(base_url).hostname
        if not hostname:
            raise ValueError("base_url must include a host")
        return cls(host=hostname, allow=tuple(allow))  # type: ignore[arg-type]

    def is_community(self, url: str) -> bool:
        hostname = (urlsplit(url).hostname or "").lower()
        return hostname == self.host

    def allows(self, method: str, url: str) -> bool:
        """Return True if the request may proceed."""
        if method.upper() in SAFE_METHODS:
            return True
        if not self.is_community(url):
            return True
        path = urlsplit(url).path or "/"
        return any(rule.matches(method, path) for rule in self.allow)

    def handle(self, route: Any, request: Any = None) -> None:
        """Playwright route handler: continue allowed requests, abort the rest."""
        request = request if request is not None else route.request
        method = request.method
        url = request.url
        if self.allows(method, url):
            route.continue_()
            return
        self.blocked.append(BlockedRequest(method=method.upper(), url=_strip_query(url)))
        route.abort()

    def install(self, target: Any) -> None:
        """Install on a Playwright BrowserContext (preferred) or Page."""
        target.route("**/*", self.handle)
