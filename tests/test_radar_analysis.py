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
    service = RadarAnalysisService(current_year=lambda: 2026)

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
    keywords = RadarAnalysisService(current_year=lambda: 2026).extract_keywords(
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
        "A paper based on underwater acoustic study method",
        "This analysis method reports results using an acoustic system.",
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
    }.isdisjoint(item.phrase for item in keywords)


def test_keyword_evolution_uses_chronological_evidence_windows():
    papers = [
        paper("old-a", 2019, "GCC-PHAT cross correlation TDOA"),
        paper("old-b", 2020, "Cross correlation time delay estimation"),
        paper("new-a", 2025, "Deep learning neural network localization"),
        paper("new-b", 2026, "Synchronization-free neural network TDOA"),
    ]
    snapshot = RadarAnalysisService(current_year=lambda: 2026).analyze(radar(), papers)

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
    service = RadarAnalysisService(current_year=lambda: 2026)

    first = service.analyze(radar(), papers)
    second = service.analyze(radar(), reversed(papers))

    assert first == second
