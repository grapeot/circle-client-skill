from __future__ import annotations

from typing import Any


def build_rich_text_body(text: str, mention_sgids: list[str] | None = None) -> dict[str, Any]:
    """Build a chat ``rich_text_body``.

    With no sgids the body matches ``send_chat_message`` before mention support:
    one paragraph, one text node, newlines left inside that node. With sgids, the
    first paragraph is one mention node per sgid, then a single text node whose
    text is a leading space plus the first line. Later non-empty lines are their
    own paragraphs. Sgids are server-signed and are not validated here.
    """
    if not mention_sgids:
        return {
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
        }
    lines = text.splitlines() or [""]
    first_content: list[dict[str, Any]] = [
        {"type": "mention", "attrs": {"sgid": sgid}} for sgid in mention_sgids
    ]
    first_content.append({"type": "text", "text": " " + lines[0]})
    paragraphs: list[dict[str, Any]] = [{"type": "paragraph", "content": first_content}]
    for line in lines[1:]:
        if line == "":
            paragraphs.append({"type": "paragraph"})
            continue
        paragraphs.append({"type": "paragraph", "content": [{"type": "text", "text": line}]})
    return {
        "body": {"type": "doc", "content": paragraphs},
        "attachments": [],
    }


def _mention_names(rich: dict[str, Any]) -> dict[str, str]:
    members = rich.get("community_members")
    if not isinstance(members, list):
        return {}
    names: dict[str, str] = {}
    for member in members:
        if not isinstance(member, dict):
            continue
        sgid = member.get("sgid")
        name = member.get("name")
        if isinstance(sgid, str) and sgid and isinstance(name, str) and name and sgid not in names:
            names[sgid] = name
    return names


def _render_inline(nodes: Any, names: dict[str, str]) -> str:
    if not isinstance(nodes, list):
        return ""
    parts: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = node.get("type")
        if kind == "text":
            text = node.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif kind == "hardBreak":
            parts.append("\n")
        elif kind == "mention":
            attrs = node.get("attrs")
            sgid = attrs.get("sgid") if isinstance(attrs, dict) else None
            name = names.get(sgid) if isinstance(sgid, str) else None
            parts.append(f"@{name}" if name else "@…")
    return "".join(parts)


def rich_text_paragraphs(record: dict[str, Any]) -> list[str]:
    """Return non-empty paragraph strings from a message's tiptap body.

    Empty paragraph blocks are visual spacing and are skipped. Mention nodes
    become ``@Name`` via ``community_members``; an unresolved sgid becomes ``@…``.
    ``hardBreak`` is a newline inside the paragraph. Missing ``rich_text_body``
    yields an empty list; fallback text is handled by ``rich_text_message_text``.
    """
    rich = record.get("rich_text_body")
    if not isinstance(rich, dict):
        return []
    body = rich.get("body")
    if not isinstance(body, dict):
        return []
    content = body.get("content")
    if not isinstance(content, list):
        return []
    names = _mention_names(rich)
    paragraphs: list[str] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "paragraph":
            continue
        rendered = _render_inline(block.get("content"), names)
        if rendered:
            paragraphs.append(rendered)
    return paragraphs


def rich_text_message_text(record: dict[str, Any]) -> str:
    """Join paragraphs with a blank line, else use stripped iOS fallback text."""
    paragraphs = rich_text_paragraphs(record)
    if paragraphs:
        return "\n\n".join(paragraphs)
    rich = record.get("rich_text_body")
    if isinstance(rich, dict):
        fallback = rich.get("circle_ios_fallback_text")
        if isinstance(fallback, str) and fallback.strip():
            return fallback.strip()
    return ""
