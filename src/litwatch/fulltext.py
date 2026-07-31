from __future__ import annotations

import httpx
import pymupdf


class FullTextExtractor:
    def __init__(self, *, timeout: float = 45, max_bytes: int = 20_000_000) -> None:
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)
        self.max_bytes = max_bytes

    def extract(self, pdf_url: str, *, max_chars: int = 36_000) -> str:
        if not pdf_url:
            return ""
        with self.client.stream("GET", pdf_url, headers={"Accept": "application/pdf"}) as response:
            response.raise_for_status()
            content_length = int(response.headers.get("content-length", 0) or 0)
            if content_length > self.max_bytes:
                raise ValueError(f"PDF is too large ({content_length} bytes)")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self.max_bytes:
                    raise ValueError(f"PDF exceeded {self.max_bytes} bytes")
                chunks.append(chunk)

        data = b"".join(chunks)
        if not data.startswith(b"%PDF"):
            raise ValueError("downloaded content is not a PDF")
        document = pymupdf.open(stream=data, filetype="pdf")
        parts: list[str] = []
        length = 0
        for page in document:
            text = page.get_text("text").strip()
            if text:
                parts.append(text)
                length += len(text)
            if length >= max_chars:
                break
        return "\n\n".join(parts)[:max_chars]
