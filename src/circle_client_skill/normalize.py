from __future__ import annotations

import json
from typing import Any


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def _nested_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(_first(value, "name", "full_name", "display_name", "title"))
    return ""


def _deep_first(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if candidate not in (None, "", [], {}):
                return candidate
        for candidate in value.values():
            found = _deep_first(candidate, keys)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(value, list):
        for candidate in value:
            found = _deep_first(candidate, keys)
            if found not in (None, "", [], {}):
                return found
    return ""


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        direct = _first(value, "text", "message", "body", "title", "name")
        if direct:
            return _text(direct)
    if value:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return ""


def normalize_notification(item: dict[str, Any]) -> dict[str, str]:
    read_value = _first(item, "read_at", "is_read", "read", "viewed_at")
    if isinstance(read_value, bool):
        status = "已读" if read_value else "未读"
    else:
        status = "已读" if read_value else "未读"

    actor = _nested_name(
        _deep_first(item, ("actor_name", "actor", "initiator", "community_member", "user"))
    )
    title = _text(
        _deep_first(item, ("notifiable_title", "space_title", "title", "subject", "headline"))
    )
    body = _text(_deep_first(item, ("body", "message", "text", "excerpt", "description")))
    action = _text(_deep_first(item, ("display_action", "action")))
    summary = " ".join(part for part in (actor, action, title) if part)
    if body and body not in summary:
        summary = f"{summary}: {body}" if summary else body

    return {
        "id": str(_first(item, "id", "uuid", "public_uid")),
        "status": status,
        "created_at": str(_first(item, "created_at", "updated_at", "timestamp")),
        "type": str(_first(item, "action", "notification_type", "type", "kind", "event_type")),
        "actor": actor,
        "summary": summary,
        "url": str(
            _deep_first(
                item,
                (
                    "action_web_url",
                    "action_web_path",
                    "url",
                    "target_url",
                    "redirect_url",
                    "action_url",
                    "web_url",
                    "path",
                ),
            )
        ),
    }


def category_for_notification(item: dict[str, Any]) -> str:
    text = json.dumps(item, ensure_ascii=False, default=str).lower()
    if "posted a comment on your lesson" in text or ("lesson" in text and "comment" in text):
        return "lesson_comments"
    if "posted a comment in" in text or "comment" in text or "replied" in text:
        return "comments"
    if "liked your post" in text or "post_like" in text or "liked" in text:
        return "likes"
    if "joined the community" in text or "new_member" in text or "joined" in text:
        return "members"
    return "other"
