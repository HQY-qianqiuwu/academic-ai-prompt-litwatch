from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from litwatch.cli import app
from litwatch.models import RunSummary


@pytest.mark.parametrize("email_arguments", [[], ["--email"]])
def test_cli_scan_exits_nonzero_when_every_provider_failed(monkeypatch, email_arguments):
    class FailedPipeline:
        def __init__(self, _settings):
            pass

        def run(self, *, days):
            return RunSummary(
                run_id=1,
                started_at="2026-09-14T00:00:00+00:00",
                finished_at="2026-09-14T00:00:01+00:00",
                fetched=0,
                deduplicated=0,
                accepted=0,
                analyzed=0,
                errors=["topic/search: all_providers_failed:rate_limited"],
                scan_status="all_providers_failed",
            ), []

        def close(self):
            pass

    monkeypatch.setattr("litwatch.cli.Pipeline", FailedPipeline)
    monkeypatch.setattr("litwatch.cli._settings", lambda: object())
    monkeypatch.setattr(
        "litwatch.cli.send_email",
        lambda *_args: pytest.fail("failed scan must not send a digest"),
    )

    result = CliRunner().invoke(app, ["scan", "--days", "7", *email_arguments])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["scan_status"] == "all_providers_failed"
