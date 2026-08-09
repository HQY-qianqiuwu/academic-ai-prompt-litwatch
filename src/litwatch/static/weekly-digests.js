(() => {
  const state = document.querySelector("[data-digest-state]");
  const list = document.querySelector("[data-digest-list]");
  const detail = document.querySelector("[data-digest-detail]");
  const params = new URLSearchParams(window.location.search);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[char]);
  const score = (value) => Number.isFinite(value) ? Number(value).toFixed(3) : "—";
  let deliveries = [];

  const renderDetail = (delivery) => {
    const digest = delivery.digest; const run = digest.run; const papers = digest.papers || [];
    detail.innerHTML = `<header><p class="research-kicker">${escapeHtml(digest.period || "Manual run")}</p><h2>${escapeHtml(digest.subscription.name)}</h2><p>${escapeHtml(digest.subscription.topic)}</p><p>Run status: ${escapeHtml(run.status)}</p></header><div class="digest-summary"><span><strong>${run.raw_count}</strong>Found</span><span><strong>${run.dedup_count}</strong>Unique</span><span><strong>${run.historical_duplicates_removed}</strong>Previously Seen</span><span><strong>${run.new_count}</strong>New</span><span><strong>${run.recommended_count}</strong>Recommended</span></div>${digest.empty_message ? `<p class="digest-empty">${escapeHtml(digest.empty_message)}</p>` : papers.map((paper) => `<article class="digest-paper"><h3>${escapeHtml(paper.title)}</h3><div class="digest-paper-meta"><span>${(paper.authors || []).map(escapeHtml).join(", ") || "Authors unavailable"}</span><span>${escapeHtml(paper.year || "Year unavailable")}</span><span>${escapeHtml(paper.venue || "Venue unavailable")}</span><span>Sources: ${(paper.sources || []).map(escapeHtml).join(", ")}</span></div><p>${escapeHtml(paper.abstract || "Abstract unavailable")}</p><div class="digest-scores"><span>Rank ${paper.rank_position}</span><span>Score ${score(paper.rank_score)}</span><span>Relevance ${score(paper.relevance_score)}</span><span>Quality ${score(paper.quality_score)}</span></div>${paper.doi ? `<p>DOI: <a href="https://doi.org/${encodeURIComponent(paper.doi)}" target="_blank" rel="noopener noreferrer">${escapeHtml(paper.doi)}</a></p>` : ""}</article>`).join("")}`;
    document.querySelectorAll(".digest-history").forEach((button) => button.classList.toggle("active", button.dataset.id === delivery.id));
  };

  const load = async () => {
    try {
      const query = params.get("subscription_id") ? `?subscription_id=${encodeURIComponent(params.get("subscription_id"))}` : "";
      const response = await fetch(`/api/v1/deliveries${query}`); if (!response.ok) throw new Error(); deliveries = await response.json();
      state.innerHTML = `<strong>${deliveries.length} historical digest(s)</strong>`;
      if (!deliveries.length) { list.innerHTML = ""; detail.innerHTML = '<p class="digest-empty">No weekly digests are available yet.</p>'; return; }
      list.innerHTML = deliveries.map((item) => `<button class="digest-history" data-id="${item.id}"><strong>${escapeHtml(item.digest.subscription.name)}</strong><br><span>${escapeHtml(new Date(item.attempted_at).toLocaleString())}</span><br><span>${escapeHtml(item.digest.run.status)}</span></button>`).join("");
      const selected = deliveries.find((item) => item.id === params.get("delivery_id")) || deliveries[0]; renderDetail(selected);
    } catch (_) { state.classList.add("digest-error"); state.innerHTML = "<strong>Digest unavailable</strong>"; }
  };
  list.addEventListener("click", (event) => { const button = event.target.closest("button[data-id]"); const selected = deliveries.find((item) => item.id === button?.dataset.id); if (selected) renderDetail(selected); });
  load();
})();
