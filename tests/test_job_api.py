from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.web import create_app


def _settings(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        _env_file=None,
        database_path=tmp_path / "jobs-api.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
        job_poll_seconds=3600,
    )


def _app(tmp_path: Path):
    return create_app(
        _settings(tmp_path),
        job_handlers={"paper_analysis": lambda _context, _job: "test-result"},
    )


def _create_job(client: TestClient, **overrides: object):
    body: dict[str, object] = {
        "job_type": "paper_analysis",
        "idempotency_key": "paper:doi:10.1000/example",
        "payload": {
            "paper_id": "doi:10.1000/example",
            "credential_reference": "provider:openai-compatible",
        },
    }
    body.update(overrides)
    return client.post("/api/v2/jobs", json=body)


def test_create_job_returns_202_and_only_safe_projection(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = _create_job(client)

    assert response.status_code == 202
    document = response.json()
    assert document["job_type"] == "paper_analysis"
    assert document["status"] == "queued"
    assert document["status_url"] == f"/api/v2/jobs/{document['job_id']}"
    serialized = response.text.lower()
    assert "payload" not in document
    assert "idempotency_key" not in document
    assert "input_hash" not in document
    assert "credential_reference" not in serialized
    assert "provider:openai-compatible" not in serialized


def test_identical_idempotency_key_reuses_existing_job(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        first = _create_job(client)
        repeated = _create_job(
            client,
            payload={"paper_id": "doi:10.1000/must-not-replace"},
        )
        persisted_payload = app.state.job_repository.get(
            first.json()["job_id"]
        ).payload

    assert first.status_code == repeated.status_code == 202
    assert repeated.json()["job_id"] == first.json()["job_id"]
    assert persisted_payload == {
        "paper_id": "doi:10.1000/example",
        "credential_reference": "provider:openai-compatible",
    }


def test_unknown_job_type_returns_safe_422(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = _create_job(
            client,
            job_type="run-arbitrary-command",
            payload={"paper_id": "not-used"},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "unsupported job type"}


def test_known_job_type_rejects_inline_secret_without_echoing_it(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = _create_job(
            client,
            payload={"password": "must-not-be-echoed"},
        )

    assert response.status_code == 422
    assert "must-not-be-echoed" not in response.text


def test_get_unknown_job_returns_404(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/v2/jobs/not-found")

    assert response.status_code == 404
    assert response.json() == {"detail": "job not found"}


def test_get_job_returns_safe_projection(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        created = _create_job(client).json()
        response = client.get(created["status_url"])

    assert response.status_code == 200
    assert response.json()["job_id"] == created["job_id"]
    assert "payload" not in response.json()
    assert "idempotency_key" not in response.json()
    assert "lease_owner" not in response.json()


def test_cancel_is_idempotent_and_returns_safe_projection(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        created = _create_job(client).json()
        first = client.post(f"{created['status_url']}/cancel")
        repeated = client.post(f"{created['status_url']}/cancel")

    assert first.status_code == repeated.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert repeated.json() == first.json()
    assert "payload" not in repeated.json()


def test_application_lifespan_starts_and_stops_job_worker(tmp_path):
    app = _app(tmp_path)
    worker = app.state.job_worker

    assert worker.is_running is False
    with TestClient(app):
        assert worker.is_running is True
    assert worker.is_running is False


def test_production_app_does_not_advertise_unregistered_placeholder_jobs(tmp_path):
    app = create_app(_settings(tmp_path))

    with TestClient(app) as client:
        response = _create_job(client)

    assert response.status_code == 422
    assert response.json() == {"detail": "unsupported job type"}
    assert app.state.job_worker.registered_job_types == frozenset()
