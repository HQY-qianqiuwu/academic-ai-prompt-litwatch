from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from litwatch.db import Database


class EmailSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_email: str = ""
    enabled: bool = False
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_username: str = ""
    has_auth_code: bool = False


class EmailNotConfiguredError(RuntimeError):
    """Raised when email delivery is requested without a configured secret."""


class EmailSettingsStore:
    """Persist public email settings in SQLite and the auth code write-only on disk."""

    def __init__(self, database: Database, secret_path: Path) -> None:
        self.database = database
        self.secret_path = secret_path

    def load(self) -> EmailSettings:
        with self.database.connection:
            row = self.database.connection.execute(
                """
                SELECT recipient_email, enabled, smtp_host, smtp_port, smtp_username
                FROM email_settings WHERE id = 1
                """
            ).fetchone()
        if row is None:
            return EmailSettings()
        values = dict(row)
        values["has_auth_code"] = self.secret_path.exists()
        return EmailSettings.model_validate(values)

    def save(self, settings: EmailSettings, auth_code: str | None = None) -> None:
        with self.database.connection:
            self.database.connection.execute(
                """
                INSERT INTO email_settings(
                    id, recipient_email, enabled, smtp_host, smtp_port, smtp_username
                ) VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    recipient_email = excluded.recipient_email,
                    enabled = excluded.enabled,
                    smtp_host = excluded.smtp_host,
                    smtp_port = excluded.smtp_port,
                    smtp_username = excluded.smtp_username
                """,
                (
                    settings.recipient_email,
                    int(settings.enabled),
                    settings.smtp_host,
                    settings.smtp_port,
                    settings.smtp_username,
                ),
            )
        if auth_code is not None:
            self.secret_path.parent.mkdir(parents=True, exist_ok=True)
            self.secret_path.write_text(auth_code.strip() + "\n", encoding="utf-8")
            if os.name == "nt":
                try:
                    os.chmod(self.secret_path, 0o600)
                except OSError:
                    pass

    def load_auth_code(self) -> str:
        if not self.secret_path.exists():
            raise EmailNotConfiguredError("Email auth code is not configured")
        value = self.secret_path.read_text(encoding="utf-8").strip()
        if not value:
            raise EmailNotConfiguredError("Email auth code is not configured")
        return value

    def configured(self) -> bool:
        settings = self.load()
        return bool(
            settings.enabled
            and settings.recipient_email
            and self.secret_path.exists()
        )
