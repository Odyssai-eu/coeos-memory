"""Ask Claude through the Claude Code command line, with no other dependency.

The capture and the compiler run `claude -p`, so they use the login the user
already has in Claude Code. The JSON output carries an explicit error flag:
an expired login or a rate limit is reported as an error and is never
mistaken for an answer.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import INTERNAL_ENV

# Hooks started by a desktop app may run with a short PATH.
USUAL_PLACES = ("~/.local/bin", "~/.claude/local", "/opt/homebrew/bin", "/usr/local/bin")


class LLMError(RuntimeError):
    """Claude gave no usable answer. The caller keeps its input for later."""


def claude_binary() -> str:
    found = shutil.which("claude")
    if found:
        return found
    for place in USUAL_PLACES:
        candidate = Path(place).expanduser() / "claude"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise LLMError("the `claude` command was not found; install Claude Code first")


def ask(
    prompt: str,
    system: str,
    model: str = "",
    tools: str = "",
    cwd: Path | None = None,
    accept_edits: bool = False,
    timeout: int = 300,
) -> str:
    """One non-interactive Claude call. Returns the text of its answer.

    `tools` is a comma-separated list of built-in tools ("" for none). With
    `accept_edits`, Claude may write files under `cwd` without asking.
    """
    command = [
        claude_binary(), "-p", prompt,
        "--output-format", "json",
        "--system-prompt", system,
        "--tools", tools,
        "--no-session-persistence",
        "--strict-mcp-config",
    ]
    if model:
        command += ["--model", model]
    if accept_edits:
        command += ["--permission-mode", "acceptEdits"]
    environment = dict(os.environ, **{INTERNAL_ENV: "1"})
    try:
        done = subprocess.run(
            command, cwd=str(cwd) if cwd else None, env=environment,
            capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise LLMError(f"Claude did not answer within {timeout} seconds")
    except OSError as e:
        raise LLMError(f"could not start Claude: {e}")

    output = done.stdout.strip()
    try:
        answer = json.loads(output)
    except json.JSONDecodeError:
        detail = (output or done.stderr.strip())[:200]
        raise LLMError(f"Claude returned no result (exit {done.returncode}): {detail}")
    if not isinstance(answer, dict) or answer.get("is_error") or answer.get("subtype") != "success":
        detail = str(answer.get("result") or answer.get("subtype") or "")[:200] \
            if isinstance(answer, dict) else ""
        raise LLMError(f"Claude reported an error: {detail}")
    text = str(answer.get("result") or "").strip()
    if not text:
        raise LLMError("Claude returned an empty answer")
    return text
