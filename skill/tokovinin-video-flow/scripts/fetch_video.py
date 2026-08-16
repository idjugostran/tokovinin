#!/usr/bin/env python3
"""
Fetch subtitles + metadata for a Misha Tokovinin (@mtokovinin) YouTube video via yt-dlp.

Text-only fetch — never downloads the video itself. This pipeline detects
signals from the transcript and metadata alone (see detect_flags.py), not
from video frames.

Usage:
    uv run python3 fetch_video.py <url_or_video_id> --out-dir DIR [--lang ru,en]

Writes into DIR:
    <id>.ru.vtt / <id>.en.vtt   - raw auto-subtitles
    <id>.info.json              - metadata (title, duration, chapters, channel)

Requires a system binary (not pip-installable): yt-dlp.
    brew install yt-dlp
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path


def extract_video_id(url_or_id: str) -> str:
    url_or_id = url_or_id.strip()
    patterns = [
        r'(?:v=|youtu\.be/|shorts/|embed/|live/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',
    ]
    for pattern in patterns:
        m = re.search(pattern, url_or_id)
        if m:
            return m.group(1)
    return url_or_id


def run(cmd):
    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="YouTube URL or 11-char video ID")
    ap.add_argument("--out-dir", default="transcripts", help="Output directory")
    ap.add_argument("--lang", default="ru,en", help="Subtitle languages, comma-separated")
    args = ap.parse_args()

    video_id = extract_video_id(args.url)
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / video_id

    run([
        "yt-dlp", "--skip-download",
        "--write-auto-sub", "--write-sub", "--sub-lang", args.lang, "--sub-format", "vtt",
        "--write-description", "--write-info-json",
        "-o", str(base), url,
    ])

    print(f"Done. Files written under {out_dir}/{video_id}.*", file=sys.stderr)


if __name__ == "__main__":
    main()
