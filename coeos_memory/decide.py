"""The decision model: closed questions, answered with a probability.

A decision model does not write. It picks one option out of a list, or says
yes or no, and gives a confidence. Any server that speaks the `systemone`
protocol works (POST <api base>/systemone): Jev through OpenRouter, or a
model served on your own network.

Two uses:

  rank()    order the wiki articles against a question. This is what makes
            `memory_search` read a question for its meaning.
  shadow    after each capture, the model says where an entry belongs and
            whether a piece of session was worth saving. Its opinion is
            written to .coeos/shadow.jsonl next to what really happened, and
            nothing acts on it. `coeos_memory decide score` compares the two,
            so that a threshold is chosen from measured accuracy before
            anything is automated.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime

from . import settings, vault

MAX_OPTIONS = 255      # most a `choice` question accepts
MAX_STATE_CHARS = 6000
MIN_ENTRY_CHARS = 200
TIMEOUT = 90

Q_ARTICLE = "Which wiki article does this log entry belong to?"
Q_SEARCH = "Which wiki article best answers this question?"
Q_DURABLE = (
    "Does this log entry contain a durable fact worth keeping: a decision, a lesson "
    "learned, a pitfall, or a fact about a project or a system?"
)
Q_GATE = (
    "Does this conversation contain anything worth saving to long-term memory: a "
    "decision with its reason, a lesson learned, a pitfall, or a durable fact about "
    "a project or a system?"
)
BANDS = (("0.8 and above", 0.8, 1.01), ("0.5 to 0.8", 0.5, 0.8), ("below 0.5", 0.0, 0.5))


class DecisionUnavailable(RuntimeError):
    pass


def ask(state: str, questions: dict) -> dict:
    """One call to the decision model. Returns its `answers`."""
    config = settings.decision()
    if not config["url"] or not config["model"]:
        raise DecisionUnavailable("no decision model configured")
    headers = {"Content-Type": "application/json"}
    if config["api_key"]:
        headers["Authorization"] = f"Bearer {config['api_key']}"
    body = {"model": config["model"], "state": state, "questions": questions}
    request = urllib.request.Request(
        f"{config['url']}/systemone", json.dumps(body).encode(), headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode())["answers"]
    except urllib.error.HTTPError as e:
        raise DecisionUnavailable(f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError) as e:
        raise DecisionUnavailable(f"{type(e).__name__}: {e}")


def rank(state: str, instructions: str, options: dict[str, str]) -> list[tuple[str, float]]:
    """Options sorted by probability, best first, for any number of options.

    Beyond 255 options they are split into groups; each group names its three
    best and the winners meet in a final call.
    """
    keys = list(options)

    def one_call(group: list[str]) -> list[tuple[str, float]]:
        question = {"type": "choice", "instructions": instructions,
                    "criteria": {k: options[k] for k in group}}
        answer = ask(state, {"q": question})["q"]
        return sorted(answer["probabilities"].items(), key=lambda kv: -kv[1])

    while len(keys) > MAX_OPTIONS:
        finalists: list[str] = []
        for start in range(0, len(keys), MAX_OPTIONS):
            finalists.extend(k for k, _ in one_call(keys[start:start + MAX_OPTIONS])[:3])
        keys = finalists
    return one_call(keys)


def yes_no(state: str, instructions: str) -> dict:
    """{'value', 'confidence'} for a yes/no question."""
    answer = ask(state, {"q": {"type": "noul", "instructions": instructions}})["q"]
    # `noul`, the probability of yes, is the one field every server returns.
    yes = float(answer["noul"])
    return {"value": yes >= 0.5, "confidence": round(max(yes, 1 - yes), 4)}


# ----------------------------------------------------------------- shadow

def _shadow_file():
    return vault.state_dir() / "shadow.jsonl"


def read_shadow() -> list[dict]:
    try:
        lines = _shadow_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _write_shadow(record: dict) -> None:
    vault.state_dir().mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "model": settings.decision()["model"], **record}
    with open(_shadow_file(), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _entry_id(text: str) -> str:
    return hashlib.sha256(vault.normalise(text).encode()).hexdigest()[:16]


def judge_entries(since: str = "", limit: int = 0) -> int:
    """Give an opinion on every log entry that has none yet. Returns the count."""
    seen = {r["id"] for r in read_shadow() if r.get("kind") == "entry"}
    options = {a["slug"]: vault.article_label(a) for a in vault.articles()}
    done = 0
    for day, clock, label, text in vault.entries(since):
        ident = _entry_id(text)
        if ident in seen or len(text) < MIN_ENTRY_CHARS:
            continue
        seen.add(ident)
        state = text[:MAX_STATE_CHARS]
        started = time.time()
        try:
            article = None
            if options:
                ranked = rank(state, Q_ARTICLE, options)
                article = {"choice": ranked[0][0], "confidence": round(ranked[0][1], 4),
                           "top": [[k, round(p, 4)] for k, p in ranked[:3]]}
            durable = yes_no(state, Q_DURABLE)
        except DecisionUnavailable as e:
            logging.getLogger("coeos_memory").error("shadow opinions stopped: %s", e)
            break
        _write_shadow({"kind": "entry", "id": ident, "day": day, "time": clock, "label": label,
                       "article": article, "durable": durable,
                       "seconds": round(time.time() - started, 1)})
        done += 1
        if limit and done >= limit:
            break
    return done


def judge_gate(context: str, session: str, saved: bool) -> None:
    """Opinion on a raw piece of session, next to whether Claude kept something."""
    opinion = yes_no(context[-MAX_STATE_CHARS:], Q_GATE)
    _write_shadow({"kind": "gate", "session": session, "worth_saving": opinion, "saved": saved})


def score() -> str:
    """Compare the opinions with what really happened. Returns a text report."""
    records = read_shadow()
    sources = {a["slug"]: set(a["sources"]) for a in vault.articles()}
    compiled_days = set().union(*sources.values()) if sources else set()
    lines = []

    entries = [r for r in records if r.get("kind") == "entry" and r.get("article")]
    judged = [r for r in entries if r["day"] in compiled_days]
    lines.append(f"Entries judged: {len(entries)}, of which {len(judged)} on a compiled day.")
    lines.append("")
    lines.append("Article chosen by the model, against the articles the compiler "
                 "attached to that day:")
    lines.append(f"{'confidence':<16}{'cases':>6}{'right':>7}{'rate':>7}")
    for name, low, high in BANDS:
        band = [r for r in judged if low <= r["article"]["confidence"] < high]
        right = sum(1 for r in band if r["day"] in sources.get(r["article"]["choice"], ()))
        rate = f"{100 * right / len(band):.0f} %" if band else "-"
        lines.append(f"{name:<16}{len(band):>6}{right:>7}{rate:>7}")

    gates = [r for r in records if r.get("kind") == "gate"]
    lines.append("")
    lines.append(f"Worth saving? Model against Claude: {len(gates)} cases.")
    if gates:
        lines.append(f"{'confidence':<16}{'cases':>6}{'agree':>7}")
        for name, low, high in BANDS:
            band = [r for r in gates if low <= r["worth_saving"]["confidence"] < high]
            agree = sum(1 for r in band if r["worth_saving"]["value"] == r["saved"])
            lines.append(f"{name:<16}{len(band):>6}{agree:>7}")
    lines.append("")
    lines.append("The article comparison is made per day, not per entry: a choice counts "
                 "as right when the article lists that day among its sources.")
    return "\n".join(lines)
