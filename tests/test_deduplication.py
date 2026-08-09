from __future__ import annotations

from datetime import date

from litwatch.models import Author, Paper
from litwatch.services.deduplication import (
    deduplicate_papers,
    normalize_doi,
    titles_are_near_duplicates,
)


def paper(
    canonical_id: str,
    title: str,
    *,
    source: str,
    doi: str = "",
    authors: list[str] | None = None,
    abstract: str = "",
    publication_date: date | None = None,
    venue: str = "",
    url: str = "",
) -> Paper:
    return Paper(
        canonical_id=canonical_id,
        source_ids={source: canonical_id},
        sources=[source],
        title=title,
        doi=doi,
        authors=[Author(name=name) for name in authors or []],
        abstract=abstract,
        publication_date=publication_date,
        venue=venue,
        url=url,
    )


def test_normalize_doi_handles_case_labels_and_resolver_urls():
    expected = "10.1234/example"
    assert normalize_doi(" DOI:10.1234/Example ") == expected
    assert normalize_doi("https://doi.org/10.1234/Example") == expected
    assert normalize_doi("http://dx.doi.org/10.1234/EXAMPLE") == expected
    assert normalize_doi("not-a-doi") == ""


def test_doi_duplicates_merge_case_and_url_forms():
    result = deduplicate_papers(
        [
            paper(
                "openalex:w1",
                "A TDOA Localization Study",
                source="openalex",
                doi="HTTPS://DOI.ORG/10.1234/Example",
            ),
            paper(
                "crossref:x1",
                "A TDOA Localization Study",
                source="crossref",
                doi="doi:10.1234/example",
            ),
        ]
    )

    assert result.raw_count == 2
    assert result.dedup_count == 1
    assert result.duplicates_removed == 1
    assert result.papers[0].canonical_id == "doi:10.1234/example"
    assert result.papers[0].doi == "10.1234/example"
    assert result.papers[0].url == "https://doi.org/10.1234/example"
    assert result.papers[0].sources == ["crossref", "openalex"]


def test_exact_normalized_title_merges_punctuation_variants():
    result = deduplicate_papers(
        [
            paper("openalex:w1", "Underwater Acoustic: TDOA Localization", source="openalex"),
            paper("crossref:x1", "underwater acoustic TDOA localization", source="crossref"),
        ]
    )

    assert result.dedup_count == 1
    assert result.papers[0].sources == ["crossref", "openalex"]


def test_near_title_matching_protects_method_and_dimension_terms():
    first = "Robust 3D underwater acoustic TDOA localization using hydrophones"
    reordered = "Robust underwater acoustic TDOA localization using 3D hydrophones"
    different_method = "Robust 3D underwater acoustic DOA localization using hydrophones"
    different_dimension = "Robust 2D underwater acoustic TDOA localization using hydrophones"

    assert titles_are_near_duplicates(first, reordered) is True
    assert titles_are_near_duplicates(first, different_method) is False
    assert titles_are_near_duplicates(first, different_dimension) is False
    assert deduplicate_papers(
        [
            paper("openalex:w1", first, source="openalex"),
            paper("crossref:x1", different_method, source="crossref"),
        ]
    ).dedup_count == 2


def test_merge_selects_complete_real_metadata_and_unions_sources():
    sparse = paper(
        "arxiv:2401.00001",
        "Underwater Acoustic Localization",
        source="arxiv",
        authors=["Ada Lovelace"],
        abstract="Short abstract.",
        publication_date=date(2025, 2, 1),
        url="http://arxiv.org/abs/2401.00001",
    )
    complete = paper(
        "arxiv:2401.00001",
        "Underwater Acoustic Localization: A Hydrophone Array Study",
        source="semantic_scholar",
        authors=["Ada Lovelace", "Grace Hopper"],
        abstract="A substantially longer provider-backed abstract about the experiment.",
        publication_date=date(2024, 12, 1),
        venue="Journal of Underwater Acoustics",
        url="https://example.test/paper",
    )

    merged = deduplicate_papers([sparse, complete]).papers[0]

    assert merged.sources == ["arxiv", "semantic_scholar"]
    assert merged.title == complete.title
    assert [author.name for author in merged.authors] == ["Ada Lovelace", "Grace Hopper"]
    assert merged.abstract == complete.abstract
    assert merged.publication_date == date(2024, 12, 1)
    assert merged.venue == "Journal of Underwater Acoustics"
    assert merged.url == "https://example.test/paper"


def test_metadata_conflicts_are_deterministic_regardless_of_input_order():
    first = paper(
        "shared:identifier",
        "A deterministic underwater paper",
        source="openalex",
        authors=["Zed Author", "Second Author"],
        abstract="A provider abstract with equal length A.",
        publication_date=date(2025, 1, 2),
        venue="Venue Z",
    )
    second = paper(
        "shared:identifier",
        "A deterministic underwater paper",
        source="crossref",
        authors=["Alpha Author", "Second Author"],
        abstract="A provider abstract with equal length B.",
        publication_date=date(2024, 1, 2),
        venue="Venue A",
    )

    forward = deduplicate_papers([first, second]).papers[0]
    reverse = deduplicate_papers([second, first]).papers[0]

    assert forward.model_dump() == reverse.model_dump()
    assert [author.name for author in forward.authors] == ["Alpha Author", "Second Author"]
    assert forward.publication_date == date(2024, 1, 2)
    assert forward.venue == "Venue A"


def test_distinct_titles_without_shared_identity_are_not_merged():
    result = deduplicate_papers(
        [
            paper(
                "openalex:w1",
                "Underwater Acoustic TDOA Localization with a Sparse Array",
                source="openalex",
            ),
            paper(
                "crossref:x1",
                "Energy Efficient Routing for Underwater Sensor Networks",
                source="crossref",
            ),
        ]
    )

    assert result.dedup_count == 2


def test_conflicting_real_dois_block_even_exact_title_merge():
    result = deduplicate_papers(
        [
            paper(
                "openalex:w1",
                "Identical Underwater Acoustic Localization Title",
                source="openalex",
                doi="10.1234/first",
            ),
            paper(
                "crossref:x1",
                "Identical Underwater Acoustic Localization Title",
                source="crossref",
                doi="10.1234/second",
            ),
        ]
    )

    assert result.dedup_count == 2
    assert {paper.doi for paper in result.papers} == {"10.1234/first", "10.1234/second"}
