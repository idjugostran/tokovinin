---
name: tokovinin-video-flow
description: "Tokovinin videos to compact knowledge base: transcript, text-only flag detection, compressed notes, log registry."
platforms: [macos, linux]
---

# Tokovinin Video → Knowledge Base Pipeline

## When to use

Use when the user gives a YouTube link (or video ID) from Misha Tokovinin's
channel (@mtokovinin) and asks to add/process/summarize it into the project's
knowledge base, or says things like "обработай видео", "добавь ролик в базу",
"сожми транскрипцию для контекста".

Produces, per video: a cleaned transcript, a text-only flags file (no video
frames/screenshots involved anywhere in this pipeline — deliberately excluded,
see Design notes), a compressed markdown entry appended to `kb/tokovinin_kb.md`,
and an updated record in the central log registry `log/videos.json`.

## Why this exists

Tokovinin's channel is mostly a **reaction format**: he comments on a
compilation of other people's clips, with a sponsor ad at the start. Feeding
the raw transcript to a model wastes tokens on ad copy, filler, and verbatim
dialogue from other people. This pipeline strips that down to a compressed
per-video knowledge block (~1/6th the token count of the raw transcript) and
tracks, per video, whether it likely contains other people's voices — so a
later consumer of the knowledge base knows to treat quoted opinions carefully.

## Design notes

- **No screenshots / no video frame analysis.** An earlier version of this
  pipeline downloaded the video and classified frames pixel-by-pixel (ad
  end-card color, split-screen detection) to precisely label which lines were
  Tokovinin's own words. That approach is explicitly excluded now — this
  pipeline never downloads video, only subtitles + metadata (text).
  Consequence: detection is **video-level, not line-level** — a video gets
  flagged as "possibly contains other speakers", not split into "his words"
  vs. "their words". If line-level separation is ever needed again, treat it
  as a distinct, opt-in step, not part of this default flow.
- **Flags are approximate by construction.** `possible_sponsor_intro` and
  `possible_other_speakers` are heuristics with false positive/negative rates.
  Treat them as triage signals for a human/model to double check, not ground
  truth.
- **Flags are extensible without touching the schema.** Both the keyword lists
  (`references/*.txt`) and the log record's `flags` dict are designed to grow:
  add a keyword to a `.txt` file, or add a new detector function in
  `detect_flags.py` that returns another `"flag_name": {"value": ..., "reason": ...}`
  entry — no migration needed, `log_registry.py` just merges whatever keys it's given.

## Setup

System binary (not pip-installable — install once via Homebrew):
```bash
brew install yt-dlp
```
No Python dependencies beyond the standard library.

## Project layout

```
Tokovinin/
├── channel_videos.txt              # yt-dlp --flat-playlist video list
├── transcripts/
│   ├── <id>.ru.vtt, <id>.info.json      # raw fetch_video.py output
│   ├── <id>_full.txt                     # cleaned transcript, no labels
│   └── <id>.flags.json                   # detect_flags.py output (audit trail)
├── log/
│   └── videos.json                 # central registry: status + flags per video_id
└── kb/
    └── tokovinin_kb.md              # accumulated compressed notes, one ## block per video
```

## Workflow

### Step 0 — Usage pre-flight check (whole cron cycle, not per-video)

Run **once**, before Step 1 of the *first* video in a cron cycle - not
per-video:
```bash
python3 SKILL_DIR/scripts/check_usage.py --threshold 0.5
```
Checks the Anthropic account's `five_hour` (session) and `seven_day`
(weekly) usage windows - Anthropic has no "daily" window, so both of these
are checked and **either one** over 50% aborts. If it exits non-zero, **skip
the entire cycle** - don't process any videos this run, log nothing, just
stop (there will be another cron run later). If it exits 0, proceed with
Step 1 for every new video found.

Needs `ANTHROPIC_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, or `ANTHROPIC_API_KEY` in
the environment (same token Hermes itself resolves first) - fails open
(exit 0, i.e. proceed) if none is set, since the check itself is best-effort
against a semi-undocumented endpoint. Pass `--strict` to fail closed instead.

### Step 1 — Fetch transcript + metadata
```bash
python3 SKILL_DIR/scripts/fetch_video.py "<url_or_id>" --out-dir transcripts --skip-video
```
Writes `transcripts/<id>.ru.vtt` and `<id>.info.json` (title, description,
duration, chapters). `--skip-video` is now the default recommendation since
nothing downstream needs the video file.

Register the fetch in the log and send the "started" notification (Notification 1/3 — see Notifications section):
```bash
python3 SKILL_DIR/scripts/log_registry.py touch <id> \
  --title "<title from info.json>" --url "https://www.youtube.com/watch?v=<id>" \
  --duration-sec <duration> --stage fetched --notify
```

### Step 2 — Clean the transcript
```bash
python3 SKILL_DIR/scripts/clean_transcript.py transcripts/<id>.ru.vtt --out transcripts/<id>_full.txt
python3 SKILL_DIR/scripts/log_registry.py stage <id> transcribed
```
Strips VTT timestamps/tags, dedupes rolling-caption repeats, unescapes HTML
entities. Does **not** cut the ad — see Step 3, ad removal is now a flag +
approximate range, not a surgical cut, since there's no visual boundary to
anchor on from text alone.

### Step 3 — Detect flags (text-only)
```bash
python3 SKILL_DIR/scripts/detect_flags.py transcripts/<id>.ru.vtt \
  --info transcripts/<id>.info.json --out transcripts/<id>.flags.json
python3 SKILL_DIR/scripts/log_registry.py set-flags <id> transcripts/<id>.flags.json
```
Current detectors (see `scripts/detect_flags.py` docstring for exact logic):
- `possible_other_speakers` — rate of the `>>` auto-caption speaker-change
  marker per minute, plus keyword scan of title/description against
  `references/reaction-keywords.txt`.
- `possible_sponsor_intro` — keyword scan of the first ~90s of transcript
  against `references/sponsor-keywords.txt`; `approx_end_sec` is a rough
  estimate, not a precise cut point (the ad's legal disclaimer card is a
  burned-in visual, never spoken, so it can't be caught in captions at all).

To add a new flag: write a `detect_x(...)` function returning
`{"value": bool, "reason": str, ...anything else useful}` and add it to the
`flags` dict in `main()`. To tune existing flags: edit the `.txt` keyword
files, no code change needed.

### Step 4 — Compress into the knowledge base
Done by the model reading `transcripts/<id>_full.txt` in full — a semantic
summarization pass, not a script. Follow `references/compression-rules.md`
for what to keep/drop and the block format. If `possible_sponsor_intro` is
true, skip the ad content around `approx_end_sec` by judgment (the model can
usually tell where the ad copy ends just by reading). If
`possible_other_speakers` is true, keep the "clip/guest says X" vs.
"Tokovinin says Y" distinction explicit in the compressed notes (same as
before, just without a precise per-line boundary). Append as a new
`## <title>` block at the end of `kb/tokovinin_kb.md`; never rewrite earlier
blocks unless the user asks.

Measure the token counts (raw `_full.txt` vs. the new kb block) so the
notification can report the compression ratio, then mark the stage done
and send Notification 2/3:
```bash
python3 -c "import tiktoken; print(len(tiktoken.get_encoding('cl100k_base').encode(open('transcripts/<id>_full.txt').read())))"
# repeat on just the new kb block's text to get tokens_after
python3 SKILL_DIR/scripts/log_registry.py stage <id> compressed --notify \
  --tokens-before <N> --tokens-after <M>
```

### Step 5 — Verify
```bash
python3 SKILL_DIR/scripts/log_registry.py verify <id> --notify
```
Checks that all four stages (`fetched`, `transcribed`, `flags_detected`, `compressed`) are
recorded for this video and sends Notification 3/3 — either a confirmation
or a call-out of which stage is missing. This is the only stage-5 output;
don't also run `show`/manual token checks by default, that's what `verify`
replaces.

## Notifications

Videos are processed once a day (see Scheduling below), so per-video chatter
needs to stay minimal. Exactly **3 Telegram notifications per video**, no more:

| # | When | Step | Message content |
|---|------|------|------------------|
| 1 | fetch started | Step 1 (`touch ... --notify`) | title, url, duration |
| 2 | compression done | Step 4 (`stage ... compressed --notify`) | title, token count before/after + ratio, any active flags |
| 3 | post-run check | Step 5 (`verify ... --notify`) | confirmation, or which stage is missing |

Deliberately **not** notifying on `transcribed` or `set-flags` — those are
intermediate/uninteresting on their own; their content (flag values, token
counts) rides along inside notification #2 instead of getting a message of
their own.

Delivery goes through `hermes send` (`scripts/log_registry.py`'s `notify()`
helper — plain `subprocess`, no LLM/agent loop, safe to call from a cron
script). Target defaults to `telegram` (home channel); override globally with
`--target platform:chat_id` on any `log_registry.py` invocation.

Telegram's own `important` notification mode (the default —
`display.platforms.telegram.notifications` unset in config.yaml) already
delivers all of these silently (`disable_notification=True`); switch it to
`all` in config only if you want them to actually ping.

If `hermes send` fails (e.g. Telegram not yet connected via `hermes auth add
telegram`), `notify()` prints a warning to stderr and returns — it never
raises, so a notification hiccup can't take down the pipeline itself.

## Scheduling (every 3 hours)

One-time machine provisioning is a separate concern from this skill's
per-video workflow, so it lives in its own standalone script
(`scripts/setup.sh`) rather than in this always-loaded document. It is
self-contained on purpose — designed to run on a machine with **nothing**
pre-installed, as a single pasted command:

```bash
curl -fsSL https://raw.githubusercontent.com/idjugostran/tokovinin/main/skill/tokovinin-video-flow/scripts/setup.sh | bash
```

That one line clones the project (default `~/Tokovinin`, override with
`TOKOVININ_INSTALL_DIR`/`TOKOVININ_REPO_URL` env vars since there's no local
copy yet to pass CLI flags to), scaffolds `transcripts/`/`kb/`/`log/`,
installs `yt-dlp`, registers this skill with Hermes (adds the repo's `skill/`
dir to `skills.external_dirs` in `~/.hermes/config.yaml`), checks Telegram,
and creates the cron job (every 3 hours). Idempotent — pasting the same link again
later re-checks/updates everything without duplicating the cron job or
clobbering `kb/tokovinin_kb.md` / `log/videos.json` if they already have
real content.

Once cloned, the same script also accepts CLI flags for re-runs:
```bash
skill/tokovinin-video-flow/scripts/setup.sh --no-cron              # deps + scaffolding only, skip the cron job
skill/tokovinin-video-flow/scripts/setup.sh --schedule "0 */6 * * *" --job-name tokovinin-pipeline
```

See the script's header comment for the full step list and exactly why
`--deliver` is deliberately not passed to the cron job (it would double up
with the 3 per-video notifications this skill already sends via
`log_registry.py --notify`).

The cron job itself, once created, does 3 things each run:
1. **Step 0** (`check_usage.py`) — if over threshold, stop here, skip the
   whole cycle.
2. `python3 SKILL_DIR/scripts/list_new_videos.py --log log/videos.json --out channel_videos.txt --limit 1`
   — refreshes `channel_videos.txt` from the channel and prints **at most 1**
   video ID not yet in `log/videos.json` (the oldest unprocessed one), on
   stdout (diagnostics go to stderr). `--limit` exists specifically so a
   cron cycle processes one video at a time rather than draining an entire
   backlog in a single run — without it, the pipeline instructions ("for
   each new id") mean a first run against a channel with a large backlog
   processes everything it finds in one go (this is what happened the first
   real run: 61 videos in a single cycle). With `--limit 1` and a 3-hour
   schedule, a 61-video backlog instead spreads out over ~7.5 days,
   oldest-first.
3. Runs Steps 1-5 for the (at most one) printed ID.

No batch-level summary notification is set up — the 3 per-video notifications
above are the whole feed per video processed. Revisit `--limit` upward if
new-video volume grows enough that one-per-cycle can't keep up (see TODO).

## Inspecting the log

```bash
python3 SKILL_DIR/scripts/log_registry.py list                                   # all videos, one line each
python3 SKILL_DIR/scripts/log_registry.py list --flag possible_other_speakers    # only flagged ones
python3 SKILL_DIR/scripts/log_registry.py show <id>                              # full record
```

## Getting the channel's video list / finding new videos

```bash
python3 SKILL_DIR/scripts/list_new_videos.py --log log/videos.json --out channel_videos.txt
```
Overwrites `channel_videos.txt` with one tab-separated
`id<TAB>title<TAB>duration_string<TAB>view_count` line per video (newest
first, as returned by the channel page — that's the only ordering signal
available without a much slower full per-video extraction), and prints to
stdout just the IDs not already in `log/videos.json` — nothing else on
stdout, so it composes directly into a shell loop. Pass `--channel <url>` to
point it at a different channel.

Tab-separated, not `|`-separated: Tokovinin's own video titles routinely
contain a literal `|` (his channel's title convention is "... | Misha
Tokovinin"), which would misalign fields for anything doing a naive split on
`|`.

## Error Handling

- **yt-dlp `content not available on this app`**: yt-dlp version too old for
  current YouTube player changes. `brew upgrade yt-dlp` and retry.
- **Empty/missing `.ru.vtt`**: no Russian auto-captions; retry `fetch_video.py`
  with `--lang en` or check if captions are disabled entirely on the video.
- **`possible_sponsor_intro` false negative**: sponsor changed / new ad
  phrasing not in the keyword list — add the phrase to
  `references/sponsor-keywords.txt` and re-run `detect_flags.py`.
- **`possible_other_speakers` false negative** on a genuine reaction video:
  `>>` rate can be low if YouTube's captioner merged speaker turns; rely on
  the title/description keyword signal, or add a video-specific keyword to
  `references/reaction-keywords.txt`.

## TODO before treating this as final

- Validate `possible_sponsor_intro` and `possible_other_speakers` thresholds
  against 2-3 more videos — both keyword lists and the marker-rate threshold
  (currently 3.0/min) were tuned on a single episode (a8a-hy31pdI).
- Resolved: `log/videos.json` is committed (small, plain JSON, and it's the
  only record of what's already been processed — needed so `list_new_videos.py`
  works from a fresh clone).
- Consider making Step 4 (compression) itself a scripted call to a cheap model
  if this pipeline ends up running unattended over many videos.
- If the channel ever publishes many videos per day, 3 notifications/video
  will get noisy fast — switch to a single end-of-run batch summary at that
  point (see Notifications section).
