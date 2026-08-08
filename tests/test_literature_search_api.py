from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.models import Author, Paper
from litwatch.services import LiteratureSearchResult
from litwatch.web import create_app


class FakeLiteratureSearchService:
    def __init__(
        self,
        papers: list[Paper] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.papers = papers or []
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, *, topic: str, limit: int) -> LiteratureSearchResult:
        self.calls.append((topic, limit))
        if self.error is not None:
            raise self.error
        return LiteratureSearchResult(query=topic, papers=self.papers[:limit])


def settings_for(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        database_path=tmp_path / "litwatch.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )


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
            "OpenAlex request timed out",
        ),
        (upstream_status_error(429), 502, "OpenAlex upstream request failed"),
        (upstream_status_error(500), 502, "OpenAlex upstream request failed"),
        (
            json.JSONDecodeError("PASSWORD=should-not-leak", "invalid", 0),
            502,
            "OpenAlex upstream request failed",
        ),
        (
            AttributeError("SECRET=should-not-leak at C:\\private\\source.py"),
            502,
            "OpenAlex upstream request failed",
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
