(() => {
  "use strict";

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
    heading.append(
      textElement("h2", "", capability?.display_name || provider.provider_id),
      textElement("p", "", capability?.supports_anonymous ? "Anonymous access supported" : "API key required"),
    );
    const readiness = textElement(
      "span",
      `credential-state ${provider.credential_configured ? "configured" : "not-configured"}`,
      provider.credential_configured ? "Credential configured" : "No credential configured",
    );
    header.append(heading, readiness);

    const toggles = document.createElement("div");
    toggles.className = "provider-toggles";
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.name = "enabled";
    enabled.checked = provider.enabled;
    const enabledLabel = document.createElement("label");
    enabledLabel.append(enabled, textElement("span", "", "Enabled"));
    const selected = document.createElement("input");
    selected.type = "checkbox";
    selected.name = "default_selected";
    selected.checked = provider.default_selected;
    selected.disabled = !provider.enabled;
    const selectedLabel = document.createElement("label");
    selectedLabel.append(selected, textElement("span", "", "Selected by default"));
    enabled.addEventListener("change", () => {
      selected.disabled = !enabled.checked;
      if (!enabled.checked) selected.checked = false;
    });
    toggles.append(enabledLabel, selectedLabel);

    const baseLabel = textElement("label", "setting-field", "");
    baseLabel.append(textElement("span", "", "Base URL"));
    const baseUrl = document.createElement("input");
    baseUrl.type = "url";
    baseUrl.name = "base_url";
    baseUrl.required = true;
    baseUrl.value = provider.base_url;
    baseLabel.append(baseUrl);

    const keyLabel = textElement("label", "setting-field", "");
    const keyTitle = provider.provider_id === "semantic_scholar"
      ? "API Key (optional BYOK)"
      : "API Key";
    keyLabel.append(textElement("span", "", keyTitle));
    const apiKey = document.createElement("input");
    apiKey.type = "password";
    apiKey.name = "api_key";
    apiKey.autocomplete = "new-password";
    apiKey.placeholder = provider.credential_configured
      ? "Leave blank to keep the configured key"
      : "Leave blank to use anonymous access";
    apiKey.disabled = !provider.credential_reference;
    keyLabel.append(apiKey);

    const actions = document.createElement("div");
    actions.className = "setting-actions";
    const save = textElement("button", "research-primary", "Save Provider");
    save.type = "submit";
    actions.append(save);
    if (provider.credential_reference && provider.credential_configured) {
      const clear = textElement("button", "clear-secret", "Clear configured key");
      clear.type = "button";
      clear.addEventListener("click", async () => {
        if (!window.confirm(`Clear the configured key for ${provider.provider_id}?`)) return;
        clear.disabled = true;
        try {
          await postUpdate({ provider_id: provider.provider_id, clear_secret: true });
          setState("success", "Credential cleared", "The Provider now uses its non-key configuration.");
          await loadSettings();
        } catch (_error) {
          setState("error", "Credential was not cleared", "LitWatch rejected the credential update.");
          clear.disabled = false;
        }
      });
      actions.append(clear);
    }

    card.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!card.reportValidity()) return;
      save.disabled = true;
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
        setState("success", "Provider saved", `${provider.provider_id} configuration was updated.`);
        await loadSettings();
      } catch (error) {
        const message = error.status === 422
          ? "This endpoint or configuration is not allowed."
          : "LitWatch could not save this Provider.";
        setState("error", "Provider was not saved", message);
        save.disabled = false;
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
      setState("success", "Provider settings ready", "Only non-secret configuration is shown.");
    } catch (_error) {
      container.replaceChildren();
      setState("error", "Provider settings unavailable", "Confirm LitWatch is running, then reload this page.");
    }
  };

  loadSettings();
})();
