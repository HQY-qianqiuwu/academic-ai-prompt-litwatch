(() => {
  "use strict";

  const list = document.querySelector("[data-jobs-list]");
  const state = document.querySelector("[data-jobs-state]");
  const refresh = document.querySelector("[data-refresh-jobs]");
  const pagination = document.querySelector("[data-jobs-pagination]");
  if (!list || !state || !refresh || !pagination) return;

  const t = (key, params = {}) => window.LitWatchI18n.t(key, params);
  const pageLimit = 25;
  let offset = 0;
  const setState = (message) => { state.textContent = message; };
  const text = (tag, value) => { const element = document.createElement(tag); element.textContent = value; return element; };

  const cancelJob = async (job, button) => {
    button.disabled = true;
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
    if (job.cancellation_requested_at) {
      card.append(text("p", t("jobs.cancellationRequested")));
    }
    if (["queued", "running"].includes(job.status) && !job.cancellation_requested_at) {
      const cancel = text("button", t("jobs.cancel"));
      cancel.type = "button";
      cancel.addEventListener("click", () => cancelJob(job, cancel));
      footer.append(cancel);
    }
    card.append(header, id, details, footer);
    return card;
  };

  const renderPagination = (page) => {
    pagination.replaceChildren();
    const previous = text("button", t("jobs.previous"));
    previous.type = "button";
    previous.disabled = page.offset === 0;
    previous.addEventListener("click", () => {
      offset = Math.max(0, offset - pageLimit);
      loadJobs();
    });
    const next = text("button", t("jobs.next"));
    next.type = "button";
    next.disabled = !page.has_more;
    next.addEventListener("click", () => {
      offset += pageLimit;
      loadJobs();
    });
    pagination.append(previous, text("span", t("jobs.page", { start: page.offset + 1, total: page.total })), next);
  };

  async function loadJobs() {
    setState(t("jobs.loading"));
    try {
      const response = await fetch(`/api/v2/jobs?limit=${pageLimit}&offset=${offset}`, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("jobs unavailable");
      const page = await response.json();
      if (!page || !Array.isArray(page.items)) throw new Error("invalid jobs response");
      list.replaceChildren(...page.items.map(jobCard));
      renderPagination(page);
      setState(page.items.length ? t("jobs.ready", { count: page.total }) : t("jobs.empty"));
    } catch (_error) {
      list.replaceChildren();
      pagination.replaceChildren();
      setState(t("jobs.unavailable"));
    }
  }

  refresh.addEventListener("click", loadJobs);
  loadJobs();
})();
