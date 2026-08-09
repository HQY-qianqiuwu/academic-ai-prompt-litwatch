from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date

import httpx

from litwatch.config import Topic
from litwatch.models import Author, Paper
from litwatch.text import canonical_id


class SemanticScholarSource:
    name = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(
        self,
        *,
        api_key: str = "",
        timeout: float = 30,
        base_url: str | None = None,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        self.endpoint = base_url or self.endpoint
        self.max_retries = max_retries
        self.sleep = sleep
        headers = {"x-api-key": api_key} if api_key else {}
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
            transport=httpx.HTTPTransport(retries=2),
        )

    def search(self, topic: Topic, start_date: date, end_date: date, limit: int) -> list[Paper]:
        params = {
            "query": topic.query,
            "limit": min(limit, 100),
            "publicationDateOrYear": f"{start_date}:{end_date}",
            "fields": (
                "paperId,externalIds,title,abstract,authors,publicationDate,venue,url,"
                "openAccessPdf,citationCount"
            ),
        }
        response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            response = self.client.get(self.endpoint, params=params)
            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable or attempt == self.max_retries:
                break
            raw = response.headers.get("retry-after") or ""
            try:
                retry_after = float(raw)
            except ValueError:
                retry_after = 2**attempt
            self.sleep(min(max(retry_after, 0), 10))
        if response is None:  # pragma: no cover - loop invariant
            raise RuntimeError("Semantic Scholar request was not attempted")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise TypeError("Semantic Scholar response must contain a data list")
        return [
            self._parse(item)
            for item in payload["data"]
            if isinstance(item, dict)
            and isinstance(item.get("title"), str)
            and item["title"].strip()
        ]

    def _parse(self, item: dict) -> Paper:
        external = item.get("externalIds")
        if not isinstance(external, dict):
            external = {}
        doi = str(external.get("DOI") or "").removeprefix("https://doi.org/")
        arxiv_id = str(external.get("ArXiv") or "")
        oa_pdf = item.get("openAccessPdf")
        if not isinstance(oa_pdf, dict):
            oa_pdf = {}
        authors = item.get("authors")
        if not isinstance(authors, list):
            authors = []
        publication_date = None
        raw_date = item.get("publicationDate")
        if isinstance(raw_date, str):
            try:
                publication_date = date.fromisoformat(raw_date)
            except ValueError:
                publication_date = None
        try:
            citation_count = int(item.get("citationCount") or 0)
        except (TypeError, ValueError):
            citation_count = 0
        return Paper(
            canonical_id=canonical_id(doi=doi, arxiv_id=arxiv_id, title=item["title"]),
            source_ids={"semantic_scholar": item.get("paperId", "")},
            sources=[self.name],
            title=item["title"].strip(),
            abstract=str(item.get("abstract") or ""),
            authors=[
                Author(name=str(author["name"]))
                for author in authors
                if isinstance(author, dict) and author.get("name")
            ],
            publication_date=publication_date,
            venue=str(item.get("venue") or ""),
            doi=doi,
            url=str(item.get("url") or ""),
            pdf_url=str(oa_pdf.get("url") or ""),
            is_open_access=bool(oa_pdf.get("url")),
            citation_count=citation_count,
        )
