(() => {
  "use strict";

  const list = document.querySelector("[data-jobs-list]");
  const state = document.querySelector("[data-jobs-state]");
  const refresh = document.querySelector("[data-refresh-jobs]");
  if (!list || !state || !refresh) return;

  const t = (key, params = {}) => window.LitWatchI18n.t(key, params);
  const setState = (message) => { state.textContent = message; };
  const text = (tag, value) => { const element = document.createElement(tag); element.textContent = value; return element; };

  const cancelJob = async (job) => {
    try {
      const response = await fetch(`${job.status_url}/cancel`, { method: "POST", headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("cancel failed");
      await loadJobs();
    } catch (_error) {
      setState(t("jobs.cancelFailed"));
    }
  };

  const jobCard = (job) => {
    const card = document.createElement("article");
    card.className = "job-card";
    const header = document.createElement("header");
    header.append(text("strong", job.job_type), text("span", t("jobs.status", { status: job.status })));
    const id = text("code", job.job_id);
    const details = text("p", `${t("jobs.resultReference")}: ${job.result_reference || t("common.notYet")}`);
    const footer = document.createElement("footer");
    footer.append(text("small", `${t("jobs.attempt")}: ${job.attempt}/${job.max_attempts}`));
    if (["queued", "running"].includes(job.status)) {
      const cancel = text("button", t("jobs.cancel"));
      cancel.type = "button";
      cancel.addEventListener("click", () => cancelJob(job));
      footer.append(cancel);
    }
    card.append(header, id, details, footer);
    return card;
  };

  async function loadJobs() {
    setState(t("jobs.loading"));
    try {
      const response = await fetch("/api/v2/jobs", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("jobs unavailable");
      const jobs = await response.json();
      if (!Array.isArray(jobs)) throw new Error("invalid jobs response");
      list.replaceChildren(...jobs.map(jobCard));
      setState(jobs.length ? t("jobs.ready", { count: jobs.length }) : t("jobs.empty"));
    } catch (_error) {
      list.replaceChildren();
      setState(t("jobs.unavailable"));
    }
  }

  refresh.addEventListener("click", loadJobs);
  loadJobs();
})();
