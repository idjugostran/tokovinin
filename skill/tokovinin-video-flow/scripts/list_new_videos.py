#!/usr/bin/env python3
"""
Refresh channel_videos.txt from the channel and print video IDs that are on
the channel but not yet in the wiki - one per line, oldest-new-video first.

Usage:
    python3 list_new_videos.py --log log/videos.json --wiki-pages wiki/pages --out channel_videos.txt
    python3 list_new_videos.py --channel https://www.youtube.com/@other/videos ...
    python3 list_new_videos.py --include-no-captions ...   # manual triage only

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
       updating the log). The log is still read, for two purposes:
         a) the `no_captions` exclusion below, and
         b) two informational warnings printed to stderr:
              - "stale": logged, but no wiki page yet - still a valid target,
                not excluded from the output.
              - "orphan": has a wiki page, but never logged - purely
                informational.
            Neither warning affects what gets printed to stdout.
    3. Videos stamped `status.no_captions` in the log are EXCLUDED from the
       output. YouTube has no captions for them at all, so SKILL.md step 3
       stops the run - and since selection is otherwise by wiki-page
       presence, and no page is ever written for them, such a video would
       sit at the head of the oldest-first queue forever and every future
       invocation would burn on it and stop. That is a deadlock, not a
       retry: the pipeline never reaches the videos behind it. Excluding
       them is what keeps "one invocation = one video landed" true.

       This is a terminal stamp, not a permanent verdict on the video.
       Captions occasionally appear later, and a human can always supply a
       transcript by hand. To re-surface such a video, either pass
       --include-no-captions (prints them, clearly marked, for manual
       triage) or delete the `no_captions` key from its log record.
    4. Prints channel IDs with no wiki page, oldest-new-video first, one per
       line - nothing else on stdout, so this composes directly into a shell
       loop or "take the first line" selection.

    IMPORTANT for callers: do NOT write
        VIDEO_ID=$(python3 list_new_videos.py ... | head -1)
    A pipeline's exit status is `head`'s, so a failure here (yt-dlp missing,
    network blocked, YouTube bot check) would leave VIDEO_ID empty and be
    indistinguishable from "caught up". Redirect to a file, check the exit
    code, then take the first line - see SKILL.md step 1.

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

# A stage that means "this video can never be ingested from YouTube captions".
# Kept as a tuple so a future terminal stage (e.g. members_only) is a one-line
# change here rather than a new branch.
TERMINAL_STAGES = ("no_captions",)


def fetch_channel_lines(channel_url: str) -> list[str]:
    result = subprocess.run(
        [
            "yt-dlp", "--flat-playlist",
            "--print", "%(id)s\t%(title)s\t%(duration_string)s\t%(view_count)s",
            channel_url,
        ],
        capture_output=True, text=True, timeout=600,
    )
    # Not check=True: CalledProcessError's message is just "returned non-zero
    # exit status 1" - it does NOT carry stderr, so the one line that says
    # whether this was the network allowlist ("403 / host_not_allowed") or
    # YouTube's bot check would be swallowed. In an unattended Routine that log
    # is the only diagnostic anyone gets, so print yt-dlp's own words.
    if result.returncode != 0:
        sys.exit(
            f"yt-dlp failed (exit {result.returncode}) on {channel_url}\n"
            f"--- yt-dlp stderr ---\n{result.stderr.strip() or '(empty)'}"
        )

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    # An empty listing on a zero exit is never legitimate - this channel has 65
    # videos. It means a soft block or a changed page layout. Bail BEFORE the
    # caller overwrites channel_videos.txt, which is tracked: writing "" there
    # would destroy real data and, because stdout is then also empty, the
    # pipeline would read it as the clean "wiki is caught up" case.
    if not lines:
        sys.exit(
            f"yt-dlp exited 0 but listed no videos on {channel_url} - refusing "
            f"to overwrite the channel list. This is a soft block or a layout "
            f"change, NOT an empty channel and NOT 'caught up'."
        )
    return lines


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


def terminal_ids(log_data: dict) -> set[str]:
    """Video IDs carrying a terminal stage - excluded from the work queue."""
    return {
        vid for vid, rec in log_data.items()
        if any(s in (rec.get("status") or {}) for s in TERMINAL_STAGES)
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=DEFAULT_CHANNEL, help="Channel /videos URL")
    ap.add_argument("--log", type=Path, default=Path("log/videos.json"))
    ap.add_argument("--wiki-pages", type=Path, default=Path("wiki/pages"))
    ap.add_argument("--out", type=Path, default=Path("channel_videos.txt"))
    ap.add_argument(
        "--include-no-captions", action="store_true",
        help="Also print videos stamped no_captions. Manual triage only - the "
             "normal pipeline must not pass this, or it deadlocks on them.",
    )
    args = ap.parse_args()

    print(f"Fetching video list from {args.channel} ...", file=sys.stderr)
    lines = fetch_channel_lines(args.channel)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} lines to {args.out}", file=sys.stderr)

    channel_ids = [line.split("\t", 1)[0] for line in lines]

    known_ids = wiki_ingested_ids(args.wiki_pages)

    log_data = {}
    if args.log.exists():
        log_data = json.loads(args.log.read_text(encoding="utf-8"))
    log_ids = set(log_data)

    excluded = terminal_ids(log_data)
    if args.include_no_captions:
        if excluded:
            print(f"NOTE: --include-no-captions: {len(excluded)} terminal id(s) "
                  f"re-surfaced for manual triage: {sorted(excluded)}", file=sys.stderr)
        excluded = set()
    elif excluded:
        print(f"NOTE: {len(excluded)} id(s) skipped - no captions on YouTube "
              f"(terminal): {sorted(excluded)}", file=sys.stderr)

    stale = log_ids - known_ids - excluded
    orphan = known_ids - log_ids
    if stale:
        print(f"NOTE: {len(stale)} id(s) logged but not yet wiki-ingested "
              f"(still candidates): {sorted(stale)}", file=sys.stderr)
    if orphan:
        print(f"NOTE: {len(orphan)} id(s) wiki-ingested but missing from "
              f"{args.log} (informational only): {sorted(orphan)}", file=sys.stderr)

    new_ids = [vid for vid in channel_ids if vid not in known_ids and vid not in excluded]
    print(f"{len(new_ids)} video(s) not yet in the wiki, out of "
          f"{len(channel_ids)} on the channel page", file=sys.stderr)

    new_ids.reverse()  # channel scan is newest-first; work the backlog oldest-first
    for vid in new_ids:
        print(vid)


if __name__ == "__main__":
    main()
