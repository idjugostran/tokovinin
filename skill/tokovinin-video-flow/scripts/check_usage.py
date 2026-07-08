#!/usr/bin/env python3
"""
Pre-flight check: is the Anthropic/Claude account already over a usage
threshold? Meant to run once at the start of each cron cycle (every 3 hours), before
Step 1 of any video - if either window is over the threshold, skip the
whole cycle rather than starting work that might get rate-limited partway
through.

Anthropic's OAuth usage endpoint has no "daily" window - only:
  - five_hour: a rolling ~5h session window
  - seven_day: a rolling 7-day ("weekly") window
Both are checked here (per project decision - "either one over threshold
blocks the run", not just one or the other).

Token resolution is env-var only, deliberately - this script does NOT read
Hermes' or Claude Code's credential files directly (~/.hermes/auth.json,
~/.claude/.credentials.json, etc.). Reaching into another program's secret
store to reimplement its auth is fragile and a bad security boundary to
cross. Instead it expects the same token Hermes itself checks first, via
env var:
    ANTHROPIC_TOKEN            (Hermes-managed OAuth/setup token)
    CLAUDE_CODE_OAUTH_TOKEN     (Claude Code setup-token convention)
    ANTHROPIC_API_KEY           (plain API key - usage endpoint requires
                                 OAuth though, so this will just report
                                 "unavailable", not an error)
If none are set, the check is skipped (fail-open) - use --strict to fail
closed instead (exit 1) if you'd rather block the run than run unchecked.

Usage:
    uv run python3 check_usage.py --threshold 0.5
    echo $?   # 0 = OK to proceed, 1 = over threshold (or --strict + no token)

Exit codes:
    0 - OK to proceed (usage below threshold, or check skipped/unavailable
        and --strict was not passed)
    1 - over threshold on at least one window, OR --strict was passed and
        no usable token / the API call failed
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
WINDOWS = (("five_hour", "session (5h)"), ("seven_day", "week (7d)"))


def resolve_token() -> str | None:
    for var in ("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return None


def fetch_usage(token: str) -> dict:
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "claude-code/2.1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.5,
                     help="Utilization fraction (0-1) above which to block the run (default: 0.5 = 50%%)")
    ap.add_argument("--strict", action="store_true",
                     help="Exit 1 if no token is available or the API call fails, instead of fail-open")
    args = ap.parse_args()

    token = resolve_token()
    if not token:
        msg = "No ANTHROPIC_TOKEN/CLAUDE_CODE_OAUTH_TOKEN/ANTHROPIC_API_KEY in env - skipping usage check"
        print(msg, file=sys.stderr)
        sys.exit(1 if args.strict else 0)

    try:
        payload = fetch_usage(token)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"Usage check failed ({e}) - proceeding without it" if not args.strict
              else f"Usage check failed ({e}) - blocking run (--strict)", file=sys.stderr)
        sys.exit(1 if args.strict else 0)

    over_threshold = []
    for key, label in WINDOWS:
        window = payload.get(key) or {}
        util = window.get("utilization")
        if util is None:
            continue
        frac = float(util) if float(util) <= 1 else float(util) / 100
        print(f"{label}: {frac * 100:.0f}%", file=sys.stderr)
        if frac >= args.threshold:
            over_threshold.append((label, frac))

    if over_threshold:
        details = ", ".join(f"{label} at {frac*100:.0f}%" for label, frac in over_threshold)
        print(f"Over threshold ({args.threshold*100:.0f}%): {details} - skipping this cycle", file=sys.stderr)
        sys.exit(1)

    print("Under threshold on all checked windows - OK to proceed", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
