from __future__ import annotations

import base64
import json
import shlex
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from dotenv import dotenv_values, set_key


class ConfigurationError(ValueError):
    """Raised when imported browser credentials are incomplete or unsafe."""


@dataclass(frozen=True)
class CircleSettings:
    notifications_url: str
    count_url: str
    reset_count_url: str
    authorization: str
    cookie: str | None = None
    user_agent: str | None = None
    referer: str | None = None
    frontend_version: str | None = None
    csrf_token: str | None = None
    origin: str | None = None

    @property
    def base_url(self) -> str:
        """Derive the community base URL from the notifications URL."""
        parts = urlparse(self.notifications_url)
        return f"{parts.scheme}://{parts.netloc}"

    def headers(self, *, mutation: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": self.authorization,
        }
        optional = {
            "Cookie": self.cookie,
            "User-Agent": self.user_agent,
            "Referer": self.referer,
            "X-Circle-Frontend-Version": self.frontend_version,
        }
        headers.update({key: value for key, value in optional.items() if value})
        if mutation:
            mutation_headers = {
                "X-CSRF-Token": self.csrf_token,
                "Origin": self.origin,
            }
            headers.update({key: value for key, value in mutation_headers.items() if value})
        return headers


ENV_KEYS = {
    "notifications_url": "CIRCLE_CLIENT_NOTIFICATIONS_URL",
    "count_url": "CIRCLE_CLIENT_COUNT_URL",
    "reset_count_url": "CIRCLE_CLIENT_RESET_COUNT_URL",
    "authorization": "CIRCLE_CLIENT_AUTHORIZATION",
    "cookie": "CIRCLE_CLIENT_COOKIE",
    "user_agent": "CIRCLE_CLIENT_USER_AGENT",
    "referer": "CIRCLE_CLIENT_REFERER",
    "frontend_version": "CIRCLE_CLIENT_FRONTEND_VERSION",
    "csrf_token": "CIRCLE_CLIENT_CSRF_TOKEN",
    "origin": "CIRCLE_CLIENT_ORIGIN",
}


def _validate_circle_url(url: str, *, allowed_paths: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigurationError("Circle notifications URL must use HTTPS")
    if parsed.path.rstrip("/") not in allowed_paths:
        allowed = " or ".join(sorted(allowed_paths))
        raise ConfigurationError(f"cURL URL must target {allowed}")


def _jwt_claims(authorization: str) -> dict[str, object]:
    token = authorization.split(" ", 1)[-1]
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload if isinstance(payload, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _derive_urls(url: str, authorization: str) -> tuple[str, str, str]:
    parsed = urlparse(url)
    notifications_path = "/internal_api/notifications"
    count_path = f"{notifications_path}/new_notifications_count"
    reset_count_path = f"{notifications_path}/mark_all_as_read"
    query = parse_qs(parsed.query)
    community_id = query.get("community_id", [None])[0]
    if not community_id:
        community_id = _jwt_claims(authorization).get("community_id")
    count_query = urlencode({"community_id": community_id}) if community_id else ""
    notifications_url = urlunparse(parsed._replace(path=notifications_path, query="", fragment=""))
    count_url = urlunparse(parsed._replace(path=count_path, query=count_query, fragment=""))
    reset_count_url = urlunparse(parsed._replace(path=reset_count_path, query="", fragment=""))
    return notifications_url, count_url, reset_count_url


def parse_curl(command: str) -> CircleSettings:
    """Parse a browser Copy as cURL command without executing it."""
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise ConfigurationError(f"Invalid cURL quoting: {exc}") from exc

    if not tokens or Path(tokens[0]).name != "curl":
        raise ConfigurationError("Input must be a curl command")

    url: str | None = None
    headers: dict[str, str] = {}
    cookie_from_flag: str | None = None
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-H", "--header"}:
            index += 1
            if index >= len(tokens) or ":" not in tokens[index]:
                raise ConfigurationError("Malformed cURL header")
            name, value = tokens[index].split(":", 1)
            headers[name.strip().lower()] = value.strip()
        elif token in {"-b", "--cookie"}:
            index += 1
            if index >= len(tokens):
                raise ConfigurationError("Missing cURL cookie value")
            cookie_from_flag = tokens[index]
        elif token == "--url":
            index += 1
            if index >= len(tokens):
                raise ConfigurationError("Missing cURL URL")
            url = tokens[index]
        elif token.startswith("https://"):
            url = token
        index += 1

    if not url:
        raise ConfigurationError("No HTTPS URL found in cURL command")
    _validate_circle_url(
        url,
        allowed_paths={
            "/internal_api/notifications",
            "/internal_api/notifications/new_notifications_count",
            "/internal_api/notifications/mark_all_as_read",
        },
    )

    authorization = headers.get("authorization")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ConfigurationError("The copied request has no Bearer Authorization header")

    referer = headers.get("referer")
    if referer and urlparse(referer).netloc != urlparse(url).netloc:
        raise ConfigurationError("Notification URL and Referer must use the same host")

    origin = headers.get("origin")
    if origin and urlparse(origin).netloc != urlparse(url).netloc:
        raise ConfigurationError("Notification URL and Origin must use the same host")

    notifications_url, count_url, reset_count_url = _derive_urls(url, authorization)
    return CircleSettings(
        notifications_url=notifications_url,
        count_url=count_url,
        reset_count_url=reset_count_url,
        authorization=authorization,
        cookie=headers.get("cookie") or cookie_from_flag,
        user_agent=headers.get("user-agent"),
        referer=referer,
        frontend_version=headers.get("x-circle-frontend-version"),
        csrf_token=headers.get("x-csrf-token"),
        origin=origin,
    )


def save_settings(settings: CircleSettings, env_path: Path) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.touch(mode=0o600, exist_ok=True)
    for field, env_key in ENV_KEYS.items():
        value = getattr(settings, field)
        if value is not None:
            set_key(str(env_path), env_key, value, quote_mode="always")
    env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def load_settings(env_path: Path) -> CircleSettings:
    values = dotenv_values(env_path)
    missing = [
        key
        for key in (ENV_KEYS["notifications_url"], ENV_KEYS["authorization"])
        if not values.get(key)
    ]
    if missing:
        raise ConfigurationError(f"Missing configuration: {', '.join(missing)}")
    notifications_url = str(values[ENV_KEYS["notifications_url"]])
    authorization = str(values[ENV_KEYS["authorization"]])
    _, derived_count_url, derived_reset_count_url = _derive_urls(notifications_url, authorization)
    settings = CircleSettings(
        notifications_url=notifications_url,
        count_url=str(values.get(ENV_KEYS["count_url"]) or derived_count_url),
        reset_count_url=str(values.get(ENV_KEYS["reset_count_url"]) or derived_reset_count_url),
        authorization=authorization,
        cookie=values.get(ENV_KEYS["cookie"]),
        user_agent=values.get(ENV_KEYS["user_agent"]),
        referer=values.get(ENV_KEYS["referer"]),
        frontend_version=values.get(ENV_KEYS["frontend_version"]),
        csrf_token=values.get(ENV_KEYS["csrf_token"]),
        origin=values.get(ENV_KEYS["origin"]),
    )
    _validate_circle_url(
        settings.notifications_url,
        allowed_paths={"/internal_api/notifications"},
    )
    _validate_circle_url(
        settings.count_url,
        allowed_paths={"/internal_api/notifications/new_notifications_count"},
    )
    _validate_circle_url(
        settings.reset_count_url,
        allowed_paths={"/internal_api/notifications/mark_all_as_read"},
    )
    return settings


def jwt_expiration(authorization: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(_jwt_claims(authorization)["exp"]), tz=UTC)
    except (KeyError, TypeError, ValueError):
        return None
