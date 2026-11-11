# AGENTS.md: install and operate Coeos Memory

A guide for an agent (or a person) who has to install, update, operate or
extend Coeos Memory without the context of those who built it. What the
product is for is described in [README.md](README.md).

Everything an agent is expected to do is in this file. If a task is not
covered here, say so and ask before improvising.

## What you install

| Piece | Role | Form | Required |
|---|---|---|---|
| The package (this repository) | Captures sessions, compiles the wiki, searches it | Standard-library Python, started by the hooks | yes |
| The vault | Holds the memory | A folder of markdown: `daily/`, `knowledge/`, `WIKI.md` | yes |
| Three hooks | Connect Claude Code to the package | Entries in `~/.claude/settings.json` | yes |
| The desktop extension | Gives Claude Chat and Cowork access to the vault | `dist/coeos-memory.mcpb`, installed in the Claude app | optional |
| A decision model | Ranks articles by meaning | A remote API speaking the `systemone` protocol | optional |
| A RAG backend | Graph retrieval over the wiki | A LightRAG instance, standalone or managed with Coeos-RAG | optional |

The package and the vault are two different folders. The package is code and
is versioned here. The vault is the user's data and is never committed
anywhere by you.

## Platforms

| Piece | macOS | Linux | Windows |
|---|---|---|---|
| Package and hooks | yes | expected to work, not tested | no (`fcntl`) |
| Desktop extension | yes | expected to work, not tested | no |
| Obsidian | yes | yes | yes |

Tested with Python 3.9 and Claude Code 2.1 on macOS.

## Rules you never break

- **Never work around a failed login.** When a Claude call fails with "not
  logged in", "session expired" or a usage limit, stop and tell the user to
  run `claude` and log in. Do not retry in a loop, do not switch model, do
  not rewrite code to avoid the call. Nothing is lost while you wait: the
  capture queue keeps what could not be processed.
- **Never say "installed" before section 3 passes.**
- **Never write a secret.** No password, key or token in the vault, in
  `config.json`, in a commit, or in your messages. An API key is typed by the
  user, in the extension or in the `env` block of their settings (section 5).
- **`daily/` is append-only.** Do not delete, reorder or rewrite entries. The
  one exception is importing notes (section 7), which adds a file.
- **Never edit `knowledge/index.md` by hand.** Rebuild it:
  `python3 -m coeos_memory index`.
- **Never copy the hooks into a project's `.claude/settings.json`.** They
  live in `~/.claude/settings.json` only. Two copies make every capture run
  twice.
- **Never edit `~/.claude/settings.json` by hand to add or remove the
  hooks.** Use `install-hooks` and `remove-hooks`: they are idempotent and
  keep a backup.
- **Never send the vault to a server the user did not name.** There is no
  default decision model and no default RAG address, on purpose.
- **Never remove the `COEOS_MEMORY_INTERNAL` guard.** The package starts
  Claude itself; without the guard its own sessions would be captured, which
  would start Claude again, without end.
- **Never commit a vault into this repository.**

## Prerequisites

Run these and read the output before anything else.

```bash
python3 --version      # 3.9 or later
claude --version       # Claude Code is installed
git --version
```

If `claude` is missing, stop: the user installs Claude Code and logs in
themselves (<https://code.claude.com/docs>). You cannot log in for them.

There is nothing to `pip install`.

## 1. Install the package and create the vault

```bash
git clone https://github.com/Odyssai-eu/coeos-memory.git
cd coeos-memory
python3 -m coeos_memory init
```

`init` creates `~/coeos-memory-vault` and never overwrites an existing file,
so it is safe to run on a vault that already has content. Ask the user where
they want the vault before running it if they keep notes in a synced folder:

```bash
python3 -m coeos_memory init --vault "/path/they/chose"
```

The path is stored in `~/.config/coeos-memory/config.json`.

The cloned folder must stay where it is: the hooks point to it. If it is
moved later, run section 2 again from the new place.

## 2. Install the hooks

Show the user what will change, then apply it:

```bash
python3 -m coeos_memory install-hooks --dry-run
python3 -m coeos_memory install-hooks
```

This adds `SessionStart`, `PreCompact` and `SessionEnd` hooks to
`~/.claude/settings.json`, leaves every other hook untouched, and saves the
previous file as `settings.json.bak-<date>-<time>`.

Tell the user to restart the Claude Code sessions that are open, including
the one you are running in: hooks are read when a session starts.

## 3. Verify (blocking)

```bash
python3 -m coeos_memory doctor
```

Every required line must read `ok`. `doctor` makes one small Claude call to
check the login. Lines marked `--` are optional parts that are not configured.
A `FAIL` line says what to do; do it, or hand it to the user if it is theirs
to do (logging in), then run `doctor` again.

Then check the session-start hook by hand:

```bash
echo '{"session_id":"probe","cwd":"/tmp"}' | python3 -m coeos_memory hook session-start
```

It prints nothing on an empty vault, and a JSON object with
`additionalContext` once the vault has at least one log or article. Either is
correct; an error is not.

You cannot prove the capture from inside the session you are running in: it
happens when a session ends. Tell the user exactly this, and what to look for
after their next session:

- `<vault>/.coeos/capture.log` has a line `queued N piece(s)` followed by
  `worker done: {'saved': ...}`;
- `<vault>/daily/<today>.md` has a new entry.

If you are started again in a later session, check those two things before
reporting the installation as working.

## 4. The desktop extension (optional)

Only if the user wants the memory in Claude Chat or Cowork.

```bash
python3 scripts/build_extension.py
```

This writes `dist/coeos-memory.mcpb`. The rest is done by the user, in the
Claude app; you cannot do it for them:

1. Open the file (`open dist/coeos-memory.mcpb` on macOS).
2. Give the vault folder when asked.
3. **Enable the extension** in *Settings → Extensions*. It is installed
   switched off.
4. Start a new conversation and ask: "search my memory for …".

In Chat and Cowork nothing is captured automatically. Give the user this
instruction to paste in *Settings → Profile*, and tell them it raises the
odds without guaranteeing anything:

> Before answering a question about my projects, my setup or something we
> decided earlier, call `memory_search`. When a conversation produces a
> decision, a lesson or a durable fact, call `memory_capture` before you
> conclude.

## 5. A decision model (optional)

Without one, search matches keywords. With one, it ranks articles by meaning.

Ask the user which provider they use. The address is the part before
`/systemone`.

| Provider | API address | Model name |
|---|---|---|
| OpenRouter | `https://openrouter.ai/api/v1` | `~typesafe/jev-latest` |
| A server on their network | `http://<host>:<port>/v1` | the name it serves |

The tilde is part of the OpenRouter model name. Without it the server answers
"Model does not exist".

Where the values go:

- **With the extension:** the user types the address, the model and the key
  in *Settings → Extensions → Coeos Memory*. The hooks read the address and
  the model from there.
- **Without the extension:** write the address and the model with
  environment variables (`COEOS_DECISION_URL`, `COEOS_DECISION_MODEL`) or in
  `~/.config/coeos-memory/config.json` (`decision_endpoint`,
  `decision_model`).

**The key.** The Claude app keeps the key typed in the extension encrypted
and hands it only to the extension. The hooks cannot read it. If the provider
needs a key, the user must also declare it in the `env` block of
`~/.claude/settings.json`. Tell them where; do not ask them to paste the key
to you.

```json
{
  "env": {
    "COEOS_DECISION_API_KEY": "their-key"
  }
}
```

Verify with `python3 -m coeos_memory doctor` (the `Decision model` line), then
`python3 -m coeos_memory search "a question"`: the first line of the result
must say `decision model`, not `keywords`.

## 6. A RAG backend: LightRAG or Coeos-RAG (optional)

Worth it from a few hundred articles. The backend is always a
[LightRAG](https://github.com/HKUDS/LightRAG) instance. The user has two ways
to run one:

- **LightRAG alone.** They install and start `lightrag-server` following
  LightRAG's own documentation.
- **LightRAG managed with [Coeos-RAG](https://github.com/Odyssai-eu/Coeos-RAG).**
  Coeos-RAG is a console on top of LightRAG instances: documents, processing
  queue, queries, and switching the model or the embedder of a corpus safely.
  Its own `AGENTS.md` covers its installation. It runs on macOS.

In both cases, give Coeos Memory **the address of the LightRAG instance
itself**, port included. Coeos-RAG is not in the data path: its own address
is the console's, not the instance's.

Set it in the extension (*LightRAG: instance address*), or with
`COEOS_LIGHTRAG_URL`, or as `lightrag_url` in `config.json`. Then:

```bash
python3 -m coeos_memory rag sync --dry-run   # how many files would be sent
python3 -m coeos_memory rag sync             # send them
python3 -m coeos_memory rag status
```

Before a first load, tell the user how many files it is and that extraction
runs on their instance for a while afterwards. After it, read the `failed`
counter in `rag status`: a file is recorded as sent when LightRAG accepts it,
and extraction happens later. Failed documents are reprocessed from the
LightRAG or Coeos-RAG interface.

Never restart a LightRAG instance while it is extracting: its store can be
truncated. If the instance is managed with Coeos-RAG, let Coeos-RAG do
restarts; it refuses when the instance is busy.

## 7. Operations

| Task | Command |
|---|---|
| Check everything | `python3 -m coeos_memory doctor` |
| Process the capture queue now | `python3 -m coeos_memory worker` |
| Compile the finished days | `python3 -m coeos_memory compile` |
| Compile today as well | `python3 -m coeos_memory compile --today` |
| Rebuild the index | `python3 -m coeos_memory index` |
| Search | `python3 -m coeos_memory search "question"` |
| Score the decision model's opinions | `python3 -m coeos_memory decide score` |
| Send the wiki to the RAG | `python3 -m coeos_memory rag sync` |

**Keeping a project out.** Create an empty `.coeos-memory-ignore` file at its
root. Sessions started there are neither captured nor given the index.

**Importing existing notes.** Create `<vault>/daily/<a past date>.md` with
this shape, then run `compile`. Import a few pages at a time.

```markdown
# 2025-11-03

## 09:00 · import

The text of the notes.
```

**Changing how the wiki is written.** Edit `<vault>/WIKI.md`. The compiler
reads it at every run.

## 8. Using the memory while you work

When the hooks are installed, your session starts with a block titled
"Long-term memory": the path of the articles, the index, and the end of the
latest log.

- **Read before you answer.** If the user asks about a project, their setup,
  or something decided earlier, look for a matching summary in the index and
  read that article's file. When the index is truncated or nothing matches,
  run `python3 -m coeos_memory search "…"`.
- **Do not capture by hand in Claude Code.** The hooks do it when the session
  compacts or ends. Writing to `daily/` yourself would duplicate it.
- **In Chat and Cowork**, use `memory_search`, `memory_read` and
  `memory_capture`. Capture once, near the end, a self-contained entry with
  the sections that apply: **Context**, **Decisions**, **Lessons**,
  **Facts**, **Open items**.
- **When the user corrects a fact,** fix the article that states it: edit the
  file in `knowledge/`, keep one line on what it replaced and when, set
  `updated` to today, then run `python3 -m coeos_memory index`.
- **When two articles cover one topic,** merge them into one, union their
  `sources`, replace `[[links]]` to the removed file, delete it, then rebuild
  the index. Do it only when the user asks.
- **Say where a statement comes from** when it matters: the article, and the
  days listed in its `sources`.

## 9. Diagnose

Start with `doctor`. The capture log is `<vault>/.coeos/capture.log`.

| Symptom | Cause | What to do |
|---|---|---|
| `FAIL Claude login`, or the log says `Not logged in` / `session expired` | The Claude Code login expired | Tell the user to run `claude` and log in. Then `worker` |
| No new entry after a session | Hooks missing, or the session started before they were installed | `install-hooks`, then the user restarts the session |
| No new entry, hooks present | Fewer than two spoken turns, or the project has `.coeos-memory-ignore` | Nothing to fix |
| `Capture queue: N piece(s) waiting` | A Claude call failed earlier | Fix the cause shown in the log, then `worker` |
| Entries exist, no article | The day is not over yet | `compile --today` |
| Search result says `keywords` with a decision model set | The model did not answer | `doctor`; check the model name (tilde) and the key in `env` |
| An entry appears twice | Hooks installed in two places | Remove the copy in the project's `.claude/settings.json` |
| Claude ignores the memory in Chat | Extension disabled, or the conversation predates it | The user enables it and starts a new conversation |
| `rag status` shows `failed` | Extraction failed on the instance | The user reprocesses from the LightRAG or Coeos-RAG interface |

## 10. Update and uninstall

```bash
git pull
python3 -m coeos_memory install-hooks
python3 -m coeos_memory doctor
python3 scripts/build_extension.py    # the user then reinstalls the extension
```

```bash
python3 -m coeos_memory remove-hooks
```

The user removes the extension in the Claude app. Leave the vault and
`~/.config/coeos-memory/` in place unless the user asks you, in so many
words, to delete the memory.

## 11. Develop

```bash
python3 -m unittest discover -s tests -v
python3 scripts/build_extension.py
```

- Standard library only. No third-party import, in the package or the tests.
- Python 3.9 syntax. Keep `from __future__ import annotations` at the top of
  a module that uses modern type hints.
- Tests use no network and never call Claude: patch `llm.ask`.
- The version lives in two places that must match:
  `coeos_memory/__init__.py` and `extension/manifest.json`. The build fails
  if they differ.
- A hook must never break the user's session: `capture.hook` catches
  everything and exits 0. Keep it that way.
- An optional step (decision model, RAG, compile after capture) must never
  block a capture.
- No address, host or key in the code. Everything comes from
  `coeos_memory/settings.py`.

## Code map

| Module | Role |
|---|---|
| `coeos_memory/settings.py` | Every setting: environment, extension, `config.json`, default |
| `coeos_memory/vault.py` | The vault on disk: daily logs, articles, index, state |
| `coeos_memory/transcript.py` | Reads a Claude Code transcript as spoken turns |
| `coeos_memory/llm.py` | One non-interactive `claude -p` call, with explicit errors |
| `coeos_memory/capture.py` | The hooks, the queue and the worker |
| `coeos_memory/compiler.py` | Daily logs into wiki articles |
| `coeos_memory/search.py` | Ranking by decision model, keyword fallback |
| `coeos_memory/decide.py` | Decision model client, shadow opinions, scoring |
| `coeos_memory/rag_sync.py` | LightRAG sync with a ledger |
| `coeos_memory/hooks_install.py` | Adds and removes the hooks |
| `coeos_memory/doctor.py` | The installation check |
| `coeos_memory/__main__.py` | The command line |
| `extension/` | Manifest and MCP server of the desktop extension |
| `scripts/build_extension.py` | Builds `dist/coeos-memory.mcpb` |

State lives in `<vault>/.coeos/`: `offsets.json` (turns already captured per
session), `queue/` (pieces waiting for Claude), `compiled.json`,
`shadow.jsonl`, `rag-ledger.json`, `capture.log`.

## What leaves the machine

| Part | Sends | To |
|---|---|---|
| Capture and compile | Session text, logs, the articles being edited | Claude, through the user's Claude Code login |
| Decision model, if set | Search questions with article titles and summaries; log entries | The provider the user named |
| RAG sync, if set | The files matched by `rag_sources` | The LightRAG instance the user named |

Tell the user this before you configure a decision model or a RAG backend.
