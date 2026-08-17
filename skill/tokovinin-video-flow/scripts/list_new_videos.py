#!/usr/bin/env python3
"""
Print the video IDs that are on the channel but not yet in the wiki - one per
line, oldest-new-video first.

Usage:
    python3 list_new_videos.py --channel-file channel_videos.txt \
        --log log/videos.json --wiki-pages wiki/pages

This script does NOT talk to YouTube. It used to shell out to yt-dlp, which is
unusable in the environment this skill runs in: a cloud Routine forces all
egress through a proxy that refuses YouTube unless the domain is allow-listed,
and even then the datacenter IP invites a bot check. The channel listing now
arrives through the TubeAlfred connector, whose traffic does not go through
that proxy at all - the agent calls it, writes channel_videos.txt, and this
script reads that file. See SKILL.md step 1.

Input: channel_videos.txt, one tab-separated
`id<TAB>title<TAB>duration_string<TAB>view_count` line per video, NEWEST FIRST
(the order the channel page returns). Tab, not `|`, on purpose: Tokovinin's own
titles routinely contain a literal `|` (e.g. "... | Misha Tokovinin"), which
would misalign fields for any consumer doing a naive split.

Behavior:
    1. "Already processed" ground truth is a live scan of wiki/pages/*.md for
       `**Source:** raw/<id>.txt` header lines - NOT log/videos.json key
       presence. A log entry can exist with no wiki page (fetched but never
       finished ingesting - this repo genuinely has such a case), and a wiki
       page can exist with no log entry (hand-ingested without updating the
       log). The log is read only for
         a) the terminal-stage exclusion below, and
         b) two informational stderr warnings:
            - "stale": logged, but no wiki page yet - still a valid target,
              not excluded from the output.
            - "orphan": has a wiki page, but never logged - informational.
    2. Videos stamped with a TERMINAL_STAGES key in the log are EXCLUDED from
       the queue. Without this the oldest caption-less video sits at the head
       of the oldest-first queue forever and every future run burns on it,
       never reaching the videos behind it. To re-surface one, pass
       --include-no-captions (prints them, clearly marked, for manual triage)
       or delete the terminal key from its log record.
    3. Prints the surviving IDs, oldest-new-video first, one per line - nothing
       else on stdout, so this composes into "take the first line". Diagnostics
       go to stderr so they are never mistaken for video IDs.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SOURCE_LINE_RE = re.compile(r"\*\*Source:\*\*\s+raw/([A-Za-z0-9_-]{11})\.txt")

# Stages meaning "this video can never be ingested from YouTube captions as they
# stand". Kept as a tuple so a future terminal stage (e.g. members_only) is a
# one-line change here rather than a new branch.
#   no_captions     - YouTube has no caption track at all.
#   translated_only - only a machine-translated track exists; the channel speaks
#                     Russian, so that is not a transcript of the video.
TERMINAL_STAGES = ("no_captions", "translated_only")


def read_channel_file(path: Path) -> list[str]:
    """Video IDs from the agent-written channel listing, newest first."""
    if not path.exists():
        sys.exit(
            f"{path} not found. SKILL.md step 1 writes it from the TubeAlfred "
            f"connector's channel listing BEFORE calling this script."
        )
    ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        vid = line.split("\t", 1)[0].strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            sys.exit(f"{path}: not a video ID in first column: {vid!r}")
        ids.append(vid)
    # An empty listing is never legitimate - this channel has 65 videos. It
    # means the connector returned nothing or the file was truncated. Bail
    # loudly: an empty result here would otherwise read as "wiki is caught up".
    if not ids:
        sys.exit(f"{path} lists no videos - NOT 'caught up'. Refusing to guess.")
    return ids


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


def terminal_ids(log_data: dict) -> dict[str, str]:
    """Video ID -> the terminal stage it carries. Excluded from the work queue.
    Returns the stage, not just the id, so the operator's NOTE can say WHICH
    terminal reason applied - "no captions" and "translated only" need
    different follow-up, and a single lumped message would misreport one."""
    found = {}
    for vid, rec in log_data.items():
        for s in TERMINAL_STAGES:
            if s in (rec.get("status") or {}):
                found[vid] = s
                break
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel-file", type=Path, default=Path("channel_videos.txt"),
                    help="TSV written by SKILL.md step 1, newest first")
    ap.add_argument("--log", type=Path, default=Path("log/videos.json"))
    ap.add_argument("--wiki-pages", type=Path, default=Path("wiki/pages"))
    ap.add_argument(
        "--include-no-captions", action="store_true",
        help="Also print videos carrying a terminal stage. Manual triage only - "
             "the normal pipeline must not pass this, or it deadlocks on them.",
    )
    args = ap.parse_args()

    channel_ids = read_channel_file(args.channel_file)
    print(f"Read {len(channel_ids)} video(s) from {args.channel_file}", file=sys.stderr)

    known_ids = wiki_ingested_ids(args.wiki_pages)

    log_data = {}
    if args.log.exists():
        log_data = json.loads(args.log.read_text(encoding="utf-8"))
    log_ids = set(log_data)

    terminal = terminal_ids(log_data)
    detail = ", ".join(f"{vid} ({stage})" for vid, stage in sorted(terminal.items()))
    excluded = set(terminal)
    if args.include_no_captions:
        if terminal:
            print(f"NOTE: --include-no-captions: {len(terminal)} terminal id(s) "
                  f"re-surfaced for manual triage: {detail}", file=sys.stderr)
        excluded = set()
    elif terminal:
        print(f"NOTE: {len(terminal)} id(s) skipped as terminal: {detail}",
              file=sys.stderr)

    stale = log_ids - known_ids - excluded
    orphan = known_ids - log_ids
    if stale:
        print(f"NOTE: {len(stale)} id(s) logged but not yet wiki-ingested "
              f"(still candidates): {sorted(stale)}", file=sys.stderr)
    if orphan:
        print(f"NOTE: {len(orphan)} id(s) wiki-ingested but missing from "
              f"{args.log} (informational only): {sorted(orphan)}", file=sys.stderr)

    new_ids = [v for v in channel_ids if v not in known_ids and v not in excluded]
    print(f"{len(new_ids)} video(s) not yet in the wiki, out of "
          f"{len(channel_ids)} on the channel", file=sys.stderr)

    new_ids.reverse()  # channel listing is newest-first; work the backlog oldest-first
    for vid in new_ids:
        print(vid)


if __name__ == "__main__":
    main()
