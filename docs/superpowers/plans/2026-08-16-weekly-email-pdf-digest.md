# Weekly Email PDF Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Monday 09:00, each email-enabled research subscription sends the week's high-quality new papers to the user-configured QQ mailbox as an HTML email with a PDF digest attachment.

**Architecture:** Reuse the existing Subscription/Scheduler/Run/Delivery pipeline. Add a write-only `EmailSettingsStore` (public fields in SQLite, SMTP auth code in `data/smtp-auth.secret`), an `EmailMailer` that renders HTML + PDF (PyMuPDF built-in CJK font) and sends via the existing `notifier.send_email`, and a new `DeliveryService.deliver_email` channel that is idempotent per run and isolated from run/Dashboard failures. A new "邮件设置" web page plus a per-subscription "每周邮件" toggle and Monday-09:00 defaults complete the feature.

**Tech Stack:** Python 3.14 / FastAPI / Jinja2 / vanilla JS / SQLite / smtplib / PyMuPDF (fitz).

## Global Constraints

- Branch: `feat/v2.0-python-native-runtime`. Do NOT create a Stable tag.
- SMTP auth code is write-only: never returned by GET/API, never rendered, never logged, never committed. Secret file lives under `data/` (already gitignored).
- No new third-party dependencies (PyMuPDF is already installed).
- Do not use `git add .`; stage explicit files only.
- Do not modify v1.0/v1.1 DSL, protected `.github` files, or existing Stable tags.
- Existing subscriptions keep their schedules; only new subscriptions default to Monday 09:00.
- Email failure must not change run status or Dashboard delivery.

---

## File Structure

New files:
- `src/litwatch/email_settings.py` — `EmailSettings` model + `EmailSettingsStore` (write-only secret).
- `src/litwatch/email_digest.py` — `render_html(digest) -> str`, `render_pdf(digest) -> bytes`.
- `src/litwatch/email_mailer.py` — `EmailMailer` (configured check, send_digest, send_test).
- `src/litwatch/templates/email_settings.html` — settings page.
- `src/litwatch/static/email-settings.js` — page logic.
- `tests/test_email_settings.py`, `tests/test_email_digest.py` — new tests.

Modified files:
- `src/litwatch/db.py` — migration 11 (email_settings table + subscriptions.email_enabled).
- `src/litwatch/subscriptions.py` — `email_enabled`, Monday 09:00 defaults.
- `src/litwatch/api_models.py` — subscription email field + email settings API models.
- `src/litwatch/subscription_repository.py` — persist `email_enabled`.
- `src/litwatch/services/delivery.py` — extract `_build_digest`, add `deliver_email`.
- `src/litwatch/notifier.py` — optional PDF attachment on `send_email`.
- `src/litwatch/services/subscription_runs.py` — call `deliver_email` after dashboard.
- `src/litwatch/web.py` — wiring, page + API routes.
- `src/litwatch/templates/*.html` (11 files) — nav link to 邮件设置.
- `src/litwatch/templates/subscriptions.html` — email toggle + Monday 09:00 defaults.
- `src/litwatch/static/subscriptions.js` — email toggle payload.
- `src/litwatch/static/i18n.js` — `nav.email`, `subscriptions.emailEnabled` keys.
- `tests/test_delivery.py`, `tests/test_subscription_runs.py`, `tests/test_subscription_ui.py`, `tests/test_local_ui_navigation.py` — extended tests.

---

### Task 1: Schema and Subscription Email Field

**Files:**
- Modify: `src/litwatch/db.py` (append migration 11 to `_MIGRATION_SQL`, after the `paper_analyses` tuple)
- Modify: `src/litwatch/subscriptions.py`
- Modify: `src/litwatch/api_models.py`
- Modify: `src/litwatch/subscription_repository.py`
- Test: `tests/test_email_settings.py` (created in Task 2; here only migration test)

**Interfaces:**
- Produces: `subscriptions.email_enabled` column; `SubscriptionSpec.email_enabled: bool = True`; `SubscriptionUpdateRequest.email_enabled: bool | None`; `SubscriptionResponse.email_enabled: bool`.

- [ ] **Step 1: Write the failing migration + model test**

Create `tests/test_email_settings.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider tests/test_email_settings.py`
Expected: FAIL (no `email_settings` table; default weekday is 6).

- [ ] **Step 3: Implement migration and model changes**

In `src/litwatch/db.py`, append before the closing `)` of `_MIGRATION_SQL`:

```python
    (
        11,
        "email_settings_and_subscription_email",
        """
        CREATE TABLE IF NOT EXISTS email_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            recipient_email TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
            smtp_host TEXT NOT NULL DEFAULT 'smtp.qq.com',
            smtp_port INTEGER NOT NULL DEFAULT 465 CHECK (smtp_port BETWEEN 1 AND 65535),
            smtp_username TEXT NOT NULL DEFAULT ''
        );
        ALTER TABLE subscriptions
            ADD COLUMN email_enabled INTEGER NOT NULL DEFAULT 1
            CHECK (email_enabled IN (0, 1));
        """,
    ),
```

In `src/litwatch/subscriptions.py`:

```python
    weekday: StrictInt = Field(default=0, ge=0, le=6)
    local_time: str = "09:00"
    timezone: str = "Asia/Shanghai"
    enabled: StrictBool = True
    email_enabled: StrictBool = True
```

In `src/litwatch/api_models.py`, add to `SubscriptionUpdateRequest`:

```python
    email_enabled: bool | None = None
```

Add to `SubscriptionResponse`:

```python
    email_enabled: bool
```

In `src/litwatch/subscription_repository.py`:

- `create()`: add `email_enabled` to the INSERT column list and `:email_enabled` to VALUES.
- `update()`: add `email_enabled=:email_enabled,` to the SET clause.
- `_database_values()`: add `"email_enabled": int(subscription.email_enabled),`.
- `_from_row()`: add `"email_enabled": bool(row["email_enabled"]),`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_email_settings.py`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/litwatch/db.py src/litwatch/subscriptions.py src/litwatch/api_models.py src/litwatch/subscription_repository.py tests/test_email_settings.py
git commit -m "feat(email): add email settings schema and subscription email flag"
```

---

### Task 2: EmailSettingsStore (Write-Only Secret)

**Files:**
- Create: `src/litwatch/email_settings.py`
- Modify: `tests/test_email_settings.py`

**Interfaces:**
- Produces: `EmailSettings` (public model), `EmailNotConfiguredError`, `EmailSettingsStore(database, secret_path)` with `load() -> EmailSettings`, `save(settings, auth_code=None)`, `load_auth_code() -> str`, `configured() -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_email_settings.py`:

```python
import pytest

from litwatch.email_settings import (
    EmailNotConfiguredError,
    EmailSettings,
    EmailSettingsStore,
)


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_email_settings.py`
Expected: FAIL (module `litwatch.email_settings` does not exist).

- [ ] **Step 3: Implement `src/litwatch/email_settings.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_email_settings.py`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/litwatch/email_settings.py tests/test_email_settings.py
git commit -m "feat(email): add write-only email settings store"
```

---

### Task 3: HTML + PDF Digest Renderer

**Files:**
- Create: `src/litwatch/email_digest.py`
- Test: `tests/test_email_digest.py`

**Interfaces:**
- Produces: `render_html(digest: dict[str, object]) -> str`; `render_pdf(digest: dict[str, object]) -> bytes` (returns a valid PDF, CJK-safe).
- Consumes: digest dict produced by `DeliveryService._build_digest` (keys `subscription`, `period`, `run`, `papers`; each paper has `title`, `authors`, `year`, `venue`, `abstract`, `sources`, `doi`, `url`, `rank_position`, `rank_score`, `relevance_score`, `quality_score`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_email_digest.py`:

```python
from pathlib import Path

import fitz

from litwatch.email_digest import render_html, render_pdf


DIGEST = {
    "subscription": {"id": "sub-a", "name": "TDOA Weekly", "topic": "underwater acoustic TDOA"},
    "period": "2026-W33",
    "run": {"status": "success", "raw_count": 30, "new_count": 2, "recommended_count": 1},
    "papers": [
        {
            "canonical_id": "doi:10.1000/tdoa",
            "title": "Underwater Acoustic TDOA Paper",
            "authors": ["Alice"],
            "year": 2026,
            "venue": "JASA",
            "abstract": "Provider-backed abstract.",
            "sources": ["openalex"],
            "doi": "10.1000/tdoa",
            "url": "https://example.org/tdoa",
            "rank_position": 1,
            "rank_score": 0.9,
            "relevance_score": 0.8,
            "quality_score": 0.7,
        }
    ],
}


def test_render_html_contains_paper_fields():
    html = render_html(DIGEST)
    assert "Underwater Acoustic TDOA Paper" in html
    assert "10.1000/tdoa" in html
    assert "0.90" in html


def test_render_pdf_is_valid_pdf_with_text():
    payload = render_pdf(DIGEST)
    assert payload.startswith(b"%PDF")
    document = fitz.open(stream=payload, filetype="pdf")
    text = "".join(page.get_text() for page in document)
    assert "Underwater Acoustic TDOA Paper" in text
    assert "10.1000/tdoa" in text


def test_render_pdf_handles_empty_papers():
    empty = {**DIGEST, "papers": []}
    payload = render_pdf(empty)
    assert payload.startswith(b"%PDF")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_email_digest.py`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement `src/litwatch/email_digest.py`**

```python
from __future__ import annotations

import html

import fitz


def render_html(digest: dict[str, object]) -> str:
    subscription = digest["subscription"]
    run = digest["run"]
    cards: list[str] = []
    for paper in digest["papers"]:
        title = html.escape(str(paper["title"]))
        authors = html.escape(", ".join(paper["authors"]))
        venue = html.escape(str(paper.get("venue") or ""))
        year = paper.get("year") or ""
        abstract = html.escape(str(paper.get("abstract") or ""))
        doi = html.escape(str(paper.get("doi") or ""))
        url = html.escape(str(paper.get("url") or ""))
        link = f'<a href="{url}">{title}</a>' if url else title
        cards.append(
            f"""
            <article style="margin:16px 0;padding:16px;border:1px solid #dbe4e8;border-radius:12px">
              <h3 style="margin:0 0 8px">{link}</h3>
              <div style="color:#62737b;font-size:13px">{authors} · {year} · {venue}</div>
              <p style="font-size:14px">{abstract}</p>
              <div style="font-size:12px;color:#0f766e">
                DOI: {doi} · 排名 {paper["rank_position"]} · 综合 {paper["rank_score"]:.2f}
                · 相关 {paper["relevance_score"]:.2f} · 质量 {paper["quality_score"]:.2f}
              </div>
            </article>
            """
        )
    body = "".join(cards) if cards else "<p>本期没有达到阈值的新论文。</p>"
    return f"""<!doctype html><html><body style="font-family:Arial,'Microsoft YaHei',sans-serif;color:#17323a;max-width:760px;margin:auto">
    <h1>LitWatch 每周文献推荐</h1>
    <p>订阅：{html.escape(str(subscription["name"]))} · 周期：{html.escape(str(digest["period"]))}</p>
    <p>新增 {run["new_count"]} 篇，推荐 {run["recommended_count"]} 篇。</p>
    {body}
    </body></html>"""


def render_pdf(digest: dict[str, object]) -> bytes:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    subscription = digest["subscription"]
    run = digest["run"]
    y = 36.0

    def write(text: str, *, size: float = 12, bold: bool = False) -> None:
        nonlocal y
        page.insert_text(
            (36, y),
            text,
            fontsize=size,
            fontname="china-s",
        )
        y += size + 6

    write(f"LitWatch 每周文献推荐 - {subscription['name']}", size=18)
    write(f"周期：{digest['period']}    新增：{run['new_count']}    推荐：{run['recommended_count']}")
    for paper in digest["papers"]:
        if y > 780:
            page = document.new_page(width=595, height=842)
            y = 36.0
        write(f"{paper['rank_position']}. {paper['title']}", size=14)
        authors = ", ".join(paper["authors"])
        write(f"{authors} · {paper.get('year') or ''} · {paper.get('venue') or ''}", size=10)
        write(f"DOI: {paper.get('doi') or ''}    综合: {paper['rank_score']:.2f}"
              f"    相关: {paper['relevance_score']:.2f}    质量: {paper['quality_score']:.2f}", size=10)
        abstract = str(paper.get("abstract") or "")[:300]
        write(abstract, size=10)
        write("", size=6)
    return document.tobytes()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_email_digest.py`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/litwatch/email_digest.py tests/test_email_digest.py
git commit -m "feat(email): render HTML and PDF weekly digest"
```

---

### Task 4: Mailer and Attachment Support

**Files:**
- Modify: `src/litwatch/notifier.py`
- Create: `src/litwatch/email_mailer.py`
- Test: `tests/test_email_mailer.py`

**Interfaces:**
- Produces: `notifier.send_email(settings, subject, html_body, attachment: tuple[str, bytes] | None = None)`; `EmailMailer(settings, store)` with `configured() -> bool`, `send_digest(digest: dict) -> None`, `send_test() -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_email_mailer.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_email_mailer.py`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement**

In `src/litwatch/notifier.py`, change the signature and add the attachment before `send_message`:

```python
def send_email(
    settings: Settings,
    subject: str,
    html_body: str,
    attachment: tuple[str, bytes] | None = None,
) -> None:
    required = [
        settings.smtp_host,
        settings.smtp_username,
        settings.smtp_password,
        settings.email_from,
        settings.email_to,
    ]
    if not all(required):
        raise ValueError("SMTP 配置不完整，请检查 .env")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.email_from
    message["To"] = settings.email_to
    message.set_content("请使用支持 HTML 的邮件客户端查看 LitWatch 文献摘要。")
    message.add_alternative(html_body, subtype="html")
    if attachment is not None:
        filename, payload = attachment
        message.add_attachment(
            payload,
            maintype="application",
            subtype="pdf",
            filename=filename,
        )
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context) as server:
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
```

Create `src/litwatch/email_mailer.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_email_mailer.py`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/litwatch/notifier.py src/litwatch/email_mailer.py tests/test_email_mailer.py
git commit -m "feat(email): add digest mailer with PDF attachment"
```

---

### Task 5: Email Delivery Channel and Run Hook

**Files:**
- Modify: `src/litwatch/services/delivery.py`
- Modify: `src/litwatch/services/subscription_runs.py`
- Test: `tests/test_delivery.py`

**Interfaces:**
- Produces: `DeliveryService(delivery_repository, papers, email_sender: EmailDigestSender | None = None)`; `deliver_email(subscription, run, recommendations) -> Delivery`; `EmailDigestSender` protocol (`configured()`, `send_digest(digest)`).
- Consumes: `EmailMailer` from Task 4.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_delivery.py`:

```python
import smtplib

from litwatch.deliveries import DeliveryChannel, DeliveryStatus
from litwatch.email_mailer import EmailMailer
from litwatch.email_settings import EmailSettings, EmailSettingsStore


class FakeSender:
    def __init__(self, configured=True, error=None):
        self._configured = configured
        self.error = error
        self.sent: list[dict[str, object]] = []

    def configured(self) -> bool:
        return self._configured

    def send_digest(self, digest: dict[str, object]) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(digest)


def test_deliver_email_creates_delivered_delivery_once(tmp_path: Path):
    database = Database(tmp_path / "email.db")
    delivery_service = DeliveryService(
        DeliveryRepository(database),
        HistoricalPaperRepository(database),
        email_sender=FakeSender(),
    )
    subscription = Subscription(
        id="sub-a", name="TDOA Weekly",
        topic="underwater acoustic TDOA localization",
        providers=["openalex"], search_limit=10, recommendation_limit=5,
        weekday=0, local_time="09:00", timezone="Asia/Shanghai",
        email_enabled=True, created_at=NOW, updated_at=NOW,
    )
    run = SubscriptionRun(
        id="run-a", subscription_id="sub-a", run_key="weekly:a",
        trigger=SubscriptionRunTrigger.SCHEDULED, started_at=NOW,
        heartbeat_at=NOW, finished_at=NOW,
        status=SubscriptionRunStatus.SUCCESS,
        new_count=1, recommended_count=1,
    )
    recommendation = Recommendation(
        id="rec-a", run_id="run-a", subscription_id="sub-a",
        canonical_id="doi:10.1000/tdoa", rank_position=1,
        rank_score=0.9, relevance_score=0.8, quality_score=0.7,
        recommended_at=NOW,
    )
    first = delivery_service.deliver_email(subscription, run, [recommendation])
    second = delivery_service.deliver_email(subscription, run, [recommendation])
    assert first.channel is DeliveryChannel.EMAIL
    assert first.status is DeliveryStatus.DELIVERED
    assert second.id == first.id


def test_deliver_email_fails_safely_without_configuration(tmp_path: Path):
    database = Database(tmp_path / "email.db")
    delivery_service = DeliveryService(
        DeliveryRepository(database),
        HistoricalPaperRepository(database),
        email_sender=FakeSender(configured=False),
    )
    subscription = Subscription(
        id="sub-a", name="TDOA Weekly",
        topic="underwater acoustic TDOA localization",
        providers=["openalex"], search_limit=10, recommendation_limit=5,
        weekday=0, local_time="09:00", timezone="Asia/Shanghai",
        email_enabled=True, created_at=NOW, updated_at=NOW,
    )
    run = SubscriptionRun(
        id="run-a", subscription_id="sub-a", run_key="weekly:a",
        trigger=SubscriptionRunTrigger.SCHEDULED, started_at=NOW,
        heartbeat_at=NOW, finished_at=NOW,
        status=SubscriptionRunStatus.SUCCESS,
    )
    delivery = delivery_service.deliver_email(subscription, run, [])
    assert delivery.status is DeliveryStatus.FAILED
    assert delivery.safe_error == "Email not configured"


def test_deliver_email_maps_smtp_auth_failure_to_safe_error(tmp_path: Path):
    database = Database(tmp_path / "email.db")
    delivery_service = DeliveryService(
        DeliveryRepository(database),
        HistoricalPaperRepository(database),
        email_sender=FakeSender(error=smtplib.SMTPAuthenticationError(535, b"auth")),
    )
    subscription = Subscription(
        id="sub-a", name="TDOA Weekly",
        topic="underwater acoustic TDOA localization",
        providers=["openalex"], search_limit=10, recommendation_limit=5,
        weekday=0, local_time="09:00", timezone="Asia/Shanghai",
        email_enabled=True, created_at=NOW, updated_at=NOW,
    )
    run = SubscriptionRun(
        id="run-a", subscription_id="sub-a", run_key="weekly:a",
        trigger=SubscriptionRunTrigger.SCHEDULED, started_at=NOW,
        heartbeat_at=NOW, finished_at=NOW,
        status=SubscriptionRunStatus.SUCCESS,
    )
    delivery = delivery_service.deliver_email(subscription, run, [])
    assert delivery.status is DeliveryStatus.FAILED
    assert delivery.safe_error == "SMTP authentication failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_delivery.py`
Expected: FAIL (signature mismatch; `deliver_email` missing).

- [ ] **Step 3: Implement**

In `src/litwatch/services/delivery.py`:

```python
import smtplib
from typing import Protocol
```

Add the protocol and import `DeliveryChannel` already present:

```python
class EmailDigestSender(Protocol):
    def configured(self) -> bool: ...

    def send_digest(self, digest: dict[str, object]) -> None: ...
```

Change `__init__` to accept `email_sender`:

```python
    def __init__(
        self,
        repository: DeliveryRepository,
        papers: HistoricalPaperRepository,
        *,
        email_sender: EmailDigestSender | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repository = repository
        self.papers = papers
        self.email_sender = email_sender
        self.clock = clock or (lambda: datetime.now(UTC))
        self.id_factory = id_factory or (lambda: uuid4().hex)
```

Extract the digest-building body of `deliver_dashboard` into `_build_digest(subscription, run, recommendations) -> dict[str, object]` (move the existing `cards` + `digest` construction verbatim), then have `deliver_dashboard` call it. Add:

```python
    @staticmethod
    def _safe_email_error(error: Exception) -> str:
        if isinstance(error, smtplib.SMTPAuthenticationError):
            return "SMTP authentication failed"
        if isinstance(error, (smtplib.SMTPException, OSError)):
            return "Email transport failed"
        return "Email delivery failed"

    def deliver_email(
        self,
        subscription: Subscription,
        run: SubscriptionRun,
        recommendations: list[Recommendation],
    ) -> Delivery:
        existing = self.repository.get_for_run(
            run.id, channel=DeliveryChannel.EMAIL
        )
        if existing is not None:
            return existing
        now = self._now()
        digest = self._build_digest(subscription, run, recommendations)
        if (
            self.email_sender is None
            or not subscription.email_enabled
            or not self.email_sender.configured()
        ):
            delivery = Delivery(
                id=self.id_factory(),
                run_id=run.id,
                subscription_id=subscription.id,
                channel=DeliveryChannel.EMAIL,
                status=DeliveryStatus.FAILED,
                digest=digest,
                attempted_at=now,
                safe_error="Email not configured",
            )
            stored, _ = self.repository.create(delivery)
            return stored
        try:
            self.email_sender.send_digest(digest)
        except Exception as error:  # noqa: BLE001 - normalized to allowlist
            delivery = Delivery(
                id=self.id_factory(),
                run_id=run.id,
                subscription_id=subscription.id,
                channel=DeliveryChannel.EMAIL,
                status=DeliveryStatus.FAILED,
                digest=digest,
                attempted_at=now,
                safe_error=self._safe_email_error(error),
            )
        else:
            delivery = Delivery(
                id=self.id_factory(),
                run_id=run.id,
                subscription_id=subscription.id,
                channel=DeliveryChannel.EMAIL,
                status=DeliveryStatus.DELIVERED,
                digest=digest,
                attempted_at=now,
                delivered_at=now,
            )
        stored, _ = self.repository.create(delivery)
        return stored
```

In `src/litwatch/services/subscription_runs.py`, after the `deliver_dashboard` call:

```python
        delivery = (
            self.delivery_service.deliver_dashboard(subscription, run, recommendations)
            if self.delivery_service is not None
            else None
        )
        if self.delivery_service is not None:
            self.delivery_service.deliver_email(subscription, run, recommendations)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_delivery.py tests/test_subscription_runs.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/litwatch/services/delivery.py src/litwatch/services/subscription_runs.py tests/test_delivery.py
git commit -m "feat(email): deliver weekly digest email per subscription run"
```

---

### Task 6: Web UI — Email Settings Page, Subscription Toggle, Defaults

**Files:**
- Modify: `src/litwatch/web.py`
- Modify: `src/litwatch/api_models.py` (email settings API models)
- Create: `src/litwatch/templates/email_settings.html`
- Create: `src/litwatch/static/email-settings.js`
- Modify: `src/litwatch/templates/subscriptions.html`
- Modify: `src/litwatch/static/subscriptions.js`
- Modify: `src/litwatch/static/i18n.js`
- Modify: all other `src/litwatch/templates/*.html` nav blocks (11 files)

**Interfaces:**
- Produces: `GET /email-settings` page; `GET /api/v1/email-settings` -> `EmailSettingsResponse`; `PUT /api/v1/email-settings`; `POST /api/v1/email-settings/test` -> `EmailSettingsTestResponse`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subscription_ui.py` (same imports and `settings_for` helper as the file's existing tests):

```python
def test_email_settings_page_renders(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/email-settings")
    assert response.status_code == 200
    assert "email" in response.text.lower()


def test_email_settings_api_never_returns_secret(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        settings_response = client.put(
            "/api/v1/email-settings",
            json={
                "recipient_email": "me@qq.com",
                "enabled": True,
                "smtp_auth_code": "write-only-code",
            },
        )
        get_body = client.get("/api/v1/email-settings").json()
    assert settings_response.status_code == 200
    body = settings_response.json()
    assert body["recipient_email"] == "me@qq.com"
    assert body["has_auth_code"] is True
    assert "write-only-code" not in settings_response.text
    assert "write-only-code" not in str(get_body)
```

Append to `tests/test_subscription_ui.py`:

```python
def test_subscription_form_has_email_toggle_and_monday_default(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        page = client.get("/subscriptions").text
    assert 'name="email_enabled"' in page
    assert 'value="0" selected' in page
    assert 'value="09:00"' in page
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/test_subscription_ui.py tests/test_local_ui_navigation.py`
Expected: FAIL (route 404, form fields missing).

- [ ] **Step 3: Implement**

In `src/litwatch/api_models.py` add:

```python
class EmailSettingsResponse(BaseModel):
    recipient_email: str
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    has_auth_code: bool

    @classmethod
    def from_settings(cls, settings) -> "EmailSettingsResponse":
        return cls(**settings.model_dump())


class EmailSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_email: str | None = None
    enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_auth_code: str | None = None


class EmailSettingsTestResponse(BaseModel):
    ok: bool
    safe_error: str | None = None
```

In `src/litwatch/web.py`:

- Imports: `EmailSettingsStore`, `EmailSettings`, `EmailSettingsUpdate`, `EmailSettingsResponse`, `EmailSettingsTestResponse`, `EmailMailer`, `EmailNotConfiguredError`.
- In `create_app`, after `delivery_repository`:

```python
    email_settings_store = EmailSettingsStore(
        database, settings.database_path.parent / "smtp-auth.secret"
    )
    email_mailer = EmailMailer(settings, email_settings_store)
    delivery_service = DeliveryService(
        delivery_repository,
        historical_repository,
        email_sender=email_mailer,
    )
```

- Page route (near other page routes):

```python
    @app.get("/email-settings", response_class=HTMLResponse)
    async def email_settings_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="email_settings.html",
            context={},
        )
```

- API routes:

```python
    @app.get("/api/v1/email-settings", response_model=EmailSettingsResponse)
    def get_email_settings() -> EmailSettingsResponse:
        return EmailSettingsResponse.from_settings(email_settings_store.load())

    @app.put("/api/v1/email-settings", response_model=EmailSettingsResponse)
    def update_email_settings(payload: EmailSettingsUpdate) -> EmailSettingsResponse:
        current = email_settings_store.load()
        merged = EmailSettings.model_validate(
            {
                **current.model_dump(),
                **payload.model_dump(exclude_unset=True, exclude={"smtp_auth_code"}),
            }
        )
        email_settings_store.save(merged, auth_code=payload.smtp_auth_code)
        return EmailSettingsResponse.from_settings(email_settings_store.load())

    @app.post("/api/v1/email-settings/test", response_model=EmailSettingsTestResponse)
    def test_email_settings() -> EmailSettingsTestResponse:
        try:
            email_mailer.send_test()
        except EmailNotConfiguredError:
            raise HTTPException(status_code=400, detail="Email not configured") from None
        except Exception as error:  # noqa: BLE001 - normalized
            return EmailSettingsTestResponse(
                ok=False, safe_error=DeliveryService._safe_email_error(error)
            )
        return EmailSettingsTestResponse(ok=True)
```

Create `src/litwatch/templates/email_settings.html` (copy the header/nav/footer structure from `provider_settings.html`, add form fields `recipient_email`, `enabled`, `smtp_auth_code`, buttons Save + Test Send, and a status element).

Create `src/litwatch/static/email-settings.js` that:

- `GET /api/v1/email-settings` on load; populate `recipient_email`, `enabled`, show "已配置/未配置" status; never render the auth code.
- On submit, `PUT /api/v1/email-settings` with `{recipient_email, enabled, smtp_auth_code}` (auth code only if the field is non-empty).
- Test button: `POST /api/v1/email-settings/test`; show `ok` or the `safe_error`.

In `src/litwatch/templates/subscriptions.html`:

- Change weekday default option: `<option value="0" selected data-i18n="weekday.0">星期一</option>` (remove `selected` from value 6).
- Change time default: `<input name="local_time" type="time" value="09:00" required>`.
- Add after the enabled toggle:

```html
          <label class="subscription-toggle"><input name="email_enabled" type="checkbox" checked> <span data-i18n="subscriptions.emailEnabled">每周发送邮件</span></label>
```

In `src/litwatch/static/subscriptions.js`:

- In the edit populate block, after `form.elements.enabled.checked = item.enabled;` add:

```javascript
      form.elements.email_enabled.checked = item.email_enabled !== false;
```

- In the payload object, add:

```javascript
      email_enabled:data.get("email_enabled") === "on",
```

In `src/litwatch/static/i18n.js` add keys (zh/en) for `nav.email` ("邮件设置" / "Email Settings") and `subscriptions.emailEnabled` ("每周发送邮件" / "Email weekly digest").

In every `src/litwatch/templates/*.html` nav block, add before the provider-settings link:

```html
        <a href="/email-settings" data-i18n="nav.email">邮件设置</a>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/test_subscription_ui.py tests/test_local_ui_navigation.py tests/test_v2_acceptance.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/litwatch/web.py src/litwatch/api_models.py src/litwatch/templates src/litwatch/static tests/test_subscription_ui.py tests/test_local_ui_navigation.py
git commit -m "feat(web): add email settings page and subscription email toggle"
```

---

### Task 7: Full Regression, Documentation, and Manual E2E Prep

**Files:**
- Modify: `README.md` (usage section for 邮件设置)
- Modify: `docs/V1_6_WEEKLY_RECOMMENDATIONS.md` (email status from deferred to implemented)
- Test: full suite

- [ ] **Step 1: Run the full automated gates**

Run:

```bash
python -m pytest -q
ruff check src tests
git diff --check
```

Expected: all pass, test count > 604.

- [ ] **Step 2: Update README and delivery docs**

Add a "每周邮件" paragraph in `README.md` describing: fill QQ mailbox + write-only auth code on `/email-settings`, toggle per subscription, Monday 09:00 default, HTML + PDF attachment, secrets stay local.

In `docs/V1_6_WEEKLY_RECOMMENDATIONS.md`, update the Stage 8 section: "Email delivery: IMPLEMENTED (v2.0 weekly email PDF digest)" and keep the write-only constraint statement.

- [ ] **Step 3: Commit docs**

```bash
git add README.md docs/V1_6_WEEKLY_RECOMMENDATIONS.md
git commit -m "docs(email): record weekly email pdf digest delivery"
```

- [ ] **Step 4: Manual E2E checklist (user-run, not automated)**

1. Open `http://127.0.0.1:8000/email-settings`; enter QQ email + SMTP auth code; click 测试发送 and confirm receipt.
2. Create a subscription (defaults Monday 09:00) with 每周发送邮件 on; Run Now; confirm one email with `weekly-digest.pdf`.
3. Restart LitWatch; settings persist, auth code is not shown.
4. Run Now again in the same week; confirm no duplicate email for the same run.

---

## Self-Review Notes

- Every spec requirement maps to a task: write-only store (Task 2), HTML+PDF (Task 3), delivery + isolation + idempotency (Task 5), UI + Monday 09:00 defaults (Task 6), docs + gates (Task 7).
- No placeholders: all new modules include complete code; existing-file edits give exact insert points and snippets.
- Type consistency: `EmailMailer` implements the `EmailDigestSender` protocol (`configured` + `send_digest`); `deliver_email` uses `repository.get_for_run(run.id, channel=DeliveryChannel.EMAIL)` which already supports the channel parameter.
