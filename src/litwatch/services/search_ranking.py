from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from itertools import pairwise

from litwatch.models import Paper
from litwatch.services.deduplication import normalize_doi
from litwatch.text import normalize_title

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


@dataclass(frozen=True)
class QualityScore:
    score: float
    title_present: float
    authors_present: float
    publication_date_present: float
    venue_present: float
    doi_present: float
    abstract_present: float
    source_coverage: float


@dataclass(frozen=True)
class PaperRankingScore:
    rank_score: float
    relevance: RelevanceScore
    quality: QualityScore


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


def quality_score(paper: Paper) -> QualityScore:
    """Score only source-backed metadata already present on the Paper."""
    title_present = float(bool(paper.title.strip()))
    authors_present = float(any(author.name.strip() for author in paper.authors))
    publication_date_present = float(paper.publication_date is not None)
    venue_present = float(bool(paper.venue.strip()))
    doi_present = float(bool(normalize_doi(paper.doi)))
    abstract_present = float(bool(paper.abstract.strip()))
    source_coverage = min(1.0, len(set(paper.sources)) / 2)
    score = (
        0.10 * title_present
        + 0.15 * authors_present
        + 0.10 * publication_date_present
        + 0.10 * venue_present
        + 0.15 * doi_present
        + 0.25 * abstract_present
        + 0.15 * source_coverage
    )
    return QualityScore(
        score=round(score, 6),
        title_present=title_present,
        authors_present=authors_present,
        publication_date_present=publication_date_present,
        venue_present=venue_present,
        doi_present=doi_present,
        abstract_present=abstract_present,
        source_coverage=round(source_coverage, 6),
    )


def paper_ranking_score(query: str, paper: Paper) -> PaperRankingScore:
    relevance = relevance_score(query, paper)
    quality = quality_score(paper)
    return PaperRankingScore(
        rank_score=round(0.85 * relevance.score + 0.15 * quality.score, 6),
        relevance=relevance,
        quality=quality,
    )


def rank_papers(query: str, papers: list[Paper]) -> list[Paper]:
    """Return scored copies in a stable total order."""
    scored: list[Paper] = []
    for candidate in papers:
        paper = candidate.model_copy(deep=True)
        ranking = paper_ranking_score(query, paper)
        paper.score = ranking.rank_score
        paper.score_detail = {
            "rank_score": ranking.rank_score,
            "relevance_score": ranking.relevance.score,
            "quality_score": ranking.quality.score,
            "relevance_components": {
                "title_coverage": ranking.relevance.title_coverage,
                "abstract_coverage": ranking.relevance.abstract_coverage,
                "ordered_pair_coverage": ranking.relevance.ordered_pair_coverage,
                "exact_phrase_title": ranking.relevance.exact_phrase_title,
                "all_query_title": ranking.relevance.all_query_title,
            },
            "quality_components": {
                "title_present": ranking.quality.title_present,
                "authors_present": ranking.quality.authors_present,
                "publication_date_present": ranking.quality.publication_date_present,
                "venue_present": ranking.quality.venue_present,
                "doi_present": ranking.quality.doi_present,
                "abstract_present": ranking.quality.abstract_present,
                "source_coverage": ranking.quality.source_coverage,
            },
        }
        scored.append(paper)

    return sorted(scored, key=_ranking_sort_key)


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


def _ranking_sort_key(paper: Paper) -> tuple[object, ...]:
    publication_year = paper.publication_date.year if paper.publication_date else -1
    return (
        -float(paper.score_detail["rank_score"]),
        -float(paper.score_detail["relevance_score"]),
        -float(paper.score_detail["quality_score"]),
        -publication_year,
        normalize_title(paper.title),
        paper.canonical_id.casefold(),
    )
