from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Self

from pydantic import BaseModel, computed_field

from litwatch.config import Settings, Topic
from litwatch.models import Paper
from litwatch.sources.base import PaperSource
from litwatch.sources.openalex import OpenAlexSource

# The v1.1 request contract has no date fields. Use a broad historical lower bound while keeping
# the upper bound tied to the current date. Both values are injectable so a later API revision can
# expose an explicit date range without changing the provider or relying on a future hard-coded date.
DEFAULT_HISTORICAL_START_DATE = date(1900, 1, 1)


def _utc_today() -> date:
    return datetime.now(UTC).date()


class LiteratureSearchResult(BaseModel):
    query: str
    papers: list[Paper]

    @computed_field
    @property
    def paper_count(self) -> int:
        return len(self.papers)


class LiteratureSearchService:
    def __init__(
        self,
        source: PaperSource,
        *,
        historical_start_date: date = DEFAULT_HISTORICAL_START_DATE,
        current_date: Callable[[], date] = _utc_today,
    ) -> None:
        self.source = source
        self.historical_start_date = historical_start_date
        self.current_date = current_date

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            OpenAlexSource(
                email=settings.openalex_email,
                timeout=settings.request_timeout_seconds,
            )
        )

    def search(self, *, topic: str, limit: int) -> LiteratureSearchResult:
        normalized_topic = topic.strip()
        if not normalized_topic:
            raise ValueError("topic must not be blank")
        if isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")

        end_date = self.current_date()
        if self.historical_start_date > end_date:
            raise ValueError("historical_start_date must not be after the current date")

        provider_topic = Topic(
            id="literature_search",
            name=normalized_topic,
            query=normalized_topic,
            min_score=0,
        )
        provider_papers = self.source.search(
            provider_topic,
            self.historical_start_date,
            end_date,
            limit,
        )
        papers = provider_papers[:limit]
        if any(not isinstance(paper, Paper) for paper in papers):
            raise TypeError("literature sources must return Paper instances")

        return LiteratureSearchResult(query=normalized_topic, papers=papers)
