from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from litwatch.config import Settings
from litwatch.runtime import RuntimeMode, RuntimeStatus
from litwatch.web import create_app


def test_runtime_defaults_to_python():
    settings = Settings(_env_file=None)

    assert settings.runtime_mode is RuntimeMode.PYTHON_DEFAULT
    assert RuntimeStatus.from_mode(settings.runtime_mode).requires_dify is False


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

    runtime.start()
    runtime.start()
    runtime.stop()
    runtime.stop()

    assert calls == ["scheduler-start", "scheduler-stop"]


def test_runtime_status_api_returns_only_dependency_flags(tmp_path):
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
    }
