#!/usr/bin/env bash
# Standalone installer for the tokovinin-video-flow pipeline + skill.
#
# Designed to be run as a one-liner straight from GitHub, with nothing
# pre-cloned on the machine:
#
#   curl -fsSL https://raw.githubusercontent.com/idjugostran/tokovinin/main/skill/tokovinin-video-flow/scripts/setup.sh | bash
#
# Everything is self-contained: it clones the project, installs system deps,
# scaffolds the project's data directories, registers the skill with Hermes,
# and creates the cron job (every 3 hours by default). Idempotent - safe to
# re-run (e.g. paste the same link again later to update + re-check
# everything).
#
# Override defaults via env vars (useful for the curl|bash form, where there's
# no way to pass CLI flags before the script exists locally):
#   TOKOVININ_REPO_URL   git remote to clone (default: see REPO_URL below)
#   TOKOVININ_INSTALL_DIR  where to clone it (default: ~/Tokovinin)
# CLI flags (only usable once you have a local copy, e.g. `./setup.sh --no-cron`):
#   --dir PATH            same as TOKOVININ_INSTALL_DIR
#   --repo URL             same as TOKOVININ_REPO_URL
#   --no-cron              skip cron job creation (deps + scaffolding only)
#   --schedule EXPR        cron schedule (default: "0 */3 * * *" - every 3 hours)
#   --job-name NAME        cron job name (default: tokovinin-pipeline)
#
# What it does, in order:
#   0. Clones the project repo (or `git pull --ff-only` if already cloned).
#   1. Creates the project's directory skeleton (transcripts/, kb/, log/) and
#      seeds kb/tokovinin_kb.md + log/videos.json - but only the files that
#      don't already exist, so re-running never clobbers real accumulated
#      notes on a machine that's been running this for a while.
#   2. Checks/installs yt-dlp via Homebrew (the only system dependency).
#   3. Checks the `hermes` CLI is on PATH (can't install Hermes itself here -
#      that's a separate onboarding step, see hermes.nousresearch.com).
#   4. Registers the skill with Hermes by adding the cloned repo's `skill/`
#      directory to `skills.external_dirs` in ~/.hermes/config.yaml (best-
#      effort text patch, skipped with a manual instruction if the config's
#      current shape isn't one of the two forms this script knows how to
#      patch safely - never guesses past that).
#   5. Checks whether Telegram is connected (`hermes send --list telegram`);
#      warns but does not fail if not - notifications will just no-op until
#      `hermes auth add telegram` is run separately.
#   6. Creates the cron job (every 3 hours by default) via `hermes cron
#      create`, bound to this skill, with --workdir set to the cloned
#      project's root. Skips creation if a job with the same --name already
#      exists.

set -euo pipefail

REPO_URL="${TOKOVININ_REPO_URL:-https://github.com/idjugostran/tokovinin.git}"
INSTALL_DIR="${TOKOVININ_INSTALL_DIR:-$HOME/Tokovinin}"
JOB_NAME="tokovinin-pipeline"
SCHEDULE="0 */3 * * *"
CREATE_CRON=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    --no-cron) CREATE_CRON=0; shift ;;
    --schedule) SCHEDULE="$2"; shift 2 ;;
    --job-name) JOB_NAME="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

echo "== 0. Clone/update project =="
if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "  Existing checkout found at $INSTALL_DIR - pulling..."
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "  Cloning $REPO_URL -> $INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi
PROJECT_ROOT="$(cd "$INSTALL_DIR" && pwd)"
SKILL_PARENT_DIR="$PROJECT_ROOT/skill"

echo "== 1. Project directories =="
mkdir -p "$PROJECT_ROOT/transcripts" "$PROJECT_ROOT/kb" "$PROJECT_ROOT/log"
echo "  OK: transcripts/, kb/, log/ under $PROJECT_ROOT"

KB_FILE="$PROJECT_ROOT/kb/tokovinin_kb.md"
if [[ -f "$KB_FILE" ]]; then
  echo "  OK: kb/tokovinin_kb.md already exists - leaving it alone"
else
  cat > "$KB_FILE" <<'EOF'
# Токовинин — база знаний по видео (сжатые конспекты)

<!-- ШАБЛОН для каждого нового видео:
## [ГГГГ-ММ-ДД] Название | video_id | длительность
Тема: 1 строка, что за видео (реакция/монолог/интервью и т.д.)
### [Глава/таймкод]
- тезис 1 (кто говорит, если не сам автор — помечать)
- тезис 2
- цифры/факты дословно, если есть
- цитаты только если реально ёмкие и запоминающиеся
Не включать: рекламу, шутки/смех, воду, повторы, разбор чужого ролика дословно (только суть претензии/тезиса).
-->
EOF
  echo "  Created kb/tokovinin_kb.md with the template header"
fi

LOG_FILE="$PROJECT_ROOT/log/videos.json"
if [[ -f "$LOG_FILE" ]]; then
  echo "  OK: log/videos.json already exists - leaving it alone"
else
  echo "{}" > "$LOG_FILE"
  echo "  Created empty log/videos.json"
fi

echo "== 2. yt-dlp =="
if command -v yt-dlp >/dev/null 2>&1; then
  echo "  OK: $(yt-dlp --version)"
else
  echo "  Not found - installing via Homebrew..."
  brew install yt-dlp
fi

echo "== 3. hermes CLI =="
if command -v hermes >/dev/null 2>&1; then
  echo "  OK: $(hermes --version 2>&1 | head -1)"
else
  echo "  ERROR: 'hermes' not found on PATH. Install Hermes first:"
  echo "         https://hermes.nousresearch.com"
  exit 1
fi

echo "== 4. Register skill with Hermes (skills.external_dirs) =="
python3 - "$SKILL_PARENT_DIR" <<'PYEOF'
import re
import sys
from pathlib import Path

skill_parent_dir = sys.argv[1]
config_path = Path.home() / ".hermes" / "config.yaml"

if not config_path.exists():
    print(f"  WARNING: {config_path} not found - skipping (run 'hermes' once to create it, then re-run this script)")
    sys.exit(0)

text = config_path.read_text(encoding="utf-8")

if skill_parent_dir in text:
    print(f"  OK: {skill_parent_dir} already registered in skills.external_dirs")
    sys.exit(0)

# Case 1: empty flow-style list -> "external_dirs: []"
flow_empty = re.search(r"^(\s*)external_dirs:\s*\[\]\s*$", text, re.MULTILINE)
if flow_empty:
    indent = flow_empty.group(1)
    new_line = f'{indent}external_dirs: ["{skill_parent_dir}"]'
    text = text[:flow_empty.start()] + new_line + text[flow_empty.end():]
    config_path.write_text(text, encoding="utf-8")
    print(f"  Added {skill_parent_dir} to skills.external_dirs (was empty)")
    sys.exit(0)

# Case 2: non-empty flow-style list -> "external_dirs: [a, b]"
flow_nonempty = re.search(r"^(\s*)external_dirs:\s*\[(.*)\]\s*$", text, re.MULTILINE)
if flow_nonempty:
    indent, inner = flow_nonempty.group(1), flow_nonempty.group(2).strip()
    new_inner = f'{inner}, "{skill_parent_dir}"' if inner else f'"{skill_parent_dir}"'
    new_line = f"{indent}external_dirs: [{new_inner}]"
    text = text[:flow_nonempty.start()] + new_line + text[flow_nonempty.end():]
    config_path.write_text(text, encoding="utf-8")
    print(f"  Added {skill_parent_dir} to skills.external_dirs (existing flow list)")
    sys.exit(0)

# Case 3: block-style list -> "external_dirs:\n  - foo\n  - bar"
block = re.search(r"^(\s*)external_dirs:\s*\n((?:\1\s+- .*\n?)*)", text, re.MULTILINE)
if block:
    indent = block.group(1)
    item_indent = indent + "  "
    insert_at = block.end()
    new_item = f'{item_indent}- "{skill_parent_dir}"\n'
    text = text[:insert_at] + new_item + text[insert_at:]
    config_path.write_text(text, encoding="utf-8")
    print(f"  Added {skill_parent_dir} to skills.external_dirs (existing block list)")
    sys.exit(0)

print("  WARNING: could not find a recognizable 'external_dirs:' shape in")
print(f"           {config_path} - add it manually under skills.external_dirs:")
print(f'             - "{skill_parent_dir}"')
PYEOF

echo "== 5. Telegram connection =="
if hermes send --list telegram >/dev/null 2>&1; then
  echo "  OK: Telegram is connected"
else
  echo "  WARNING: Telegram not connected yet."
  echo "           Notifications (--notify in log_registry.py) will silently"
  echo "           no-op until you run: hermes auth add telegram"
fi

if [[ "$CREATE_CRON" -eq 0 ]]; then
  echo "== Skipping cron job creation (--no-cron) =="
  exit 0
fi

echo "== 6. Cron job (every 3 hours) =="
# Match the name as a whole whitespace-bounded token, not a bare substring -
# `hermes cron list` has no --json output to key off reliably, and a plain
# `grep -q "$JOB_NAME"` would also match e.g. a "tokovinin-pipeline-v2" job.
# Still not bulletproof (depends on list output separating fields by
# whitespace), just meaningfully safer than a raw substring match.
if hermes cron list 2>/dev/null | grep -qE "(^|[[:space:]])${JOB_NAME}([[:space:]]|$)"; then
  echo "  Job '$JOB_NAME' already exists - skipping (use 'hermes cron edit $JOB_NAME ...' to change it)"
else
  # Both positionals (schedule, prompt) must come before the --flags, not
  # interleaved with them - `hermes cron create` splits argparse's optional
  # and positional actions into separate groups internally, so an
  # optional flag sitting between the two positionals confuses which
  # group the trailing string belongs to and it bubbles up to the
  # top-level parser as "unrecognized arguments" instead of being
  # consumed as the `prompt` positional. Confirmed by hitting this for
  # real on 2026-07-08.
  hermes cron create "$SCHEDULE" \
    "Run Step 0 (check_usage.py) first - if it exits non-zero, stop and skip this cycle entirely. Otherwise check @mtokovinin for new videos (channel_videos.txt vs log/videos.json keys) and run the pipeline (Steps 1-5) for each new id." \
    --name "$JOB_NAME" \
    --skill tokovinin-video-flow \
    --workdir "$PROJECT_ROOT"
  echo "  Created job '$JOB_NAME' (schedule: $SCHEDULE, workdir: $PROJECT_ROOT)"
fi

echo "== Done =="
echo "Project installed at: $PROJECT_ROOT"
echo "Manage the cron job with: hermes cron list / pause / edit / rm $JOB_NAME"
