#!/usr/bin/env python3
"""
Central log of every video the pipeline has touched: what was fetched,
what stage of processing it reached, and what flags were detected on it.
Also sends Telegram notifications at the three points that matter for a
once-a-day batch run: fetch started, compression done, and post-run verify.

Storage: a single JSON file, keyed by video_id, so it's easy to update one
video's record without rewriting/parsing line-by-line (default location:
log/videos.json at the project root).

Record shape (extensible on purpose - add new keys under "status" or "flags"
whenever a new pipeline stage or detector shows up, no schema migration needed):

{
  "<video_id>": {
    "title": "...",
    "url": "https://www.youtube.com/watch?v=<video_id>",
    "duration_sec": 1529,
    "status": {
      "fetched": "2026-07-06T18:02:00Z",
      "transcribed": "2026-07-06T18:05:00Z",
      "flags_detected": "2026-07-06T18:07:00Z",
      "compressed": "2026-07-06T18:10:00Z"
    },
    "flags": {
      "possible_other_speakers": {"value": true, "reason": "...", ...},
      "possible_sponsor_intro": {"value": true, "reason": "...", ...}
    }
  }
}

Notifications go through `hermes send` (no LLM/agent loop needed - safe to
call from a plain cron script). Telegram's own "important" notification mode
(display.platforms.telegram.notifications, default) already delivers these
silently (disable_notification=True) - no extra flag needed on our side.

CLI usage:
    # Stage 1 - create/update basic info after fetching, notify "started"
    uv run python3 log_registry.py touch <video_id> --title T --url U \\
        --duration-sec 1529 --stage fetched --notify

    # mark an intermediate stage done (no notification - see design notes)
    uv run python3 log_registry.py stage <video_id> transcribed

    # merge in a flags.json produced by detect_flags.py (no notification -
    # flags are summarized in the Stage 4 notification instead)
    uv run python3 log_registry.py set-flags <video_id> flags.json

    # Stage 4 - mark compression done, notify with token savings
    uv run python3 log_registry.py stage <video_id> compressed --notify \\
        --tokens-before 10964 --tokens-after 1764

    # Stage 5 - verify the record is internally consistent, notify either way
    uv run python3 log_registry.py verify <video_id> --notify

    # inspect
    uv run python3 log_registry.py show <video_id>
    uv run python3 log_registry.py list
    uv run python3 log_registry.py list --flag possible_other_speakers
"""

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG = Path("log/videos.json")
DEFAULT_TARGET = "telegram"
REQUIRED_STAGES = ("fetched", "transcribed", "flags_detected", "compressed")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_duration(seconds) -> str:
    if seconds is None:
        return "?"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def load(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def notify(message: str, target: str = DEFAULT_TARGET) -> None:
    """Fire-and-report a Telegram (or other platform) push via `hermes send`.

    No LLM/agent loop involved - safe to call from a cron script. Failures
    are printed to stderr but never raise, so a notification hiccup can't
    fail the pipeline itself.
    """
    try:
        result = subprocess.run(
            ["hermes", "send", "--to", target, "-q", message],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"[notify] hermes send failed ({result.returncode}): {result.stderr.strip()}",
                  flush=True)
    except FileNotFoundError:
        print("[notify] 'hermes' CLI not found on PATH - skipping notification", flush=True)
    except Exception as e:
        print(f"[notify] error sending notification: {e}", flush=True)


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

    if args.notify and args.stage == "fetched":
        title = rec.get("title", args.video_id)
        url = rec.get("url", "")
        dur = format_duration(rec.get("duration_sec"))
        notify(f"📥 Начал обработку: «{title}»\n{url} ({dur})", args.target)


def cmd_stage(args):
    data = load(args.log)
    rec = data.setdefault(args.video_id, {"status": {}, "flags": {}})
    rec["status"][args.stage] = now_iso()
    save(args.log, data)
    print(f"{args.video_id}: stage '{args.stage}' recorded")

    if args.notify and args.stage == "compressed":
        title = rec.get("title", args.video_id)
        lines = [f"✅ Добавлено в базу знаний: «{title}»"]
        if args.tokens_before and args.tokens_after:
            ratio = args.tokens_before / args.tokens_after if args.tokens_after else 0
            lines.append(f"Сжатие: {args.tokens_before} → {args.tokens_after} токенов (≈{ratio:.1f}x)")
        flags_on = [k for k, v in rec.get("flags", {}).items() if v.get("value")]
        if flags_on:
            lines.append(f"🚩 Флаги: {', '.join(flags_on)}")
        notify("\n".join(lines), args.target)


def cmd_set_flags(args):
    data = load(args.log)
    rec = data.setdefault(args.video_id, {"status": {}, "flags": {}})
    new_flags = json.loads(args.flags_json.read_text(encoding="utf-8"))
    rec.setdefault("flags", {}).update(new_flags)
    # Stamp the stage automatically (rather than requiring a separate
    # `stage <id> flags_detected` call) so `verify` can actually catch a
    # skipped/failed flags step - before this fix, no stage was ever
    # recorded for this step, so REQUIRED_STAGES couldn't see it was missing.
    rec.setdefault("status", {})["flags_detected"] = now_iso()
    save(args.log, data)
    print(f"{args.video_id}: flags updated -> {list(new_flags.keys())}")


def cmd_verify(args):
    data = load(args.log)
    rec = data.get(args.video_id)
    if rec is None:
        msg = f"⚠️ Проверка: {args.video_id} отсутствует в логе"
        print(msg)
        if args.notify:
            notify(msg, args.target)
        return

    status = rec.get("status", {})
    missing = [s for s in REQUIRED_STAGES if s not in status]
    title = rec.get("title", args.video_id)

    if missing:
        msg = f"⚠️ Проверка «{title}»: не хватает стадий {missing}"
    else:
        msg = f"🔎 Проверка «{title}»: все стадии на месте ({', '.join(REQUIRED_STAGES)}), расхождений нет"

    print(msg)
    if args.notify:
        notify(msg, args.target)


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
    # --log/--target live ONLY on the subparsers (via parents=[common]), not
    # on the top-level `ap` - deliberately, after finding that having them on
    # BOTH silently breaks the "before the subcommand" position: the
    # subparser re-applies its own default over whatever the top-level parser
    # already set, discarding the user's value with no error at all (worse
    # than the original bug, which at least failed loudly). Restricting them
    # to subparsers-only means "before the subcommand" now fails loudly
    # ("unrecognized arguments") instead of silently reverting to the
    # default, and "after the subcommand" - the only form documented in
    # SKILL.md - works correctly. Confirmed via direct argparse testing.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--log", type=Path, default=DEFAULT_LOG)
    common.add_argument("--target", default=DEFAULT_TARGET,
                         help="hermes send --to target (default: telegram home channel)")

    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("touch", parents=[common], help="create/update a record and set a stage timestamp")
    p.add_argument("video_id")
    p.add_argument("--title")
    p.add_argument("--url")
    p.add_argument("--duration-sec", type=int)
    p.add_argument("--stage", default="fetched")
    p.add_argument("--notify", action="store_true",
                    help="push a Telegram notification (only fires on --stage fetched)")
    p.set_defaults(func=cmd_touch)

    p = sub.add_parser("stage", parents=[common], help="mark a pipeline stage as done (timestamped)")
    p.add_argument("video_id")
    p.add_argument("stage")
    p.add_argument("--notify", action="store_true",
                    help="push a Telegram notification (only fires on stage=compressed)")
    p.add_argument("--tokens-before", type=int, help="pre-compression token count, for the notify message")
    p.add_argument("--tokens-after", type=int, help="post-compression token count, for the notify message")
    p.set_defaults(func=cmd_stage)

    p = sub.add_parser("set-flags", parents=[common], help="merge a flags.json (from detect_flags.py) into the record")
    p.add_argument("video_id")
    p.add_argument("flags_json", type=Path)
    p.set_defaults(func=cmd_set_flags)

    p = sub.add_parser("verify", parents=[common], help="check that all expected stages are recorded, optionally notify")
    p.add_argument("video_id")
    p.add_argument("--notify", action="store_true")
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
