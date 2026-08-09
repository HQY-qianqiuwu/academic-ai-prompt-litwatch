(() => {
  "use strict";

  const i18n = window.LitWatchI18n;
  const t = (key, params = {}) => i18n.t(key, params);
  const container = document.querySelector("[data-provider-settings]");
  const state = document.querySelector("[data-settings-state]");
  if (!container || !state) return;

  let profileId = "default";
  let capabilities = new Map();

  const textElement = (tag, className, value) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = value;
    return element;
  };

  const setState = (kind, title, message) => {
    state.className = `settings-state ${kind || ""}`.trim();
    state.replaceChildren(
      textElement("strong", "", title),
      textElement("span", "", message),
    );
  };

  const postUpdate = async (providerUpdate) => {
    const response = await fetch("/api/v1/provider-profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ profile_id: profileId, providers: [providerUpdate] }),
    });
    if (!response.ok) {
      const error = new Error("provider profile update failed");
      error.status = response.status;
      throw error;
    }
    return response.json();
  };

  const providerCard = (provider) => {
    const capability = capabilities.get(provider.provider_id);
    const card = document.createElement("form");
    card.className = "provider-setting-card";
    card.dataset.providerSetting = provider.provider_id;

    const header = document.createElement("header");
    const heading = document.createElement("div");
    const providerName = textElement("h2", "", capability?.display_name || provider.provider_id);
    providerName.setAttribute("translate", "no");
    heading.append(
      providerName,
      textElement("p", "", capability?.supports_anonymous ? t("settings.anonymous") : t("settings.keyRequired")),
    );
    const readiness = textElement(
      "span",
      `credential-state ${provider.credential_configured ? "configured" : "not-configured"}`,
      provider.credential_configured ? t("settings.configured") : t("settings.notConfigured"),
    );
    header.append(heading, readiness);

    const toggles = document.createElement("div");
    toggles.className = "provider-toggles";
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.name = "enabled";
    enabled.checked = provider.enabled;
    const enabledLabel = document.createElement("label");
    enabledLabel.append(enabled, textElement("span", "", t("settings.enabled")));
    const selected = document.createElement("input");
    selected.type = "checkbox";
    selected.name = "default_selected";
    selected.checked = provider.default_selected;
    selected.disabled = !provider.enabled;
    const selectedLabel = document.createElement("label");
    selectedLabel.append(selected, textElement("span", "", t("settings.defaultSelected")));
    enabled.addEventListener("change", () => {
      selected.disabled = !enabled.checked;
      if (!enabled.checked) selected.checked = false;
    });
    toggles.append(enabledLabel, selectedLabel);

    const baseLabel = textElement("label", "setting-field", "");
    baseLabel.append(textElement("span", "", t("settings.baseUrl")));
    const baseUrl = document.createElement("input");
    baseUrl.type = "url";
    baseUrl.name = "base_url";
    baseUrl.required = true;
    baseUrl.value = provider.base_url;
    baseLabel.append(baseUrl);

    const keyLabel = textElement("label", "setting-field", "");
    const keyTitle = provider.provider_id === "semantic_scholar"
      ? t("settings.optionalByok")
      : t("settings.apiKey");
    keyLabel.append(textElement("span", "", keyTitle));
    const apiKey = document.createElement("input");
    apiKey.type = "password";
    apiKey.name = "api_key";
    apiKey.autocomplete = "new-password";
    apiKey.placeholder = provider.credential_configured
      ? t("settings.keepKey")
      : t("settings.anonymousPlaceholder");
    apiKey.disabled = !provider.credential_reference;
    keyLabel.append(apiKey);

    const actions = document.createElement("div");
    actions.className = "setting-actions";
    const save = textElement("button", "research-primary", t("settings.save"));
    save.type = "submit";
    actions.append(save);
    if (provider.credential_reference && provider.credential_configured) {
      const clear = textElement("button", "clear-secret", t("settings.clear"));
      clear.type = "button";
      clear.addEventListener("click", async () => {
        if (!window.confirm(t("settings.clearConfirm", { provider: provider.provider_id }))) return;
        clear.disabled = true;
        try {
          await postUpdate({ provider_id: provider.provider_id, clear_secret: true });
          setState("success", t("settings.cleared"), t("settings.clearedBody"));
          await loadSettings();
        } catch (_error) {
          setState("error", t("settings.clearFailed"), t("settings.clearFailedBody"));
          clear.disabled = false;
        }
      });
      actions.append(clear);
    }

    card.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!card.reportValidity()) return;
      save.disabled = true;
      save.textContent = t("settings.saving");
      const update = {
        provider_id: provider.provider_id,
        enabled: enabled.checked,
        default_selected: selected.checked,
        base_url: baseUrl.value.trim(),
      };
      if (apiKey.value.trim()) update.api_key = apiKey.value.trim();
      try {
        await postUpdate(update);
        apiKey.value = "";
        setState("success", t("settings.saved"), t("settings.savedBody", { provider: provider.provider_id }));
        await loadSettings();
      } catch (error) {
        const message = error.status === 422
          ? t("settings.invalidEndpoint")
          : t("settings.saveUnavailable");
        setState("error", t("settings.saveFailed"), message);
        save.disabled = false;
        save.textContent = t("settings.save");
      }
    });

    card.append(header, toggles, baseLabel, keyLabel, actions);
    return card;
  };

  const loadSettings = async () => {
    try {
      const [capabilityResponse, profileResponse] = await Promise.all([
        fetch("/api/v1/providers", { headers: { Accept: "application/json" } }),
        fetch("/api/v1/provider-profiles", { headers: { Accept: "application/json" } }),
      ]);
      if (!capabilityResponse.ok || !profileResponse.ok) throw new Error("settings unavailable");
      const capabilityPayload = await capabilityResponse.json();
      const profilePayload = await profileResponse.json();
      const profile = profilePayload.find((item) => item.profile_id === "default") || profilePayload[0];
      if (!profile || !Array.isArray(profile.providers)) throw new Error("invalid settings response");
      profileId = profile.profile_id;
      capabilities = new Map(capabilityPayload.map((item) => [item.name, item]));
      container.replaceChildren(...profile.providers.map(providerCard));
      setState("success", t("settings.ready"), t("settings.readyBody"));
    } catch (_error) {
      container.replaceChildren();
      setState("error", t("settings.unavailable"), t("settings.unavailableBody"));
    }
  };

  loadSettings();
})();
