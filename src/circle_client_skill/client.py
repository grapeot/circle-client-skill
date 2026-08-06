from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
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

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any | None = None,
        params: dict[str, str] | None = None,
        mutation: bool = False,
        accept_statuses: tuple[int, ...] = (200, 201, 202, 204),
    ) -> Any:
        """Send a request and return parsed JSON (or None for 204)."""
        if params:
            parts = urlsplit(url)
            existing = dict(parse_qsl(parts.query, keep_blank_values=True))
            existing.update(params)
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(existing), ""))
        try:
            response = self.session.request(
                method,
                url,
                headers=self.settings.headers(mutation=mutation),
                json=json_body if json_body is not None else None,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CircleClientError(f"Circle request failed: {type(exc).__name__}") from exc
        if response.status_code not in accept_statuses:
            request_id = response.headers.get("cf-ray") or response.headers.get("x-request-id")
            suffix = f"; request_id={request_id}" if request_id else ""
            body_snippet = response.text[:200] if response.text else ""
            raise CircleClientError(
                f"Circle returned HTTP {response.status_code}{suffix}"
                + (f" [body: {body_snippet}]" if body_snippet else ""),
                status_code=response.status_code,
            )
        if response.status_code == 204 or not response.text:
            return None
        try:
            return response.json()
        except requests.JSONDecodeError as exc:
            raise CircleClientError("Circle returned a non-JSON response") from exc

    # ---- Spaces ----

    def list_spaces(self) -> dict[str, Any]:
        """List all visible spaces in the community."""
        return self._request("GET", f"{self.settings.base_url}/internal_api/spaces")

    def get_space(self, space_id: int) -> dict[str, Any]:
        """Get metadata for a single space."""
        return self._request("GET", f"{self.settings.base_url}/internal_api/spaces/{space_id}")

    def list_space_topics(self, space_id: int) -> dict[str, Any]:
        """List topics (tags) for a space."""
        return self._request("GET", f"{self.settings.base_url}/internal_api/spaces/{space_id}/topics")

    # ---- Posts ----

    def list_posts(
        self,
        space_id: int,
        *,
        page: int = 1,
        per_page: int = 24,
    ) -> dict[str, Any]:
        """List posts in a space."""
        return self._request(
            "GET",
            f"{self.settings.base_url}/internal_api/spaces/{space_id}/posts",
            params={
                "include_top_pinned_post": "true",
                "used_on": "posts",
                "per_page": str(per_page),
                "page": str(page),
            },
        )

    def get_post(self, space_id: int, slug: str) -> dict[str, Any]:
        """Get a single post by slug."""
        return self._request(
            "GET",
            f"{self.settings.base_url}/internal_api/spaces/{space_id}/posts/{slug}",
        )

    def create_post(
        self,
        space_id: int,
        *,
        name: str,
        user_id: int,
        tiptap_body: dict[str, Any] | None = None,
        topics: list[int] | None = None,
        status: str = "published",
    ) -> dict[str, Any]:
        """Create a new post in a space. Requires mutation headers (CSRF)."""
        if tiptap_body is None:
            tiptap_body = {
                "body": {"type": "doc", "content": [{"type": "paragraph"}]},
                "inline_attachments": [],
                "sgids_to_object_map": {},
            }
        body = {
            "post": {
                "name": name,
                "space_id": space_id,
                "status": status,
                "user_id": user_id,
                "tiptap_body": tiptap_body,
                "topics": topics or [],
                "slug": "",
                "published_at": None,
                "hide_meta_info": False,
                "hide_from_featured_areas": False,
                "is_comments_closed": False,
                "is_comments_disabled": False,
                "is_liking_disabled": False,
                "is_truncation_disabled": False,
                "meta_tag_attributes": {},
                "pin_to_top": False,
            }
        }
        return self._request(
            "POST",
            f"{self.settings.base_url}/internal_api/spaces/{space_id}/posts",
            json_body=body,
            mutation=True,
        )

    def update_post(
        self,
        space_id: int,
        slug: str,
        *,
        post_id: int,
        name: str,
        user_id: int,
        tiptap_body: dict[str, Any] | None = None,
        topics: list[int] | None = None,
        status: str = "published",
    ) -> dict[str, Any]:
        """Update an existing post. Requires mutation headers (CSRF)."""
        if tiptap_body is None:
            tiptap_body = {
                "body": {"type": "doc", "content": [{"type": "paragraph"}]},
                "inline_attachments": [],
                "sgids_to_object_map": {},
            }
        body = {
            "post": {
                "id": post_id,
                "name": name,
                "space_id": space_id,
                "slug": slug,
                "status": status,
                "user_id": user_id,
                "tiptap_body": tiptap_body,
                "topics": topics or [],
                "hide_meta_info": False,
                "hide_from_featured_areas": False,
                "is_comments_closed": False,
                "is_comments_disabled": False,
                "is_liking_disabled": False,
                "is_truncation_disabled": False,
                "meta_tag_attributes": {},
                "pin_to_top": False,
            }
        }
        return self._request(
            "PATCH",
            f"{self.settings.base_url}/internal_api/spaces/{space_id}/posts/{slug}",
            json_body=body,
            mutation=True,
        )

    def delete_post(self, space_id: int, slug: str) -> dict[str, Any] | None:
        """Delete a post by slug. Requires mutation headers (CSRF)."""
        return self._request(
            "DELETE",
            f"{self.settings.base_url}/internal_api/spaces/{space_id}/posts/{slug}",
            mutation=True,
            accept_statuses=(200, 204),
        )

    def get_post_details(self, post_ids: list[int], space_id: int) -> list[dict[str, Any]]:
        """Get post policies (can_manage, can_update, can_destroy, etc.)."""
        ids_param = ",".join(str(i) for i in post_ids)
        result = self._request(
            "GET",
            f"{self.settings.base_url}/internal_api/post_details",
            params={"post_ids": ids_param, "space_id": str(space_id)},
        )
        return result if isinstance(result, list) else []

    # ---- Comments (post replies) ----

    def list_comments(self, post_id: int, *, page: int = 1, per_page: int = 15) -> dict[str, Any]:
        """List comments on a post."""
        return self._request(
            "GET",
            f"{self.settings.base_url}/internal_api/posts/{post_id}/comments",
            params={"per_page": str(per_page), "page": str(page)},
        )

    def create_comment(
        self,
        post_id: int,
        *,
        text: str,
        parent_comment_id: int | None = None,
    ) -> dict[str, Any]:
        """Reply to a post. Requires mutation headers (CSRF)."""
        body = {
            "comment": {
                "body": "",
                "tiptap_body": {
                    "body": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": text}],
                            }
                        ],
                    },
                    "inline_attachments": [],
                    "sgids_to_object_map": {},
                },
            }
        }
        if parent_comment_id is not None:
            body["comment"]["parent_comment_id"] = parent_comment_id
        return self._request(
            "POST",
            f"{self.settings.base_url}/internal_api/posts/{post_id}/comments",
            json_body=body,
            mutation=True,
            accept_statuses=(200, 201),
        )

    # ---- Image upload ----

    def upload_image(self, file_path: str | Path) -> dict[str, Any]:
        """Upload an image to Circle. Returns dict with signed_id, url, etc.

        Two-step: POST to create blob, then PUT file bytes to the signed S3 URL.
        Requires mutation headers (CSRF) for the POST.
        """
        path = Path(file_path)
        file_content = path.read_bytes()
        checksum = base64.b64encode(hashlib.md5(file_content).digest()).decode("utf-8")
        content_type = mimetypes.guess_type(str(path))[0] or "image/png"

        blob = self._request(
            "POST",
            f"{self.settings.base_url}/internal_api/direct_uploads",
            json_body={
                "blob": {
                    "filename": path.name,
                    "byte_size": len(file_content),
                    "checksum": checksum,
                    "content_type": content_type,
                    "metadata": {"identified": True},
                }
            },
            mutation=True,
        )
        if not isinstance(blob, dict) or "direct_upload" not in blob:
            raise CircleClientError("direct_uploads did not return a direct_upload field")
        put_url = blob["direct_upload"]["url"]
        put_headers = blob["direct_upload"]["headers"]
        try:
            put_response = self.session.put(put_url, headers=put_headers, data=file_content, timeout=self.timeout)
        except requests.RequestException as exc:
            raise CircleClientError(f"S3 PUT request failed: {type(exc).__name__}") from exc
        if put_response.status_code not in (200, 204):
            raise CircleClientError(
                f"S3 PUT failed with HTTP {put_response.status_code}",
                status_code=put_response.status_code,
            )
        return blob

    # ---- Chat ----

    def list_chat_messages(
        self,
        chat_room_uuid: str,
        *,
        previous_per_page: int = 0,
        next_per_page: int = 50,
        before_creation_uuid: str | None = None,
    ) -> dict[str, Any]:
        """List messages in a chat room.

        Circle chat uses cursor-based pagination via before_creation_uuid,
        not page numbers. Set previous_per_page to fetch older messages
        and next_per_page to fetch newer ones.
        """
        params: dict[str, str] = {
            "previous_per_page": str(previous_per_page),
            "next_per_page": str(next_per_page),
        }
        if before_creation_uuid:
            params["before_creation_uuid"] = before_creation_uuid
        return self._request(
            "GET",
            f"{self.settings.base_url}/internal_api/chat_rooms/{chat_room_uuid}/messages",
            params=params,
        )

    def fetch_chat_replies(
        self,
        chat_room_uuid: str,
        parent_message_id: int | str,
        *,
        per_page: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch thread replies for a specific message.

        Uses the same messages endpoint with parent_message_id as a query param.
        Returns a list of reply message records.
        """
        result = self._request(
            "GET",
            f"{self.settings.base_url}/internal_api/chat_rooms/{chat_room_uuid}/messages",
            params={
                "previous_per_page": str(per_page),
                "next_per_page": "0",
                "parent_message_id": str(parent_message_id),
            },
        )
        if isinstance(result, dict):
            records = result.get("records")
            return records if isinstance(records, list) else []
        return result if isinstance(result, list) else []

    def send_chat_message(
        self,
        chat_room_uuid: str,
        *,
        chat_room_participant_id: int,
        text: str,
        parent_message_id: int | None = None,
    ) -> dict[str, Any]:
        """Send a message to a chat room. If parent_message_id is set, creates a thread reply."""
        body = {
            "chat_room_message": {
                "chat_room_participant_id": chat_room_participant_id,
                "rich_text_body": {
                    "body": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": text}],
                            }
                        ],
                    },
                    "attachments": [],
                },
                "unfurl_urls": {},
            }
        }
        if parent_message_id is not None:
            body["chat_room_message"]["parent_message_id"] = parent_message_id
        return self._request(
            "POST",
            f"{self.settings.base_url}/internal_api/chat_rooms/{chat_room_uuid}/messages",
            json_body=body,
            mutation=True,
            accept_statuses=(200, 202),
        )

    # ---- Notifications ----

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
