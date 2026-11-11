"""Command line: python3 -m coeos_memory <command>

  init [--vault PATH]     create the vault and remember where it is
  install-hooks           add the three hooks to ~/.claude/settings.json
  remove-hooks            take them out again
  doctor                  check the whole installation
  compile [--today]       compile the pending daily logs into the wiki
  index                   rebuild knowledge/index.md
  search QUESTION         find articles
  worker                  process the capture queue now
  decide judge|score      shadow opinions of the decision model
  rag sync|status         send the wiki to LightRAG
  hook EVENT              entry point of the hooks (not for manual use)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, settings, vault


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coeos_memory", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--vault", type=Path)
    install = sub.add_parser("install-hooks")
    install.add_argument("--dry-run", action="store_true")
    sub.add_parser("remove-hooks")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--offline", action="store_true", help="skip the test call to Claude")
    compile_ = sub.add_parser("compile")
    compile_.add_argument("--today", action="store_true", help="include today's log")
    compile_.add_argument("--limit", type=int, default=30)
    sub.add_parser("index")
    search = sub.add_parser("search")
    search.add_argument("question", nargs="+")
    search.add_argument("--limit", type=int, default=5)
    sub.add_parser("worker")
    decide = sub.add_parser("decide")
    decide.add_argument("action", choices=("judge", "score"))
    decide.add_argument("--since", default="")
    decide.add_argument("--limit", type=int, default=0)
    rag = sub.add_parser("rag")
    rag.add_argument("action", choices=("sync", "status"))
    rag.add_argument("--limit", type=int, default=0)
    rag.add_argument("--dry-run", action="store_true")
    hook = sub.add_parser("hook")
    hook.add_argument("event", choices=("session-start", "pre-compact", "session-end"))

    args = parser.parse_args(argv)

    if args.command == "hook":
        from . import capture
        return capture.hook(args.event)

    if args.command == "worker":
        from . import capture
        counts = capture.drain()
        capture.after_capture()
        print(f"saved {counts['saved']}, nothing to keep {counts['nothing']}, "
              f"left in the queue {counts['left']}")
        return 0

    if args.command == "init":
        if args.vault:
            settings.write_config({"memory_dir": str(args.vault.expanduser().resolve())})
        root = vault.init()
        print(f"Vault ready: {root}\nOpen this folder in Obsidian (Open folder as vault).")
        return 0

    if args.command in ("install-hooks", "remove-hooks"):
        from . import hooks_install
        changes = hooks_install.apply(remove=args.command == "remove-hooks",
                                      dry_run=getattr(args, "dry_run", False))
        print("\n".join(changes) if changes else "Nothing to change.")
        if changes and not getattr(args, "dry_run", False):
            print("Restart the Claude Code sessions that are open: hooks are read at start.")
        return 0

    if args.command == "doctor":
        from . import doctor as doctor_module
        report, healthy = doctor_module.run(live=not args.offline)
        print(report)
        return 0 if healthy else 1

    if args.command == "compile":
        from . import compiler, llm
        days = compiler.pending_days(include_today=args.today)[:args.limit]
        if not days:
            print("Nothing to compile.")
            return 0
        for day in days:
            try:
                report = compiler.compile_day(day)
            except llm.LLMError as e:
                print(f"{day}: stopped. {e}", file=sys.stderr)
                return 1
            print(f"{day}:\n{report}\n")
        return 0

    if args.command == "index":
        print(vault.rebuild_index())
        return 0

    if args.command == "search":
        from . import search as search_module
        found = search_module.search(" ".join(args.question), args.limit)
        print(f"{len(found['results'])} of {found['total']} articles ({found['method']})")
        for item in found["results"]:
            article, relevance = item["article"], item["relevance"]
            score = f"  {relevance:.0%}" if relevance is not None else ""
            print(f"- {article['slug']}{score}\n  {article['summary']}")
        return 0

    if args.command == "decide":
        from . import decide as decide_module
        if args.action == "judge":
            print(f"{decide_module.judge_entries(args.since, args.limit)} entries judged")
        else:
            print(decide_module.score())
        return 0

    if args.command == "rag":
        from . import rag_sync
        if args.action == "status":
            print(rag_sync.status())
        else:
            counts = rag_sync.sync(args.limit, args.dry_run)
            print(f"sent {counts['sent']}, already there {counts['already']}, "
                  f"waiting {counts['waiting']}, left {counts['left']}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
