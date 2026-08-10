from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel, Field

from litwatch.provider_config import ProviderProfileStore
from litwatch.radar_repository import RadarRepository
from litwatch.radars import RadarScan, RadarScanStatus, RadarSpec, ResearchRadar
from litwatch.services.deduplication import deduplicate_papers
from litwatch.services.literature_search import (
    AllProvidersFailedError,
    LiteratureSearchService,
    ProviderExecutionStatus,
    ProviderSearchStatus,
)
from litwatch.services.radar_analysis import RadarAnalysisService
from litwatch.sources.registry import ProviderRegistry


class RadarNotFoundError(LookupError):
    pass


class RadarProviderError(ValueError):
    pass


class RadarYearRangeError(ValueError):
    pass


class RadarScanAlreadyActiveError(RuntimeError):
    pass


class RadarScanUnavailableError(RuntimeError):
    pass


class RadarScanResult(BaseModel):
    scan: RadarScan
    new_canonical_ids: list[str] = Field(default_factory=list)
    seen_canonical_ids: list[str] = Field(default_factory=list)


FILTERING_MODES = {
    "openalex": "provider_side",
    "crossref": "provider_side",
    "semantic_scholar": "provider_side",
    "arxiv": "provider_side_with_post_validation",
}
FAILED_PROVIDER_STATUSES = {
    ProviderExecutionStatus.TIMEOUT,
    ProviderExecutionStatus.RATE_LIMITED,
    ProviderExecutionStatus.AUTH_ERROR,
    ProviderExecutionStatus.UPSTREAM_ERROR,
    ProviderExecutionStatus.PARSE_ERROR,
}


class ResearchRadarService:
    """Validated Radar CRUD and bounded historical backfill orchestration."""

    def __init__(
        self,
        repository: RadarRepository,
        provider_registry: ProviderRegistry,
        provider_profile_store: ProviderProfileStore,
        *,
        search_service: LiteratureSearchService | None = None,
        analysis_service: RadarAnalysisService | None = None,
        profile_id: str = "default",
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repository = repository
        self.provider_registry = provider_registry
        self.provider_profile_store = provider_profile_store
        self.search_service = search_service
        self.analysis_service = analysis_service or RadarAnalysisService(
            current_date=lambda: self._now().date()
        )
        self.profile_id = profile_id
        self.clock = clock or (lambda: datetime.now(UTC))
        self.id_factory = id_factory or (lambda: uuid4().hex)

    def create(self, spec: RadarSpec) -> ResearchRadar:
        self._validate_providers(spec.providers)
        now = self._now()
        self._validate_year_range(spec, current_year=now.year)
        radar = ResearchRadar(
            **spec.model_dump(),
            id=self.id_factory(),
            created_at=now,
            updated_at=now,
        )
        return self.repository.create(radar)

    def list(self) -> list[ResearchRadar]:
        return self.repository.list()

    def get(self, radar_id: str) -> ResearchRadar:
        radar = self.repository.get(radar_id)
        if radar is None:
            raise RadarNotFoundError(radar_id)
        return radar

    def update(self, radar_id: str, changes: Mapping[str, object]) -> ResearchRadar:
        current = self.get(radar_id)
        editable = {
            field_name: getattr(current, field_name) for field_name in RadarSpec.model_fields
        }
        editable.update(changes)
        spec = RadarSpec.model_validate(editable)
        self._validate_providers(spec.providers)
        now = self._now()
        self._validate_year_range(spec, current_year=now.year)
        updated = current.model_copy(
            update={**spec.model_dump(), "updated_at": now}, deep=True
        )
        return self.repository.update(ResearchRadar.model_validate(updated))

    def scan(self, radar_id: str) -> RadarScanResult:
        radar = self.get(radar_id)
        if not radar.enabled:
            raise RadarScanUnavailableError("Radar is disabled")
        if self.search_service is None:
            raise RadarScanUnavailableError("Literature search service is unavailable")
        started_at = self._now()
        scan = RadarScan(
            id=self.id_factory(),
            radar_id=radar.id,
            started_at=started_at,
            heartbeat_at=started_at,
            status=RadarScanStatus.RUNNING,
            start_year=radar.start_year,
            end_year=radar.end_year,
        )
        try:
            self.repository.create_scan(scan)
        except sqlite3.IntegrityError as error:
            raise RadarScanAlreadyActiveError(radar.id) from error

        candidates = []
        safe_statuses: list[dict[str, object]] = []
        raw_count = 0
        any_period_succeeded = False
        any_provider_failed = False
        for period_start, period_end in self._periods(radar.start_year, radar.end_year):
            scan.heartbeat_at = self._now()
            self.repository.update_scan(scan)
            try:
                result = self.search_service.search(
                    topic=radar.topic,
                    limit=radar.search_limit_per_period,
                    providers=radar.providers,
                    start_date=date(period_start, 1, 1),
                    end_date=date(period_end, 12, 31),
                )
            except AllProvidersFailedError as error:
                any_provider_failed = True
                safe_statuses.extend(
                    self._period_statuses(error.provider_status, period_start, period_end)
                )
                continue
            except Exception:  # noqa: BLE001 - persist a safe scan failure only
                return self._finish_failed(scan, safe_statuses, "scan_failed")

            any_period_succeeded = True
            raw_count += result.diagnostics.raw_count
            candidates.extend(result.papers)
            safe_statuses.extend(
                self._period_statuses(result.provider_status, period_start, period_end)
            )
            if any(item.status in FAILED_PROVIDER_STATUSES for item in result.provider_status):
                any_provider_failed = True

        if not any_period_succeeded:
            return self._finish_failed(scan, safe_statuses, "all_providers_failed")

        filtered_candidates = [
            paper
            for paper in candidates
            if not self._contains_excluded_phrase(paper, radar.exclude_keywords)
        ]
        deduplicated = deduplicate_papers(filtered_candidates)
        finished_at = self._now()
        observation = self.repository.observe_papers(
            radar.id,
            scan.id,
            deduplicated.papers,
            finished_at,
        )
        scan.finished_at = finished_at
        scan.heartbeat_at = finished_at
        scan.status = (
            RadarScanStatus.PARTIAL_SUCCESS
            if any_provider_failed
            else RadarScanStatus.SUCCESS
        )
        scan.raw_count = raw_count
        scan.dedup_count = deduplicated.dedup_count
        scan.new_count = len(observation.new_papers)
        scan.provider_status = safe_statuses
        analysis = self.analysis_service.analyze(
            radar, self.repository.list_papers(radar.id)
        )
        scan.analysis = analysis.model_dump(mode="json")
        self.repository.update_representative_scores(
            radar.id,
            {
                paper.canonical_id: paper.representative_score
                for paper in analysis.representative_papers
            },
        )
        self.repository.update_scan(scan)
        self.repository.record_scan_attempt(
            radar.id, scan_at=finished_at, successful=True
        )
        return RadarScanResult(
            scan=scan,
            new_canonical_ids=[paper.canonical_id for paper in observation.new_papers],
            seen_canonical_ids=[paper.canonical_id for paper in observation.seen_papers],
        )

    def recover_stale_scans(self, *, timeout_seconds: int = 900) -> int:
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        now = self._now()
        return self.repository.recover_stale_scans(
            stale_before=now - timedelta(seconds=timeout_seconds),
            recovered_at=now,
        )

    def _finish_failed(
        self,
        scan: RadarScan,
        statuses: list[dict[str, object]],
        safe_error: str,
    ) -> RadarScanResult:
        finished_at = self._now()
        scan.finished_at = finished_at
        scan.heartbeat_at = finished_at
        scan.status = RadarScanStatus.FAILED
        scan.provider_status = statuses
        scan.safe_error = safe_error
        self.repository.update_scan(scan)
        self.repository.record_scan_attempt(
            scan.radar_id, scan_at=finished_at, successful=False
        )
        return RadarScanResult(scan=scan)

    @staticmethod
    def _periods(start_year: int, end_year: int) -> list[tuple[int, int]]:
        periods: list[tuple[int, int]] = []
        current = start_year
        while current <= end_year:
            period_end = min(current + 1, end_year)
            periods.append((current, period_end))
            current = period_end + 1
        return periods

    @staticmethod
    def _period_statuses(
        statuses: list[ProviderSearchStatus], start_year: int, end_year: int
    ) -> list[dict[str, object]]:
        return [
            {
                **status.model_dump(mode="json"),
                "period": f"{start_year}-{end_year}",
                "filtering_mode": FILTERING_MODES.get(
                    status.provider, "post_filtering"
                ),
            }
            for status in statuses
        ]

    @staticmethod
    def _contains_excluded_phrase(paper: object, phrases: list[str]) -> bool:
        if not phrases:
            return False
        title = str(getattr(paper, "title", ""))
        abstract = str(getattr(paper, "abstract", ""))
        text = f"{title}\n{abstract}".casefold()
        return any(phrase.casefold() in text for phrase in phrases)

    def _validate_providers(self, provider_ids: list[str]) -> None:
        capabilities = {
            capability.provider_type: capability
            for capability in self.provider_registry.capabilities()
        }
        try:
            profile = self.provider_profile_store.get(self.profile_id)
        except KeyError:
            raise RadarProviderError("Provider profile is unavailable") from None
        configured = {provider.provider_id: provider for provider in profile.providers}
        for provider_id in provider_ids:
            provider = configured.get(provider_id)
            if provider is None:
                raise RadarProviderError(f"Provider {provider_id!r} is unavailable")
            capability = capabilities.get(provider.provider_type)
            if capability is None or not capability.runnable:
                raise RadarProviderError(f"Provider {provider_id!r} is not runnable")
            if not provider.enabled:
                raise RadarProviderError(f"Provider {provider_id!r} is disabled")

    @staticmethod
    def _validate_year_range(spec: RadarSpec, *, current_year: int) -> None:
        if spec.end_year > current_year:
            raise RadarYearRangeError("end_year must not be in the future")

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Radar clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
