from __future__ import annotations

import ipaddress
import weakref
from collections.abc import Callable
from urllib.parse import urljoin

import httpx
import pymupdf

from litwatch.provider_security import (
    AddressResolver,
    ProviderBaseUrlError,
    ValidatedProviderUrl,
    resolve_host_addresses,
    resolve_validated_provider_url,
)


class FullTextSecurityError(ValueError):
    """Raised when a PDF download cannot cross the safe network boundary."""


_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
ClientFactory = Callable[[], httpx.Client]


class FullTextExtractor:
    def __init__(
        self,
        *,
        timeout: float = 45,
        max_bytes: int = 20_000_000,
        max_redirects: int = 3,
        resolver: AddressResolver = resolve_host_addresses,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects must not be negative")
        if client is not None:
            raise ValueError("shared client injection is not supported")
        if transport is not None:
            raise ValueError("shared transport injection is not supported")
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.resolver = resolver
        self._client_factory = client_factory or self._create_isolated_client
        self._issued_clients: weakref.WeakSet[httpx.Client] = weakref.WeakSet()
        self._closed = False

    def extract(self, pdf_url: str, *, max_chars: int = 36_000) -> str:
        if self._closed:
            raise RuntimeError("FullTextExtractor is closed")
        if not pdf_url:
            return ""
        data, content_type = self._download(pdf_url)
        if content_type != "application/pdf" and not data.startswith(b"%PDF"):
            raise FullTextSecurityError("downloaded content is not a PDF")
        return self._extract_text(data, max_chars)

    def _download(self, pdf_url: str) -> tuple[bytes, str]:
        current_url = pdf_url
        redirects = 0
        while True:
            target = self._validated_url(current_url)
            try:
                client = self._new_isolated_client()
                try:
                    request = self._build_request(client, target)
                    response = client.send(request, stream=True, follow_redirects=False)
                    try:
                        if response.status_code in _REDIRECT_STATUS_CODES:
                            location = response.headers.get("location")
                            if not location:
                                raise FullTextSecurityError("PDF redirect is invalid")
                            if redirects >= self.max_redirects:
                                raise FullTextSecurityError("PDF redirect limit exceeded")
                            redirects += 1
                            current_url = urljoin(target.value, location)
                            continue
                        if response.is_error:
                            raise FullTextSecurityError("PDF download failed")
                        return self._read_response(response)
                    finally:
                        response.close()
                finally:
                    client.close()
            except FullTextSecurityError:
                raise
            except httpx.HTTPError:
                raise FullTextSecurityError("PDF download failed") from None

    def _validated_url(self, value: str) -> ValidatedProviderUrl:
        try:
            return resolve_validated_provider_url(value, resolver=self.resolver)
        except ProviderBaseUrlError as error:
            raise FullTextSecurityError(str(error)) from None

    def _create_isolated_client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
            http2=False,
            transport=httpx.HTTPTransport(
                retries=0,
                trust_env=False,
                limits=httpx.Limits(max_keepalive_connections=0),
            ),
        )

    def _new_isolated_client(self) -> httpx.Client:
        client = self._client_factory()
        try:
            if (
                client.is_closed
                or client._state.name != "UNOPENED"
                or client in self._issued_clients
            ):
                raise FullTextSecurityError("PDF client factory must return a fresh client")
            if client._trust_env:
                raise FullTextSecurityError("PDF client factory must disable trust_env")
            if client.follow_redirects:
                raise FullTextSecurityError("PDF client factory must disable redirects")
            pool = getattr(client._transport, "_pool", None)
            if getattr(pool, "_http2", False):
                raise FullTextSecurityError("PDF client factory must use HTTP/1.1")
        except FullTextSecurityError:
            client.close()
            raise
        self._issued_clients.add(client)
        return client

    def _build_request(self, client: httpx.Client, target: ValidatedProviderUrl) -> httpx.Request:
        try:
            hostname = (
                f"[{target.hostname}]"
                if ipaddress.ip_address(target.hostname).version == 6
                else target.hostname
            )
        except ValueError:
            hostname = target.hostname
        host_header = hostname if target.port == 443 else f"{hostname}:{target.port}"
        return client.build_request(
            "GET",
            httpx.URL(target.value).copy_with(host=target.addresses[0]),
            headers={"Accept": "application/pdf", "Host": host_header},
            extensions={"sni_hostname": target.hostname},
        )

    def close(self) -> None:
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed

    def _read_response(self, response: httpx.Response) -> tuple[bytes, str]:
        content_length_header = response.headers.get("content-length")
        try:
            content_length = int(content_length_header or 0)
        except ValueError:
            raise FullTextSecurityError("PDF response is invalid") from None
        if content_length > self.max_bytes:
            raise FullTextSecurityError("PDF is too large")

        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > self.max_bytes:
                raise FullTextSecurityError("PDF is too large")
            chunks.append(chunk)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        return b"".join(chunks), content_type

    @staticmethod
    def _extract_text(data: bytes, max_chars: int) -> str:
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except pymupdf.FileDataError:
            raise FullTextSecurityError("PDF could not be parsed") from None
        try:
            parts: list[str] = []
            length = 0
            for page in document:
                text = page.get_text("text").strip()
                if text:
                    parts.append(text)
                    length += len(text)
                if length >= max_chars:
                    break
        finally:
            document.close()
        return "\n\n".join(parts)[:max_chars]
