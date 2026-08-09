from __future__ import annotations

from datetime import date

import httpx
import pytest

from litwatch.config import Topic
from litwatch.sources.crossref import CrossrefSource


def topic() -> Topic:
    return Topic(
        id="underwater_acoustics",
        name="Underwater acoustics",
        query="underwater acoustic localization",
    )


def source_with_handler(
    handler,
    *,
    email: str = "",
    max_retries: int = 2,
    sleep=lambda _seconds: None,
) -> CrossrefSource:
    source = CrossrefSource(
        email=email,
        base_url="https://crossref.test/v1/works",
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


def test_crossref_maps_real_fields_and_polite_request_contract():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["query.bibliographic"] == (
            "underwater acoustic localization"
        )
        assert request.url.params["rows"] == "8"
        assert request.url.params["filter"] == (
            "from-pub-date:2020-01-01,until-pub-date:2026-08-09"
        )
        assert request.url.params["mailto"] == "researcher@example.com"
        assert "mailto:researcher@example.com" in request.headers["user-agent"]
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            "DOI": "https://doi.org/10.1000/crossref",
                            "title": ["Underwater localization"],
                            "author": [
                                {"given": "Ada", "family": "Lovelace"},
                                {"given": "Grace", "family": "Hopper"},
                            ],
                            "published-print": {"date-parts": [[2024, 5, 6]]},
                            "container-title": ["Journal of Acoustics"],
                            "URL": "https://doi.org/10.1000/crossref",
                            "abstract": (
                                "<jats:p>Measured <jats:bold>localization</jats:bold> "
                                "results &amp; analysis.</jats:p>"
                            ),
                            "link": [
                                {
                                    "URL": "https://example.test/paper.pdf",
                                    "content-type": "application/pdf",
                                }
                            ],
                            "is-referenced-by-count": 17,
                        }
                    ]
                }
            },
            request=request,
        )

    source = source_with_handler(handler, email="researcher@example.com")
    papers = source.search(topic(), date(2020, 1, 1), date(2026, 8, 9), 8)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.canonical_id == "doi:10.1000/crossref"
    assert paper.source_ids == {"crossref": "10.1000/crossref"}
    assert paper.sources == ["crossref"]
    assert paper.title == "Underwater localization"
    assert [author.name for author in paper.authors] == ["Ada Lovelace", "Grace Hopper"]
    assert paper.publication_date == date(2024, 5, 6)
    assert paper.venue == "Journal of Acoustics"
    assert paper.doi == "10.1000/crossref"
    assert paper.url == "https://doi.org/10.1000/crossref"
    assert paper.abstract == "Measured localization results & analysis."
    assert paper.pdf_url == "https://example.test/paper.pdf"
    assert paper.is_open_access is False
    assert paper.citation_count == 17


@pytest.mark.parametrize(
    ("date_field", "parts", "expected"),
    [
        ("published-print", [2023, 7, 2], date(2023, 7, 2)),
        ("published-online", [2022, 3], date(2022, 3, 1)),
        ("issued", [2021], date(2021, 1, 1)),
    ],
)
def test_crossref_uses_deterministic_publication_date_fallbacks(
    date_field: str,
    parts: list[int],
    expected: date,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            "DOI": "10.1000/date",
                            "title": ["Dated paper"],
                            date_field: {"date-parts": [parts]},
                        }
                    ]
                }
            },
            request=request,
        )

    paper = source_with_handler(handler).search(
        topic(), date(1900, 1, 1), date(2026, 8, 9), 10
    )[0]

    assert paper.publication_date == expected


def test_crossref_missing_metadata_stays_empty_and_missing_title_is_skipped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {"DOI": "10.1000/no-title", "author": [{"family": "Ignored"}]},
                        {
                            "title": "Metadata-light paper",
                            "author": None,
                            "container-title": [],
                        },
                    ]
                }
            },
            request=request,
        )

    papers = source_with_handler(handler).search(
        topic(), date(1900, 1, 1), date(2026, 8, 9), 10
    )

    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "Metadata-light paper"
    assert paper.doi == ""
    assert paper.abstract == ""
    assert paper.authors == []
    assert paper.venue == ""
    assert paper.publication_date is None


def test_crossref_empty_result_is_successful():
    source = source_with_handler(
        lambda request: httpx.Response(
            200,
            json={"message": {"items": []}},
            request=request,
        )
    )

    assert source.search(topic(), date(2020, 1, 1), date(2026, 8, 9), 10) == []


def test_crossref_retries_429_then_succeeds():
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(
                429,
                headers={"retry-after": "0.5"},
                request=request,
            )
        return httpx.Response(
            200,
            json={"message": {"items": []}},
            request=request,
        )

    source = source_with_handler(handler, sleep=sleeps.append)

    assert source.search(topic(), date(2020, 1, 1), date(2026, 8, 9), 10) == []
    assert calls == 3
    assert sleeps == [0.5, 0.5]


def test_crossref_retries_5xx_with_finite_ceiling():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    with pytest.raises(httpx.HTTPStatusError):
        source_with_handler(handler, max_retries=1).search(
            topic(), date(2020, 1, 1), date(2026, 8, 9), 10
        )

    assert calls == 2


def test_crossref_timeout_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("test timeout", request=request)

    with pytest.raises(httpx.ReadTimeout):
        source_with_handler(handler).search(
            topic(), date(2020, 1, 1), date(2026, 8, 9), 10
        )


@pytest.mark.parametrize(
    "response",
    [
        lambda request: httpx.Response(
            200,
            content=b"not-json",
            headers={"content-type": "application/json"},
            request=request,
        ),
        lambda request: httpx.Response(200, json={"message": {}}, request=request),
    ],
)
def test_crossref_rejects_malformed_payload(response):
    with pytest.raises((ValueError, TypeError)):
        source_with_handler(response).search(
            topic(), date(2020, 1, 1), date(2026, 8, 9), 10
        )
