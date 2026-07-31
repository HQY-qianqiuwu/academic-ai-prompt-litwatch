from __future__ import annotations

import httpx

from litwatch.config import Settings
from litwatch.models import Paper


class ZoteroExporter:
    def __init__(self, settings: Settings) -> None:
        if not settings.zotero_user_id or not settings.zotero_api_key:
            raise ValueError("Zotero 配置不完整，请检查 .env")
        self.endpoint = f"https://api.zotero.org/users/{settings.zotero_user_id}/items"
        self.client = httpx.Client(
            timeout=30,
            headers={
                "Zotero-API-Key": settings.zotero_api_key,
                "Zotero-API-Version": "3",
                "Content-Type": "application/json",
            },
        )

    def export(self, papers: list[Paper]) -> dict:
        payload = [self._item(paper) for paper in papers]
        if not payload:
            return {"successful": {}, "unchanged": {}, "failed": {}}
        response = self.client.post(self.endpoint, json=payload)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _item(paper: Paper) -> dict:
        analysis = paper.analysis
        note = str(analysis.get("one_liner") or "")
        tags = [
            {"tag": f"LitWatch/{paper.topic_name}"},
            {"tag": f"LitWatch/score-{paper.score:.2f}"},
        ]
        return {
            "itemType": "journalArticle",
            "title": paper.title,
            "creators": [
                {"creatorType": "author", "name": author.name} for author in paper.authors
            ],
            "abstractNote": paper.abstract,
            "publicationTitle": paper.venue,
            "date": paper.publication_date.isoformat() if paper.publication_date else "",
            "DOI": paper.doi,
            "url": paper.url,
            "extra": f"LitWatch: {note}" if note else "Imported by LitWatch",
            "tags": tags,
        }
