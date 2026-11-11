"""Check that every part of the installation works, and say what to do if not.

The most common failure is silent: the Claude login expires and nothing is
captured any more. `doctor` makes one small Claude call to catch exactly that.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

from . import hooks_install, llm, settings, vault


def _line(ok, label: str, detail: str = "") -> str:
    mark = {True: "ok  ", False: "FAIL", None: "--  "}[ok]
    return f"[{mark}] {label}" + (f": {detail}" if detail else "")


def _reachable(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            return "" if response.status < 500 else f"HTTP {response.status}"
    except urllib.error.HTTPError as e:
        return "" if e.code < 500 else f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return str(getattr(e, "reason", e))


def run(live: bool = True) -> tuple[str, bool]:
    """Returns (report, healthy). `live` makes one small Claude call."""
    lines, healthy = [], True

    def check(ok, label, detail="", required=True):
        nonlocal healthy
        lines.append(_line(ok, label, detail))
        if ok is False and required:
            healthy = False

    version = sys.version_info
    check(version >= (3, 9), "Python 3.9 or later", f"{version.major}.{version.minor}")

    try:
        binary = llm.claude_binary()
        check(True, "Claude Code command", binary)
    except llm.LLMError as e:
        binary = ""
        check(False, "Claude Code command", str(e))

    if binary and live:
        try:
            llm.ask("Reply with the single word OK.", "You answer in one word.",
                    model=settings.capture_model(), timeout=90)
            check(True, "Claude login", "a test call succeeded")
        except llm.LLMError as e:
            check(False, "Claude login", f"{e}. Run `claude` and log in again.")

    root = vault.root()
    if (root / "daily").is_dir() and (root / "knowledge").is_dir():
        logs = len(list(vault.daily_dir().glob("*.md")))
        check(True, "Vault", f"{root} ({logs} daily logs, {len(vault.articles())} articles)")
    else:
        check(False, "Vault", f"{root} is not initialised. Run `python3 -m coeos_memory init`.")

    events = hooks_install.installed()
    check(len(events) == len(hooks_install.HOOKS), "Claude Code hooks",
          ", ".join(events) if events else "none. Run `python3 -m coeos_memory install-hooks`.")

    queue = vault.state_dir() / "queue"
    waiting = len(list(queue.glob("*.json"))) if queue.is_dir() else 0
    check(waiting == 0 or None, "Capture queue",
          "empty" if not waiting else f"{waiting} piece(s) waiting; they are retried at the "
          "next capture, or now with `python3 -m coeos_memory worker`", required=False)

    decision = settings.decision()
    if decision["url"]:
        try:
            from . import decide
            decide.yes_no("The sky is blue.", "Is this statement about the weather or the sky?")
            check(True, "Decision model", f"{decision['model']} at {decision['url']}")
        except Exception as e:
            check(False, "Decision model", f"{decision['model']} at {decision['url']}: {e}",
                  required=False)
    else:
        check(None, "Decision model", "not configured (search uses keywords)", required=False)

    rag = settings.lightrag()
    if rag["url"]:
        problem = _reachable(rag["url"] + "/health")
        check(not problem, "LightRAG", rag["url"] + (f": {problem}" if problem else ""),
              required=False)
    else:
        check(None, "LightRAG", "not configured (nothing is sent)", required=False)

    return "\n".join(lines), healthy
