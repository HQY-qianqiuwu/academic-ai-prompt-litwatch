from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from litwatch.config import Topic
from litwatch.models import Paper
from litwatch.provider_config import (
    ProviderConfig,
    ProviderProfile,
    ProviderProfileStore,
    ProviderType,
)
from litwatch.services import (
    AllProvidersFailedError,
    LiteratureSearchService,
    ProviderErrorCode,
    ProviderExecutionStatus,
    ProviderSearchStatus,
)
from litwatch.services import literature_search as literature_search_module
from litwatch.sources.registry import (
    InMemoryCredentialStore,
    ProviderCapability,
    ProviderDisabledError,
    ProviderNotFoundError,
    ProviderRegistry,
)


class FakeSource:
    name = "fake"

    def __init__(
        self,
        papers: list[Paper] | None = None,
        error: Exception | None = None,
        *,
        name: str = "fake",
        events: list[str] | None = None,
    ) -> None:
        self.name = name
        self.papers = papers or []
        self.error = error
        self.events = events
        self.calls: list[tuple[Topic, date, date, int]] = []

    def search(
        self,
        topic: Topic,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[Paper]:
        if self.events is not None:
            self.events.append(self.name)
        self.calls.append((topic, start_date, end_date, limit))
        if self.error is not None:
            raise self.error
        return self.papers


def paper(canonical_id: str) -> Paper:
    return Paper(
        canonical_id=canonical_id,
        title=f"Paper {canonical_id}",
        sources=["openalex"],
    )


def test_search_normalizes_topic_passes_limit_and_returns_papers():
    source = FakeSource([paper("one"), paper("two")])
    service = LiteratureSearchService(source, current_date=lambda: date(2026, 8, 8))

    result = service.search(topic="  underwater acoustic TDOA localization  ", limit=1)

    provider_topic, start_date, end_date, provider_limit = source.calls[0]
    assert provider_topic.query == "underwater acoustic TDOA localization"
    assert provider_topic.name == "underwater acoustic TDOA localization"
    assert start_date == date(1900, 1, 1)
    assert end_date == date(2026, 8, 8)
    assert provider_limit == 1
    assert result.query == "underwater acoustic TDOA localization"
    assert result.paper_count == len(result.papers) == 1
    assert all(isinstance(item, Paper) for item in result.papers)
    assert result.model_dump()["paper_count"] == 1
    assert result.provider_status[0].provider == "fake"
    assert result.provider_status[0].status is ProviderExecutionStatus.SUCCESS
    assert result.provider_status[0].fetched_count == 2
    assert result.provider_status[0].returned_count == 1


def test_search_supports_an_injected_historical_start_date():
    source = FakeSource([paper("one")])
    service = LiteratureSearchService(
        source,
        historical_start_date=date(1950, 1, 1),
        current_date=lambda: date(2026, 8, 8),
    )

    service.search(topic="underwater acoustics", limit=10)

    _, start_date, end_date, _ = source.calls[0]
    assert start_date == date(1950, 1, 1)
    assert end_date == date(2026, 8, 8)


def test_single_provider_runtime_failure_becomes_safe_aggregate_error():
    error = RuntimeError("upstream unavailable")
    service = LiteratureSearchService(FakeSource(error=error))

    with pytest.raises(AllProvidersFailedError) as raised:
        service.search(topic="underwater acoustics", limit=10)

    assert str(raised.value) == "all selected literature providers failed"
    assert raised.value.provider_status[0].status is ProviderExecutionStatus.UPSTREAM_ERROR
    assert raised.value.provider_status[0].error_code is ProviderErrorCode.PROVIDER_ERROR
    assert "upstream unavailable" not in str(raised.value)


@pytest.mark.parametrize(
    ("topic", "limit", "message"),
    [
        ("   ", 10, "topic must not be blank"),
        ("underwater acoustics", 0, "limit must be a positive integer"),
        ("underwater acoustics", -1, "limit must be a positive integer"),
    ],
)
def test_search_rejects_invalid_service_inputs(topic: str, limit: int, message: str):
    source = FakeSource()
    service = LiteratureSearchService(source)

    with pytest.raises(ValueError, match=message):
        service.search(topic=topic, limit=limit)

    assert source.calls == []


def test_service_has_no_forbidden_framework_or_pipeline_imports():
    module_path = Path(literature_search_module.__file__)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    forbidden = {
        "fastapi",
        "litwatch.analysis",
        "litwatch.db",
        "litwatch.pipeline",
        "litwatch.ranking",
        "litwatch.zotero",
    }
    assert imports.isdisjoint(forbidden)


def registry_service(source: FakeSource, *, enabled: bool = True) -> LiteratureSearchService:
    config = ProviderConfig(
        provider_id="openalex",
        provider_type=ProviderType.OPENALEX,
        enabled=enabled,
        base_url="https://api.openalex.org/works",
    )
    profile_store = ProviderProfileStore([ProviderProfile(providers=[config])])
    registry = ProviderRegistry(
        factories={ProviderType.OPENALEX: lambda _config, _credential: source},
        credential_store=InMemoryCredentialStore(),
    )
    return LiteratureSearchService(
        registry=registry,
        profile_store=profile_store,
        current_date=lambda: date(2026, 8, 8),
    )


def test_registry_backed_service_preserves_v1_1_default_provider_behavior():
    source = FakeSource([paper("one")])

    result = registry_service(source).search(topic="underwater acoustics", limit=10)

    assert result.paper_count == 1
    assert len(source.calls) == 1


def test_registry_backed_service_supports_explicit_provider_selection():
    source = FakeSource([paper("one")])

    result = registry_service(source).search(
        topic="underwater acoustics", limit=10, providers=["openalex"]
    )

    assert result.paper_count == 1
    assert len(source.calls) == 1


def test_registry_backed_service_rejects_disabled_explicit_provider():
    service = registry_service(FakeSource(), enabled=False)

    with pytest.raises(ProviderDisabledError, match="disabled"):
        service.search(
            topic="underwater acoustics", limit=10, providers=["openalex"]
        )


def test_registry_backed_service_rejects_unknown_provider():
    service = registry_service(FakeSource())

    with pytest.raises(ProviderNotFoundError, match="not in profile"):
        service.search(
            topic="underwater acoustics", limit=10, providers=["not-real"]
        )


def test_provider_status_rejects_raw_error_text():
    with pytest.raises(ValidationError):
        ProviderSearchStatus(
            provider="openalex",
            status=ProviderExecutionStatus.UPSTREAM_ERROR,
            error_code="API_KEY=must-not-leak",
        )


def test_omitted_providers_use_default_selected_only():
    openalex = FakeSource([paper("openalex")], name="openalex")
    semantic = FakeSource([paper("semantic")], name="semantic_scholar")
    configs = [
        ProviderConfig(
            provider_id="openalex",
            provider_type=ProviderType.OPENALEX,
            enabled=True,
            default_selected=True,
            base_url="https://example.test/openalex",
        ),
        ProviderConfig(
            provider_id="semantic_scholar",
            provider_type=ProviderType.SEMANTIC_SCHOLAR,
            enabled=True,
            default_selected=False,
            base_url="https://example.test/semantic",
        ),
    ]
    registry = ProviderRegistry(
        factories={
            ProviderType.OPENALEX: lambda _config, _credential: openalex,
            ProviderType.SEMANTIC_SCHOLAR: lambda _config, _credential: semantic,
        },
        credential_store=InMemoryCredentialStore(),
        capabilities=(
            ProviderCapability(
                ProviderType.OPENALEX,
                "OpenAlex",
                True,
                True,
                False,
                True,
                ("search",),
            ),
            ProviderCapability(
                ProviderType.SEMANTIC_SCHOLAR,
                "Semantic Scholar",
                True,
                False,
                False,
                True,
                ("search",),
            ),
        ),
    )
    service = LiteratureSearchService(
        registry=registry,
        profile_store=ProviderProfileStore([ProviderProfile(providers=configs)]),
    )

    default_result = service.search(topic="underwater acoustics", limit=10)
    explicit_result = service.search(
        topic="underwater acoustics",
        limit=10,
        providers=["semantic_scholar", "openalex"],
    )

    assert [item.provider for item in default_result.provider_status] == ["openalex"]
    assert [item.provider for item in explicit_result.provider_status] == [
        "semantic_scholar",
        "openalex",
    ]


PROVIDER_TYPES = {
    "openalex": ProviderType.OPENALEX,
    "semantic_scholar": ProviderType.SEMANTIC_SCHOLAR,
    "arxiv": ProviderType.ARXIV,
    "crossref": ProviderType.CROSSREF,
}


def multi_provider_service(
    sources: dict[str, FakeSource],
    *,
    defaults: set[str] | None = None,
) -> LiteratureSearchService:
    defaults = defaults or {"openalex"}
    configs = [
        ProviderConfig(
            provider_id=provider_id,
            provider_type=PROVIDER_TYPES[provider_id],
            enabled=True,
            default_selected=provider_id in defaults,
            base_url=f"https://{provider_id}.example.test/search",
        )
        for provider_id in sources
    ]
    capabilities = tuple(
        ProviderCapability(
            PROVIDER_TYPES[provider_id],
            provider_id,
            True,
            provider_id in defaults,
            False,
            True,
            ("search",),
        )
        for provider_id in sources
    )
    factories = {
        PROVIDER_TYPES[provider_id]: (
            lambda _config, _credential, source=source: source
        )
        for provider_id, source in sources.items()
    }
    return LiteratureSearchService(
        registry=ProviderRegistry(
            factories=factories,
            credential_store=InMemoryCredentialStore(),
            capabilities=capabilities,
        ),
        profile_store=ProviderProfileStore([ProviderProfile(providers=configs)]),
        current_date=lambda: date(2026, 8, 9),
    )


def status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://provider.example.test/search")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("safe test error", request=request, response=response)


def test_multi_provider_search_is_sequential_and_round_robin_with_total_limit():
    events: list[str] = []
    sources = {
        "openalex": FakeSource(
            [paper("oa1"), paper("oa2"), paper("oa3")],
            name="openalex",
            events=events,
        ),
        "semantic_scholar": FakeSource(
            [paper("s1"), paper("s2")],
            name="semantic_scholar",
            events=events,
        ),
        "arxiv": FakeSource([paper("a1")], name="arxiv", events=events),
        "crossref": FakeSource(
            [paper("c1"), paper("c2")], name="crossref", events=events
        ),
    }
    providers = ["openalex", "semantic_scholar", "arxiv", "crossref"]

    result = multi_provider_service(sources).search(
        topic="underwater acoustics",
        limit=7,
        providers=providers,
    )

    assert events == providers
    assert [item.canonical_id for item in result.papers] == [
        "oa1",
        "s1",
        "a1",
        "c1",
        "oa2",
        "s2",
        "c2",
    ]
    assert result.paper_count == 7
    assert all(source.calls[0][3] == 7 for source in sources.values())
    statuses = {item.provider: item for item in result.provider_status}
    assert statuses["openalex"].fetched_count == 3
    assert statuses["openalex"].returned_count == 2
    assert statuses["semantic_scholar"].returned_count == 2
    assert statuses["arxiv"].returned_count == 1
    assert statuses["crossref"].returned_count == 2


def test_multi_provider_search_preserves_duplicates():
    duplicate = paper("same-id")
    service = multi_provider_service(
        {
            "openalex": FakeSource([duplicate], name="openalex"),
            "crossref": FakeSource([duplicate.model_copy()], name="crossref"),
        }
    )

    result = service.search(
        topic="underwater acoustics",
        limit=10,
        providers=["openalex", "crossref"],
    )

    assert [item.canonical_id for item in result.papers] == ["same-id", "same-id"]


def test_empty_and_failed_providers_do_not_discard_successful_results():
    service = multi_provider_service(
        {
            "openalex": FakeSource([paper("oa")], name="openalex"),
            "semantic_scholar": FakeSource(
                error=status_error(429), name="semantic_scholar"
            ),
            "arxiv": FakeSource([], name="arxiv"),
            "crossref": FakeSource(
                error=httpx.ReadTimeout("test timeout"), name="crossref"
            ),
        }
    )

    result = service.search(
        topic="underwater acoustics",
        limit=10,
        providers=["openalex", "semantic_scholar", "arxiv", "crossref"],
    )

    assert [item.canonical_id for item in result.papers] == ["oa"]
    statuses = {item.provider: item for item in result.provider_status}
    assert statuses["openalex"].status is ProviderExecutionStatus.SUCCESS
    assert statuses["semantic_scholar"].status is ProviderExecutionStatus.RATE_LIMITED
    assert statuses["semantic_scholar"].error_code is ProviderErrorCode.UPSTREAM_429
    assert statuses["arxiv"].status is ProviderExecutionStatus.EMPTY
    assert statuses["crossref"].status is ProviderExecutionStatus.TIMEOUT


def test_all_timeouts_raise_504_eligible_aggregate():
    service = multi_provider_service(
        {
            "openalex": FakeSource(error=httpx.ReadTimeout("one"), name="openalex"),
            "arxiv": FakeSource(error=httpx.ConnectTimeout("two"), name="arxiv"),
        }
    )

    with pytest.raises(AllProvidersFailedError) as raised:
        service.search(
            topic="underwater acoustics",
            limit=10,
            providers=["openalex", "arxiv"],
        )

    assert raised.value.all_timeouts is True


def test_mixed_all_failed_errors_are_not_all_timeouts():
    service = multi_provider_service(
        {
            "openalex": FakeSource(error=httpx.ReadTimeout("one"), name="openalex"),
            "crossref": FakeSource(error=status_error(503), name="crossref"),
        }
    )

    with pytest.raises(AllProvidersFailedError) as raised:
        service.search(
            topic="underwater acoustics",
            limit=10,
            providers=["openalex", "crossref"],
        )

    assert raised.value.all_timeouts is False


def test_all_empty_providers_return_http_eligible_empty_success():
    service = multi_provider_service(
        {
            "openalex": FakeSource([], name="openalex"),
            "arxiv": FakeSource([], name="arxiv"),
        }
    )

    result = service.search(
        topic="underwater acoustics",
        limit=10,
        providers=["openalex", "arxiv"],
    )

    assert result.paper_count == 0
    assert all(
        item.status is ProviderExecutionStatus.EMPTY
        for item in result.provider_status
    )
