from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from litwatch.historical_paper_repository import HistoricalPaperRepository
from litwatch.models import Paper
from litwatch.services.deduplication import papers_are_duplicates
from litwatch.services.historical_papers import HistoricalPaperService
from litwatch.services.literature_search import (
    AllProvidersFailedError,
    LiteratureSearchService,
    ProviderExecutionStatus,
    ProviderSearchStatus,
)
from litwatch.services.subscriptions import SubscriptionNotFoundError
from litwatch.subscription_repository import SubscriptionRepository
from litwatch.subscription_run_repository import SubscriptionRunRepository
from litwatch.subscription_runs import (
    Recommendation,
    SubscriptionRun,
    SubscriptionRunStatus,
    SubscriptionRunTrigger,
)


class RunAlreadyActiveError(RuntimeError):
    pass


class SubscriptionRunError(RuntimeError):
    pass


class SubscriptionRunResult(BaseModel):
    run: SubscriptionRun
    recommendations: list[Recommendation] = Field(default_factory=list)


class SubscriptionRunService:
    """Execute one subscription through the existing search and history layers."""

    def __init__(
        self,
        search_service: LiteratureSearchService,
        subscription_repository: SubscriptionRepository,
        run_repository: SubscriptionRunRepository,
        historical_repository: HistoricalPaperRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.search_service = search_service
        self.subscription_repository = subscription_repository
        self.run_repository = run_repository
        self.historical_repository = historical_repository
        self.historical_service = HistoricalPaperService(
            historical_repository, subscription_repository
        )
        self.clock = clock or (lambda: datetime.now(UTC))
        self.id_factory = id_factory or (lambda: uuid4().hex)

    def run_now(self, subscription_id: str) -> SubscriptionRunResult:
        return self.run(
            subscription_id,
            trigger=SubscriptionRunTrigger.MANUAL,
            run_key=f"manual:{subscription_id}:{self.id_factory()}",
        )

    def run(
        self,
        subscription_id: str,
        *,
        trigger: SubscriptionRunTrigger,
        run_key: str,
        scheduled_for_at: datetime | None = None,
        period_key: str | None = None,
    ) -> SubscriptionRunResult:
        subscription = self.subscription_repository.get(subscription_id)
        if subscription is None:
            raise SubscriptionNotFoundError(subscription_id)
        now = self._now()
        run = SubscriptionRun(
            id=self.id_factory(),
            subscription_id=subscription_id,
            run_key=run_key,
            trigger=trigger,
            scheduled_for_at=scheduled_for_at,
            period_key=period_key,
            started_at=now,
            heartbeat_at=now,
            status=SubscriptionRunStatus.RUNNING,
        )
        run, created = self.run_repository.create(run)
        if not created:
            if run.status is SubscriptionRunStatus.RUNNING:
                raise RunAlreadyActiveError(run.id)
            return SubscriptionRunResult(
                run=run,
                recommendations=self.run_repository.list_recommendations(run.id),
            )

        try:
            result = self.search_service.search(
                topic=subscription.topic,
                limit=subscription.search_limit,
                providers=subscription.providers,
            )
        except AllProvidersFailedError as error:
            return self._finish_failed(run, error.provider_status, "all_providers_failed")
        except Exception as error:
            self._finish_failed(run, [], "run_failed")
            raise SubscriptionRunError("Subscription run failed") from error

        finished_at = self._now()
        observation = self.historical_service.observe_papers_for_subscription(
            subscription_id,
            result.papers,
            finished_at,
            run_id=run.id,
        )
        ranked_new = self._ranked_observation(result.papers, observation.new_papers)
        eligible = ranked_new
        recommendations: list[Recommendation] = []
        for position, paper in enumerate(
            eligible[: subscription.recommendation_limit], start=1
        ):
            recommendation = Recommendation(
                id=self.id_factory(),
                run_id=run.id,
                subscription_id=subscription_id,
                canonical_id=paper.canonical_id,
                rank_position=position,
                rank_score=self._score(paper, "rank_score", paper.score),
                relevance_score=self._score(paper, "relevance_score", 0.0),
                quality_score=self._score(paper, "quality_score", 0.0),
                score_detail=paper.score_detail.copy(),
                recommended_at=finished_at,
            )
            if not self.run_repository.add_recommendation(recommendation):
                continue
            self.historical_repository.mark_recommended(
                subscription_id,
                paper.canonical_id,
                finished_at,
                rank_score=recommendation.rank_score,
                relevance_score=recommendation.relevance_score,
                quality_score=recommendation.quality_score,
                run_id=run.id,
            )
            recommendations.append(recommendation)

        failed_statuses = {
            ProviderExecutionStatus.TIMEOUT,
            ProviderExecutionStatus.RATE_LIMITED,
            ProviderExecutionStatus.AUTH_ERROR,
            ProviderExecutionStatus.UPSTREAM_ERROR,
            ProviderExecutionStatus.PARSE_ERROR,
        }
        is_partial = any(status.status in failed_statuses for status in result.provider_status)
        run.status = (
            SubscriptionRunStatus.PARTIAL_SUCCESS
            if is_partial
            else SubscriptionRunStatus.SUCCESS
        )
        run.finished_at = finished_at
        run.heartbeat_at = finished_at
        run.raw_count = result.diagnostics.raw_count
        run.dedup_count = result.diagnostics.dedup_count
        run.duplicates_removed = result.diagnostics.duplicates_removed
        run.historical_duplicates_removed = len(observation.seen_papers)
        run.new_count = len(observation.new_papers)
        run.eligible_count = len(eligible)
        run.recommended_count = len(recommendations)
        run.provider_status = self._safe_statuses(result.provider_status)
        self.run_repository.finish(run)
        self.subscription_repository.record_execution(
            subscription_id, run_at=finished_at, successful=True
        )
        return SubscriptionRunResult(run=run, recommendations=recommendations)

    def _finish_failed(
        self,
        run: SubscriptionRun,
        statuses: list[ProviderSearchStatus],
        safe_error: str,
    ) -> SubscriptionRunResult:
        finished_at = self._now()
        run.status = SubscriptionRunStatus.FAILED
        run.finished_at = finished_at
        run.heartbeat_at = finished_at
        run.provider_status = self._safe_statuses(statuses)
        run.safe_error = safe_error
        self.run_repository.finish(run)
        self.subscription_repository.record_execution(
            run.subscription_id, run_at=finished_at, successful=False
        )
        return SubscriptionRunResult(run=run)

    @staticmethod
    def _ranked_observation(ranked: list[Paper], observed: list[Paper]) -> list[Paper]:
        remaining = [paper.model_copy(deep=True) for paper in observed]
        ordered: list[Paper] = []
        for candidate in ranked:
            match = next(
                (paper for paper in remaining if papers_are_duplicates(candidate, paper)),
                None,
            )
            if match is None:
                continue
            ordered.append(match)
            remaining.remove(match)
        ordered.extend(sorted(remaining, key=lambda paper: paper.canonical_id.casefold()))
        return ordered

    @staticmethod
    def _safe_statuses(statuses: list[ProviderSearchStatus]) -> list[dict[str, object]]:
        return [status.model_dump(mode="json") for status in statuses]

    @staticmethod
    def _score(paper: Paper, name: str, fallback: float) -> float:
        value = paper.score_detail.get(name)
        return float(value) if isinstance(value, int | float) else fallback

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("run clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
