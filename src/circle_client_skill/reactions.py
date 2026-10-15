from __future__ import annotations

from typing import Any

# Semantic name -> Circle's reaction unicode code (lowercase hex, "-fe0f" suffix
# where the emoji presentation selector applies). The unicode strings are the
# wire format Circle echoes back in `reactions` arrays on message records.
REACTION_EMOTES: dict[str, str] = {
    "heart": "2764-fe0f",
    "thumb_up": "1f44d",
    "star": "2b50",
}

# Payload key per reactable target type, as captured on the wire for chat room
# messages. `comment` and `post` follow the same polymorphic pattern but must
# stay behind the verify gate (see dashboard.VERIFIED_REACTION_KINDS) until a
# live round-trip confirms them.
REACTION_TARGET_KEYS: dict[str, str] = {
    "chat_room_message": "chat_room_message",
    "comment": "comment",
    "post": "post",
}

EMOJI_GLYPHS: dict[str, str] = {
    "2764-fe0f": "❤️",
    "1f44d": "👍",
    "2b50": "⭐",
}

# Post comments use Circle's legacy named like types (POST /user_likes with
# ``user_likeable_type``), a separate system from the unicode /reactions
# pipeline used by chat messages. Keys come from the comment's
# reaction_summary.counts; glyphs are our rendering choice.
COMMENT_REACTION_TYPES: list[dict[str, str]] = [
    {"type": "like", "glyph": "👍"},
    {"type": "love", "glyph": "❤️"},
    {"type": "celebrate", "glyph": "🎉"},
    {"type": "support", "glyph": "💪"},
    {"type": "insightful", "glyph": "💡"},
    {"type": "funny", "glyph": "😂"},
]

COMMENT_REACTION_TYPE_NAMES = {entry["type"] for entry in COMMENT_REACTION_TYPES}


def resolve_unicode(name_or_unicode: str) -> str:
    """Map a semantic emote name to Circle's unicode code, else pass through."""
    value = (name_or_unicode or "").strip()
    emote = REACTION_EMOTES.get(value.lower())
    if emote:
        return emote
    if not value or not is_valid_unicode(value):
        raise ValueError(
            f"Unsupported reaction {value!r}; use one of {sorted(REACTION_EMOTES)} "
            "or a hex unicode code such as '2764-fe0f'"
        )
    return value


def is_valid_unicode(code: str) -> bool:
    parts = code.split("-")
    return all(part and all(ch in "0123456789abcdefABCDEF" for ch in part) for part in parts)


def reaction_glyph(unicode: str, emoji_label: Any = None) -> str:
    literal = EMOJI_GLYPHS.get(unicode) if isinstance(unicode, str) else None
    if literal:
        return literal
    if isinstance(emoji_label, str) and emoji_label:
        return emoji_label
    return "🙂"