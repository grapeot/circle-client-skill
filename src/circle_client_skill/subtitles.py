"""Offline helpers for building a bilingual WebVTT file for an edited recording.

The workflow (see ``skills/references/recording_posts.md``) is:

1. ``parse_vtt`` reads the meeting tool's transcript (for Zoom, ``transcript.vtt``: one
   sentence-level cue per utterance, prefixed with ``Speaker: ``).
2. ``remap_cues`` moves the cues onto the timeline of the edited video: cues inside a cut
   are dropped, later cues shift left by the cut length, cues after the truncation point
   are dropped, and the last cue is clamped to the video duration.
3. An agent corrects ASR errors and translates. For every cue it returns a list of
   segments ``{"zh": ..., "en": ...}`` split at sentence boundaries.
4. ``build_bilingual_vtt`` spreads each cue's time over its segments in proportion to the
   English length, keeps neighbouring cues from overlapping and writes two-line cues
   (Chinese first, English second).
5. ``validate_vtt`` re-parses the result and reports ordering, duration, overlap, count
   and leftover-misspelling problems.

Nothing here touches the network or Circle; uploading the file is a browser step.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

_TIMING = re.compile(
    r"^\s*(?P<start>(?:\d+:)?\d{1,2}:\d{2}\.\d{3})\s+-->\s+(?P<end>(?:\d+:)?\d{1,2}:\d{2}\.\d{3})"
)
_SPEAKER = re.compile(r"^(?P<speaker>[^:\n]{1,80}):\s+(?P<text>.*)$", re.DOTALL)


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str
    speaker: str | None = None


def parse_timestamp(value: str) -> float:
    parts = value.strip().split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) >= 3 else 0
    return hours * 3600 + minutes * 60 + seconds


def format_timestamp(seconds: float) -> str:
    millis = round(max(seconds, 0.0) * 1000)
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def parse_vtt(text: str, *, speakers: bool = False) -> list[Cue]:
    """Parse WebVTT cues. With ``speakers=True`` a leading ``Name: `` becomes ``speaker``."""
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        for idx, line in enumerate(lines):
            match = _TIMING.match(line)
            if not match:
                continue
            body = "\n".join(lines[idx + 1 :]).strip()
            speaker = None
            if speakers:
                found = _SPEAKER.match(body)
                if found:
                    speaker, body = found["speaker"].strip(), found["text"].strip()
            cues.append(
                Cue(parse_timestamp(match["start"]), parse_timestamp(match["end"]), body, speaker)
            )
            break
    return cues


def remap_cues(
    cues: Iterable[Cue],
    *,
    cuts: Sequence[tuple[float, float]] = (),
    end_at: float | None = None,
    duration: float | None = None,
) -> list[Cue]:
    """Map source-timeline cues onto the edited video's timeline.

    ``cuts`` are ``(start, end)`` ranges removed from the source; ``end_at`` is the source
    time where the edit was truncated; ``duration`` is the edited video's length. A cue
    that starts inside a cut, or at/after ``end_at``, is dropped. A cue that starts before
    a cut and runs into it is trimmed at the cut start.
    """
    ordered_cuts = sorted(cuts)
    for start, end in ordered_cuts:
        if end <= start:
            raise ValueError(f"invalid cut ({start}, {end})")

    def shift(t: float) -> float:
        return t - sum(e - s for s, e in ordered_cuts if e <= t)

    out: list[Cue] = []
    for cue in sorted(cues, key=lambda c: c.start):
        if end_at is not None and cue.start >= end_at:
            continue
        if any(s <= cue.start < e for s, e in ordered_cuts):
            continue
        end = cue.end
        if end_at is not None:
            end = min(end, end_at)
        for s, _e in ordered_cuts:
            if cue.start < s < end:
                end = s
        new_start, new_end = shift(cue.start), shift(end)
        if duration is not None:
            new_end = min(new_end, duration)
        if new_end <= new_start:
            continue
        out.append(replace(cue, start=new_start, end=new_end))
    return out


def split_times(start: float, end: float, weights: Sequence[int]) -> list[tuple[float, float]]:
    """Split ``[start, end]`` into consecutive spans proportional to ``weights`` (min 1)."""
    if not weights:
        raise ValueError("at least one segment is required")
    sizes = [max(int(w), 1) for w in weights]
    total = sum(sizes)
    spans: list[tuple[float, float]] = []
    cursor = start
    for idx, size in enumerate(sizes):
        stop = end if idx == len(sizes) - 1 else cursor + (end - start) * size / total
        spans.append((cursor, stop))
        cursor = stop
    return spans


def build_bilingual_vtt(
    cues: Sequence[Cue],
    segments: Sequence[Sequence[Mapping[str, str]]],
    *,
    gap: float = 0.05,
) -> str:
    """Assemble a WebVTT file with one ``zh`` line above one ``en`` line per cue.

    ``segments[i]`` is the list of ``{"zh", "en"}`` pieces for ``cues[i]``. A cue's end is
    pulled back to ``gap`` seconds before the next cue's start so cues never overlap.
    """
    if len(cues) != len(segments):
        raise ValueError(f"{len(cues)} cues but {len(segments)} segment lists")
    lines = ["WEBVTT", ""]
    number = 0
    for idx, (cue, pieces) in enumerate(zip(cues, segments, strict=True)):
        end = cue.end
        if idx + 1 < len(cues):
            next_start = cues[idx + 1].start
            end = min(end, next_start - gap) if next_start - gap > cue.start else min(end, next_start)
        weights = [len(piece["en"].strip()) for piece in pieces]
        for (start, stop), piece in zip(split_times(cue.start, end, weights), pieces, strict=True):
            number += 1
            lines += [
                str(number),
                f"{format_timestamp(start)} --> {format_timestamp(stop)}",
                piece["zh"].strip(),
                piece["en"].strip(),
                "",
            ]
    return "\n".join(lines)


def validate_vtt(
    text: str,
    *,
    expected_count: int | None = None,
    duration: float | None = None,
    forbidden: Iterable[str] = (),
) -> list[str]:
    """Return a list of problems; an empty list means the file passed."""
    problems: list[str] = []
    if not text.lstrip().startswith("WEBVTT"):
        problems.append("missing WEBVTT header")
    cues = parse_vtt(text)
    if expected_count is not None and len(cues) != expected_count:
        problems.append(f"expected {expected_count} cues, found {len(cues)}")
    for idx, cue in enumerate(cues, start=1):
        if cue.end <= cue.start:
            problems.append(f"cue {idx}: non-positive duration")
        if idx > 1:
            prev = cues[idx - 2]
            if cue.start < prev.start:
                problems.append(f"cue {idx}: starts before cue {idx - 1}")
            if cue.start < prev.end:
                problems.append(f"cue {idx}: overlaps cue {idx - 1}")
        if duration is not None and cue.end > duration + 1e-3:
            problems.append(f"cue {idx}: ends after video duration")
        for word in forbidden:
            if word and re.search(rf"\b{re.escape(word)}\b", cue.text):
                problems.append(f"cue {idx}: contains {word!r}")
    return problems
