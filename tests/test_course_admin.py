from __future__ import annotations

import json
from pathlib import Path

import pytest

from circle_client_skill import cli
from circle_client_skill.client import CircleClient
from circle_client_skill.course_admin import (
    ManifestError,
    UploadCache,
    build_parts,
    check_section_name,
    load_manifest,
    manifest_summary,
    media_node,
    parse_chapters,
    strip_empty_edges,
)
from tests.test_course import FakeResponse, FakeSession, _settings


def _manifest(tmp_path: Path, items: list, title: str = "Lesson 1") -> Path:
    (tmp_path / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
    (tmp_path / "clip.mp4").write_bytes(b"mp4")
    path = tmp_path / "01.json"
    path.write_text(json.dumps({"title": title, "items": items}))
    return path


def test_load_manifest_resolves_media_and_counts(tmp_path) -> None:
    path = _manifest(tmp_path, [
        {"html": "<p>hi</p>"},
        {"media": "a.png", "kind": "image", "portrait": True},
        {"media": "clip.mp4", "kind": "video"},
    ])
    m = load_manifest(path)
    assert m["title"] == "Lesson 1"
    assert m["items"][1]["media"] == str((tmp_path / "a.png").resolve())
    assert m["items"][1]["portrait"] is True
    assert manifest_summary(m) == {"html": 1, "images": 1, "videos": 1}


@pytest.mark.parametrize("items, message", [
    ([{"media": "missing.png", "kind": "image"}], "not found"),
    ([{"media": "a.png", "kind": "table"}], "kind"),
    (["oops"], "not an object"),
])
def test_load_manifest_rejects_bad_items(tmp_path, items, message) -> None:
    with pytest.raises(ManifestError, match=message):
        load_manifest(_manifest(tmp_path, items))


def test_load_manifest_requires_title(tmp_path) -> None:
    with pytest.raises(ManifestError, match="title"):
        load_manifest(_manifest(tmp_path, [], title=" "))


def test_media_nodes() -> None:
    blob = {"signed_id": "sid", "url": "https://cdn.example.com/k", "content_type": "image/jpeg"}
    full = media_node("image", blob)
    assert full == {"type": "image", "attrs": {"url": "https://cdn.example.com/k", "signed_id": "sid",
                                               "content_type": "image/jpeg", "width": "100%", "alignment": "left"}}
    assert media_node("image", blob, portrait=True)["attrs"]["width_ratio"] == 0.5
    assert media_node("video", blob) == {"type": "file", "attrs": {"signed_id": "sid"}}


def test_build_parts_keeps_order(tmp_path) -> None:
    m = load_manifest(_manifest(tmp_path, [{"html": "<p>a</p>"}, {"media": "a.png", "kind": "image"},
                                           {"html": "<p>b</p>"}]))
    blobs = {m["items"][1]["media"]: {"signed_id": "s", "url": "u"}}
    parts = build_parts(m, blobs)
    assert parts[0] == "<p>a</p>" and parts[1]["type"] == "image" and parts[2] == "<p>b</p>"


def test_strip_empty_edges() -> None:
    assert strip_empty_edges(["paragraph", "heading", "paragraph", "image", "paragraph"]) == [
        "heading", "paragraph", "image"]
    assert strip_empty_edges(["paragraph"]) == []


def test_section_name_limit() -> None:
    assert check_section_name("  Bonus  ") == "Bonus"
    check_section_name("x" * 100)
    with pytest.raises(ValueError, match="101 characters"):
        check_section_name("x" * 101)


def test_parse_chapters() -> None:
    text = "# comment\n00:00 Opening\n05:01 Experiment 1\n\n1:02:03 Late\n"
    assert parse_chapters(text) == [(0, "Opening"), (301, "Experiment 1"), (3723, "Late")]
    with pytest.raises(ValueError, match="00:00"):
        parse_chapters("00:05 Late start")
    with pytest.raises(ValueError, match="increasing"):
        parse_chapters("00:00 A\n00:00 B")
    with pytest.raises(ValueError, match="line 1"):
        parse_chapters("five minutes in")


def test_upload_cache_reuses_until_content_changes(tmp_path) -> None:
    f = tmp_path / "a.png"
    f.write_bytes(b"one")
    calls = []

    def upload(path):
        calls.append(path)
        return {"signed_id": f"s{len(calls)}", "url": "u", "content_type": "image/png"}

    cache = UploadCache(tmp_path / "cache.json")
    first, uploaded = cache.get_or_upload(f, upload)
    again, uploaded_again = cache.get_or_upload(f, upload)
    assert uploaded and not uploaded_again and first == again
    f.write_bytes(b"two")
    changed, uploaded_changed = cache.get_or_upload(f, upload)
    assert uploaded_changed and changed["signed_id"] == "s2"


def test_client_course_admin_requests() -> None:
    session = FakeSession()
    base = "https://community.example.com/internal_api/courses/9000000/sections"
    session.set_response(f"GET {base}", FakeResponse({"records": [{"id": 1, "lessons": []}]}))
    client = CircleClient(_settings(), session=session)
    assert client.list_course_sections(9000000) == [{"id": 1, "lessons": []}]
    client.create_course_section(9000000, "New")
    client.rename_course_section(9000000, 9000001, "Renamed")
    client.create_course_lesson(9000000, 9000001, "Lesson")
    calls = session.calls[1:]
    assert [c["method"] for c in calls] == ["POST", "PUT", "POST"]
    assert calls[0]["json"] == {"course_section": {"drip_delay": 0, "lesson_order": [], "name": "New"}}
    assert calls[1]["url"].endswith("/sections/9000001")
    assert calls[2]["url"].endswith("/sections/9000001/lessons")
    assert calls[2]["json"]["course_lesson"]["status"] == "draft"


def _run(argv, monkeypatch):
    monkeypatch.setattr(cli, "load_settings", lambda _path: _settings())
    args = cli.build_parser().parse_args(argv)
    args.handler(args)


def test_create_section_dry_run_and_confirmation(monkeypatch, capsys) -> None:
    _run(["create-section", "-s", "9000000", "--name", "Bonus"], monkeypatch)
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    with pytest.raises(ValueError, match="CREATE-SECTION"):
        _run(["create-section", "-s", "9000000", "--name", "Bonus", "--execute"], monkeypatch)
    with pytest.raises(ValueError, match="at most 100"):
        _run(["create-section", "-s", "9000000", "--name", "x" * 101], monkeypatch)


def test_fill_lesson_dry_run_does_not_need_a_browser(tmp_path, monkeypatch, capsys) -> None:
    path = _manifest(tmp_path, [{"html": "<p>a</p>"}, {"media": "a.png", "kind": "image"}])
    _run(["fill-lesson", "-s", "9000000", "--lesson-id", "9000002", "--manifest", str(path)], monkeypatch)
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["images"] == 1 and out["save"] is True


def test_media_settings_needs_something_to_set(monkeypatch) -> None:
    with pytest.raises(ValueError, match="nothing to set"):
        _run(["lesson-media-settings", "-s", "9000000", "--lesson-id", "9000002"], monkeypatch)


def test_course_admin_commands_accept_global_flags_after_subcommand() -> None:
    args = cli.build_parser().parse_args(["course-sections", "-s", "1", "--json"])
    assert args.json is True


# --- lesson-media-settings while the featured video is still processing ---


def test_player_ready() -> None:
    from circle_client_skill.course_admin import player_ready

    assert player_ready(None, 700) == (False, "no video in the dialog yet")
    assert player_ready({"duration": None, "seekable_end": None}, 700)[0] is False
    ok, detail = player_ready({"duration": 10.0, "seekable_end": 10.0}, 700)
    assert not ok and "00:10" in detail and "11:40" in detail
    assert player_ready({"duration": 1070.0, "seekable_end": 300.0}, 700)[0] is False
    assert player_ready({"duration": 1070.0, "seekable_end": None}, 700)[0] is True
    assert player_ready({"duration": 1070.0, "seekable_end": 1070.0}, 700)[0] is True


def test_retry_until_retries_then_succeeds() -> None:
    from circle_client_skill.course_admin import WaitBudget, retry_until

    results = iter([(False, "a"), (False, "b"), (True, "done")])
    waits: list[int] = []
    budget = WaitBudget(60_000)
    assert retry_until(lambda: next(results), budget=budget, wait=waits.append,
                       interval_ms=5000, what="x") == "done"
    assert waits == [5000, 5000]
    assert budget.spent_ms == 10_000


def test_retry_until_gives_up_at_budget_with_rerun_hint() -> None:
    from circle_client_skill.course_admin import MediaNotReadyError, WaitBudget, retry_until

    waits: list[int] = []
    with pytest.raises(MediaNotReadyError) as err:
        retry_until(lambda: (False, "button says 'Add at 00:10'"), budget=WaitBudget(12_000),
                    wait=waits.append, interval_ms=5000, what="seek failed")
    assert waits == [5000, 5000, 2000]  # bounded: never waits past the budget
    message = str(err.value)
    assert "Add at 00:10" in message and "still processing" in message
    assert "nothing was saved" in message and "Rerun" in message


class _Loc:
    def __init__(self, ui: _FakeUI, name: str) -> None:
        self.ui, self.name = ui, name

    first = last = property(lambda self: self)

    def count(self) -> int:
        return 0  # no existing chapters to delete

    def click(self, **_: object) -> None:
        self.ui.actions.append(f"click {self.name}")
        if self.name == "Add at":
            self.ui.chapters_at.append(self.ui.position)

    def fill(self, text: str) -> None:
        self.ui.actions.append(f"fill {text}")

    def press(self, _key: str) -> None:
        pass

    def wait_for(self, **_: object) -> None:
        pass

    def inner_text(self) -> str:
        return f"Add at {self.ui.position // 60:02d}:{self.ui.position % 60:02d}"


class _FakeUI:
    """Page and dialog in one: the preview can only seek up to ``ready_s``, which grows with each wait."""

    def __init__(self, ready_s: int, grow_per_wait_s: int) -> None:
        self.ready_s, self.grow = ready_s, grow_per_wait_s
        self.position = 0
        self.actions: list[str] = []
        self.chapters_at: list[int] = []
        self.waited_ms = 0

    def wait_for_timeout(self, ms: int) -> None:
        self.waited_ms += ms
        if ms >= 2000:  # only the retry waits, not the UI settle waits
            self.ready_s += self.grow

    def evaluate(self, js: str, arg: object = None) -> object:
        from circle_client_skill.course_admin import PLAYER_STATE_JS, SEEK_JS

        if js == PLAYER_STATE_JS:
            return {"duration": 1070.0, "seekable_end": float(self.ready_s)}
        if js == SEEK_JS:
            self.position = min(int(arg), self.ready_s)  # clamped like a still-processing stream
            return self.position
        return []  # tracks / poster readback

    def get_by_role(self, _role: str, name: str = "", **_: object) -> _Loc:
        return _Loc(self, name)

    def get_by_text(self, text: str) -> _Loc:
        return _Loc(self, text)

    def locator(self, selector: str) -> _Loc:
        return _Loc(self, "Add at" if "Add at" in selector else selector)

    def goto(self, _url: str) -> None:
        pass


def _run_media_settings(monkeypatch, ui: _FakeUI) -> dict:
    from circle_client_skill import course_admin

    monkeypatch.setattr(course_admin, "open_editor", lambda *a, **k: None)
    monkeypatch.setattr(course_admin, "open_customize_media", lambda page: ui)
    chapters = [(0, "Intro"), (229, "Two"), (434, "Three"), (700, "Four")]
    return course_admin.set_media_settings(ui, url="https://example.invalid/x", chapters=chapters,
                                           log=lambda _m: None)


def test_media_settings_waits_for_processing_video_then_adds_chapters(monkeypatch) -> None:
    ui = _FakeUI(ready_s=10, grow_per_wait_s=120)
    _run_media_settings(monkeypatch, ui)
    assert ui.chapters_at == [229, 434, 700]
    assert "click Save" in ui.actions


def test_media_settings_not_ready_saves_nothing(monkeypatch) -> None:
    from circle_client_skill.course_admin import MEDIA_READY_BUDGET_MS, MediaNotReadyError

    ui = _FakeUI(ready_s=10, grow_per_wait_s=0)
    with pytest.raises(MediaNotReadyError, match="still processing"):
        _run_media_settings(monkeypatch, ui)
    assert ui.actions == []  # failed before the thumbnail, transcript or chapters were touched
    assert ui.waited_ms <= MEDIA_READY_BUDGET_MS + 10_000


def test_media_settings_seek_retry_is_bounded(monkeypatch) -> None:
    from circle_client_skill import course_admin

    ui = _FakeUI(ready_s=1070, grow_per_wait_s=0)
    # duration looks complete but seeks past 00:10 keep being clamped
    original = ui.evaluate

    def evaluate(js: str, arg: object = None) -> object:
        if js == course_admin.SEEK_JS:
            ui.position = min(int(arg), 10)
            return ui.position
        return original(js, arg)

    ui.evaluate = evaluate  # type: ignore[method-assign]
    with pytest.raises(course_admin.MediaNotReadyError, match="Add at 00:10"):
        _run_media_settings(monkeypatch, ui)
    assert "click Save" not in ui.actions
    assert ui.waited_ms <= course_admin.MEDIA_READY_BUDGET_MS + 400 * 1200
