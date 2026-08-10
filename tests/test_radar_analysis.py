from __future__ import annotations

from datetime import UTC, date, datetime

from litwatch.models import Paper
from litwatch.radars import ResearchRadar
from litwatch.services.radar_analysis import RadarAnalysisService


def radar(**overrides: object) -> ResearchRadar:
    payload: dict[str, object] = {
        "id": "radar",
        "name": "TDOA Evolution",
        "topic": "underwater acoustic TDOA localization",
        "keywords": ["time delay estimation"],
        "exclude_keywords": [],
        "providers": ["openalex", "arxiv", "crossref"],
        "start_year": 2019,
        "end_year": 2026,
        "recent_window_years": 2,
        "search_limit_per_period": 30,
        "enabled": True,
        "created_at": datetime(2026, 8, 10, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 10, tzinfo=UTC),
    }
    payload.update(overrides)
    return ResearchRadar.model_validate(payload)


def paper(identifier: str, year: int, title: str, abstract: str = "") -> Paper:
    return Paper(
        canonical_id=f"doi:10.1000/{identifier}",
        title=title,
        abstract=abstract,
        publication_date=date(year, 6, 1),
        sources=["openalex"],
    )


def test_annual_statistics_include_zero_years_and_real_counts():
    papers = [
        paper("a", 2019, "TDOA A"),
        paper("b", 2019, "TDOA B"),
        paper("c", 2021, "TDOA C"),
        paper("d", 2021, "TDOA D"),
        paper("e", 2021, "TDOA E"),
    ]
    service = RadarAnalysisService(current_date=lambda: date(2026, 8, 10))

    snapshot = service.analyze(radar(start_year=2019, end_year=2021), papers)

    assert [(item.year, item.count) for item in snapshot.annual_counts] == [
        (2019, 2),
        (2020, 0),
        (2021, 3),
    ]
    assert snapshot.partial_current_year is False


def test_technical_terms_and_multiword_phrases_are_preserved():
    source = paper(
        "technical",
        2026,
        "GCC-PHAT TDOA for AUV localization with MIMO OFDM",
        "A CNN and LSTM neural network extends YOLO with deep learning, "
        "receiver geometry, synchronization-free time delay estimation.",
    )
    keywords = RadarAnalysisService(current_date=lambda: date(2026, 8, 10)).extract_keywords(
        [source], radar=radar(), limit=30
    )
    phrases = {item.phrase for item in keywords}

    assert {
        "GCC-PHAT",
        "TDOA",
        "AUV",
        "MIMO",
        "OFDM",
        "CNN",
        "LSTM",
        "YOLO",
        "deep learning",
        "neural network",
        "receiver geometry",
        "synchronization-free",
        "time delay estimation",
    } <= phrases
    assert "gcc" not in phrases
    assert "phat" not in phrases


def test_stopwords_and_domain_neutral_terms_do_not_dominate():
    source = paper(
        "generic",
        2025,
        "A paper based on the underwater acoustic study method",
        "This analysis method and results are for an acoustic system.",
    )
    keywords = RadarAnalysisService().extract_keywords(
        [source], radar=radar(), limit=30
    )

    assert {
        "paper",
        "based",
        "underwater",
        "acoustic",
        "study",
        "method",
        "analysis",
        "results",
        "using",
        "system",
        "and",
        "are",
        "for",
        "the",
    }.isdisjoint(item.phrase for item in keywords)


def test_keyword_evolution_uses_chronological_evidence_windows():
    papers = [
        paper("old-a", 2019, "GCC-PHAT cross correlation TDOA"),
        paper("old-b", 2020, "Cross correlation time delay estimation"),
        paper("new-a", 2025, "Deep learning neural network localization"),
        paper("new-b", 2026, "Synchronization-free neural network TDOA"),
    ]
    snapshot = RadarAnalysisService(current_date=lambda: date(2026, 8, 10)).analyze(
        radar(), papers
    )

    early = {item.phrase for item in snapshot.periods[0].keywords}
    recent = {item.phrase for item in snapshot.periods[-1].keywords}
    assert {"GCC-PHAT", "cross correlation"} <= early
    assert {"deep learning", "neural network", "synchronization-free"} <= recent
    assert all(item.canonical_ids for period in snapshot.periods for item in period.keywords)


def test_keyword_analysis_is_deterministic():
    papers = [
        paper("b", 2025, "Neural network TDOA"),
        paper("a", 2025, "Neural network TDOA"),
    ]
    service = RadarAnalysisService(current_date=lambda: date(2026, 8, 10))

    first = service.analyze(radar(), papers)
    second = service.analyze(radar(), reversed(papers))

    assert first == second


def test_trend_classification_detects_emerging_sustained_and_declining_phrases():
    papers = [
        paper("old-gcc-1", 2019, "GCC-PHAT cross correlation TDOA"),
        paper("old-gcc-2", 2020, "GCC-PHAT cross correlation TDOA"),
        paper("old-gcc-3", 2021, "GCC-PHAT TDOA"),
        paper("old-tdoa", 2022, "TDOA localization"),
        paper("new-deep-1", 2025, "Deep learning neural network TDOA"),
        paper("new-deep-2", 2026, "Deep learning neural network TDOA"),
        paper("new-deep-3", 2026, "Deep learning neural network TDOA"),
        paper("new-sync-1", 2025, "Synchronization-free TDOA"),
        paper("new-sync-2", 2026, "Synchronization-free TDOA"),
        paper("new-sync-3", 2026, "Synchronization-free TDOA"),
    ]
    snapshot = RadarAnalysisService(
        current_date=lambda: date(2026, 8, 10)
    ).analyze(radar(), papers)
    classes = {trend.phrase: trend.classification.value for trend in snapshot.trends}

    assert classes["deep learning"] == "emerging"
    assert classes["neural network"] == "emerging"
    assert classes["synchronization-free"] == "emerging"
    assert "TDOA" not in classes
    assert classes["GCC-PHAT"] == "declining"


def test_academic_boilerplate_is_rejected_from_keywords_and_trends():
    papers = [
        paper(
            f"generic-{index}",
            2026,
            "This paper proposes a better high performance method",
            "We demonstrate multiple applications; however two results are used.",
        )
        for index in range(3)
    ]
    snapshot = RadarAnalysisService(
        current_date=lambda: date(2026, 8, 10)
    ).analyze(radar(), papers)
    rejected = {
        "demonstrate",
        "propose",
        "proposes",
        "used",
        "however",
        "two",
        "better",
        "high",
        "multiple",
        "application",
        "performance",
    }

    assert rejected.isdisjoint(item.phrase for item in snapshot.keywords)
    assert rejected.isdisjoint(item.phrase for item in snapshot.trends)


def test_phrase_first_extraction_keeps_research_concepts_and_acronyms():
    source = paper(
        "concepts",
        2026,
        "Robust multipath localization with receiver geometry optimization",
        "Synchronization-free localization uses deep learning and neural network "
        "time delay estimation for a hydrophone array and sensor networks. "
        "GCC-PHAT TDOA supports OFDM MIMO AUV LSTM YOLO.",
    )

    phrases = {
        item.phrase
        for item in RadarAnalysisService().extract_keywords(
            [source], radar=radar(), limit=100
        )
    }

    assert {
        "robust multipath localization",
        "receiver geometry optimization",
        "synchronization-free localization",
        "deep learning",
        "neural network",
        "time delay estimation",
        "hydrophone array",
        "sensor network",
        "GCC-PHAT",
        "TDOA",
        "OFDM",
        "MIMO",
        "AUV",
        "LSTM",
        "YOLO",
    } <= phrases


def test_tdoa_expansion_and_acronym_do_not_form_a_redundant_concept():
    source = paper(
        "tdoa-alias",
        2026,
        "Time-difference-of-arrival (TDOA) localization and TDOA measurement",
    )

    phrases = {
        item.phrase
        for item in RadarAnalysisService().extract_keywords(
            [source], radar=radar(), limit=100
        )
    }

    assert "TDOA" in phrases
    assert "TDOA localization" in phrases
    assert "TDOA measurement" in phrases
    assert not any("TDOA TDOA" in phrase for phrase in phrases)
    assert not any("time-difference-of-arrival" in phrase for phrase in phrases)


def test_concept_count_is_distinct_document_frequency_not_occurrence_count():
    repeated = paper(
        "repeat",
        2026,
        "Neural network localization",
        "Neural network neural network neural network localization.",
    )
    another = paper("another", 2026, "Neural networks for localization")

    keywords = RadarAnalysisService().extract_keywords(
        [repeated, another], radar=radar(), limit=100
    )
    neural_network = next(item for item in keywords if item.phrase == "neural network")

    assert neural_network.count == 2
    assert neural_network.canonical_ids == [
        "doi:10.1000/another",
        "doi:10.1000/repeat",
    ]


def test_safe_morphology_merges_network_and_environment_plural_forms():
    papers = [
        paper("singular", 2025, "Sensor network in a multipath environment"),
        paper("plural", 2026, "Sensor networks in multipath environments"),
    ]
    keywords = RadarAnalysisService().extract_keywords(
        papers, radar=radar(), limit=100
    )
    counts = {item.phrase: item.count for item in keywords}

    assert counts["sensor network"] == 2
    assert counts["multipath environment"] == 2


def test_topic_background_terms_remain_summary_only_not_hot_trends():
    papers = [
        paper(f"background-{index}", 2026, "Underwater acoustic TDOA localization")
        for index in range(3)
    ]
    snapshot = RadarAnalysisService(
        current_date=lambda: date(2026, 8, 10)
    ).analyze(radar(), papers)

    assert "TDOA" in {item.phrase for item in snapshot.keywords}
    assert "TDOA" not in {item.phrase for item in snapshot.trends}
    assert "underwater localization" not in {
        item.phrase for item in snapshot.trends
    }


def test_two_recent_documents_do_not_create_small_sample_trend():
    papers = [
        paper("small-1", 2025, "Synchronization-free localization"),
        paper("small-2", 2026, "Synchronization-free localization"),
    ]
    snapshot = RadarAnalysisService(
        current_date=lambda: date(2026, 8, 10)
    ).analyze(radar(), papers)

    assert "synchronization-free localization" not in {
        item.phrase for item in snapshot.trends
    }


def test_trend_evidence_contains_only_distinct_supporting_papers():
    papers = [
        paper(
            "support-1",
            2025,
            "Robust multipath localization",
            "Robust multipath localization appears repeatedly: multipath multipath.",
        ),
        paper("support-2", 2026, "Robust multipath localization"),
        paper("support-3", 2026, "Robust multipath localization"),
        paper("unrelated", 2026, "Neural network time delay estimation"),
    ]
    snapshot = RadarAnalysisService(
        current_date=lambda: date(2026, 8, 10)
    ).analyze(radar(), papers)
    trend = next(
        item for item in snapshot.trends if item.phrase == "robust multipath localization"
    )

    assert trend.canonical_ids == [
        "doi:10.1000/support-1",
        "doi:10.1000/support-2",
        "doi:10.1000/support-3",
    ]
    assert trend.recent_count == 3


def test_hotness_is_normalized_explainable_and_has_evidence():
    papers = [
        paper("old", 2020, "TDOA receiver geometry"),
        paper("new-1", 2025, "TDOA receiver geometry neural network"),
        paper("new-2", 2026, "TDOA receiver geometry neural network"),
    ]
    snapshot = RadarAnalysisService(
        current_date=lambda: date(2026, 8, 10)
    ).analyze(radar(), papers)

    for trend in snapshot.trends:
        assert 0 <= trend.hotness_score <= 1
        assert set(trend.components) == {
            "recent_volume",
            "growth",
            "recency",
            "source_diversity",
        }
        assert trend.canonical_ids


def test_partial_current_year_exposure_avoids_false_decline():
    partial_radar = radar(
        start_year=2022,
        end_year=2026,
        recent_window_years=1,
    )
    papers = [
        paper("old-1", 2022, "TDOA receiver geometry"),
        paper("old-2", 2023, "TDOA receiver geometry"),
        paper("old-3", 2024, "TDOA receiver geometry"),
        paper("old-4", 2025, "TDOA receiver geometry"),
        paper("current", 2026, "TDOA receiver geometry"),
    ]
    snapshot = RadarAnalysisService(
        current_date=lambda: date(2026, 2, 1)
    ).analyze(partial_radar, papers)
    receiver_geometry = next(
        trend for trend in snapshot.trends if trend.phrase == "receiver geometry"
    )

    assert snapshot.partial_current_year is True
    assert receiver_geometry.classification.value != "declining"
    assert receiver_geometry.recent_annual_rate > receiver_geometry.baseline_annual_rate


def test_representative_paper_selection_is_deterministic_and_not_newest_only():
    older = paper("older", 2022, "TDOA receiver geometry GCC-PHAT")
    older.score = 0.95
    older.score_detail = {"relevance_score": 0.95, "quality_score": 0.95}
    newer = paper("newer", 2026, "TDOA localization")
    newer.score = 0.2
    newer.score_detail = {"relevance_score": 0.2, "quality_score": 0.4}
    service = RadarAnalysisService(current_date=lambda: date(2026, 8, 10))

    first = service.analyze(radar(), [newer, older])
    second = service.analyze(radar(), [older, newer])

    assert first.representative_papers == second.representative_papers
    assert first.representative_papers[0].canonical_id == older.canonical_id
    assert first.representative_papers[0].representative_score > (
        first.representative_papers[1].representative_score
    )


def test_timeline_uses_period_keywords_and_representative_evidence():
    papers = [
        paper("early", 2019, "GCC-PHAT cross correlation TDOA"),
        paper("recent", 2026, "Neural network synchronization-free TDOA"),
    ]
    snapshot = RadarAnalysisService(
        current_date=lambda: date(2026, 8, 10)
    ).analyze(radar(), papers)

    assert snapshot.timeline[0].keywords
    assert snapshot.timeline[0].representative_canonical_ids == [
        "doi:10.1000/early"
    ]
    assert snapshot.timeline[-1].representative_canonical_ids == [
        "doi:10.1000/recent"
    ]
    all_ids = {paper.canonical_id for paper in papers}
    assert all(
        set(period.representative_canonical_ids) <= all_ids
        for period in snapshot.timeline
    )
