from __future__ import annotations

from litwatch.config import Settings
from litwatch.email_digest import render_html, render_pdf
from litwatch.email_settings import EmailSettingsStore
from litwatch.notifier import send_email


class EmailMailer:
    """Build the send-time SMTP configuration and render the digest email."""

    def __init__(self, settings: Settings, store: EmailSettingsStore) -> None:
        self.settings = settings
        self.store = store

    def configured(self) -> bool:
        return self.store.configured()

    def _runtime_settings(self, email, auth_code: str) -> Settings:
        sender = email.smtp_username or email.recipient_email
        return self.settings.model_copy(
            update={
                "smtp_host": email.smtp_host,
                "smtp_port": email.smtp_port,
                "smtp_username": sender,
                "smtp_password": auth_code,
                "email_from": sender,
                "email_to": email.recipient_email,
            }
        )

    def send_digest(self, digest: dict[str, object]) -> None:
        email = self.store.load()
        auth_code = self.store.load_auth_code()
        subject = (
            f"LitWatch 每周文献推荐 - {digest['subscription']['name']} "
            f"({digest['period']})"
        )
        html_body = render_html(digest)
        pdf = render_pdf(digest)
        send_email(
            self._runtime_settings(email, auth_code),
            subject,
            html_body,
            attachment=("weekly-digest.pdf", pdf),
        )

    def send_test(self) -> None:
        email = self.store.load()
        auth_code = self.store.load_auth_code()
        send_email(
            self._runtime_settings(email, auth_code),
            "LitWatch 测试邮件",
            "<p>这是一封来自 LitWatch 的测试邮件。</p>",
        )
