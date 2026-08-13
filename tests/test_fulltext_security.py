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
        request_handler=handler,
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
        request_handler=handler,
    )

    with pytest.raises(ValueError, match="non-public"):
        extractor.extract("https://public.example.test/paper.pdf")

    assert not requests


def test_extract_rejects_redirect_to_private_host_without_following_it():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        assert request.headers["host"] == "public.example.test"
        if request.url.host == "8.8.8.8":
            return httpx.Response(
                302,
                headers={"location": "https://127.0.0.1/private.pdf"},
                request=request,
            )
        raise AssertionError("private redirect target must not be requested")

    extractor = FullTextExtractor(
        resolver=_public_resolver,
        request_handler=handler,
    )

    with pytest.raises(ValueError, match="non-public"):
        extractor.extract("https://public.example.test/paper.pdf")

    assert requests == ["https://8.8.8.8/paper.pdf"]


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
        request_handler=handler,
    )

    with pytest.raises(ValueError, match="redirect limit"):
        extractor.extract("https://public.example.test/paper.pdf")

    assert requests == [
        "https://8.8.8.8/paper.pdf",
        "https://8.8.8.8/1.pdf",
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
        request_handler=handler,
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
        request_handler=handler,
    )

    with pytest.raises(ValueError, match="too large"):
        extractor.extract("https://public.example.test/paper.pdf")


def test_extract_normalizes_timeout_without_network_details():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("credential=secret", request=request)

    extractor = FullTextExtractor(
        resolver=_public_resolver,
        request_handler=handler,
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
        request_handler=handler,
    )

    assert extractor.extract("https://public.example.test/paper.pdf", max_chars=10) == "Public PDF"


def test_extract_binds_the_validated_address_without_re_resolving_it():
    resolved_hosts: list[tuple[str, int]] = []

    def rebinding_resolver(hostname: str, port: int) -> tuple[str, ...]:
        resolved_hosts.append((hostname, port))
        if len(resolved_hosts) > 1:
            return ("127.0.0.1",)
        return ("8.8.8.8",)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "8.8.8.8"
        assert request.headers["host"] == "public.example.test"
        assert request.extensions["sni_hostname"] == "public.example.test"
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=_pdf_bytes(),
            request=request,
        )

    extractor = FullTextExtractor(
        resolver=rebinding_resolver,
        request_handler=handler,
    )

    assert extractor.extract("https://public.example.test/paper.pdf") == "Public PDF"
    assert resolved_hosts == [("public.example.test", 443)]


def test_extract_binds_each_redirect_hop_to_its_validated_address():
    resolved_hosts: list[tuple[str, int]] = []
    requests: list[tuple[str, str, str]] = []

    def resolver(hostname: str, port: int) -> tuple[str, ...]:
        resolved_hosts.append((hostname, port))
        return {"first.example.test": ("8.8.8.8",), "next.example.test": ("1.1.1.1",)}[
            hostname
        ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            (
                request.url.host or "",
                request.headers["host"],
                request.extensions["sni_hostname"],
            )
        )
        if request.url.host == "8.8.8.8":
            return httpx.Response(
                302,
                headers={"location": "https://next.example.test/paper.pdf"},
                request=request,
            )
        assert request.url.host == "1.1.1.1"
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=_pdf_bytes(),
            request=request,
        )

    extractor = FullTextExtractor(resolver=resolver, request_handler=handler)

    assert extractor.extract("https://first.example.test/paper.pdf") == "Public PDF"
    assert resolved_hosts == [("first.example.test", 443), ("next.example.test", 443)]
    assert requests == [
        ("8.8.8.8", "first.example.test", "first.example.test"),
        ("1.1.1.1", "next.example.test", "next.example.test"),
    ]


def test_extract_closes_internal_client_after_its_request(monkeypatch):
    closed_clients: list[httpx.Client] = []
    original_close = httpx.Client.close

    def tracking_close(client: httpx.Client) -> None:
        original_close(client)
        closed_clients.append(client)

    monkeypatch.setattr(httpx.Client, "close", tracking_close)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=_pdf_bytes(),
            request=request,
        )

    extractor = FullTextExtractor(
        resolver=_public_resolver,
        request_handler=handler,
    )

    assert extractor.extract("https://public.example.test/paper.pdf") == "Public PDF"

    assert len(closed_clients) == 1
    assert closed_clients[0].is_closed


def test_extract_owns_fresh_transport_for_each_shared_address_redirect_hop(monkeypatch):
    requests: list[tuple[str, str]] = []
    created_transports: list[httpx.MockTransport] = []

    class TrackingMockTransport(httpx.MockTransport):
        def __init__(self, handler):
            super().__init__(handler)
            self.is_closed = False
            created_transports.append(self)

        def close(self) -> None:
            self.is_closed = True
            super().close()

    monkeypatch.setattr(httpx, "MockTransport", TrackingMockTransport)

    def resolver(hostname: str, _port: int) -> tuple[str, ...]:
        return {"first.example.test": ("8.8.8.8",), "next.example.test": ("8.8.8.8",)}[
            hostname
        ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            (
                request.url.host or "",
                request.headers["host"],
            )
        )
        if request.headers["host"] == "first.example.test":
            return httpx.Response(
                302,
                headers={"location": "https://next.example.test/paper.pdf"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=_pdf_bytes(),
            request=request,
        )

    extractor = FullTextExtractor(
        resolver=resolver,
        request_handler=handler,
    )

    assert extractor.extract("https://first.example.test/paper.pdf") == "Public PDF"
    assert requests == [
        ("8.8.8.8", "first.example.test"),
        ("8.8.8.8", "next.example.test"),
    ]
    assert len(created_transports) == 2
    assert created_transports[0] is not created_transports[1]
    assert all(transport.is_closed for transport in created_transports)


@pytest.mark.parametrize(
    ("url", "expected_host"),
    [
        ("https://[2606:4700:4700::1111]/paper.pdf", "[2606:4700:4700::1111]"),
        ("https://[2606:4700:4700::1111]:8443/paper.pdf", "[2606:4700:4700::1111]:8443"),
    ],
)
def test_extract_formats_public_ipv6_host_header(url: str, expected_host: str):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["host"] == expected_host
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=_pdf_bytes(),
            request=request,
        )

    extractor = FullTextExtractor(request_handler=handler)

    assert extractor.extract(url) == "Public PDF"


@pytest.mark.parametrize("argument", ["client", "client_factory", "transport"])
def test_extractor_rejects_connection_owning_injection(argument: str):
    with pytest.raises(TypeError, match=f"unexpected keyword argument '{argument}'"):
        FullTextExtractor(**{argument: object()})


def test_extract_closes_internally_owned_client_on_request_exception(monkeypatch):
    closed_clients: list[httpx.Client] = []
    original_close = httpx.Client.close

    def tracking_close(client: httpx.Client) -> None:
        original_close(client)
        closed_clients.append(client)

    monkeypatch.setattr(httpx.Client, "close", tracking_close)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("credential=secret", request=request)

    extractor = FullTextExtractor(
        resolver=_public_resolver,
        request_handler=handler,
    )

    with pytest.raises(ValueError, match="PDF download failed"):
        extractor.extract("https://public.example.test/paper.pdf")

    assert len(closed_clients) == 1
    assert closed_clients[0].is_closed
