from __future__ import annotations

import html
import re
import time
from collections.abc import Callable
from datetime import date
from threading import Lock

import httpx

from litwatch.config import Topic
from litwatch.models import Author, Paper
from litwatch.text import canonical_id


class CrossrefSource:
    name = "crossref"
    endpoint = "https://api.crossref.org/v1/works"
    _request_lock = Lock()

    def __init__(
        self,
        *,
        email: str = "",
        timeout: float = 30,
        base_url: str | None = None,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        self.email = email.strip()
        self.endpoint = base_url or self.endpoint
        self.max_retries = max_retries
        self.sleep = sleep
        identity = (
            f"LitWatch/0.1 (mailto:{self.email})"
            if self.email
            else "LitWatch/0.1 (literature metadata retrieval)"
        )
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": identity},
            transport=httpx.HTTPTransport(retries=2),
        )

    def search(
        self,
        topic: Topic,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[Paper]:
        params = {
            "query.bibliographic": topic.query,
            "rows": min(limit, 1000),
            "filter": f"from-pub-date:{start_date},until-pub-date:{end_date}",
        }
        if self.email:
            params["mailto"] = self.email

        response: httpx.Response | None = None
        with self._request_lock:
            for attempt in range(self.max_retries + 1):
                response = self.client.get(self.endpoint, params=params)
                retryable = response.status_code == 429 or response.status_code >= 500
                if not retryable or attempt == self.max_retries:
                    break
                self.sleep(self._retry_delay(response, attempt))
        if response is None:  # pragma: no cover - loop invariant
            raise RuntimeError("Crossref request was not attempted")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Crossref response must be an object")
        message = payload.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("items"), list):
            raise TypeError("Crossref response must contain message.items")
        papers: list[Paper] = []
        for item in message["items"]:
            if not isinstance(item, dict) or not self._first_text(item.get("title")):
                continue
            papers.append(self._parse(item))
        return papers

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        raw = response.headers.get("retry-after") or ""
        try:
            delay = float(raw)
        except ValueError:
            delay = 2**attempt
        return min(max(delay, 0), 10)

    def _parse(self, item: dict) -> Paper:
        title = self._first_text(item.get("title"))
        doi = self._normalize_doi(item.get("DOI"))
        raw_url = item.get("URL")
        url = str(raw_url).strip() if raw_url else ""
        if not url and doi:
            url = f"https://doi.org/{doi}"
        identity = canonical_id(doi=doi, title=title)
        source_id = doi or url or identity
        authors = item.get("author")
        if not isinstance(authors, list):
            authors = []
        try:
            citation_count = int(item.get("is-referenced-by-count") or 0)
        except (TypeError, ValueError):
            citation_count = 0
        return Paper(
            canonical_id=identity,
            source_ids={self.name: source_id},
            sources=[self.name],
            title=title,
            abstract=self._clean_abstract(item.get("abstract")),
            authors=[
                Author(name=name)
                for author in authors
                if isinstance(author, dict)
                and (name := self._author_name(author))
            ],
            publication_date=self._publication_date(item),
            venue=self._first_text(item.get("container-title")),
            doi=doi,
            url=url,
            pdf_url=self._pdf_url(item.get("link")),
            is_open_access=False,
            citation_count=citation_count,
        )

    @staticmethod
    def _first_text(value: object) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
        return ""

    @staticmethod
    def _author_name(author: dict) -> str:
        parts = [str(author.get(key) or "").strip() for key in ("given", "family")]
        name = " ".join(part for part in parts if part)
        return name or str(author.get("name") or "").strip()

    @staticmethod
    def _normalize_doi(value: object) -> str:
        if not value:
            return ""
        return re.sub(
            r"^https?://(?:dx\.)?doi\.org/",
            "",
            str(value).strip(),
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _clean_abstract(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            return ""
        without_tags = re.sub(r"<[^>]+>", " ", value)
        return " ".join(html.unescape(without_tags).split())

    @staticmethod
    def _publication_date(item: dict) -> date | None:
        for field in ("published-print", "published-online", "published", "issued"):
            value = item.get(field)
            if not isinstance(value, dict):
                continue
            date_parts = value.get("date-parts")
            if (
                not isinstance(date_parts, list)
                or not date_parts
                or not isinstance(date_parts[0], list)
                or not date_parts[0]
            ):
                continue
            parts = date_parts[0]
            try:
                year = int(parts[0])
                month = int(parts[1]) if len(parts) > 1 and parts[1] else 1
                day = int(parts[2]) if len(parts) > 2 and parts[2] else 1
                return date(year, month, day)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _pdf_url(value: object) -> str:
        if not isinstance(value, list):
            return ""
        for link in value:
            if not isinstance(link, dict):
                continue
            url = str(link.get("URL") or "").strip()
            content_type = str(link.get("content-type") or "").lower()
            if url and ("pdf" in content_type or url.lower().endswith(".pdf")):
                return url
        return ""
