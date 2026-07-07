#!/usr/bin/env python3
"""
Detect text-only signals from a video's subtitles + metadata - no video frames,
no screenshots. Produces a flags dict meant to be merged into the log registry:
write it to a file with `--out flags.json`, then run
`log_registry.py set-flags <video_id> flags.json` to merge it in (also stamps
the `flags_detected` stage - see log_registry.py).

Flags computed today (add more the same way - keyword lists live in
references/*.txt so they can be edited without touching this script):

  - possible_other_speakers: the transcript likely contains other people's
    voices (guests, reacted-to clips, interviews), not just the host.
    Signal 1: frequency of the `>>` speaker-change marker in the raw auto-caption
      (YouTube inserts it on detected voice/speaker changes). High rate per
      minute of runtime is a strong hint of a multi-voice video.
    Signal 2: title/description keywords from references/reaction-keywords.txt.

  - possible_sponsor_intro: the first N seconds likely contain a paid ad read,
    based on keyword hits from references/sponsor-keywords.txt within the
    early portion of the transcript. Approximate only - there is no reliable
    way to find the exact ad boundary from text alone (the legal disclaimer
    card is burned into the video, not spoken, so it never appears in
    auto-captions). Treat `approx_end_sec` as a rough estimate to sanity-check,
    not a precise cut point.

Usage:
    uv run python3 detect_flags.py VIDEO.ru.vtt --info VIDEO.info.json --out flags.json
"""

import argparse
import html
import json
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_keywords(name: str) -> list[str]:
    path = SKILL_DIR / "references" / name
    return [
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def ts_to_sec(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_vtt_entries(path: Path):
    """Yield (start_seconds, raw_text_with_markers) per unique caption line."""
    content = path.read_text(encoding="utf-8")
    prev_text = None
    for block in content.split("\n\n"):
        lines = block.split("\n")
        ts_line = next((l for l in lines if "-->" in l), None)
        if not ts_line:
            continue
        try:
            t = ts_to_sec(ts_line.split("-->")[0].strip().split(" ")[0])
        except ValueError:
            continue
        for l in lines:
            if "-->" in l or not l.strip():
                continue
            clean = re.sub(r"<[^>]+>", "", l).strip()
            clean = html.unescape(clean)
            if clean and clean != prev_text:
                yield t, clean
                prev_text = clean


def detect_other_speakers(entries, duration_sec, title, description):
    full_text = " ".join(text for _, text in entries)
    marker_count = full_text.count(">>")
    minutes = max(duration_sec / 60, 1)
    marker_rate = marker_count / minutes

    keywords = load_keywords("reaction-keywords.txt")
    haystack = f"{title}\n{description}".lower()
    matched_keywords = [k for k in keywords if k in haystack]

    MARKER_RATE_THRESHOLD = 3.0  # empirically: a8a-hy31pdI had ~11.4/min
    flagged = marker_rate >= MARKER_RATE_THRESHOLD or bool(matched_keywords)

    reasons = []
    if marker_rate >= MARKER_RATE_THRESHOLD:
        reasons.append(f"high '>>' speaker-change rate: {marker_rate:.1f}/min (threshold {MARKER_RATE_THRESHOLD})")
    if matched_keywords:
        reasons.append(f"title/description keywords: {matched_keywords}")
    if not reasons:
        reasons.append(f"'>>' rate {marker_rate:.1f}/min below threshold, no keyword match")

    return {
        "value": flagged,
        "reason": "; ".join(reasons),
        "marker_rate_per_min": round(marker_rate, 2),
        "matched_keywords": matched_keywords,
    }


def detect_sponsor_intro(entries, window_sec=90):
    keywords = load_keywords("sponsor-keywords.txt")
    early = [(t, text) for t, text in entries if t <= window_sec]
    matches = []
    last_match_t = None
    for t, text in early:
        low = text.lower()
        hit = [k for k in keywords if k in low]
        if hit:
            matches.extend(hit)
            last_match_t = t

    flagged = bool(matches)
    result = {
        "value": flagged,
        "reason": f"matched keywords in first {window_sec}s: {sorted(set(matches))}" if matches
                  else f"no sponsor keywords found in first {window_sec}s",
    }
    if last_match_t is not None:
        result["approx_end_sec"] = int(last_match_t) + 5  # rough buffer, not exact
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vtt", type=Path)
    ap.add_argument("--info", type=Path, help="yt-dlp .info.json for title/description/duration")
    ap.add_argument("--out", type=Path, help="Write flags JSON here (default: stdout)")
    args = ap.parse_args()

    title, description, duration = "", "", 0
    if args.info and args.info.exists():
        info = json.loads(args.info.read_text(encoding="utf-8"))
        title = info.get("title", "")
        description = info.get("description", "")
        duration = info.get("duration", 0)

    entries = list(parse_vtt_entries(args.vtt))
    if not duration and entries:
        duration = entries[-1][0]

    flags = {
        "possible_other_speakers": detect_other_speakers(entries, duration, title, description),
        "possible_sponsor_intro": detect_sponsor_intro(entries),
    }

    output = json.dumps(flags, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(output)


if __name__ == "__main__":
    main()
