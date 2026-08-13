from __future__ import annotations

from pathlib import Path
from threading import Event
from time import monotonic, sleep

from fastapi.testclient import TestClient

from litwatch import web
from litwatch.config import Settings
from litwatch.models import Paper
from litwatch.web import create_app


def _settings(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text(
        """topics:
  - id: underwater
    name: Underwater acoustics
    query: underwater acoustic localization
""",
        encoding="utf-8",
    )
    return Settings(
        _env_file=None,
        database_path=tmp_path / "paper-analysis-api.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
        job_poll_seconds=3600,
        job_lease_seconds=2,
        job_default_timeout_seconds=2,
    )


def _seed_paper(app, *, abstract: str = "The abstract describes a grounded localization method.") -> None:
    database = app.state.database
    run_id = database.start_run()
    database.upsert(
        Paper(
            canonical_id="doi:10.1000/example",
            title="Provider-owned title",
            abstract=abstract,
            doi="10.1000/example",
            venue="Provider-owned venue",
            url="https://provider.example/paper",
            topic_id="underwater",
            topic_name="Underwater acoustics",
        ),
        run_id,
    )


def _create_analysis(client: TestClient, **overrides: object):
    body: dict[str, object] = {
        "job_type": "paper_analysis",
        "idempotency_key": "analysis:doi:10.1000/example:abstract",
        "payload": {
            "canonical_id": "doi:10.1000/example",
            "topic_id": "underwater",
            "evidence_scope": "abstract",
        },
    }
    body.update(overrides)
    return client.post("/api/v2/jobs", json=body)


def _wait_for_job(app, job_id: str, statuses: set[str], timeout: float = 2.5):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        job = app.state.job_repository.get(job_id)
        if job is not None and job.status.value in statuses:
            return job
        sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {statuses}")


def _analysis_count(app) -> int:
    return int(
        app.state.database.connection.execute(
            "SELECT COUNT(*) FROM paper_analyses"
        ).fetchone()[0]
    )


def test_paper_analysis_job_creation_returns_202_and_validates_scope(tmp_path):
    app = create_app(_settings(tmp_path))
    _seed_paper(app)

    with TestClient(app) as client:
        created = _create_analysis(client)
        invalid_scope = _create_analysis(
            client,
            idempotency_key="analysis:invalid-scope",
            payload={
                "canonical_id": "doi:10.1000/example",
                "topic_id": "underwater",
                "evidence_scope": "invented_scope",
            },
        )

    assert created.status_code == 202
    assert created.json()["job_type"] == "paper_analysis"
    assert created.json()["status"] == "queued"
    assert invalid_scope.status_code == 422
    assert "invented_scope" not in invalid_scope.text


def test_paper_analysis_request_rejects_fulltext_and_blank_identifiers_without_enqueueing(
    tmp_path,
):
    app = create_app(_settings(tmp_path))
    _seed_paper(app)

    with TestClient(app) as client:
        fulltext = _create_analysis(
            client,
            idempotency_key="analysis:fulltext",
            payload={
                "canonical_id": "doi:10.1000/example",
                "topic_id": "underwater",
                "evidence_scope": "fulltext",
                "evidence": "unbounded complete paper text",
            },
        )
        blank_canonical = _create_analysis(
            client,
            idempotency_key="analysis:blank-canonical",
            payload={
                "canonical_id": "   ",
                "topic_id": "underwater",
                "evidence_scope": "abstract",
            },
        )
        blank_topic = _create_analysis(
            client,
            idempotency_key="analysis:blank-topic",
            payload={
                "canonical_id": "doi:10.1000/example",
                "topic_id": "   ",
                "evidence_scope": "abstract",
            },
        )
        job_count = app.state.database.connection.execute(
            "SELECT COUNT(*) FROM jobs"
        ).fetchone()[0]

    assert fulltext.status_code == 422
    assert blank_canonical.status_code == 422
    assert blank_topic.status_code == 422
    assert job_count == 0


def test_duplicate_analysis_submission_reuses_the_durable_job(tmp_path):
    app = create_app(_settings(tmp_path))
    _seed_paper(app)

    with TestClient(app) as client:
        first = _create_analysis(client)
        repeated = _create_analysis(
            client,
            payload={
                "canonical_id": "doi:10.1000/example",
                "topic_id": "underwater",
                "evidence_scope": "metadata_only",
            },
        )

    assert first.status_code == repeated.status_code == 202
    assert repeated.json()["job_id"] == first.json()["job_id"]


def test_completed_analysis_job_exposes_a_safe_result_reference_on_readback(tmp_path):
    app = create_app(_settings(tmp_path))
    _seed_paper(app)

    with TestClient(app) as client:
        created = _create_analysis(client)
        assert created.status_code == 202
        app.state.job_worker.run_once()
        completed = _wait_for_job(app, created.json()["job_id"], {"completed"})
        readback = client.get(created.json()["status_url"])

    assert completed.result_reference is not None
    assert completed.result_reference.startswith("paper_analysis:")
    assert readback.status_code == 200
    assert readback.json()["result_reference"] == completed.result_reference
    assert "payload" not in readback.json()


def test_analysis_without_abstract_persists_metadata_only_evidence_scope(tmp_path):
    app = create_app(_settings(tmp_path))
    _seed_paper(app, abstract="")

    with TestClient(app) as client:
        created = _create_analysis(client, idempotency_key="analysis:no-abstract")
        assert created.status_code == 202
        app.state.job_worker.run_once()
        _wait_for_job(app, created.json()["job_id"], {"completed"})
        evidence_scope = app.state.database.connection.execute(
            "SELECT evidence_scope FROM paper_analyses"
        ).fetchone()[0]

    assert evidence_scope == "metadata_only"


def test_real_analysis_handler_cancellation_does_not_persist_after_model_returns(
    tmp_path, monkeypatch
):
    app = create_app(_settings(tmp_path))
    _seed_paper(app)
    entered = Event()
    release = Event()

    with TestClient(app) as client:
        def delayed_analyze(*_args, **_kwargs):
            entered.set()
            assert release.wait(1)
            return {"status": "extractive"}

        monkeypatch.setattr(app.state.paper_analysis_service.analyzer, "analyze", delayed_analyze)
        cancelled = _create_analysis(client, idempotency_key="analysis:cancelled")
        assert cancelled.status_code == 202
        app.state.job_worker.run_once()
        assert entered.wait(1)
        cancelled_readback = client.post(f"{cancelled.json()['status_url']}/cancel")
        release.set()
        cancelled_record = _wait_for_job(app, cancelled.json()["job_id"], {"cancelled"})
        analysis_count = _analysis_count(app)


    assert cancelled_readback.status_code == 200
    assert cancelled_record.result_reference is None
    assert analysis_count == 0


def test_real_analysis_handler_timeout_does_not_persist_after_model_returns(tmp_path, monkeypatch):
    app = create_app(_settings(tmp_path))
    _seed_paper(app)
    entered = Event()
    release = Event()

    with TestClient(app) as client:
        def delayed_analyze(*_args, **_kwargs):
            entered.set()
            assert release.wait(2)
            return {"status": "extractive"}

        monkeypatch.setattr(app.state.paper_analysis_service.analyzer, "analyze", delayed_analyze)
        timed_out = _create_analysis(
            client,
            idempotency_key="analysis:timed-out",
            timeout_seconds=1,
        )
        assert timed_out.status_code == 202
        app.state.job_worker.run_once()
        assert entered.wait(1)
        sleep(1.05)
        app.state.job_worker.run_once()
        release.set()
        timeout_record = _wait_for_job(
            app, timed_out.json()["job_id"], {"queued", "failed"}, timeout=2.5
        )
        analysis_count = _analysis_count(app)

    assert timeout_record.safe_error_code == "timeout"
    assert timeout_record.result_reference is None
    assert analysis_count == 0


def test_owned_llm_client_closes_only_after_a_stopped_worker_attempt_drains(
    tmp_path, monkeypatch
):
    class Runtime:
        gateway = object()
        budget_factory = staticmethod(lambda _request: None)

        def __init__(self) -> None:
            self.closed = Event()

        def close(self) -> None:
            self.closed.set()

    runtime = Runtime()
    monkeypatch.setattr(web, "build_llm_runtime", lambda *_args, **_kwargs: runtime)
    entered = Event()
    release = Event()

    def non_cooperative_handler(_context, _record):
        entered.set()
        assert release.wait(2)

    app = web.create_app(
        _settings(tmp_path), job_handlers={"paper_analysis": non_cooperative_handler}
    )
    with TestClient(app) as client:
        created = _create_analysis(client, idempotency_key="analysis:worker-drain")
        assert created.status_code == 202
        app.state.job_worker.run_once()
        assert entered.wait(1)

    assert runtime.closed.is_set() is False
    release.set()
    assert runtime.closed.wait(1)


def test_analysis_job_never_mutates_provider_owned_canonical_metadata(tmp_path):
    app = create_app(_settings(tmp_path))
    _seed_paper(app)
    columns = "title,abstract,authors_json,publication_date,venue,doi,url,pdf_url,sources_json,source_ids_json"
    before = tuple(
        app.state.database.connection.execute(
            f"SELECT {columns} FROM papers WHERE canonical_id=?", ("doi:10.1000/example",)
        ).fetchone()
    )

    with TestClient(app) as client:
        created = _create_analysis(client)
        assert created.status_code == 202
        app.state.job_worker.run_once()
        _wait_for_job(app, created.json()["job_id"], {"completed"})
        after = tuple(
            app.state.database.connection.execute(
                f"SELECT {columns} FROM papers WHERE canonical_id=?", ("doi:10.1000/example",)
            ).fetchone()
        )
    assert after == before
