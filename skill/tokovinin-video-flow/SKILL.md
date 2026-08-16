---
name: tokovinin-video-flow
description: "Fetches the next new @mtokovinin video and adds it to the Tokovinin wiki (wiki-ingest), commits, and pushes. Manual invocation only."
---

# Tokovinin Video Flow

Takes the wiki at `/Users/idjugostran/Projects/Tokovinin` from "N videos ingested"
to "N+1 videos ingested" for exactly **one** new video per invocation: clone/pull
the repo, fetch that video's transcript, run the same `wiki-ingest` process used to
build the other 231 pages by hand, commit, and push. Designed to run inside an
agentic environment with Bash + git + network access (Claude Cowork, Claude Code,
or similar) — this file assumes the agent reading it can run shell commands and
edit files directly, not that it's calling some Cowork-specific API.

**Trigger: explicit invocation only** — "process the next Tokovinin video", "run
video-flow", "ingest the newest video on the channel". Unlike the read-only
`tokovinin-wiki-context` skill, this one writes and pushes to a real repository —
it must never fire passively just because Tokovinin came up in conversation.

**Full autonomy on push, one boundary.** This skill never pauses for confirmation
before writing or before pushing — that's been explicitly delegated. It also never
uses `git commit --no-verify` and never hand-edits `wiki/index.md` — those two
invariants hold regardless of autonomy. If the wiki-ingest contradiction gate blocks
(step 7), the skill does not try to resolve it and does not bypass the hook to force
a push through — see step 7 for the exact fallback.

## Prerequisites

- **Push access.** Two environments, both handled by step 0:
  - *Local (Claude Code on the owner's machine)* — a git credential helper
    (`osxkeychain`) already holds the credentials. Nothing to provide.
  - *Cloud sandbox (Claude Cowork or similar)* — no credentials exist there, so a
    **fine-grained GitHub PAT scoped to `idjugostran/tokovinin` with
    `Contents: Read and write`** must be present in the environment as `$GH_TOKEN`.
    Step 0 wires it into a credential helper that keeps it in the environment and
    never writes it to `.git/config`. This skill never creates, prints, or asks for
    the token — if `$GH_TOKEN` is unset and no helper is configured, step 0's
    `push --dry-run` fails fast and the run stops before any expensive work.
- **Never run these steps under `set -x`.** Shell tracing would print `$GH_TOKEN`
  into the session log.
- `yt-dlp` — checked and installed via pip in step 0, not assumed present. A cloud
  sandbox's datacenter IP may still get YouTube's "Sign in to confirm you're not a
  bot" on step 1; that's a hard stop, not something to retry differently.

## Procedure

Every step below is tagged **[script]** (a deterministic command, no judgment) or
**[judgment]** (the agent reads content and decides — not scriptable).

### 0. [script] Preflight — every invocation

```bash
if [ -f SCHEMA.md ] && [ -d wiki ]; then
  :                       # cwd is already the repo root
elif [ -d tokovinin/.git ]; then
  cd tokovinin
else
  git clone https://github.com/idjugostran/tokovinin.git tokovinin && cd tokovinin
fi
git pull --ff-only
```

Clone into `tokovinin/`, never into the cwd: `git clone <url> .` fails outright if
the cwd holds anything at all, and a cloud sandbox's working directory routinely
does (uploads, prior artifacts).

If the pull isn't a fast-forward (uncommitted local state from a previous crashed
run), **stop and surface it** — this is the one place autonomy doesn't extend to
silently discarding unknown local state.

```bash
git config user.name  "idjugostran"
git config user.email "idjugostran@gmail.com"
git config core.hooksPath bin/hooks
```

All three repo-local, unconditional, idempotent. Set the identity **every time, not
`|| `-guarded on emptiness** — a cloud sandbox ships a *pre-seeded* default of
`Claude <noreply@anthropic.com>`, so a guard on "is it unset?" never fires and the
whole wiki's history silently lands under the wrong author. `core.hooksPath` is
likewise repo-local and **not** carried by a fresh clone (SCHEMA.md's own documented
gotcha), so it must run every time, not just "if this looks like a fresh clone."

If GitHub rejects the push later with `GH007` (the account blocks pushes that expose
a private email), switch `user.email` to the account's
`<id>+idjugostran@users.noreply.github.com` form and re-commit.

```bash
[ -z "$GH_TOKEN" ] || git config credential.helper \
  '!f() { echo username=x-access-token; echo "password=$GH_TOKEN"; }; f'
git push --dry-run origin HEAD || { echo "no push access — stop"; exit 1; }
```

The helper reads `$GH_TOKEN` from the environment at push time, so the token never
lands in `.git/config` where a repo dump would leak it. Locally `$GH_TOKEN` is unset
and the existing keychain helper handles auth — hence the `[ -z ]` guard. The
`--dry-run` authenticates for real against the remote: it turns "no credentials" from
a step-11 failure *after* a full ingest into a two-second failure before any work.

```bash
export PATH="$HOME/.local/bin:$PATH"
command -v yt-dlp >/dev/null \
  || python3 -m pip install --user yt-dlp \
  || python3 -m pip install --user --break-system-packages yt-dlp
command -v yt-dlp >/dev/null || { echo "yt-dlp unavailable — stop"; exit 1; }
```

Three things this guards, all of which bite on a stock Linux image: `pip` may not
exist as a command (only `python3 -m pip`); `--user` installs land in
`~/.local/bin`, which is often not on `PATH`, so `command -v` stays empty *after* a
successful install; and PEP 668 makes the plain `--user` install refuse with
`externally-managed-environment`, which the `--break-system-packages` retry clears.
The final re-check is what actually matters — never proceed to step 1 assuming the
install worked.

### 1. [script] Discover the one video to process

```bash
python3 skill/tokovinin-video-flow/scripts/list_new_videos.py \
  --log log/videos.json --wiki-pages wiki/pages --out channel_videos.txt \
  > new_videos.txt || { echo "channel listing FAILED — not 'caught up'"; exit 1; }
VIDEO_ID=$(head -1 new_videos.txt)
```

Redirect to a file and check the exit code **before** taking the first line. Do
**not** write `VIDEO_ID=$(... | head -1)`: a pipeline's exit status is `head`'s, so
any failure of the listing (yt-dlp missing, network down, YouTube's bot check) would
leave `$VIDEO_ID` empty and get reported as the success case below — a silent false
"caught up" that looks exactly like a clean run. `set -o pipefail` would fix *that*
but introduces its own trap: `head -1` closes the pipe early, and once the producer's
output exceeds the pipe buffer the resulting SIGPIPE surfaces as exit 120 on an
otherwise successful run (measured: 65 channel lines pass, 200k lines fail). The
redirect sidesteps the question instead of tuning around a buffer size.

If the command succeeded and `$VIDEO_ID` is empty: **report "wiki is caught up with
the channel" and stop.** No commit, no push. (`new_videos.txt` is scratch — it is
untracked and never staged; delete it or leave it, but never `git add` it.)

`list_new_videos.py` cross-checks the channel against `wiki/pages/*.md`'s
`**Source:** raw/<id>.txt` headers (the real ground truth), not just
`log/videos.json` keys — a video can be logged as "fetched" from a previous run
that never finished (this repo has exactly one such case today) and still needs
processing. Read the script's stderr for `NOTE:` warnings before proceeding.

### 2. [script] Fetch

```bash
python3 skill/tokovinin-video-flow/scripts/fetch_video.py "$VIDEO_ID" --out-dir transcripts
```

Writes `transcripts/$VIDEO_ID.ru.vtt` (or `.en.vtt` if Russian captions aren't
available), `transcripts/$VIDEO_ID.info.json`, `transcripts/$VIDEO_ID.description`.
Read `title` and `duration` from `.info.json`, then:

```bash
python3 skill/tokovinin-video-flow/scripts/log_registry.py touch "$VIDEO_ID" \
  --title "<title>" --url "https://www.youtube.com/watch?v=$VIDEO_ID" \
  --duration-sec <duration> --stage fetched
```

### 3. [script] Clean straight into `raw/`

```bash
VTT="transcripts/$VIDEO_ID.ru.vtt"
[ -f "$VTT" ] || VTT="transcripts/$VIDEO_ID.en.vtt"
```

**If neither file exists, the video has no captions on YouTube at all** — this is
real, not hypothetical: `ZS5fd3f_Lek` (204k views, the channel's most-viewed video)
hit exactly this. `yt-dlp --list-subs` on it reports "has no automatic captions" /
"has no subtitles" — nothing to fetch, no fallback language helps. When this
happens:

```bash
python3 skill/tokovinin-video-flow/scripts/log_registry.py stage "$VIDEO_ID" no_captions
```

Report plainly ("no captions available for `<id>` — `<title>`, skipping") and
**stop for this video** — no `wiki/`/`raw/` changes, nothing to commit. Do not treat
this as an error to retry differently; there is no different fetch strategy that
produces captions YouTube never generated. It stays a candidate in
`list_new_videos.py`'s output (no wiki page exists for it), so a future run will
surface it again — that's expected, not a bug; captions occasionally appear later,
and a human can always intervene (e.g. supply a transcript manually) if they don't.

Otherwise:

```bash
[ -f "raw/$VIDEO_ID.txt" ] || python3 skill/tokovinin-video-flow/scripts/clean_transcript.py \
  "$VTT" --out "raw/$VIDEO_ID.txt"
```

`raw/$VIDEO_ID.txt` is the **only** cleaned-transcript output — no intermediate
`transcripts/<id>_full.txt` duplicate. The existence guard respects `raw/`'s
documented immutability (SCHEMA.md: "raw/ is immutable — skills never modify it") on
a retried run after a crash.

### 4. [script] Detect flags

```bash
python3 skill/tokovinin-video-flow/scripts/detect_flags.py "$VTT" \
  --info "transcripts/$VIDEO_ID.info.json" --out "transcripts/$VIDEO_ID.flags.json"
python3 skill/tokovinin-video-flow/scripts/log_registry.py set-flags "$VIDEO_ID" \
  "transcripts/$VIDEO_ID.flags.json"
```

### 5. [judgment] Ground before writing

Read `wiki/index.md` in full, then `raw/$VIDEO_ID.txt` in full, then
`transcripts/$VIDEO_ID.flags.json`. If `possible_sponsor_intro.value` is `true`,
treat `approx_end_sec` as roughly where real content starts; the ad span gets marked
in the Source page's own Summary as "ad — not content," never modeled as a concept
of its own. Cross-reference the transcript's actual content against `wiki/index.md`
summaries and any directly relevant pages **before writing anything**, to decide per
segment:

- genuinely new material → new Concept page
- overlaps something already covered → extend the existing page (new paragraph,
  new footnote, `sources:` frontmatter entry, bump `updated`) + add a backlink
- pure remix/rebroadcast of already-covered material → minimal Source page only,
  backlink to the existing concept(s), no new concept page

This judgment call is the bulk of what made 231 pages out of 64 videos without
duplicate concepts — see any existing Source page's "Relation to Other Wiki Pages"
section for the pattern. **No pause for confirmation here** — proceed straight to
writing, unlike the generic `wiki-ingest` skill's human-in-the-loop step 3.

### 6. [judgment] Write pages

Follow `wiki-ingest` steps 4–7 for this one video:

- **Slug** from the video title, lowercase-hyphen (e.g. "Attention Is All You Need"
  → `attention-is-all-you-need`). Check `ls wiki/pages/` for collisions before
  finalizing.
- **Source page** `wiki/pages/<slug>.md`, full frontmatter (`title, category,
  summary, tags, sources, created, updated` — all seven required), header line in
  the full form:
  ```
  **Source:** raw/<id>.txt · https://www.youtube.com/watch?v=<id> (<duration>)
  ```
- **Entity/Concept pages** touched by this video: extend in place (never append a
  chronological "update" section) or create from the template in SCHEMA.md /
  `wiki-skills:wiki-ingest`.
- **Citations**: `[^N]: [[slug](pages/slug.md)] [M:SS] — «verbatim quote»` (or
  `[synthesis] — description`). `[M:SS]` timestamps come from the `.ru.vtt`/`.en.vtt`
  WebVTT cue times — `raw/<id>.txt` itself carries no timing info at all, it's one
  continuous paragraph. No `L<n>` line-range needed — transcripts are exempt per
  SCHEMA.md's Citations section.
- **Backlink audit**: scan every existing `wiki/pages/*.md` for mentions of this
  video's entities/concepts that don't yet link to the new material; add
  cross-references.
- **Self-check**: every non-common-knowledge claim has a footnote; every
  `[[slug](pages/slug.md)]` written this run resolves to an existing page or one
  created in this same run.

### 7. [judgment, deterministic backstop] Contradiction check

Compare pages touched this run against themselves and the neighbor pages already
read in steps 5–6 (not the whole wiki — SCHEMA.md's "touched neighbors only" rule).

- **No blocking contradiction** (the common case) → continue to step 8.
- **Blocking contradiction found** → **do not** try to auto-resolve it and **do
  not** commit any `wiki/` or `raw/` changes for this video. Instead:
  ```bash
  python3 skill/tokovinin-video-flow/scripts/log_registry.py stage "$VIDEO_ID" blocked
  git add log/videos.json channel_videos.txt
  git commit -m "$(cat <<EOF
  chore: skip «<Video Title>» (<video_id>) — contradiction unresolved

  <one-line description of the conflicting claims and the two pages involved>

  Wiki-Op: ingest-blocked

  Co-Authored-By: Claude <noreply@anthropic.com>
  EOF
  )"
  git push
  ```
  Report the block plainly and stop — **do not proceed to steps 8–11 for this
  video.** The next invocation retries it automatically: selection (step 1) is by
  wiki-page presence, and no page was created, so it stays a candidate.

  This is the one place "one invocation = one video landed" doesn't hold, and it's
  intentional: `bin/hooks/pre-commit` hard-blocks any commit staging a page with
  `contradiction-check: failed` in frontmatter regardless of what this skill does,
  and an unattended pass resolving its own conflict defeats the reason that gate
  exists (SCHEMA.md: "a gate, not an annotation"). Landing a `wiki_ingested` stage
  timestamp for a video whose wiki write never actually happened would also be
  simply false — don't do that either.

### 8. [script] Regenerate the index

```bash
python3 bin/generate-index.py
```

`python3`, not `python` — most Linux images ship no `python` alias at all.

### 9. [judgment] Update `wiki/overview.md` if warranted

Only if this video actually shifts the synthesis — a new paragraph under Current
Understanding, new entries in Key Entities/Concepts, a resolved or newly-raised
question in Open Questions. Skip this step outright for a pure-remix video with
nothing new to say.

### 10. [script] Stamp the terminal stage

```bash
python3 skill/tokovinin-video-flow/scripts/log_registry.py stage "$VIDEO_ID" wiki_ingested
```

### 11. [script] Commit and push — no pause

```bash
git add wiki/ "raw/$VIDEO_ID.txt" log/videos.json channel_videos.txt
git commit -m "$(cat <<EOF
docs: summarize «<Video Title>» (<video_id>)

Wiki-Op: ingest

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

The pre-commit hook (`bin/check-contradictions.py` then `bin/lint-mechanical.py
--staged`) runs automatically here — **never** `--no-verify`. If it blocks, that
means step 6 or step 7 missed something: fix the flagged page and re-stage, don't
force through.

### 12. [report]

One paragraph: video id/title, pages written/updated (list), flags detected, any
soft tensions noted (never persisted to any page, per SCHEMA.md), commit hash, push
confirmation. If step 1 found nothing new, or step 7 deferred the video, say that
plainly instead.

## Pitfalls

- **Don't skip the wiki-page ground-truth check in step 1.** `log/videos.json` alone
  is not sufficient — a logged-but-unfinished video (this repo has one on record
  today) must still be picked up.
- **Don't leave `transcripts/<id>_full.txt` as a second copy of the cleaned
  transcript.** `raw/<id>.txt` is the only one; `transcripts/` isn't even tracked by
  git (`.gitignore`).
- **Don't touch `raw/<id>.txt` once it exists.** It's immutable per SCHEMA.md —
  footnote line/timestamp references depend on it never changing after the fact.
- **Don't hand-write `wiki/index.md`.** Always regenerate via
  `bin/generate-index.py` after any page add/edit, in the same commit as the page
  change.
- **Don't bypass the pre-commit hook, ever**, even to "fix" a blocked run — follow
  step 7's fallback instead.
- **Don't process more than one video per invocation.** If the discovery step finds
  several new videos, take only the first (oldest-new) and stop after it — the next
  invocation handles the next one.
- **Don't trust a pre-seeded git identity.** Step 0 sets `user.name`/`user.email`
  unconditionally because a sandbox already has one — the wrong one. An unguarded
  `git commit` there succeeds and attributes the wiki to `Claude`.
- **Don't report "caught up" on an unchecked exit code.** See step 1: an empty
  `$VIDEO_ID` means "caught up" *only* if the listing command actually succeeded.
- **Don't echo or log `$GH_TOKEN`,** and don't run any of this under `set -x`.
- **The executing copy of the scripts is the one inside the clone,** at
  `skill/tokovinin-video-flow/scripts/`, not whatever copy of this skill the agent
  loaded. If a script needs changing, change it in the repo and commit — editing an
  installed copy of the skill changes nothing about what runs.

## Verification

After building or changing this skill, before relying on it:

1. Run `list_new_videos.py` alone and confirm its stdout matches what's actually
   missing from `wiki/pages/` (cross-check with `grep -L` or similar) — not just
   what's missing from `log/videos.json`. **Confirmed working**: as of this
   writing it correctly prints exactly `ZS5fd3f_Lek`.
2. Run the full flow once against a real backlog video, confirm: `raw/<id>.txt`
   created, a new `wiki/pages/<slug>.md` with the full Source header, three new
   `status` keys in `log/videos.json` for that id, index regenerated, commit pushed.
   **Not yet completed end-to-end**: the one real candidate in this repo
   (`ZS5fd3f_Lek`) turned out to have no YouTube captions at all (see step 3's
   no-captions fallback — this is what it was built for and confirmed working:
   `log/videos.json["ZS5fd3f_Lek"].status.no_captions` is stamped, nothing was
   committed). Re-run this check the next time a video with real captions is
   available — either a genuinely new upload, or by pointing `fetch_video.py` at
   an already-ingested id in a scratch copy of the repo to test the write path
   without touching the real wiki.
3. Re-run `list_new_videos.py` immediately after a successful full run — that
   video must no longer appear.
4. `log_registry.py verify <id>` → all three `REQUIRED_STAGES` present.
