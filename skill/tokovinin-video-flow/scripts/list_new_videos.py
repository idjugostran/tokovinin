#!/usr/bin/env python3
"""
Refresh channel_videos.txt from the channel and print video IDs that are on
the channel but not yet in the wiki - one per line, oldest-new-video first.

Usage:
    python3 list_new_videos.py --log log/videos.json --wiki-pages wiki/pages --out channel_videos.txt
    python3 list_new_videos.py --channel https://www.youtube.com/@other/videos ...

Behavior:
    1. Runs `yt-dlp --flat-playlist` against the channel and overwrites
       channel_videos.txt with one tab-separated
       `id<TAB>title<TAB>duration_string<TAB>view_count` line per video,
       newest first (as returned by the channel page). Tab, not `|`, on
       purpose: Tokovinin's own video titles routinely contain a literal
       `|` (e.g. "... | Misha Tokovinin"), which would misalign fields for
       any consumer doing a naive split.
    2. "Already processed" ground truth is a live scan of wiki/pages/*.md for
       `**Source:** raw/<id>.txt` header lines - NOT log/videos.json key
       presence. A log entry can exist with no wiki page (fetched but never
       finished ingesting - e.g. this repo genuinely has one such case), and
       a wiki page can exist with no log entry (hand-ingested without
       updating the log). The log is still read, but only to print two
       informational warnings to stderr:
         - "stale": logged, but no wiki page yet - still a valid target,
           not excluded from the output.
         - "orphan": has a wiki page, but never logged - purely informational.
       Neither warning affects what gets printed to stdout.
    3. Prints channel IDs with no wiki page, oldest-new-video first, one per
       line - nothing else on stdout, so this composes directly into a shell
       loop or "take the first line" selection:

           VIDEO_ID=$(python3 list_new_videos.py --log log/videos.json --wiki-pages wiki/pages | head -1)

    Diagnostics (counts, warnings, the channel URL used) go to stderr, not
    stdout, so they never get treated as video IDs.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_CHANNEL = "https://www.youtube.com/@mtokovinin/videos"

SOURCE_LINE_RE = re.compile(r"\*\*Source:\*\*\s+raw/([A-Za-z0-9_-]{11})\.txt")


def fetch_channel_lines(channel_url: str) -> list[str]:
    result = subprocess.run(
        [
            "yt-dlp", "--flat-playlist",
            "--print", "%(id)s\t%(title)s\t%(duration_string)s\t%(view_count)s",
            channel_url,
        ],
        capture_output=True, text=True, check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def wiki_ingested_ids(pages_dir: Path) -> set[str]:
    """Video IDs that already have a Source page in the wiki - the real
    ground truth for "already processed", independent of log/videos.json."""
    ids = set()
    if not pages_dir.exists():
        return ids
    for page in pages_dir.glob("*.md"):
        if page.name.startswith("audit-"):
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        for m in SOURCE_LINE_RE.finditer(text):
            ids.add(m.group(1))
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=DEFAULT_CHANNEL, help="Channel /videos URL")
    ap.add_argument("--log", type=Path, default=Path("log/videos.json"))
    ap.add_argument("--wiki-pages", type=Path, default=Path("wiki/pages"))
    ap.add_argument("--out", type=Path, default=Path("channel_videos.txt"))
    args = ap.parse_args()

    print(f"Fetching video list from {args.channel} ...", file=sys.stderr)
    lines = fetch_channel_lines(args.channel)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} lines to {args.out}", file=sys.stderr)

    channel_ids = [line.split("\t", 1)[0] for line in lines]

    known_ids = wiki_ingested_ids(args.wiki_pages)

    log_ids = set()
    if args.log.exists():
        log_ids = set(json.loads(args.log.read_text(encoding="utf-8")).keys())

    stale = log_ids - known_ids
    orphan = known_ids - log_ids
    if stale:
        print(f"NOTE: {len(stale)} id(s) logged but not yet wiki-ingested "
              f"(still candidates): {sorted(stale)}", file=sys.stderr)
    if orphan:
        print(f"NOTE: {len(orphan)} id(s) wiki-ingested but missing from "
              f"{args.log} (informational only): {sorted(orphan)}", file=sys.stderr)

    new_ids = [vid for vid in channel_ids if vid not in known_ids]
    print(f"{len(new_ids)} video(s) not yet in the wiki, out of "
          f"{len(channel_ids)} on the channel page", file=sys.stderr)

    new_ids.reverse()  # channel scan is newest-first; work the backlog oldest-first
    for vid in new_ids:
        print(vid)


if __name__ == "__main__":
    main()
