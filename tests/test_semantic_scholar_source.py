from __future__ import annotations

from datetime import date

import httpx
import pytest

from litwatch.config import Topic
from litwatch.sources.semantic_scholar import SemanticScholarSource


def topic() -> Topic:
    return Topic(
        id="underwater_acoustics",
        name="Underwater acoustics",
        query="underwater acoustic localization",
    )


def source_with_handler(
    handler,
    *,
    api_key: str = "",
    max_retries: int = 2,
    sleep=lambda _seconds: None,
) -> SemanticScholarSource:
    source = SemanticScholarSource(
        api_key=api_key,
        base_url="https://semantic.test/graph/v1/paper/search",
        max_retries=max_retries,
        sleep=sleep,
    )
    headers = dict(source.client.headers)
    source.client.close()
    source.client = httpx.Client(
        headers=headers,
        transport=httpx.MockTransport(handler),
    )
    return source


def test_semantic_scholar_maps_real_fields_and_request_contract():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["query"] == "underwater acoustic localization"
        assert request.url.params["limit"] == "7"
        assert request.url.params["publicationDateOrYear"] == "2020-01-01:2026-08-09"
        assert request.headers["x-api-key"] == "test-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "S2-123",
                        "externalIds": {"DOI": "10.1000/example", "ArXiv": "2401.12345"},
                        "title": "  Underwater localization  ",
                        "abstract": "Measured localization results.",
                        "authors": [{"name": "Ada"}, {"name": "Grace"}],
                        "publicationDate": "2024-05-06",
                        "venue": "JASA",
                        "url": "https://www.semanticscholar.org/paper/S2-123",
                        "openAccessPdf": {"url": "https://example.test/paper.pdf"},
                        "citationCount": 12,
                    }
                ]
            },
            request=request,
        )

    source = source_with_handler(handler, api_key="test-key")
    papers = source.search(topic(), date(2020, 1, 1), date(2026, 8, 9), 7)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.canonical_id == "doi:10.1000/example"
    assert paper.source_ids == {"semantic_scholar": "S2-123"}
    assert paper.sources == ["semantic_scholar"]
    assert paper.title == "Underwater localization"
    assert [author.name for author in paper.authors] == ["Ada", "Grace"]
    assert paper.publication_date == date(2024, 5, 6)
    assert paper.venue == "JASA"
    assert paper.doi == "10.1000/example"
    assert paper.abstract == "Measured localization results."
    assert paper.pdf_url == "https://example.test/paper.pdf"
    assert paper.is_open_access is True
    assert paper.citation_count == 12


def test_semantic_scholar_preserves_missing_metadata_without_guessing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "S2-EMPTY",
                        "title": "Metadata-light paper",
                        "externalIds": None,
                        "authors": None,
                        "publicationDate": "not-a-date",
                    }
                ]
            },
            request=request,
        )

    paper = source_with_handler(handler).search(
        topic(), date(2020, 1, 1), date(2026, 8, 9), 10
    )[0]

    assert paper.doi == ""
    assert paper.abstract == ""
    assert paper.authors == []
    assert paper.publication_date is None
    assert paper.venue == ""


def test_semantic_scholar_empty_result_is_successful():
    source = source_with_handler(
        lambda request: httpx.Response(200, json={"data": []}, request=request)
    )

    assert source.search(topic(), date(2020, 1, 1), date(2026, 8, 9), 10) == []


def test_semantic_scholar_retries_429_then_succeeds():
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(
                429,
                headers={"retry-after": "0.25"},
                request=request,
            )
        return httpx.Response(200, json={"data": []}, request=request)

    source = source_with_handler(handler, sleep=sleeps.append)

    assert source.search(topic(), date(2020, 1, 1), date(2026, 8, 9), 10) == []
    assert calls == 3
    assert sleeps == [0.25, 0.25]


@pytest.mark.parametrize("status_code", [401, 403])
def test_semantic_scholar_auth_errors_are_not_retried(status_code: int):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, request=request)

    source = source_with_handler(handler)

    with pytest.raises(httpx.HTTPStatusError) as raised:
        source.search(topic(), date(2020, 1, 1), date(2026, 8, 9), 10)

    assert raised.value.response.status_code == status_code
    assert calls == 1


def test_semantic_scholar_timeout_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("test timeout", request=request)

    with pytest.raises(httpx.ReadTimeout):
        source_with_handler(handler).search(
            topic(), date(2020, 1, 1), date(2026, 8, 9), 10
        )


def test_semantic_scholar_retries_5xx_with_a_finite_ceiling():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    with pytest.raises(httpx.HTTPStatusError):
        source_with_handler(handler, max_retries=2).search(
            topic(), date(2020, 1, 1), date(2026, 8, 9), 10
        )

    assert calls == 3


@pytest.mark.parametrize(
    "response",
    [
        lambda request: httpx.Response(
            200,
            content=b"not-json",
            headers={"content-type": "application/json"},
            request=request,
        ),
        lambda request: httpx.Response(200, json={"data": {}}, request=request),
    ],
)
def test_semantic_scholar_rejects_malformed_payload(response):
    with pytest.raises((ValueError, TypeError)):
        source_with_handler(response).search(
            topic(), date(2020, 1, 1), date(2026, 8, 9), 10
        )


def test_semantic_scholar_client_repr_does_not_expose_key():
    marker = "private-semantic-scholar-test-key"
    source = SemanticScholarSource(api_key=marker)

    assert marker not in repr(source.__dict__)
