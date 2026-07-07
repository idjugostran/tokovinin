#!/usr/bin/env python3
"""
Clean a YouTube auto-subtitle .vtt into plain text: strip timestamps/tags,
unescape HTML entities, dedupe the "rolling caption" repeats, and turn the
`>>` speaker-change marker into an explicit separator.

No video/screenshot analysis here - text only.

Usage:
    uv run python3 clean_transcript.py VIDEO.ru.vtt --out OUT.txt
"""

import argparse
import html
import re
from pathlib import Path


def ts_to_sec(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_vtt(path: Path):
    """Yield (start_seconds, text) for each unique caption line, deduped."""
    content = path.read_text(encoding="utf-8")
    prev_text = None
    for block in content.split("\n\n"):
        lines = block.split("\n")
        ts_line = next((l for l in lines if "-->" in l), None)
        if not ts_line:
            continue
        start_str = ts_line.split("-->")[0].strip().split(" ")[0]
        try:
            t = ts_to_sec(start_str)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vtt", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    entries = list(parse_vtt(args.vtt))
    text = " ".join(t for _, t in entries)
    text = text.replace(">>", " — ")
    text = re.sub(r"\s+", " ", text).strip()

    args.out.write_text(text, encoding="utf-8")
    print(f"Wrote {args.out} ({len(entries)} caption lines, {len(text)} chars)")


if __name__ == "__main__":
    main()
