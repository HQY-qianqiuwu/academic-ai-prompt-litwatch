from pathlib import Path

import pytest

from litwatch.db import Database
from litwatch.email_settings import (
    EmailNotConfiguredError,
    EmailSettings,
    EmailSettingsStore,
)
from litwatch.subscriptions import SubscriptionSpec


def test_migration_11_creates_email_tables(tmp_path: Path):
    database = Database(tmp_path / "email.db")
    with database.connection:
        columns = {
            row["name"]
            for row in database.connection.execute(
                "PRAGMA table_info(email_settings)"
            ).fetchall()
        }
        sub_columns = {
            row["name"]
            for row in database.connection.execute(
                "PRAGMA table_info(subscriptions)"
            ).fetchall()
        }
    assert {"id", "recipient_email", "enabled", "smtp_host", "smtp_port"} <= columns
    assert "email_enabled" in sub_columns


def test_subscription_spec_defaults_to_monday_0900_email_on():
    spec = SubscriptionSpec(
        name="TDOA",
        topic="underwater acoustic TDOA localization",
        providers=["openalex"],
    )
    assert spec.weekday == 0
    assert spec.local_time == "09:00"
    assert spec.email_enabled is True


def test_store_round_trips_public_fields_and_never_exposes_secret(tmp_path: Path):
    database = Database(tmp_path / "email.db")
    store = EmailSettingsStore(database, tmp_path / "smtp-auth.secret")
    store.save(
        EmailSettings(
            recipient_email="me@qq.com",
            enabled=True,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="me@qq.com",
        ),
        auth_code="qq-auth-code",
    )
    loaded = store.load()
    assert loaded.recipient_email == "me@qq.com"
    assert loaded.has_auth_code is True
    assert "auth_code" not in loaded.model_dump()
    assert "qq-auth-code" not in str(loaded.model_dump())


def test_store_secret_is_overwritable_and_readable_only_for_send(tmp_path: Path):
    database = Database(tmp_path / "email.db")
    store = EmailSettingsStore(database, tmp_path / "smtp-auth.secret")
    store.save(EmailSettings(recipient_email="a@qq.com"), auth_code="first")
    store.save(EmailSettings(recipient_email="a@qq.com"), auth_code="second")
    assert store.load_auth_code() == "second"


def test_configured_requires_recipient_enabled_and_secret(tmp_path: Path):
    database = Database(tmp_path / "email.db")
    store = EmailSettingsStore(database, tmp_path / "smtp-auth.secret")
    assert store.configured() is False
    store.save(EmailSettings(recipient_email="a@qq.com", enabled=True), auth_code="code")
    assert store.configured() is True


def test_load_auth_code_raises_when_missing(tmp_path: Path):
    database = Database(tmp_path / "email.db")
    store = EmailSettingsStore(database, tmp_path / "smtp-auth.secret")
    with pytest.raises(EmailNotConfiguredError):
        store.load_auth_code()
