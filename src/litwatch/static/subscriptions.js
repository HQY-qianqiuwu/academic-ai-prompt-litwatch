(() => {
  const state = document.querySelector("[data-subscription-state]");
  const list = document.querySelector("[data-subscription-list]");
  const editor = document.querySelector("[data-subscription-editor]");
  const form = document.querySelector("[data-subscription-form]");
  const detail = document.querySelector("[data-subscription-detail]");
  const providerFieldset = document.querySelector("[data-subscription-providers]");
  const providerOptions = document.querySelector("[data-subscription-provider-options]");
  let subscriptions = [];
  let providers = [];

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[char]);
  const dateText = (value) => value ? new Date(value).toLocaleString() : "Not yet";
  const setState = (title, message, error = false) => {
    state.classList.toggle("subscription-error", error);
    state.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span>`;
  };
  const safeError = (status) => status === 422 ? "Invalid subscription or schedule." : status === 404 ? "Subscription unavailable." : status === 409 ? "A run is already active." : "The request could not be completed.";

  const request = async (url, options = {}) => {
    const response = await fetch(url, {headers:{"Content-Type":"application/json"}, ...options});
    if (!response.ok) throw new Error(safeError(response.status));
    return response.json();
  };

  const renderProviders = (selected = []) => {
    providerOptions.innerHTML = providers.filter((item) => item.runnable).map((item) => `<label><input type="checkbox" name="providers" value="${escapeHtml(item.name)}" ${selected.includes(item.name) ? "checked" : ""}> ${escapeHtml(item.display_name)}</label>`).join("");
    providerFieldset.disabled = false;
  };

  const render = () => {
    if (!subscriptions.length) {
      list.innerHTML = '<article class="subscription-card"><h2>No subscriptions yet</h2><p>Create one to begin a persistent weekly research watch.</p></article>';
      return;
    }
    list.innerHTML = subscriptions.map((item) => `<article class="subscription-card" data-enabled="${item.enabled}">
      <h2>${escapeHtml(item.name)}</h2><p class="topic">${escapeHtml(item.topic)}</p>
      <div class="subscription-meta"><span>Providers: ${item.providers.map(escapeHtml).join(", ")}</span><span>Weekly: day ${item.weekday}, ${escapeHtml(item.local_time)}</span><span>Last run: ${escapeHtml(dateText(item.last_run_at))}</span><span>Next run: ${escapeHtml(dateText(item.next_run_at))}</span></div>
      <div class="subscription-actions"><button class="research-primary" data-action="run" data-id="${item.id}">Run Now</button><button class="research-secondary" data-action="view" data-id="${item.id}">View</button><button class="research-secondary" data-action="edit" data-id="${item.id}">Edit</button><button class="research-secondary" data-action="toggle" data-id="${item.id}">${item.enabled ? "Disable" : "Enable"}</button></div>
    </article>`).join("");
  };

  const openEditor = (item = null) => {
    form.reset();
    form.elements.subscription_id.value = item?.id || "";
    document.querySelector("[data-editor-title]").textContent = item ? "Edit subscription" : "New subscription";
    if (item) {
      for (const name of ["name","topic","search_limit","recommendation_limit","weekday","local_time","timezone"]) form.elements[name].value = item[name];
      form.elements.keywords.value = item.keywords.join(", ");
      form.elements.enabled.checked = item.enabled;
    }
    renderProviders(item?.providers || providers.filter((p) => p.default_selected && p.runnable).map((p) => p.name));
    editor.hidden = false;
    editor.scrollIntoView({behavior:"smooth", block:"start"});
  };

  const load = async () => {
    try {
      [providers, subscriptions] = await Promise.all([request("/api/v1/providers"), request("/api/v1/subscriptions")]);
      renderProviders(); render(); setState("Subscriptions ready", `${subscriptions.length} saved subscription(s).`);
    } catch (error) { setState("Subscription unavailable", error.message, true); }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const id = data.get("subscription_id");
    const payload = {name:data.get("name"), topic:data.get("topic"), keywords:String(data.get("keywords") || "").split(",").map((v) => v.trim()).filter(Boolean), providers:data.getAll("providers"), search_limit:Number(data.get("search_limit")), recommendation_limit:Number(data.get("recommendation_limit")), frequency:"weekly", weekday:Number(data.get("weekday")), local_time:data.get("local_time"), timezone:data.get("timezone"), enabled:data.get("enabled") === "on"};
    const button = document.querySelector("[data-save-subscription]"); button.disabled = true;
    try { await request(id ? `/api/v1/subscriptions/${id}` : "/api/v1/subscriptions", {method:id ? "PATCH" : "POST", body:JSON.stringify(payload)}); editor.hidden = true; await load(); }
    catch (error) { setState("Invalid schedule", error.message, true); }
    finally { button.disabled = false; }
  });

  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]"); if (!button) return;
    const item = subscriptions.find((entry) => entry.id === button.dataset.id); if (!item) return;
    if (button.dataset.action === "edit") return openEditor(item);
    if (button.dataset.action === "view") { detail.hidden = false; detail.innerHTML = `<strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.topic)}</p><p>Keywords: ${item.keywords.map(escapeHtml).join(", ") || "None"}</p><p><a href="/weekly-digests?subscription_id=${encodeURIComponent(item.id)}">View historical digests</a></p>`; return; }
    button.disabled = true;
    try {
      if (button.dataset.action === "toggle") await request(`/api/v1/subscriptions/${item.id}`, {method:"PATCH",body:JSON.stringify({enabled:!item.enabled})});
      if (button.dataset.action === "run") {
        button.textContent = "Running...";
        const payload = await request(`/api/v1/subscriptions/${item.id}/run`, {method:"POST"});
        const run = payload.run; const runTitle = run.status === "partial_success" ? "Provider partial failure" : `Run ${run.status}`; const digestLink = payload.delivery ? `<p><a href="/weekly-digests?delivery_id=${encodeURIComponent(payload.delivery.id)}">Open Weekly Digest</a></p>` : ""; detail.hidden = false; detail.innerHTML = `<strong>${escapeHtml(runTitle)}</strong><div class="run-summary"><span><strong>${run.raw_count}</strong>Found</span><span><strong>${run.dedup_count}</strong>Unique</span><span><strong>${run.historical_duplicates_removed}</strong>Previously Seen</span><span><strong>${run.new_count}</strong>New</span><span><strong>${run.recommended_count}</strong>Recommended</span></div>${digestLink}`;
      }
      await load();
    } catch (error) { setState(button.dataset.action === "run" ? "Run failed" : "Subscription unavailable", error.message, true); }
    finally { button.disabled = false; if (button.dataset.action === "run") button.textContent = "Run Now"; }
  });

  document.querySelector("[data-new-subscription]").addEventListener("click", () => openEditor());
  document.querySelector("[data-cancel-edit]").addEventListener("click", () => { editor.hidden = true; });
  load();
})();
