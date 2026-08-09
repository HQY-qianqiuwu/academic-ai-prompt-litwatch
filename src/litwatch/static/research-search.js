(() => {
  "use strict";

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
    const status = document.createElement("small");
    status.textContent = provider.runnable ? "Available" : "Coming later";
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
      providerHelp.textContent = "Choose the sources LitWatch should search.";
      providerPicker.disabled = false;
      submitButton.disabled = false;
    } catch (_error) {
      providerHelp.textContent = "Provider capabilities could not be loaded.";
      setState("error", "LitWatch service unavailable", "Reload the page and try again.");
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
    Number.isFinite(Number(value)) ? Number(value).toFixed(3) : "Not available";

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
      renderScore("Rank", ranking?.rank_score),
      renderScore("Relevance", ranking?.relevance_score),
      renderScore(
        "Quality",
        ranking?.quality_score,
        "Metadata completeness and multi-source evidence; not journal prestige",
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

    const metadata = document.createElement("p");
    metadata.className = "paper-metadata";
    const metadataParts = [];
    metadataParts.push(
      paper.authors?.length ? paper.authors.join(", ") : "Authors unavailable",
    );
    if (paper.year) metadataParts.push(String(paper.year));
    if (paper.venue) metadataParts.push(paper.venue);
    metadata.textContent = metadataParts.join(" · ");

    const abstract = document.createElement("div");
    abstract.className = "paper-abstract";
    const abstractText = paper.abstract || "Abstract unavailable.";
    abstract.append(textElement("p", "", abstractText));
    if (abstractText.length > 360) {
      abstract.classList.add("collapsed");
      const toggle = textElement("button", "abstract-toggle", "Show more");
      toggle.type = "button";
      toggle.addEventListener("click", () => {
        const collapsed = abstract.classList.toggle("collapsed");
        toggle.textContent = collapsed ? "Show more" : "Show less";
      });
      abstract.append(toggle);
    }

    const footer = document.createElement("footer");
    const sourceList = document.createElement("div");
    sourceList.className = "paper-sources";
    (paper.sources || []).forEach((source) => {
      sourceList.append(textElement("span", "source-badge", source));
    });
    footer.append(sourceList);
    if (paperUrl) {
      const external = document.createElement("a");
      external.href = paperUrl;
      external.target = "_blank";
      external.rel = "noopener noreferrer";
      external.textContent = paper.doi ? "Open DOI" : "Open source record";
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
        textElement("strong", "", "No papers found"),
        textElement("span", "", "Try a broader topic or select another available Provider."),
      );
      results.replaceChildren(empty);
      return;
    }
    results.replaceChildren(
      ...payload.papers.map((paper, index) => renderPaper(paper, index, ranking.get(paper.canonical_id))),
    );
  };

  const providerStatusLabels = {
    success: "Success",
    empty: "No results",
    rate_limited: "Rate limited",
    auth_error: "Authentication required",
    timeout: "Timed out",
    upstream_error: "Provider unavailable",
    parse_error: "Invalid provider response",
  };

  const renderDiagnostics = (payload) => {
    const diagnostics = payload.diagnostics || {};
    const statuses = Array.isArray(payload.provider_status) ? payload.provider_status : [];
    const failedStatuses = statuses.filter((item) => !["success", "empty"].includes(item.status));
    const container = document.createElement("div");
    container.className = "search-diagnostics";

    const headline = document.createElement("div");
    headline.className = "diagnostic-headline";
    headline.append(
      textElement("strong", "", `${payload.paper_count} papers shown`),
      textElement("span", "", `Query: ${payload.query}`),
    );

    const metrics = document.createElement("div");
    metrics.className = "diagnostic-metrics";
    [
      ["Candidates", diagnostics.raw_count],
      ["Unique", diagnostics.dedup_count],
      ["Duplicates removed", diagnostics.duplicates_removed],
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
        `${failedStatuses.length} Provider request(s) had issues; successful results remain available.`,
      ));
    }

    const details = document.createElement("details");
    details.className = "provider-diagnostics";
    const detailsSummary = textElement("summary", "", "Provider diagnostics");
    const statusList = document.createElement("div");
    statusList.className = "provider-status-list";
    statuses.forEach((item) => {
      const row = document.createElement("article");
      row.className = `provider-status status-${item.status}`;
      row.dataset.providerStatus = item.provider;
      row.append(
        textElement("strong", "", item.provider),
        textElement("span", "status-label", providerStatusLabels[item.status] || "Unavailable"),
        textElement(
          "small",
          "",
          `${item.returned_count ?? 0} returned · ${item.elapsed_ms ?? 0} ms`,
        ),
      );
      statusList.append(row);
    });
    details.append(detailsSummary, statusList);
    container.append(details);
    summary.replaceChildren(container);
  };

  const errorMessageFor = (error) => {
    if (error.kind === "invalid_response") {
      return ["Invalid response from LitWatch", "Retry the search or restart the local service."];
    }
    if (!error.status) {
      return ["LitWatch service unavailable", "Confirm the local service is running, then retry."];
    }
    const messages = {
      400: ["Search request needs attention", "Check the topic and Provider selection."],
      422: ["Search request needs attention", "Check the topic and Provider selection."],
      429: ["Search is temporarily rate limited", "Wait briefly, then retry the request."],
      502: ["Literature Providers are unavailable", "The selected Providers could not complete the search."],
      504: ["Literature search timed out", "The selected Providers took too long to respond."],
    };
    return messages[error.status] || ["Search failed", "LitWatch could not complete this request."];
  };

  const search = async () => {
    if (searching) return;
    const topic = topicInput.value.trim();
    const providers = selectedProviders();
    if (!topic) {
      topicInput.setCustomValidity("Enter a research topic.");
      topicInput.reportValidity();
      return;
    }
    topicInput.setCustomValidity("");
    if (!providers.length) {
      setState("error", "Select at least one Provider", "Choose an available source to search.");
      return;
    }

    searching = true;
    submitButton.disabled = true;
    submitButton.textContent = "Searching literature...";
    retryButton.hidden = true;
    summary.hidden = true;
    results.replaceChildren();
    setState("loading", "Searching literature...", "LitWatch is querying the selected Providers.");

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
        setState("empty", "No papers found", "The Providers completed the search without matching papers.");
      } else if (partial) {
        setState("warning", "Search complete with Provider issues", "Available papers are shown below.");
        retryButton.hidden = false;
      } else {
        setState("success", "Search complete", `LitWatch returned ${payload.paper_count} papers.`);
      }
      document.dispatchEvent(new CustomEvent("litwatch:search-results", { detail: payload }));
    } catch (error) {
      const [title, message] = errorMessageFor(error);
      setState("error", title, message);
      retryButton.hidden = false;
    } finally {
      searching = false;
      submitButton.disabled = false;
      submitButton.textContent = "Search Literature";
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
