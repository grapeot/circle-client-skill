from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .rich_text import rich_text_paragraphs


def _plain(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        if "text" in value:
            return str(value["text"])
        return "".join(_plain(item) for item in value.get("content", []))
    if isinstance(value, list):
        return "".join(_plain(item) for item in value)
    return str(value)


def _has_tiptap_body_document(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    body = value.get("body")
    return isinstance(body, dict) and (
        body.get("type") == "doc" or isinstance(body.get("content"), list)
    )


def _body_text(record: dict[str, Any]) -> str:
    for key in ("tiptap_body", "rich_text_body", "body"):
        value = record.get(key)
        if value is None:
            continue
        if _has_tiptap_body_document(value):
            paragraphs = rich_text_paragraphs({"rich_text_body": value})
            if paragraphs:
                return "\n\n".join(paragraphs)
        plain_source = value["body"] if isinstance(value, dict) and "body" in value else value
        text = _plain(plain_source)
        if text:
            return " ".join(text.split())
    return ""


def _truncate(value: Any, width: int) -> str:
    text = " ".join(str(value if value is not None else "").split())
    if len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def _table(rows: Iterable[Iterable[Any]], columns: list[tuple[str, int | None]]) -> str:
    normalized = [
        [_truncate(value, maximum) if maximum is not None else _truncate(value, 10_000) for value, (_, maximum) in zip(row, columns, strict=True)]
        for row in rows
    ]
    widths = []
    for index, (header, maximum) in enumerate(columns):
        values = [len(row[index]) for row in normalized]
        width = max([len(header), *values])
        widths.append(min(width, maximum) if maximum is not None else width)
    lines = ["  ".join(header.ljust(widths[index]) for index, (header, _) in enumerate(columns)).rstrip()]
    lines.extend(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip()
        for row in normalized
    )
    return "\n".join(lines)


def _short_time(value: Any) -> str:
    text = str(value or "")
    if len(text) >= 16 and text[10:11] == "T":
        return text[:16] + "Z"
    return text


def _space_group(space: dict[str, Any]) -> str:
    group = space.get("space_group") or space.get("group")
    if isinstance(group, dict):
        return str(group.get("name") or "")
    return str(space.get("space_group_name") or group or "")


def _visibility(space: dict[str, Any]) -> str:
    if space.get("is_hidden") or space.get("hidden"):
        return "hid"
    if space.get("is_private") or space.get("private"):
        return "priv"
    value = str(space.get("visibility") or "open").lower()
    if value.startswith("hid"):
        return "hid"
    if value.startswith("priv") or value in {"closed", "secret"}:
        return "priv"
    return "open"


def format_spaces_table(spaces: list) -> str:
    rows = []
    for space in spaces:
        rows.append(
            (
                space.get("id"),
                space.get("name"),
                space.get("slug"),
                str(space.get("post_type") or space.get("type") or "")[:5],
                space.get("posts_count", space.get("post_count", 0)),
                space.get("members_count", space.get("member_count", 0)),
                _space_group(space),
                _visibility(space),
            )
        )
    return _table(
        rows,
        [
            ("ID", None),
            ("NAME", 30),
            ("SLUG", 24),
            ("TYPE", 5),
            ("POSTS", None),
            ("MEMBERS", None),
            ("GROUP", 25),
            ("VIS", 4),
        ],
    )


def format_space_card(space: dict) -> str:
    return "\n".join(
        [
            f"# {space.get('name', '')}  (id={space.get('id', '')})",
            f"slug: {space.get('slug', '')}   type: {space.get('post_type') or space.get('type') or ''}   group: {_space_group(space)}",
            f"posts: {space.get('posts_count', space.get('post_count', 0))}   members: {space.get('members_count', space.get('member_count', 0))}   visibility: {_visibility(space)}",
            f"chat_room_id: {space.get('chat_room_id', '')}   chat_room_uuid: {space.get('chat_room_uuid', '')}",
            f"is_chat_participant: {str(bool(space.get('is_chat_participant'))).lower()}",
        ]
    )


def format_posts_table(posts: list, full: bool) -> str:
    # REPLIES 列仅在 post 携带 comments_count 时显示, 由 --with-counts 注入.
    has_counts = any(post.get("comments_count") is not None for post in posts)
    rows = []
    for post in posts:
        row = [
            post.get("id"),
            post.get("name"),
            post.get("slug"),
            _short_time(post.get("published_at")),
            post.get("community_member_id", post.get("author_id", "")),
        ]
        if has_counts:
            count = post.get("comments_count")
            row.append("" if count is None else count)
        if full:
            topics = post.get("topics") or []
            topic_names = [str(topic.get("name", "")) if isinstance(topic, dict) else str(topic) for topic in topics]
            row.extend([", ".join(topic_names), _body_text(post)])
        rows.append(row)
    columns: list[tuple[str, int | None]] = [
        ("ID", None),
        ("NAME", 30),
        ("SLUG", 24),
        ("PUBLISHED_AT", 20),
        ("AUTHOR_ID", None),
    ]
    if has_counts:
        columns.append(("REPLIES", None))
    if full:
        columns.extend([("TOPICS", 30), ("BODY_PREVIEW", 80)])
    return _table(rows, columns)


def format_post_card(post: dict) -> str:
    space = post.get("space")
    space_name = space.get("name", "") if isinstance(space, dict) else post.get("space_name", "")
    space_id = space.get("id", "") if isinstance(space, dict) else post.get("space_id", "")
    replies = post.get("comments_count", post.get("replies_count", 0))
    likes = post.get("likes_count", post.get("like_count", 0))
    return "\n".join(
        [
            f"# {post.get('name', '')}  (id={post.get('id', '')})",
            f"space: {space_name} ({space_id})   slug: {post.get('slug', '')}",
            f"published: {post.get('published_at', '')}   author_id: {post.get('community_member_id', post.get('author_id', ''))}",
            f"replies: {replies}   likes: {likes}",
            "---",
            _body_text(post),
            "---",
        ]
    )


def format_chat_messages_table(messages: list, pagination: dict) -> str:
    summary = (
        f"total: {pagination.get('total_count', len(messages))}   "
        f"page: first={pagination.get('first_id', '')} last={pagination.get('last_id', '')} "
        f"has_prev={str(bool(pagination.get('has_previous_page'))).lower()} "
        f"has_next={str(bool(pagination.get('has_next_page'))).lower()}"
    )
    rows = [
        (
            message.get("id"),
            _short_time(message.get("created_at")),
            message.get("chat_room_participant_id", ""),
            message.get("replies_count", 0),
            _body_text(message),
        )
        for message in messages
    ]
    table = _table(
        rows,
        [
            ("ID", None),
            ("CREATED_AT", 20),
            ("AUTHOR_PID", None),
            ("REPLIES", None),
            ("BODY_PREVIEW", 80),
        ],
    )
    return f"{summary}\n{table}"


def format_course_lessons(sections: list) -> str:
    rows = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        for lesson in section.get("lessons") or []:
            if not isinstance(lesson, dict):
                continue
            rows.append(
                (
                    section.get("id"),
                    lesson.get("id"),
                    lesson.get("name"),
                    str(lesson.get("content_kind") or ""),
                    "yes" if lesson.get("completed") else "no",
                    "yes" if section.get("is_dripped") else "no",
                )
            )
    return _table(
        rows,
        [
            ("SECTION", None),
            ("LESSON", None),
            ("NAME", 60),
            ("KIND", 8),
            ("DONE", 4),
            ("DRIP", 4),
        ],
    )


def _lesson_body(lesson: dict[str, Any]) -> dict[str, Any]:
    for key in ("rich_text_body", "serialized_rich_text_body"):
        value = lesson.get(key)
        if isinstance(value, dict):
            return value
    return {}


def format_lesson_card(lesson: dict) -> str:
    body = _lesson_body(lesson)
    text = str(body.get("circle_ios_fallback_text") or "").strip() or _body_text(lesson)
    attachments = [
        str(item.get("filename", ""))
        for item in body.get("attachments") or []
        if isinstance(item, dict) and item.get("filename")
    ]
    lines = [
        f"# {lesson.get('name', '')}  (id={lesson.get('id', '')})",
        (
            f"status: {lesson.get('status', '')}   "
            f"completed: {str(bool(lesson.get('completed'))).lower()}   "
            f"dripped: {str(bool(lesson.get('is_dripped'))).lower()}"
        ),
        (
            f"featured_media: {str(bool(lesson.get('featured_media_enabled'))).lower()}   "
            f"comments_enabled: {str(bool(lesson.get('comments_enabled'))).lower()}"
        ),
        f"chat_room_uuid: {lesson.get('chat_room_uuid', '')}",
    ]
    if attachments:
        lines.append("files: " + ", ".join(attachments))
    lines.extend(["---", text, "---"])
    return "\n".join(lines)


def format_mention_sgids_table(mapping: dict) -> str:
    rows = []
    for sgid, item in mapping.items():
        record = item if isinstance(item, dict) else {}
        shown = str(sgid)
        if len(shown) > 24:
            shown = shown[:24] + "…"
        rows.append(
            (
                record.get("name") or "",
                "" if record.get("community_member_id") is None else record.get("community_member_id"),
                "" if record.get("user_id") is None else record.get("user_id"),
                shown,
            )
        )
    return _table(
        rows,
        [
            ("NAME", 40),
            ("COMMUNITY_MEMBER_ID", None),
            ("USER_ID", None),
            ("SGID", None),
        ],
    )


def format_mentions_table(results: list) -> str:
    rows = []
    for item in results:
        record = item if isinstance(item, dict) else {}
        sgid = str(record.get("sgid") or "")
        if len(sgid) > 24:
            sgid = sgid[:24] + "…"
        rows.append((record.get("just_name", ""), record.get("id", ""), sgid))
    return _table(
        rows,
        [
            ("NAME", 40),
            ("USER_ID", None),
            ("SGID", None),
        ],
    )


def format_comment_threads(threads: dict) -> str:
    parts = []
    for root_id, replies in threads.items():
        if not replies:
            continue
        parts.append(
            f"thread {root_id}  ({len(replies)} replies)\n"
            f"{format_chat_messages_table(replies, {})}"
        )
    return "\n\n".join(parts)


def format_count(count: int) -> str:
    return str(count)


def format_auth_status(status: dict) -> str:
    configured = "yes" if status.get("configured") else "no"
    cookie = "yes" if status.get("cookie_present") else "no"
    csrf = "yes" if status.get("csrf_present") else "no"
    jwt = "yes" if status.get("jwt_present") else "no"
    return (
        f"configured: {configured}   host: {status.get('host', '')}\n"
        f"cookie: {cookie}   csrf: {csrf}   jwt: {jwt}"
    )


def format_fetch_summary(summary: dict) -> str:
    return (
        f"Fetched {summary.get('count', 0)} unread notifications from {summary.get('host', '')}\n"
        f"pages: {summary.get('pages_fetched', 0)}   per_page: {summary.get('per_page', 0)}   "
        f"saved: {summary.get('output', '')}"
    )


def format_mutation_dryrun(preflight: dict) -> str:
    raw_operation = str(preflight.get("operation", "mutation"))
    operation = {
        "reset_notification_count": "reset-count",
    }.get(raw_operation, raw_operation.replace("_", "-"))
    fields = []
    skipped = {"success", "dry_run", "operation", "method", "url"}
    for key, value in preflight.items():
        if key in skipped or value is None:
            continue
        label = {"space_id": "space", "chat_room_uuid": "room"}.get(
            key, key.removesuffix("_present")
        )
        if key.endswith("_present"):
            rendered = "present" if value else "missing"
        elif isinstance(value, str) and key in {"name", "text"}:
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = str(value).lower() if isinstance(value, bool) else str(value)
        fields.append(f"{label}: {rendered}")
    detail = f"  {'   '.join(fields)}" if fields else ""
    confirm = operation.upper()
    return f"DRY-RUN: {operation}\n{detail}\nRun with --execute --confirm {confirm} to perform."


def format_mutation_result(result: dict, operation: str) -> str:
    operation = operation.replace("_", "-")
    if operation in {"create-post", "update-post"}:
        post = result.get("post", result)
        verb = "created" if operation == "create-post" else "updated"
        suffix = f" in space {post.get('space_id')}" if post.get("space_id") is not None else ""
        return f"OK: {verb} post #{post.get('id', '')} {json.dumps(post.get('name', ''), ensure_ascii=False)}{suffix}"
    if operation == "delete-post":
        return f"OK: deleted post {result.get('slug', '')}"
    if operation == "reply-post":
        comment = result.get("comment", result)
        return f"OK: replied to post {comment.get('post_id', result.get('post_id', ''))} (comment id={comment.get('id', '')})"
    if operation == "upload-image":
        return f"OK: uploaded image (signed_id={result.get('signed_id', '')})"
    if operation == "chat-send":
        message = result.get("message", result)
        room = result.get("chat_room_uuid", "")
        return f"OK: sent chat message (creation_uuid={message.get('creation_uuid', '')}) to room {room}"
    if operation == "update-chat-message":
        message = result.get("message")
        message_id = result.get("message_id", "")
        if not message_id and isinstance(message, dict):
            message_id = message.get("id", "")
        room = result.get("chat_room_uuid", "")
        return f"OK: updated chat message #{message_id} in room {room}"
    if operation == "reset-count":
        return "OK: reset notification count"
    if operation == "mark-notification-read":
        return f"OK: marked notification {result.get('notification_id', '')} as read"
    return f"OK: {operation}"


def format_unreplied_table(messages: list) -> str:
    rows = []
    for message in messages:
        participants = message.get("thread_participants_preview") or []
        names = [
            str(participant.get("name") or participant.get("display_name") or "")
            for participant in participants
            if isinstance(participant, dict)
        ]
        rows.append(
            (
                message.get("id"),
                _short_time(message.get("created_at")),
                message.get("replies_count", 0),
                f"[{', '.join(name for name in names if name)}]",
                _body_text(message),
            )
        )
    return _table(
        rows,
        [
            ("ID", None),
            ("CREATED_AT", 20),
            ("REPLIES", None),
            ("PARTICIPANTS", 30),
            ("BODY_PREVIEW", 80),
        ],
    )
