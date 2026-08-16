---
name: tokovinin-wiki-context
description: "Answers Tokovinin/Токовинин questions from the wiki: Миша Токовинин — бизнес, найм, продажи, деньги, мотивация (конспекты видео канала @mtokovinin)"
---

# Tokovinin Wiki Context

Reads the wiki (wiki-init/wiki-ingest format) straight from GitHub over HTTPS —
no clone, no local data, nothing installed but this file.

## Wiki Source

**Base URL:** https://raw.githubusercontent.com/idjugostran/tokovinin/main

That line is the only configuration. The wiki always has the same shape under it:

```
<base>/wiki/index.md      — catalog of every page, one line each (committed, always current)
<base>/wiki/overview.md   — running synthesis across all 64 videos + open questions
<base>/wiki/pages/<slug>.md
```

Pages fall into three categories (see the index's headings): **Sources** (one
per video — summary, key takeaways, footnoted quotes), **Concepts**
(cross-video synthesis of a recurring idea, the richest entry point for a
topic question), and **Entities** (currently just `misha-tokovinin.md`, the
author page listing every video he appears in).

## When to Use

Trigger whenever **Миша Токовинин** or clearly related content is mentioned
anywhere in the user's message, in any form (not exhaustive — match the
intent, not just these exact strings):

- Russian, any case/declension: `Токовинин` / `токовинин` (Токовинина,
  Токовинину, Токовининым...), `Миша Токовинин`
- English: `Tokovinin`, `Misha Tokovinin`, the channel handle `mtokovinin`

A passing mention is enough ("как говорил Токовинин...", "по мотивам видео
Токовинина") — it doesn't have to be a question.

This is a **grounding skill**, not a whole-file-attachment one — the wiki is
231 pages / ~180k tokens, so pulling all of it on every mention would be
wasteful and mostly irrelevant. Fetch the index, then *just* the pages it
says matter.

## Prerequisites

Network access, plus any one fetch tool (see below). No git, no clone, no
install of the wiki data itself.

## How to Read

Use the first of these that's available in the current environment:

1. **Bash + curl** — exact bytes, no summarization layer:
   `curl -fsS <base>/wiki/index.md`
2. **WebFetch / web_fetch** — where there's no shell (claude.ai). Ask for the
   document's content **verbatim**, not a summary; this skill needs the page
   text, not a paraphrase of it.
3. **Private repo** (no public raw URL): `gh api
   repos/idjugostran/tokovinin/contents/wiki/index.md -H "Accept: application/vnd.github.raw"`

**Fetch the URL directly — never route through a web-search tool first.**
`raw.githubusercontent.com` serves plain text, not an HTML page, so search
engines essentially never index it — this is true even for this public repo,
and getting zero search results does **not** mean the repo is private or
unreachable. If a direct-fetch tool (`curl`, `WebFetch`/`web_fetch`) is
available, call it on the URL immediately; don't search for the repo or the
URL first and treat empty results as failure.

Page URLs are never guessed. `wiki/index.md` lists every page as
`[[slug](pages/slug.md)]` — that relative path maps to
`<base>/wiki/pages/slug.md`. A 404 means the index is out of date: say so,
don't substitute a similar-looking page.

## Procedure

1. **Fetch the index in full** (~26k tokens — not optional, and not to be
   grepped or skimmed: the one-line summaries are the only retrieval signal).
   Use it to pick the pages actually relevant to the mention/question:
   - For a topic/opinion question ("что он думает про наём", "как он
     относится к рекламе") — start in the **Concepts** section. Concept pages
     are already cross-video syntheses with footnoted quotes; they're denser
     and more complete than any single video's notes.
   - For "what did he say in video X" — go to the matching **Sources** entry.
   - For "everything he's ever said about himself" / broad canvassing — the
     **Entities** entry `misha-tokovinin.md` lists every video appearance.
   - Match on the index's one-line summaries, not just page titles — titles
     are often the YouTube clickbait title, the summary says what the page
     actually argues.
   - Normally fetch one to three pages; at most four or five for a genuinely
     broad question. Follow one level of `[[slug](pages/slug.md)]`
     cross-references in a fetched page if it points somewhere clearly
     relevant to the question.

2. **Fetch the chosen pages in full** (median ~800 tokens each), not a
   summary or a grep of them. Don't answer from general business knowledge —
   the wiki is ground truth here for what Tokovinin has actually said, and
   his positions are frequently contrarian (against hiring "по нужде",
   against "вечные бизнесы" lists, against generic motivational advice) —
   generic knowledge gets him wrong.

3. **Synthesize an answer grounded in what you fetched, citing in chat-safe
   form:**
   - Cite every claim by naming the page **in prose**, e.g. "по концепции
     «Ниша и тайминг» ..." or "(вики: Собеседование — это свидание)" — plain
     text, no brackets. **Never emit the wiki's internal
     `[[slug](pages/slug.md)]` syntax in the reply** — it isn't a link any
     chat client can render, and it can make the whole message fail to parse
     as Markdown, falling back to showing raw `**`/`[...]` literally.
   - **Link citations to the exact moment, not just the video.** Every
     footnote in a fetched page carries a timestamp:
     `[^3]: [[some-slug](pages/some-slug.md)] [8:34] — «quote»`. To turn that
     into a clickable link, resolve the video id: if `some-slug` is a Source
     page, its `**Source:** raw/<id>.txt` header line has the id directly. If
     the footnote's target is a different Source page than the one you
     fetched, fetch that page too (or its first few lines) to read the id —
     never guess it from the slug. Convert the timestamp to seconds
     (`8:34` → `8*60+34=514`) and link with the timestamp as the visible
     text: `[8:34](https://youtu.be/a8a-hy31pdI?t=514)`.
   - The channel is largely a reaction format: Source pages keep "the clip
     says X" separate from "Tokovinin says Y", and note in their Summary when
     a video is mostly a remix/rebroadcast of an earlier one. Preserve that
     distinction — never attribute a quoted clip's opinion to him, and prefer
     citing the original source over a remix if both cover the same point.
   - Explicitly surface disagreements or unresolved tensions rather than
     picking one silently — check `wiki/overview.md`'s Open Questions section
     for anything relevant before presenting a single position as settled.
   - If the index has nothing covering what was asked, say so plainly ("в
     вики нет страницы на эту тему") instead of quietly falling back to
     general knowledge.
   - If neither the index nor a page can be fetched at all, say that plainly
     and stop — do **not** answer from general knowledge while implying it
     came from the wiki.
   - **Disclose that this skill answered.** End the reply with a short
     plain-text marker on its own line, e.g. `📚 Источник: Tokovinin Wiki
     (tokovinin-wiki-context)` — no brackets or links.

4. **Never write to the wiki from this skill.** This is read-only context
   grounding. All 64 videos on the channel as of 2026-08-15 are ingested and
   the wiki isn't on any refresh schedule — treat it as "everything processed
   as of the last ingest", not "everything currently on the channel". If
   asked to add or reprocess a video, say that's outside what this skill
   does rather than attempting it — never fetch videos, run `yt-dlp`, or edit
   wiki files.

## Pitfalls

- **Don't web-search for the repo or the raw URL before fetching it.** Raw
  GitHub content URLs aren't indexed by search engines regardless of repo
  visibility — an empty search result is expected and is not evidence the
  repo is private or down. Call the fetch tool on the URL directly.
- **Don't fetch the whole `wiki/pages/` tree.** 231 files, ~180k tokens.
  Fetch the index, then only what it says is relevant.
- **Don't regenerate `wiki/index.md`.** It's committed, not a runtime
  artifact — whoever edits the wiki regenerates it (`bin/generate-index.py`)
  and commits it. Read only.
- **raw.githubusercontent.com is CDN-cached (~5 min).** A commit pushed
  seconds ago may not be visible yet. If the user says the wiki just changed
  and you don't see it, that's why — wait rather than declaring it missing.
- **Don't attribute clip/guest opinions to Tokovinin.** Reaction-format pages
  mark whose position is whose; keep that boundary in the answer.
- **Don't put `[[slug](pages/slug.md)]` in the chat reply.** Internal
  cross-reference syntax, meaningless outside the file tree. Cite by page
  name in prose. Real YouTube timestamp links are the one exception.
- **Don't linkify timestamps with a guessed video id.** The id comes from an
  actually-fetched Source page's `**Source:**` line, nowhere else.

## Verification

After answering, every factual claim should be traceable to a named wiki page
(in prose, not a `[[slug](pages/slug.md)]` link), with a timestamp link where
it matters. If it isn't, it was answered from general knowledge — go back and
ground it, or say the wiki doesn't cover it. Check the reply contains no
literal `[[...]]` or `pages/....md` text, and that it ends with the
`📚 Источник:` disclosure line.
