#!/usr/bin/env bash
# Installer for the tokovinin-kb-context Claude skill.
#
# Installs ONE file (SKILL.md) — the knowledge base itself is never
# downloaded, the skill fetches it from GitHub over HTTPS at answer time.
# No git, no clone. Run it straight from GitHub with nothing pre-cloned:
#
#   curl -fsSL https://raw.githubusercontent.com/idjugostran/tokovinin/main/skill/tokovinin-kb-context/scripts/install.sh | bash
#
# Idempotent — re-running just overwrites the installed SKILL.md with the
# current one (that's also how you update it).
#
# Options (env var or flag; flags only work on a local copy, not curl|bash):
#   TOKOVININ_SKILLS_DIR   --dir PATH   skills dir (default: ~/.claude/skills)
#
# claude.ai (web) has no skills directory to write into — there, install by
# uploading the skill/tokovinin-kb-context/ folder through the Skills UI instead.
#
# To uninstall: rm -rf ~/.claude/skills/tokovinin-kb-context

set -euo pipefail

BASE_URL="https://raw.githubusercontent.com/idjugostran/tokovinin/main"
SKILL_NAME="tokovinin-kb-context"
SKILLS_DIR="${TOKOVININ_SKILLS_DIR:-$HOME/.claude/skills}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) SKILLS_DIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Check the kb is actually readable BEFORE installing anything - otherwise a
# network problem or a repo rename would install a skill that 404s on every
# question.
echo "== 1. Check knowledge base is readable =="
INDEX_URL="$BASE_URL/kb/index.md"
if ! INDEX="$(curl -fsS "$INDEX_URL")"; then
  echo "  ERROR: cannot read $INDEX_URL" >&2
  echo "         Check network access and that the repo is public." >&2
  exit 1
fi
VIDEOS="$(printf '%s\n' "$INDEX" | grep -c '^### ' || true)"
echo "  OK: $INDEX_URL ($VIDEOS videos)"

echo "== 2. Install SKILL.md =="
DEST="$SKILLS_DIR/$SKILL_NAME"
mkdir -p "$DEST"
curl -fsS "$BASE_URL/skill/tokovinin-kb-context/SKILL.md" -o "$DEST/SKILL.md"
echo "  OK: $DEST/SKILL.md"

echo "== Done =="
echo "Restart / start a new Claude session to pick it up."
