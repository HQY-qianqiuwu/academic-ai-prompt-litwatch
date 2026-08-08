from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Self

from pydantic import BaseModel, computed_field

from litwatch.config import Settings, Topic
from litwatch.models import Paper
from litwatch.provider_config import (
    ProviderProfile,
    ProviderProfileStore,
    default_provider_profile,
)
from litwatch.sources.base import PaperSource
from litwatch.sources.registry import ProviderNotFoundError, ProviderRegistry

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
        source: PaperSource | None = None,
        *,
        registry: ProviderRegistry | None = None,
        profile_store: ProviderProfileStore | None = None,
        profile_id: str = "default",
        historical_start_date: date = DEFAULT_HISTORICAL_START_DATE,
        current_date: Callable[[], date] = _utc_today,
    ) -> None:
        if source is None and (registry is None or profile_store is None):
            raise ValueError("source or registry with profile_store is required")
        if source is not None and (registry is not None or profile_store is not None):
            raise ValueError("source and registry configuration are mutually exclusive")
        self.source = source
        self.registry = registry
        self.profile_store = profile_store
        self.profile_id = profile_id
        self.historical_start_date = historical_start_date
        self.current_date = current_date

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        profile_store = ProviderProfileStore(
            [default_provider_profile(openalex_base_url=settings.openalex_base_url)]
        )
        return cls(
            registry=ProviderRegistry.from_settings(settings),
            profile_store=profile_store,
        )

    def _selected_sources(self, providers: list[str] | None) -> list[PaperSource]:
        if self.source is not None:
            if providers is not None and providers != [self.source.name]:
                raise ProviderNotFoundError("injected source does not match provider selection")
            return [self.source]

        if self.registry is None or self.profile_store is None:  # pragma: no cover - invariant
            raise RuntimeError("provider registry is not configured")

        profile: ProviderProfile = self.profile_store.get(self.profile_id)
        if providers is None:
            provider_configs = [provider for provider in profile.providers if provider.enabled]
        else:
            if not providers:
                raise ProviderNotFoundError("at least one provider must be selected")
            if len(providers) != len(set(providers)):
                raise ProviderNotFoundError("provider selection must not contain duplicates")
            try:
                provider_configs = [profile.provider(provider_id) for provider_id in providers]
            except KeyError as error:
                raise ProviderNotFoundError(
                    f"provider {error.args[0]!r} is not in profile {profile.profile_id!r}"
                ) from None

        if not provider_configs:
            raise ProviderNotFoundError(f"profile {profile.profile_id!r} has no enabled providers")
        return [self.registry.build(config) for config in provider_configs]

    def search(
        self,
        *,
        topic: str,
        limit: int,
        providers: list[str] | None = None,
    ) -> LiteratureSearchResult:
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
        provider_papers: list[Paper] = []
        for source in self._selected_sources(providers):
            provider_papers.extend(
                source.search(
                    provider_topic,
                    self.historical_start_date,
                    end_date,
                    limit,
                )
            )
        papers = provider_papers[:limit]
        if any(not isinstance(paper, Paper) for paper in papers):
            raise TypeError("literature sources must return Paper instances")

        return LiteratureSearchResult(query=normalized_topic, papers=papers)
