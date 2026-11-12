"""Read a Claude Code session transcript (JSONL) as a list of spoken turns.

Only what the human typed and what the assistant wrote is kept. Tool calls,
tool results, thinking, skill bodies and system reminders are left out, and so
are the entries the harness writes under the same roles: the memory is about
what was decided and learned, not about every file that was read on the way.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

MAX_TURN_CHARS = 4000

# A user entry whose text starts with one of these was written by the harness
# (a slash command, a notification, a compaction summary, an interruption).
HARNESS_PREFIXES = (
    "<command-name>", "<command-message>", "<local-command-", "<system-reminder>",
    "<task-notification>", "<bash-", "Base directory for this skill",
    "This session is being continued", "[Request interrupted", "Caveat:",
)
# The harness appends these blocks to a message the human typed.
SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)


def speaker(entry: object) -> str:
    """'user' or 'assistant' when the entry is a message a person or the assistant
    wrote, '' otherwise.

    The top-level `type` decides. Other types, such as api-request-blob, carry
    message roles too, but they hold harness content, so they never count.
    """
    if not isinstance(entry, dict):
        return ""
    message = entry.get("message")
    if not isinstance(message, dict):
        return ""
    kind = entry.get("type")
    if kind == "user":
        if message.get("role") != "user":
            return ""
        if entry.get("isMeta") or entry.get("isCompactSummary") or entry.get("isSidechain"):
            return ""
        # An origin other than a human means a notification or a peer message.
        # An entry with no origin at all is from older transcripts, and is human.
        origin = entry.get("origin")
        if origin is not None and not (isinstance(origin, dict) and origin.get("kind") == "human"):
            return ""
        return "user"
    if kind == "assistant":
        if message.get("role") != "assistant":
            return ""
        if entry.get("isSidechain") or entry.get("isApiErrorMessage"):
            return ""
        if message.get("model") == "<synthetic>":
            return ""
        return "assistant"
    return ""


def spoken_text(role: str, content: object) -> str:
    """The text of a message, without tool blocks, and without harness text.

    '' when nothing is left to keep.
    """
    if isinstance(content, list):
        content = "\n".join(
            block.get("text") or "" for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    if not isinstance(content, str):
        return ""
    if role == "user":
        content = SYSTEM_REMINDER.sub("", content).strip()
        if content.startswith(HARNESS_PREFIXES):
            return ""
    return content.strip()


def turns(path: Path) -> list[tuple[str, str]]:
    """[(role, text)] in order. Unreadable lines are skipped."""
    spoken: list[tuple[str, str]] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = speaker(entry)
            if not role:
                continue
            text = spoken_text(role, entry["message"].get("content"))
            if text:
                spoken.append((role, text))
    return spoken


def render(spoken: list[tuple[str, str]]) -> str:
    """Turns as text for the model. A very long turn keeps its head and tail."""
    parts = []
    for role, text in spoken:
        if len(text) > MAX_TURN_CHARS:
            half = MAX_TURN_CHARS // 2
            text = text[:half] + "\n[...]\n" + text[-half:]
        parts.append(f"{'USER' if role == 'user' else 'ASSISTANT'}:\n{text}")
    return "\n\n".join(parts)


def chunks(spoken: list[tuple[str, str]], max_chars: int) -> list[list[tuple[str, str]]]:
    """Split turns into consecutive groups of at most `max_chars` each."""
    groups: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    size = 0
    for turn in spoken:
        length = min(len(turn[1]), MAX_TURN_CHARS) + 20
        if current and size + length > max_chars:
            groups.append(current)
            current, size = [], 0
        current.append(turn)
        size += length
    if current:
        groups.append(current)
    return groups
