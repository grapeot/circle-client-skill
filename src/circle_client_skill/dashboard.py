"""Notification one-stop dashboard: state assembly plus a localhost action server.

The dashboard is the interactive surface behind ``circle-client dashboard``.
Pure logic here (grouping, enrichment, cache) is offline-testable; the HTTP
layer is a thin shell. Every user click maps to exactly one explicit Circle
mutation; the server never batches or queues writes on its own.
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .client import CircleClient, CircleClientError
from .dashboard_ui import PAGE
from .formatters import _body_text
from .reactions import (
    COMMENT_REACTION_TYPE_NAMES,
    COMMENT_REACTION_TYPES,
    REACTION_EMOTES,
    is_valid_unicode,
    resolve_unicode,
    unicode_glyph,
)
from .rich_text import rich_text_message_text

VERIFIED_REACTION_KINDS: tuple[str, ...] = ("chat_room_message", "comment")

MAX_COMMENT_PAGES = 5
COMMENTS_PER_PAGE = 50
# Course-room participant lists cover the whole membership (thousands, always
# paginated); a few pages give partial names cheaply, and rows still render
# with thread structure when a name is unknown.
MAX_PARTICIPANT_PAGES = 3
MAX_ROOTS_WINDOW = 50
MAX_BACKWARD_PAGES = 12
BACKWARD_PER_PAGE = 200

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def room_uuid_of(notification: dict[str, Any]) -> str | None:
    path = notification.get("action_inbox_path") or ""
    if not isinstance(path, str) or not path:
        return None
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return last if _UUID_RE.match(last) else None


def context_key(notification: dict[str, Any]) -> tuple[Any, ...]:
    kind = notification.get("notifiable_type")
    action = notification.get("action") or ""
    if kind == "ChatRoomMessage":
        uuid = room_uuid_of(notification)
        return ("room", uuid) if uuid else ("other",)
    if kind == "Comment":
        if action == "like":
            return ("like", notification.get("post_id"))
        post_id = notification.get("post_id")
        return ("post", post_id) if post_id is not None else ("other",)
    if kind == "Post":
        if action == "like":
            return ("like", notification.get("post_id"))
        return ("post_link",)
    return ("other",)


def group_notifications(notifications: list[dict[str, Any]]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for notification in notifications:
        groups.setdefault(context_key(notification), []).append(notification)
    return groups


def _merge_by_notifiable(records: list[dict[str, Any]]) -> dict[int | None, list[dict[str, Any]]]:
    merged: dict[int | None, list[dict[str, Any]]] = {}
    for record in records:
        merged.setdefault(record.get("notifiable_id"), []).append(record)
    return merged


def _reactions_summary(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw = record.get("reactions") if record.get("reactions") is not None else record.get("reaction_summary")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "unicode": item.get("unicode"),
                "emoji": item.get("emoji"),
                "count": item.get("count", 1),
            }
        )
    return out


def _base_row(record_id: Any, *, kind: str, actor: str | None, created_at: Any, text: str, reactions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": record_id,
        "kind": kind,
        "actor_name": actor,
        "created_at": created_at,
        "text": text,
        "reactions": reactions,
    }


def room_participants_map(client: CircleClient, room_uuid: str) -> dict[int, str]:
    names: dict[int, str] = {}
    for page in range(1, MAX_PARTICIPANT_PAGES + 1):
        result = client.list_room_participants(room_uuid, page=page)
        records = result.get("records") or []
        for record in records:
            participant_id = record.get("id")
            if participant_id is None:
                continue
            names[int(participant_id)] = str(record.get("name") or "")
        if not result.get("has_next_page") or not records:
            break
    return names


def build_room_rows(
    client: CircleClient,
    room_uuid: str,
    target_ids: set[int],
    anchors: dict[int, int | None] | None = None,
) -> list[dict[str, Any]]:
    """Rows of a chat room: only the target (unread message) threads.

    The user reads unread comments, not the room feed. Notification web URLs
    carry the thread-root anchor (``#message_<root>``), which lets us jump
    straight to a thread whose root sits outside the default window.
    """
    anchors = anchors or {}
    result = client.list_chat_messages(room_uuid, previous_per_page=MAX_ROOTS_WINDOW)
    window_records = [m for m in (result.get("records") or []) if m.get("id") is not None]
    pool: dict[int, dict[str, Any]] = {int(m["id"]): m for m in window_records}
    threads: dict[int, list[dict[str, Any]]] = {}

    def fetch_replies(parent_ids: list[int]) -> None:
        for parent_id in parent_ids:
            if parent_id in threads:
                continue
            if parent_id in pool and not pool[parent_id].get("replies_count"):
                continue
            reply_page = client.fetch_chat_replies(room_uuid, parent_id)
            fetched = [m for m in (reply_page.get("records") or []) if m.get("id") is not None]
            threads[parent_id] = fetched
            for reply in fetched:
                pool.setdefault(int(reply["id"]), reply)

    included: set[int] = set()

    def include_target_thread(root_id: int) -> None:
        fetch_replies([root_id])
        included.update({root_id, *(int(m["id"]) for m in threads.get(root_id, []))})

    def resolve_if_present(target_id: int) -> bool:
        message = pool.get(target_id)
        if message is None:
            return False
        parent_id = message.get("parent_message_id")
        include_target_thread(int(parent_id) if parent_id is not None else target_id)
        return True

    unresolved = [tid for tid in target_ids if not resolve_if_present(tid)]

    still: list[int] = []
    for target_id in unresolved:
        anchor = anchors.get(target_id)
        if anchor is not None and anchor != target_id:
            fetch_replies([anchor])
            if target_id in pool:
                include_target_thread(anchor)
            else:
                still.append(target_id)
        else:
            still.append(target_id)

    if still:
        # Last resort without an anchor: scan every known reply-bearing root,
        # then walk backwards bounded if the target is still unfound.
        roots_to_scan = [root_id for root_id, root in pool.items() if root.get("replies_count") and root_id not in threads]
        if roots_to_scan:
            fetch_replies(roots_to_scan)
        resolved = set()
        for target_id in list(still):
            if resolve_if_present(target_id):
                resolved.add(target_id)
        still = [t for t in still if t not in resolved]
    if still:
        for _step in range(MAX_BACKWARD_PAGES):
            oldest = min(pool, default=None)
            if oldest is None:
                break
            older = client.list_chat_messages(room_uuid, previous_per_page=BACKWARD_PER_PAGE, cursor=oldest)
            older_records = [m for m in (older.get("records") or []) if m.get("id") is not None]
            fresh = [m for m in older_records if int(m["id"]) not in pool]
            if not fresh:
                break
            for message in fresh:
                pool.setdefault(int(message["id"]), message)
            fetch_replies([int(message["id"]) for message in fresh if message.get("replies_count")])
            resolved = set()
            for target_id in list(still):
                if resolve_if_present(target_id):
                    resolved.add(target_id)
            still = [t for t in still if t not in resolved]
            if not still:
                break

    missing_targets = still
    try:
        names = room_participants_map(client, room_uuid)
    except CircleClientError:
        names = {}
    rows = []
    for message_id in included | set(missing_targets):
        message = pool.get(message_id)
        if message is None:
            rows.append(
                {
                    "id": message_id,
                    "kind": "message",
                    "actor_name": None,
                    "created_at": None,
                    "text": "(该消息不在最近窗口内)",
                    "reactions": [],
                    "missing": True,
                }
            )
            continue
        participant_id = message.get("chat_room_participant_id")
        row = _base_row(
            message_id,
            kind="message",
            actor=names.get(int(participant_id)) if participant_id is not None else None,
            created_at=message.get("created_at"),
            text=rich_text_message_text(message),
            reactions=_reactions_summary(message),
        )
        parent_id = message.get("parent_message_id")
        row["parent_id"] = int(parent_id) if parent_id is not None else None
        parent = pool.get(int(parent_id)) if parent_id is not None else None
        if parent is not None:
            parent_participant = parent.get("chat_room_participant_id")
            parent_actor = names.get(int(parent_participant)) if parent_participant is not None else None
            row["reply_to"] = parent_actor
            row["depth"] = 1
        elif parent_id is not None:
            # The root record is outside the pool (kept as a marker row); the
            # reply still reads as a reply through depth + indent.
            row["reply_to"] = None
            row["depth"] = 1
        else:
            row["reply_to"] = None
            row["depth"] = 0
        if row.get("parent_id") is None and message.get("replies_count") and message_id not in threads:
            row["hidden_replies"] = int(message["replies_count"])
        rows.append(row)

    def _order(row: dict[str, Any]) -> tuple[str, int, str, str]:
        if row.get("missing"):
            return ("\uffff", 2, "", str(row.get("id") or ""))  # always last
        parent_id = row.get("parent_id")
        if parent_id is None:
            return (row.get("created_at") or "", 0, "", str(row.get("id") or ""))
        root = pool.get(int(parent_id))
        root_time = (root or {}).get("created_at") or row.get("created_at") or ""
        return (root_time, 1, row.get("created_at") or "", str(row.get("id") or ""))

    rows.sort(key=_order)
    return rows


def build_comment_rows(client: CircleClient, post_id: int, target_ids: set[int]) -> list[dict[str, Any]]:
    """Rows of a post's comment thread, root-time order, target chains only."""
    comments: dict[int, dict[str, Any]] = {}

    def chains_resolved() -> bool:
        if not all(tid in comments for tid in target_ids):
            return False
        for target_id in target_ids:
            cursor = comments.get(target_id)
            for _ in range(8):
                if cursor is None:
                    break
                parent_id = cursor.get("parent_comment_id")
                if parent_id is None:
                    break
                if int(parent_id) not in comments:
                    return False
                cursor = comments[int(parent_id)]
        return True

    for page in range(1, MAX_COMMENT_PAGES + 1):
        result = client.list_comments(post_id, page=page, per_page=COMMENTS_PER_PAGE)
        records = result.get("records") or []
        for comment in records:
            if comment.get("id") is not None:
                comments[int(comment["id"])] = comment
        if not result.get("has_next_page") or not records:
            break
        if chains_resolved():
            break
    children: dict[int | None, list[dict[str, Any]]] = {}
    for comment in comments.values():
        children.setdefault(comment.get("parent_comment_id"), []).append(comment)
    for siblings in children.values():
        siblings.sort(key=lambda c: (c.get("created_at") or "", c.get("id") or 0))
    included: set[int] = set()
    for target_id in target_ids:
        node = comments.get(target_id)
        if node is None:
            continue
        cursor: dict[str, Any] | None = node
        while cursor is not None:
            if cursor.get("id") is not None:
                included.add(int(cursor["id"]))
            cursor = comments.get(cursor.get("parent_comment_id"))
        stack = [node]
        while stack:
            current = stack.pop()
            for child in children.get(current.get("id"), []):
                if child.get("id") is not None and int(child["id"]) not in included:
                    included.add(int(child["id"]))
                stack.append(child)
    def _emit(comment_id: int, out: list[int]) -> None:
        out.append(comment_id)
        for child in children.get(comment_id, []):
            if child.get("id") is not None and int(child["id"]) in included:
                _emit(int(child["id"]), out)

    ordered: list[int] = []
    tops = [
        comment
        for comment in (comments.get(cid) for cid in included)
        if comment is not None
        and (comment.get("parent_comment_id") is None or int(comment.get("parent_comment_id")) not in included)
    ]
    tops.sort(key=lambda c: (c.get("created_at") or "", c.get("id") or 0))
    for top in tops:
        _emit(int(top["id"]), ordered)
    ordered += [comment_id for comment_id in included if comment_id not in ordered]
    rows = []
    for comment_id in ordered:
        comment = comments.get(comment_id)
        if comment is None:
            continue
        member = comment.get("community_member")
        actor = member.get("name") if isinstance(member, dict) else None
        parent_id = comment.get("parent_comment_id")
        parent = comments.get(parent_id) if parent_id is not None else None
        parent_member = parent.get("community_member") if isinstance(parent, dict) else None
        reply_to = parent_member.get("name") if isinstance(parent_member, dict) else None
        depth = 0
        cursor: dict[str, Any] | None = comment
        while cursor is not None:
            pid = cursor.get("parent_comment_id")
            if pid is None or int(pid) not in comments or depth > 8:
                break
            depth += 1
            cursor = comments[int(pid)]
        row = _base_row(
            comment_id,
            kind="comment",
            actor=str(actor) if actor else None,
            created_at=comment.get("created_at"),
            text=_body_text(comment),
            reactions=_reactions_summary(comment),
        )
        row["parent_id"] = parent_id
        row["reply_to"] = str(reply_to) if reply_to else None
        row["depth"] = depth
        rows.append(row)
    return rows


class DashboardCache:
    """Per-context enrichment cache keyed by the set of target ids."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[Any, ...], dict[str, Any]] = {}

    def rows_for(
        self,
        client: CircleClient,
        key: tuple[Any, ...],
        target_ids: set[int],
        builder: Any,
    ) -> list[dict[str, Any]]:
        with self._lock:
            entry = self._entries.get(key)
        if entry and set(map(int, target_ids)) <= set(entry["target_ids"]):
            return entry["rows"]
        rows = builder(client, key, target_ids)
        with self._lock:
            self._entries[key] = {"target_ids": sorted(target_ids), "rows": rows}
        return rows

    def invalidate(self, key: tuple[Any, ...]) -> None:
        """Drop one context's cached rows so the next refresh re-reads it."""
        with self._lock:
            self._entries.pop(key, None)


def _enrich_context(
    client: CircleClient,
    key: tuple[Any, ...],
    notifications: list[dict[str, Any]],
    cache: DashboardCache,
) -> dict[str, Any]:
    kind, *_id = key
    first = notifications[0]
    context: dict[str, Any] = {
        "kind": kind,
        "context_id": key[1] if kind in ("room", "post") else None,
        "title": first.get("notifiable_title"),
        "space_title": first.get("space_title"),
        "new_count": len(notifications),
    }
    links = [n.get("action_web_url") for n in notifications if n.get("action_web_url")]
    context["url"] = links[0] if links else None
    context["updated_at"] = max((n.get("created_at") or "" for n in notifications), default="")
    if kind in ("room", "post"):
        targets = _merge_by_notifiable(notifications)
        target_ids = {int(t) for t in targets if t is not None}
        try:
            if kind == "room":
                room_uuid = key[1]
                anchors: dict[int, int | None] = {}
                for notification in notifications:
                    notifiable_id = notification.get("notifiable_id")
                    match = re.search(r"#message_(\d+)", notification.get("action_web_url") or "")
                    if notifiable_id is not None:
                        anchors[int(notifiable_id)] = int(match.group(1)) if match else None
                rows = cache.rows_for(
                    client,
                    ("room", room_uuid),
                    target_ids,
                    lambda cl, k, t: build_room_rows(cl, room_uuid, t, anchors),
                )
            else:
                rows = cache.rows_for(
                    client,
                    ("post", key[1]),
                    target_ids,
                    lambda cl, k, t: build_comment_rows(cl, key[1], t),
                )
        except (CircleClientError, ValueError) as exc:
            context["error"] = str(exc)
            rows = []
        merged = {target: notes[0] for target, notes in targets.items()}
        target_rows: list[dict[str, Any]] = []
        annotated: list[dict[str, Any]] = []
        for row in rows:
            row = dict(row)
            row["is_target"] = row["id"] in set(target_ids)
            row["target"] = (
                {"kind": "chat_room_message" if kind == "room" else "comment", "id": row["id"]}
                if row["is_target"]
                else None
            )
            if row["is_target"]:
                notification = merged.get(row["id"])
                if notification is not None:
                    row["actor_name"] = notification.get("actor_name") or row["actor_name"]
                    row["actor_image"] = notification.get("actor_image")
                    row["action"] = notification.get("display_action")
                row["notification_ids"] = [n.get("id") for n in targets.get(row["id"], [])]
                target_rows.append(row)
            annotated.append(row)
        # Second pass: a reply's reply_to borrows the parent row's resolved name
        # (from participants pages or from the notification, whichever hit).
        by_id = {row["id"]: row for row in annotated}
        for row in annotated:
            parent_id = row.get("parent_id")
            if parent_id is not None and not row.get("reply_to"):
                parent_row = by_id.get(parent_id)
                if parent_row is not None and parent_row.get("actor_name"):
                    row["reply_to"] = parent_row["actor_name"]
        context["rows"] = annotated
        context["targets"] = target_rows
    else:
        context["rows"] = []
        context["targets"] = []
    return context


def _like_groups(groups: dict[tuple[Any, ...], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out = []
    for key, items in sorted(groups.items(), key=lambda kv: max_n(kv[1]), reverse=True):
        if key[0] != "like" or key[1] is None:
            continue
        actors: list[str] = []
        for notification in items:
            name = notification.get("actor_name")
            if name and name not in actors:
                actors.append(name)
        out.append(
            {
                "post_id": key[1],
                "title": items[0].get("notifiable_title"),
                "space_title": items[0].get("space_title"),
                "count": len(items),
                "actors": actors,
                "notification_ids": [n.get("id") for n in items],
                "url": next((n.get("action_web_url") for n in items if n.get("action_web_url")), None),
                "updated_at": max((n.get("created_at") or "" for n in items), default=""),
            }
        )
    return out


def max_n(items: list[dict[str, Any]]) -> str:
    return max((n.get("created_at") or "" for n in items), default="")


def _other_items(groups: dict[tuple[Any, ...], list[dict[str, Any]]], discussion_keys: set[tuple[Any, ...]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, group in groups.items():
        if key in discussion_keys or key[0] == "like":
            continue
        for notification in group:
            kind = notification.get("notifiable_type")
            items.append(
                {
                    "notification_ids": [notification.get("id")],
                    "notifiable_type": kind,
                    "actor_name": notification.get("actor_name"),
                    "display_action": notification.get("display_action"),
                    "title": notification.get("notifiable_title"),
                    "space_title": notification.get("space_title"),
                    "url": notification.get("action_web_url"),
                    "created_at": notification.get("created_at"),
                    # Flagged content needs review first; no quick mark-read.
                    "allow_mark_read": kind != "FlaggedContent",
                }
            )
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return items


def assemble_state(
    client: CircleClient,
    document: dict[str, Any],
    *,
    cache: DashboardCache,
    verified_kinds: tuple[str, ...],
    emotes: dict[str, str] | None = None,
    emotes_warning: str | None = None,
) -> dict[str, Any]:
    notifications = document.get("notifications") or []
    emotes = emotes if emotes is not None else dict(REACTION_EMOTES)
    groups = group_notifications(notifications)
    discussions: list[dict[str, Any]] = []
    discussion_keys = {
        key for key in groups if key[0] in ("room", "post", "post_link")
    }
    enrich_keys = [key for key in discussion_keys if key[0] in ("room", "post")]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            key: pool.submit(_enrich_context, client, key, groups.get(key) or [], cache)
            for key in enrich_keys
        }
        for _key, future in futures.items():
            discussions.append(future.result())
    for key in discussion_keys:
        if key[0] == "post_link":
            discussions.append(_enrich_context(client, key, groups.get(key) or [], cache))
    discussions.sort(key=lambda context: context.get("updated_at") or "", reverse=True)
    _SECTION_PRIORITY = {"room": 0, "post": 1, "post_link": 2}
    discussions.sort(key=lambda context: _SECTION_PRIORITY.get(context.get("kind"), 3))
    badge = None
    try:
        badge_result = client.get_notification_count()
        value = badge_result.get("count", badge_result) if isinstance(badge_result, dict) else badge_result
        badge = int(value) if isinstance(value, (int, str)) else None
    except Exception:
        badge = None
    return {
        "fetched_at": document.get("fetched_at"),
        "count": len(notifications),
        "badge_count": badge,
        "host": (document.get("source") or {}).get("host"),
        "verified_reaction_kinds": list(verified_kinds),
        "emotes": [
            {"name": name, "unicode": code, "glyph": unicode_glyph(code)}
            for name, code in emotes.items()
        ],
        "emotes_config_warning": emotes_warning,
        "comment_reactions": COMMENT_REACTION_TYPES,
        "sections": [
            {"id": "discussions", "title": "要回应的讨论", "contexts": discussions},
            {"id": "likes", "title": "点赞", "groups": _like_groups(groups)},
            {"id": "other", "title": "其他", "items": _other_items(groups, discussion_keys)},
        ],
    }


class ActionError(Exception):
    """A rejected dashboard action; carries the HTTP status to return."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class DashboardServer:
    """State cache + action executor shared by the dashboard HTTP server."""

    def __init__(
        self,
        settings: Any,
        *,
        port: int = 8780,
        state_dir: Path = Path("data"),
        client: CircleClient | None = None,
        timeout: float = 30,
    ) -> None:
        self.client = client or CircleClient(settings, timeout=timeout)
        self.port = port
        self.state_dir = state_dir
        self.cache = DashboardCache()
        self.state_lock = threading.Lock()
        self.notifications_by_id: dict[int, dict[str, Any]] = {}
        self.last_state: dict[str, Any] | None = None
        self.log_path = state_dir / "dashboard_log.jsonl"
        self.state_path = state_dir / "dashboard.json"
        self.verified_kinds: tuple[str, ...] = VERIFIED_REACTION_KINDS
        self.emotes, self.emotes_warning = self.load_emotes()

    def load_emotes(self) -> tuple[dict[str, str], str | None]:
        """Built-in emote set, extended by an optional gitignored emotes.json.

        File format: ``{"<semantic name>": "<unicode code>"}``. Invalid entries
        are skipped; the built-ins survive a broken file.
        """
        emotes = dict(REACTION_EMOTES)
        path = self.state_dir / "emotes.json"
        if not path.exists():
            return emotes, None
        warnings: list[str] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return emotes, f"emotes.json 无法解析，使用内置集合: {exc}"
        if not isinstance(data, dict):
            return emotes, "emotes.json 需要 {\"名字\": \"unicode\"} 形式，使用内置集合"
        for name, code in data.items():
            if not isinstance(name, str) or not name or not isinstance(code, str) or not is_valid_unicode(code):
                warnings.append(str(name) or "<空>")
                continue
            emotes[name] = code
        warning = None
        if warnings:
            warning = f"emotes.json 里跳过无效条目: {', '.join(warnings)}"
        return emotes, warning

    def allowed_origins(self) -> set[str]:
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    def build_state(self) -> dict[str, Any]:
        document = self.client.fetch_notifications()
        with self.state_lock:
            self.notifications_by_id = {
                int(n["id"]): n for n in document.get("notifications") or [] if n.get("id") is not None
            }
            state = assemble_state(
                self.client,
                document,
                cache=self.cache,
                verified_kinds=self.verified_kinds,
                emotes=self.emotes,
                emotes_warning=self.emotes_warning,
            )
            self.last_state = state
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        return state

    def _row_target_kind(self, row: dict[str, Any]) -> str:
        return "chat_room_message" if row.get("kind") == "message" else "comment"

    def _cache_key_for(self, kind: str, context: dict[str, Any]) -> tuple[Any, ...]:
        context_id = context.get("context_id")
        return ("room", context_id) if kind == "chat_room_message" else ("post", context_id)

    def _locate(
        self,
        kind: str,
        target_id: int,
        notification_id: int | None = None,
    ) -> dict[str, Any]:
        """Find the context+row this reaction targets.

        With notification_id set (unread-target path) the row must carry that
        notification; without it, any row visible on the page qualifies. The
        context is needed to invalidate its enrichment cache afterwards.
        """
        state = self.last_state
        if state is None:
            raise ActionError("当前没有 state；先刷新", 409)
        for section in state.get("sections", []):
            for context in section.get("contexts", []):
                if context.get("error"):
                    continue
                if kind != "chat_room_message" and context.get("kind") != "post":
                    continue
                if kind == "chat_room_message" and context.get("kind") != "room":
                    continue
                if notification_id is None:
                    for row in context.get("rows", []):
                        if row.get("missing"):
                            continue
                        if self._row_target_kind(row) == kind and int(row.get("id") or 0) == int(target_id):
                            return context
                else:
                    for target in context.get("targets", []):
                        ids = set(target.get("notification_ids") or [])
                        info = target.get("target") or {}
                        if (
                            notification_id in ids
                            and info.get("kind") == kind
                            and int(info.get("id") or 0) == int(target_id)
                        ):
                            return context
        raise ActionError("该消息不在当前页面上下文里；请刷新", 404)

    def react(self, payload: dict[str, Any]) -> dict[str, Any]:
        notification_id = payload.get("notification_id")
        kind = payload.get("kind")
        target_id = payload.get("target_id")
        unicode_code = str(payload.get("unicode") or "")
        reaction_type = str(payload.get("reaction_type") or "")
        if kind not in self.verified_kinds:
            raise ActionError(f"reaction target {kind!r} 未验证，暂不开放", 409)
        if notification_id is None:
            if not isinstance(target_id, int):
                raise ActionError("target_id 必须是整数")
        elif not isinstance(notification_id, int) or not isinstance(target_id, int):
            raise ActionError("notification_id / target_id 必须是整数")
        with self.state_lock:
            context = self._locate(kind, target_id, notification_id if isinstance(notification_id, int) else None)
        if kind == "comment":
            if reaction_type not in COMMENT_REACTION_TYPE_NAMES:
                raise ActionError(f"不支持的 comment 反应类型 {reaction_type!r}")
            self.client.create_comment_like(target_id, reaction_type=reaction_type, execute=True)
        elif kind == "chat_room_message":
            try:
                unicode_code = resolve_unicode(unicode_code)
            except ValueError as exc:
                raise ActionError(str(exc)) from exc
            self.client.create_reaction(kind, target_id, unicode_code, execute=True)
        else:
            raise ActionError(f"不支持的 reaction target {kind!r}")
        self.cache.invalidate(self._cache_key_for(kind, context))
        marked_read = False
        read_error = None
        if notification_id is not None:
            marked_read = True
            try:
                self.client.mark_notification_read(notification_id, execute=True)
            except CircleClientError as exc:
                marked_read = False
                read_error = str(exc)
        self.log_action(
            {
                "action": "react",
                "notification_id": notification_id,
                "target_kind": kind,
                "target_id": target_id,
                "unicode": unicode_code,
                "reaction_type": reaction_type,
                "marked_read": marked_read,
                "error": read_error,
            }
        )
        return {"marked_read": marked_read, "target_kind": kind, "target_id": target_id}

    def mark_read(self, payload: dict[str, Any]) -> dict[str, Any]:
        notification_id = payload.get("notification_id")
        if not isinstance(notification_id, int):
            raise ActionError("notification_id 必须是整数")
        with self.state_lock:
            if notification_id not in self.notifications_by_id:
                raise ActionError("通知不在当前未读集合里；请刷新", 404)
        self.client.mark_notification_read(notification_id, execute=True)
        self.log_action({"action": "mark_read", "notification_id": notification_id})
        return {"marked_read": True}

    def log_action(self, entry: dict[str, Any]) -> None:
        record = {"ts": datetime_utc_iso(), **entry}
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def datetime_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class _DashboardHTTPServer(ThreadingHTTPServer):
    def __init__(self, addr: tuple[str, int], dashboard: DashboardServer) -> None:
        super().__init__(addr, DashboardRequestHandler)
        self.dashboard = dashboard


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = "CircleClientDashboard/0.1"

    def _dashboard(self) -> DashboardServer:
        return self.server.dashboard  # type: ignore[attr-defined]

    def _send_bytes(self, body: bytes, *, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        self._send_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            status=status,
            content_type="application/json; charset=utf-8",
        )

    def _state_payload(self) -> int:
        dashboard = self._dashboard()
        try:
            state = dashboard.build_state()
        except CircleClientError as exc:
            self._send_json({"success": False, "error": str(exc)}, status=502)
            return 502
        self._send_json({"success": True, "state": state})
        return 200

    def _run_action(self, name: str) -> int:
        dashboard = self._dashboard()
        if self.headers.get("Origin") not in dashboard.allowed_origins():
            self._send_json({"success": False, "error": "Origin rejected"}, status=403)
            return 403
        content_type = self.headers.get("Content-Type") or ""
        if "application/json" not in content_type:
            self._send_json({"success": False, "error": "Content-Type must be application/json"}, status=415)
            return 415
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= 8192:
            self._send_json({"success": False, "error": "Bad request body"}, status=400)
            return 400
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("body must be a JSON object")
            result = dashboard.react(payload) if name == "react" else dashboard.mark_read(payload)
        except ActionError as exc:
            self._send_json({"success": False, "error": exc.message}, status=exc.status)
            return exc.status
        except (ValueError, CircleClientError) as exc:
            status = exc.status_code if isinstance(exc, CircleClientError) else 400
            self._send_json({"success": False, "error": str(exc)}, status=(502 if isinstance(exc, CircleClientError) else 400))
            return status
        self._send_json({"success": True, **result})
        return 200

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            self._send_bytes(
                dashboard_page().encode("utf-8"),
                status=200,
                content_type="text/html; charset=utf-8",
            )
            return
        if path == "/api/state":
            self._state_payload()
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path in ("/api/react", "/api/mark_read"):
            self._run_action(path.removeprefix("/api/"))
            return
        self._send_json({"success": False, "error": "Unknown action"}, status=404)

    def log_message(self, *args: Any) -> None:  # keep the console quiet
        return


def dashboard_page() -> str:
    return PAGE


def create_dashboard_server(
    settings: Any,
    *,
    port: int = 8780,
    state_dir: Path = Path("data"),
    timeout: float = 30,
    client: CircleClient | None = None,
) -> tuple[_DashboardHTTPServer, str]:
    """Bind the dashboard to 127.0.0.1 (only) and return the live server."""
    dashboard = DashboardServer(settings, port=port, state_dir=state_dir, timeout=timeout, client=client)
    server = _DashboardHTTPServer(("127.0.0.1", port), dashboard)
    actual_port = int(server.server_address[1])
    dashboard.port = actual_port
    return server, f"http://127.0.0.1:{actual_port}/"