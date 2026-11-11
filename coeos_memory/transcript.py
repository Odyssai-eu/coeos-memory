"""Read a Claude Code session transcript (JSONL) as a list of spoken turns.

Only what the user and the assistant said is kept. Tool calls, tool results
and thinking are left out: the memory is about what was decided and learned,
not about every file that was read on the way.
"""

from __future__ import annotations

import json
from pathlib import Path

MAX_TURN_CHARS = 4000


def turns(path: Path) -> list[tuple[str, str]]:
    """[(role, text)] in order. Unreadable lines are skipped."""
    spoken: list[tuple[str, str]] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = entry.get("message")
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant"):
                continue
            content = message.get("content")
            if isinstance(content, list):
                content = "\n".join(
                    block.get("text", "") for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            if isinstance(content, str) and content.strip():
                spoken.append((message["role"], content.strip()))
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
