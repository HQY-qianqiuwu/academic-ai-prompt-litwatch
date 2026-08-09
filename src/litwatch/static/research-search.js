(() => {
  "use strict";

  const i18n = window.LitWatchI18n;
  const t = (key, params = {}) => i18n.t(key, params);
  const form = document.querySelector("[data-search-form]");
  if (!form) return;

  const topicInput = form.elements.topic;
  const limitInput = form.elements.limit;
  const providerPicker = form.querySelector("[data-provider-picker]");
  const providerOptions = form.querySelector("[data-provider-options]");
  const providerHelp = providerPicker.querySelector(".provider-help");
  const submitButton = form.querySelector("[data-search-submit]");
  const state = document.querySelector("[data-search-state]");
  const retryButton = document.querySelector("[data-search-retry]");
  const summary = document.querySelector("[data-search-summary]");
  const results = document.querySelector("[data-search-results]");
  let searching = false;

  const setState = (kind, title, message) => {
    state.className = `search-state ${kind || ""}`.trim();
    state.replaceChildren();
    const strong = document.createElement("strong");
    strong.textContent = title;
    const span = document.createElement("span");
    span.textContent = message;
    state.append(strong, span);
  };

  const providerLabel = (provider) => {
    const label = document.createElement("label");
    label.className = "provider-choice";
    if (!provider.runnable) label.classList.add("unavailable");

    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "providers";
    input.value = provider.name;
    input.checked = Boolean(provider.runnable && provider.default_selected);
    input.disabled = !provider.runnable;

    const text = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = provider.display_name;
    name.setAttribute("translate", "no");
    const status = document.createElement("small");
    status.textContent = provider.runnable ? t("common.available") : t("common.comingLater");
    text.append(name, status);
    label.append(input, text);
    return label;
  };

  const loadProviders = async () => {
    try {
      const response = await fetch("/api/v1/providers", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("provider capabilities unavailable");
      const providers = await response.json();
      if (!Array.isArray(providers)) throw new Error("invalid Provider response");
      providerOptions.replaceChildren(...providers.map(providerLabel));
      providerHelp.textContent = t("search.providersHelp");
      providerPicker.disabled = false;
      submitButton.disabled = false;
    } catch (_error) {
      providerHelp.textContent = t("search.providersUnavailable");
      setState("error", t("search.unavailable"), t("search.unavailableBody"));
      retryButton.hidden = false;
    }
  };

  const selectedProviders = () =>
    [...form.querySelectorAll("input[name='providers']:checked")].map((input) => input.value);

  const textElement = (tag, className, value) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = value;
    return element;
  };

  const safeExternalUrl = (value) => {
    if (!value) return null;
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch (_error) {
      return null;
    }
  };

  const formatScore = (value) =>
    Number.isFinite(Number(value)) ? Number(value).toFixed(3) : t("paper.scoreUnavailable");

  const renderScore = (label, value, title = "") => {
    const score = document.createElement("span");
    score.className = "paper-score";
    if (title) score.title = title;
    score.append(textElement("small", "", label), textElement("strong", "", formatScore(value)));
    return score;
  };

  const renderPaper = (paper, index, ranking) => {
    const card = document.createElement("article");
    card.className = "research-paper-card";
    card.dataset.paperCard = paper.canonical_id;

    const header = document.createElement("header");
    header.className = "paper-rank-row";
    header.append(textElement("span", "paper-rank", `#${index + 1}`));
    const scores = document.createElement("div");
    scores.className = "paper-scores";
    scores.append(
      renderScore(t("paper.rank"), ranking?.rank_score),
      renderScore(t("paper.relevance"), ranking?.relevance_score),
      renderScore(
        t("paper.quality"),
        ranking?.quality_score,
        t("paper.qualityHelp"),
      ),
    );
    header.append(scores);

    const title = document.createElement("h2");
    const normalizedDoi = paper.doi?.replace(/^https?:\/\/(dx\.)?doi\.org\//i, "");
    const paperUrl = safeExternalUrl(paper.url)
      || safeExternalUrl(normalizedDoi ? `https://doi.org/${normalizedDoi}` : null);
    if (paperUrl) {
      const link = document.createElement("a");
      link.href = paperUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = paper.title;
      title.append(link);
    } else {
      title.textContent = paper.title;
    }

    const metadata = document.createElement("div");
    metadata.className = "paper-metadata";
    const metadataItem = (label, value) => {
      const item = document.createElement("span");
      item.append(textElement("strong", "", `${label}: `), document.createTextNode(value));
      return item;
    };
    metadata.append(
      metadataItem(
        t("paper.authors"),
        paper.authors?.length ? paper.authors.join(", ") : t("paper.authorsUnavailable"),
      ),
      metadataItem(t("paper.year"), paper.year ? String(paper.year) : t("paper.yearUnavailable")),
      metadataItem(t("paper.venue"), paper.venue || t("paper.venueUnavailable")),
    );

    const abstract = document.createElement("div");
    abstract.className = "paper-abstract";
    const abstractText = paper.abstract || t("paper.abstractUnavailable");
    abstract.append(textElement("strong", "paper-field-label", t("paper.abstract")));
    abstract.append(textElement("p", "", abstractText));
    if (abstractText.length > 360) {
      abstract.classList.add("collapsed");
      const toggle = textElement("button", "abstract-toggle", t("paper.showMore"));
      toggle.type = "button";
      toggle.addEventListener("click", () => {
        const collapsed = abstract.classList.toggle("collapsed");
        toggle.textContent = collapsed ? t("paper.showMore") : t("paper.showLess");
      });
      abstract.append(toggle);
    }

    const footer = document.createElement("footer");
    const sourceList = document.createElement("div");
    sourceList.className = "paper-sources";
    sourceList.append(textElement("strong", "paper-field-label", `${t("paper.sources")}:`));
    (paper.sources || []).forEach((source) => {
      const badge = textElement("span", "source-badge", source);
      badge.setAttribute("translate", "no");
      sourceList.append(badge);
    });
    footer.append(sourceList);
    if (paperUrl) {
      const external = document.createElement("a");
      external.href = paperUrl;
      external.target = "_blank";
      external.rel = "noopener noreferrer";
      external.textContent = paper.doi ? t("paper.openDoi") : t("paper.openRecord");
      footer.append(external);
    }

    card.append(header, title, metadata, abstract, footer);
    return card;
  };

  const renderPapers = (payload) => {
    const ranking = new Map(
      (payload.diagnostics?.ranking || []).map((item) => [item.canonical_id, item]),
    );
    if (!payload.papers.length) {
      const empty = document.createElement("div");
      empty.className = "research-empty-state";
      empty.append(
        textElement("strong", "", t("search.noPapers")),
        textElement("span", "", t("search.noPapersHint")),
      );
      results.replaceChildren(empty);
      return;
    }
    results.replaceChildren(
      ...payload.papers.map((paper, index) => renderPaper(paper, index, ranking.get(paper.canonical_id))),
    );
  };

  const providerStatusLabels = (status) => t(`providerStatus.${status}`);

  const renderDiagnostics = (payload) => {
    const diagnostics = payload.diagnostics || {};
    const statuses = Array.isArray(payload.provider_status) ? payload.provider_status : [];
    const failedStatuses = statuses.filter((item) => !["success", "empty"].includes(item.status));
    const container = document.createElement("div");
    container.className = "search-diagnostics";

    const headline = document.createElement("div");
    headline.className = "diagnostic-headline";
    headline.append(
      textElement("strong", "", t("diagnostics.shown", { count: payload.paper_count })),
      textElement("span", "", t("diagnostics.query", { query: payload.query })),
    );

    const metrics = document.createElement("div");
    metrics.className = "diagnostic-metrics";
    [
      [t("diagnostics.candidates"), diagnostics.raw_count],
      [t("diagnostics.unique"), diagnostics.dedup_count],
      [t("diagnostics.merged"), diagnostics.duplicates_removed],
    ].forEach(([label, value]) => {
      const metric = document.createElement("span");
      metric.append(textElement("small", "", label), textElement("strong", "", String(value ?? 0)));
      metrics.append(metric);
    });
    container.append(headline, metrics);

    if (failedStatuses.length) {
      container.append(textElement(
        "p",
        "partial-warning",
        t("diagnostics.partial", { count: failedStatuses.length }),
      ));
    }

    const details = document.createElement("details");
    details.className = "provider-diagnostics";
    const detailsSummary = textElement("summary", "", t("diagnostics.details"));
    const statusList = document.createElement("div");
    statusList.className = "provider-status-list";
    statuses.forEach((item) => {
      const row = document.createElement("article");
      row.className = `provider-status status-${item.status}`;
      row.dataset.providerStatus = item.provider;
      row.append(
        textElement("strong", "", item.provider),
        textElement("span", "status-label", providerStatusLabels(item.status)),
        textElement(
          "small",
          "",
          t("diagnostics.returned", {
            count: item.returned_count ?? 0,
            elapsed: item.elapsed_ms ?? 0,
          }),
        ),
      );
      row.querySelector("strong").setAttribute("translate", "no");
      statusList.append(row);
    });
    details.append(detailsSummary, statusList);
    container.append(details);
    summary.replaceChildren(container);
  };

  const errorMessageFor = (error) => {
    if (error.kind === "invalid_response") {
      return [t("search.invalidResponse"), t("search.invalidResponseBody")];
    }
    if (!error.status) {
      return [t("search.unavailable"), t("search.unavailableBody")];
    }
    const messages = {
      400: [t("search.invalidConfig"), t("search.invalidConfigBody")],
      422: [t("search.invalidConfig"), t("search.invalidConfigBody")],
      429: [t("search.rateLimited"), t("search.rateLimitedBody")],
      502: [t("search.providersFailed"), t("search.providersFailedBody")],
      504: [t("search.timedOut"), t("search.timedOutBody")],
    };
    return messages[error.status] || [t("search.failed"), t("search.failedBody")];
  };

  const search = async () => {
    if (searching) return;
    const topic = topicInput.value.trim();
    const providers = selectedProviders();
    if (!topic) {
      topicInput.setCustomValidity(t("search.enterTopic"));
      topicInput.reportValidity();
      return;
    }
    topicInput.setCustomValidity("");
    if (!providers.length) {
      setState("error", t("search.selectProviderTitle"), t("search.selectProviderBody"));
      return;
    }

    searching = true;
    submitButton.disabled = true;
    submitButton.textContent = t("search.searching");
    retryButton.hidden = true;
    summary.hidden = true;
    results.replaceChildren();
    setState("loading", t("search.searching"), t("search.loadingBody"));

    try {
      const response = await fetch("/api/v1/literature/search", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ topic, limit: Number(limitInput.value), providers }),
      });
      if (!response.ok) {
        const error = new Error("search request failed");
        error.status = response.status;
        throw error;
      }
      let payload;
      try {
        payload = await response.json();
      } catch (_error) {
        const invalidResponse = new Error("invalid search response");
        invalidResponse.kind = "invalid_response";
        throw invalidResponse;
      }
      if (!payload || !Array.isArray(payload.papers)) {
        const invalidResponse = new Error("invalid search response");
        invalidResponse.kind = "invalid_response";
        throw invalidResponse;
      }
      summary.hidden = false;
      renderDiagnostics(payload);
      const partial = (payload.provider_status || []).some(
        (item) => !["success", "empty"].includes(item.status),
      );
      if (!payload.paper_count) {
        setState("empty", t("search.noPapers"), t("search.noPapersBody"));
      } else if (partial) {
        setState("warning", t("search.partialTitle"), t("search.partialBody"));
        retryButton.hidden = false;
      } else {
        setState("success", t("search.complete"), t("search.completeCount", { count: payload.paper_count }));
      }
      document.dispatchEvent(new CustomEvent("litwatch:search-results", { detail: payload }));
    } catch (error) {
      const [title, message] = errorMessageFor(error);
      setState("error", title, message);
      retryButton.hidden = false;
    } finally {
      searching = false;
      submitButton.disabled = false;
      submitButton.textContent = t("search.submit");
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    search();
  });
  retryButton.addEventListener("click", search);
  topicInput.addEventListener("input", () => topicInput.setCustomValidity(""));
  document.addEventListener("litwatch:search-results", (event) => renderPapers(event.detail));
  loadProviders();
})();
