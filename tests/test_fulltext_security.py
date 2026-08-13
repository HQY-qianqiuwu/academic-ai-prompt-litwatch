from __future__ import annotations

import httpx
import pymupdf
import pytest

from litwatch.fulltext import FullTextExtractor


def _public_resolver(_hostname: str, _port: int) -> tuple[str, ...]:
    return ("8.8.8.8",)


def _pdf_bytes(text: str = "Public PDF") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


@pytest.mark.parametrize(
    "url",
    [
        "http://public.example.test/paper.pdf",
        "https://user:secret@public.example.test/paper.pdf",
    ],
)
def test_extract_rejects_unsafe_url_before_request(url: str):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=_pdf_bytes(), request=request)

    extractor = FullTextExtractor(
        resolver=_public_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError) as error:
        extractor.extract(url)

    assert "secret" not in str(error.value)
    assert not requests


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1"])
def test_extract_rejects_loopback_or_private_dns_before_request(address: str):
    requests: list[httpx.Request] = []

    def private_resolver(_hostname: str, _port: int) -> tuple[str, ...]:
        return (address,)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=_pdf_bytes(), request=request)

    extractor = FullTextExtractor(
        resolver=private_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match="non-public"):
        extractor.extract("https://public.example.test/paper.pdf")

    assert not requests


def test_extract_rejects_redirect_to_private_host_without_following_it():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "public.example.test":
            return httpx.Response(
                302,
                headers={"location": "https://127.0.0.1/private.pdf"},
                request=request,
            )
        raise AssertionError("private redirect target must not be requested")

    extractor = FullTextExtractor(
        resolver=_public_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match="non-public"):
        extractor.extract("https://public.example.test/paper.pdf")

    assert requests == ["https://public.example.test/paper.pdf"]


def test_extract_enforces_manual_redirect_limit():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": f"https://public.example.test/{len(requests)}.pdf"},
            request=request,
        )

    extractor = FullTextExtractor(
        max_redirects=1,
        resolver=_public_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match="redirect limit"):
        extractor.extract("https://public.example.test/paper.pdf")

    assert requests == [
        "https://public.example.test/paper.pdf",
        "https://public.example.test/1.pdf",
    ]


def test_extract_rejects_non_pdf_content_without_pdf_signature():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html>not a PDF</html>",
            request=request,
        )

    extractor = FullTextExtractor(
        resolver=_public_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match="not a PDF"):
        extractor.extract("https://public.example.test/paper.pdf")


def test_extract_rejects_stream_that_exceeds_max_bytes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.7" + b"x" * 32,
            request=request,
        )

    extractor = FullTextExtractor(
        max_bytes=16,
        resolver=_public_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match="too large"):
        extractor.extract("https://public.example.test/paper.pdf")


def test_extract_normalizes_timeout_without_network_details():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("credential=secret", request=request)

    extractor = FullTextExtractor(
        resolver=_public_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError) as error:
        extractor.extract("https://public.example.test/paper.pdf")

    assert str(error.value) == "PDF download failed"
    assert "secret" not in str(error.value)


def test_extract_accepts_public_pdf_with_signature_and_bounded_text():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/octet-stream"},
            content=_pdf_bytes("Public PDF evidence"),
            request=request,
        )

    extractor = FullTextExtractor(
        resolver=_public_resolver,
        transport=httpx.MockTransport(handler),
    )

    assert extractor.extract("https://public.example.test/paper.pdf", max_chars=10) == "Public PDF"
