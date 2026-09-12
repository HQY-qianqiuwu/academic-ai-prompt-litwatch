from __future__ import annotations

import re
import smtplib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from litwatch.deliveries import Delivery, DeliveryChannel, DeliveryStatus
from litwatch.delivery_repository import DeliveryRepository
from litwatch.historical_paper_repository import HistoricalPaperRepository
from litwatch.subscription_runs import Recommendation, SubscriptionRun
from litwatch.subscriptions import Subscription


class EmailDigestSender(Protocol):
    def configured(self) -> bool: ...

    def send_digest(self, digest: dict[str, object]) -> None: ...


class TextTranslator(Protocol):
    def translate(self, text: str) -> str: ...


class DeliveryService:
    """Persist render-independent digest snapshots for delivery channels."""

    def __init__(
        self,
        repository: DeliveryRepository,
        papers: HistoricalPaperRepository,
        *,
        email_sender: EmailDigestSender | None = None,
        translator: TextTranslator | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repository = repository
        self.papers = papers
        self.email_sender = email_sender
        self.translator = translator
        self.clock = clock or (lambda: datetime.now(UTC))
        self.id_factory = id_factory or (lambda: uuid4().hex)

    def deliver_dashboard(
        self,
        subscription: Subscription,
        run: SubscriptionRun,
        recommendations: list[Recommendation],
    ) -> Delivery:
        existing = self.repository.get_for_run(run.id)
        if existing is not None:
            return existing
        now = self._now()
        digest = self._build_digest(subscription, run, recommendations)
        delivery = Delivery(
            id=self.id_factory(),
            run_id=run.id,
            subscription_id=subscription.id,
            channel=DeliveryChannel.DASHBOARD,
            status=DeliveryStatus.DELIVERED,
            digest=digest,
            attempted_at=now,
            delivered_at=now,
        )
        stored, _ = self.repository.create(delivery)
        return stored

    def _build_digest(
        self,
        subscription: Subscription,
        run: SubscriptionRun,
        recommendations: list[Recommendation],
    ) -> dict[str, object]:
        cards: list[dict[str, object]] = []
        for recommendation in recommendations:
            paper = self.papers.get_paper(recommendation.canonical_id)
            if paper is None:
                continue
            methods = self._method_sentences(paper.abstract)
            cards.append(
                {
                    "canonical_id": paper.canonical_id,
                    "title": paper.title,
                    "authors": [author.name for author in paper.authors],
                    "year": paper.publication_date.year if paper.publication_date else None,
                    "venue": paper.venue or None,
                    "abstract": paper.abstract or None,
                    "title_zh": self._translate(paper.title),
                    "abstract_zh": self._translate(paper.abstract),
                    "methods_zh": [self._translate(method) for method in methods],
                    "recommendation_reason_zh": self._recommendation_reason(
                        subscription.topic, recommendation
                    ),
                    "sources": list(paper.sources),
                    "doi": paper.doi or None,
                    "url": paper.url or None,
                    "rank_position": recommendation.rank_position,
                    "rank_score": recommendation.rank_score,
                    "relevance_score": recommendation.relevance_score,
                    "quality_score": recommendation.quality_score,
                }
            )
        digest: dict[str, object] = {
            "subscription": {
                "id": subscription.id,
                "name": subscription.name,
                "topic": subscription.topic,
            },
            "period": run.period_key,
            "run": {
                "id": run.id,
                "status": run.status.value,
                "started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "raw_count": run.raw_count,
                "dedup_count": run.dedup_count,
                "duplicates_removed": run.duplicates_removed,
                "historical_duplicates_removed": run.historical_duplicates_removed,
                "new_count": run.new_count,
                "recommended_count": run.recommended_count,
                "provider_status": run.provider_status,
            },
            "papers": cards,
            "empty_message": (
                "No new papers matched this subscription this week."
                if run.new_count == 0
                else None
            ),
        }
        return digest

    def _translate(self, text: str) -> str:
        if not text or self.translator is None:
            return text
        try:
            translated = self.translator.translate(text).strip()
        except Exception:  # noqa: BLE001 - translation must not block delivery
            return text
        return translated or text

    @staticmethod
    def _method_sentences(abstract: str) -> list[str]:
        if not abstract.strip():
            return []
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[.!?。！？])\s+", abstract.strip())
            if item.strip()
        ]
        markers = (
            "method", "approach", "algorithm", "model", "framework", "scheme",
            "technique", "propose", "develop", "design", "employ", "utilize",
            "方法", "算法", "模型", "框架", "方案", "提出", "采用", "构建",
        )
        matched = [
            sentence for sentence in sentences
            if any(marker in sentence.casefold() for marker in markers)
        ]
        return (matched or sentences)[:2]

    @staticmethod
    def _recommendation_reason(
        topic: str, recommendation: Recommendation
    ) -> str:
        if recommendation.relevance_score >= 0.75:
            relevance = "高度相关"
        elif recommendation.relevance_score >= 0.5:
            relevance = "较为相关"
        else:
            relevance = "具有一定相关性"
        return (
            f"与订阅主题“{topic}”{relevance}；"
            f"相关度 {recommendation.relevance_score:.2f}，"
            f"文献质量 {recommendation.quality_score:.2f}。"
        )

    @staticmethod
    def _safe_email_error(error: Exception) -> str:
        if isinstance(error, smtplib.SMTPAuthenticationError):
            return "SMTP authentication failed"
        if isinstance(error, (smtplib.SMTPException, OSError)):
            return "Email transport failed"
        return "Email delivery failed"

    def deliver_email(
        self,
        subscription: Subscription,
        run: SubscriptionRun,
        recommendations: list[Recommendation],
    ) -> Delivery:
        existing = self.repository.get_for_run(
            run.id, channel=DeliveryChannel.EMAIL
        )
        if existing is not None:
            return existing
        now = self._now()
        digest = self._build_digest(subscription, run, recommendations)
        if (
            self.email_sender is None
            or not subscription.email_enabled
            or not self.email_sender.configured()
        ):
            delivery = Delivery(
                id=self.id_factory(),
                run_id=run.id,
                subscription_id=subscription.id,
                channel=DeliveryChannel.EMAIL,
                status=DeliveryStatus.FAILED,
                digest=digest,
                attempted_at=now,
                safe_error="Email not configured",
            )
            stored, _ = self.repository.create(delivery)
            return stored
        try:
            self.email_sender.send_digest(digest)
        except Exception as error:  # noqa: BLE001 - normalized to allowlist
            delivery = Delivery(
                id=self.id_factory(),
                run_id=run.id,
                subscription_id=subscription.id,
                channel=DeliveryChannel.EMAIL,
                status=DeliveryStatus.FAILED,
                digest=digest,
                attempted_at=now,
                safe_error=self._safe_email_error(error),
            )
        else:
            delivery = Delivery(
                id=self.id_factory(),
                run_id=run.id,
                subscription_id=subscription.id,
                channel=DeliveryChannel.EMAIL,
                status=DeliveryStatus.DELIVERED,
                digest=digest,
                attempted_at=now,
                delivered_at=now,
            )
        stored, _ = self.repository.create(delivery)
        return stored

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("delivery clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
