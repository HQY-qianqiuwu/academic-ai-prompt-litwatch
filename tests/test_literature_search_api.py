from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.models import Author, Paper
from litwatch.services import (
    AllProvidersFailedError,
    LiteratureSearchResult,
    ProviderErrorCode,
    ProviderExecutionStatus,
    ProviderSearchStatus,
)
from litwatch.sources.registry import InMemoryCredentialStore, ProviderNotFoundError
from litwatch.web import create_app


class FakeLiteratureSearchService:
    def __init__(
        self,
        papers: list[Paper] | None = None,
        error: Exception | None = None,
        provider_status: list[ProviderSearchStatus] | None = None,
    ) -> None:
        self.papers = papers or []
        self.error = error
        self.provider_status = provider_status or []
        self.calls: list[tuple[str, int]] = []

    def search(
        self,
        *,
        topic: str,
        limit: int,
        providers: list[str] | None = None,
    ) -> LiteratureSearchResult:
        self.calls.append((topic, limit))
        if self.error is not None:
            raise self.error
        return LiteratureSearchResult(
            query=topic,
            papers=self.papers[:limit],
            provider_status=self.provider_status,
        )


def settings_for(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        database_path=tmp_path / "litwatch.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )


def allow_test_provider_url(value: str) -> str:
    """Offline API tests replace DNS validation with an explicit safe test double."""
    return value


def sample_papers() -> list[Paper]:
    return [
        Paper(
            canonical_id="doi:10.1234/acoustics",
            title="Underwater acoustic localization",
            authors=[Author(name="Ada Lovelace"), Author(name="Grace Hopper")],
            publication_date=date(2024, 5, 1),
            venue="Journal of Underwater Acoustics",
            doi="10.1234/acoustics",
            url="https://doi.org/10.1234/acoustics",
            abstract="A provider-backed abstract.",
            sources=["openalex"],
        ),
        Paper(
            canonical_id="openalex:W123",
            title="Paper with unavailable metadata",
            sources=["openalex"],
        ),
    ]


def upstream_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request(
        "GET",
        "https://api.openalex.org/works",
        headers={"Authorization": "Bearer should-not-leak"},
    )
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"upstream returned {status_code}; API_KEY=sk-should-not-leak",
        request=request,
        response=response,
    )


def test_search_returns_normalized_contract_without_network(tmp_path, monkeypatch):
    def fail_if_openalex_is_called(*args, **kwargs):
        raise AssertionError("real OpenAlex network access is forbidden in API tests")

    monkeypatch.setattr("litwatch.sources.openalex.OpenAlexSource.search", fail_if_openalex_is_called)
    service = FakeLiteratureSearchService(sample_papers())

    with TestClient(create_app(settings_for(tmp_path), service)) as client:
        response = client.post(
            "/api/v1/literature/search",
            json={"topic": "  underwater acoustic TDOA localization  ", "limit": 10},
        )

    assert response.status_code == 200
    payload = response.json()
    assert service.calls == [("underwater acoustic TDOA localization", 10)]
    assert payload["query"] == "underwater acoustic TDOA localization"
    assert payload["paper_count"] == len(payload["papers"]) == 2
    assert payload["provider_status"] == []
    assert payload["papers"][0] == {
        "canonical_id": "doi:10.1234/acoustics",
        "title": "Underwater acoustic localization",
        "authors": ["Ada Lovelace", "Grace Hopper"],
        "year": 2024,
        "venue": "Journal of Underwater Acoustics",
        "doi": "10.1234/acoustics",
        "url": "https://doi.org/10.1234/acoustics",
        "abstract": "A provider-backed abstract.",
        "sources": ["openalex"],
    }
    assert payload["papers"][1]["authors"] == []
    assert payload["papers"][1]["sources"] == ["openalex"]
    for field in ("venue", "doi", "url", "abstract"):
        assert payload["papers"][1][field] is None


@pytest.mark.parametrize(
    "request_body",
    [
        {"topic": "", "limit": 10},
        {"topic": "   ", "limit": 10},
        {"topic": "a", "limit": 10},
        {"topic": "a" * 501, "limit": 10},
        {"topic": "underwater acoustics", "limit": 0},
        {"topic": "underwater acoustics", "limit": -1},
        {"topic": "underwater acoustics", "limit": 51},
        {"topic": "underwater acoustics", "limit": "not-an-integer"},
    ],
)
def test_search_rejects_invalid_request_values(tmp_path, request_body):
    service = FakeLiteratureSearchService(sample_papers())

    with TestClient(create_app(settings_for(tmp_path), service)) as client:
        response = client.post("/api/v1/literature/search", json=request_body)

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            httpx.TimeoutException(
                "timeout at D:\\private\\project; TOKEN=should-not-leak"
            ),
            504,
            "Literature request timed out",
        ),
        (upstream_status_error(429), 502, "Literature request failed"),
        (upstream_status_error(500), 502, "Literature request failed"),
        (
            json.JSONDecodeError("PASSWORD=should-not-leak", "invalid", 0),
            502,
            "Literature request failed",
        ),
        (
            AttributeError("SECRET=should-not-leak at C:\\private\\source.py"),
            502,
            "Literature request failed",
        ),
    ],
)
def test_search_maps_upstream_failures_without_leaking_details(
    tmp_path,
    error,
    expected_status,
    expected_detail,
):
    service = FakeLiteratureSearchService(error=error)

    with TestClient(create_app(settings_for(tmp_path), service)) as client:
        response = client.post(
            "/api/v1/literature/search",
            json={"topic": "underwater acoustics", "limit": 10},
        )

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}
    response_text = response.text.lower()
    for forbidden in ("traceback", "should-not-leak", "api_key", "token", "password", "secret"):
        assert forbidden not in response_text
    assert service.calls == [("underwater acoustics", 10)]


def test_provider_apis_are_exposed_and_default_profile_is_safe(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        capabilities = client.get("/api/v1/providers")
        profiles = client.get("/api/v1/provider-profiles")
        openapi = client.get("/openapi.json")

    assert capabilities.status_code == 200
    runnable = {
        item["provider_type"]: item["runnable"] for item in capabilities.json()
    }
    assert runnable["openalex"] is True
    assert runnable["semantic_scholar"] is True
    assert runnable["arxiv"] is True
    assert runnable["crossref"] is True
    openalex_capability = next(
        item for item in capabilities.json() if item["name"] == "openalex"
    )
    assert openalex_capability["default_selected"] is True
    assert openalex_capability["requires_api_key"] is False
    assert openalex_capability["supports_anonymous"] is True
    assert "search" in openalex_capability["capabilities"]

    assert profiles.status_code == 200
    profile = profiles.json()[0]
    assert profile["profile_id"] == "default"
    assert [item["provider_id"] for item in profile["providers"]] == [
        "openalex",
        "semantic_scholar",
        "arxiv",
        "crossref",
    ]
    defaults = [
        item["provider_id"]
        for item in profile["providers"]
        if item["default_selected"]
    ]
    assert defaults == ["openalex"]
    assert all("api_key" not in item for item in profile["providers"])
    paths = openapi.json()["paths"]
    assert "post" in paths["/api/v1/literature/search"]
    assert "get" in paths["/api/v1/providers"]
    assert set(paths["/api/v1/provider-profiles"]) == {"get", "post"}
    provider_write_schema = openapi.json()["components"]["schemas"][
        "ProviderConfigWrite"
    ]
    assert provider_write_schema["properties"]["api_key"]["writeOnly"] is True


def test_provider_profile_accepts_api_key_without_returning_it(tmp_path):
    marker = "private-provider-test-value"
    request_body = {
        "profile_id": "default",
        "providers": [
            {
                "provider_id": "semantic_scholar",
                "provider_type": "semantic_scholar",
                "enabled": False,
                "base_url": "https://api.semanticscholar.org/graph/v1",
                "requires_api_key": True,
                "credential_reference": "semantic_scholar_default",
                "api_key": marker,
            }
        ],
    }

    with TestClient(
        create_app(
            settings_for(tmp_path),
            provider_base_url_validator=allow_test_provider_url,
        )
    ) as client:
        response = client.post("/api/v1/provider-profiles", json=request_body)
        profiles = client.get("/api/v1/provider-profiles")

    assert response.status_code == 200
    assert response.json()["providers"][0]["configured"] is True
    assert response.json()["providers"][0]["credential_configured"] is True
    for payload in (response.text, profiles.text):
        assert marker not in payload
        assert '"api_key":' not in payload


def test_provider_profile_reports_missing_credential_without_faking_readiness(tmp_path):
    request_body = {
        "profile_id": "default",
        "providers": [
            {
                "provider_id": "semantic_scholar",
                "provider_type": "semantic_scholar",
                "enabled": False,
                "base_url": "https://api.semanticscholar.org/graph/v1",
                "requires_api_key": True,
                "credential_reference": "missing_default",
            }
        ],
    }

    with TestClient(
        create_app(
            settings_for(tmp_path),
            provider_base_url_validator=allow_test_provider_url,
        )
    ) as client:
        response = client.post("/api/v1/provider-profiles", json=request_body)

    assert response.status_code == 200
    assert response.json()["providers"][0]["configured"] is False
    assert response.json()["providers"][0]["credential_configured"] is False


def test_validation_error_does_not_echo_provider_api_key(tmp_path):
    marker = "private-invalid-test-value"

    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.post(
            "/api/v1/provider-profiles",
            json={
                "profile_id": "default",
                "providers": [
                    {
                        "provider_id": "semantic_scholar",
                        "provider_type": "semantic_scholar",
                        "enabled": False,
                        "base_url": "not-a-url",
                        "requires_api_key": True,
                        "credential_reference": "semantic_scholar_default",
                        "api_key": marker,
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert marker not in response.text


def test_provider_profile_partial_update_preserves_write_only_secret(tmp_path):
    marker = "test-profile-secret-not-real"
    full_profile = {
        "profile_id": "default",
        "providers": [
            {
                "provider_id": "semantic_scholar",
                "provider_type": "semantic_scholar",
                "enabled": True,
                "default_selected": False,
                "base_url": "https://api.semanticscholar.org",
                "api_key": marker,
            }
        ],
    }
    partial_update = {
        "profile_id": "default",
        "providers": [{"provider_id": "semantic_scholar", "enabled": False}],
    }

    with TestClient(
        create_app(
            settings_for(tmp_path),
            provider_base_url_validator=allow_test_provider_url,
        )
    ) as client:
        created = client.post("/api/v1/provider-profiles", json=full_profile)
        updated = client.post("/api/v1/provider-profiles", json=partial_update)
        fetched = client.get("/api/v1/provider-profiles")

    assert created.status_code == updated.status_code == fetched.status_code == 200
    updated_provider = updated.json()["providers"][0]
    assert updated_provider["enabled"] is False
    assert updated_provider["credential_reference"] == "semantic_scholar_default"
    assert updated_provider["credential_configured"] is True
    for payload in (created.text, updated.text, fetched.text):
        assert marker not in payload
        assert '"api_key":' not in payload


def test_provider_profile_explicit_clear_restores_unconfigured_state(tmp_path):
    marker = "test-clear-secret-not-real"
    credential_store = InMemoryCredentialStore()
    app = create_app(
        settings_for(tmp_path),
        credential_store=credential_store,
        provider_base_url_validator=allow_test_provider_url,
    )
    full_profile = {
        "profile_id": "default",
        "providers": [
            {
                "provider_id": "semantic_scholar",
                "provider_type": "semantic_scholar",
                "enabled": True,
                "default_selected": False,
                "base_url": "https://api.semanticscholar.org",
                "api_key": marker,
            }
        ],
    }

    with TestClient(app) as client:
        created = client.post("/api/v1/provider-profiles", json=full_profile)
        cleared = client.post(
            "/api/v1/provider-profiles",
            json={
                "profile_id": "default",
                "providers": [
                    {"provider_id": "semantic_scholar", "clear_secret": True}
                ],
            },
        )

    assert created.status_code == cleared.status_code == 200
    assert cleared.json()["providers"][0]["credential_configured"] is False
    assert credential_store.source("semantic_scholar_default") is None
    assert marker not in cleared.text


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1",
        "https://127.0.0.1",
        "https://localhost",
        "https://10.0.0.1",
        "https://169.254.169.254",
        "https://[::1]",
    ],
)
def test_provider_profile_rejects_unsafe_base_url(tmp_path, base_url):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.post(
            "/api/v1/provider-profiles",
            json={
                "profile_id": "default",
                "providers": [
                    {
                        "provider_id": "semantic_scholar",
                        "provider_type": "semantic_scholar",
                        "enabled": False,
                        "base_url": base_url,
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid provider profile"}


def test_search_passes_explicit_provider_selection_without_breaking_v1_1_request(tmp_path):
    class ProviderAwareFake(FakeLiteratureSearchService):
        def __init__(self):
            super().__init__(sample_papers())
            self.provider_calls: list[list[str] | None] = []

        def search(
            self,
            *,
            topic: str,
            limit: int,
            providers: list[str] | None = None,
        ) -> LiteratureSearchResult:
            self.provider_calls.append(providers)
            return super().search(topic=topic, limit=limit)

    service = ProviderAwareFake()
    with TestClient(create_app(settings_for(tmp_path), service)) as client:
        v1_1_response = client.post(
            "/api/v1/literature/search",
            json={"topic": "underwater acoustics", "limit": 1},
        )
        selected_response = client.post(
            "/api/v1/literature/search",
            json={
                "topic": "underwater acoustics",
                "limit": 1,
                "providers": ["openalex"],
            },
        )

    assert v1_1_response.status_code == selected_response.status_code == 200
    assert service.provider_calls == [None, ["openalex"]]


def test_api_returns_additive_provider_status_for_partial_success(tmp_path):
    statuses = [
        ProviderSearchStatus(
            provider="openalex",
            status=ProviderExecutionStatus.SUCCESS,
            fetched_count=2,
            returned_count=1,
            elapsed_ms=12,
        ),
        ProviderSearchStatus(
            provider="semantic_scholar",
            status=ProviderExecutionStatus.RATE_LIMITED,
            elapsed_ms=25,
            error_code=ProviderErrorCode.UPSTREAM_429,
        ),
    ]
    service = FakeLiteratureSearchService(
        sample_papers()[:1], provider_status=statuses
    )

    with TestClient(create_app(settings_for(tmp_path), service)) as client:
        response = client.post(
            "/api/v1/literature/search",
            json={"topic": "underwater acoustics", "limit": 5},
        )

    assert response.status_code == 200
    assert response.json()["provider_status"] == [
        {
            "provider": "openalex",
            "status": "success",
            "fetched_count": 2,
            "returned_count": 1,
            "elapsed_ms": 12,
            "error_code": None,
        },
        {
            "provider": "semantic_scholar",
            "status": "rate_limited",
            "fetched_count": 0,
            "returned_count": 0,
            "elapsed_ms": 25,
            "error_code": "upstream_429",
        },
    ]


@pytest.mark.parametrize(
    ("statuses", "expected_status", "expected_detail"),
    [
        (
            [
                ProviderSearchStatus(
                    provider="openalex",
                    status=ProviderExecutionStatus.TIMEOUT,
                    error_code=ProviderErrorCode.TIMEOUT,
                ),
                ProviderSearchStatus(
                    provider="arxiv",
                    status=ProviderExecutionStatus.TIMEOUT,
                    error_code=ProviderErrorCode.TIMEOUT,
                ),
            ],
            504,
            "All selected literature providers timed out",
        ),
        (
            [
                ProviderSearchStatus(
                    provider="openalex",
                    status=ProviderExecutionStatus.TIMEOUT,
                    error_code=ProviderErrorCode.TIMEOUT,
                ),
                ProviderSearchStatus(
                    provider="crossref",
                    status=ProviderExecutionStatus.UPSTREAM_ERROR,
                    error_code=ProviderErrorCode.UPSTREAM_HTTP,
                ),
            ],
            502,
            "All selected literature providers failed",
        ),
    ],
)
def test_api_maps_safe_all_provider_failures(
    tmp_path,
    statuses,
    expected_status,
    expected_detail,
):
    service = FakeLiteratureSearchService(error=AllProvidersFailedError(statuses))

    with TestClient(create_app(settings_for(tmp_path), service)) as client:
        response = client.post(
            "/api/v1/literature/search",
            json={"topic": "underwater acoustics", "limit": 5},
        )

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}


def test_api_maps_invalid_provider_selection_to_422(tmp_path):
    service = FakeLiteratureSearchService(error=ProviderNotFoundError("not-real"))

    with TestClient(create_app(settings_for(tmp_path), service)) as client:
        response = client.post(
            "/api/v1/literature/search",
            json={
                "topic": "underwater acoustics",
                "limit": 5,
                "providers": ["not-real"],
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Invalid provider selection or configuration"
    }
