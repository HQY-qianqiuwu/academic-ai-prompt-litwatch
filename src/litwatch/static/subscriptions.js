(() => {
  const i18n = window.LitWatchI18n;
  const t = (key, params = {}) => i18n.t(key, params);
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
  const dateText = (value) => value ? new Date(value).toLocaleString(i18n.locale()) : t("common.notYet");
  const setState = (title, message, error = false) => {
    state.classList.toggle("subscription-error", error);
    state.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span>`;
  };
  const safeError = (status) => status === 422 ? t("subscriptions.invalid") : status === 404 ? t("subscriptions.notFound") : status === 409 ? t("subscriptions.activeRun") : t("subscriptions.requestFailed");

  const request = async (url, options = {}) => {
    const response = await fetch(url, {headers:{"Content-Type":"application/json"}, ...options});
    if (!response.ok) throw new Error(safeError(response.status));
    return response.json();
  };

  const renderProviders = (selected = []) => {
    providerOptions.innerHTML = providers.filter((item) => item.runnable).map((item) => `<label><input type="checkbox" name="providers" value="${escapeHtml(item.name)}" ${selected.includes(item.name) ? "checked" : ""}> <span translate="no">${escapeHtml(item.display_name)}</span></label>`).join("");
    providerFieldset.disabled = false;
  };

  const render = () => {
    if (!subscriptions.length) {
      list.innerHTML = `<article class="subscription-card"><h2>${escapeHtml(t("subscriptions.empty"))}</h2><p>${escapeHtml(t("subscriptions.emptyBody"))}</p></article>`;
      return;
    }
    list.innerHTML = subscriptions.map((item) => `<article class="subscription-card" data-enabled="${item.enabled}">
      <h2>${escapeHtml(item.name)}</h2><p class="topic">${escapeHtml(item.topic)}</p>
      <div class="subscription-meta"><span>${escapeHtml(t("subscriptions.providersLabel", {providers:item.providers.join(", ")}))}</span><span>${escapeHtml(t("subscriptions.schedule", {weekday:t(`weekday.${item.weekday}`),time:item.local_time}))}</span><span>${escapeHtml(t("subscriptions.lastRun", {date:dateText(item.last_run_at)}))}</span><span>${escapeHtml(t("subscriptions.nextRun", {date:dateText(item.next_run_at)}))}</span></div>
      <div class="subscription-actions"><button class="research-primary" data-action="run" data-id="${item.id}">${escapeHtml(t("subscriptions.runNow"))}</button><button class="research-secondary" data-action="view" data-id="${item.id}">${escapeHtml(t("subscriptions.view"))}</button><button class="research-secondary" data-action="edit" data-id="${item.id}">${escapeHtml(t("subscriptions.edit"))}</button><button class="research-secondary" data-action="toggle" data-id="${item.id}">${escapeHtml(item.enabled ? t("subscriptions.disable") : t("subscriptions.enable"))}</button></div>
    </article>`).join("");
  };

  const openEditor = (item = null) => {
    form.reset();
    form.elements.subscription_id.value = item?.id || "";
    document.querySelector("[data-editor-title]").textContent = item ? t("subscriptions.editTitle") : t("subscriptions.new");
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
      renderProviders(); render(); setState(t("subscriptions.ready"), t("subscriptions.readyBody", {count:subscriptions.length}));
    } catch (error) { setState(t("subscriptions.unavailable"), error.message, true); }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const id = data.get("subscription_id");
    const payload = {name:data.get("name"), topic:data.get("topic"), keywords:String(data.get("keywords") || "").split(",").map((v) => v.trim()).filter(Boolean), providers:data.getAll("providers"), search_limit:Number(data.get("search_limit")), recommendation_limit:Number(data.get("recommendation_limit")), frequency:"weekly", weekday:Number(data.get("weekday")), local_time:data.get("local_time"), timezone:data.get("timezone"), enabled:data.get("enabled") === "on"};
    const button = document.querySelector("[data-save-subscription]"); button.disabled = true;
    try { await request(id ? `/api/v1/subscriptions/${id}` : "/api/v1/subscriptions", {method:id ? "PATCH" : "POST", body:JSON.stringify(payload)}); editor.hidden = true; await load(); }
    catch (error) { setState(t("subscriptions.invalidSchedule"), error.message, true); }
    finally { button.disabled = false; }
  });

  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]"); if (!button) return;
    const item = subscriptions.find((entry) => entry.id === button.dataset.id); if (!item) return;
    if (button.dataset.action === "edit") return openEditor(item);
    if (button.dataset.action === "view") { detail.hidden = false; detail.innerHTML = `<strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.topic)}</p><p>${escapeHtml(t("subscriptions.keywordsLabel", {keywords:item.keywords.join(", ") || t("common.none")}))}</p><p><a href="/weekly-digests?subscription_id=${encodeURIComponent(item.id)}">${escapeHtml(t("subscriptions.history"))}</a></p>`; return; }
    button.disabled = true;
    try {
      if (button.dataset.action === "toggle") await request(`/api/v1/subscriptions/${item.id}`, {method:"PATCH",body:JSON.stringify({enabled:!item.enabled})});
      if (button.dataset.action === "run") {
        button.textContent = t("subscriptions.running");
        const payload = await request(`/api/v1/subscriptions/${item.id}/run`, {method:"POST"});
        const run = payload.run; const runTitle = run.status === "partial_success" ? t("subscriptions.partial") : t("subscriptions.runResult", {status:t(`runStatus.${run.status}`)}); const digestLink = payload.delivery ? `<p><a href="/weekly-digests?delivery_id=${encodeURIComponent(payload.delivery.id)}">${escapeHtml(t("subscriptions.openDigest"))}</a></p>` : ""; detail.hidden = false; detail.innerHTML = `<strong>${escapeHtml(runTitle)}</strong><div class="run-summary"><span><strong>${run.raw_count}</strong>${escapeHtml(t("digest.found"))}</span><span><strong>${run.dedup_count}</strong>${escapeHtml(t("digest.unique"))}</span><span><strong>${run.historical_duplicates_removed}</strong>${escapeHtml(t("digest.seen"))}</span><span><strong>${run.new_count}</strong>${escapeHtml(t("digest.new"))}</span><span><strong>${run.recommended_count}</strong>${escapeHtml(t("digest.recommended"))}</span></div>${digestLink}`;
      }
      await load();
    } catch (error) { setState(button.dataset.action === "run" ? t("subscriptions.runFailed") : t("subscriptions.unavailable"), error.message, true); }
    finally { button.disabled = false; if (button.dataset.action === "run") button.textContent = t("subscriptions.runNow"); }
  });

  document.querySelector("[data-new-subscription]").addEventListener("click", () => openEditor());
  document.querySelector("[data-cancel-edit]").addEventListener("click", () => { editor.hidden = true; });
  load();
})();
