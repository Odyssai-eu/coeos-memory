"""Install or remove the three Claude Code hooks, once per machine.

They go into ~/.claude/settings.json, so every Claude Code session in every
project reads the memory at start and feeds it at compaction and at the end.
Do not copy them into a project's own .claude/settings.json: they would run
twice.

Idempotent. The previous settings file is kept next to the new one.
"""

from __future__ import annotations

import json
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"
MARKER = "coeos_memory hook"
# event -> (argument, timeout in seconds)
HOOKS = {
    "SessionStart": ("session-start", 15),
    "PreCompact": ("pre-compact", 10),
    "SessionEnd": ("session-end", 10),
}


def command_for(argument: str) -> str:
    package_parent = Path(__file__).resolve().parent.parent
    return (f"PYTHONPATH={shlex.quote(str(package_parent))} {shlex.quote(sys.executable)} "
            f"-m {MARKER} {argument} || true")


def _ours(hook: dict) -> bool:
    return MARKER in str(hook.get("command", ""))


def apply(settings_path: Path = SETTINGS, remove: bool = False, dry_run: bool = False) -> list[str]:
    """Returns the list of changes made (empty when nothing had to change)."""
    try:
        original = settings_path.read_text(encoding="utf-8")
        data = json.loads(original)
    except FileNotFoundError:
        original, data = "", {}
    hooks = data.setdefault("hooks", {})
    changes: list[str] = []

    for event, (argument, timeout) in HOOKS.items():
        groups = hooks.get(event, [])
        mine = [h for g in groups for h in g.get("hooks", []) if _ours(h)]
        wanted = command_for(argument)
        if remove:
            if mine:
                for group in groups:
                    group["hooks"] = [h for h in group.get("hooks", []) if not _ours(h)]
                changes.append(f"{event}: removed")
        elif not mine:
            groups.append({"matcher": "", "hooks": [
                {"type": "command", "command": wanted, "timeout": timeout}]})
            changes.append(f"{event}: added")
        else:
            if mine[0].get("command") != wanted:
                mine[0]["command"] = wanted
                changes.append(f"{event}: updated")
            for extra in mine[1:]:
                for group in groups:
                    if extra in group.get("hooks", []):
                        group["hooks"].remove(extra)
                changes.append(f"{event}: duplicate removed")
        kept = [g for g in groups if g.get("hooks")]
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        data.pop("hooks", None)

    if changes and not dry_run:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        if original:
            backup = settings_path.with_name(
                f"{settings_path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
            shutil.copy2(settings_path, backup)
        settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    return changes


def installed(settings_path: Path = SETTINGS) -> list[str]:
    """Events that currently carry one of our hooks."""
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [event for event in HOOKS
            if any(_ours(h) for g in data.get("hooks", {}).get(event, [])
                   for h in g.get("hooks", []))]
