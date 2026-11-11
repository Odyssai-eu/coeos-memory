"""Compile the daily logs into the wiki.

For each finished day, Claude reads that day's log and the index, then creates
or updates articles in knowledge/, following the conventions of WIKI.md. The
index is rebuilt afterwards from the articles themselves, without a model.

A day is compiled once it is over, at the first capture of a later day, or on
demand (`coeos_memory compile`). A log that changed since it was compiled is
compiled again.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from . import llm, settings, vault

SYSTEM = (
    "You maintain a personal wiki written in markdown. You work only inside the "
    "current folder. You follow the conventions of WIKI.md exactly, you never "
    "invent facts, and you never write a password, key or token."
)

TASK = """Compile one day of the memory log into the wiki.

1. Read WIKI.md (the conventions) and knowledge/index.md (the existing articles).
2. Read daily/{day}.md.
3. For each decision, lesson or durable fact in that log:
   - if an existing article covers the topic, read it and update it;
   - otherwise create a new article in knowledge/.
   Add {day} to the `sources` of every article you touch and set `updated` to {day}.
4. Do not edit knowledge/index.md and do not touch daily/.

When you are done, answer with one line per article: `created <file>` or `updated <file>`.
If the log holds nothing worth an article, answer `nothing to compile`.
"""


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def pending_days(include_today: bool = False) -> list[str]:
    """Days whose log is new or changed since it was compiled, oldest first."""
    compiled = vault.load_state("compiled")
    today = f"{datetime.now():%Y-%m-%d}"
    days = []
    for path in sorted(vault.daily_dir().glob("*.md")):
        day = path.stem
        if day >= today and not include_today:
            continue
        has_entries = any(entry[0] == day for entry in vault.entries(day))
        if has_entries and compiled.get(day) != _digest(path):
            days.append(day)
    return days


def compile_day(day: str) -> str:
    """Compile one day. Returns Claude's report. Raises llm.LLMError on failure."""
    path = vault.daily_dir() / f"{day}.md"
    report = llm.ask(
        TASK.format(day=day), SYSTEM,
        model=settings.compile_model(),
        tools="Read,Write,Edit,Glob,Grep",
        cwd=vault.root(), accept_edits=True, timeout=900,
    )
    vault.rebuild_index()
    compiled = vault.load_state("compiled")
    compiled[day] = _digest(path)
    vault.save_state("compiled", compiled)
    return report


def compile_finished_days(include_today: bool = False, limit: int = 3) -> list[str]:
    """Compile what is pending, a few days per run. Returns the days compiled."""
    done = []
    for day in pending_days(include_today)[:limit]:
        try:
            compile_day(day)
        except llm.LLMError as e:
            logging.getLogger("coeos_memory").error("compile %s stopped: %s", day, e)
            break
        done.append(day)
    return done
