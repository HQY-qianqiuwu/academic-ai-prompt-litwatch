from __future__ import annotations

import time
from datetime import date

import httpx

from litwatch.config import Topic
from litwatch.models import Author, Paper
from litwatch.text import canonical_id


class SemanticScholarSource:
    name = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, *, api_key: str = "", timeout: float = 30) -> None:
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
        for attempt in range(3):
            response = self.client.get(self.endpoint, params=params)
            if response.status_code != 429 or attempt == 2:
                break
            retry_after = float(response.headers.get("retry-after") or 2 ** (attempt + 1))
            time.sleep(min(retry_after, 10))
        response.raise_for_status()
        return [self._parse(item) for item in response.json().get("data", []) if item.get("title")]

    def _parse(self, item: dict) -> Paper:
        external = item.get("externalIds") or {}
        doi = external.get("DOI") or ""
        arxiv_id = external.get("ArXiv") or ""
        oa_pdf = item.get("openAccessPdf") or {}
        return Paper(
            canonical_id=canonical_id(doi=doi, arxiv_id=arxiv_id, title=item["title"]),
            source_ids={"semantic_scholar": item.get("paperId", "")},
            sources=[self.name],
            title=item["title"].strip(),
            abstract=item.get("abstract") or "",
            authors=[
                Author(name=a.get("name", "")) for a in item.get("authors", []) if a.get("name")
            ],
            publication_date=item.get("publicationDate"),
            venue=item.get("venue") or "",
            doi=doi,
            url=item.get("url") or "",
            pdf_url=oa_pdf.get("url") or "",
            is_open_access=bool(oa_pdf.get("url")),
            citation_count=int(item.get("citationCount") or 0),
        )
