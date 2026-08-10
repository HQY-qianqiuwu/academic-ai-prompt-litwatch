(() => {
  "use strict";
  const i18n = window.LitWatchI18n;
  const t = (key, params = {}) => i18n.t(key, params);
  const state = document.querySelector("[data-radar-state]");
  const list = document.querySelector("[data-radar-list]");
  const editor = document.querySelector("[data-radar-editor]");
  const form = document.querySelector("[data-radar-form]");
  const providerOptions = document.querySelector("[data-radar-provider-options]");
  const providerFieldset = document.querySelector("[data-radar-providers]");
  let radars = [];
  let providers = [];
  let pollTimer = null;
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[char]);
  const dateText = (value) => value ? new Date(value).toLocaleString(i18n.locale()) : t("common.notYet");
  const request = async (url, options = {}) => {
    const response = await fetch(url, {cache:"no-store", headers:{"Content-Type":"application/json"}, ...options});
    if (!response.ok) throw new Error(response.status === 422 ? t("radar.invalid") : response.status === 409 ? t("radar.scanConflict") : t("radar.unavailable"));
    return response.json();
  };
  const setState = (title, error = false) => { state.classList.toggle("status-failed", error); state.innerHTML = `<strong>${escapeHtml(title)}</strong>`; };
  const renderProviders = (selected = []) => {
    providerOptions.innerHTML = providers.filter((item) => item.runnable).map((item) => `<label><input type="checkbox" name="providers" value="${escapeHtml(item.name)}" ${selected.includes(item.name) ? "checked" : ""}> <span translate="no">${escapeHtml(item.display_name)}</span></label>`).join("");
    providerFieldset.disabled = false;
  };
  const render = () => {
    if (!radars.length) { list.innerHTML = `<article class="radar-card"><h2>${escapeHtml(t("radar.empty"))}</h2><p>${escapeHtml(t("radar.emptyBody"))}</p></article>`; return; }
    list.innerHTML = radars.map((item) => { const scanning = item.latest_scan_status === "running"; return `<article class="radar-card"><h2>${escapeHtml(item.name)}</h2><p>${escapeHtml(item.topic)}</p><div class="radar-meta"><span>${item.start_year}–${item.end_year}</span><span>${escapeHtml(t("radar.included", {count:item.paper_count}))}</span><span>${escapeHtml(t("radar.lastScan", {date:dateText(item.last_scan_at)}))}</span><span>${escapeHtml(t("radar.hotCount", {count:item.hot_trend_count}))}</span></div><div class="radar-actions"><a class="research-primary" href="/radars/${encodeURIComponent(item.id)}">${escapeHtml(t("radar.view"))}</a><button class="research-secondary" data-action="scan" data-id="${item.id}" ${scanning ? "disabled" : ""}>${escapeHtml(scanning ? t("radar.scanning") : t("radar.rescan"))}</button><button class="research-secondary" data-action="edit" data-id="${item.id}">${escapeHtml(t("radar.edit"))}</button><button class="research-secondary" data-action="toggle" data-id="${item.id}">${escapeHtml(item.enabled ? t("radar.disable") : t("radar.enable"))}</button></div></article>`; }).join("");
  };
  const openEditor = (item = null) => {
    form.reset(); form.elements.radar_id.value = item?.id || "";
    document.querySelector("[data-editor-title]").textContent = item ? t("radar.editTitle") : t("radar.new");
    const currentYear = new Date().getFullYear();
    form.elements.start_year.value = item?.start_year || currentYear - 9; form.elements.end_year.value = item?.end_year || currentYear;
    if (item) { for (const name of ["name","topic","recent_window_years","search_limit_per_period"]) form.elements[name].value = item[name]; form.elements.keywords.value = item.keywords.join(", "); form.elements.exclude_keywords.value = item.exclude_keywords.join(", "); form.elements.enabled.checked = item.enabled; form.elements.scan_after_create.checked = false; }
    renderProviders(item?.providers || providers.filter((item) => item.runnable && item.default_selected).map((item) => item.name));
    editor.hidden = false; editor.scrollIntoView({behavior:"smooth", block:"start"});
  };
  const load = async () => {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    try { [providers, radars] = await Promise.all([request("/api/v1/providers"), request("/api/v1/radars")]); render(); setState(radars.some((item) => item.latest_scan_status === "running") ? t("radar.scanning") : t("radar.ready", {count:radars.length})); if (location.pathname.endsWith("/new")) openEditor(); }
    catch (error) { setState(error.message, true); }
    finally { if (radars.some((item) => item.latest_scan_status === "running")) pollTimer = setTimeout(load, 2000); }
  };
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); const data = new FormData(form); const id = data.get("radar_id");
    const listValue = (name) => String(data.get(name) || "").split(",").map((value) => value.trim()).filter(Boolean);
    const payload = {name:data.get("name"),topic:data.get("topic"),keywords:listValue("keywords"),exclude_keywords:listValue("exclude_keywords"),providers:data.getAll("providers"),start_year:Number(data.get("start_year")),end_year:Number(data.get("end_year")),recent_window_years:Number(data.get("recent_window_years")),search_limit_per_period:Number(data.get("search_limit_per_period")),enabled:data.get("enabled") === "on"};
    const button = document.querySelector("[data-save-radar]"); button.disabled = true;
    try { const saved = await request(id ? `/api/v1/radars/${id}` : "/api/v1/radars", {method:id ? "PATCH" : "POST",body:JSON.stringify(payload)}); if (!id && data.get("scan_after_create") === "on") await request(`/api/v1/radars/${saved.id}/scan`, {method:"POST"}); editor.hidden = true; await load(); }
    catch (error) { setState(error.message, true); }
    finally { button.disabled = false; }
  });
  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]"); if (!button) return; const item = radars.find((radar) => radar.id === button.dataset.id); if (!item) return;
    if (button.dataset.action === "edit") return openEditor(item); button.disabled = true;
    try { if (button.dataset.action === "toggle") await request(`/api/v1/radars/${item.id}`, {method:"PATCH",body:JSON.stringify({enabled:!item.enabled})}); else { button.textContent = t("radar.scanning"); await request(`/api/v1/radars/${item.id}/scan`, {method:"POST"}); } await load(); }
    catch (error) { setState(error.message, true); }
    finally { button.disabled = false; }
  });
  document.querySelector("[data-new-radar]").addEventListener("click", () => openEditor());
  document.querySelector("[data-cancel-edit]").addEventListener("click", () => { editor.hidden = true; });
  load();
})();
