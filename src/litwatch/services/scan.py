"""Provider-independent scan outcome shared by interactive and scheduled callers."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

from litwatch.models import Paper
from litwatch.services.literature_search import (
    AllProvidersFailedError,
    LiteratureSearchDiagnostics,
    LiteratureSearchResult,
    LiteratureSearchService,
    ProviderExecutionStatus,
    ProviderSearchStatus,
)


class ScanStatus(StrEnum):
    SUCCESS = "success"
    SUCCESS_EMPTY = "success_empty"
    PARTIAL_SUCCESS = "partial_success"
    ALL_PROVIDERS_FAILED = "all_providers_failed"


_WORKING = {ProviderExecutionStatus.SUCCESS, ProviderExecutionStatus.EMPTY}
_SKIPPED = {ProviderExecutionStatus.SKIPPED_UNCONFIGURED}


class ScanResult(BaseModel):
    query: str
    status: ScanStatus
    papers: list[Paper] = Field(default_factory=list)
    provider_status: list[ProviderSearchStatus] = Field(default_factory=list)
    diagnostics: LiteratureSearchDiagnostics = Field(default_factory=LiteratureSearchDiagnostics)

    @computed_field
    @property
    def fetched(self) -> int:
        return self.diagnostics.raw_count

    @computed_field
    @property
    def deduplicated(self) -> int:
        return self.diagnostics.dedup_count

    @computed_field
    @property
    def selected(self) -> int:
        return len(self.papers)

    @computed_field
    @property
    def provider_success_count(self) -> int:
        return sum(item.status in _WORKING for item in self.provider_status)

    @property
    def all_timeouts(self) -> bool:
        attempted = [
            item for item in self.provider_status if item.status not in _SKIPPED
        ]
        return bool(attempted) and all(
            item.status is ProviderExecutionStatus.TIMEOUT for item in attempted
        )

    @classmethod
    def from_search(cls, result: LiteratureSearchResult) -> ScanResult:
        working = sum(item.status in _WORKING for item in result.provider_status)
        failed = sum(
            item.status not in _WORKING | _SKIPPED for item in result.provider_status
        )
        if failed and not working:
            status = ScanStatus.ALL_PROVIDERS_FAILED
        elif failed:
            status = ScanStatus.PARTIAL_SUCCESS
        elif result.papers:
            status = ScanStatus.SUCCESS
        else:
            status = ScanStatus.SUCCESS_EMPTY
        return cls(
            query=result.query,
            status=status,
            papers=result.papers,
            provider_status=result.provider_status,
            diagnostics=result.diagnostics,
        )


class ScanService:
    """Orchestrate a scan without owning persistence, analysis or delivery."""

    def __init__(self, literature_search_service: LiteratureSearchService) -> None:
        self.literature_search_service = literature_search_service

    def scan(
        self,
        *,
        topic: str,
        limit: int,
        providers: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> ScanResult:
        arguments: dict[str, object] = {"topic": topic, "limit": limit}
        if providers is not None:
            arguments["providers"] = providers
        if start_date is not None:
            arguments["start_date"] = start_date
        if end_date is not None:
            arguments["end_date"] = end_date
        try:
            result = self.literature_search_service.search(**arguments)
        except AllProvidersFailedError as error:
            return ScanResult(
                query=topic.strip(),
                status=ScanStatus.ALL_PROVIDERS_FAILED,
                provider_status=error.provider_status,
            )
        return ScanResult.from_search(result)
