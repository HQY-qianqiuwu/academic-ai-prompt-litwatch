from __future__ import annotations

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
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects must not be negative")
        if transport is not None and client is not None:
            raise ValueError("transport and client cannot both be provided")
        if client is not None and client._trust_env:
            raise ValueError("injected client must set trust_env=False")
        self.owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=(
                transport
                if transport is not None
                else httpx.HTTPTransport(retries=0, trust_env=False)
            ),
        )
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.resolver = resolver

    def extract(self, pdf_url: str, *, max_chars: int = 36_000) -> str:
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
                request = self._build_request(target)
                response = self.client.send(request, stream=True, follow_redirects=False)
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
            except FullTextSecurityError:
                raise
            except httpx.HTTPError:
                raise FullTextSecurityError("PDF download failed") from None

    def _validated_url(self, value: str) -> ValidatedProviderUrl:
        try:
            return resolve_validated_provider_url(value, resolver=self.resolver)
        except ProviderBaseUrlError as error:
            raise FullTextSecurityError(str(error)) from None

    def _build_request(self, target: ValidatedProviderUrl) -> httpx.Request:
        host_header = target.hostname if target.port == 443 else f"{target.hostname}:{target.port}"
        return self.client.build_request(
            "GET",
            httpx.URL(target.value).copy_with(host=target.addresses[0]),
            headers={"Accept": "application/pdf", "Host": host_header},
            extensions={"sni_hostname": target.hostname},
        )

    def close(self) -> None:
        if self.owns_client:
            self.client.close()

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
