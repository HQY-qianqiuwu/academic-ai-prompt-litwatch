from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, date, datetime
from threading import Lock

import httpx

from litwatch.config import Topic
from litwatch.models import Author, Paper
from litwatch.text import canonical_id

ATOM = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivSource:
    name = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    def __init__(
        self,
        *,
        timeout: float = 30,
        base_url: str | None = None,
        max_retries: int = 2,
        min_request_interval: float = 3.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if min_request_interval < 0:
            raise ValueError("min_request_interval must not be negative")
        self.endpoint = base_url or self.endpoint
        self.max_retries = max_retries
        self.min_request_interval = min_request_interval
        self.sleep = sleep
        self.clock = clock
        self._request_lock = Lock()
        self._last_request_at: float | None = None
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            transport=httpx.HTTPTransport(retries=2),
            headers={"User-Agent": "LitWatch/0.1 (literature monitoring; contact via repository)"},
        )

    def search(self, topic: Topic, start_date: date, end_date: date, limit: int) -> list[Paper]:
        terms = ([term for term in topic.include if len(term) > 2] or [
            t for t in re.findall(r"\w+", topic.query.casefold()) if len(t) > 2
        ])[:8]
        term_query = " OR ".join(f'all:"{term}"' for term in terms)
        if not term_query:
            term_query = f'all:"{topic.query}"'
        category_query = " OR ".join(f"cat:{cat}" for cat in topic.categories)
        query = f"({term_query})"
        if category_query:
            query += f" AND ({category_query})"
        query += (
            " AND submittedDate:"
            f"[{start_date:%Y%m%d}0000 TO {end_date:%Y%m%d}2359]"
        )
        params = {
            "search_query": query,
            "start": 0,
            "max_results": min(limit, 100),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        response: httpx.Response | None = None
        required_interval = self.min_request_interval
        for attempt in range(self.max_retries + 1):
            self._wait_for_request_slot(required_interval)
            response = self.client.get(self.endpoint, params=params)
            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable or attempt == self.max_retries:
                break
            retry_after = self._retry_after(response)
            required_interval = max(self.min_request_interval, retry_after)
        if response is None:  # pragma: no cover - loop invariant
            raise RuntimeError("arXiv request was not attempted")
        response.raise_for_status()
        root = ET.fromstring(response.content)
        papers = [self._parse(entry) for entry in root.findall("atom:entry", ATOM)]
        return [
            paper
            for paper in papers
            if paper.publication_date and start_date <= paper.publication_date <= end_date
        ]

    def _wait_for_request_slot(self, required_interval: float) -> None:
        with self._request_lock:
            now = self.clock()
            if self._last_request_at is not None:
                remaining = required_interval - (now - self._last_request_at)
                if remaining > 0:
                    self.sleep(remaining)
                    now = self.clock()
            self._last_request_at = now

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        raw = response.headers.get("retry-after") or ""
        try:
            return max(0, float(raw))
        except ValueError:
            return 0

    def _parse(self, entry: ET.Element) -> Paper:
        abs_url = self._text(entry, "atom:id")
        match = re.search(r"/abs/([^/?#]+)", abs_url)
        arxiv_id = match.group(1) if match else abs_url.rsplit("/", 1)[-1]
        published = self._text(entry, "atom:published")
        published_date = (
            datetime.fromisoformat(published).astimezone(UTC).date()
            if published
            else None
        )
        doi = self._text(entry, "arxiv:doi")
        journal_reference = self._text(entry, "arxiv:journal_ref")
        links = {
            link.attrib.get("type", ""): link.attrib.get("href", "")
            for link in entry.findall("atom:link", ATOM)
        }
        title = " ".join(self._text(entry, "atom:title").split())
        return Paper(
            canonical_id=canonical_id(doi=doi, arxiv_id=arxiv_id, title=title),
            source_ids={"arxiv": arxiv_id},
            sources=[self.name],
            title=title,
            abstract=" ".join(self._text(entry, "atom:summary").split()),
            authors=[
                Author(name=self._text(author, "atom:name"))
                for author in entry.findall("atom:author", ATOM)
            ],
            publication_date=published_date,
            venue=journal_reference or "arXiv",
            doi=doi,
            url=abs_url,
            pdf_url=links.get("application/pdf", f"https://arxiv.org/pdf/{arxiv_id}"),
            is_open_access=True,
        )

    @staticmethod
    def _text(node: ET.Element, path: str) -> str:
        found = node.find(path, ATOM)
        return found.text.strip() if found is not None and found.text else ""
