"""Headless probe tooling: observe Circle pages, screenshot, capture, read back.

These helpers are for probing only. Event writes (create, edit, publish) go through
the browser UI per `skills/references/events.md`; the guard blocks every non-GET
request to the community unless the caller allowlists a specific endpoint.
"""

from .capture import RequestCapture
from .guard import AllowRule, BlockedRequest, RouteGuard
from .redact import REDACTED, Redactor, redact_headers, redact_url
from .session import ProbeSession, cookies_for_browser

__all__ = [
    "REDACTED",
    "AllowRule",
    "BlockedRequest",
    "ProbeSession",
    "Redactor",
    "RequestCapture",
    "RouteGuard",
    "cookies_for_browser",
    "redact_headers",
    "redact_url",
]
