"""The vault: plain markdown on disk, readable in Obsidian.

    <vault>/
      WIKI.md            conventions the compiler follows; edit it freely
      daily/             one log per day, appended to by the capture
      knowledge/         the wiki: one article per topic, plus index.md
      .coeos/            state, queue and logs of this package

The daily logs are the source material. The articles are compiled from them
and may be rewritten at any time; correct an article in Obsidian and the next
session reads the corrected text.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import settings

INDEX_NAME = "index.md"
ENTRY_HEADING = re.compile(r"^## (\d\d:\d\d) · (.*)$")

WIKI_CONVENTIONS = """# Wiki conventions

This file tells the compiler how to write the articles of `knowledge/`.
Edit it to change how your wiki is organised.

## What an article is

One article per topic: a system, a project, a decision, a recurring problem.
Prefer updating an existing article over creating a near-duplicate.

## Format

```markdown
---
title: A short, specific title
summary: One sentence that says what the article establishes.
tags: [tag-one, tag-two]
sources: [2026-01-31, 2026-02-02]
created: 2026-01-31
updated: 2026-02-02
---

# A short, specific title

What is true now, stated plainly. Decisions come with their reason.
Pitfalls come with their root cause. Link related articles with
[[file-name-of-the-article]].
```

## Rules

- File names are lowercase words joined by hyphens, with the `.md` extension.
- `sources` lists the days whose log fed the article. Add the day you compile.
- Write what is true now. When a fact changes, rewrite it and keep one line
  on what it replaced and when.
- Never write a password, key or token.
- Do not edit `knowledge/index.md`: it is rebuilt from the articles.
"""


def root() -> Path:
    return settings.vault_dir()


def daily_dir() -> Path:
    return root() / "daily"


def knowledge_dir() -> Path:
    return root() / "knowledge"


def state_dir() -> Path:
    return root() / ".coeos"


def init() -> Path:
    """Create the vault skeleton. Existing files are left untouched."""
    for folder in (daily_dir(), knowledge_dir(), state_dir() / "queue"):
        folder.mkdir(parents=True, exist_ok=True)
    conventions = root() / "WIKI.md"
    if not conventions.exists():
        conventions.write_text(WIKI_CONVENTIONS, encoding="utf-8")
    if not (knowledge_dir() / INDEX_NAME).exists():
        rebuild_index()
    return root()


# ------------------------------------------------------------------ state

def load_state(name: str) -> dict:
    try:
        data = json.loads((state_dir() / f"{name}.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(name: str, data: dict) -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    target = state_dir() / f"{name}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(target)


# ------------------------------------------------------------- daily logs

def append_entry(text: str, label: str, when: datetime | None = None) -> Path:
    """Append one entry to the log of its day. Returns the log's path."""
    moment = when or datetime.now().astimezone()
    path = daily_dir() / f"{moment:%Y-%m-%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"# {moment:%Y-%m-%d}\n\n", encoding="utf-8")
    label = " ".join(label.split()) or "session"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"## {moment:%H:%M} · {label}\n\n{text.strip()}\n\n")
    return path


def entries(since: str = ""):
    """Yield (day, time, label, text) for every entry of the daily logs."""
    for path in sorted(daily_dir().glob("*.md")):
        day = path.stem
        if since and day < since:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        current, body = None, []
        for line in lines + ["## 00:00 · end"]:
            match = ENTRY_HEADING.match(line)
            if match:
                if current and "\n".join(body).strip():
                    yield day, current[0], current[1], "\n".join(body).strip()
                current, body = (match.group(1), match.group(2)), []
            elif current:
                body.append(line)


def normalise(text: str) -> str:
    return " ".join(text.lower().split())


def recently_logged(text: str, days: int = 7) -> bool:
    """True when the same text already sits in one of the last daily logs."""
    needle = normalise(text)
    for path in sorted(daily_dir().glob("*.md"), reverse=True)[:days]:
        try:
            if needle in normalise(path.read_text(encoding="utf-8")):
                return True
        except (OSError, UnicodeDecodeError):
            continue
    return False


# --------------------------------------------------------------- articles

def parse_front_matter(raw: str) -> tuple[dict, str]:
    """A small YAML subset: `key: value`, `key: [a, b]`, and `- item` lists."""
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---", 4)
    if end == -1:
        return {}, raw
    meta: dict = {}
    key = None
    for line in raw[4:end].splitlines():
        item = re.match(r"^\s+-\s+(.*)$", line)
        pair = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if item and key:
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(item.group(1).strip().strip("\"'"))
        elif pair:
            key, value = pair.group(1), pair.group(2).strip()
            if value.startswith("[") and value.endswith("]"):
                meta[key] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
            else:
                meta[key] = value.strip("\"'")
    return meta, raw[end + 4:].lstrip("\n")


def first_paragraph(body: str, limit: int = 240) -> str:
    for block in re.split(r"\n\s*\n", body):
        line = " ".join(block.split())
        if line and line[0] not in "#|>-":
            return line[:limit] + ("..." if len(line) > limit else "")
    return ""


def articles() -> list[dict]:
    """Every article: slug, path, title, summary, tags, sources, updated, body."""
    found = []
    for path in sorted(knowledge_dir().rglob("*.md")):
        if path.name == INDEX_NAME:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta, body = parse_front_matter(raw)
        listed = lambda key: meta.get(key) if isinstance(meta.get(key), list) else []
        found.append({
            "slug": path.relative_to(knowledge_dir()).with_suffix("").as_posix(),
            "path": path,
            "title": str(meta.get("title") or path.stem),
            "summary": str(meta.get("summary") or first_paragraph(body)),
            "tags": listed("tags"),
            "sources": [str(s) for s in listed("sources")],
            "updated": str(meta.get("updated") or ""),
            "body": body,
        })
    return found


def article_label(article: dict) -> str:
    """One line that identifies an article to a model or a reader."""
    label = article["title"]
    if article["summary"]:
        label += " — " + article["summary"]
    return label[:200]


def rebuild_index() -> Path:
    """Rewrite knowledge/index.md from the articles. Deterministic, no model."""
    rows = sorted(articles(), key=lambda a: a["title"].lower())
    lines = ["# Index", "", f"{len(rows)} articles. Rebuilt automatically; do not edit.", ""]
    if rows:
        lines += ["| Article | Summary | Updated |", "|---|---|---|"]
        for article in rows:
            summary = article["summary"].replace("|", "\\|")
            lines.append(f"| [[{article['slug']}]] | {summary} | {article['updated']} |")
    path = knowledge_dir() / INDEX_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
