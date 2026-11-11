# Settings

Every setting can be given in three places. The first one found wins:

1. an environment variable;
2. the settings of the Coeos Memory extension in the Claude app
   (*Settings → Extensions → Coeos Memory*);
3. `~/.config/coeos-memory/config.json`.

The hooks and the commands read the extension's settings too, so if you use
the extension you configure everything there, once.

| Setting | Environment variable | Key in the extension and in `config.json` | Default |
|---|---|---|---|
| Vault folder | `COEOS_MEMORY_DIR` | `memory_dir` | `~/coeos-memory-vault` |
| Model that summarises a session | `COEOS_CAPTURE_MODEL` | `capture_model` | `haiku` |
| Model that writes the articles | `COEOS_COMPILE_MODEL` | `compile_model` | `sonnet` |
| Decision model: API address | `COEOS_DECISION_URL` | `decision_endpoint` | none |
| Decision model: model name | `COEOS_DECISION_MODEL` | `decision_model` | none |
| Decision model: API key | `COEOS_DECISION_API_KEY` | see below | none |
| LightRAG: instance address | `COEOS_LIGHTRAG_URL` | `lightrag_url` | none |
| LightRAG: API key | `COEOS_LIGHTRAG_API_KEY` | not stored in a file | none |
| LightRAG: files to send | `COEOS_RAG_SOURCES` | `rag_sources` | the wiki articles |

The two model settings take any name the `claude` command accepts for
`--model`. They are set by environment variable or in
`config.json`; the extension does not list them.

## The decision model

A decision model does not write text. It answers closed questions (pick one
option out of a list, or yes or no) and returns a probability. It is small,
fast and cheap, which makes it a good fit for ranking articles against a
question.

Any server that speaks the `systemone` protocol works. The address is the
part before `/systemone`.

| Provider | API address | Model name |
|---|---|---|
| OpenRouter | `https://openrouter.ai/api/v1` | `~typesafe/jev-latest` |
| A server on your network | `http://<host>:<port>/v1` | the name it serves |

**The tilde is part of the OpenRouter model name.** `typesafe/jev-latest` is
refused with "Model does not exist". When the model does not answer, search
falls back to keywords and says so in its result; nothing breaks.

What it is used for:

- **Search.** `memory_search` and `coeos_memory search` rank the articles by
  meaning.
- **Shadow opinions.** After each capture the model says which article an
  entry belongs to and whether a piece of session was worth saving. The
  opinions are written to `.coeos/shadow.jsonl` next to what Claude actually
  did. Nothing acts on them. `python3 -m coeos_memory decide score` shows how
  often the model was right at each level of confidence, so that you can
  decide from numbers, not from a demo, whether to trust it with more.

### The API key and the hooks

The Claude app stores the key you type in the extension encrypted, and gives
it only to the extension's own server. **The Claude Code hooks cannot read
it.** If your decision model needs a key, declare it for the hooks as well,
in the `env` block of `~/.claude/settings.json`:

```json
{
  "env": {
    "COEOS_DECISION_API_KEY": "your-key"
  }
}
```

`OPENROUTER_API_KEY` is read too when the address is OpenRouter's.

Without it the capture still works. Only the shadow opinions fail, and they
never block anything.

## The RAG backend: LightRAG or Coeos-RAG

[LightRAG](https://github.com/HKUDS/LightRAG) builds a knowledge graph from
documents and answers questions across them. You can run it in two ways:

- **LightRAG alone.** Install and start `lightrag-server` following
  LightRAG's documentation.
- **LightRAG managed with [Coeos-RAG](https://github.com/Odyssai-eu/Coeos-RAG).**
  Coeos-RAG is a console on top of LightRAG instances: documents, processing
  queue, queries, and a safe way to change the model or the embedder of a
  corpus. It runs on macOS.

Either way, Coeos Memory talks to the LightRAG instance directly. Give the
address of the instance itself, port included, not the address of the
Coeos-RAG console:

```
http://localhost:9621
```

After each capture, new and changed articles are sent, ten files per run at
most. To send everything now:

```bash
python3 -m coeos_memory rag sync
python3 -m coeos_memory rag status
```

Each file is sent once. LightRAG refuses a text it already holds, and a local
ledger (`.coeos/rag-ledger.json`) avoids even asking for an unchanged file.
A changed article replaces its previous version.

`rag status` shows the server's own counters. A file is recorded as sent when
LightRAG accepts it; the extraction happens afterwards on the server. Check
the `failed` counter after a large load.

To send more than the wiki, list glob patterns, separated by commas. `{vault}`
stands for the vault folder:

```
{vault}/knowledge/**/*.md, ~/projects/*/docs/sessions/*.md
```

## Keeping a project out

Create an empty file named `.coeos-memory-ignore` at the root of the project.
Sessions started there are neither captured nor given the index.

## What each part sends, and where

| Part | Sends | To |
|---|---|---|
| Capture | The new turns of a session | Claude, through your Claude Code login |
| Compile | A day's log and the articles it touches | Claude, through your Claude Code login |
| Search with a decision model | The question, and the title and summary of each article | The decision model's server |
| Shadow opinions | Each log entry, up to 6,000 characters | The decision model's server |
| RAG sync | The files matched by `rag_sources` | The LightRAG instance you named |

With no decision model and no LightRAG configured, the only destination is
Claude.
