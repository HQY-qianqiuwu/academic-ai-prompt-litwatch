(() => {
  "use strict";

  const form = document.querySelector("[data-email-settings-form]");
  const status = document.querySelector("[data-email-settings-status]");
  if (!form || !status) return;

  const request = async (url, options = {}) => {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      ...options,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      const error = new Error(detail.detail || `request failed: ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return response.json();
  };

  const showStatus = (ok, message) => {
    status.className = `settings-state ${ok ? "ready" : "error"}`.trim();
    status.replaceChildren(
      Object.assign(document.createElement("strong"), { textContent: message }),
    );
  };

  const load = async () => {
    try {
      const settings = await request("/api/v1/email-settings");
      form.elements.recipient_email.value = settings.recipient_email;
      form.elements.enabled.checked = settings.enabled;
      showStatus(true, settings.has_auth_code ? "已配置" : "未配置");
    } catch (error) {
      showStatus(false, error.message);
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      recipient_email: form.elements.recipient_email.value.trim(),
      enabled: form.elements.enabled.checked,
    };
    const authCode = form.elements.smtp_auth_code.value.trim();
    if (authCode) payload.smtp_auth_code = authCode;
    const button = form.querySelector("[data-save-email-settings]");
    button.disabled = true;
    try {
      await request("/api/v1/email-settings", { method: "PUT", body: JSON.stringify(payload) });
      form.elements.smtp_auth_code.value = "";
      await load();
    } catch (error) {
      showStatus(false, error.message);
    } finally {
      button.disabled = false;
    }
  });

  form.querySelector("[data-test-email-settings]").addEventListener("click", async () => {
    const button = form.querySelector("[data-test-email-settings]");
    button.disabled = true;
    try {
      const result = await request("/api/v1/email-settings/test", { method: "POST" });
      showStatus(result.ok, result.ok ? "测试邮件已发送" : (result.safe_error || "发送失败"));
    } catch (error) {
      showStatus(false, error.message);
    } finally {
      button.disabled = false;
    }
  });

  load();
})();
