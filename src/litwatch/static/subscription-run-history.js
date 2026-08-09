(() => {
  "use strict";

  const i18n = window.LitWatchI18n;
  const t = (key, params = {}) => i18n.t(key, params);
  const subscriptionId = document.body.dataset.subscriptionId;
  const state = document.querySelector("[data-run-history-state]");
  const list = document.querySelector("[data-run-history-list]");
  if (!subscriptionId || !state || !list) return;

  const escapeHtml = (value) => String(value ?? "").replace(
    /[&<>"']/g,
    (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character],
  );
  const dateText = (value) => value
    ? new Date(value).toLocaleString(i18n.locale())
    : t("common.notYet");
  const setState = (title, message, error = false) => {
    state.classList.toggle("subscription-error", error);
    state.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span>`;
  };
  const request = async (url) => {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error();
    return response.json();
  };

  const providerRows = (statuses) => {
    if (!Array.isArray(statuses) || !statuses.length) {
      return `<p class="run-provider-empty">${escapeHtml(t("runs.noProviderStatus"))}</p>`;
    }
    return `<div class="run-provider-list">${statuses.map((provider) => `<span><strong translate="no">${escapeHtml(provider.provider)}</strong><b>${escapeHtml(t(`providerStatus.${provider.status}`))}</b><small>${escapeHtml(t("runs.providerReturned", { count: provider.returned_count ?? 0 }))}</small></span>`).join("")}</div>`;
  };

  const render = (runs, deliveries) => {
    const deliveryByRun = new Map(deliveries.map((delivery) => [delivery.run_id, delivery]));
    if (!runs.length) {
      list.innerHTML = `<article class="subscription-card"><p>${escapeHtml(t("runs.empty"))}</p></article>`;
      return;
    }
    list.innerHTML = runs.map((run) => {
      const delivery = deliveryByRun.get(run.id);
      const digestLink = delivery
        ? `<a class="research-secondary" href="/weekly-digests?delivery_id=${encodeURIComponent(delivery.id)}">${escapeHtml(t("runs.viewDigest"))}</a>`
        : "";
      return `<article class="run-history-card" data-run-id="${escapeHtml(run.id)}">
        <header><div><strong>${escapeHtml(t("runs.started", { date: dateText(run.started_at) }))}</strong><span>${escapeHtml(t("runs.finished", { date: dateText(run.finished_at) }))}</span></div><b class="run-status status-${escapeHtml(run.status)}">${escapeHtml(t("runs.status", { status: t(`runStatus.${run.status}`) }))}</b></header>
        <div class="run-summary"><span><strong>${run.raw_count}</strong>${escapeHtml(t("runs.candidates"))}</span><span><strong>${run.dedup_count}</strong>${escapeHtml(t("runs.unique"))}</span><span><strong>${run.historical_duplicates_removed}</strong>${escapeHtml(t("runs.seen"))}</span><span><strong>${run.new_count}</strong>${escapeHtml(t("runs.new"))}</span><span><strong>${run.recommended_count}</strong>${escapeHtml(t("runs.recommended"))}</span></div>
        <details class="run-provider-status"><summary>${escapeHtml(t("runs.providerStatus"))}</summary>${providerRows(run.provider_status)}</details>
        ${digestLink}
      </article>`;
    }).join("");
  };

  const load = async () => {
    try {
      const [runs, deliveries] = await Promise.all([
        request(`/api/v1/subscriptions/${encodeURIComponent(subscriptionId)}/runs`),
        request(`/api/v1/deliveries?subscription_id=${encodeURIComponent(subscriptionId)}`),
      ]);
      render(runs, deliveries);
      setState(t("runs.ready"), t("runs.readyBody", { count: runs.length }));
    } catch (_error) {
      list.replaceChildren();
      setState(t("runs.unavailable"), t("subscriptions.requestFailed"), true);
    }
  };

  load();
})();
