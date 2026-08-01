from __future__ import annotations

from datetime import date

import httpx

from litwatch.config import Topic
from litwatch.models import Author, Paper
from litwatch.text import abstract_from_inverted_index, canonical_id


class OpenAlexSource:
    name = "openalex"
    endpoint = "https://api.openalex.org/works"

    def __init__(self, *, email: str = "", timeout: float = 30) -> None:
        self.email = email
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            transport=httpx.HTTPTransport(retries=2),
        )

    def search(self, topic: Topic, start_date: date, end_date: date, limit: int) -> list[Paper]:
        params = {
            "search": topic.query,
            "filter": f"from_publication_date:{start_date},to_publication_date:{end_date}",
            "sort": "publication_date:desc",
            "per-page": min(limit, 200),
            "select": (
                "id,doi,title,abstract_inverted_index,authorships,publication_date,"
                "primary_location,best_oa_location,open_access,cited_by_count"
            ),
        }
        if self.email:
            params["mailto"] = self.email
        response = self.client.get(self.endpoint, params=params)
        response.raise_for_status()
        return [
            self._parse(item) for item in response.json().get("results", []) if item.get("title")
        ]

    def _parse(self, item: dict) -> Paper:
        doi = (item.get("doi") or "").removeprefix("https://doi.org/")
        primary = item.get("primary_location") or {}
        best_oa = item.get("best_oa_location") or {}
        source = primary.get("source") or {}
        oa = item.get("open_access") or {}
        pdf_url = best_oa.get("pdf_url") or primary.get("pdf_url") or ""
        return Paper(
            canonical_id=canonical_id(doi=doi, title=item["title"]),
            source_ids={"openalex": item.get("id", "")},
            sources=[self.name],
            title=item["title"].strip(),
            abstract=abstract_from_inverted_index(item.get("abstract_inverted_index")),
            authors=[
                Author(name=(entry.get("author") or {}).get("display_name", ""))
                for entry in item.get("authorships", [])
                if (entry.get("author") or {}).get("display_name")
            ],
            publication_date=item.get("publication_date"),
            venue=source.get("display_name") or "",
            doi=doi,
            url=primary.get("landing_page_url") or item.get("doi") or item.get("id", ""),
            pdf_url=pdf_url,
            is_open_access=bool(oa.get("is_oa")),
            citation_count=int(item.get("cited_by_count") or 0),
        )
