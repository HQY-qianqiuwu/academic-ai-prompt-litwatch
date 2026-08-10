from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from litwatch.models import Paper
from litwatch.radars import ResearchRadar

TECHNICAL_TERMS = {
    "tdoa": "TDOA",
    "gcc-phat": "GCC-PHAT",
    "ofdm": "OFDM",
    "mimo": "MIMO",
    "auv": "AUV",
    "cnn": "CNN",
    "lstm": "LSTM",
    "yolo": "YOLO",
}
TECHNICAL_PATTERNS = {
    "TDOA": re.compile(r"(?<![a-z0-9])tdoa(?![a-z0-9])", re.IGNORECASE),
    "GCC-PHAT": re.compile(r"(?<![a-z0-9])gcc[-\s]phat(?![a-z0-9])", re.IGNORECASE),
    "OFDM": re.compile(r"(?<![a-z0-9])ofdm(?![a-z0-9])", re.IGNORECASE),
    "MIMO": re.compile(r"(?<![a-z0-9])mimo(?![a-z0-9])", re.IGNORECASE),
    "AUV": re.compile(r"(?<![a-z0-9])auv(?:s)?(?![a-z0-9])", re.IGNORECASE),
    "CNN": re.compile(r"(?<![a-z0-9])cnn(?:s)?(?![a-z0-9])", re.IGNORECASE),
    "LSTM": re.compile(r"(?<![a-z0-9])lstm(?:s)?(?![a-z0-9])", re.IGNORECASE),
    "YOLO": re.compile(r"(?<![a-z0-9])yolo(?![a-z0-9])", re.IGNORECASE),
}
MULTIWORD_PHRASES = (
    "deep learning",
    "neural network",
    "underwater localization",
    "target localization",
    "time delay estimation",
    "receiver geometry",
    "cross correlation",
    "cooperative localization",
    "distributed localization",
    "robust estimation",
    "noise suppression",
    "sensor array",
    "synchronization-free",
)
STOPWORDS = {
    "about",
    "acoustic",
    "also",
    "analysis",
    "and",
    "approach",
    "are",
    "based",
    "been",
    "between",
    "can",
    "data",
    "different",
    "each",
    "for",
    "from",
    "has",
    "have",
    "its",
    "into",
    "method",
    "model",
    "more",
    "not",
    "paper",
    "proposed",
    "result",
    "results",
    "such",
    "study",
    "system",
    "that",
    "the",
    "their",
    "these",
    "this",
    "through",
    "underwater",
    "use",
    "using",
    "was",
    "were",
    "which",
    "with",
}
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")


class AnnualStatistic(BaseModel):
    year: int
    count: int = Field(ge=0)


class KeywordStatistic(BaseModel):
    phrase: str
    count: int = Field(ge=1)
    canonical_ids: list[str] = Field(min_length=1)
    sources: list[str] = Field(default_factory=list)


class KeywordPeriod(BaseModel):
    start_year: int
    end_year: int
    paper_count: int = Field(ge=0)
    keywords: list[KeywordStatistic] = Field(default_factory=list)


class TrendClassification(StrEnum):
    EMERGING = "emerging"
    HOT = "hot"
    SUSTAINED = "sustained"
    DECLINING = "declining"


class TrendStatistic(BaseModel):
    phrase: str
    classification: TrendClassification
    hotness_score: float = Field(ge=0.0, le=1.0)
    components: dict[str, float]
    recent_count: int = Field(ge=0)
    historical_count: int = Field(ge=0)
    recent_annual_rate: float = Field(ge=0.0)
    baseline_annual_rate: float = Field(ge=0.0)
    growth_percent: float | None = None
    sources: list[str] = Field(default_factory=list)
    canonical_ids: list[str] = Field(min_length=1)


class RepresentativePaper(BaseModel):
    canonical_id: str
    title: str
    publication_year: int | None = None
    venue: str = ""
    doi: str = ""
    url: str = ""
    sources: list[str] = Field(default_factory=list)
    representative_score: float = Field(ge=0.0, le=1.0)


class TimelinePeriod(BaseModel):
    start_year: int
    end_year: int
    keywords: list[str] = Field(default_factory=list)
    representative_canonical_ids: list[str] = Field(default_factory=list)


class RadarAnalysisSnapshot(BaseModel):
    annual_counts: list[AnnualStatistic] = Field(default_factory=list)
    partial_current_year: bool = False
    keywords: list[KeywordStatistic] = Field(default_factory=list)
    periods: list[KeywordPeriod] = Field(default_factory=list)
    trends: list[TrendStatistic] = Field(default_factory=list)
    timeline: list[TimelinePeriod] = Field(default_factory=list)
    representative_papers: list[RepresentativePaper] = Field(default_factory=list)


class RadarAnalysisService:
    """Evidence-only annual and keyword aggregation without LLM inference."""

    def __init__(self, *, current_date: Callable[[], date] | None = None) -> None:
        self.current_date = current_date or (lambda: datetime.now(UTC).date())

    def analyze(
        self, radar: ResearchRadar, papers: Iterable[Paper]
    ) -> RadarAnalysisSnapshot:
        relevant = sorted(
            (
                paper.model_copy(deep=True)
                for paper in papers
                if paper.publication_date
                and radar.start_year <= paper.publication_date.year <= radar.end_year
            ),
            key=lambda paper: (paper.publication_date, paper.canonical_id.casefold()),
        )
        annual = [
            AnnualStatistic(
                year=year,
                count=sum(
                    paper.publication_date is not None
                    and paper.publication_date.year == year
                    for paper in relevant
                ),
            )
            for year in range(radar.start_year, radar.end_year + 1)
        ]
        periods = [
            self._period(start_year, end_year, relevant, radar)
            for start_year, end_year in self._period_ranges(
                radar.start_year, radar.end_year
            )
        ]
        all_keywords = self.extract_keywords(relevant, radar=radar, limit=100)
        representative = self.select_representative_papers(
            radar, relevant, all_keywords, limit=8
        )
        return RadarAnalysisSnapshot(
            annual_counts=annual,
            partial_current_year=radar.end_year == self.current_date().year,
            keywords=all_keywords[:20],
            periods=periods,
            trends=self._trends(radar, relevant, all_keywords),
            timeline=self._timeline(radar, relevant, periods),
            representative_papers=representative,
        )

    def extract_keywords(
        self,
        papers: Iterable[Paper],
        *,
        radar: ResearchRadar,
        limit: int = 12,
    ) -> list[KeywordStatistic]:
        evidence: dict[str, set[str]] = defaultdict(set)
        sources: dict[str, set[str]] = defaultdict(set)
        configured_phrases = tuple(
            dict.fromkeys(
                item.casefold()
                for item in radar.keywords
                if item and item.casefold() not in STOPWORDS
            )
        )
        excluded = {item.casefold() for item in radar.exclude_keywords}

        for paper in papers:
            text = self._paper_text(paper)
            normalized = self._normalize_text(text)
            phrases: set[str] = set()
            for display, pattern in TECHNICAL_PATTERNS.items():
                if pattern.search(normalized):
                    phrases.add(display)
            for phrase in (*MULTIWORD_PHRASES, *configured_phrases):
                if phrase in normalized and phrase not in excluded:
                    phrases.add(TECHNICAL_TERMS.get(phrase, phrase))
            for token in TOKEN_PATTERN.findall(normalized):
                folded = token.casefold()
                display = TECHNICAL_TERMS.get(folded, folded)
                if folded in STOPWORDS or folded in excluded or display in phrases:
                    continue
                phrases.add(display)
            for phrase in phrases:
                evidence[phrase].add(paper.canonical_id)
                sources[phrase].update(paper.sources)

        ordered = sorted(
            evidence,
            key=lambda phrase: (-len(evidence[phrase]), phrase.casefold()),
        )
        return [
            KeywordStatistic(
                phrase=phrase,
                count=len(evidence[phrase]),
                canonical_ids=sorted(evidence[phrase], key=str.casefold),
                sources=sorted(sources[phrase], key=str.casefold),
            )
            for phrase in ordered[:limit]
        ]

    def _period(
        self,
        start_year: int,
        end_year: int,
        papers: list[Paper],
        radar: ResearchRadar,
    ) -> KeywordPeriod:
        period_papers = [
            paper
            for paper in papers
            if paper.publication_date
            and start_year <= paper.publication_date.year <= end_year
        ]
        return KeywordPeriod(
            start_year=start_year,
            end_year=end_year,
            paper_count=len(period_papers),
            keywords=self.extract_keywords(period_papers, radar=radar, limit=8),
        )

    def _trends(
        self,
        radar: ResearchRadar,
        papers: list[Paper],
        keywords: list[KeywordStatistic],
    ) -> list[TrendStatistic]:
        recent_start = radar.end_year - radar.recent_window_years + 1
        recent_year_exposure = self._recent_year_exposure(radar)
        baseline_years = max(0, recent_start - radar.start_year)
        paper_by_id = {paper.canonical_id: paper for paper in papers}
        raw_counts: dict[str, tuple[int, int]] = {}
        for keyword in keywords:
            evidence = [paper_by_id[item] for item in keyword.canonical_ids if item in paper_by_id]
            recent_count = sum(
                paper.publication_date is not None
                and paper.publication_date.year >= recent_start
                for paper in evidence
            )
            raw_counts[keyword.phrase] = (
                recent_count,
                len(evidence) - recent_count,
            )
        max_recent = max((counts[0] for counts in raw_counts.values()), default=0)
        trends: list[TrendStatistic] = []
        for keyword in keywords:
            recent_count, historical_count = raw_counts[keyword.phrase]
            if recent_count + historical_count < 2:
                continue
            evidence = [paper_by_id[item] for item in keyword.canonical_ids if item in paper_by_id]
            recent_rate = recent_count / max(recent_year_exposure, 0.25)
            baseline_rate = (
                historical_count / baseline_years if baseline_years else 0.0
            )
            ratio = (
                recent_rate / baseline_rate
                if baseline_rate > 0
                else (float("inf") if recent_rate > 0 else 0.0)
            )
            classification = self._classification(
                recent_count=recent_count,
                historical_count=historical_count,
                recent_rate=recent_rate,
                baseline_rate=baseline_rate,
                ratio=ratio,
                partial_current_year=radar.end_year == self.current_date().year,
            )
            components = self._hotness_components(
                radar=radar,
                evidence=evidence,
                recent_count=recent_count,
                max_recent=max_recent,
                ratio=ratio,
                configured_provider_count=len(radar.providers),
            )
            score = round(
                0.35 * components["recent_volume"]
                + 0.30 * components["growth"]
                + 0.20 * components["recency"]
                + 0.15 * components["source_diversity"],
                6,
            )
            if classification is None and recent_count >= 2 and score >= 0.65:
                classification = TrendClassification.HOT
            if classification is None:
                continue
            trends.append(
                TrendStatistic(
                    phrase=keyword.phrase,
                    classification=classification,
                    hotness_score=score,
                    components=components,
                    recent_count=recent_count,
                    historical_count=historical_count,
                    recent_annual_rate=round(recent_rate, 6),
                    baseline_annual_rate=round(baseline_rate, 6),
                    growth_percent=(
                        None
                        if baseline_rate == 0
                        else round((ratio - 1.0) * 100.0, 2)
                    ),
                    sources=keyword.sources,
                    canonical_ids=keyword.canonical_ids,
                )
            )
        return sorted(
            trends,
            key=lambda item: (-item.hotness_score, item.phrase.casefold()),
        )

    @staticmethod
    def _classification(
        *,
        recent_count: int,
        historical_count: int,
        recent_rate: float,
        baseline_rate: float,
        ratio: float,
        partial_current_year: bool,
    ) -> TrendClassification | None:
        if historical_count <= 1 and recent_count >= 2 and recent_rate > baseline_rate:
            return TrendClassification.EMERGING
        minimum_recent = 1 if partial_current_year else 2
        sustained_ratio = ratio >= 0.75 if partial_current_year else 0.75 <= ratio <= 1.5
        if historical_count >= 2 and recent_count >= minimum_recent and sustained_ratio:
            return TrendClassification.SUSTAINED
        if historical_count >= 2 and ratio < 0.75:
            return TrendClassification.DECLINING
        if recent_count >= 2 and recent_rate > baseline_rate:
            return TrendClassification.HOT
        return None

    def _hotness_components(
        self,
        *,
        radar: ResearchRadar,
        evidence: list[Paper],
        recent_count: int,
        max_recent: int,
        ratio: float,
        configured_provider_count: int,
    ) -> dict[str, float]:
        recent_volume = recent_count / max_recent if max_recent else 0.0
        if math.isinf(ratio):
            growth = 1.0
        else:
            growth_delta = min(3.0, max(-1.0, ratio - 1.0))
            growth = (growth_delta + 1.0) / 4.0
        range_width = max(1, radar.end_year - radar.start_year)
        years = [
            paper.publication_date.year
            for paper in evidence
            if paper.publication_date is not None
        ]
        recency = (
            sum((year - radar.start_year) / range_width for year in years) / len(years)
            if years
            else 0.0
        )
        evidence_sources = {
            source for paper in evidence for source in paper.sources
        }
        source_diversity = len(evidence_sources) / max(1, configured_provider_count)
        return {
            "recent_volume": round(min(1.0, max(0.0, recent_volume)), 6),
            "growth": round(min(1.0, max(0.0, growth)), 6),
            "recency": round(min(1.0, max(0.0, recency)), 6),
            "source_diversity": round(
                min(1.0, max(0.0, source_diversity)), 6
            ),
        }

    def _recent_year_exposure(self, radar: ResearchRadar) -> float:
        exposure = float(radar.recent_window_years)
        today = self.current_date()
        if radar.end_year != today.year:
            return exposure
        year_start = date(today.year, 1, 1)
        next_year = date(today.year + 1, 1, 1)
        elapsed = (today - year_start).days + 1
        progress = elapsed / (next_year - year_start).days
        return max(0.25, exposure - 1.0 + progress)

    def select_representative_papers(
        self,
        radar: ResearchRadar,
        papers: Iterable[Paper],
        keywords: list[KeywordStatistic],
        *,
        limit: int,
    ) -> list[RepresentativePaper]:
        top_keywords = keywords[:10]
        keyword_evidence = {
            keyword.phrase: set(keyword.canonical_ids) for keyword in top_keywords
        }
        scored: list[RepresentativePaper] = []
        for paper in papers:
            relevance = self._paper_score(paper, "relevance_score", paper.score)
            metadata_quality = self._paper_score(
                paper, "quality_score", self._metadata_quality(paper)
            )
            represented = sum(
                paper.canonical_id in evidence
                for evidence in keyword_evidence.values()
            )
            phrase_representativeness = represented / max(1, len(keyword_evidence))
            source_diversity = len(set(paper.sources)) / max(1, len(radar.providers))
            score = round(
                0.45 * relevance
                + 0.25 * metadata_quality
                + 0.20 * phrase_representativeness
                + 0.10 * min(1.0, source_diversity),
                6,
            )
            scored.append(
                RepresentativePaper(
                    canonical_id=paper.canonical_id,
                    title=paper.title,
                    publication_year=(
                        paper.publication_date.year if paper.publication_date else None
                    ),
                    venue=paper.venue,
                    doi=paper.doi,
                    url=paper.url,
                    sources=sorted(set(paper.sources), key=str.casefold),
                    representative_score=score,
                )
            )
        return sorted(
            scored,
            key=lambda item: (
                -item.representative_score,
                -(item.publication_year or 0),
                item.canonical_id.casefold(),
            ),
        )[:limit]

    def _timeline(
        self,
        radar: ResearchRadar,
        papers: list[Paper],
        periods: list[KeywordPeriod],
    ) -> list[TimelinePeriod]:
        timeline: list[TimelinePeriod] = []
        for period in periods:
            period_papers = [
                paper
                for paper in papers
                if paper.publication_date
                and period.start_year <= paper.publication_date.year <= period.end_year
            ]
            representative = self.select_representative_papers(
                radar, period_papers, period.keywords, limit=3
            )
            timeline.append(
                TimelinePeriod(
                    start_year=period.start_year,
                    end_year=period.end_year,
                    keywords=[keyword.phrase for keyword in period.keywords[:5]],
                    representative_canonical_ids=[
                        paper.canonical_id for paper in representative
                    ],
                )
            )
        return timeline

    @staticmethod
    def _paper_score(paper: Paper, name: str, fallback: float) -> float:
        value = paper.score_detail.get(name)
        score = float(value) if isinstance(value, int | float) else float(fallback)
        return min(1.0, max(0.0, score))

    @staticmethod
    def _metadata_quality(paper: Paper) -> float:
        signals = (
            bool(paper.title),
            bool(paper.abstract),
            bool(paper.authors),
            paper.publication_date is not None,
            bool(paper.venue),
            bool(paper.doi or paper.url),
        )
        return sum(signals) / len(signals)

    @staticmethod
    def _period_ranges(start_year: int, end_year: int) -> list[tuple[int, int]]:
        year_count = end_year - start_year + 1
        window_count = min(4, year_count)
        width = math.ceil(year_count / window_count)
        ranges: list[tuple[int, int]] = []
        cursor = start_year
        while cursor <= end_year:
            period_end = min(cursor + width - 1, end_year)
            ranges.append((cursor, period_end))
            cursor = period_end + 1
        return ranges

    @staticmethod
    def _paper_text(paper: Paper) -> str:
        return f"{paper.title}\n{paper.abstract}"

    @staticmethod
    def _normalize_text(text: str) -> str:
        return (
            text.casefold()
            .replace("–", "-")
            .replace("—", "-")
            .replace("_", " ")
        )
