"""Put content into course lessons: manifests, media nodes, and the browser steps of the lesson editor.

The admin API calls (list sections with drafts, create/rename a section, create a draft lesson) live in
``CircleClient``. This module holds the rest:

- A lesson manifest is a JSON file ``{"title": str, "items": [...]}`` where each item is either
  ``{"html": "<p>...</p>"}`` or ``{"media": "<path>", "kind": "image" | "video", "portrait": bool}``.
  Media paths are relative to the manifest. The converter that produces manifests (Markdown, tables to
  images, ...) belongs to the caller; this module only consumes the contract.
- Media are uploaded once through the direct-upload API and cached by content hash, then turned into
  tiptap ``image`` / ``file`` nodes.
- The browser steps run against a human-visible Chrome (``open-browser``) over CDP. Each step refuses to
  touch a lesson that is not a draft unless the caller passes ``allow_published``.

Observed behaviour this code depends on (2026-10, see skills/references/course_lessons.md):
the editor copies its JSON into the form on a debounce, so Save right after a programmatic change stores
the old body; Circle drops leading and trailing empty paragraphs; the Customize media button only renders
while the pointer is over the player; the lesson editor's own player is wider than the dialog preview;
deleting a chapter asks for confirmation.
Right after a featured video upload Circle is still processing it, and the dialog preview cannot seek
past the part that is ready (2026-10-21: "Add at 00:10" when 03:49 was wanted), so the chapter step waits
for the player and retries each seek within a bounded budget.
The same Customize media dialog exists on a published post's video, so ``set_media_settings`` also
drives posts (``open_post`` + ``open_customize_media_on_player``; on a post page the button sits over
the player, not at the lesson editor's fixed spot). A transcript containing a bare ``&``, ``<`` or ``>``
makes the dialog's Save silently do nothing, so the transcript is checked before anything is touched.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_SECTION_NAME = 100
SAVE_SETTLE_MS = 2500
EDITOR_JS = "[...document.querySelectorAll('.ProseMirror')].find(e => e.editor).editor"


class ManifestError(ValueError):
    pass


# ---------------------------------------------------------------- manifests and nodes


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Read and validate a lesson manifest; media paths come back absolute."""
    path = Path(path)
    data = json.loads(path.read_text())
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("title"), str)
        or not data["title"].strip()
    ):
        raise ManifestError("manifest needs a non-empty string 'title'")
    items = data.get("items")
    if not isinstance(items, list):
        raise ManifestError("manifest needs an 'items' list")
    out = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ManifestError(f"item {i} is not an object")
        if "html" in item:
            if not isinstance(item["html"], str):
                raise ManifestError(f"item {i}: 'html' must be a string")
            out.append({"html": item["html"]})
            continue
        kind = item.get("kind")
        if kind not in ("image", "video") or not isinstance(item.get("media"), str):
            raise ManifestError(f"item {i}: needs 'html', or 'media' with kind 'image' or 'video'")
        media = (path.parent / item["media"]).resolve()
        if not media.is_file():
            raise ManifestError(f"item {i}: media file not found: {media}")
        out.append({"media": str(media), "kind": kind, "portrait": bool(item.get("portrait"))})
    return {"title": data["title"].strip(), "items": out}


def manifest_summary(manifest: dict[str, Any]) -> dict[str, int]:
    items = manifest["items"]
    return {
        "html": sum(1 for i in items if "html" in i),
        "images": sum(1 for i in items if i.get("kind") == "image"),
        "videos": sum(1 for i in items if i.get("kind") == "video"),
    }


def media_node(kind: str, blob: dict[str, Any], *, portrait: bool = False) -> dict[str, Any]:
    """A tiptap node for an uploaded blob: ``file`` for video, ``image`` (full or half width) for images."""
    if kind == "video":
        return {"type": "file", "attrs": {"signed_id": blob["signed_id"]}}
    attrs: dict[str, Any] = {
        "url": blob["url"],
        "signed_id": blob["signed_id"],
        "content_type": blob.get("content_type") or "image/png",
        "width": "100%",
        "alignment": "left",
    }
    if portrait:
        attrs["width_ratio"] = 0.5
    return {"type": "image", "attrs": attrs}


def strip_empty_edges(types: list[str]) -> list[str]:
    """Node-type sequence without leading/trailing paragraphs, which Circle may drop on save."""
    keep = [i for i, t in enumerate(types) if t != "paragraph"]
    return types[keep[0] : keep[-1] + 1] if keep else []


def check_section_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("section name is empty")
    if len(name) > MAX_SECTION_NAME:
        raise ValueError(
            f"section name is {len(name)} characters; Circle allows at most {MAX_SECTION_NAME}"
        )
    return name


def parse_chapters(text: str) -> list[tuple[int, str]]:
    """Chapters as lines of ``MM:SS Title`` or ``H:MM:SS Title``; blank lines and ``#`` comments skipped."""
    chapters: list[tuple[int, str]] = []
    for n, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(?:(\d+):)?(\d{1,2}):(\d{2})\s+(.+)$", line)
        if not m:
            raise ValueError(f"chapter line {n}: expected 'MM:SS Title', got {line!r}")
        seconds = int(m[1] or 0) * 3600 + int(m[2]) * 60 + int(m[3])
        chapters.append((seconds, m[4].strip()))
    if not chapters:
        raise ValueError("no chapters found")
    if chapters[0][0] != 0:
        raise ValueError("the first chapter must start at 00:00")
    if [s for s, _ in chapters] != sorted({s for s, _ in chapters}):
        raise ValueError("chapter times must be strictly increasing")
    return chapters


def mmss(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


@dataclass
class UploadCache:
    """Direct-upload results keyed by absolute path, invalidated by SHA-1. Blobs are community-wide."""

    path: Path

    def _load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def get_or_upload(
        self, file: str | Path, upload: Callable[[Path], dict[str, Any]]
    ) -> tuple[dict[str, Any], bool]:
        file = Path(file).resolve()
        digest = hashlib.sha1(file.read_bytes()).hexdigest()
        cache = self._load()
        hit = cache.get(str(file))
        if hit and hit.get("sha1") == digest:
            return hit, False
        blob = upload(file)
        hit = {
            "sha1": digest,
            "signed_id": blob["signed_id"],
            "url": blob.get("url"),
            "content_type": blob.get("content_type"),
        }
        cache[str(file)] = hit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(cache, indent=1))
        return hit, True


def build_parts(manifest: dict[str, Any], blobs: dict[str, dict[str, Any]]) -> list[Any]:
    """Editor parts in reading order: HTML strings and node dicts."""
    parts: list[Any] = []
    for item in manifest["items"]:
        if "html" in item:
            parts.append(item["html"])
        else:
            parts.append(
                media_node(item["kind"], blobs[item["media"]], portrait=item.get("portrait", False))
            )
    return parts


# ---------------------------------------------------------------- browser steps


def editor_url(base_url: str, space_id: int, lesson_id: int) -> str:
    return f"{base_url}/settings/courses/{space_id}/lessons/{lesson_id}/edit"


def connect_page(playwright: Any, cdp: str, host: str) -> tuple[Any, Any]:
    browser = playwright.chromium.connect_over_cdp(cdp)
    pages = [pg for ctx in browser.contexts for pg in ctx.pages if host in pg.url]
    if not pages:
        raise RuntimeError(f"no tab on {host} in the browser at {cdp}; start it with open-browser")
    page = pages[0]
    page.on("dialog", lambda d: d.accept())  # "leave page?" after an unsaved fill
    return browser, page


def open_editor(page: Any, url: str, *, allow_published: bool = False) -> None:
    page.goto(url)
    page.locator(".ProseMirror").first.wait_for()
    page.wait_for_timeout(1500)
    if not allow_published and not is_draft(page):
        raise RuntimeError("lesson is published; refusing to edit it without --allow-published")


def is_draft(page: Any) -> bool:
    return bool(page.locator("input[name=status]").first.is_checked())


def save_lesson(page: Any, lesson_id: int) -> tuple[int, str]:
    with page.expect_response(
        lambda r: f"/lessons/{lesson_id}" in r.url and r.request.method in ("PUT", "PATCH")
    ) as resp:
        page.get_by_role("button", name="Save", exact=True).click()
    if not resp.value.ok:
        raise RuntimeError(f"Save returned HTTP {resp.value.status}")
    return resp.value.status, resp.value.request.post_data or ""


def set_lesson_name(page: Any, title: str) -> None:
    page.get_by_role("button", name="Edit lesson name").click()
    page.wait_for_timeout(800)
    if page.evaluate("document.activeElement.tagName") != "INPUT":
        raise RuntimeError("the lesson name input did not open")
    page.keyboard.press("Meta+a" if "Mac" in page.evaluate("navigator.platform") else "Control+a")
    page.keyboard.insert_text(title)
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)


def set_lesson_thumbnail(page: Any, image: str) -> None:
    """Left-panel thumbnail: setting the file opens an "Upload thumbnail" crop dialog that must be confirmed.
    A 16:9 image fills the crop box, so the default crop keeps the whole picture."""
    page.locator("input[type=file][name=thumbnail]").set_input_files(image)
    crop = page.get_by_role("dialog", name="Upload thumbnail")
    crop.wait_for()
    page.wait_for_timeout(1000)
    crop.get_by_role("button", name="Save changes").click()
    crop.wait_for(state="hidden")
    page.wait_for_timeout(1500)


REBUILD_JS = f"""(parts) => {{
  const ed = {EDITOR_JS};
  const end = () => ed.state.doc.content.size;
  ed.commands.setContent('');
  for (const p of parts) ed.commands.insertContentAt(end(), p);
  ed.commands.setTextSelection(1);
  return ed.getJSON().content.map(n => n.type);
}}"""
READ_JS = f"() => {EDITOR_JS}.getJSON().content.map(n => n.type)"


def fill_lesson(
    page: Any,
    *,
    url: str,
    lesson_id: int,
    title: str,
    parts: list[Any],
    expected_media: int,
    thumbnail: str | None = None,
    save: bool = True,
    allow_published: bool = False,
) -> dict[str, Any]:
    """Rename, rebuild the body, optionally set the lesson thumbnail, Save, reload and read back."""
    open_editor(page, url, allow_published=allow_published)
    set_lesson_name(page, title)
    built = page.evaluate(REBUILD_JS, parts)
    media = sum(1 for t in built if t in ("image", "file"))
    if media != expected_media:
        raise RuntimeError(f"built {media} media nodes, expected {expected_media}")
    if thumbnail:
        set_lesson_thumbnail(page, thumbnail)
    page.wait_for_timeout(SAVE_SETTLE_MS)  # the form copies the editor JSON on a debounce
    result: dict[str, Any] = {"built_nodes": len(built), "media": media, "saved": False}
    if not save:
        return result
    if not allow_published and not is_draft(page):
        raise RuntimeError("status changed away from Draft; not saving")
    status, body = save_lesson(page, lesson_id)
    image_count = sum(1 for p in parts if isinstance(p, dict) and p.get("type") == "image")
    if body.count('"image"') < image_count:
        raise RuntimeError("the Save request does not carry the new body (saved too early?)")
    page.wait_for_timeout(1500)
    page.reload()
    page.locator(".ProseMirror").first.wait_for()
    page.wait_for_timeout(2500)
    back = page.evaluate(READ_JS)
    name = page.get_by_role("button", name="Edit lesson name").inner_text().strip()
    result.update(
        saved=True,
        http=status,
        readback_nodes=len(back),
        title_ok=name == title,
        body_ok=strip_empty_edges(back) == strip_empty_edges(built),
        draft=is_draft(page),
    )
    if not (result["title_ok"] and result["body_ok"]):
        raise RuntimeError(f"readback mismatch: {result}")
    return result


def upload_featured_video(
    page: Any,
    browser: Any,
    *,
    url: str,
    lesson_id: int,
    video: str,
    allow_published: bool = False,
    timeout_s: int = 1800,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Set the lesson's featured media to a local video file and Save."""
    open_editor(page, url, allow_published=allow_published)
    cdp = browser.contexts[0].new_cdp_session(page)
    root = cdp.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"]["nodeId"]
    node = cdp.send(
        "DOM.querySelector", {"nodeId": root, "selector": 'input[type=file][accept*="video"]'}
    )["nodeId"]
    if not node:
        raise RuntimeError("no featured-media file input; is a video already attached?")
    # set_input_files refuses > 50 MB over CDP; DOM.setFileInputFiles hands Chrome the local path
    cdp.send("DOM.setFileInputFiles", {"nodeId": node, "files": [str(Path(video).resolve())]})
    for _ in range(timeout_s // 5):
        page.wait_for_timeout(5000)
        text = page.evaluate(
            "() => document.body.innerText.match(/(Uploading|Processing)[^\\n]{0,40}/)?.[0] || ''"
        )
        prompt = page.get_by_role("button", name="Upload or embed media").count()
        log(text or "upload finished")
        if not text and not prompt:
            break
    else:
        raise RuntimeError("featured video upload did not finish")
    page.wait_for_timeout(3000)
    status, body = save_lesson(page, lesson_id)
    return {"http": status, "featured_in_payload": "featured_media" in body}


VIDEOS_JS = """(root) => { const vs = []; const walk = r => r.querySelectorAll('*').forEach(e => {
  if (e.tagName === 'VIDEO') vs.push(e); if (e.shadowRoot) walk(e.shadowRoot) });
  walk(root); return vs.sort((a, b) => b.getBoundingClientRect().width - a.getBoundingClientRect().width) }"""
# seek the preview inside the dialog: on the lesson editor the page's own player is wider
SEEK_JS = f"(d, s) => {{ const v = ({VIDEOS_JS})(d)[0]; v.pause(); v.currentTime = s; return v.currentTime }}"
# what the dialog preview can play so far: duration (null until known) and the end of its seekable range
PLAYER_STATE_JS = f"""(d) => {{ const v = ({VIDEOS_JS})(d)[0]; if (!v) return null;
  const s = v.seekable; return {{duration: Number.isFinite(v.duration) ? v.duration : null,
  seekable_end: s && s.length ? s.end(s.length - 1) : null}} }}"""
MEDIA_READY_BUDGET_MS = 300_000  # shared by the readiness wait and all chapter seeks
MEDIA_RETRY_MS = 5000
NOT_READY_HINT = (
    "the featured video is probably still processing on Circle; nothing was saved (thumbnail and "
    "transcript included). Rerun lesson-media-settings in a few minutes."
)


class MediaNotReadyError(RuntimeError):
    pass


@dataclass
class WaitBudget:
    """Milliseconds of waiting left; counts only the waits it hands out, so tests can drive it."""

    total_ms: int
    spent_ms: int = 0

    def left(self) -> int:
        return max(0, self.total_ms - self.spent_ms)


def retry_until(
    attempt: Callable[[], tuple[bool, str]],
    *,
    budget: WaitBudget,
    wait: Callable[[int], None],
    interval_ms: int = MEDIA_RETRY_MS,
    what: str,
) -> str:
    """Call ``attempt`` until it reports success, waiting ``interval_ms`` between tries while budget lasts."""
    while True:
        ok, detail = attempt()
        if ok:
            return detail
        step = min(interval_ms, budget.left())
        if step <= 0:
            raise MediaNotReadyError(f"{what}: {detail}; {NOT_READY_HINT}")
        wait(step)
        budget.spent_ms += step


def player_ready(state: dict[str, Any] | None, last_seconds: int) -> tuple[bool, str]:
    """The preview can seek to ``last_seconds`` once its duration (and seekable range, if any) covers it."""
    if not state:
        return False, "no video in the dialog yet"
    duration = state.get("duration")
    if duration is None:
        return False, "player duration unknown"
    end = state.get("seekable_end") or duration
    if duration < last_seconds or end < last_seconds:
        return False, f"player covers {mmss(int(min(duration, end)))}, last chapter at {mmss(last_seconds)}"
    return True, f"player covers {mmss(int(min(duration, end)))}"


TRACKS_JS = f"""() => {{ const v = ({VIDEOS_JS})(document)[0]; if (!v) return [];
  return [...v.textTracks].map(t => {{ if (t.mode === 'disabled') t.mode = 'hidden';
    return {{kind: t.kind, label: t.label, cues: t.cues ? t.cues.length : null,
             titles: t.kind === 'chapters' && t.cues ? [...t.cues].map(c => c.text) : undefined}} }}) }}"""


THUMBNAIL_BUTTONS = ("Add image", "Replace")  # empty slot, then a slot that already holds a custom thumbnail


def open_thumbnail_chooser(dialog: Any) -> str:
    """Click the Custom thumbnail button in Customize media and return its label.

    The slot shows "Add image" until a custom thumbnail is set and "Replace" (next to "Remove")
    afterwards, so a rerun on a video that already has a thumbnail must click "Replace".
    """
    for name in THUMBNAIL_BUTTONS:
        button = dialog.get_by_role("button", name=name, exact=True)
        if button.count():
            button.first.click()
            return name
    raise RuntimeError(
        "Customize media shows neither 'Add image' nor 'Replace' under Custom thumbnail; "
        "nothing was saved"
    )


def open_customize_media(page: Any) -> Any:
    button = page.get_by_role("button", name="Customize media").first
    for _ in range(15):  # only rendered while the pointer is over the player
        page.mouse.move(900, 250)
        page.wait_for_timeout(300)
        page.mouse.move(950, 300)
        page.wait_for_timeout(700)
        if button.count():
            break
    button.click(force=True)
    dialog = page.get_by_role("dialog", name="Customize media")
    dialog.wait_for()
    page.wait_for_timeout(1500)
    return dialog


def open_post(page: Any, url: str, *, timeout_ms: int = 20_000) -> None:
    """Open a post page and wait until its video player is in the DOM (posts have no draft gate)."""
    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    waited = 0
    while not page.evaluate(f"() => ({VIDEOS_JS})(document).length"):
        if waited >= timeout_ms:
            raise RuntimeError("no video player on the post page (wrong URL, or the video is still transcoding?)")
        page.wait_for_timeout(500)
        waited += 500
    page.wait_for_timeout(1500)


PLAYER_BOX_JS = f"""() => {{ const v = ({VIDEOS_JS})(document)[0]; if (!v) return null;
  v.scrollIntoView({{block: 'center'}}); const r = v.getBoundingClientRect(); return [r.x, r.y, r.width, r.height] }}"""


def open_customize_media_on_player(page: Any) -> Any:
    """Like ``open_customize_media`` but hovers the player itself (post pages lay the player out differently)."""
    box = page.evaluate(PLAYER_BOX_JS)
    if not box:
        raise RuntimeError("no video player to hover")
    x, y, w, h = box
    button = page.get_by_role("button", name="Customize media").first
    for _ in range(15):  # only rendered while the pointer is over the player
        page.mouse.move(x + w * 0.5, y + h * 0.4)
        page.wait_for_timeout(300)
        page.mouse.move(x + w * 0.8, y + h * 0.2)
        page.wait_for_timeout(700)
        if button.count():
            break
    else:
        raise RuntimeError("Customize media button never appeared; is the session an admin or the post's author?")
    button.click(force=True)
    dialog = page.get_by_role("dialog", name="Customize media")
    dialog.wait_for()
    page.wait_for_timeout(1500)
    return dialog


def check_transcript(vtt: str) -> None:
    """Refuse a transcript Circle would silently fail to save (bare ``&``, ``<`` or ``>`` in cue text)."""
    from .subtitles import parse_vtt, unescaped_characters

    text = Path(vtt).read_text(encoding="utf-8-sig")
    if not text.lstrip().startswith("WEBVTT"):
        raise ValueError(f"{vtt} is not a WebVTT file")
    bad = sorted({ch for cue in parse_vtt(text) for ch in unescaped_characters(cue.text)})
    if bad:
        raise ValueError(
            f"{vtt} has unescaped {' '.join(bad)} in cue text; Circle's Save would silently do nothing. "
            "Escape them (&amp; &lt; &gt;), e.g. with circle_client_skill.subtitles.escape_cue_text"
        )


def set_media_settings(
    page: Any,
    *,
    url: str,
    vtt: str | None = None,
    chapters: list[tuple[int, str]] | None = None,
    video_thumbnail: str | None = None,
    allow_published: bool = False,
    target: str = "lesson",
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Custom transcript, chapters and custom video thumbnail through Customize media; then read tracks back.

    ``target="lesson"`` opens the lesson editor (draft gate applies); ``target="post"`` opens a post page.
    """
    if target not in ("lesson", "post"):
        raise ValueError(f"unknown target {target!r}")
    if vtt:
        check_transcript(vtt)
    if target == "post":
        open_post(page, url)
        dialog = open_customize_media_on_player(page)
    else:
        open_editor(page, url, allow_published=allow_published)
        dialog = open_customize_media(page)
    budget = WaitBudget(MEDIA_READY_BUDGET_MS)
    if chapters:  # before touching anything in the dialog, so a not-ready video costs nothing
        log(retry_until(
            lambda: player_ready(dialog.evaluate(PLAYER_STATE_JS), chapters[-1][0]),
            budget=budget, wait=page.wait_for_timeout, what="video not ready for chapters",
        ))
    if video_thumbnail:
        # Custom thumbnail > "Add image" (or "Replace" once a thumbnail exists) opens a
        # "Choose image" dialog with its own file input
        log(f"thumbnail button: {open_thumbnail_chooser(dialog)}")
        chooser = page.get_by_role("dialog", name="Choose image")
        chooser.wait_for()
        chooser.locator("input[type=file]").set_input_files(video_thumbnail)
        page.wait_for_timeout(2500)
        chooser.get_by_role("button", name="Save changes").click()
        chooser.wait_for(state="hidden")
        page.wait_for_timeout(1500)
        log("video thumbnail set")
    if vtt:
        dialog.get_by_text(
            "Upload a custom transcript"
        ).click()  # the radio itself is visually hidden
        page.wait_for_timeout(500)
        if not dialog.locator("input[type=radio][value=user]").is_checked():
            raise RuntimeError("could not select Upload a custom transcript")
        vtt_input = dialog.locator('input[type=file][name="transcript.user_webvtt_file"]')
        if not vtt_input.count():
            raise RuntimeError("a .vtt is already attached; remove it in the dialog first")
        vtt_input.set_input_files(vtt)
        page.wait_for_timeout(1500)
        log("transcript attached")
    if chapters:
        while dialog.get_by_role(
            "button", name="Actions"
        ).count():  # start clean so reruns are safe
            dialog.get_by_role("button", name="Actions").last.click()
            page.get_by_role("menuitem", name="Delete").click()
            confirm = page.get_by_role("dialog", name="Delete this chapter?")
            confirm.get_by_role("button", name="Delete").click()
            confirm.wait_for(state="hidden")
            page.wait_for_timeout(600)
        dialog.evaluate(SEEK_JS, 0)
        page.wait_for_timeout(800)
        dialog.get_by_role("button", name="Add chapter").click()
        page.wait_for_timeout(800)
        box = dialog.locator("input[name=title]").last
        box.fill(chapters[0][1])
        box.press("Enter")
        page.wait_for_timeout(800)
        for seconds, title in chapters[1:]:
            add = dialog.locator('button:has-text("Add at")').first

            def seek(seconds: int = seconds, add: Any = add) -> tuple[bool, str]:
                dialog.evaluate(SEEK_JS, seconds)  # re-issued on every try
                page.wait_for_timeout(1200)
                label = add.inner_text().strip()
                return label.endswith(mmss(seconds)), f"button says {label!r}, wanted {mmss(seconds)}"

            retry_until(seek, budget=budget, wait=page.wait_for_timeout, what="seek failed")
            label = add.inner_text().strip()
            add.click()
            page.wait_for_timeout(800)
            box = dialog.locator("input[name=title]").last
            box.fill(title)
            box.press("Enter")
            page.wait_for_timeout(800)
            log(f"{label} {title}")
    dialog.get_by_role("button", name="Save", exact=True).click()
    page.get_by_text("Video settings saved successfully").first.wait_for(timeout=30000)
    page.goto(url)
    page.wait_for_timeout(8000)
    tracks = page.evaluate(TRACKS_JS)
    poster = page.evaluate(f"() => (({VIDEOS_JS})(document)[0] || {{}}).poster || null")
    return {"tracks": tracks, "poster": poster}
