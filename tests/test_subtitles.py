from __future__ import annotations

from itertools import pairwise

import pytest

from circle_client_skill.subtitles import (
    Cue,
    build_bilingual_vtt,
    format_timestamp,
    parse_timestamp,
    parse_vtt,
    remap_cues,
    split_times,
    validate_vtt,
)

SOURCE_VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
Speaker A: Welcome to the demo.


2
00:00:05.000 --> 00:00:09.000
Speaker A: First we load the model. Then we run it.


3
00:00:10.000 --> 00:00:12.000
Guest B: Can you hear me?


4
00:00:12.500 --> 00:00:16.000
Speaker A: Back to the slides.


5
00:01:00.000 --> 00:01:03.000
Speaker A: Any questions?
"""


def test_parse_vtt_reads_timing_and_speaker():
    cues = parse_vtt(SOURCE_VTT, speakers=True)
    assert len(cues) == 5
    assert cues[0] == Cue(1.0, 4.0, "Welcome to the demo.", "Speaker A")
    assert cues[2].speaker == "Guest B"
    assert cues[4].start == 60.0


def test_parse_vtt_keeps_text_without_speaker_flag():
    cues = parse_vtt(SOURCE_VTT)
    assert cues[0].text == "Speaker A: Welcome to the demo."
    assert cues[0].speaker is None


def test_timestamp_round_trip():
    assert parse_timestamp("01:02:03.456") == pytest.approx(3723.456)
    assert parse_timestamp("02:03.500") == pytest.approx(123.5)
    assert format_timestamp(3723.456) == "01:02:03.456"
    assert format_timestamp(-1) == "00:00:00.000"


def test_remap_drops_cut_shifts_later_and_truncates():
    cues = parse_vtt(SOURCE_VTT, speakers=True)
    out = remap_cues(cues, cuts=[(10.0, 12.2)], end_at=50.0, duration=13.7)
    assert [c.text for c in out] == [
        "Welcome to the demo.",
        "First we load the model. Then we run it.",
        "Back to the slides.",
    ]
    assert out[0].start == 1.0 and out[1].end == 9.0
    assert out[2].start == pytest.approx(10.3)
    assert out[2].end == pytest.approx(13.7)  # 13.8 clamped to duration


def test_remap_trims_cue_running_into_cut():
    cues = [Cue(8.0, 11.0, "runs into the cut"), Cue(13.0, 14.0, "after")]
    out = remap_cues(cues, cuts=[(10.0, 12.0)])
    assert out[0].end == 10.0
    assert out[1].start == pytest.approx(11.0)


def test_remap_clamps_cue_crossing_truncation_point():
    out = remap_cues([Cue(4.0, 8.0, "x"), Cue(9.0, 10.0, "y")], end_at=6.0)
    assert len(out) == 1 and out[0].end == 6.0


def test_remap_rejects_inverted_cut():
    with pytest.raises(ValueError):
        remap_cues([], cuts=[(5.0, 4.0)])


def test_split_times_is_proportional_and_exact_at_end():
    spans = split_times(0.0, 10.0, [30, 10, 0])
    assert spans[0] == (0.0, pytest.approx(30 / 41 * 10))
    assert spans[-1][1] == 10.0
    assert all(a[1] == b[0] for a, b in pairwise(spans))


def test_build_bilingual_vtt_splits_segments_and_avoids_overlap():
    cues = [Cue(0.0, 6.0, "a"), Cue(5.0, 7.0, "b")]
    segments = [
        [{"zh": "第一句。", "en": "First sentence."}, {"zh": "第二句。", "en": "Second."}],
        [{"zh": "下一条。", "en": "Next cue."}],
    ]
    vtt = build_bilingual_vtt(cues, segments)
    assert "第一句。\nFirst sentence." in vtt
    parsed = parse_vtt(vtt)
    assert len(parsed) == 3
    assert parsed[1].end == pytest.approx(4.95)
    assert parsed[0].end == parsed[1].start
    assert validate_vtt(vtt, expected_count=3, duration=7.0) == []


def test_build_bilingual_vtt_requires_aligned_inputs():
    with pytest.raises(ValueError):
        build_bilingual_vtt([Cue(0.0, 1.0, "a")], [])


def test_validate_vtt_reports_problems():
    bad = """WEBVTT

1
00:00:02.000 --> 00:00:03.000
中文
teh model said hi

2
00:00:01.000 --> 00:00:01.000
中文
ok
"""
    problems = validate_vtt(bad, expected_count=3, duration=2.5, forbidden=["teh"])
    assert "expected 3 cues, found 2" in problems
    assert "cue 1: ends after video duration" in problems
    assert "cue 1: contains 'teh'" in problems
    assert "cue 2: non-positive duration" in problems
    assert "cue 2: starts before cue 1" in problems
    assert validate_vtt("no header") == ["missing WEBVTT header"]
