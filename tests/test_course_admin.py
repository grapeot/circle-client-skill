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
