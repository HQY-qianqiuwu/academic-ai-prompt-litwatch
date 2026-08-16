from pathlib import Path

from litwatch.db import Database
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
