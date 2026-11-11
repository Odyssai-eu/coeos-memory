"""Send the wiki to a LightRAG instance: every new or changed file, once.

Optional. Nothing is sent unless a LightRAG address is configured.

No duplicates, by construction:

  - LightRAG names a document `doc-<md5 of its stripped text>`. It refuses a
    text it already holds, whatever file it comes from, and a second document
    for a file name it already knows (checked on LightRAG 1.4.16).
  - A local ledger (.coeos/rag-ledger.json) remembers what was sent for each
    file. An unchanged file costs no network call. A changed file has its
    previous document deleted before the new text is sent; if the deletion is
    still running, the file waits for the next run.

The ledger records a file once LightRAG has accepted it. Extraction happens
later on the server: check `coeos_memory rag status` for failed documents.
"""

from __future__ import annotations

import fcntl
import glob
import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from . import settings, vault

MIN_CHARS = 200
TIMEOUT = 60
# An embedding tokenizer may reject literal special tokens: neutralise them.
SPECIAL_TOKEN = re.compile(r"<\|(endoftext|im_start|im_end|endofprompt|fim_[a-z]+)\|>")


class RagUnavailable(RuntimeError):
    pass


def _call(method: str, path: str, body: dict | None = None) -> dict:
    config = settings.lightrag()
    if not config["url"]:
        raise RagUnavailable("no LightRAG address configured")
    headers = {"Content-Type": "application/json"}
    if config["api_key"]:
        headers["X-API-Key"] = config["api_key"]
    request = urllib.request.Request(
        config["url"] + path,
        json.dumps(body).encode() if body is not None else None,
        headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        raise RagUnavailable(f"{method} {path}: HTTP {e.code} "
                             f"{e.read().decode(errors='replace')[:200]}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise RagUnavailable(f"{method} {path}: {type(e).__name__}: {e}")


def doc_id_of(text: str) -> str:
    """The id LightRAG gives this text."""
    return "doc-" + hashlib.md5(text.strip().encode()).hexdigest()


def source_id(path: Path) -> str:
    """Stable name of a file in the RAG: its path from the home folder."""
    try:
        return path.resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix().lstrip("/")


def source_files() -> list[Path]:
    """Every file to keep in the RAG, newest first."""
    found: dict[str, Path] = {}
    for pattern in settings.rag_sources():
        for name in glob.glob(os.path.expanduser(pattern), recursive=True):
            path = Path(name)
            if path.is_file() and path.suffix == ".md" and path.name != vault.INDEX_NAME:
                found[str(path.resolve())] = path
    return sorted(found.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def _read(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return SPECIAL_TOKEN.sub(lambda m: "<" + m.group(1) + ">", text).strip()


def pending(ledger: dict) -> list[tuple[str, str]]:
    """(source id, text) for each file that is new or has changed."""
    todo = []
    for path in source_files():
        try:
            text = _read(path)
        except OSError:
            continue
        source = source_id(path)
        if len(text) >= MIN_CHARS and ledger.get(source, {}).get("doc_id") != doc_id_of(text):
            todo.append((source, text))
    return todo


def _find_by_source(source: str) -> str:
    page = 1
    while True:
        documents = _call("POST", "/documents/paginated",
                          {"page": page, "page_size": 200}).get("documents") or []
        for document in documents:
            if document.get("file_path") == source:
                return document.get("id") or ""
        if len(documents) < 200:
            return ""
        page += 1


def _send(source: str, text: str, ledger: dict) -> str:
    """Send one file. Returns 'sent', 'already' or 'waiting'."""
    new_id = doc_id_of(text)
    previous = ledger.get(source, {}).get("doc_id")
    if previous and previous != new_id:
        _call("DELETE", "/documents/delete_document", {"doc_ids": [previous]})

    answer = _call("POST", "/documents/text", {"text": text, "file_source": source})
    status, message = answer.get("status"), answer.get("message") or ""
    if status == "success":
        outcome = "sent"
    elif status == "duplicated" and "Identical content" in message:
        outcome = "already"
    elif status == "duplicated":
        # LightRAG still holds another text under this file name: an old
        # version being deleted, or one this ledger does not know about.
        if not previous:
            stale = _find_by_source(source)
            if stale:
                _call("DELETE", "/documents/delete_document", {"doc_ids": [stale]})
                ledger[source] = {"doc_id": stale, "state": "replacing"}
        return "waiting"
    else:
        raise RagUnavailable(f"insert {source}: {status} {message[:160]}")
    ledger[source] = {"doc_id": new_id, "track_id": answer.get("track_id"),
                      "at": datetime.now().astimezone().isoformat(timespec="seconds")}
    return outcome


def sync(limit: int = 0, dry_run: bool = False) -> dict:
    """Send what is new or changed. `limit` caps the files sent in this run."""
    counts = {"sent": 0, "already": 0, "waiting": 0, "left": 0}
    if not settings.lightrag()["url"]:
        return counts
    vault.state_dir().mkdir(parents=True, exist_ok=True)
    with open(vault.state_dir() / "rag.lock", "w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return counts  # another run is at work
        ledger = vault.load_state("rag-ledger")
        todo = pending(ledger)
        if dry_run:
            counts["left"] = len(todo)
            return counts
        for index, (source, text) in enumerate(todo):
            if limit and counts["sent"] >= limit:
                counts["left"] = len(todo) - index
                break
            try:
                counts[_send(source, text, ledger)] += 1
            except RagUnavailable as e:
                logging.getLogger("coeos_memory").error("rag sync stopped: %s", e)
                counts["left"] = len(todo) - index
                break
            vault.save_state("rag-ledger", ledger)
    return counts


def status() -> str:
    config = settings.lightrag()
    if not config["url"]:
        return "LightRAG: not configured. Nothing is sent."
    ledger = vault.load_state("rag-ledger")
    lines = [f"LightRAG: {config['url']}",
             f"Files tracked: {len(source_files())}, in the ledger: {len(ledger)}, "
             f"to send: {len(pending(ledger))}"]
    try:
        lines.append(f"On the server: {_call('GET', '/documents/status_counts').get('status_counts')}")
    except RagUnavailable as e:
        lines.append(f"Server unreachable: {e}")
    return "\n".join(lines)
