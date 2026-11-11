"""Capture: turn what was said in a session into entries of the daily log.

Two steps, so that a hook never waits on a model:

  enqueue()  runs inside the hook. It reads the transcript, takes the turns
             that were not captured yet and writes them to a queue. Fast,
             local, no network.
  drain()    runs in a detached worker. It asks Claude what is worth keeping
             in each queued piece and appends the answer to the daily log.

No duplicates: the number of turns already taken is remembered per session,
so a compaction followed by the end of the same session never captures the
same turns twice. No loss: a piece that could not be processed (expired
login, rate limit, no network) stays in the queue and is retried by the next
worker.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import INTERNAL_ENV, llm, settings, transcript, vault

MIN_NEW_TURNS = 4          # fewer new turns than this wait for the next capture
CHUNK_CHARS = 24_000       # one model call per chunk of conversation
MAX_CHUNKS = 6             # per capture; beyond that, the most recent are kept
IGNORE_MARKER = ".coeos-memory-ignore"
SECTIONS = ("**Context**", "**Decisions**", "**Lessons**", "**Facts**", "**Open items**")

SYSTEM = (
    "You keep the long-term memory of a person who works with an AI assistant. "
    "You are given part of a working session. You write down only what a future "
    "session would need to know. You never invent, and you never write a "
    "password, key or token."
)

INSTRUCTIONS = """Below is part of a working session between a user and an AI assistant.

Write a memory entry in markdown, using only the sections that apply:

**Context** — one sentence: what was being worked on.
**Decisions** — what was decided, each with its reason.
**Lessons** — what was learned the hard way: a pitfall and its root cause, a wrong assumption and what corrected it.
**Facts** — durable facts about a system, a project, or how the user wants things done.
**Open items** — what was left to do or to verify.

Leave out routine steps, tool output and anything that will not matter in a month.
Write in the language the user writes in. Be specific: names, versions, commands, numbers.

If nothing in this part is worth keeping, answer with the single word NOTHING.

--- SESSION ---

"""


def _log() -> logging.Logger:
    logger = logging.getLogger("coeos_memory")
    if not logger.handlers:
        vault.state_dir().mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(vault.state_dir() / "capture.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                               "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


class _Lock:
    """Exclusive lock on a file of the state folder."""

    def __init__(self, name: str, wait: bool):
        self.path = vault.state_dir() / f"{name}.lock"
        self.wait = wait
        self.handle = None

    def __enter__(self) -> bool:
        vault.state_dir().mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "w")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | (0 if self.wait else fcntl.LOCK_NB))
            return True
        except BlockingIOError:
            self.handle.close()
            self.handle = None
            return False

    def __exit__(self, *exc) -> None:
        if self.handle:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def ignored(project_dir: str) -> bool:
    """A project opts out with an empty `.coeos-memory-ignore` file at its root."""
    return bool(project_dir) and (Path(project_dir) / IGNORE_MARKER).exists()


# ---------------------------------------------------------------- enqueue

def enqueue(session_id: str, transcript_path: str, project_dir: str, force: bool = False) -> int:
    """Queue the turns of a session that were not captured yet.

    Returns the number of pieces queued. With `force` (end of a session) two
    new turns are enough; otherwise fewer than MIN_NEW_TURNS wait for the
    next capture.
    """
    path = Path(transcript_path)
    if not session_id or not path.is_file():
        return 0
    spoken = transcript.turns(path)
    with _Lock("offsets", wait=True):
        offsets = vault.load_state("offsets")
        taken = int(offsets.get(session_id, 0))
        fresh = spoken[taken:]
        if len(fresh) < (2 if force else MIN_NEW_TURNS):
            return 0
        groups = transcript.chunks(fresh, CHUNK_CHARS)[-MAX_CHUNKS:]
        now = datetime.now().astimezone()
        queue = vault.state_dir() / "queue"
        queue.mkdir(parents=True, exist_ok=True)
        project = Path(project_dir).name if project_dir else "session"
        for number, group in enumerate(groups):
            piece = {
                "session": session_id,
                "project": project,
                "captured_at": now.isoformat(timespec="seconds"),
                "text": transcript.render(group),
            }
            name = f"{now:%Y%m%d-%H%M%S}-{session_id[:8]}-{number:02d}.json"
            (queue / name).write_text(json.dumps(piece, ensure_ascii=False), encoding="utf-8")
        offsets[session_id] = len(spoken)
        vault.save_state("offsets", offsets)
    _log().info("queued %d piece(s) for session %s (%d new turns)",
                len(groups), session_id[:8], len(fresh))
    return len(groups)


def start_worker() -> None:
    """Start the worker detached from the hook that called us."""
    package_parent = str(Path(__file__).resolve().parent.parent)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = package_parent + os.pathsep + environment.get("PYTHONPATH", "")
    subprocess.Popen(
        [sys.executable, "-m", "coeos_memory", "worker"],
        env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# ------------------------------------------------------------------ drain

def extract(text: str) -> str:
    """Ask Claude for the memory entry of one piece. '' when nothing to keep."""
    answer = llm.ask(INSTRUCTIONS + text, SYSTEM, model=settings.capture_model())
    if answer.strip().strip(".").upper() == "NOTHING":
        return ""
    if not any(section in answer for section in SECTIONS):
        # Neither an entry nor NOTHING: refuse it rather than log it as memory.
        raise llm.LLMError(f"unexpected answer: {answer[:120]!r}")
    return answer


def drain() -> dict:
    """Process the queue, oldest first. Stops at the first failure."""
    counts = {"saved": 0, "nothing": 0, "left": 0}
    log = _log()
    with _Lock("worker", wait=False) as acquired:
        if not acquired:
            return counts  # a worker is already running and will take the queue
        queue = vault.state_dir() / "queue"
        pieces = sorted(queue.glob("*.json")) if queue.is_dir() else []
        for index, path in enumerate(pieces):
            try:
                piece = json.loads(path.read_text(encoding="utf-8"))
                entry = extract(piece["text"])
            except llm.LLMError as e:
                counts["left"] = len(pieces) - index
                log.error("capture stopped, %d piece(s) kept for retry: %s", counts["left"], e)
                break
            except (OSError, json.JSONDecodeError, KeyError) as e:
                log.error("unreadable piece %s removed: %s", path.name, e)
                path.unlink(missing_ok=True)
                continue
            when = datetime.fromisoformat(piece["captured_at"])
            if entry:
                vault.append_entry(entry, piece.get("project", "session"), when)
                counts["saved"] += 1
            else:
                counts["nothing"] += 1
            _shadow_gate(piece, bool(entry))
            path.unlink(missing_ok=True)
        log.info("worker done: %s", counts)
    return counts


def _shadow_gate(piece: dict, saved: bool) -> None:
    """Record the decision model's opinion next to what Claude did. Optional."""
    try:
        from . import decide
        if settings.decision()["url"]:
            decide.judge_gate(piece["text"], piece.get("session", ""), saved)
    except Exception as e:  # never let an optional step break the capture
        _log().warning("shadow opinion skipped: %s", e)


def after_capture() -> None:
    """Optional steps that follow a capture. None of them may raise."""
    log = _log()
    steps = []
    try:
        from . import compiler, decide, rag_sync
        steps = [
            ("compile", compiler.compile_finished_days),
            ("shadow opinions", lambda: decide.judge_entries(since=f"{datetime.now():%Y-%m-%d}")
             if settings.decision()["url"] else None),
            ("rag sync", lambda: rag_sync.sync(limit=10) if settings.lightrag()["url"] else None),
        ]
    except Exception as e:
        log.warning("optional steps unavailable: %s", e)
    for name, step in steps:
        try:
            step()
        except Exception as e:
            log.warning("%s skipped: %s", name, e)


# ------------------------------------------------------------------ hooks

def session_context(max_chars: int = 12_000) -> str:
    """What a new session is given: the index, and the end of the latest log."""
    parts = []
    index = vault.knowledge_dir() / vault.INDEX_NAME
    if index.is_file() and vault.articles():
        parts.append("## Wiki index\n\n" + index.read_text(encoding="utf-8").strip())
    logs = sorted(vault.daily_dir().glob("*.md"))
    if logs:
        tail = logs[-1].read_text(encoding="utf-8").strip().splitlines()[-40:]
        parts.append(f"## Latest log ({logs[-1].stem})\n\n" + "\n".join(tail))
    if not parts:
        return ""
    text = (
        "# Long-term memory\n\n"
        f"Articles live in {vault.knowledge_dir()}. Read one when its summary is relevant.\n\n"
        + "\n\n".join(parts)
    )
    return text if len(text) <= max_chars else text[:max_chars] + "\n\n[index truncated]"


def hook(event: str) -> int:
    """Entry point of the three Claude Code hooks. Always exits 0."""
    if os.environ.get(INTERNAL_ENV):
        return 0  # a session this package started itself
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    project_dir = str(payload.get("cwd") or os.getcwd())
    if ignored(project_dir):
        return 0
    try:
        if event == "session-start":
            context = session_context()
            if context:
                print(json.dumps({"hookSpecificOutput": {
                    "hookEventName": "SessionStart", "additionalContext": context}}))
        elif event in ("pre-compact", "session-end"):
            queued = enqueue(
                str(payload.get("session_id") or ""),
                str(payload.get("transcript_path") or ""),
                project_dir,
                force=(event == "session-end"),
            )
            if queued or any((vault.state_dir() / "queue").glob("*.json")):
                start_worker()
    except Exception as e:  # a hook must never break the user's session
        _log().error("hook %s failed: %s: %s", event, type(e).__name__, e)
    return 0
