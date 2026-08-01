from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from .config import CircleSettings


class CircleClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def extract_notifications(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("notifications", "records", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return extract_notifications(data)
    return []


def has_next_page(payload: Any, *, page: int, received: int, per_page: int) -> bool:
    if isinstance(payload, dict):
        for container in (payload, payload.get("pagination"), payload.get("meta")):
            if not isinstance(container, dict):
                continue
            for key in ("has_next_page", "has_more", "has_next"):
                if key in container:
                    return bool(container[key])
            current = container.get("current_page", container.get("page"))
            total = container.get("total_pages", container.get("pages"))
            if isinstance(current, int) and isinstance(total, int):
                return current < total
            next_page = container.get("next_page")
            if next_page is not None:
                return bool(next_page)
    return received >= per_page


def _page_url(
    url: str,
    *,
    group: str,
    page: int,
    per_page: int,
    search_after: int | str | None = None,
) -> str:
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.update(
        {
            "notification_group": group,
            "page": str(page),
            "per_page": str(per_page),
        }
    )
    if search_after is not None:
        params["search_after"] = str(search_after)
    else:
        params.pop("search_after", None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))


class CircleClient:
    def __init__(
        self,
        settings: CircleSettings,
        *,
        session: requests.Session | None = None,
        timeout: float = 30,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get_json(self, url: str) -> Any:
        try:
            response = self.session.get(
                url,
                headers=self.settings.headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CircleClientError(f"Circle request failed: {type(exc).__name__}") from exc

        if response.status_code != 200:
            request_id = response.headers.get("cf-ray") or response.headers.get("x-request-id")
            suffix = f"; request_id={request_id}" if request_id else ""
            raise CircleClientError(
                f"Circle returned HTTP {response.status_code}{suffix}",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except requests.JSONDecodeError as exc:
            raise CircleClientError("Circle returned a non-JSON response") from exc

    def get_notification_count(self) -> dict[str, Any]:
        payload = self._get_json(self.settings.count_url)

        def find_count(value: Any) -> int | None:
            if isinstance(value, dict):
                for key in ("new_notifications_count", "unread_count", "count"):
                    candidate = value.get(key)
                    if isinstance(candidate, int) and not isinstance(candidate, bool):
                        return candidate
                for candidate in value.values():
                    found = find_count(candidate)
                    if found is not None:
                        return found
            return None

        count = find_count(payload)
        if count is None:
            raise CircleClientError("Circle count response had no recognized count field")
        return {"count": count, "raw": payload}

    def reset_notification_count(self, *, execute: bool = False) -> dict[str, Any]:
        preflight = {
            "operation": "reset_notification_count",
            "method": "POST",
            "url": self.settings.reset_count_url,
            "csrf_present": bool(self.settings.csrf_token),
            "cookie_present": bool(self.settings.cookie),
        }
        if not execute:
            return {"success": True, "dry_run": True, **preflight}
        if not self.settings.csrf_token or not self.settings.cookie:
            raise CircleClientError(
                "reset-count requires a current browser Cookie and X-CSRF-Token"
            )
        try:
            response = self.session.post(
                self.settings.reset_count_url,
                headers=self.settings.headers(mutation=True),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CircleClientError(f"Circle request failed: {type(exc).__name__}") from exc
        if response.status_code not in (200, 204):
            request_id = response.headers.get("cf-ray") or response.headers.get("x-request-id")
            suffix = f"; request_id={request_id}" if request_id else ""
            raise CircleClientError(
                f"Circle returned HTTP {response.status_code}{suffix}",
                status_code=response.status_code,
            )
        return {
            "success": True,
            "dry_run": False,
            **preflight,
            "status_code": response.status_code,
        }

    def fetch_notifications(
        self,
        *,
        group: str = "inbox",
        per_page: int = 100,
        max_pages: int = 500,
        stop_after_consecutive_read: int = 100,
    ) -> dict[str, Any]:
        if per_page < 1 or per_page > 500:
            raise ValueError("per_page must be between 1 and 500")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        if stop_after_consecutive_read < 0:
            raise ValueError("stop_after_consecutive_read cannot be negative")

        notifications: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_pages: set[str] = set()
        records_scanned = 0
        consecutive_read = 0
        stop_reason = "end_of_feed"
        search_after: int | str | None = None
        page = 1
        while page <= max_pages:
            url = _page_url(
                self.settings.notifications_url,
                group=group,
                page=page,
                per_page=per_page,
                search_after=search_after,
            )
            payload = self._get_json(url)

            records = extract_notifications(payload)
            fingerprint = hashlib.sha256(
                json.dumps(records, sort_keys=True, default=str).encode()
            ).hexdigest()
            if fingerprint in seen_pages:
                raise CircleClientError(
                    "Circle repeated a pagination page; stopped to avoid a loop"
                )
            seen_pages.add(fingerprint)
            for record in records:
                records_scanned += 1
                if record.get("read_at") is not None:
                    consecutive_read += 1
                    if (
                        stop_after_consecutive_read
                        and consecutive_read >= stop_after_consecutive_read
                    ):
                        stop_reason = "consecutive_read_threshold"
                        break
                    continue
                consecutive_read = 0
                record_id = str(record.get("id", ""))
                if record_id and record_id in seen_ids:
                    continue
                if record_id:
                    seen_ids.add(record_id)
                notifications.append(record)

            if stop_reason == "consecutive_read_threshold":
                break

            if not has_next_page(payload, page=page, received=len(records), per_page=per_page):
                break
            if isinstance(payload, dict) and payload.get("next_search_after") is not None:
                search_after = payload["next_search_after"]
            page += 1
        else:
            raise CircleClientError(f"Reached max_pages={max_pages} before pagination completed")

        return {
            "schema_version": 1,
            "fetched_at": datetime.now(UTC).isoformat(),
            "source": {
                "host": urlsplit(self.settings.notifications_url).netloc,
                "notification_group": group,
                "per_page": per_page,
                "pages_fetched": page,
                "records_scanned": records_scanned,
                "unread_only": True,
                "stop_after_consecutive_read": stop_after_consecutive_read,
                "stop_reason": stop_reason,
            },
            "count": len(notifications),
            "notifications": notifications,
        }
