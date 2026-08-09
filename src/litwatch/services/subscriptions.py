from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import uuid4

from litwatch.provider_config import ProviderProfileStore
from litwatch.sources.registry import ProviderRegistry
from litwatch.subscription_repository import SubscriptionRepository
from litwatch.subscriptions import Subscription, SubscriptionSpec


class SubscriptionNotFoundError(LookupError):
    pass


class SubscriptionProviderError(ValueError):
    pass


class SubscriptionService:
    """Validated subscription CRUD without retrieval or scheduling behavior."""

    def __init__(
        self,
        repository: SubscriptionRepository,
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

    def create(self, spec: SubscriptionSpec) -> Subscription:
        self._validate_providers(spec.providers)
        now = self._now()
        subscription = Subscription(
            **spec.model_dump(),
            id=self.id_factory(),
            created_at=now,
            updated_at=now,
            last_run_at=None,
            last_success_at=None,
            next_run_at=None,
        )
        return self.repository.create(subscription)

    def list(self) -> list[Subscription]:
        return self.repository.list()

    def get(self, subscription_id: str) -> Subscription:
        subscription = self.repository.get(subscription_id)
        if subscription is None:
            raise SubscriptionNotFoundError(subscription_id)
        return subscription

    def update(
        self, subscription_id: str, changes: Mapping[str, object]
    ) -> Subscription:
        current = self.get(subscription_id)
        editable = {
            field_name: getattr(current, field_name)
            for field_name in SubscriptionSpec.model_fields
        }
        editable.update(changes)
        spec = SubscriptionSpec.model_validate(editable)
        self._validate_providers(spec.providers)
        updated = current.model_copy(
            update={**spec.model_dump(), "updated_at": self._now()}, deep=True
        )
        return self.repository.update(Subscription.model_validate(updated))

    def _validate_providers(self, provider_ids: list[str]) -> None:
        capabilities = {
            capability.provider_type: capability
            for capability in self.provider_registry.capabilities()
        }
        try:
            profile = self.provider_profile_store.get(self.profile_id)
        except KeyError:
            raise SubscriptionProviderError("Provider profile is unavailable") from None
        configured = {provider.provider_id: provider for provider in profile.providers}

        for provider_id in provider_ids:
            provider = configured.get(provider_id)
            if provider is None:
                matching_capability = next(
                    (
                        capability
                        for capability in capabilities.values()
                        if capability.provider_type.value == provider_id
                    ),
                    None,
                )
                if matching_capability is not None and not matching_capability.runnable:
                    raise SubscriptionProviderError(
                        f"Provider {provider_id!r} is not runnable"
                    )
                raise SubscriptionProviderError(
                    f"Provider {provider_id!r} is not available in the active profile"
                )

            capability = capabilities.get(provider.provider_type)
            if capability is None or not capability.runnable:
                raise SubscriptionProviderError(
                    f"Provider {provider_id!r} is not runnable"
                )
            if not provider.enabled:
                raise SubscriptionProviderError(f"Provider {provider_id!r} is disabled")

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("subscription clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
