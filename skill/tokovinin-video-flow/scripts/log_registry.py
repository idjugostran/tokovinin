#!/usr/bin/env python3
"""
Central log of every video the pipeline has touched: what was fetched and
what stage of processing it reached.

Storage: a single JSON file, keyed by video_id, so it's easy to update one
video's record without rewriting/parsing line-by-line (default location:
log/videos.json at the project root). This file predates the wiki pipeline
(it has 65 historical entries from the old kb/-compression pipeline, each
with its own 4-key "status" block using different stage names) - those are
left untouched; only new entries use the stage names below.

Record shape (extensible on purpose - add new keys under "status" or "flags"
whenever a new pipeline stage or detector shows up, no schema migration needed):

{
  "<video_id>": {
    "title": "...",
    "url": "https://www.youtube.com/watch?v=<video_id>",
    "duration_sec": 1529,
    "status": {
      "fetched": "2026-08-16T18:02:00Z",
      "flags_detected": "2026-08-16T18:03:00Z",
      "wiki_ingested": "2026-08-16T18:12:00Z"
    },
    "flags": {
      "possible_other_speakers": {"value": true, "reason": "...", ...},
      "possible_sponsor_intro": {"value": true, "reason": "...", ...}
    }
  }
}

A video whose wiki-ingest was skipped because of a blocking contradiction
gets `stage <id> blocked` instead of `wiki_ingested` - `blocked` isn't in
REQUIRED_STAGES, so `verify` still correctly reports it as unfinished, and
the next run's `list_new_videos.py` naturally retries it (selection is by
wiki page presence, not log stage).

CLI usage:
    # create/update basic info after fetching, mark stage fetched
    python3 log_registry.py touch <video_id> --title T --url U \\
        --duration-sec 1529 --stage fetched

    # merge in a flags.json produced by detect_flags.py (auto-stamps
    # flags_detected)
    python3 log_registry.py set-flags <video_id> flags.json

    # mark the terminal stage done
    python3 log_registry.py stage <video_id> wiki_ingested

    # mark a run that was deferred due to a blocking contradiction
    python3 log_registry.py stage <video_id> blocked

    # verify the record has all required stages
    python3 log_registry.py verify <video_id>

    # inspect
    python3 log_registry.py show <video_id>
    python3 log_registry.py list
    python3 log_registry.py list --flag possible_other_speakers
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG = Path("log/videos.json")
REQUIRED_STAGES = ("fetched", "flags_detected", "wiki_ingested")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def cmd_touch(args):
    data = load(args.log)
    rec = data.setdefault(args.video_id, {"status": {}, "flags": {}})
    if args.title:
        rec["title"] = args.title
    if args.url:
        rec["url"] = args.url
    if args.duration_sec is not None:
        rec["duration_sec"] = args.duration_sec
    rec["status"][args.stage] = now_iso()
    save(args.log, data)
    print(f"{args.video_id}: stage '{args.stage}' recorded")


def cmd_stage(args):
    data = load(args.log)
    rec = data.setdefault(args.video_id, {"status": {}, "flags": {}})
    rec["status"][args.stage] = now_iso()
    save(args.log, data)
    print(f"{args.video_id}: stage '{args.stage}' recorded")


def cmd_set_flags(args):
    data = load(args.log)
    rec = data.setdefault(args.video_id, {"status": {}, "flags": {}})
    new_flags = json.loads(args.flags_json.read_text(encoding="utf-8"))
    rec.setdefault("flags", {}).update(new_flags)
    # Stamp the stage automatically (rather than requiring a separate
    # `stage <id> flags_detected` call) so `verify` can actually catch a
    # skipped/failed flags step.
    rec.setdefault("status", {})["flags_detected"] = now_iso()
    save(args.log, data)
    print(f"{args.video_id}: flags updated -> {list(new_flags.keys())}")


def cmd_verify(args):
    data = load(args.log)
    rec = data.get(args.video_id)
    if rec is None:
        print(f"⚠️ {args.video_id} not in log")
        return

    status = rec.get("status", {})
    missing = [s for s in REQUIRED_STAGES if s not in status]
    title = rec.get("title", args.video_id)

    if missing:
        print(f"⚠️ «{title}»: missing stage(s) {missing}")
    else:
        print(f"🔎 «{title}»: all stages present ({', '.join(REQUIRED_STAGES)})")


def cmd_show(args):
    data = load(args.log)
    rec = data.get(args.video_id)
    if rec is None:
        print(f"{args.video_id}: not in log")
        return
    print(json.dumps(rec, ensure_ascii=False, indent=2))


def cmd_list(args):
    data = load(args.log)
    for video_id, rec in data.items():
        if args.flag:
            flag = rec.get("flags", {}).get(args.flag)
            if not flag or not flag.get("value"):
                continue
        stages = ", ".join(rec.get("status", {}).keys())
        title = rec.get("title", "")
        flags_on = [k for k, v in rec.get("flags", {}).items() if v.get("value")]
        print(f"{video_id}  [{stages}]  flags={flags_on}  {title}")


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--log", type=Path, default=DEFAULT_LOG)

    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("touch", parents=[common], help="create/update a record and set a stage timestamp")
    p.add_argument("video_id")
    p.add_argument("--title")
    p.add_argument("--url")
    p.add_argument("--duration-sec", type=int)
    p.add_argument("--stage", default="fetched")
    p.set_defaults(func=cmd_touch)

    p = sub.add_parser("stage", parents=[common], help="mark a pipeline stage as done (timestamped)")
    p.add_argument("video_id")
    p.add_argument("stage")
    p.set_defaults(func=cmd_stage)

    p = sub.add_parser("set-flags", parents=[common], help="merge a flags.json (from detect_flags.py) into the record")
    p.add_argument("video_id")
    p.add_argument("flags_json", type=Path)
    p.set_defaults(func=cmd_set_flags)

    p = sub.add_parser("verify", parents=[common], help="check that all expected stages are recorded")
    p.add_argument("video_id")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("show", parents=[common], help="print one video's full record")
    p.add_argument("video_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("list", parents=[common], help="list all videos, optionally filtered by a truthy flag")
    p.add_argument("--flag")
    p.set_defaults(func=cmd_list)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
