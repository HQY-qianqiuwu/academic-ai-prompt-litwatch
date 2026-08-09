from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from litwatch.models import Author, Paper
from litwatch.text import canonical_id, normalize_title

_DOI_PREFIX = re.compile(r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)
_DOI_VALUE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_TITLE_TOKEN = re.compile(r"[a-z0-9]+")
_PROTECTED_TECHNICAL_TOKENS = {
    "auv",
    "doa",
    "mimo",
    "ofdm",
    "tdoa",
    "uwsn",
}


@dataclass(frozen=True)
class DeduplicationResult:
    papers: list[Paper]
    raw_count: int
    dedup_count: int

    @property
    def duplicates_removed(self) -> int:
        return self.raw_count - self.dedup_count


def normalize_doi(value: str) -> str:
    """Return a canonical bare DOI, or an empty string for an invalid value."""
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    normalized = _DOI_PREFIX.sub("", normalized, count=1).strip().casefold()
    if not _DOI_VALUE.fullmatch(normalized):
        return ""
    return normalized


def normalized_title_tokens(value: str) -> tuple[str, ...]:
    return tuple(_TITLE_TOKEN.findall(normalize_title(value)))


def titles_are_near_duplicates(first: str, second: str) -> bool:
    """Match only very close titles while protecting technical and numeric terms."""
    first_normalized = normalize_title(first)
    second_normalized = normalize_title(second)
    if first_normalized == second_normalized:
        return True

    first_tokens = normalized_title_tokens(first)
    second_tokens = normalized_title_tokens(second)
    if len(first_tokens) < 5 or len(second_tokens) < 5:
        return False

    first_numbers = {token for token in first_tokens if any(char.isdigit() for char in token)}
    second_numbers = {token for token in second_tokens if any(char.isdigit() for char in token)}
    if first_numbers != second_numbers:
        return False

    first_technical = set(first_tokens) & _PROTECTED_TECHNICAL_TOKENS
    second_technical = set(second_tokens) & _PROTECTED_TECHNICAL_TOKENS
    if first_technical != second_technical:
        return False

    first_set = set(first_tokens)
    second_set = set(second_tokens)
    union = first_set | second_set
    jaccard = len(first_set & second_set) / len(union) if union else 0.0
    sequence_ratio = SequenceMatcher(None, first_normalized, second_normalized).ratio()
    return jaccard >= 0.95 and sequence_ratio >= 0.95


def deduplicate_papers(papers: Iterable[Paper]) -> DeduplicationResult:
    """Group and merge papers without depending on Provider or input order."""
    candidates = sorted((paper.model_copy(deep=True) for paper in papers), key=_paper_sort_key)
    if not candidates:
        return DeduplicationResult(papers=[], raw_count=0, dedup_count=0)

    identities = [_paper_identity(paper) for paper in candidates]
    parents = list(range(len(candidates)))
    group_dois = [{identity[0]} if identity[0] else set() for identity in identities]

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if (
            group_dois[first_root]
            and group_dois[second_root]
            and group_dois[first_root] != group_dois[second_root]
        ):
            return
        new_root = min(first_root, second_root)
        old_root = max(first_root, second_root)
        parents[old_root] = new_root
        group_dois[new_root].update(group_dois[old_root])

    for first_index, first in enumerate(candidates):
        for second_index in range(first_index + 1, len(candidates)):
            if _papers_match(first, candidates[second_index], identities[first_index], identities[second_index]):
                union(first_index, second_index)

    groups: dict[int, list[Paper]] = {}
    for index, paper in enumerate(candidates):
        groups.setdefault(find(index), []).append(paper)

    merged = [merge_paper_group(group) for _, group in sorted(groups.items())]
    merged.sort(key=_paper_sort_key)
    return DeduplicationResult(
        papers=merged,
        raw_count=len(candidates),
        dedup_count=len(merged),
    )


def merge_paper_group(papers: Iterable[Paper]) -> Paper:
    """Merge one known duplicate group using deterministic, source-backed choices."""
    candidates = sorted((paper.model_copy(deep=True) for paper in papers), key=_paper_sort_key)
    if not candidates:
        raise ValueError("cannot merge an empty paper group")

    title = _choose_informative_text(paper.title for paper in candidates)
    doi_values = sorted(
        {
            doi
            for paper in candidates
            if (doi := _paper_doi(paper))
        }
    )
    doi = doi_values[0] if doi_values else ""
    stable_ids = sorted(
        {
            identity
            for paper in candidates
            if (identity := _stable_canonical_id(paper))
        }
    )
    merged_id = f"doi:{doi}" if doi else (stable_ids[0] if stable_ids else canonical_id(title=title))

    source_ids: dict[str, str] = {}
    for key in sorted({key for paper in candidates for key in paper.source_ids}):
        values = sorted(
            {
                value.strip()
                for paper in candidates
                if (value := paper.source_ids.get(key, "")).strip()
            }
        )
        if values:
            source_ids[key] = values[0]

    publication_dates = sorted(
        paper.publication_date for paper in candidates if paper.publication_date is not None
    )
    merged = candidates[0].model_copy(deep=True)
    merged.canonical_id = merged_id
    merged.source_ids = source_ids
    merged.sources = sorted({source for paper in candidates for source in paper.sources})
    merged.title = title
    merged.abstract = _choose_informative_text(paper.abstract for paper in candidates)
    merged.authors = _choose_authors(paper.authors for paper in candidates)
    merged.publication_date = publication_dates[0] if publication_dates else None
    merged.venue = _choose_informative_text(paper.venue for paper in candidates)
    merged.doi = doi
    merged.url = f"https://doi.org/{doi}" if doi else _choose_url(paper.url for paper in candidates)
    merged.pdf_url = _choose_url(paper.pdf_url for paper in candidates)
    merged.is_open_access = any(paper.is_open_access for paper in candidates)
    merged.citation_count = max((paper.citation_count for paper in candidates), default=0)
    merged.topic_id = _choose_informative_text(paper.topic_id for paper in candidates)
    merged.topic_name = _choose_informative_text(paper.topic_name for paper in candidates)
    merged.score = 0.0
    merged.score_detail = {}
    return merged


def _paper_doi(paper: Paper) -> str:
    doi = normalize_doi(paper.doi)
    if doi:
        return doi
    if paper.canonical_id.casefold().startswith("doi:"):
        return normalize_doi(paper.canonical_id)
    return ""


def _stable_canonical_id(paper: Paper) -> str:
    identity = unicodedata.normalize("NFKC", paper.canonical_id).strip().casefold()
    if not identity or identity.startswith(("doi:", "title:")):
        return ""
    return identity


def _paper_identity(paper: Paper) -> tuple[str, str, str]:
    return _paper_doi(paper), _stable_canonical_id(paper), normalize_title(paper.title)


def _papers_match(
    first: Paper,
    second: Paper,
    first_identity: tuple[str, str, str],
    second_identity: tuple[str, str, str],
) -> bool:
    first_doi, first_stable_id, first_title = first_identity
    second_doi, second_stable_id, second_title = second_identity
    if first_doi and first_doi == second_doi:
        return True
    if first_stable_id and first_stable_id == second_stable_id:
        return True
    if first_title and first_title == second_title:
        return True
    return titles_are_near_duplicates(first.title, second.title)


def _paper_sort_key(paper: Paper) -> tuple[object, ...]:
    return (
        _paper_doi(paper),
        normalize_title(paper.title),
        paper.canonical_id.casefold(),
        tuple(sorted(paper.sources)),
        tuple(author.name.casefold() for author in paper.authors),
    )


def _choose_informative_text(values: Iterable[str]) -> str:
    candidates = {unicodedata.normalize("NFKC", value).strip() for value in values if value.strip()}
    if not candidates:
        return ""
    return min(
        candidates,
        key=lambda value: (
            -len(normalized_title_tokens(value)),
            -len(normalize_title(value)),
            value.casefold(),
            value,
        ),
    )


def _choose_authors(author_lists: Iterable[list[Author]]) -> list[Author]:
    candidates = [
        [author.model_copy(deep=True) for author in authors if author.name.strip()]
        for authors in author_lists
    ]
    candidates = [authors for authors in candidates if authors]
    if not candidates:
        return []
    return min(
        candidates,
        key=lambda authors: (
            -len(authors),
            -sum(len(normalize_title(author.name)) for author in authors),
            tuple(author.name.casefold() for author in authors),
        ),
    )


def _choose_url(values: Iterable[str]) -> str:
    candidates = {value.strip() for value in values if value.strip()}
    if not candidates:
        return ""
    return min(
        candidates,
        key=lambda value: (
            0 if value.casefold().startswith("https://") else 1,
            value.casefold(),
            value,
        ),
    )
