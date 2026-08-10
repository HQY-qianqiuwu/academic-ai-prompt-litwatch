from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

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
    "analysis",
    "approach",
    "based",
    "between",
    "data",
    "from",
    "into",
    "method",
    "model",
    "paper",
    "proposed",
    "result",
    "results",
    "study",
    "system",
    "that",
    "their",
    "this",
    "underwater",
    "using",
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


class RadarAnalysisSnapshot(BaseModel):
    annual_counts: list[AnnualStatistic] = Field(default_factory=list)
    partial_current_year: bool = False
    keywords: list[KeywordStatistic] = Field(default_factory=list)
    periods: list[KeywordPeriod] = Field(default_factory=list)
    trends: list[dict[str, object]] = Field(default_factory=list)
    timeline: list[dict[str, object]] = Field(default_factory=list)
    representative_papers: list[dict[str, object]] = Field(default_factory=list)


class RadarAnalysisService:
    """Evidence-only annual and keyword aggregation without LLM inference."""

    def __init__(self, *, current_year: Callable[[], int] | None = None) -> None:
        self.current_year = current_year or (lambda: datetime.now(UTC).year)

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
        return RadarAnalysisSnapshot(
            annual_counts=annual,
            partial_current_year=radar.end_year == self.current_year(),
            keywords=self.extract_keywords(relevant, radar=radar, limit=20),
            periods=periods,
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
