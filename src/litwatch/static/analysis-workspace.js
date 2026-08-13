(() => {
  "use strict";

  const form = document.querySelector("[data-analysis-form]");
  const state = document.querySelector("[data-analysis-state]");
  if (!form || !state) return;

  const t = (key, params = {}) => window.LitWatchI18n.t(key, params);
  const submitButton = form.querySelector("[data-analysis-submit]");
  let submitting = false;
  let retryFingerprint = null;
  let retryKey = null;
  const setState = (message, detail = "") => {
    state.replaceChildren();
    const title = document.createElement("strong");
    title.textContent = message;
    state.append(title);
    if (detail) {
      const text = document.createElement("span");
      text.textContent = detail;
      state.append(document.createElement("br"), text);
    }
  };
  const idempotencyKey = () => `analysis:${window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`}`;
  const payloadFromForm = () => {
    const values = new FormData(form);
    const evidenceScope = String(values.get("evidence_scope"));
    const payload = {
      canonical_id: String(values.get("canonical_id") || "").trim(),
      topic_id: String(values.get("topic_id") || "").trim(),
      evidence_scope: evidenceScope,
    };
    const evidence = String(values.get("evidence") || "").trim();
    if (evidenceScope === "fulltext_excerpt" && evidence) payload.evidence = evidence;
    return payload;
  };

  form.addEventListener("input", () => {
    const fingerprint = JSON.stringify(payloadFromForm());
    if (retryFingerprint && retryFingerprint !== fingerprint) {
      retryFingerprint = null;
      retryKey = null;
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }
    if (submitting) return;
    const payload = payloadFromForm();
    const fingerprint = JSON.stringify(payload);
    if (retryFingerprint !== fingerprint) {
      retryFingerprint = fingerprint;
      retryKey = idempotencyKey();
    }
    submitting = true;
    submitButton.disabled = true;
    setState(t("analysis.submitting"));
    try {
      const response = await fetch("/api/v2/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          job_type: "paper_analysis",
          idempotency_key: retryKey,
          payload,
        }),
      });
      if (!response.ok) throw new Error("analysis submission failed");
      const job = await response.json();
      const reference = job.result_reference || t("analysis.pendingResult");
      setState(t("analysis.queued", { jobId: job.job_id }), `${t("analysis.resultReference")}: ${reference}`);
      retryFingerprint = null;
      retryKey = null;
    } catch (_error) {
      setState(t("analysis.failed"));
    } finally {
      submitting = false;
      submitButton.disabled = false;
    }
  });
})();
