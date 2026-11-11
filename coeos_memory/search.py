"""Find the wiki articles that answer a question.

With a decision model configured, the articles are ranked by meaning: a
question in one language finds an article written in another. Without one, or
when it does not answer, the search falls back to keywords and says so.
"""

from __future__ import annotations

import re
import unicodedata

from . import settings, vault

MIN_RELEVANCE = 0.03
STOPWORDS = set(
    "a an and are as at be by for from how in is it of on or that the this to was what "
    "when where which who why with".split()
)


def fold(text: str) -> str:
    """Lowercase without accents, so 'mémoire' matches 'memoire'."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def keywords(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9_.-]*", fold(text))
            if len(w) > 1 and w not in STOPWORDS]


def _starts(word: str, text: str) -> int:
    """How many words of `text` begin with `word`."""
    return len(re.findall(r"(?<![a-z0-9])" + re.escape(word), text))


def keyword_score(article: dict, wanted: list[str]) -> int:
    title, slug = fold(article["title"]), fold(article["slug"])
    labels = fold(" ".join(article["tags"]) + " " + article["summary"])
    body = fold(article["body"])
    total = found = 0
    for word in wanted:
        hits = 8 * _starts(word, title) + 5 * _starts(word, labels) + 3 * _starts(word, slug)
        hits += min(_starts(word, body), 5)
        if hits:
            found += 1
            total += hits
    if found * 2 < len(wanted):
        return 0  # under half the words: noise
    return total * 2 if found == len(wanted) and len(wanted) > 1 else total


def search(query: str, limit: int = 5) -> dict:
    """{'method', 'total', 'results': [{'article', 'relevance'}]}.

    `method` is 'decision model' or 'keywords'. `relevance` is a probability
    with the decision model, None with keywords.
    """
    found = vault.articles()
    outcome = {"method": "keywords", "total": len(found), "results": []}
    if not found:
        return outcome

    if settings.decision()["url"]:
        try:
            from . import decide
            ranked = decide.rank(query, decide.Q_SEARCH,
                                 {a["slug"]: vault.article_label(a) for a in found})
            by_slug = {a["slug"]: a for a in found}
            picked = [(by_slug[k], p) for k, p in ranked if k in by_slug][:limit]
            kept = [(a, p) for a, p in picked if p >= MIN_RELEVANCE] or picked[:1]
            outcome["method"] = "decision model"
            outcome["results"] = [{"article": a, "relevance": p} for a, p in kept]
            return outcome
        except Exception:
            pass  # fall back to keywords

    wanted = keywords(query)
    scored = sorted(((keyword_score(a, wanted), a) for a in found), key=lambda pair: -pair[0])
    outcome["results"] = [{"article": a, "relevance": None} for s, a in scored if s > 0][:limit]
    return outcome


def find_article(name: str):
    """An article by slug, file name or title; None when there is no match."""
    wanted = fold(re.sub(r"\.md$", "", name.strip().strip("[]")))
    for article in vault.articles():
        if wanted in (fold(article["slug"]), fold(article["path"].stem), fold(article["title"])):
            return article
    return None
