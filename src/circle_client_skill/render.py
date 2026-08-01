from __future__ import annotations

import csv
import html
import json
from collections import OrderedDict
from pathlib import Path
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


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def render_markdown(document: dict[str, Any]) -> str:
    rows = [normalize_notification(item) for item in document.get("notifications", [])]
    lines = [
        "# Circle Notifications",
        "",
        f"- Fetched at: `{document.get('fetched_at', '')}`",
        f"- Notification group: `{document.get('source', {}).get('notification_group', '')}`",
        f"- Count: **{len(rows)}**",
        "",
        "| Status | Time | Type | Actor | Notification | Link |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        link = f"[Open]({_markdown_cell(row['url'])})" if row["url"] else ""
        values = [
            row["status"],
            row["created_at"],
            row["type"],
            row["actor"],
            row["summary"],
            link,
        ]
        lines.append("| " + " | ".join(_markdown_cell(value) for value in values) + " |")
    return "\n".join(lines) + "\n"


def render_csv(document: dict[str, Any], output: Path) -> None:
    rows = [normalize_notification(item) for item in document.get("notifications", [])]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "status", "created_at", "type", "actor", "summary", "url"],
        )
        writer.writeheader()
        writer.writerows(rows)


CATEGORY_META = OrderedDict(
    [
        ("lesson_comments", ("Lesson comments", "Needs attention", True, True)),
        ("comments", ("Comments", "Conversations to review", True, False)),
        ("other", ("Other notifications", "Everything else", True, False)),
        ("likes", ("Post likes", "Grouped low-priority activity", False, False)),
        ("members", ("New members", "Community joins", False, False)),
    ]
)


def _safe_link(value: str, host: str) -> str:
    if value.startswith("https://") or value.startswith("http://"):
        return value
    if value.startswith("/") and host:
        return f"https://{host}{value}"
    return ""


def render_html(document: dict[str, Any]) -> str:
    host = str(document.get("source", {}).get("host", ""))
    grouped: dict[str, list[dict[str, str]]] = {key: [] for key in CATEGORY_META}
    for item in document.get("notifications", []):
        category = category_for_notification(item)
        grouped[category].append(normalize_notification(item))

    sections: list[str] = []
    for key, (title, subtitle, expanded, highlight) in CATEGORY_META.items():
        rows = grouped[key]
        if not rows:
            continue
        cards: list[str] = []
        for row in rows:
            url = _safe_link(row["url"], host)
            summary = html.escape(row["summary"] or "Notification")
            actor = html.escape(row["actor"])
            meta_parts = [part for part in (actor, row["created_at"], row["type"]) if part]
            meta = " · ".join(html.escape(part) for part in meta_parts)
            content = (
                f'<a class="notification-link" href="{html.escape(url, quote=True)}" '
                'target="_blank" rel="noopener noreferrer">'
                if url
                else '<div class="notification-link no-link">'
            )
            closing = "</a>" if url else "</div>"
            cards.append(
                f'{content}<span class="status-dot" aria-hidden="true"></span>'
                f'<span class="notification-copy"><strong>{summary}</strong>'
                f'<small>{meta}</small></span><span class="arrow">↗</span>{closing}'
            )
        open_attribute = " open" if expanded else ""
        section_class = " category highlight" if highlight else " category"
        sections.append(
            f'<details class="{section_class}"{open_attribute}>'
            f"<summary><span><b>{html.escape(title)}</b><small>{html.escape(subtitle)}</small></span>"
            f'<span class="count-badge">{len(rows)}</span></summary>'
            f'<div class="notification-list">{"".join(cards)}</div></details>'
        )

    total = len(document.get("notifications", []))
    fetched_at = html.escape(str(document.get("fetched_at", "")))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Circle Notifications</title>
<style>
:root {{ color-scheme: light; --ink:#17324d; --muted:#667f97; --line:#dbe7f0; --paper:#f5f9fc;
  --card:#ffffff; --blue:#276b9c; --blue-soft:#e8f3fa; --accent:#0f7892; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:linear-gradient(150deg,#edf5fa 0%,#f8fbfd 46%,#eef4f7 100%);
  color:var(--ink); font:15px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ width:min(920px,calc(100% - 28px)); margin:0 auto; padding:48px 0 72px; }}
header {{ display:grid; grid-template-columns:1fr auto; gap:24px; align-items:end; margin-bottom:26px; }}
.eyebrow {{ color:var(--blue); font-size:12px; font-weight:750; letter-spacing:.13em; text-transform:uppercase; }}
h1 {{ margin:5px 0 7px; font:600 clamp(30px,6vw,49px)/1.06 ui-serif,Georgia,serif; letter-spacing:-.035em; }}
.subtitle {{ margin:0; color:var(--muted); }}
.total {{ min-width:104px; padding:16px 18px; border:1px solid #c8dce9; border-radius:18px;
  background:rgba(255,255,255,.7); text-align:right; box-shadow:0 10px 35px rgba(29,76,108,.07); }}
.total b {{ display:block; color:var(--blue); font:650 30px/1 ui-serif,Georgia,serif; }}
.total span {{ color:var(--muted); font-size:12px; }}
.category {{ margin:12px 0; overflow:hidden; border:1px solid var(--line); border-radius:18px;
  background:rgba(255,255,255,.86); box-shadow:0 8px 28px rgba(30,71,99,.055); }}
.category.highlight {{ border-color:#9bc7db; box-shadow:0 10px 34px rgba(15,120,146,.11); }}
summary {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding:18px 20px;
  cursor:pointer; list-style:none; }}
summary::-webkit-details-marker {{ display:none; }}
summary b {{ display:block; font-size:16px; }} summary small {{ display:block; color:var(--muted); margin-top:1px; }}
.highlight summary {{ background:linear-gradient(90deg,#e3f2f7,#f5fafc); }}
.count-badge {{ display:grid; place-items:center; min-width:34px; height:28px; padding:0 9px; border-radius:99px;
  background:var(--blue-soft); color:var(--blue); font-weight:750; }}
.notification-list {{ border-top:1px solid var(--line); }}
.notification-link {{ display:grid; grid-template-columns:9px 1fr auto; gap:13px; align-items:start; padding:15px 20px;
  color:inherit; text-decoration:none; border-bottom:1px solid #e7eef3; transition:background .15s ease; }}
a.notification-link {{ cursor:pointer; }}
.notification-link:last-child {{ border-bottom:0; }} .notification-link:hover {{ background:#f1f7fa; }}
.notification-link.is-visited {{ background:#edf2f5; color:#607386; }}
.notification-link.is-visited .status-dot {{ background:#a8b6c1; }}
.notification-link.is-visited .arrow {{ color:#9aa9b4; }}
.status-dot {{ width:7px; height:7px; margin-top:7px; border-radius:50%; background:var(--accent); }}
.notification-copy strong {{ display:block; font-size:14px; font-weight:650; }}
.notification-copy small {{ display:block; margin-top:4px; color:var(--muted); font-size:12px; }}
.arrow {{ color:#6f91a8; font-size:16px; }} .no-link .arrow {{ visibility:hidden; }}
footer {{ margin-top:20px; color:var(--muted); font-size:11px; text-align:center; }}
@media (max-width:620px) {{ main {{ width:min(100% - 18px,920px); padding:28px 0 48px; }}
  header {{ grid-template-columns:1fr; gap:15px; }} .total {{ justify-self:start; text-align:left; min-width:120px; }}
  summary,.notification-link {{ padding-left:15px; padding-right:15px; }}
  .notification-link {{ grid-template-columns:7px 1fr auto; gap:10px; }} }}
</style>
</head>
<body><main>
<header><div><div class="eyebrow">Circle · Inbox</div><h1>Notifications</h1>
<p class="subtitle">Grouped for a quieter review.</p></div>
<div class="total"><b>{total}</b><span>notifications</span></div></header>
{"".join(sections) if sections else '<p class="subtitle">No notifications found.</p>'}
<footer>Fetched {fetched_at} · Local private view</footer>
</main>
<script>
const visitedInThisPage = new Set();
document.querySelectorAll('a.notification-link').forEach((link) => {{
  link.addEventListener('click', () => {{
    visitedInThisPage.add(link.href);
    link.classList.add('is-visited');
  }});
}});
</script>
</body></html>"""
