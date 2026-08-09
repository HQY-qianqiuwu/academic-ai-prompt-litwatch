from __future__ import annotations

from datetime import date

from litwatch.models import Author, Paper
from litwatch.services.search_ranking import (
    quality_score,
    rank_papers,
    relevance_score,
    tokenize,
)


def paper(title: str, abstract: str = "") -> Paper:
    return Paper(canonical_id=f"test:{title}", title=title, abstract=abstract)


def test_tokenization_preserves_technical_terms_and_digits():
    assert tokenize("The TDOA, OFDM/MIMO 3D U-Net using AUV and UWSN") == (
        "tdoa",
        "ofdm",
        "mimo",
        "3d",
        "u",
        "net",
        "auv",
        "uwsn",
    )


def test_tdoa_golden_titles_outrank_generic_underwater_routing():
    query = "underwater acoustic TDOA localization"
    candidates = [
        paper("Underwater Acoustic TDOA Localization with Sparse Hydrophone Arrays"),
        paper("Energy Efficient Routing for Underwater Sensor Networks"),
        paper("Underwater Acoustic Localization Using Time Difference of Arrival"),
    ]

    scores = [relevance_score(query, candidate).score for candidate in candidates]

    assert scores[0] > scores[1]
    assert scores[2] > scores[1]
    assert scores[0] - scores[1] >= 0.4


def test_ofdm_golden_title_outranks_generic_auv_networking():
    query = "underwater acoustic OFDM communication"
    ofdm = paper("Channel Estimation and Equalization for Underwater Acoustic OFDM Communication")
    generic = paper("Adaptive Routing for AUV Networks in Underwater Environments")

    assert relevance_score(query, ofdm).score > relevance_score(query, generic).score


def test_title_evidence_has_more_weight_than_abstract_only_evidence():
    query = "underwater acoustic TDOA localization"
    title_match = paper("Underwater Acoustic TDOA Localization")
    abstract_match = paper(
        "Hydrophone Array Processing",
        "This paper studies underwater acoustic TDOA localization.",
    )

    assert relevance_score(query, title_match).score > relevance_score(query, abstract_match).score


def test_complete_title_phrase_receives_explicit_rewards():
    score = relevance_score(
        "underwater acoustic TDOA localization",
        paper("Robust Underwater Acoustic TDOA Localization"),
    )

    assert score.title_coverage == 1.0
    assert score.ordered_pair_coverage == 1.0
    assert score.exact_phrase_title == 1.0
    assert score.all_query_title == 1.0
    assert score.score == 0.85


def test_relevance_scoring_is_deterministic():
    candidate = paper(
        "Underwater Acoustic OFDM Channel Estimation",
        "Communication performance is evaluated using real measurements.",
    )

    first = relevance_score("underwater acoustic OFDM communication", candidate)
    second = relevance_score("underwater acoustic OFDM communication", candidate)

    assert first == second


def test_complete_metadata_beats_sparse_metadata_at_equal_relevance():
    sparse = paper("Underwater Acoustic TDOA Localization")
    sparse.canonical_id = "sparse"
    complete = paper(
        "Underwater Acoustic TDOA Localization",
        "A real provider-backed abstract.",
    )
    complete.canonical_id = "complete"
    complete.authors = [Author(name="Ada Lovelace")]
    complete.publication_date = date(2025, 1, 1)
    complete.venue = "Journal of Underwater Acoustics"
    complete.doi = "10.1234/complete"
    complete.sources = ["openalex", "crossref"]

    ranked = rank_papers("underwater acoustic TDOA localization", [sparse, complete])

    assert quality_score(complete).score > quality_score(sparse).score
    assert [item.canonical_id for item in ranked] == ["complete", "sparse"]


def test_quality_cannot_overpower_large_relevance_advantage():
    relevant = paper("Underwater Acoustic TDOA Localization")
    relevant.canonical_id = "relevant"
    complete_but_generic = paper(
        "Energy Efficient Routing for Underwater Sensor Networks",
        "A complete but unrelated networking study.",
    )
    complete_but_generic.canonical_id = "generic"
    complete_but_generic.authors = [Author(name="Grace Hopper")]
    complete_but_generic.publication_date = date(2026, 1, 1)
    complete_but_generic.venue = "Complete Metadata Journal"
    complete_but_generic.doi = "10.1234/generic"
    complete_but_generic.sources = ["openalex", "crossref"]

    ranked = rank_papers(
        "underwater acoustic TDOA localization",
        [complete_but_generic, relevant],
    )

    assert [item.canonical_id for item in ranked] == ["relevant", "generic"]


def test_tie_break_uses_year_then_title_then_canonical_id():
    query = "unmatched query"
    papers = [
        Paper(canonical_id="z", title="Beta", publication_date=date(2024, 1, 1)),
        Paper(canonical_id="b", title="Alpha", publication_date=date(2025, 1, 1)),
        Paper(canonical_id="a", title="Alpha", publication_date=date(2025, 1, 1)),
    ]

    ranked = rank_papers(query, papers)

    assert [item.canonical_id for item in ranked] == ["a", "b", "z"]


def test_ranking_is_input_order_independent_and_explainable():
    candidates = [
        Paper(canonical_id="generic", title="Generic Underwater Routing"),
        Paper(canonical_id="ofdm", title="Underwater Acoustic OFDM Communication"),
    ]

    forward = rank_papers("underwater acoustic OFDM communication", candidates)
    reverse = rank_papers("underwater acoustic OFDM communication", list(reversed(candidates)))

    assert [paper.canonical_id for paper in forward] == [paper.canonical_id for paper in reverse]
    assert forward[0].score_detail["rank_score"] == forward[0].score
    assert "relevance_components" in forward[0].score_detail
    assert "quality_components" in forward[0].score_detail
