# Install

Five steps. The first three give Claude Code a memory. The fourth lets you
read it. The fifth extends it to Claude Chat and Cowork.

## Before you start

Check the three required pieces.

**Claude Code, logged in.**

```bash
claude --version
```

If the command is not found, install Claude Code first
(<https://code.claude.com/docs>). Then start `claude` once and log in. The
memory uses this login for every call it makes. When the login expires,
nothing is captured until you log in again; `doctor` detects it.

**Python 3.9 or later.**

```bash
python3 --version
```

macOS ships it with the Xcode command line tools
(`xcode-select --install`). On Linux, use your distribution's package. There
is no `pip install`: the package uses the standard library only.

**Git**, to fetch the code.

## 1. Get the code

```bash
git clone https://github.com/Odyssai-eu/coeos-memory.git
cd coeos-memory
```

Keep this folder where it is afterwards: the hooks point to it. If you move
it, run `install-hooks` again from the new place.

## 2. Create the vault

```bash
python3 -m coeos_memory init
```

This creates `~/coeos-memory-vault` with:

| Path | Content |
|---|---|
| `daily/` | One log per day, written by the capture |
| `knowledge/` | The wiki: one article per topic, and `index.md` |
| `WIKI.md` | The conventions the compiler follows. Edit it to shape your wiki |
| `.coeos/` | State, queue and logs. Hidden in Obsidian |

To put the vault elsewhere, for example in a synced folder:

```bash
python3 -m coeos_memory init --vault ~/Documents/Memory
```

The choice is stored in `~/.config/coeos-memory/config.json`.

## 3. Install the hooks

```bash
python3 -m coeos_memory install-hooks
```

Three hooks are added to `~/.claude/settings.json`:

| Hook | What it does |
|---|---|
| `SessionStart` | Gives the new session the wiki index and the end of the latest log |
| `PreCompact` | Captures what was said before Claude Code compacts the conversation |
| `SessionEnd` | Captures what is left when the session ends |

The previous `settings.json` is kept next to the new one, with a `.bak-` and
the date in its name. Running the command twice changes nothing.
`--dry-run` shows what would change.

They apply to every project. Do not copy them into a project's own
`.claude/settings.json`: they would run twice.

**Restart the Claude Code sessions that are open.** Hooks are read when a
session starts.

Check everything:

```bash
python3 -m coeos_memory doctor
```

Every line should read `ok`. Lines marked `--` are optional parts you have not
configured.

## 4. Open the vault in Obsidian

Install Obsidian from <https://obsidian.md>. Choose *Open folder as vault*
and select the vault folder.

No plugin is required. The articles link to each other with `[[wikilinks]]`,
so the graph view and the backlinks panel work out of the box.

The vault is empty until your first captured session. To see the full loop
without waiting for tomorrow, finish a Claude Code session, then:

```bash
python3 -m coeos_memory compile --today
```

## 5. Chat and Cowork: the desktop extension

Claude Chat and Cowork cannot read files on their own and have no hooks. The
extension gives them three tools on the same vault: `memory_search`,
`memory_read` and `memory_capture`.

Build it and open it:

```bash
python3 scripts/build_extension.py
open dist/coeos-memory.mcpb        # macOS; on Linux, open the file from the app
```

The Claude app asks for the memory folder. Give it the vault.

**The extension is installed disabled.** Go to *Settings → Extensions* and
switch it on.

In these two modes Claude uses the memory only when it decides to call the
tools. To make that the default, add this to your instructions
(*Settings → Profile*):

> Before answering a question about my projects, my setup or something we
> decided earlier, call `memory_search`. When a conversation produces a
> decision, a lesson or a durable fact, call `memory_capture` before you
> conclude.

This raises the odds; it is not a guarantee. Only Claude Code captures
automatically.

## Updating

```bash
git pull
python3 -m coeos_memory install-hooks
python3 scripts/build_extension.py   # then reinstall the extension if you use it
```

## Uninstalling

```bash
python3 -m coeos_memory remove-hooks
```

Remove the extension from *Settings → Extensions*. The vault is yours: delete
the folder only if you want to lose the memory.
