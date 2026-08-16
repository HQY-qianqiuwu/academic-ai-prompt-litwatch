from pathlib import Path

import pytest

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.email_mailer import EmailMailer
from litwatch.email_settings import EmailNotConfiguredError, EmailSettings, EmailSettingsStore


def _digest() -> dict[str, object]:
    return {
        "subscription": {"id": "sub-a", "name": "TDOA Weekly"},
        "period": "2026-W33",
        "run": {"new_count": 1, "recommended_count": 1},
        "papers": [
            {
                "title": "Underwater Acoustic TDOA Paper",
                "authors": ["Alice"],
                "year": 2026,
                "venue": "JASA",
                "abstract": "Abstract.",
                "sources": ["openalex"],
                "doi": "10.1000/tdoa",
                "url": "",
                "rank_position": 1,
                "rank_score": 0.9,
                "relevance_score": 0.8,
                "quality_score": 0.7,
            }
        ],
    }


def test_mailer_send_digest_uses_store_credentials(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "email.db")
    store = EmailSettingsStore(database, tmp_path / "smtp-auth.secret")
    store.save(
        EmailSettings(
            recipient_email="me@qq.com", enabled=True,
            smtp_host="smtp.qq.com", smtp_port=465, smtp_username="me@qq.com",
        ),
        auth_code="qq-auth-code",
    )
    captured: dict[str, object] = {}

    def fake_send(settings, subject, html_body, attachment=None):
        captured["settings"] = settings
        captured["subject"] = subject
        captured["attachment"] = attachment

    monkeypatch.setattr("litwatch.email_mailer.send_email", fake_send)
    mailer = EmailMailer(Settings(_env_file=None), store)
    assert mailer.configured() is True
    mailer.send_digest(_digest())
    assert captured["subject"].startswith("LitWatch 每周文献推荐")
    name, payload = captured["attachment"]
    assert name == "weekly-digest.pdf"
    assert payload.startswith(b"%PDF")


def test_mailer_send_test_raises_when_not_configured(tmp_path: Path):
    database = Database(tmp_path / "email.db")
    store = EmailSettingsStore(database, tmp_path / "smtp-auth.secret")
    mailer = EmailMailer(Settings(_env_file=None), store)
    with pytest.raises(EmailNotConfiguredError):
        mailer.send_test()
