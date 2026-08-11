# V2.0F AI Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make model and PDF boundaries explicit, consented, bounded, and secret-safe.

**Architecture:** Trusted instructions and untrusted evidence remain separate typed fields. Shared redaction and network validation execute before persistence or external requests.

**Tech Stack:** Python ipaddress/socket/url parsing, httpx transports, pytest.

## Global Constraints

- No broad private-network allowlist.
- No credential, Cookie, Authorization, token, or secret reflection.
- No silent full-text cloud egress.

---

### Task 1: Shared secret redaction and prompt boundary

**Files:**
- Create: `src/litwatch/security.py`
- Modify: `src/litwatch/llm/models.py`
- Modify: `src/litwatch/llm/openai_compatible.py`
- Modify: `src/litwatch/services/jobs.py`
- Test: `tests/test_ai_security.py`

- [ ] **Step 1: Add failing tests with API-key, Bearer, Cookie, URL credential, and prompt-injection payload fixtures; assert persisted errors/traces contain none and evidence cannot create a system-role message.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement `redact_sensitive_text`, allowlisted safe errors, and provider message construction with one trusted system message plus delimited user evidence.**
- [ ] **Step 4: Run security, job, and gateway tests; verify PASS.**
- [ ] **Step 5: Commit with `feat(security): isolate untrusted AI evidence`.**

### Task 2: Harden FullTextExtractor networking

**Files:**
- Modify: `src/litwatch/fulltext.py`
- Reuse: `src/litwatch/provider_security.py`
- Test: `tests/test_fulltext_security.py`

**Interfaces:**
- `FullTextExtractor.extract` validates every URL hop, permits bounded HTTPS redirects, requires PDF content type or signature, and retains `max_bytes`/`max_chars`.

- [ ] **Step 1: Add failing tests for HTTP/credential URL rejection, private/loopback DNS, redirect to private host, redirect limit, wrong content type, oversized stream, timeout, and valid public PDF.**
- [ ] **Step 2: Verify RED against current redirect-following behavior.**
- [ ] **Step 3: Disable automatic redirects and implement validated manual hops with injected resolver/transport.**
- [ ] **Step 4: Run `python -m pytest tests/test_fulltext_security.py tests/test_provider_security.py tests/test_core.py -q`; verify PASS.**
- [ ] **Step 5: Commit with `fix(fulltext): enforce safe PDF network boundary`.**

### Task 3: Security audit gate

**Files:**
- Create: `docs/V2_0_SECURITY_BOUNDARY.md`
- Create: `tests/test_secret_regression.py`
- Modify: `.env.example`

- [ ] **Step 1: Add behavioral tests that create profiles/jobs/analyses/errors and assert serialized API, DB, HTML, and logs exclude configured test secrets.**
- [ ] **Step 2: Verify the test fails if redaction is intentionally bypassed, restore implementation, and verify GREEN.**
- [ ] **Step 3: Document egress, injection, redaction, budgets, and PDF rules with exact settings and safe error codes.**
- [ ] **Step 4: Run security tests, full suite, Ruff, and diff-check.**
- [ ] **Step 5: Commit with `test(security): enforce v2 AI boundary`.**

