from __future__ import annotations

from datetime import date

import httpx
import pytest

from litwatch.config import Topic
from litwatch.models import Paper
from litwatch.provider_config import (
    ProviderConfig,
    ProviderProfile,
    ProviderProfileStore,
    ProviderType,
    default_provider_profile,
)
from litwatch.services.literature_search import (
    AllProvidersFailedError,
    LiteratureSearchService,
    ProviderExecutionStatus,
    ProviderSearchStatus,
)
from litwatch.services.scan import ScanService, ScanStatus
from litwatch.sources.registry import InMemoryCredentialStore, ProviderCapability, ProviderRegistry


class Source:
    def __init__(self, name: str, papers: list[Paper] | None = None, error: Exception | None = None):
        self.name = name
        self.papers = papers or []
        self.error = error
        self.calls = 0

    def search(self, _topic: Topic, _start: date, _end: date, _limit: int) -> list[Paper]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.papers


def service(sources: dict[str, Source], *, default_profile: bool = False) -> ScanService:
    types = {
        "openalex": ProviderType.OPENALEX,
        "arxiv": ProviderType.ARXIV,
        "crossref": ProviderType.CROSSREF,
    }
    configs = [
        ProviderConfig(
            provider_id=name,
            provider_type=types[name],
            enabled=True,
            default_selected=True,
            base_url=f"https://{name}.example.org/search",
        )
        for name in sources
    ]
    registry = ProviderRegistry(
        factories={types[name]: (lambda _config, _secret, source=source: source)
                   for name, source in sources.items()},
        credential_store=InMemoryCredentialStore(),
        capabilities=tuple(
            ProviderCapability(types[name], name, True, True, False, True, ("search",))
            for name in sources
        ),
    )
    profile = (
        default_provider_profile(openalex_base_url="https://openalex.example.org/search")
        if default_profile
        else ProviderProfile(providers=configs)
    )
    return ScanService(
        LiteratureSearchService(
            registry=registry,
            profile_store=ProviderProfileStore([profile]),
            current_date=lambda: date(2026, 9, 14),
        )
    )


def paper(identifier: str, source: str) -> Paper:
    return Paper(canonical_id=identifier, title="Underwater acoustic localization", sources=[source])


def rate_limit() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://openalex.example.org/search")
    return httpx.HTTPStatusError("rate limited", request=request,
                                 response=httpx.Response(429, request=request))


def test_fallback_completes_normalize_deduplicate_score_and_scan_result():
    duplicate = paper("same", "arxiv")
    scan = service({
        "openalex": Source("openalex", error=rate_limit()),
        "arxiv": Source("arxiv", [duplicate, duplicate.model_copy(deep=True)]),
    }).scan(topic="underwater acoustic localization", limit=10)

    assert scan.status is ScanStatus.PARTIAL_SUCCESS
    assert scan.fetched == 2
    assert scan.deduplicated == 1
    assert scan.selected == 1
    assert scan.provider_success_count == 1
    assert scan.papers[0].sources == ["arxiv"]
    assert scan.papers[0].score_detail["rank_score"] >= 0
    assert [item.status for item in scan.provider_status] == [
        ProviderExecutionStatus.RATE_LIMITED, ProviderExecutionStatus.SUCCESS
    ]


def test_scan_distinguishes_empty_success_from_all_provider_failure():
    empty = service({"openalex": Source("openalex")}).scan(topic="acoustics", limit=5)
    failed = service({"openalex": Source("openalex", error=rate_limit())}).scan(
        topic="acoustics", limit=5
    )

    assert empty.status is ScanStatus.SUCCESS_EMPTY
    assert empty.provider_success_count == 1
    assert failed.status is ScanStatus.ALL_PROVIDERS_FAILED
    assert failed.provider_success_count == 0
    assert failed.selected == 0


def test_scan_success_is_separate_from_ai_analysis():
    scan = service({"openalex": Source("openalex", [paper("one", "openalex")])}).scan(
        topic="underwater acoustic localization", limit=5
    )

    assert scan.status is ScanStatus.SUCCESS
    assert scan.selected == 1
    assert scan.papers[0].analysis == {}


def test_default_profile_falls_back_after_openalex_rate_limit():
    sources = {
        "openalex": Source("openalex", error=rate_limit()),
        "arxiv": Source("arxiv", [paper("arxiv:one", "arxiv")]),
        "crossref": Source("crossref"),
    }

    scan = service(sources, default_profile=True).scan(
        topic="underwater acoustic localization", limit=5
    )

    assert scan.status is ScanStatus.PARTIAL_SUCCESS
    assert scan.selected == 1
    assert scan.papers[0].score_detail["rank_score"] >= 0
    assert [source.calls for source in sources.values()] == [1, 1, 1]


def test_unconfigured_provider_does_not_mask_all_attempted_timeouts():
    class FailedSearch:
        def search(self, **_kwargs):
            raise AllProvidersFailedError([
                ProviderSearchStatus(
                    provider="semantic_scholar",
                    status=ProviderExecutionStatus.SKIPPED_UNCONFIGURED,
                ),
                ProviderSearchStatus(provider="openalex", status=ProviderExecutionStatus.TIMEOUT),
            ])

    result = ScanService(FailedSearch()).scan(topic="acoustics", limit=5)

    assert result.status is ScanStatus.ALL_PROVIDERS_FAILED
    assert result.all_timeouts is True


@pytest.mark.parametrize("provider_id", ["openalex", "arxiv", "crossref"])
def test_each_keyless_provider_passes_through_normalize_deduplicate_score(
    provider_id: str,
):
    candidate = Paper(
        canonical_id="paper:one",
        title="Underwater acoustic localization",
        sources=[],
    )
    provider = Source(provider_id, [candidate, candidate.model_copy(deep=True)])

    scan = service({provider_id: provider}).scan(
        topic="underwater acoustic localization", limit=5
    )

    assert provider.calls == 1
    assert scan.status is ScanStatus.SUCCESS
    assert (scan.fetched, scan.deduplicated, scan.selected) == (2, 1, 1)
    assert scan.diagnostics.duplicates_removed == 1
    assert scan.papers[0].sources == [provider_id]
    assert set(scan.papers[0].score_detail) >= {
        "rank_score", "relevance_score", "quality_score"
    }
    assert len(scan.diagnostics.ranking) == 1
    assert scan.diagnostics.ranking[0].canonical_id == "paper:one"
    assert scan.provider_status[0].returned_count == 1


def test_three_keyless_providers_merge_to_one_scored_scan_result():
    sources = {
        provider_id: Source(
            provider_id,
            [Paper(canonical_id="paper:shared", title="Underwater acoustic localization")],
        )
        for provider_id in ("openalex", "arxiv", "crossref")
    }

    scan = service(sources).scan(topic="underwater acoustic localization", limit=5)

    assert scan.status is ScanStatus.SUCCESS
    assert (scan.fetched, scan.deduplicated, scan.selected) == (3, 1, 1)
    assert scan.papers[0].sources == ["arxiv", "crossref", "openalex"]
    assert len(scan.diagnostics.ranking) == 1
    assert all(item.returned_count == 1 for item in scan.provider_status)
    assert [source.calls for source in sources.values()] == [1, 1, 1]
