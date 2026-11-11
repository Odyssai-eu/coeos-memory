# Troubleshooting

Start here:

```bash
python3 -m coeos_memory doctor
```

It checks Python, the `claude` command, the login (with one small test call),
the vault, the hooks, the capture queue, and the optional decision model and
LightRAG. A line marked `FAIL` says what to do.

The capture log is `<vault>/.coeos/capture.log`.

## Nothing is being captured

**The login expired.** This is the usual cause, and it is silent from Claude
Code's side. `doctor` reports `FAIL Claude login`. Start `claude`, log in
again, then process what was waiting:

```bash
python3 -m coeos_memory worker
```

Nothing was lost in the meantime: pieces that could not be processed stay in
`<vault>/.coeos/queue/`.

**The hooks are not installed, or the session is older than the hooks.**
`doctor` reports the hooks it finds. Run `install-hooks`, then restart the
Claude Code session: hooks are read at start.

**The session was too short.** A session with fewer than two spoken turns is
not captured. Between compactions, at least four new turns are needed.

**The project opted out.** Look for a `.coeos-memory-ignore` file at its root.

**You moved the cloned folder.** The hooks point to its old path. Run
`install-hooks` again from the new place.

## The log has entries but there are no articles

Compilation waits for the day to be over, then runs at the first capture of
a later day. To compile now:

```bash
python3 -m coeos_memory compile --today
```

If it stops with an error, the message is Claude's. Fix the cause (most often
the login, or a usage limit) and run it again: a day is marked compiled only
when it succeeded.

## Claude does not use the memory in Chat or Cowork

- **The extension is disabled.** It is installed switched off. Enable it in
  *Settings → Extensions*.
- **The conversation is older than the extension.** Start a new one.
- **Claude did not think of it.** In these modes the tools are called at
  Claude's discretion. Add the instruction given in
  [install.md](install.md#5-chat-and-cowork-the-desktop-extension), or ask
  explicitly: "search my memory for …".

The extension's own log is in the Claude app's log folder, in a file named
`mcp-server-Coeos Memory.log`.

## Search returns nothing, or says it used keywords

Keyword search matches words. Ask with the words the article uses, in the
language it is written in, or configure a decision model.

If a decision model is configured and the result still says `keywords`, the
model did not answer. `doctor` shows why. Two common causes:

- The model name. On OpenRouter it is `~typesafe/jev-latest`, with the tilde.
- The key. The extension has it; the hooks and the command line need it in
  the environment. See
  [settings.md](settings.md#the-api-key-and-the-hooks).

## An entry appears twice

It should not: captured turns are counted per session. If you see it, check
that the hooks are installed once. A copy in a project's own
`.claude/settings.json` in addition to the one in `~/.claude/settings.json`
makes each hook run twice.

## LightRAG shows failed documents

```bash
python3 -m coeos_memory rag status
```

The `failed` counter is LightRAG's. The LightRAG interface, or Coeos-RAG if
you use it, gives the reason per document and can reprocess them. A frequent cause is the extraction model of
the instance not being loaded.

## Removing everything

```bash
python3 -m coeos_memory remove-hooks
```

Then remove the extension from the Claude app. The vault and
`~/.config/coeos-memory/` are left in place; delete them yourself if you want
to.
