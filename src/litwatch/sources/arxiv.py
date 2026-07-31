from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime

import httpx

from litwatch.config import Topic
from litwatch.models import Author, Paper
from litwatch.text import canonical_id

ATOM = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivSource:
    name = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    def __init__(self, *, timeout: float = 30) -> None:
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "LitWatch/0.1 (literature monitoring; contact via repository)"},
        )

    def search(self, topic: Topic, start_date: date, end_date: date, limit: int) -> list[Paper]:
        terms = [term for term in topic.include if len(term) > 2] or topic.query.split()[:8]
        term_query = " OR ".join(f'all:"{term}"' for term in terms)
        category_query = " OR ".join(f"cat:{cat}" for cat in topic.categories)
        query = f"({term_query})"
        if category_query:
            query += f" AND ({category_query})"
        response = self.client.get(
            self.endpoint,
            params={
                "search_query": query,
                "start": 0,
                "max_results": min(limit, 100),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        papers = [self._parse(entry) for entry in root.findall("atom:entry", ATOM)]
        return [
            paper
            for paper in papers
            if paper.publication_date and start_date <= paper.publication_date <= end_date
        ]

    def _parse(self, entry: ET.Element) -> Paper:
        abs_url = self._text(entry, "atom:id")
        match = re.search(r"/abs/([^/?#]+)", abs_url)
        arxiv_id = match.group(1) if match else abs_url.rsplit("/", 1)[-1]
        published = self._text(entry, "atom:published")
        published_date = datetime.fromisoformat(published).astimezone(UTC).date()
        doi = self._text(entry, "arxiv:doi")
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
            venue="arXiv",
            doi=doi,
            url=abs_url,
            pdf_url=links.get("application/pdf", f"https://arxiv.org/pdf/{arxiv_id}"),
            is_open_access=True,
        )

    @staticmethod
    def _text(node: ET.Element, path: str) -> str:
        found = node.find(path, ATOM)
        return found.text.strip() if found is not None and found.text else ""
