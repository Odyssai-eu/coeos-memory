#!/usr/bin/env python3
"""MCP server of the Coeos Memory extension.

Gives Claude Chat and Cowork, which have neither file access nor hooks, three
tools on the same vault Claude Code feeds:

  memory_search   find the wiki articles that answer a question
  memory_read     return one article in full
  memory_capture  append an entry to today's log; the compiler turns it into
                  wiki articles later

Standard library only, Python 3.9+. stdio transport, one JSON-RPC message per
line. The `coeos_memory` package is bundled next to this file.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coeos_memory import __version__, search, vault  # noqa: E402

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_READ_CHARS = 60_000
MAX_CAPTURE_CHARS = 8_000
MIN_CAPTURE_CHARS = 40

TOOLS = [
    {
        "name": "memory_search",
        "description": (
            "Search the user's long-term memory: a wiki compiled from their past working "
            "sessions (decisions and their reasons, lessons, pitfalls, facts about their "
            "projects and systems). Call it before answering a question about their projects, "
            "their setup or something decided earlier. Returns the closest articles with a "
            "summary; read the useful one with memory_read."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A question or a few keywords."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_read",
        "description": (
            "Return one article of the user's long-term memory in full. `article` is the "
            "identifier given by memory_search."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"article": {"type": "string"}},
            "required": ["article"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_capture",
        "description": (
            "Add an entry to the user's long-term memory. Call it when the conversation "
            "produced something durable: a decision and its reason, a lesson, a pitfall, a "
            "fact about a project or a system. Write a self-contained, concise entry using "
            "the sections that apply: **Context**, **Decisions**, **Lessons**, **Facts**, "
            "**Open items**. Never include a password, key or token. An entry identical to "
            "a recent one is refused."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The entry, in markdown."},
                "source": {
                    "type": "string",
                    "description": "Where the entry comes from: chat, cowork or code.",
                    "default": "chat",
                },
            },
            "required": ["content"],
            "additionalProperties": False,
        },
    },
]


def log(message):
    sys.stderr.write("[coeos-memory] %s\n" % message)
    sys.stderr.flush()


def text_result(text):
    return {"content": [{"type": "text", "text": text}], "isError": False}


def error_result(text):
    return {"content": [{"type": "text", "text": text}], "isError": True}


def tool_search(args):
    query = str(args.get("query") or "").strip()
    if not query:
        return error_result("query is empty.")
    limit = max(1, min(int(args.get("limit") or 5), 10))
    found = search.search(query, limit)
    if not found["total"]:
        return text_result("The memory holds no article yet (%s)." % vault.knowledge_dir())
    if not found["results"]:
        hint = ""
        if found["method"] == "keywords":
            hint = (" The search ran on keywords: try two or three specific terms, in the "
                    "language the articles are written in.")
        return text_result("No article matches \"%s\" (%d articles).%s"
                           % (query, found["total"], hint))
    lines = ["%d of %d articles for \"%s\" (ranked by %s):"
             % (len(found["results"]), found["total"], query, found["method"]), ""]
    for item in found["results"]:
        article, relevance = item["article"], item["relevance"]
        detail = "article: %s | updated: %s" % (article["slug"], article["updated"] or "?")
        if relevance is not None:
            detail += " | relevance: %d%%" % round(100 * relevance)
        lines += ["## %s" % article["title"], detail, article["summary"], ""]
    return text_result("\n".join(lines).rstrip())


def tool_read(args):
    name = str(args.get("article") or "").strip()
    if not name:
        return error_result("article is empty.")
    article = search.find_article(name)
    if article is None:
        return error_result("No such article: %s. Use memory_search." % name)
    text = article["path"].read_text(encoding="utf-8")
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + "\n\n[truncated]"
    return text_result(text)


def tool_capture(args):
    content = str(args.get("content") or "").strip()
    source = "".join(c for c in str(args.get("source") or "chat").lower()
                     if c.isalnum() or c in "-_")[:20] or "chat"
    if len(content) < MIN_CAPTURE_CHARS:
        return error_result("Entry too short to be useful (%d characters)." % len(content))
    if len(content) > MAX_CAPTURE_CHARS:
        return error_result("Entry too long (%d characters, maximum %d). Summarise it."
                            % (len(content), MAX_CAPTURE_CHARS))
    if not vault.root().is_dir():
        return error_result("Memory folder not found: %s" % vault.root())
    if vault.recently_logged(content):
        return text_result("Already in the memory: nothing was added.")
    path = vault.append_entry(content, source)
    log("captured %d characters from %s into %s" % (len(content), source, path.name))
    return text_result("Added to %s (%d characters)." % (path.name, len(content)))


HANDLERS = {
    "memory_search": tool_search,
    "memory_read": tool_read,
    "memory_capture": tool_capture,
}


def handle(message):
    """Return the response to a request, or None for a notification."""
    if "id" not in message:
        return None
    identifier = message["id"]
    method = message.get("method")
    params = message.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        result = {
            "protocolVersion": requested if requested in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "coeos-memory", "version": __version__},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        handler = HANDLERS.get(params.get("name"))
        if handler is None:
            return {"jsonrpc": "2.0", "id": identifier,
                    "error": {"code": -32602, "message": "unknown tool: %s" % params.get("name")}}
        try:
            result = handler(params.get("arguments") or {})
        except Exception as e:  # the server must survive a bad call
            result = error_result("%s: %s" % (type(e).__name__, e))
    else:
        return {"jsonrpc": "2.0", "id": identifier,
                "error": {"code": -32601, "message": "method not found: %s" % method}}
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def main():
    log("start v%s, vault at %s" % (__version__, vault.root()))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "parse error"}}
        else:
            response = handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
