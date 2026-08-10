from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import uuid4

from litwatch.provider_config import ProviderProfileStore
from litwatch.radar_repository import RadarRepository
from litwatch.radars import RadarSpec, ResearchRadar
from litwatch.sources.registry import ProviderRegistry


class RadarNotFoundError(LookupError):
    pass


class RadarProviderError(ValueError):
    pass


class RadarYearRangeError(ValueError):
    pass


class ResearchRadarService:
    """Validated Radar CRUD. Historical scanning is added in the next stage."""

    def __init__(
        self,
        repository: RadarRepository,
        provider_registry: ProviderRegistry,
        provider_profile_store: ProviderProfileStore,
        *,
        profile_id: str = "default",
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repository = repository
        self.provider_registry = provider_registry
        self.provider_profile_store = provider_profile_store
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
