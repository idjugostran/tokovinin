---
name: tokovinin-video-flow
description: "Fetches the next new @mtokovinin video and adds it to the Tokovinin wiki (wiki-ingest), commits, and pushes. Manual invocation only."
---

# Tokovinin Video Flow

Takes the `idjugostran/tokovinin` wiki from "N videos ingested" to "N+1 videos
ingested" for exactly **one** new video per invocation: fetch that video's
transcript, run the same `wiki-ingest` process used to build the other 231 pages
by hand, commit, and push.

**Trigger: explicit invocation only** — "process the next Tokovinin video", "run
video-flow", "ingest the newest video on the channel", or a Routine whose saved
prompt says so. Unlike the read-only `tokovinin-wiki-context` skill, this one
writes and pushes to a real repository — it must never fire passively just
because Tokovinin came up in conversation.

**Full autonomy on push, one boundary.** This skill never pauses for confirmation
before writing or before pushing — that's been explicitly delegated. It also never
uses `git commit --no-verify` and never hand-edits `wiki/index.md` — those two
invariants hold regardless of autonomy. If the contradiction gate blocks (step 7),
the skill does not try to resolve it and does not bypass the hook to force a push
through — see step 7 for the exact fallback.

## Supported environments

Two, and only two. Both were verified by running the flow, not reasoned about.

**A. Cloud Routine** (`claude.ai/code/routines`, or Desktop → Routines → New
routine → Cloud). This is the environment the flow is built for: the repository
is a first-class part of the routine, cloned at the start of every run, and
pushes carry your own GitHub identity. Configure the routine as:

- **Repositories** — `idjugostran/tokovinin`.
- **Connectors** — **TubeAlfred** (`tubealfred.com`), and nothing else. This is
  the only route to YouTube that works here, and the reason the flow no longer
  ships a `yt-dlp` fetcher. Verified in a real Routine run.
- **Environment → Network access** — leave at the default `Trusted`. Nothing
  needs adding: connector traffic does not pass through the session's HTTP
  proxy, so the domain allowlist never applies to it.
- **Environment → Setup script** — empty. Every script here is pure stdlib.
- **Trigger** — **weekly**, or **Run now**. Connector calls are metered from a
  credit wallet (new accounts get 100 free credits), and a run that finds nothing
  still costs 1 credit for the page-1 listing; a run that ingests costs 3. The
  channel publishes one or two videos a month, so weekly polling never misses
  anything and 100 credits cover roughly two years. Daily would burn the same
  free allowance in about three months for no earlier result, and the one-hour
  minimum would exhaust it in four days.

**Why the connector rather than `yt-dlp`.** A Routine forces all egress through
a proxy. With YouTube off the allowlist, yt-dlp dies at step 1 with `Unable to
connect to proxy` / `Tunnel connection failed: 403 Forbidden` — measured; note
that is the proxy refusing to open the tunnel, not YouTube's bot check, which
would look like "Sign in to confirm you're not a bot" *after* connecting.
Allow-listing YouTube would fix the tunnel but leaves the datacenter IP exposed
to the actual bot check. The connector sidesteps both, and it hands back cues
already parsed, which is why `fetch_video.py` and `clean_transcript.py` are gone
rather than ported.

**B. Local** — Claude Code on the owner's machine, interactively or as a Desktop
scheduled task (Routines → New routine → **Local**), with the working folder set
to the repository. Push is handled by the `osxkeychain` credential helper that is
already configured. YouTube is still reached through the TubeAlfred connector, not
over the local network — one code path, so a local run actually exercises what a
Routine run does.

**Not supported: a generic cloud sandbox** (Claude Cowork and similar). Measured
there: `youtube.com` is not on the egress allowlist, so step 1 cannot run, and
`git push` is refused by the session's git proxy with *"not in this session's
authorized repository set"*. A personal access token does **not** help — the
proxy refuses before any credential is consulted. Do not add PAT plumbing to work
around this; there is nothing to work around. Step 0's `push --dry-run` stops such
a run in about two seconds, which is the correct outcome.

**Never wire `$GH_TOKEN` into a credential helper.** Some sandboxes ship it
pre-seeded with the literal placeholder `proxy-injected` (alongside
`GITHUB_TOKEN`, `AWS_SECRET_ACCESS_KEY`, and friends), so a `[ -z "$GH_TOKEN" ]`
guard never fires and the "credential" supplied is junk. Neither supported
environment needs a token at all. Also: never run any of these steps under
`set -x`.

## Falling back to the `yt-dlp` flow

The previous version of this skill fetched everything with `yt-dlp` and no
connector. It is preserved whole at the git tag **`flow-ytdlp`** — not as a second
copy of the directory, deliberately: a parallel copy would drift out of step with
`bin/`, `SCHEMA.md` and the wiki conventions within a few commits, and be broken by
the time anyone reached for it. A tag cannot drift.

Restore it with:

```bash
git checkout flow-ytdlp -- skill/tokovinin-video-flow
```

Then, because that version reaches YouTube directly, the Routine must be
reconfigured to match: **Network access** → `Custom` with `*.youtube.com`,
`youtube.com`, `youtubei.googleapis.com` and the package-manager defaults;
**Setup script** → `python3 -m pip install --user --upgrade yt-dlp`. The connector
can stay connected — that version simply won't call it.

Two things to know before relying on it. It was **never observed working in a
Routine**: the only run reached step 1 and died on the proxy, which is what
motivated this rewrite; allow-listing YouTube fixes the tunnel but leaves the
datacenter IP facing YouTube's actual bot check, which is untested. And the tag
predates step 0's `git checkout main` fix, so a restored copy will still stumble
on a generated `claude/*` branch — re-apply that one hunk from the commit
following the tag.

## Procedure

Every step below is tagged **[script]** (a deterministic command, no judgment) or
**[judgment]** (the agent reads content and decides — not scriptable).

### 0. [script] Preflight — every invocation

```bash
if [ -f SCHEMA.md ] && [ -d wiki ]; then
  :                       # cwd is already the repo root (Routine and local)
elif [ -d tokovinin/.git ]; then
  cd tokovinin
else
  git clone https://github.com/idjugostran/tokovinin.git tokovinin && cd tokovinin
fi
git rev-parse --abbrev-ref HEAD    # must print: main
git checkout main || { echo "cannot reach main — stop"; exit 1; }
git pull --ff-only origin main
```

The first branch is the normal one in both supported environments. The clone
fallback stays for the odd case of an empty working directory — and clones into
`tokovinin/`, never into the cwd, because `git clone <url> .` fails outright
(exit 128) if the cwd holds anything at all.

**Get onto `main` explicitly, and name the remote and branch in the pull.** This
flow commits straight to `main` — that is what every commit in this repo's history
does and what step 11 assumes. Neither half of that can be left implicit:

- A bare `git pull --ff-only` needs the current branch to have an upstream. Some
  agent environments start you on a generated working branch with no tracking
  information, and the pull then dies with `There is no tracking information for
  the current branch` — observed. Naming `origin main` removes the dependency.
- Worse, and silent: on such a branch step 11's `git push` would push *that*
  branch rather than `main`, so the wiki update would land somewhere nobody reads
  while every command still reported success. The `checkout main` is what prevents
  that, not the pull.

If the checkout or the pull aborts with `Your local changes to the following files
would be overwritten` — a previous run left uncommitted state behind. **Stop and
surface it.** This is the one place autonomy doesn't extend to silently discarding
unknown local state. A failure that merely says the branch has no upstream is a
different thing and is what the explicit `origin main` above already fixes.

```bash
git config user.name  "idjugostran"
git config user.email "idjugostran@gmail.com"
git config core.hooksPath bin/hooks
```

All three repo-local, unconditional, idempotent. Set the identity **every time,
not `|| `-guarded on emptiness** — a cloud session ships a *pre-seeded* default of
`Claude <noreply@anthropic.com>` (verified), so a guard on "is it unset?" never
fires and the whole wiki's history silently lands under the wrong author.
`core.hooksPath` is likewise repo-local and **not** carried by a fresh clone
(SCHEMA.md's own documented gotcha), so it must run every time, not just "if this
looks like a fresh clone."

If GitHub rejects the push later with `GH007` (the account blocks pushes that
expose a private email), switch `user.email` to the account's
`<id>+idjugostran@users.noreply.github.com` form and re-commit.

```bash
git push --dry-run origin HEAD || { echo "no push access — stop"; exit 1; }
```

No credential wiring: a Routine already carries your GitHub identity, and locally
the keychain helper is in charge. The `--dry-run` authenticates for real against
the remote, turning "can't push here" from a step-11 failure *after* a full ingest
into a two-second stop before any work.

Finally, confirm the **TubeAlfred connector's tools are actually available** in
this session before doing anything else. If they are not, stop and say so — steps
1 and 2 have no other way to reach YouTube, and there is nothing to install that
would create one.

### 1. [script] Discover the one video to process

First, **list the channel through the connector**: call its channel-videos tool for
`@mtokovinin`. **Fetch the first page only, and stop there** unless the condition
below applies.

The listing is newest-first and a page holds ~30 videos. A newly published video
is therefore always on page 1 — this channel puts out one or two videos a month,
so 30 uploads between two runs is not a scenario. Page 1 answers the question this
flow actually asks ("did something new appear?") for **one credit**, where the
full three-page sweep costs three.

Paginate further **only** when the wiki has a genuine backlog: if *every* id on
page 1 is unprocessed, the unprocessed run may extend past the page boundary, so
keep calling with the continuation token until a page contains an id that already
has a wiki page. That is a different question — "is the backlog complete?" — and
it is also worth a deliberate full sweep now and then, by hand, to catch drift.
Today the answer is 0 candidates out of 65, so the common path is one call.

**A `402` from the connector means the credit wallet is empty, not that there is
nothing to do.** Treat it exactly like any other listing failure: stop, say so
plainly, do not commit, and never report "caught up". Same for a `429`, which
means the 60-calls-per-minute burst limit was hit — impossible at this flow's five
calls per run, so if you see one, something is looping. Failed calls are not
charged, so a stopped run costs nothing.

Write the result to `channel_videos.txt`, newest first, one tab-separated
`id<TAB>title<TAB>duration<TAB>views` line per video. Tab, not `|`, on purpose:
the titles routinely contain a literal `|`.

The titles the channel listing returns are **YouTube's English auto-translations**
("Deliberately LOSSED BILLIONS"), not what the video is called. That is fine here —
this file exists to answer "which ids exist", and step 2 fetches the real Russian
title. Do not use a title from this file for a slug or a page heading.

```bash
python3 skill/tokovinin-video-flow/scripts/list_new_videos.py \
  --channel-file channel_videos.txt --log log/videos.json --wiki-pages wiki/pages \
  > new_videos.txt || { echo "listing FAILED — not 'caught up'"; exit 1; }
VIDEO_ID=$(head -1 new_videos.txt)
```

Redirect to a file and check the exit code **before** taking the first line. Do
**not** write `VIDEO_ID=$(... | head -1)`: a pipeline's exit status is `head`'s, so
any failure of the listing would leave `$VIDEO_ID` empty and get reported as the
success case below — a silent false "caught up" that looks exactly like a clean
run. `set -o pipefail` would fix *that* but introduces its own trap: `head -1`
closes the pipe early, and once the producer's output exceeds the pipe buffer the
resulting SIGPIPE surfaces as exit 120 on an otherwise successful run (measured:
65 channel lines pass, 200k lines fail). The redirect sidesteps the question
instead of tuning around a buffer size.

If the command succeeded and `$VIDEO_ID` is empty: **report "wiki is caught up
with the channel" and stop.** No commit, no push. (`new_videos.txt` is scratch —
untracked and gitignored; never `git add` it.)

`list_new_videos.py` cross-checks the channel against `wiki/pages/*.md`'s
`**Source:** raw/<id>.txt` headers (the real ground truth), not just
`log/videos.json` keys — a video can be logged as "fetched" from a previous run
that never finished and still needs processing. It also **excludes** videos
stamped `no_captions`; see step 3 for why that exclusion is what keeps the queue
moving. Read the script's stderr for `NOTE:` lines before proceeding.

### 2. [script] Fetch through the connector

Two connector calls for `$VIDEO_ID`:

1. **Video details** — ask for `title,description`. This returns the **Russian
   original** («Осознанно ПРОСРАЛ МИЛЛИАРДЫ | Миша Токовинин») plus the full
   Russian description, which usually carries the author's own chapter list. This
   is the *only* source of the real title; the step-1 listing gives translations.
   Duration comes from the `duration`/`length_seconds` column of
   `channel_videos.txt`.
2. **Transcript** — with `language: ru`, `kind: any`.

Write both into one capture file, `transcripts/$VIDEO_ID.json`, exactly this shape
(everything downstream reads it, nothing else):

```json
{"video_id": "...", "title": "<Russian title>", "description": "<Russian description>",
 "duration_sec": 604, "language_code": "ru", "is_auto_generated": true,
 "available_tracks": [...],
 "transcript": [{"text": "...", "start_ms": "2360", "start_time_text": "0:02"}, ...]}
```

`transcripts/` is gitignored — this capture is a working artifact, not a record.
Then:

```bash
python3 skill/tokovinin-video-flow/scripts/log_registry.py touch "$VIDEO_ID" \
  --title "<Russian title>" --url "https://www.youtube.com/watch?v=$VIDEO_ID" \
  --duration-sec <duration> --stage fetched
```

### 3. [script] Write `raw/` — or record a terminal stage and stop

Judge the capture from step 2 by two of its fields, in this order:

**`language_code` is not `ru`** → the connector had no Russian track and gave a
translation. The channel speaks Russian, so a non-Russian track is a machine
translation, not a transcript of the video. Putting it in `raw/` would file
translated text — mid-sentence language switches and all — under a `**Source:**`
header claiming to be the transcript, and nothing downstream would catch it. Stamp
the terminal stage, commit it with `Wiki-Op: ingest-translated-only`, push, report
"only a translated (`<code>`) track for `<id>` — `<title>`, needs a human", and stop
for this video:

```bash
python3 skill/tokovinin-video-flow/scripts/log_registry.py stage "$VIDEO_ID" translated_only
```

**`available_tracks` is empty and `transcript` is empty** → the video has no
captions on YouTube at all. This is real, not hypothetical: `ZS5fd3f_Lek` (204k
views, the channel's most-viewed video) returns exactly that — `language: "Unknown"`,
`transcript: []`, `available_tracks: []`. Nothing to fetch, no other language helps.
**Stamp it and commit the stamp**:

```bash
python3 skill/tokovinin-video-flow/scripts/log_registry.py stage "$VIDEO_ID" no_captions
git add log/videos.json channel_videos.txt
git commit -m "$(cat <<EOF
chore: skip «<Video Title>» (<video_id>) — no captions on YouTube

Wiki-Op: ingest-no-captions

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

Then report plainly ("no captions available for `<id>` — `<title>`, skipping") and
**stop for this video** — no `wiki/` or `raw/` changes.

**The commit is not bookkeeping, it is what keeps the pipeline alive.** Step 1
excludes `no_captions` videos from the queue, and it reads that stamp from the
committed `log/videos.json`. A cloud run's filesystem is discarded when the
session ends, so an uncommitted stamp is lost — and then the same caption-less
video sits at the head of the oldest-first queue on every future run, each
invocation burns on it and stops at this step, and the videos behind it are never
reached. Leaving the stamp uncommitted converts "skip one video" into "the
pipeline never advances again".

This is not a permanent verdict: captions occasionally appear later, and a human
can supply a transcript by hand. To re-surface such a video, run
`list_new_videos.py --include-no-captions` or delete the `no_captions` key from
its log record.

Otherwise:

Write the capture's `transcript_only_text` **verbatim** to `raw/$VIDEO_ID.txt`, and
only if that file does not already exist:

```bash
[ -f "raw/$VIDEO_ID.txt" ] && echo "raw/ already has it — do not touch"
```

There is no cleaning step any more. The connector returns the cues already
stripped of WebVTT markup, and `transcript_only_text` is their concatenation —
verified byte-for-byte against `raw/ybhcNd7aLBg.txt`, which the retired
`clean_transcript.py` had produced from the `.ru-orig.vtt` of the same video
(same 246 cues, same first and last characters). Do not re-wrap, re-punctuate or
"tidy" it: `raw/` is immutable per SCHEMA.md ("raw/ is immutable — skills never
modify it"), and every footnote timestamp is anchored to this exact text. The
existence guard is what makes a retried run after a crash safe.

### 4. [script] Detect flags

```bash
python3 skill/tokovinin-video-flow/scripts/detect_flags.py \
  "transcripts/$VIDEO_ID.json" --out "transcripts/$VIDEO_ID.flags.json"
python3 skill/tokovinin-video-flow/scripts/log_registry.py set-flags "$VIDEO_ID" \
  "transcripts/$VIDEO_ID.flags.json"
```

One argument now: the step-2 capture carries the cues, the title and the
description, so the separate `--info` file is gone with `yt-dlp`.

### 5. [judgment] Ground before writing

Read `wiki/index.md` in full, then `raw/$VIDEO_ID.txt` in full, then
`transcripts/$VIDEO_ID.flags.json`. If `possible_sponsor_intro.value` is `true`,
treat `approx_end_sec` as roughly where real content starts; the ad span gets
marked in the Source page's own Summary as "ad — not content," never modeled as a
concept of its own. Cross-reference the transcript's actual content against
`wiki/index.md` summaries and any directly relevant pages **before writing
anything**, to decide per segment:

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

- **Slug** — **transliterate the Russian title to Latin**, then lowercase-hyphen.
  Every one of the 231 existing pages does this; a Cyrillic slug would break the
  convention and the `[[slug](pages/slug.md)]` link form. Real examples from the
  repo: "Авторитаризм или Демократия? Советы астролога" →
  `avtoritarizm-ili-demokratiya`; "Астрология — ложь, но веру в неё можно
  использовать" → `astrologiya-lozh-no-veru-v-nee-mozhno-ispolzovat`. Drop
  punctuation, keep it short enough to read. Check `ls wiki/pages/` for collisions
  before finalizing.
- **Source page** `wiki/pages/<slug>.md`, full frontmatter (`title, category,
  summary, tags, sources, created, updated` — all seven required, the pre-commit
  lint blocks on any missing one), header line in the full form:
  ```
  **Source:** raw/<id>.txt · https://www.youtube.com/watch?v=<id> (<duration>)
  ```
  (14 legacy pages use a short form without URL and duration; new pages use the
  full form.)
- **Entity/Concept pages** touched by this video: extend in place (never append a
  chronological "update" section) or create from the template in SCHEMA.md /
  `wiki-skills:wiki-ingest`.
- **Citations**: `[^N]: [[slug](pages/slug.md)] [M:SS] — «verbatim quote»` (or
  `[synthesis] — description`). `[M:SS]` timestamps are the capture's
  `start_time_text`, which already arrives in exactly that form — find the cue
  containing the quote and copy its value; no arithmetic on `start_ms`, no parsing
  of anything. `raw/<id>.txt` itself carries no timing info at all, it's one
  continuous paragraph. No `L<n>` line-range needed — transcripts are exempt per
  SCHEMA.md's Citations section.
- **Backlink audit**: scan every existing `wiki/pages/*.md` for mentions of this
  video's entities/concepts that don't yet link to the new material; add
  cross-references.
- **Self-check**: every non-common-knowledge claim has a footnote; every
  `[[slug](pages/slug.md)]` written this run resolves to an existing page or one
  created in this same run. (The pre-commit lint enforces this too, but finding it
  here is cheaper than a blocked commit at step 11.)

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
  wiki-page presence, and no page was created, so it stays a candidate. Unlike
  `no_captions`, `blocked` is deliberately *not* a terminal stage — the whole point
  is that a human resolves the conflict and the next run picks the video back up.

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

Push straight to the default branch, in both environments — the model is "one
invocation = one video landed in the wiki", and a review queue would defeat it.
In a Routine this works as long as the branch isn't protected on GitHub, has no
open pull request from someone else, and carries no commits authored by anyone
other than you; all three hold for this repo. If a push to the default branch is
ever rejected, Claude Code accepts `claude/`-prefixed branches unconditionally —
push there and open a PR rather than forcing anything.

The pre-commit hook (`bin/check-contradictions.py` then `bin/lint-mechanical.py
--staged`) runs automatically here — **never** `--no-verify`. If it blocks, that
means step 6 or step 7 missed something: fix the flagged page and re-stage, don't
force through.

### 12. [report]

One paragraph: video id/title, pages written/updated (list), flags detected, any
soft tensions noted (never persisted to any page, per SCHEMA.md), commit hash,
push confirmation. If step 1 found nothing new, or step 3 hit no captions, or step
7 deferred the video, say that plainly instead.

In a Routine this report is the only thing a human reads. A green run status means
only that the session exited without an infrastructure error — it says nothing
about whether a video was ingested. Make the first sentence state the outcome
unambiguously: ingested, caught up, skipped (no captions), or blocked.

## Pitfalls

- **Don't skip the wiki-page ground-truth check in step 1.** `log/videos.json`
  alone is not sufficient — a logged-but-unfinished video must still be picked up.
- **Don't leave a `no_captions` stamp uncommitted.** It is the queue's only exit
  from a caption-less video; uncommitted, the pipeline deadlocks on it forever.
- **Don't pass `--include-no-captions` in the normal flow.** It exists for manual
  triage and re-introduces exactly that deadlock.
- **Don't stop at the first page of the channel listing.** It returns ~30 of ~65
  videos plus a continuation token; paginate to the end. A partial listing hides
  the oldest unprocessed videos, which are exactly the ones the queue wants next.
- **Don't take a title from `channel_videos.txt`.** Those are YouTube's English
  auto-translations. The real Russian title comes from step 2's video-details call,
  and the slug is transliterated from *that*.
- **Don't reintroduce a `yt-dlp` path "as a fallback".** In a Routine it cannot
  reach YouTube at all, so a fallback would only add a way to fail slower.
- **Don't keep a second copy of the transcript.** `raw/<id>.txt` is the only one;
  `transcripts/` isn't even tracked by git (`.gitignore`).
- **Don't touch `raw/<id>.txt` once it exists.** It's immutable per SCHEMA.md —
  footnote line/timestamp references depend on it never changing after the fact.
- **Don't hand-write `wiki/index.md`.** Always regenerate via
  `bin/generate-index.py` after any page add/edit, in the same commit as the page
  change.
- **Don't bypass the pre-commit hook, ever**, even to "fix" a blocked run — follow
  step 7's fallback instead. And don't reintroduce `uv run` into the hook: both
  gate scripts are pure stdlib, there is no `pyproject.toml`/`uv.lock`, and
  `uv run` would resolve an environment (possibly downloading an interpreter) on
  every commit — i.e. it needs network, which a restricted environment may not
  give it, turning the gate into a dead end.
- **Don't process more than one video per invocation.** If the discovery step finds
  several new videos, take only the first (oldest-new) and stop after it — the next
  invocation handles the next one.
- **Don't trust a pre-seeded git identity.** Step 0 sets `user.name`/`user.email`
  unconditionally because a cloud session already has one — the wrong one. An
  unguarded `git commit` there succeeds and attributes the wiki to `Claude`.
- **Don't trust `$GH_TOKEN` either**, and never wire it into a credential helper:
  some sandboxes pre-seed it with the placeholder `proxy-injected`, so an
  `[ -z ]` guard never fires. Neither supported environment needs a token.
- **Don't report "caught up" on an unchecked exit code.** See step 1: an empty
  `$VIDEO_ID` means "caught up" *only* if the listing command actually succeeded.
- **Don't echo or log `$GH_TOKEN`,** and don't run any of this under `set -x`.
- **The executing copy of the scripts is the one inside the checkout,** at
  `skill/tokovinin-video-flow/scripts/`, not whatever copy of this skill the agent
  loaded. If a script needs changing, change it in the repo and commit — editing an
  installed copy of the skill changes nothing about what runs.

## Verification

After building or changing this skill, before relying on it:

0. **Connector reachability, before anything else.** Fetch the transcript for
   `ybhcNd7aLBg` and check `language_code: ru`, `is_auto_generated: true`, and 246
   cues. **Confirmed working in a real Routine run** — that is what established the
   connector is usable there at all, and it is the check to repeat first whenever
   a run fails, since every later step depends on it.
1. Run `list_new_videos.py` alone against the committed `channel_videos.txt` and
   confirm its stdout matches what's actually missing from `wiki/pages/`, minus
   anything carrying a terminal stage (cross-check with `grep -L` or similar) —
   not just what's missing from `log/videos.json`. Then run it again with
   `--include-no-captions` and confirm the excluded ids come back. **Confirmed
   working**: reads 65 videos, excludes `ZS5fd3f_Lek (no_captions)`, prints 0
   candidates, and re-surfaces it under the flag. Both guards were exercised too —
   a missing file and an empty file each stop the run instead of reporting "caught
   up".
2. Run the full flow once against a real backlog video, confirm: `raw/<id>.txt`
   created, a new `wiki/pages/<slug>.md` with the full Source header, three new
   `status` keys in `log/videos.json` for that id, index regenerated, commit
   pushed. **Not yet completed end-to-end against a real video with captions** —
   the one real candidate in this repo (`ZS5fd3f_Lek`) has no captions at all, and
   the connector confirms it independently of the retired yt-dlp path (`transcript:
   []`, `available_tracks: []`), which is what step 3's terminal branch was built
   for. The pieces either side of it are verified: `detect_flags.py` on a
   connector-shaped capture reproduces the flags already stored in
   `log/videos.json` for `ybhcNd7aLBg`, and the write path (pages → index → hooks →
   commit → push) was exercised on synthetic input, including the
   contradiction-blocked branch. Re-run this the next time a captioned video is
   available.
3. Re-run `list_new_videos.py` immediately after a successful full run — that
   video must no longer appear. **Confirmed working.**
4. `log_registry.py verify <id>` → all three `REQUIRED_STAGES` present.
   **Confirmed working.**
5. In a Routine specifically: open the run's session and read the transcript. A
   green status only means the session exited cleanly; blocked network requests and
   task-level failures surface in the transcript, not in the status indicator.
