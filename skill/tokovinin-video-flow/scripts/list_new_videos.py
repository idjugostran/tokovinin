#!/usr/bin/env python3
"""
Refresh channel_videos.txt from the channel and print the video IDs that
aren't in the log registry yet - the one mechanical step of the cron
run that previously had no script (see SKILL.md review notes): the agent had
to parse a human-formatted channel_videos.txt and diff it against
log/videos.json by hand every run.

Usage:
    uv run python3 list_new_videos.py --log log/videos.json --out channel_videos.txt
    uv run python3 list_new_videos.py --channel https://www.youtube.com/@other/videos ...

Behavior:
    1. Runs `yt-dlp --flat-playlist` against the channel and overwrites
       channel_videos.txt with one tab-separated
       `id<TAB>title<TAB>duration_string<TAB>view_count` line per video,
       newest first (as returned by the channel page). Tab, not `|`, on
       purpose: Tokovinin's own video titles routinely contain a literal
       `|` (e.g. "... | Misha Tokovinin" is the channel's own title
       convention - 49 of the current 62 titles have at least one), which
       would misalign the title/duration/views fields for any future
       consumer doing a naive split. Extracting the id here is maxsplit=1
       either way so it was never actually broken, but nothing else should
       have to know that footgun exists.
    2. Reads log/videos.json, takes its top-level keys as "already known"
       video IDs.
    3. Prints the channel IDs not in that set to stdout, one per line -
       nothing else on stdout, so this composes directly into a shell loop:

           for id in $(uv run python3 list_new_videos.py); do
               uv run python3 fetch_video.py "$id" ...
           done

    4. `--limit N` caps how many IDs get printed. Without it, ALL new IDs
       print - the pipeline instructions say "for each new id", so a first
       real run against a channel with a large backlog processes the whole
       backlog in one cron cycle (this is what actually happened the first
       time: 61 videos in a single run - by design, just not the intended
       cadence). When limiting, the OLDEST new videos are kept (the tail of
       the newest-first list), so a capped backlog gets worked through
       chronologically over successive cron cycles instead of always
       grabbing the same newest video and never reaching the backlog.

    Diagnostics (counts, the channel URL used, etc.) go to stderr, not stdout,
    so they don't get treated as video IDs by anything consuming this script's
    output.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_CHANNEL = "https://www.youtube.com/@mtokovinin/videos"


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=DEFAULT_CHANNEL, help="Channel /videos URL")
    ap.add_argument("--log", type=Path, default=Path("log/videos.json"))
    ap.add_argument("--out", type=Path, default=Path("channel_videos.txt"))
    ap.add_argument("--limit", type=int, default=None,
                     help="Max number of new video IDs to print (oldest-first among the new ones). Default: no limit.")
    args = ap.parse_args()

    print(f"Fetching video list from {args.channel} ...", file=sys.stderr)
    lines = fetch_channel_lines(args.channel)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} lines to {args.out}", file=sys.stderr)

    channel_ids = [line.split("\t", 1)[0] for line in lines]

    known_ids = set()
    if args.log.exists():
        known_ids = set(json.loads(args.log.read_text(encoding="utf-8")).keys())

    new_ids = [vid for vid in channel_ids if vid not in known_ids]
    print(f"{len(new_ids)} new video(s) out of {len(channel_ids)} on the channel page", file=sys.stderr)

    if args.limit is not None and len(new_ids) > args.limit:
        skipped = len(new_ids) - args.limit
        new_ids = new_ids[-args.limit:] if args.limit > 0 else []
        print(f"--limit {args.limit}: printing the {args.limit} oldest new video(s), "
              f"{skipped} remaining for future cycles", file=sys.stderr)

    for vid in new_ids:
        print(vid)


if __name__ == "__main__":
    main()
