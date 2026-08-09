from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.services.scheduler import (
    SchedulerService,
    next_weekly_occurrence,
)
from litwatch.subscription_repository import SubscriptionRepository
from litwatch.subscription_run_repository import SubscriptionRunRepository
from litwatch.subscription_runs import (
    SubscriptionRun,
    SubscriptionRunStatus,
    SubscriptionRunTrigger,
)
from litwatch.subscriptions import Subscription
from litwatch.web import create_app


def subscription(
    subscription_id: str,
    *,
    created_at: datetime,
    enabled: bool = True,
    next_run_at: datetime | None = None,
    timezone: str = "Asia/Shanghai",
) -> Subscription:
    return Subscription(
        id=subscription_id,
        name="Weekly",
        topic="underwater acoustic localization",
        providers=["openalex"],
        search_limit=10,
        recommendation_limit=5,
        weekday=6,
        local_time="08:00",
        timezone=timezone,
        enabled=enabled,
        created_at=created_at,
        updated_at=created_at,
        next_run_at=next_run_at,
    )


class FakeRunService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, subscription_id: str, **kwargs):
        self.calls.append({"subscription_id": subscription_id, **kwargs})
        return SimpleNamespace(run=SimpleNamespace(id=f"run-{len(self.calls)}"))


def scheduler_stack(tmp_path: Path, *subscriptions: Subscription):
    database = Database(tmp_path / "scheduler.db")
    repository = SubscriptionRepository(database)
    for item in subscriptions:
        repository.create(item)
    runs = SubscriptionRunRepository(database)
    runner = FakeRunService()
    scheduler = SchedulerService(repository, runs, runner, owner="test-scheduler")
    return database, repository, runs, runner, scheduler


def test_due_weekly_run_uses_deterministic_key_and_advances_schedule(tmp_path):
    due = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)  # Sunday 08:00 Asia/Shanghai.
    item = subscription(
        "sub-a", created_at=due - timedelta(days=2), next_run_at=due
    )
    database, repository, _, runner, scheduler = scheduler_stack(tmp_path, item)

    executed = scheduler.tick(due)

    assert executed == ["run-1"]
    assert runner.calls[0]["trigger"] is SubscriptionRunTrigger.SCHEDULED
    assert runner.calls[0]["run_key"] == f"weekly:sub-a:{due.isoformat()}"
    assert repository.get("sub-a").next_run_at == due + timedelta(days=7)
    database.connection.close()


def test_not_due_and_disabled_subscriptions_are_skipped(tmp_path):
    now = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    future = now + timedelta(days=7)
    database, _, _, runner, scheduler = scheduler_stack(
        tmp_path,
        subscription("future", created_at=now, next_run_at=future),
        subscription("disabled", created_at=now - timedelta(days=7), enabled=False),
    )

    assert scheduler.tick(now) == []
    assert runner.calls == []
    database.connection.close()


def test_missed_occurrence_catches_up_exactly_once(tmp_path):
    due = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    monday = due + timedelta(days=1)
    database, _, _, runner, scheduler = scheduler_stack(
        tmp_path,
        subscription("sub-a", created_at=due - timedelta(days=7), next_run_at=due),
    )

    first = scheduler.tick(monday)
    second = scheduler.tick(monday)

    assert first == ["run-1"]
    assert second == []
    assert len(runner.calls) == 1
    assert runner.calls[0]["trigger"] is SubscriptionRunTrigger.CATCH_UP
    database.connection.close()


def test_new_subscription_does_not_catch_up_occurrence_before_creation(tmp_path):
    monday = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    database, repository, _, runner, scheduler = scheduler_stack(
        tmp_path, subscription("sub-a", created_at=monday)
    )

    assert scheduler.tick(monday) == []
    assert runner.calls == []
    assert repository.get("sub-a").next_run_at > monday
    database.connection.close()


def test_run_repository_prevents_two_active_runs_for_subscription(tmp_path):
    now = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    database, _, runs, _, _ = scheduler_stack(
        tmp_path, subscription("sub-a", created_at=now)
    )
    first = SubscriptionRun(
        id="run-one",
        subscription_id="sub-a",
        run_key="one",
        trigger=SubscriptionRunTrigger.SCHEDULED,
        started_at=now,
        heartbeat_at=now,
        status=SubscriptionRunStatus.RUNNING,
        lease_owner="one",
        lease_expires_at=now + timedelta(minutes=5),
    )
    second = first.model_copy(update={"id": "run-two", "run_key": "two"})

    stored_first, created_first = runs.create(first)
    stored_second, created_second = runs.create(second)

    assert created_first is True
    assert created_second is False
    assert stored_first.id == stored_second.id == "run-one"
    database.connection.close()


def test_stale_running_lease_is_recovered_and_allows_new_claim(tmp_path):
    now = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    database, _, runs, _, _ = scheduler_stack(
        tmp_path, subscription("sub-a", created_at=now)
    )
    stale = SubscriptionRun(
        id="stale",
        subscription_id="sub-a",
        run_key="stale-key",
        trigger=SubscriptionRunTrigger.SCHEDULED,
        started_at=now - timedelta(minutes=10),
        heartbeat_at=now - timedelta(minutes=10),
        status=SubscriptionRunStatus.RUNNING,
        lease_owner="dead",
        lease_expires_at=now - timedelta(minutes=5),
    )
    runs.create(stale)

    assert runs.recover_stale(now) == ["stale"]
    recovered = runs.get("stale")
    assert recovered.status is SubscriptionRunStatus.INTERRUPTED
    assert recovered.safe_error == "stale_run_recovered"
    database.connection.close()


def test_timezone_and_dst_weekly_calculation_are_timezone_aware():
    before_dst = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    item = subscription(
        "dst",
        created_at=before_dst,
        timezone="America/New_York",
    ).model_copy(update={"weekday": 6, "local_time": "08:00"})

    first = next_weekly_occurrence(item, before_dst)
    after_transition = next_weekly_occurrence(item, first)

    assert first.tzinfo is UTC
    assert after_transition.tzinfo is UTC
    assert first.hour == 13
    assert after_transition.hour == 12


def test_next_run_survives_restart(tmp_path):
    now = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    database, repository, _, _, scheduler = scheduler_stack(
        tmp_path, subscription("sub-a", created_at=now)
    )
    scheduler.tick(now)
    expected = repository.get("sub-a").next_run_at
    database.connection.close()

    reopened = Database(tmp_path / "scheduler.db")
    assert SubscriptionRepository(reopened).get("sub-a").next_run_at == expected
    reopened.connection.close()


class FakeLifecycleScheduler:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


def test_fastapi_lifespan_starts_and_stops_scheduler(tmp_path):
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    settings = Settings(
        database_path=tmp_path / "web.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )
    scheduler = FakeLifecycleScheduler()

    with TestClient(create_app(settings, scheduler_service=scheduler)) as client:
        assert client.get("/health").status_code == 200
        assert scheduler.started == 1

    assert scheduler.stopped == 1
