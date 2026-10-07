"""Local-only helpers for opening notification URLs in the default browser.

This module has no network dependency. It turns a fetch artifact into a list of
openable URLs and then hands each one to the operating system's URL opener
(macOS ``open`` / Linux ``xdg-open``). The OS dispatches the URL to the browser,
which sidesteps the popup blocker that stops ``window.open`` from a web page.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from .render import category_for_notification, normalize_notification

CATEGORIES = ("lesson_comments", "comments", "likes", "members", "other", "all")

_SLEEP: Callable[[float], None] = time.sleep
_RUN: Callable[..., Any] = subprocess.run


def default_opener() -> str | None:
    """Return the platform URL opener, or None when neither is installed."""
    return shutil.which("open") or shutil.which("xdg-open")


def resolve_url(value: str, host: str) -> str:
    """Return an absolute URL for a full URL or a community-relative path."""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/") and host:
        return f"https://{host}{value}"
    return ""


def is_openable(url: str, host: str) -> bool:
    """Only allow http(s) URLs on the community host (or any host when unset)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return not host or parts.netloc == host


def plan_targets(
    document: dict[str, Any],
    *,
    category: str = "all",
    order: str = "newest",
    dedupe: bool = True,
) -> dict[str, Any]:
    """Select, validate, sort and dedupe notification targets from an artifact."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category: {category}")
    if order not in ("newest", "oldest"):
        raise ValueError(f"unknown order: {order}")

    host = str(document.get("source", {}).get("host", ""))
    candidates: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for item in document.get("notifications", []):
        item_category = category_for_notification(item)
        if category != "all" and item_category != category:
            continue
        normalized = normalize_notification(item)
        url = resolve_url(normalized["url"], host)
        if not url or not is_openable(url, host):
            skipped.append({"url": normalized["url"], "reason": "url not on the community host"})
            continue
        candidates.append(
            {"url": url, "category": item_category, "created_at": normalized["created_at"]}
        )

    candidates.sort(key=lambda target: target["created_at"], reverse=(order == "newest"))

    targets: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if dedupe and candidate["url"] in seen:
            continue
        seen.add(candidate["url"])
        targets.append(candidate)

    return {
        "category": category,
        "host": host,
        "order": order,
        "dedupe": dedupe,
        "available": len(candidates),
        "targets": targets,
        "skipped": skipped,
    }


def open_sequentially(
    targets: list[dict[str, str]],
    *,
    interval: float = 3.0,
    opener: str,
    background: bool = False,
    sleep: Callable[[float], None] = _SLEEP,
    run: Callable[..., Any] = _RUN,
) -> dict[str, Any]:
    """Open each target with the OS opener, sleeping between opens."""
    opened: list[str] = []
    failures: list[dict[str, str]] = []
    for index, target in enumerate(targets):
        url = target["url"]
        command = [opener, *(["-g"] if background else []), url]
        try:
            run(command, check=True)
            opened.append(url)
        except (OSError, subprocess.CalledProcessError) as exc:
            failures.append({"url": url, "error": str(exc)})
        if index < len(targets) - 1 and interval > 0:
            sleep(interval)
    return {
        "opened": len(opened),
        "failed": len(failures),
        "urls": opened,
        "failures": failures,
        "interval": interval,
        "background": background,
    }
