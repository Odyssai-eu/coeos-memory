# The LLM wiki, and how to grow yours

## The idea

Most personal knowledge bases die of maintenance. Writing a note is easy;
keeping two hundred notes consistent with each other is work nobody does.

The LLM wiki pattern, described by Andrej Karpathy in
[a short note](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f),
hands that work to a model. You supply raw material. The model writes the
wiki and keeps it up to date: it creates an article when a new topic appears,
rewrites the paragraph that became false, and links the pages together. You
read the result in an editor, and you correct it when it is wrong.

Coeos Memory applies the pattern to one specific source: your own working
sessions with Claude.

## The three layers

| Layer | In this package | Who writes it |
|---|---|---|
| Raw sources | `daily/`: what was said and decided, one log per day | The capture, after each session |
| The wiki | `knowledge/`: one article per topic, plus `index.md` | Claude, when it compiles a day |
| The conventions | `WIKI.md`: what an article is and how it is written | You |

The raw layer is append-only. The wiki layer is rewritten freely: an article
is the current best statement of a topic, not a history. The conventions are
the lever you hold: change `WIKI.md` and the next compilation follows it.

## The loop

1. **Capture.** At the end of a session, and before each compaction, the turns
   that were not captured yet are sent to Claude with one question: what would
   a future session need to know? The answer is a short entry with the
   sections that apply: context, decisions and their reasons, lessons, facts,
   open items. If nothing is worth keeping, nothing is written.
2. **Compile.** Once a day is over, Claude reads that day's log, the index and
   `WIKI.md`. It updates the articles that already cover a topic and creates
   the missing ones. Then the index is rebuilt from the articles themselves,
   by code, not by a model.
3. **Recall.** The next Claude Code session starts with the index: every
   article's title and one-sentence summary. Claude reads an article when its
   summary is relevant to the task. From Chat and Cowork, the same articles
   are reached with `memory_search` and `memory_read`.

## Starting your wiki

**Day one.** After `init`, the vault is empty. Work in Claude Code as usual.
When you close a session, look at `daily/`: today's log has an entry. To see
articles straight away:

```bash
python3 -m coeos_memory compile --today
```

Open `knowledge/` in Obsidian. Each article starts with a block like this:

```markdown
---
title: Remote access to the home lab
summary: How the lab is reached from outside, and why subnet routing was chosen.
tags: [network, tailscale]
sources: [2026-01-31]
created: 2026-01-31
updated: 2026-01-31
---
```

`summary` is what the index shows and what a search ranks. `sources` lists the
days whose log fed the article: follow them back to `daily/` to see where a
statement came from.

**The first weeks.** Read what gets written. Three things are worth doing
early:

- **Correct wrong statements in place.** Edit the article in Obsidian. The
  next session reads your text. Nothing overwrites a correction unless a
  later log contradicts it, in which case the article says what changed.
- **Merge near-duplicates.** If two articles cover one topic, tell Claude in
  a session: "merge these two articles of my memory". Or do it by hand and
  delete one file.
- **Tighten the conventions.** If articles are too long, too granular or in
  the wrong language, say so in `WIKI.md`. It is plain prose; write the rule
  the way you would explain it to a colleague.

## Bringing in notes you already have

The compiler reads anything in `daily/` that has this shape:

```markdown
# 2025-11-03

## 09:00 · import

The text of your note, or several notes one after the other.
```

Create a file named after a past date, paste your notes under a heading of
that form, and run:

```bash
python3 -m coeos_memory compile
```

Do it in batches of a few pages. A day's log that is too long produces
shallow articles.

## When the wiki grows

The index given to a new session is capped at 12,000 characters, about 80
articles. Beyond that it is cut, and recall depends on search.

- **Keyword search** works with no extra setup. It matches words, so a
  question must use the words of the article, in its language.
- **A decision model** ranks articles by meaning. A question in French finds
  an article written in English. It is one setting; see
  [settings.md](settings.md).
- **LightRAG** builds a knowledge graph over the articles and answers
  questions that span several of them. Useful from a few hundred articles.
  See [settings.md](settings.md).

## What is not automated

There is no linter yet. Nothing checks the wiki for contradictions, orphan
pages or stale articles on a schedule. Reading your wiki in Obsidian is the
check; the graph view shows orphans at a glance.
