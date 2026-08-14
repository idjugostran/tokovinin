---
name: tokovinin-kb-context
description: "Attaches the Tokovinin video knowledge base as context. Trigger: the word 'Токовинин'/'Tokovinin' anywhere in the conversation, any form/case."
platforms: [macos, linux]
---

# Tokovinin Knowledge Base Context

## When to use

Trigger unconditionally whenever the word **"Токовинин"** (or "Tokovinin",
any case/declension - "Токовинина", "Токовинину", etc.) appears anywhere in
the user's message. Not limited to explicit questions like "what did
Tokovinin say about X" - any mention at all is enough, including passing
references ("как говорил Токовинин...", "по мотивам видео Токовинина").

This is a **context-attachment skill**, not a workflow skill: it has no
steps to run and nothing to install. Its only job is to get the right part
of the knowledge base into context before answering.

## Where the knowledge base lives

Two files matter, and they exist in two interchangeable places:

| | Local (this skill inside a clone of the project) | Standalone (skill installed on its own) |
|---|---|---|
| Index | `../../kb/index.md` | `https://raw.githubusercontent.com/idjugostran/tokovinin/main/kb/index.md` |
| One video | `../../kb/videos/<id>.md` | `https://raw.githubusercontent.com/idjugostran/tokovinin/main/kb/videos/<id>.md` |

Prefer the local copy when it exists; otherwise fetch over HTTP (public
repo, no auth). Fetch fresh each session - the base grows as new videos are
processed.

**Never load every file in `kb/videos/`.** The whole base is ~124k tokens;
the index plus the one or two videos a question actually needs is ~13k.
Loading all of it is the failure mode this two-step layout exists to prevent.

## What to do

1. **Read the index in full.** It lists every video: `<id> · <title> | <duration>`
   plus that video's chapter headings. ~10k tokens, this part is not optional
   and must not be grepped or skimmed - the chapter headings are the only
   retrieval signal available.
2. **Pick the videos that actually bear on the question** - normally one or
   two, at most three or four for a broad question ("что он вообще думает
   про найм"). Match on chapter headings, not just titles: the titles are
   YouTube clickbait, the chapters say what was really discussed.
3. **Read those `kb/videos/<id>.md` files in full**, not a summary or a grep
   of them. Each one is a whole video's compressed notes, median ~1.5k tokens.
4. If nothing in the index looks relevant, say so ("в базе нет видео на эту
   тему") rather than fetching random files or answering from general
   knowledge.
5. If the index or a video file can't be read at all (no network, repo
   unreachable), say that plainly and stop. Do **not** fall back to general
   knowledge while implying it came from the knowledge base.

## How to answer

- Treat the fetched files as the ground-truth record of what Misha Tokovinin
  has said. Prefer them over general knowledge or guessing.
- Cite which video a claim comes from when it matters - don't blend several
  videos' positions into one unattributed claim if the user might want to
  check the source.
- **Link every citation to the exact moment in the video, not just the
  video.** Each chapter header in a video file carries a `MM:SS`/`H:MM:SS`
  timestamp (e.g. `### Кого нельзя брать на работу (0:00–8:34)`) and the
  file's header line has the id (`id: a8a-hy31pdI | ... |
  https://www.youtube.com/watch?v=a8a-hy31pdI`). Convert the chapter's start
  timestamp to seconds (`8:34` → `8*60+34=514` - plain arithmetic, no script
  needed) and render the citation as a markdown link with the timestamp as
  the visible text: `[8:34](https://youtu.be/a8a-hy31pdI?t=514)`. Telegram
  (and any other surface that renders markdown links) turns this into a
  clickable timestamp that jumps straight to that moment.
- The channel is largely a reaction format, so many video files keep "the
  clip says X" separate from "Tokovinin says Y". Preserve that distinction -
  don't attribute a quoted opinion to him.

## Notes

- **Nothing to download or process here.** This skill never fetches a video,
  never runs `yt-dlp`, never runs pipeline scripts, never adds flags, never
  writes to the knowledge base. It reads an already-built base and nothing
  else. If the base is missing a video the user asks about, the answer is
  "этого видео пока нет в базе" - not an attempt to process it.
- **Where the base comes from** (background, not something a user of this
  skill has to do): a separate skill in the same repo, `tokovinin-video-flow`,
  builds these files from YouTube captions and is run by the maintainer. It
  needs `yt-dlp`, the Hermes CLI and cron, so it is deliberately *not* part of
  this standalone install. Nobody reading the base needs it - the HTTP source
  is always the current published state. It is not on a schedule, so treat the
  base as "everything processed so far", not "everything on the channel".
- **Portable by design - no scripts, no dependencies, one file.** In Hermes
  it's registered automatically alongside `tokovinin-video-flow` (`setup.sh`
  adds the whole `skill/` parent dir to `skills.external_dirs`). Standalone
  in Claude Code it's just this file dropped into
  `~/.claude/skills/tokovinin-kb-context/SKILL.md` - see the repo README.
