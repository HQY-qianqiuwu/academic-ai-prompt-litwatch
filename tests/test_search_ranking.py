from __future__ import annotations

from litwatch.models import Paper
from litwatch.services.search_ranking import relevance_score, tokenize


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
