from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

import httpx
import pytest

from litwatch.config import Topic
from litwatch.sources.arxiv import ArxivSource

ATOM_HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
"""
ATOM_FOOTER = "</feed>"


def entry(
    *,
    arxiv_id: str = "2401.12345v2",
    published: str = "2024-01-15T10:00:00Z",
    doi: str = "",
    journal_ref: str = "",
) -> str:
    doi_xml = f"<arxiv:doi>{doi}</arxiv:doi>" if doi else ""
    journal_xml = (
        f"<arxiv:journal_ref>{journal_ref}</arxiv:journal_ref>"
        if journal_ref
        else ""
    )
    return f"""
    <entry>
      <id>https://arxiv.org/abs/{arxiv_id}</id>
      <published>{published}</published>
      <updated>{published}</updated>
      <title>  Underwater\n acoustic localization  </title>
      <summary>  A measured\n localization result. </summary>
      <author><name>Ada Lovelace</name></author>
      <author><name>Grace Hopper</name></author>
      <link href="https://arxiv.org/abs/{arxiv_id}" type="text/html" />
      <link href="https://arxiv.org/pdf/{arxiv_id}" type="application/pdf" />
      {doi_xml}
      {journal_xml}
    </entry>
    """


def feed(*entries: str) -> bytes:
    return (ATOM_HEADER + "".join(entries) + ATOM_FOOTER).encode()


def topic() -> Topic:
    return Topic(
        id="underwater_acoustics",
        name="Underwater acoustics",
        query="underwater acoustic localization",
        include=["underwater acoustics", "TDOA"],
        categories=["eess.AS"],
    )


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def source_with_handler(
    handler,
    *,
    clock: FakeClock | None = None,
    max_retries: int = 2,
) -> ArxivSource:
    clock = clock or FakeClock()
    source = ArxivSource(
        base_url="https://arxiv.test/api/query",
        max_retries=max_retries,
        min_request_interval=3,
        clock=clock,
        sleep=clock.sleep,
    )
    headers = dict(source.client.headers)
    source.client.close()
    source.client = httpx.Client(
        headers=headers,
        transport=httpx.MockTransport(handler),
    )
    return source


def test_arxiv_maps_atom_fields_query_and_dates():
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["search_query"]
        assert 'all:"underwater acoustics"' in query
        assert "cat:eess.AS" in query
        assert "submittedDate:[202401010000 TO 202412312359]" in query
        assert request.url.params["max_results"] == "5"
        assert request.url.params["sortBy"] == "submittedDate"
        assert request.headers["user-agent"].startswith("LitWatch/")
        return httpx.Response(
            200,
            content=feed(
                entry(doi="10.1000/arxiv", journal_ref="Journal of Acoustics"),
                entry(arxiv_id="1901.00001", published="2019-01-01T00:00:00Z"),
            ),
            request=request,
        )

    papers = source_with_handler(handler).search(
        topic(), date(2024, 1, 1), date(2024, 12, 31), 5
    )

    assert len(papers) == 1
    paper = papers[0]
    assert paper.canonical_id == "doi:10.1000/arxiv"
    assert paper.source_ids == {"arxiv": "2401.12345v2"}
    assert paper.sources == ["arxiv"]
    assert paper.title == "Underwater acoustic localization"
    assert paper.abstract == "A measured localization result."
    assert [author.name for author in paper.authors] == ["Ada Lovelace", "Grace Hopper"]
    assert paper.publication_date == date(2024, 1, 15)
    assert paper.venue == "Journal of Acoustics"
    assert paper.doi == "10.1000/arxiv"
    assert paper.url == "https://arxiv.org/abs/2401.12345v2"
    assert paper.pdf_url == "https://arxiv.org/pdf/2401.12345v2"
    assert paper.is_open_access is True


def test_arxiv_without_doi_keeps_real_arxiv_identity_and_venue():
    source = source_with_handler(
        lambda request: httpx.Response(200, content=feed(entry()), request=request)
    )

    paper = source.search(topic(), date(2024, 1, 1), date(2024, 12, 31), 5)[0]

    assert paper.canonical_id == "arxiv:2401.12345"
    assert paper.doi == ""
    assert paper.venue == "arXiv"


def test_arxiv_empty_feed_is_successful():
    source = source_with_handler(
        lambda request: httpx.Response(200, content=feed(), request=request)
    )

    assert source.search(topic(), date(2024, 1, 1), date(2024, 12, 31), 5) == []


def test_arxiv_rejects_malformed_xml():
    source = source_with_handler(
        lambda request: httpx.Response(200, content=b"<feed>", request=request)
    )

    with pytest.raises(ET.ParseError, match="no element found"):
        source.search(topic(), date(2024, 1, 1), date(2024, 12, 31), 5)


def test_arxiv_timeout_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("test timeout", request=request)

    with pytest.raises(httpx.ReadTimeout):
        source_with_handler(handler).search(
            topic(), date(2024, 1, 1), date(2024, 12, 31), 5
        )


def test_arxiv_consecutive_requests_wait_but_first_request_does_not():
    clock = FakeClock()
    source = source_with_handler(
        lambda request: httpx.Response(200, content=feed(), request=request),
        clock=clock,
    )

    source.search(topic(), date(2024, 1, 1), date(2024, 12, 31), 5)
    assert clock.sleeps == []
    source.search(topic(), date(2024, 1, 1), date(2024, 12, 31), 5)

    assert clock.sleeps == [3.0]


def test_arxiv_retries_rate_limit_with_finite_polite_waits():
    calls = 0
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            headers={"retry-after": "4"},
            request=request,
        )

    source = source_with_handler(handler, clock=clock, max_retries=2)

    with pytest.raises(httpx.HTTPStatusError):
        source.search(topic(), date(2024, 1, 1), date(2024, 12, 31), 5)

    assert calls == 3
    assert clock.sleeps == [4.0, 4.0]


def test_arxiv_retries_5xx_with_finite_ceiling():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    with pytest.raises(httpx.HTTPStatusError):
        source_with_handler(handler, max_retries=1).search(
            topic(), date(2024, 1, 1), date(2024, 12, 31), 5
        )

    assert calls == 2
