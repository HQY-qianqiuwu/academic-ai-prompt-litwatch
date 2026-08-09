from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from litwatch.historical_paper_repository import HistoricalPaperRepository
from litwatch.models import Paper
from litwatch.paper_history import ObservationResult
from litwatch.services.deduplication import deduplicate_papers, papers_are_duplicates
from litwatch.services.subscriptions import SubscriptionNotFoundError
from litwatch.subscription_repository import SubscriptionRepository


class HistoricalPaperService:
    """Classify observations without depending on scheduling or recommendation policy."""

    def __init__(
        self,
        repository: HistoricalPaperRepository,
        subscription_repository: SubscriptionRepository,
    ) -> None:
        self.repository = repository
        self.subscription_repository = subscription_repository

    def observe_papers_for_subscription(
        self,
        subscription_id: str,
        papers: Iterable[Paper],
        observed_at: datetime,
        run_id: str | None = None,
    ) -> ObservationResult:
        if not self.subscription_repository.exists(subscription_id):
            raise SubscriptionNotFoundError(subscription_id)
        candidates = [paper.model_copy(deep=True) for paper in papers]
        deduplicated = deduplicate_papers(candidates).papers
        for merged in deduplicated:
            matching = [
                candidate
                for candidate in candidates
                if papers_are_duplicates(merged, candidate)
            ]
            if not matching:
                continue
            ranked = min(
                matching,
                key=lambda candidate: (-candidate.score, candidate.canonical_id.casefold()),
            )
            merged.score = ranked.score
            merged.score_detail = ranked.score_detail.copy()
            merged.topic_id = ranked.topic_id
            merged.topic_name = ranked.topic_name
            merged.analysis = ranked.analysis.copy()
        return self.repository.observe(
            subscription_id, deduplicated, observed_at, run_id=run_id
        )
