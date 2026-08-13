from __future__ import annotations

import json
import logging
from pathlib import Path
from time import monotonic, sleep

from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.models import Paper
from litwatch.security import redact_sensitive_text
from litwatch.web import create_app

API_KEY_SENTINEL = "task3-synthetic-api-key-17"
BEARER_SENTINEL = "task3-synthetic-bearer-token-17"
COOKIE_SENTINEL = "task3-synthetic-cookie-value-17"
URL_USER_SENTINEL = "task3-synthetic-url-user-17"
URL_PASSWORD_SENTINEL = "task3-synthetic-url-password-17"
SENTINELS = (
    API_KEY_SENTINEL,
    BEARER_SENTINEL,
    COOKIE_SENTINEL,
    URL_USER_SENTINEL,
    URL_PASSWORD_SENTINEL,
)


def _sensitive_detail() -> str:
    return "\n".join(
        (
            f"api_key={API_KEY_SENTINEL}",
            f"Authorization: Bearer {BEARER_SENTINEL}",
            f"Cookie: session={COOKIE_SENTINEL}",
            (
                "Source URL: https://"
                f"{URL_USER_SENTINEL}:{URL_PASSWORD_SENTINEL}@papers.example.test/item"
            ),
        )
    )


def _settings(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text(
        """topics:
  - id: security
    name: Security regression
    query: secret-safe boundaries
""",
        encoding="utf-8",
    )
    return Settings(
        _env_file=None,
        database_path=tmp_path / "security-regression.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
        job_poll_seconds=3_600,
    )


def _wait_for_status(app, job_id: str, status: str) -> object:
    deadline = monotonic() + 2
    while monotonic() < deadline:
        record = app.state.job_repository.get(job_id)
        if record is not None and record.status.value == status:
            return record
        sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {status}")


def _assert_secret_free(*projections: str) -> None:
    for sentinel in SENTINELS:
        assert all(sentinel not in projection for projection in projections)


def test_synthetic_secrets_are_absent_from_public_persistence_html_and_log_projections(
    tmp_path, caplog, monkeypatch
):
    """Breaks if shared credential redaction or safe-error projections are bypassed."""

    app = create_app(
        _settings(tmp_path),
        job_handlers={
            "security_audit": lambda _context, _record: (_ for _ in ()).throw(
                RuntimeError(_sensitive_detail())
            )
        },
        provider_base_url_validator=lambda value: value,
    )
    app.state.database.upsert(
        Paper(
            canonical_id="doi:10.1000/security-regression",
            title="Secret-safe security regression",
            abstract="A safe abstract for the failed-analysis projection.",
            topic_id="security",
            topic_name="Security regression",
        ),
        app.state.database.start_run(),
    )

    def fail_analysis(*_args, **_kwargs):
        raise RuntimeError(_sensitive_detail())

    monkeypatch.setattr(app.state.paper_analysis_service.analyzer, "analyze", fail_analysis)
    caplog.set_level(logging.WARNING, logger="litwatch.security_audit")

    with TestClient(app) as client:
        profile_response = client.post(
            "/api/v1/provider-profiles",
            json={
                "profile_id": "default",
                "providers": [
                    {
                        "provider_id": "semantic_scholar",
                        "api_key": API_KEY_SENTINEL,
                    }
                ],
            },
        )
        failed_job_response = client.post(
            "/api/v2/jobs",
            json={
                "job_type": "security_audit",
                "idempotency_key": "security-audit-failure",
                "payload": {"paper_id": "doi:10.1000/security-regression"},
            },
        )
        analysis_job_response = client.post(
            "/api/v2/jobs",
            json={
                "job_type": "paper_analysis",
                "idempotency_key": "security-audit-analysis",
                "payload": {
                    "canonical_id": "doi:10.1000/security-regression",
                    "topic_id": "security",
                    "evidence_scope": "abstract",
                },
            },
        )
        assert profile_response.status_code == 200
        assert failed_job_response.status_code == analysis_job_response.status_code == 202
        app.state.job_worker.run_once()
        failed_job = _wait_for_status(app, failed_job_response.json()["job_id"], "failed")
        analysis_job = _wait_for_status(app, analysis_job_response.json()["job_id"], "completed")
        failed_job_readback = client.get(failed_job_response.json()["status_url"])
        analysis_job_readback = client.get(analysis_job_response.json()["status_url"])
        html_response = client.get("/provider-settings")
        database_rows = {
            "jobs": [
                dict(row)
                for row in app.state.database.connection.execute(
                    "SELECT * FROM jobs ORDER BY job_id"
                ).fetchall()
            ],
            "analyses": [
                dict(row)
                for row in app.state.database.connection.execute(
                    "SELECT * FROM paper_analyses ORDER BY canonical_id"
                ).fetchall()
            ],
        }

    assert failed_job.safe_error_code == "handler_error"
    assert failed_job.safe_error_message == "job handler failed"
    assert analysis_job.result_reference is not None
    assert failed_job_readback.status_code == analysis_job_readback.status_code == 200
    assert html_response.status_code == 200

    logging.getLogger("litwatch.security_audit").warning(
        "security audit projection=%s", redact_sensitive_text(_sensitive_detail())
    )
    serialized_llm_projection = json.dumps(
        {"untrusted_evidence": redact_sensitive_text(_sensitive_detail())},
        sort_keys=True,
    )

    _assert_secret_free(
        profile_response.text,
        failed_job_readback.text,
        analysis_job_readback.text,
        json.dumps(database_rows, default=str, sort_keys=True),
        html_response.text,
        caplog.text,
        serialized_llm_projection,
    )
