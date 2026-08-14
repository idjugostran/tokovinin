#!/usr/bin/env python3
"""Rebuild kb/index.md from the per-video files in kb/videos/.

The knowledge base is split one file per video (kb/videos/<id>.md) rather
than one monolith, because a reader skill has to pull it over HTTP: the
whole base is ~124k tokens, while the index plus the one or two files a
question actually needs is ~5k. The index is what makes that selection
possible, so it carries enough signal to pick the right video - title,
duration, one-line topic, and the chapter headings - and nothing else.

Generated, never hand-edited: run this after adding or editing any file in
kb/videos/.

Usage:
    python3 kb_index.py                 # rebuild kb/index.md
    python3 kb_index.py --kb-dir kb     # ... under a different kb root
    python3 kb_index.py --check         # exit 1 if index.md is out of date
    python3 kb_index.py --self-check    # parser sanity check, touches nothing

Every file in kb/videos/ must start with a "## <title>" line followed by an
"id: <video_id> | <duration> | <url>" line - that's the shape Step 4 of the
pipeline writes. A file that doesn't parse is a hard error, not a skip: a
silently omitted video is a video the reader skill can never find.
"""

import argparse
import re
import sys
from pathlib import Path

HEADER_RE = re.compile(r"\A## (?P<title>.+)\nid:\s*(?P<id>\S+)\s*\|\s*(?P<duration>[^|\n]+?)\s*\|", re.M)
TOPIC_RE = re.compile(r"^Тема:\s*(.+)$", re.M)
CHAPTER_RE = re.compile(r"^### (.+?)\s*(?:\([\d:–\-—\s]+\))?\s*$", re.M)


def parse(text):
    """-> dict with title/id/duration/topic/chapters. Raises ValueError if malformed."""
    m = HEADER_RE.match(text)
    if not m:
        raise ValueError("does not start with '## <title>' + 'id: <id> | <duration> | <url>'")
    topic = TOPIC_RE.search(text)
    return {
        "id": m["id"],
        "title": m["title"].strip(),
        "duration": m["duration"].strip(),
        "topic": topic.group(1).strip() if topic else "",
        "chapters": [c.strip() for c in CHAPTER_RE.findall(text)],
    }


def render(videos):
    out = [
        f"# Индекс базы — {len(videos)} видео",
        "",
        "<!-- Сгенерирован scripts/kb_index.py. Не править руками. -->",
        "",
        "Полный конспект каждого видео лежит в `kb/videos/<id>.md`, по HTTP:",
        "`https://raw.githubusercontent.com/idjugostran/tokovinin/main/kb/videos/<id>.md`",
        "",
    ]
    # Title + chapter headings only. The "Тема:" line is deliberately left out:
    # it's boilerplate on 58 of 64 videos ("монолог/ответы автора по теме..."),
    # so it costs tokens in the index without helping pick a video. It stays in
    # the per-video file, which the reader fetches anyway.
    for v in videos:
        out.append(f"### {v['id']} · {v['title']} | {v['duration']}")
        if v["chapters"]:
            out.append("Главы: " + "; ".join(v["chapters"]))
        out.append("")
    return "\n".join(out)


def build(kb_dir):
    videos_dir = kb_dir / "videos"
    paths = sorted(videos_dir.glob("*.md"))
    if not paths:
        sys.exit(f"No video files found in {videos_dir}")
    videos, errors = [], []
    for p in paths:
        try:
            v = parse(p.read_text(encoding="utf-8"))
        except ValueError as e:
            errors.append(f"  {p.name}: {e}")
            continue
        if v["id"] != p.stem:
            errors.append(f"  {p.name}: id line says '{v['id']}', filename says '{p.stem}'")
            continue
        videos.append(v)
    if errors:
        sys.exit("Malformed video files:\n" + "\n".join(errors))
    return videos, render(videos)


def self_check():
    v = parse(
        "## Как НАЙТИ ЖЕНУ? | Миша Токовинин\n"
        "id: -o1JXDb8jtI | 13:44 | https://www.youtube.com/watch?v=-o1JXDb8jtI\n"
        "Тема: монолог про отношения\n"
        "Реклама: нет\n"
        "\n### Где знакомиться (0:00–4:12)\n- тезис\n"
        "\n### Чего не делать (4:12–13:44)\n- тезис\n"
    )
    assert v["id"] == "-o1JXDb8jtI", v["id"]
    assert v["duration"] == "13:44", v["duration"]
    assert v["topic"] == "монолог про отношения", v["topic"]
    assert v["chapters"] == ["Где знакомиться", "Чего не делать"], v["chapters"]
    try:
        parse("no header here\n")
    except ValueError:
        pass
    else:
        raise AssertionError("malformed input should raise")
    print("self-check OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kb-dir", type=Path, default=Path("kb"))
    ap.add_argument("--check", action="store_true", help="Exit 1 if index.md differs from what would be generated")
    ap.add_argument("--self-check", action="store_true", help="Run the parser sanity check and exit")
    args = ap.parse_args()

    if args.self_check:
        self_check()
        return

    videos, text = build(args.kb_dir)
    index_path = args.kb_dir / "index.md"

    if args.check:
        current = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        if current != text:
            sys.exit(f"{index_path} is out of date - run: python3 {Path(__file__).name}")
        print(f"{index_path} is up to date ({len(videos)} videos)")
        return

    index_path.write_text(text, encoding="utf-8")
    chapters = sum(len(v["chapters"]) for v in videos)
    print(f"Wrote {index_path}: {len(videos)} videos, {chapters} chapters")


if __name__ == "__main__":
    main()
