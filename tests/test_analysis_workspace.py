from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.web import create_app


def _settings(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        _env_file=None,
        database_path=tmp_path / "analysis-workspace.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
        job_poll_seconds=3600,
    )


def test_analysis_page_uses_native_required_validation(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/analysis")

    assert response.status_code == 200
    assert "novalidate" not in response.text
    assert 'name="canonical_id" required' in response.text
    assert 'name="topic_id" required' in response.text
    assert "data-analysis-submit" in response.text


def test_jobs_workspace_renders_pending_cancellation_without_another_cancel_button(tmp_path):
    script = Path("src/litwatch/static/jobs-workspace.js").read_text(encoding="utf-8")

    assert "job.cancellation_requested_at" in script
    assert 't("jobs.cancellationRequested")' in script
    assert '!job.cancellation_requested_at' in script
    assert "button.disabled = true" in script


def test_analysis_submission_prevents_duplicate_inflight_requests_and_reuses_retry_key():
    script = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

(async () => {
const listeners = {};
const submitButton = { disabled: false };
const form = {
  addEventListener(name, listener) { listeners[name] = listener; },
  checkValidity() { return true; },
  querySelector() { return submitButton; },
};
const state = { replaceChildren() {}, append() {} };
global.document = {
  querySelector(selector) {
    if (selector === "[data-analysis-form]") return form;
    if (selector === "[data-analysis-state]") return state;
    return null;
  },
  createElement() { return { append() {}, textContent: "" }; },
};
global.window = {
  LitWatchI18n: { t(key) { return key; } },
  crypto: { randomUUID: (() => { let index = 0; return () => `key-${++index}`; })() },
};
let values = {
  canonical_id: "doi:10.1000/example",
  topic_id: "underwater",
  evidence_scope: "abstract",
  evidence: "",
};
global.FormData = class { constructor() {} get(name) { return values[name]; } };
const requests = [];
global.fetch = (_url, options) => new Promise((resolve) => requests.push({ options, resolve }));

vm.runInThisContext(fs.readFileSync(process.argv[1], "utf8"));
const submit = listeners.submit;
const event = { preventDefault() {} };

const first = submit(event);
assert.equal(submitButton.disabled, true);
await submit(event);
assert.equal(requests.length, 1);
requests[0].resolve({ ok: false });
await first;
assert.equal(submitButton.disabled, false);

const retry = submit(event);
assert.equal(requests.length, 2);
assert.equal(
  JSON.parse(requests[0].options.body).idempotency_key,
  JSON.parse(requests[1].options.body).idempotency_key,
);
requests[1].resolve({ ok: true, json: async () => ({ job_id: "job-1", result_reference: null }) });
await retry;

const afterSuccess = submit(event);
assert.equal(requests.length, 3);
assert.notEqual(
  JSON.parse(requests[1].options.body).idempotency_key,
  JSON.parse(requests[2].options.body).idempotency_key,
);
requests[2].resolve({ ok: false });
await afterSuccess;

const retained = JSON.parse(requests[2].options.body).idempotency_key;
values = { ...values, topic_id: "changed-topic" };
listeners.input();
const afterInputChange = submit(event);
assert.equal(requests.length, 4);
assert.notEqual(retained, JSON.parse(requests[3].options.body).idempotency_key);
requests[3].resolve({ ok: false });
await afterInputChange;
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    result = subprocess.run(
        ["node", "-e", script, "src/litwatch/static/analysis-workspace.js"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
