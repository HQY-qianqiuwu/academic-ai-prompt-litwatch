(() => {
  const i18n = window.LitWatchI18n;
  const t = (key, params = {}) => i18n.t(key, params);
  const state = document.querySelector("[data-digest-state]");
  const list = document.querySelector("[data-digest-list]");
  const detail = document.querySelector("[data-digest-detail]");
  const params = new URLSearchParams(window.location.search);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[char]);
  const score = (value) => Number.isFinite(value) ? Number(value).toFixed(3) : "—";
  let deliveries = [];

  const renderDetail = (delivery) => {
    const digest = delivery.digest; const run = digest.run; const papers = digest.papers || [];
    detail.innerHTML = `<header><p class="research-kicker">${escapeHtml(digest.period || t("digest.manualRun"))}</p><h2>${escapeHtml(digest.subscription.name)}</h2><p>${escapeHtml(digest.subscription.topic)}</p><p>${escapeHtml(t("digest.runStatus", {status:t(`runStatus.${run.status}`)}))}</p></header><div class="digest-summary"><span><strong>${run.raw_count}</strong>${escapeHtml(t("digest.found"))}</span><span><strong>${run.dedup_count}</strong>${escapeHtml(t("digest.unique"))}</span><span><strong>${run.historical_duplicates_removed}</strong>${escapeHtml(t("digest.seen"))}</span><span><strong>${run.new_count}</strong>${escapeHtml(t("digest.new"))}</span><span><strong>${run.recommended_count}</strong>${escapeHtml(t("digest.recommended"))}</span></div>${digest.empty_message ? `<p class="digest-empty">${escapeHtml(t("digest.empty"))}</p>` : papers.map((paper) => `<article class="digest-paper"><h3>${escapeHtml(paper.title)}</h3><div class="digest-paper-meta"><span><strong>${escapeHtml(t("paper.authors"))}:</strong> ${(paper.authors || []).map(escapeHtml).join(", ") || escapeHtml(t("paper.authorsUnavailable"))}</span><span><strong>${escapeHtml(t("paper.year"))}:</strong> ${escapeHtml(paper.year || t("paper.yearUnavailable"))}</span><span><strong>${escapeHtml(t("paper.venue"))}:</strong> ${escapeHtml(paper.venue || t("paper.venueUnavailable"))}</span><span><strong>${escapeHtml(t("paper.sources"))}:</strong> <span translate="no">${(paper.sources || []).map(escapeHtml).join(", ")}</span></span></div><p><strong>${escapeHtml(t("paper.abstract"))}:</strong> ${escapeHtml(paper.abstract || t("paper.abstractUnavailable"))}</p><div class="digest-scores"><span>${escapeHtml(t("paper.rank"))} ${paper.rank_position}</span><span>${escapeHtml(t("paper.rank"))} ${score(paper.rank_score)}</span><span>${escapeHtml(t("paper.relevance"))} ${score(paper.relevance_score)}</span><span>${escapeHtml(t("paper.quality"))} ${score(paper.quality_score)}</span></div>${paper.doi ? `<p>DOI: <a href="https://doi.org/${encodeURIComponent(paper.doi)}" target="_blank" rel="noopener noreferrer">${escapeHtml(paper.doi)}</a></p>` : ""}</article>`).join("")}`;
    document.querySelectorAll(".digest-history").forEach((button) => button.classList.toggle("active", button.dataset.id === delivery.id));
  };

  const load = async () => {
    try {
      const query = params.get("subscription_id") ? `?subscription_id=${encodeURIComponent(params.get("subscription_id"))}` : "";
      const response = await fetch(`/api/v1/deliveries${query}`); if (!response.ok) throw new Error(); deliveries = await response.json();
      state.innerHTML = `<strong>${escapeHtml(t("digest.historyCount", {count:deliveries.length}))}</strong>`;
      if (!deliveries.length) { list.innerHTML = ""; detail.innerHTML = `<p class="digest-empty">${escapeHtml(t("digest.none"))}</p>`; return; }
      list.innerHTML = deliveries.map((item) => `<button class="digest-history" data-id="${item.id}"><strong>${escapeHtml(item.digest.subscription.name)}</strong><br><span>${escapeHtml(new Date(item.attempted_at).toLocaleString(i18n.locale()))}</span><br><span>${escapeHtml(t(`runStatus.${item.digest.run.status}`))}</span></button>`).join("");
      const selected = deliveries.find((item) => item.id === params.get("delivery_id")) || deliveries[0]; renderDetail(selected);
    } catch (_) { state.classList.add("digest-error"); state.innerHTML = `<strong>${escapeHtml(t("digest.unavailable"))}</strong>`; }
  };
  list.addEventListener("click", (event) => { const button = event.target.closest("button[data-id]"); const selected = deliveries.find((item) => item.id === button?.dataset.id); if (selected) renderDetail(selected); });
  load();
})();
