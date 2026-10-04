"""Redaction for anything a probe writes to disk.

Two layers: structural (header names, JSON keys and URL query parameters that are
known to carry credentials) and literal (the actual credential values loaded from
the local credential store are replaced wherever they appear).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"

SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-csrf-token",
        "x-xsrf-token",
        "csrf-token",
        "x-api-key",
    }
)

_SENSITIVE_KEY = re.compile(
    r"^(cookie|set[-_]?cookie|authorization|proxy[-_]authorization|"
    r"(x[-_])?(csrf|xsrf)([-_]token)?|authenticity[-_]token|"
    r"(access|refresh|id|auth|api|bearer|session)[-_]?token|jwt|password|secret|"
    r"client[-_]secret|api[-_]?key|remember[-_]user[-_]token|_?circle[-_]session|"
    r"x[-_]amz[-_](signature|credential|security[-_]token)|signature|sig)$",
    re.IGNORECASE,
)

_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_URL = re.compile(r"https?://[^\s\"'<>]+")


def is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY.match(key.strip()))


def redact_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {
        name: (REDACTED if name.lower() in SENSITIVE_HEADERS else value)
        for name, value in headers.items()
    }


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not any(is_sensitive_key(key) for key, _ in pairs):
        return url
    cleaned = [(key, REDACTED if is_sensitive_key(key) else value) for key, value in pairs]
    return urlunsplit(parts._replace(query=urlencode(cleaned, safe="[]")))


class Redactor:
    """Redact text and JSON, including literal credential values."""

    def __init__(self, secrets: Iterable[str | None] = ()) -> None:
        # Longest first so a value that contains another is replaced whole.
        unique = {s for s in secrets if s and len(s) >= 6}
        self._secrets = sorted(unique, key=len, reverse=True)

    def text(self, value: str) -> str:
        out = value
        for secret in self._secrets:
            out = out.replace(secret, REDACTED)
        out = _BEARER.sub(f"Bearer {REDACTED}", out)
        return _URL.sub(lambda m: redact_url(m.group(0)), out)

    def json(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: (REDACTED if isinstance(key, str) and is_sensitive_key(key) else self.json(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.json(item) for item in value]
        if isinstance(value, str):
            return self.text(value)
        return value

    def body(self, raw: str | None, limit: int = 4000) -> str | None:
        """Redact a request body. JSON is redacted structurally, other text literally."""
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return self.text(raw)[:limit]
        return json.dumps(self.json(parsed), ensure_ascii=False)[:limit]


def secrets_from_cookie_header(cookie: str | None) -> list[str]:
    """Return every cookie value in a `name=value; ...` header, raw and URL-decoded."""
    if not cookie:
        return []
    values = []
    for part in cookie.split(";"):
        if "=" in part:
            value = part.split("=", 1)[1].strip()
            values.append(value)
            decoded = unquote(value)
            if decoded != value:
                values.append(decoded)
    return values
