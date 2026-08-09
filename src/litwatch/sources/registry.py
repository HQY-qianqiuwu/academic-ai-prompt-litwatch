"""Provider capability registry and safe credential resolution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from litwatch.config import Settings
from litwatch.provider_config import ProviderConfig, ProviderType
from litwatch.provider_security import ProviderBaseUrlError, validate_provider_base_url
from litwatch.sources.arxiv import ArxivSource
from litwatch.sources.base import PaperSource
from litwatch.sources.crossref import CrossrefSource
from litwatch.sources.openalex import OpenAlexSource
from litwatch.sources.semantic_scholar import SemanticScholarSource


class ProviderRegistryError(ValueError):
    """Base class for provider selection and configuration failures."""


class ProviderNotFoundError(ProviderRegistryError):
    """Raised when a provider identifier is absent from the selected profile."""


class ProviderDisabledError(ProviderRegistryError):
    """Raised when a disabled provider is selected explicitly."""


class ProviderNotRunnableError(ProviderRegistryError):
    """Raised for a declared future capability without a runnable adapter."""


class ProviderCredentialError(ProviderRegistryError):
    """Raised when an enabled provider lacks its referenced credential."""


class CredentialStore(Protocol):
    """Resolve secrets by opaque reference without exposing them in provider config."""

    def resolve(self, reference: str) -> str | None: ...


class InMemoryCredentialStore:
    """Layer runtime profile secrets over environment-provided credentials."""

    def __init__(self, credentials: Mapping[str, str] | None = None) -> None:
        self._environment_credentials = {
            reference: secret
            for reference, secret in (credentials or {}).items()
            if secret
        }
        self._runtime_credentials: dict[str, str] = {}
        self._lock = RLock()

    @classmethod
    def from_settings(cls, settings: Settings) -> InMemoryCredentialStore:
        """Load supported secret values already resolved by pydantic-settings/.env."""
        return cls(
            {
                "semantic_scholar_default": settings.semantic_scholar_api_key,
                "ieee_xplore_default": settings.ieee_xplore_api_key,
            }
        )

    def resolve(self, reference: str) -> str | None:
        with self._lock:
            if reference in self._runtime_credentials:
                return self._runtime_credentials[reference]
            return self._environment_credentials.get(reference)

    def configured(self, reference: str | None) -> bool:
        return bool(reference and self.resolve(reference))

    def set(self, reference: str, secret: str) -> None:
        if not secret:
            raise ValueError("credential must not be blank")
        with self._lock:
            self._runtime_credentials[reference] = secret

    def clear(self, reference: str) -> None:
        """Clear only the runtime override so environment fallback remains available."""
        with self._lock:
            self._runtime_credentials.pop(reference, None)

    def source(self, reference: str | None) -> str | None:
        """Describe credential precedence without exposing the credential value."""
        if not reference:
            return None
        with self._lock:
            if reference in self._runtime_credentials:
                return "profile"
            if reference in self._environment_credentials:
                return "environment"
            return None

    def __repr__(self) -> str:
        with self._lock:
            configured = len(
                set(self._environment_credentials) | set(self._runtime_credentials)
            )
        return f"InMemoryCredentialStore(configured={configured})"


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """Static registry metadata; runnable never implies that credentials are configured."""

    provider_type: ProviderType
    display_name: str
    runnable: bool
    default_selected: bool
    requires_api_key: bool
    supports_anonymous: bool
    capabilities: tuple[str, ...]


ProviderFactory = Callable[[ProviderConfig, str | None], PaperSource]
ProviderBaseUrlValidator = Callable[[str], str]


CAPABILITIES = (
    ProviderCapability(
        ProviderType.OPENALEX, "OpenAlex", True, True, False, True, ("search", "metadata")
    ),
    ProviderCapability(
        ProviderType.SEMANTIC_SCHOLAR,
        "Semantic Scholar",
        True,
        False,
        False,
        True,
        ("search", "metadata", "citations"),
    ),
    ProviderCapability(
        ProviderType.ARXIV, "arXiv", True, False, False, True, ("search", "preprints")
    ),
    ProviderCapability(
        ProviderType.CROSSREF,
        "Crossref",
        True,
        False,
        False,
        True,
        ("search", "metadata"),
    ),
    ProviderCapability(
        ProviderType.IEEE_XPLORE,
        "IEEE Xplore",
        False,
        False,
        True,
        False,
        ("search", "metadata"),
    ),
    ProviderCapability(
        ProviderType.SCOPUS,
        "Scopus",
        False,
        False,
        True,
        False,
        ("search", "metadata"),
    ),
    ProviderCapability(
        ProviderType.WEB_OF_SCIENCE,
        "Web of Science",
        False,
        False,
        True,
        False,
        ("search", "metadata"),
    ),
)


class ProviderRegistry:
    """Build configured PaperSource instances without coupling callers to adapters."""

    def __init__(
        self,
        *,
        factories: Mapping[ProviderType, ProviderFactory],
        credential_store: CredentialStore,
        capabilities: tuple[ProviderCapability, ...] = CAPABILITIES,
        base_url_validator: ProviderBaseUrlValidator | None = None,
    ) -> None:
        self._factories = dict(factories)
        self.credential_store = credential_store
        self._capabilities = {item.provider_type: item for item in capabilities}
        self._base_url_validator = base_url_validator

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        credential_store: CredentialStore | None = None,
        base_url_validator: ProviderBaseUrlValidator = validate_provider_base_url,
    ) -> ProviderRegistry:
        def openalex_factory(config: ProviderConfig, _: str | None) -> PaperSource:
            timeout = config.options.get(
                "timeout_seconds", settings.request_timeout_seconds
            )
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
                raise ProviderRegistryError("OpenAlex timeout_seconds must be positive")
            return OpenAlexSource(
                email=settings.openalex_email,
                timeout=float(timeout),
                base_url=str(config.base_url),
            )

        def semantic_scholar_factory(
            config: ProviderConfig, credential: str | None
        ) -> PaperSource:
            timeout = config.options.get(
                "timeout_seconds", settings.request_timeout_seconds
            )
            retries = config.options.get("max_retries", 2)
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or timeout <= 0
            ):
                raise ProviderRegistryError(
                    "Semantic Scholar timeout_seconds must be positive"
                )
            if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
                raise ProviderRegistryError(
                    "Semantic Scholar max_retries must be a non-negative integer"
                )
            return SemanticScholarSource(
                api_key=credential or "",
                timeout=float(timeout),
                base_url=str(config.base_url),
                max_retries=retries,
            )

        def arxiv_factory(config: ProviderConfig, _: str | None) -> PaperSource:
            timeout = config.options.get(
                "timeout_seconds", settings.request_timeout_seconds
            )
            retries = config.options.get("max_retries", 2)
            interval = config.options.get("min_request_interval", 3.0)
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or timeout <= 0
            ):
                raise ProviderRegistryError("arXiv timeout_seconds must be positive")
            if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
                raise ProviderRegistryError(
                    "arXiv max_retries must be a non-negative integer"
                )
            if (
                isinstance(interval, bool)
                or not isinstance(interval, (int, float))
                or interval < 0
            ):
                raise ProviderRegistryError(
                    "arXiv min_request_interval must not be negative"
                )
            return ArxivSource(
                timeout=float(timeout),
                base_url=str(config.base_url),
                max_retries=retries,
                min_request_interval=float(interval),
            )

        def crossref_factory(config: ProviderConfig, _: str | None) -> PaperSource:
            timeout = config.options.get(
                "timeout_seconds", settings.request_timeout_seconds
            )
            retries = config.options.get("max_retries", 2)
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or timeout <= 0
            ):
                raise ProviderRegistryError("Crossref timeout_seconds must be positive")
            if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
                raise ProviderRegistryError(
                    "Crossref max_retries must be a non-negative integer"
                )
            mailto = config.options.get("mailto", settings.crossref_email)
            if not isinstance(mailto, str):
                raise ProviderRegistryError("Crossref mailto must be a string")
            return CrossrefSource(
                email=mailto,
                timeout=float(timeout),
                base_url=str(config.base_url),
                max_retries=retries,
            )

        return cls(
            factories={
                ProviderType.OPENALEX: openalex_factory,
                ProviderType.SEMANTIC_SCHOLAR: semantic_scholar_factory,
                ProviderType.ARXIV: arxiv_factory,
                ProviderType.CROSSREF: crossref_factory,
            },
            credential_store=credential_store or InMemoryCredentialStore.from_settings(settings),
            base_url_validator=base_url_validator,
        )

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return tuple(self._capabilities.values())

    def build(self, config: ProviderConfig) -> PaperSource:
        if not config.enabled:
            raise ProviderDisabledError(f"provider {config.provider_id!r} is disabled")

        capability = self._capabilities.get(config.provider_type)
        factory = self._factories.get(config.provider_type)
        if capability is None or factory is None or not capability.runnable:
            raise ProviderNotRunnableError(
                f"provider type {config.provider_type.value!r} is not runnable"
            )

        if self._base_url_validator is not None:
            try:
                validated_base_url = self._base_url_validator(str(config.base_url))
            except ProviderBaseUrlError:
                raise ProviderRegistryError(
                    f"provider {config.provider_id!r} failed base URL security validation"
                ) from None
            config = config.model_copy(update={"base_url": validated_base_url})

        credential: str | None = None
        if config.credential_reference:
            credential = self.credential_store.resolve(config.credential_reference)
        if config.requires_api_key:
            if not config.credential_reference:
                raise ProviderCredentialError(
                    f"provider {config.provider_id!r} requires credential_reference"
                )
            if not credential:
                raise ProviderCredentialError(
                    f"credential for provider {config.provider_id!r} is not configured"
                )

        return factory(config, credential)
