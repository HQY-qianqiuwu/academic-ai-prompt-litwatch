from __future__ import annotations

from urllib.parse import urljoin

import httpx
import pymupdf

from litwatch.provider_security import (
    AddressResolver,
    ProviderBaseUrlError,
    resolve_host_addresses,
    validate_provider_base_url,
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
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects must not be negative")
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            transport=transport if transport is not None else httpx.HTTPTransport(retries=0),
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
            safe_url = self._validated_url(current_url)
            try:
                with self.client.stream(
                    "GET", safe_url, headers={"Accept": "application/pdf"}
                ) as response:
                    if response.status_code in _REDIRECT_STATUS_CODES:
                        location = response.headers.get("location")
                        if not location:
                            raise FullTextSecurityError("PDF redirect is invalid")
                        if redirects >= self.max_redirects:
                            raise FullTextSecurityError("PDF redirect limit exceeded")
                        redirects += 1
                        current_url = urljoin(safe_url, location)
                        continue
                    if response.is_error:
                        raise FullTextSecurityError("PDF download failed")
                    return self._read_response(response)
            except FullTextSecurityError:
                raise
            except httpx.HTTPError:
                raise FullTextSecurityError("PDF download failed") from None

    def _validated_url(self, value: str) -> str:
        try:
            return validate_provider_base_url(value, resolver=self.resolver)
        except ProviderBaseUrlError as error:
            raise FullTextSecurityError(str(error)) from None

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
