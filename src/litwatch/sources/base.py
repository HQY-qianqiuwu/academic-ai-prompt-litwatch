from __future__ import annotations

from datetime import date
from typing import Protocol

from litwatch.config import Topic
from litwatch.models import Paper


class PaperSource(Protocol):
    name: str

    def search(self, topic: Topic, start_date: date, end_date: date, limit: int) -> list[Paper]: ...
