---
name: tokovinin-kb-context
description: "Attaches the full Tokovinin video knowledge base as context. Trigger: the word 'Токовинин'/'Tokovinin' anywhere in the conversation, any form/case."
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
steps, no scripts, nothing to run. Its only job is to make sure the model
has the accumulated knowledge base in context before answering.

## What to do

1. Read `kb/tokovinin_kb.md` (project root - the same `Tokovinin/` project
   this skill lives under, i.e. `../../kb/tokovinin_kb.md` relative to this
   file) **in full**, not a summary or a grep of it.
2. Treat its contents as the ground-truth record of what Misha Tokovinin has
   said/covered across his processed videos. Prefer it over general
   knowledge or guessing when answering anything about him or his content.
3. If the file is missing, empty, or only has the template header with no
   real `##` video blocks yet, say so plainly ("в базе знаний пока нет
   обработанных видео") instead of answering from general knowledge as if it
   came from the kb.
4. Cite which video a claim comes from when it matters (each `##` block has
   an `id:` / URL line) - don't blend multiple videos' positions into one
   unattributed claim if the user might want to check the source.
5. **Link every citation to the exact moment in the video, not just the
   video.** Each chapter header carries a `MM:SS`/`H:MM:SS` timestamp (e.g.
   `### Кого нельзя брать на работу (0:00–8:34)`) and each video block's
   header line has the id (`id: a8a-hy31pdI | ... | https://www.youtube.com/watch?v=a8a-hy31pdI`).
   Convert the chapter's start timestamp to seconds (`8:34` → `8*60+34=514`
   - plain arithmetic, no script needed) and render the citation as a
   markdown link with the timestamp as the visible text:
   `[8:34](https://youtu.be/a8a-hy31pdI?t=514)`. Telegram (and other
   surfaces Hermes renders markdown links for) turns this into a clickable
   blue timestamp that jumps straight to that moment - no separate tool or
   script involved, this is just markdown link syntax in the response text.

## Notes

- **Whole-file attachment, no retrieval/chunking, by design** - the current
  size (~1 video ≈ 1.7-2k tokens) makes this cheap. This does not scale
  indefinitely: revisit (chunked/keyword retrieval instead of the whole
  file) once the kb has enough videos that attaching all of it becomes
  expensive on every mention of the name. See the `tokovinin-video-flow`
  skill's TODO for the same scaling note from the producing side.
- **Read-only.** This skill never runs pipeline scripts, never adds flags,
  never writes to `kb/tokovinin_kb.md`. For adding new videos to the
  knowledge base, see the `tokovinin-video-flow` skill instead.
- Registered with Hermes automatically alongside `tokovinin-video-flow` -
  `setup.sh` adds the whole `skill/` parent directory to
  `skills.external_dirs`, so any skill folder placed under it (this one
  included) is picked up without extra configuration.
