---
name: tokovinin-kb-context
description: "Answers questions from the knowledge base: Миша Токовинин — бизнес, найм, продажи, деньги, мотивация (конспекты видео канала @mtokovinin)"
---

# Tokovinin KB (Миша Токовинин)

Reads the knowledge base (compressed video notes) straight from GitHub over
HTTPS — no clone, no local data, nothing installed but this file.

## KB Source

**Base URL:** https://raw.githubusercontent.com/idjugostran/tokovinin/main

That line is the only configuration. The base always has the same shape under it:

```
<base>/kb/index.md         — catalog of every video: id, title, duration, chapter headings (committed, always current)
<base>/kb/videos/<id>.md   — one video's full compressed notes
```

## When to Use

Trigger whenever **Миша Токовинин** or clearly related content is mentioned
anywhere in the user's message, in any form (not exhaustive — match the
intent, not just these exact strings):

- Russian, any case/declension: `Токовинин` / `токовинин` (Токовинина,
  Токовинину, Токовининым...), `Миша Токовинин`
- English: `Tokovinin`, `Misha Tokovinin`, the channel handle `mtokovinin`

A passing mention is enough ("как говорил Токовинин...", "по мотивам видео
Токовинина") — it doesn't have to be a question.

This is a **grounding skill**, not a whole-file-attachment one — the base is
64 videos / ~124k tokens, so pulling all of it on every mention would be
wasteful and mostly irrelevant. Fetch the index, then *just* the videos it
says matter.

## Prerequisites

Network access, plus any one fetch tool (see below). No git, no clone, no
install of the kb data itself.

## How to Read

Use the first of these that's available in the current environment:

1. **Bash + curl** — exact bytes, no summarization layer:
   `curl -fsS <base>/kb/index.md`
2. **WebFetch / web_fetch** — where there's no shell (claude.ai). Ask for the
   document's content **verbatim**, not a summary; this skill needs the page
   text, not a paraphrase of it.
3. **Private repo** (no public raw URL): `gh api
   repos/idjugostran/tokovinin/contents/kb/index.md -H "Accept: application/vnd.github.raw"`

Video URLs are never guessed. `kb/index.md` lists every video's `<id>` — that
id maps to `<base>/kb/videos/<id>.md`. A 404 means the index is out of date:
say so, don't substitute a similar-looking video.

## Procedure

1. **Fetch the index in full** (~10k tokens — not optional, and not to be
   grepped or skimmed: the chapter headings are the only retrieval signal).
   Use it to pick the videos actually relevant to the mention/question —
   normally one or two, at most three or four for a broad question ("что он
   вообще думает про найм"). Match on chapter headings, not just titles: the
   titles are YouTube clickbait, the chapters say what was really discussed.

2. **Fetch the chosen `kb/videos/<id>.md` files in full** (median ~1.5k
   tokens each), not a summary or a grep of them. Don't answer from general
   business knowledge — the base is ground truth here for what Tokovinin has
   actually said, and his positions are frequently contrarian (against hiring
   "по нужде", against "вечные бизнесы" lists, against generic motivational
   advice) — generic knowledge gets him wrong.

3. **Synthesize an answer grounded in what you fetched, citing in chat-safe
   form:**
   - Cite which video a claim comes from when it matters — don't blend
     several videos' positions into one unattributed claim.
   - **Link citations to the exact moment, not just the video.** Each chapter
     header carries a timestamp (`### Кого нельзя брать на работу (0:00–8:34)`)
     and the file's header line has the id (`id: a8a-hy31pdI | ... |
     https://www.youtube.com/watch?v=a8a-hy31pdI`). Convert the chapter's
     start to seconds (`8:34` → `8*60+34=514` — plain arithmetic) and link
     with the timestamp as the visible text:
     `[8:34](https://youtu.be/a8a-hy31pdI?t=514)`. Only from an id read in
     the fetched file — never guess it.
   - The channel is largely a reaction format: many notes keep "the clip
     says X" separate from "Tokovinin says Y". Preserve that distinction —
     never attribute a quoted clip's opinion to him.
   - If the index has no video covering what was asked, say so plainly
     ("в базе нет видео на эту тему") instead of quietly falling back to
     general knowledge.
   - If neither the index nor a video file can be fetched at all, say that
     plainly and stop — do **not** answer from general knowledge while
     implying it came from the base.
   - **Disclose that this skill answered.** End the reply with a short
     plain-text marker on its own line, e.g. `📚 Источник: Tokovinin KB
     (tokovinin-kb-context)` — no brackets or links.

4. **Never write to the knowledge base from this skill.** This is read-only
   context grounding. The base is built by a separate pipeline
   (`tokovinin-video-flow`, same repo) run by the maintainer; it is not on a
   schedule, so treat the base as "everything processed so far", not
   "everything on the channel". If asked to add/process a video, say that's
   outside what this skill does rather than attempting it — never fetch
   videos, run `yt-dlp`, or edit kb files.

## Pitfalls

- **Don't fetch the whole `kb/videos/` tree.** ~124k tokens across 64 files.
  Fetch the index, then only what the index says is relevant (~13k for a
  typical answer).
- **Don't regenerate `kb/index.md`.** It's committed, not a runtime
  artifact — the pipeline regenerates it (`scripts/kb_index.py`) when videos
  are added. Read only.
- **raw.githubusercontent.com is CDN-cached (~5 min).** A commit pushed
  seconds ago may not be visible yet. If the user says the base just changed
  and you don't see it, that's why — wait rather than declaring it missing.
- **Don't attribute clip/guest opinions to Tokovinin.** Reaction-format
  notes mark whose position is whose; keep that boundary in the answer.
- **Don't linkify timestamps with a guessed video id.** The id comes from
  the fetched file's header line, nowhere else.

## Verification

After answering, every factual claim should be traceable to a named video
(with a timestamp link where it matters). If it isn't, it was answered from
general knowledge — go back and ground it, or say the base doesn't cover it.
Check the reply ends with the `📚 Источник:` disclosure line.
