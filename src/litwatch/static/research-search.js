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
    submitButton.textContent = "Searching literature…";
    retryButton.hidden = true;
    summary.hidden = true;
    results.replaceChildren();
    setState("loading", "Searching literature…", "LitWatch is querying the selected Providers.");

    try {
      const response = await fetch("/api/v1/literature/search", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ topic, limit: Number(limitInput.value), providers }),
      });
      if (!response.ok) throw new Error(`search failed with status ${response.status}`);
      const payload = await response.json();
      if (!payload || !Array.isArray(payload.papers)) throw new Error("invalid search response");
      summary.hidden = false;
      summary.textContent = `${payload.paper_count} papers returned`;
      setState("success", "Search complete", `LitWatch returned ${payload.paper_count} papers.`);
      document.dispatchEvent(new CustomEvent("litwatch:search-results", { detail: payload }));
    } catch (_error) {
      setState("error", "Search failed", "LitWatch could not complete this request.");
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
  loadProviders();
})();
