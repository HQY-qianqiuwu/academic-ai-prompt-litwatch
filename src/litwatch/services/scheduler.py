from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from litwatch.services.subscription_runs import (
    RunAlreadyActiveError,
    SubscriptionRunService,
)
from litwatch.subscription_repository import SubscriptionRepository
from litwatch.subscription_run_repository import SubscriptionRunRepository
from litwatch.subscription_runs import SubscriptionRunTrigger
from litwatch.subscriptions import Subscription


def scheduled_occurrence(subscription: Subscription, local_date: date) -> datetime:
    hour, minute = (int(part) for part in subscription.local_time.split(":"))
    zone = ZoneInfo(subscription.timezone)
    local = datetime.combine(local_date, time(hour, minute), tzinfo=zone)
    return local.astimezone(UTC)


def next_weekly_occurrence(subscription: Subscription, after: datetime) -> datetime:
    after_utc = _aware_utc(after)
    zone = ZoneInfo(subscription.timezone)
    local_after = after_utc.astimezone(zone)
    days_ahead = (subscription.weekday - local_after.weekday()) % 7
    candidate_date = local_after.date() + timedelta(days=days_ahead)
    candidate = scheduled_occurrence(subscription, candidate_date)
    if candidate <= after_utc:
        candidate = scheduled_occurrence(subscription, candidate_date + timedelta(days=7))
    return candidate


def latest_weekly_occurrence(subscription: Subscription, at: datetime) -> datetime:
    at_utc = _aware_utc(at)
    zone = ZoneInfo(subscription.timezone)
    local_at = at_utc.astimezone(zone)
    days_back = (local_at.weekday() - subscription.weekday) % 7
    candidate_date = local_at.date() - timedelta(days=days_back)
    candidate = scheduled_occurrence(subscription, candidate_date)
    if candidate > at_utc:
        candidate = scheduled_occurrence(subscription, candidate_date - timedelta(days=7))
    return candidate


class SchedulerService:
    """Bounded weekly scheduler with deterministic catch-up and durable run keys."""

    def __init__(
        self,
        subscriptions: SubscriptionRepository,
        runs: SubscriptionRunRepository,
        run_service: SubscriptionRunService,
        *,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = 30,
        lease_seconds: int = 300,
        owner: str | None = None,
    ) -> None:
        self.subscriptions = subscriptions
        self.runs = runs
        self.run_service = run_service
        self.clock = clock or (lambda: datetime.now(UTC))
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds
        self.owner = owner or f"scheduler-{uuid4().hex}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="litwatch-subscription-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def tick(self, now: datetime | None = None) -> list[str]:
        now_utc = _aware_utc(now or self.clock())
        self.runs.recover_stale(now_utc)
        executed: list[str] = []
        for subscription in self.subscriptions.list():
            if not subscription.enabled:
                continue
            due = self._due_occurrence(subscription, now_utc)
            if due is None:
                continue
            trigger = (
                SubscriptionRunTrigger.CATCH_UP
                if now_utc > due + timedelta(minutes=1)
                else SubscriptionRunTrigger.SCHEDULED
            )
            run_key = f"weekly:{subscription.id}:{due.isoformat()}"
            period_key = due.astimezone(ZoneInfo(subscription.timezone)).date().isoformat()
            try:
                result = self.run_service.run(
                    subscription.id,
                    trigger=trigger,
                    run_key=run_key,
                    scheduled_for_at=due,
                    period_key=period_key,
                    lease_owner=self.owner,
                    lease_seconds=self.lease_seconds,
                )
            except RunAlreadyActiveError:
                continue
            executed.append(result.run.id)
            self.subscriptions.set_next_run_at(
                subscription.id, next_weekly_occurrence(subscription, due)
            )
        return executed

    def _due_occurrence(
        self, subscription: Subscription, now: datetime
    ) -> datetime | None:
        if subscription.next_run_at is not None:
            return subscription.next_run_at if subscription.next_run_at <= now else None
        latest = latest_weekly_occurrence(subscription, now)
        if latest >= subscription.created_at:
            return latest
        self.subscriptions.set_next_run_at(
            subscription.id, next_weekly_occurrence(subscription, now)
        )
        return None

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.tick()
            except Exception as error:  # noqa: BLE001 - keep later polls alive
                self.last_error = type(error).__name__


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scheduler timestamps must be timezone-aware")
    return value.astimezone(UTC)
