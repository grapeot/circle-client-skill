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
