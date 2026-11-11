# Coeos Memory

One long-term memory for Claude Code, Claude Chat and Cowork, kept as plain
markdown on your machine.

Your working sessions are summarised into a daily log. The log is compiled
into a wiki: one article per topic, cross-linked, readable and editable in
Obsidian. Every new session starts with the wiki's index, so Claude knows what
was decided last week and why.

The design follows the LLM wiki pattern described by Andrej Karpathy: raw
sources go in, a model writes and maintains the wiki, and you read and correct
it. See [docs/llm-wiki.md](docs/llm-wiki.md).

## How it works

```
Claude Code session
   │  hooks: session start, before compaction, session end
   ▼
capture        the turns not captured yet are summarised by Claude
   ▼
daily/2026-01-31.md          one log per day
   │  compile, once the day is over
   ▼
knowledge/*.md               the wiki, one article per topic
knowledge/index.md           rebuilt from the articles
   │
   ├──▶ injected at the start of the next Claude Code session
   └──▶ searched from Chat and Cowork through the desktop extension
```

Three properties hold by construction:

- **No duplicate capture.** The number of turns already taken is remembered
  per session. A compaction followed by the end of the same session never
  summarises the same turns twice.
- **No silent loss.** A piece that cannot be processed (expired login, rate
  limit, no network) stays in a queue and is retried.
- **No error stored as memory.** An answer that is neither an entry nor an
  explicit "nothing to keep" is rejected.

## Requirements

| What | Why | Required |
|---|---|---|
| [Claude Code](https://code.claude.com/docs), logged in | Hooks, and the Claude calls that write the memory | yes |
| Python 3.9 or later | Runs everything. No package to install: standard library only | yes |
| macOS or Linux | Windows is not supported yet | yes |
| [Obsidian](https://obsidian.md) | Reading, correcting and browsing the wiki | recommended |
| Claude desktop app | Gives Chat and Cowork access through the extension | optional |
| A decision model (for example Jev through OpenRouter) | Search by meaning instead of keywords | optional |
| A RAG backend: a [LightRAG](https://github.com/HKUDS/LightRAG) instance, alone or managed with [Coeos-RAG](https://github.com/Odyssai-eu/Coeos-RAG) | Graph retrieval over the wiki | optional |

## Install

```bash
git clone https://github.com/Odyssai-eu/coeos-memory.git
cd coeos-memory
python3 -m coeos_memory init
python3 -m coeos_memory install-hooks
python3 -m coeos_memory doctor
```

`init` creates the vault in `~/coeos-memory-vault` (choose another place with
`--vault`). `install-hooks` adds three hooks to `~/.claude/settings.json` and
keeps a backup of the file. `doctor` checks every part and tells you what to
fix.

Then open the vault in Obsidian: *Open folder as vault*.

Restart the Claude Code sessions that were open: hooks are read at start.

The step-by-step guide, including the desktop extension, is in
[docs/install.md](docs/install.md).

**Installing with an agent.** [AGENTS.md](AGENTS.md) tells a coding agent
everything it has to do, in order, and what it must never do. Open the
cloned folder in Claude Code and ask it to install Coeos Memory.

## Daily use

There is nothing to do. Work in Claude Code as usual.

- At the end of a session, and before each compaction, what was said is
  summarised into `daily/`.
- The first capture of a new day compiles the previous day into the wiki.
- The next session starts with the index.

Useful commands:

```bash
python3 -m coeos_memory compile --today   # compile now, without waiting for tomorrow
python3 -m coeos_memory search "why did we pick subnet routing"
python3 -m coeos_memory doctor
```

To keep a project out of the memory, create an empty file named
`.coeos-memory-ignore` at its root.

## What leaves your machine

- **Always:** the text of your sessions goes to Claude, through your own
  Claude Code login, to be summarised and compiled. It is the same service
  that already saw the session.
- **Only if you configure a decision model:** each search question, with the
  titles and summaries of your articles, and each log entry, go to that
  model's server.
- **Only if you configure a RAG backend:** the wiki articles go to the
  LightRAG instance you named.

Nothing else is sent anywhere. The vault is a folder you own.

## Cost

Capture makes one call to a small Claude model per 24,000 characters of new
conversation. Compilation makes one agentic call per day of log. Both count
against your Claude Code usage.

## Limits

- Developed and tested on macOS with Python 3.9 and Claude Code 2.1. Linux
  should work and is not tested. Windows is not supported.
- In Chat and Cowork nothing is captured automatically: those modes have no
  hooks. Claude writes to the memory only when it calls `memory_capture`.
  See [docs/install.md](docs/install.md) for the instruction that makes it
  do so.
- Cowork loads desktop extensions according to Anthropic's documentation. We
  have not verified it ourselves yet.
- One capture covers at most the last 144,000 characters of new conversation.
  Since Claude Code compacts long before that much is said, the cap is rarely
  reached.
- The LightRAG sync was tested against LightRAG 1.4.16.
- There is no automatic linting of the wiki yet. Contradictions and stale
  articles are found by reading, or by asking Claude to review a folder.

## Documentation

- [AGENTS.md](AGENTS.md): the complete guide for an agent that installs or
  operates the memory
- [Install](docs/install.md)
- [The LLM wiki, and how to grow yours](docs/llm-wiki.md)
- [Settings](docs/settings.md)
- [Troubleshooting](docs/troubleshooting.md)

## Credits

- Andrej Karpathy, for the
  [LLM wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
- [LightRAG](https://github.com/HKUDS/LightRAG) (HKUDS), the optional graph
  retrieval backend, and [Coeos-RAG](https://github.com/Odyssai-eu/Coeos-RAG),
  the console that manages LightRAG instances.
- [Obsidian](https://obsidian.md), the editor.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
