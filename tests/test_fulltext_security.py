from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

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


def _mock_client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
    created_clients: list[httpx.Client] | None = None,
) -> Callable[[], httpx.Client]:
    def factory() -> httpx.Client:
        client = httpx.Client(
            follow_redirects=False,
            trust_env=False,
            transport=httpx.MockTransport(handler),
        )
        if created_clients is not None:
            created_clients.append(client)
        return client

    return factory


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
        client_factory=_mock_client_factory(handler),
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
        client_factory=_mock_client_factory(handler),
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
        client_factory=_mock_client_factory(handler),
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
        client_factory=_mock_client_factory(handler),
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
        client_factory=_mock_client_factory(handler),
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
        client_factory=_mock_client_factory(handler),
    )

    with pytest.raises(ValueError, match="too large"):
        extractor.extract("https://public.example.test/paper.pdf")


def test_extract_normalizes_timeout_without_network_details():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("credential=secret", request=request)

    extractor = FullTextExtractor(
        resolver=_public_resolver,
        client_factory=_mock_client_factory(handler),
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
        client_factory=_mock_client_factory(handler),
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
        client_factory=_mock_client_factory(handler),
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

    extractor = FullTextExtractor(resolver=resolver, client_factory=_mock_client_factory(handler))

    assert extractor.extract("https://first.example.test/paper.pdf") == "Public PDF"
    assert resolved_hosts == [("first.example.test", 443), ("next.example.test", 443)]
    assert requests == [
        ("8.8.8.8", "first.example.test", "first.example.test"),
        ("1.1.1.1", "next.example.test", "next.example.test"),
    ]


def test_extract_closes_each_factory_client_after_its_request():
    created_clients: list[httpx.Client] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=_pdf_bytes(),
            request=request,
        )

    extractor = FullTextExtractor(
        resolver=_public_resolver,
        client_factory=_mock_client_factory(handler, created_clients),
    )

    assert extractor.extract("https://public.example.test/paper.pdf") == "Public PDF"

    assert len(created_clients) == 1
    assert created_clients[0].is_closed


def test_extract_rejects_shared_client_injection_even_when_proxy_safe():
    client = httpx.Client(
        trust_env=False,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request)),
    )
    try:
        with pytest.raises(ValueError, match="client injection"):
            FullTextExtractor(resolver=_public_resolver, client=client)
    finally:
        client.close()


def test_extract_rejects_shared_transport_injection():
    with pytest.raises(ValueError, match="transport injection"):
        FullTextExtractor(
            resolver=_public_resolver,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request)),
        )


def test_extract_uses_fresh_factory_clients_for_shared_address_redirect_hops():
    requests: list[tuple[str, str]] = []
    created_clients: list[httpx.Client] = []

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
        client_factory=_mock_client_factory(handler, created_clients),
    )

    assert extractor.extract("https://first.example.test/paper.pdf") == "Public PDF"
    assert requests == [
        ("8.8.8.8", "first.example.test"),
        ("8.8.8.8", "next.example.test"),
    ]
    assert len(created_clients) == 2
    assert all(client.is_closed for client in created_clients)


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

    extractor = FullTextExtractor(client_factory=_mock_client_factory(handler))

    assert extractor.extract(url) == "Public PDF"


def test_extract_rejects_factory_that_reuses_a_previously_issued_client():
    client = httpx.Client(
        follow_redirects=False,
        trust_env=False,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                302,
                headers={"location": "https://next.example.test/paper.pdf"},
                request=request,
            )
        ),
    )
    try:
        extractor = FullTextExtractor(
            resolver=lambda _hostname, _port: ("8.8.8.8",),
            client_factory=lambda: client,
        )

        with pytest.raises(ValueError, match="fresh"):
            extractor.extract("https://first.example.test/paper.pdf")
    finally:
        client.close()


def test_extract_rejects_factory_client_with_http2_enabled():
    class Http2MockTransport(httpx.MockTransport):
        def __init__(self) -> None:
            super().__init__(lambda request: httpx.Response(200, request=request))
            self._pool = SimpleNamespace(_http2=True)

    client = httpx.Client(
        follow_redirects=False,
        trust_env=False,
        transport=Http2MockTransport(),
    )
    try:
        extractor = FullTextExtractor(
            resolver=_public_resolver,
            client_factory=lambda: client,
        )

        with pytest.raises(ValueError, match="HTTP/1.1"):
            extractor.extract("https://public.example.test/paper.pdf")
        assert client.is_closed
    finally:
        client.close()
