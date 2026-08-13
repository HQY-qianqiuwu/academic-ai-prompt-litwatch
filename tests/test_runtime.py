from pathlib import Path
from traceback import format_exception

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from litwatch.config import Settings
from litwatch.migrations import MigrationSafetyError
from litwatch.runtime import RuntimeMode, RuntimeStatus
from litwatch.web import create_app


def test_runtime_defaults_to_python():
    settings = Settings(_env_file=None)

    assert settings.runtime_mode is RuntimeMode.PYTHON_DEFAULT
    assert RuntimeStatus.from_mode(settings.runtime_mode).requires_dify is False


def test_dify_free_runtime_contract_has_no_legacy_dependencies():
    settings = Settings(_env_file=None, runtime_mode="dify_free")

    assert RuntimeStatus.from_mode(settings.runtime_mode) == RuntimeStatus(
        mode=RuntimeMode.DIFY_FREE,
        python_primary=True,
        requires_dify=False,
        requires_docker=False,
        requires_ssrf_proxy=False,
    )


def test_unknown_runtime_mode_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, runtime_mode="unknown")


def test_application_runtime_starts_and_stops_scheduler_once():
    from litwatch.runtime import ApplicationRuntime

    calls: list[str] = []
    runtime = ApplicationRuntime(
        scheduler_start=lambda: calls.append("scheduler-start"),
        scheduler_stop=lambda: calls.append("scheduler-stop"),
    )

    assert runtime.migration_verified is False
    runtime.start()
    assert runtime.migration_verified is True
    runtime.start()
    runtime.stop()
    runtime.stop()

    assert calls == ["scheduler-start", "scheduler-stop"]


def test_application_runtime_fails_closed_before_services_start():
    from litwatch.runtime import ApplicationRuntime

    calls: list[str] = []

    def reject_unsafe_database() -> None:
        calls.append("database-verify")
        raise MigrationSafetyError("database migration verification failed")

    runtime = ApplicationRuntime(
        database_preflight=reject_unsafe_database,
        scheduler_start=lambda: calls.append("scheduler-start"),
        scheduler_stop=lambda: calls.append("scheduler-stop"),
        startup_hooks=(lambda: calls.append("service-start"),),
    )

    with pytest.raises(
        MigrationSafetyError, match="database migration verification failed"
    ):
        runtime.start()

    assert calls == ["database-verify"]
    assert runtime.started is False
    assert runtime.migration_verified is False


def test_application_runtime_unwinds_worker_when_scheduler_start_fails():
    from litwatch.runtime import ApplicationRuntime

    calls: list[str] = []

    def fail_scheduler_start() -> None:
        calls.append("scheduler-start")
        raise RuntimeError("scheduler start failed")

    def fail_worker_cleanup() -> None:
        calls.append("worker-stop")
        raise RuntimeError("worker cleanup detail")

    runtime = ApplicationRuntime(
        scheduler_start=fail_scheduler_start,
        scheduler_stop=lambda: calls.append("scheduler-stop"),
        worker_start=lambda: calls.append("worker-start"),
        worker_stop=fail_worker_cleanup,
    )

    with pytest.raises(RuntimeError, match="scheduler start failed"):
        runtime.start()

    assert calls == ["worker-start", "scheduler-start", "worker-stop"]


def test_application_runtime_releases_owned_resources_when_startup_fails():
    from litwatch.runtime import ApplicationRuntime

    calls: list[str] = []

    def fail_scheduler_start() -> None:
        calls.append("scheduler-start")
        raise RuntimeError("scheduler start failed")

    runtime = ApplicationRuntime(
        database_preflight=lambda: calls.append("database-preflight"),
        scheduler_start=fail_scheduler_start,
        scheduler_stop=lambda: calls.append("scheduler-stop"),
        worker_start=lambda: calls.append("worker-start"),
        worker_stop=lambda: calls.append("worker-stop"),
        shutdown_hooks=(lambda: calls.append("resource-close"),),
    )

    with pytest.raises(RuntimeError, match="scheduler start failed"):
        runtime.start()

    assert calls == [
        "database-preflight",
        "worker-start",
        "scheduler-start",
        "worker-stop",
        "resource-close",
    ]


def test_scheduler_stop_failure_still_stops_worker_and_reports_safe_error():
    from litwatch.runtime import ApplicationRuntime, RuntimeLifecycleError

    calls: list[str] = []

    def fail_scheduler_stop() -> None:
        calls.append("scheduler-stop")
        raise RuntimeError("secret scheduler detail")

    runtime = ApplicationRuntime(
        scheduler_start=lambda: calls.append("scheduler-start"),
        scheduler_stop=fail_scheduler_stop,
        worker_start=lambda: calls.append("worker-start"),
        worker_stop=lambda: calls.append("worker-stop"),
    )
    runtime.start()

    with pytest.raises(
        RuntimeLifecycleError, match="application runtime shutdown failed"
    ) as error:
        runtime.stop()

    assert "secret scheduler detail" not in str(error.value)
    assert error.value.__cause__ is None
    assert "secret scheduler detail" not in "".join(format_exception(error.value))
    assert calls == [
        "worker-start",
        "scheduler-start",
        "scheduler-stop",
        "worker-stop",
    ]


def test_runtime_status_api_returns_safe_live_component_health(tmp_path):
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "runtime.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v2/runtime")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "python_default",
        "python_primary": True,
        "requires_dify": False,
        "requires_docker": False,
        "requires_ssrf_proxy": False,
        "migration_verified": True,
        "runtime_started": True,
        "job_worker_running": True,
        "job_worker_active": 0,
        "scheduler_running": True,
        "scheduler_last_error": None,
    }


def test_runtime_status_api_detects_a_stopped_job_worker(tmp_path):
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "worker-health.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )
    app = create_app(settings)

    with TestClient(app) as client:
        app.state.job_worker.stop()
        document = client.get("/api/v2/runtime").json()

    assert document["runtime_started"] is True
    assert document["migration_verified"] is True
    assert document["job_worker_running"] is False
    assert document["scheduler_running"] is True


def test_runtime_status_api_detects_stopped_scheduler_and_safe_error(tmp_path):
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "scheduler-health.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )
    app = create_app(settings)

    with TestClient(app) as client:
        app.state.scheduler_service.last_error = "ValueError"
        app.state.scheduler_service.stop()
        document = client.get("/api/v2/runtime").json()

    assert document["runtime_started"] is True
    assert document["migration_verified"] is True
    assert document["job_worker_running"] is True
    assert document["scheduler_running"] is False
    assert document["scheduler_last_error"] == "ValueError"
