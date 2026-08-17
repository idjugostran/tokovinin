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
    python3 detect_flags.py transcripts/<id>.json --out flags.json

Note on signal 1 (the `>>` marker): measured across all 75 caption files this
repo has ever fetched, `>>` appears exactly ZERO times - YouTube does not emit
it on this channel. The signal is inert and every flag raised so far came from
signal 2 (keywords). It is kept because it costs nothing and would start
working if YouTube's caption format changed; do not read a `False` here as
evidence that a video is single-voice.
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


def parse_capture(path: Path):
    """Yield (start_seconds, text) per caption cue from a step-2 capture file.

    The capture is the single JSON SKILL.md step 2 writes from the TubeAlfred
    connector: {video_id, title, description, duration_sec, language_code,
    transcript: [{text, start_ms, start_time_text}, ...]}. It replaced a
    WebVTT parser - the connector hands back parsed cues, so re-deriving them
    from subtitle markup would be work for nothing.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    prev_text = None
    for cue in data.get("transcript") or []:
        text = html.unescape(re.sub(r"<[^>]+>", "", cue.get("text", "")).strip())
        if not text or text == prev_text:
            continue
        yield float(cue["start_ms"]) / 1000.0, text
        prev_text = text


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
    ap.add_argument("capture", type=Path,
                    help="transcripts/<id>.json written by SKILL.md step 2")
    ap.add_argument("--out", type=Path, help="Write flags JSON here (default: stdout)")
    args = ap.parse_args()

    data = json.loads(args.capture.read_text(encoding="utf-8"))
    title = data.get("title", "")
    description = data.get("description", "")
    duration = data.get("duration_sec") or 0

    entries = list(parse_capture(args.capture))
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
