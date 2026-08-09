from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from itertools import pairwise

from litwatch.models import Paper

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "using",
    "via",
    "with",
}


@dataclass(frozen=True)
class RelevanceScore:
    score: float
    title_coverage: float
    abstract_coverage: float
    ordered_pair_coverage: float
    exact_phrase_title: float
    all_query_title: float


def tokenize(value: str, *, remove_stopwords: bool = True) -> tuple[str, ...]:
    """Return stable Unicode-normalized tokens without external NLP dependencies."""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    tokens = tuple(_TOKEN_PATTERN.findall(normalized))
    if not remove_stopwords:
        return tokens
    return tuple(token for token in tokens if token not in _STOPWORDS)


def relevance_score(query: str, paper: Paper) -> RelevanceScore:
    """Score query evidence with title matches dominating abstract matches."""
    query_tokens = _unique_in_order(tokenize(query))
    title_tokens = tokenize(paper.title)
    abstract_tokens = tokenize(paper.abstract)
    query_set = set(query_tokens)
    title_set = set(title_tokens)
    abstract_set = set(abstract_tokens)

    title_coverage = _coverage(query_set, title_set)
    abstract_coverage = _coverage(query_set, abstract_set)
    ordered_pair_coverage = _ordered_pair_coverage(query_tokens, title_tokens)
    exact_phrase_title = float(
        bool(query_tokens)
        and " ".join(query_tokens) in " ".join(title_tokens)
    )
    all_query_title = float(bool(query_set) and query_set.issubset(title_set))
    score = (
        0.50 * title_coverage
        + 0.15 * abstract_coverage
        + 0.15 * ordered_pair_coverage
        + 0.10 * exact_phrase_title
        + 0.10 * all_query_title
    )
    return RelevanceScore(
        score=round(score, 6),
        title_coverage=round(title_coverage, 6),
        abstract_coverage=round(abstract_coverage, 6),
        ordered_pair_coverage=round(ordered_pair_coverage, 6),
        exact_phrase_title=exact_phrase_title,
        all_query_title=all_query_title,
    )


def _unique_in_order(tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(tokens))


def _coverage(query_tokens: set[str], evidence_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens & evidence_tokens) / len(query_tokens)


def _ordered_pair_coverage(
    query_tokens: tuple[str, ...],
    evidence_tokens: tuple[str, ...],
) -> float:
    query_pairs = tuple(pairwise(query_tokens))
    if not query_pairs:
        return 0.0
    evidence_pairs = set(pairwise(evidence_tokens))
    return sum(pair in evidence_pairs for pair in query_pairs) / len(query_pairs)
