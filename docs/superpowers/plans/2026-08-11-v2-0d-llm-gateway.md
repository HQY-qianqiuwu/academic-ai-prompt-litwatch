# V2.0D LLM Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put all model transport, structured parsing, usage, cost, retry, and safe-error behavior behind one Python gateway.

**Architecture:** `PaperAnalyzer` retains research semantics and delegates model transport to an injected `LLMGateway`; only one OpenAI-compatible provider is implemented.

**Tech Stack:** Pydantic, httpx, pytest-httpx.

## Global Constraints

- Business code must not import a vendor SDK.
- Finite retry only for timeout, 429, and 5xx.
- No key/header/raw credential in logs, persistence, or errors.

---

### Task 1: Typed gateway/provider contracts

**Files:**
- Create: `src/litwatch/llm/__init__.py`
- Create: `src/litwatch/llm/models.py`
- Create: `src/litwatch/llm/gateway.py`
- Create: `src/litwatch/llm/openai_compatible.py`
- Test: `tests/test_llm_gateway.py`

**Interfaces:**
- `LLMRequest`, `LLMResponse`, `LLMUsage`, `LLMBudget`, `LLMResult`, `LLMErrorCode`.
- `LLMProvider.complete(request) -> LLMResponse`.
- `LLMGateway.complete_structured(request, response_model, budget) -> LLMResult`.

- [ ] **Step 1: Add failing tests for success, JSON parse/validation, timeout, 429 Retry-After, 5xx backoff, 401/403 no-retry, usage, cost, and redacted errors.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement minimal contracts, finite retry, normalized errors, and Pydantic structured parsing.**
- [ ] **Step 4: Run `python -m pytest tests/test_llm_gateway.py -q`; verify PASS.**
- [ ] **Step 5: Commit with `feat(llm): add OpenAI-compatible gateway`.**

### Task 2: Cost and egress policy

**Files:**
- Create: `src/litwatch/llm/security.py`
- Modify: `src/litwatch/config.py`
- Modify: `.env.example`
- Test: `tests/test_llm_security.py`

**Interfaces:**
- `DataEgressPolicy.authorize(provider_kind, evidence_scope, payload_chars)`.
- `CostGuard.authorize(estimated_tokens, estimated_cost, daily_spend, active_jobs)`.

- [ ] **Step 1: Add failing tests for cloud consent, full-text opt-in, payload limit, token/job cost/daily cost/concurrency rejection, and local provider allowance.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement exact settings and guards before network dispatch.**
- [ ] **Step 4: Run gateway/security/config tests; verify PASS.**
- [ ] **Step 5: Commit with `feat(llm): enforce egress and cost limits`.**

### Task 3: Refactor PaperAnalyzer through LLMGateway

**Files:**
- Modify: `src/litwatch/analysis.py`
- Modify: `src/litwatch/config.py`
- Test: `tests/test_core.py`
- Test: `tests/test_paper_analyzer.py`

- [ ] **Step 1: Add failing tests asserting injected gateway use, no direct client request, extractive fallback without credentials, preserved evidence scope, and normalized safe failure.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Remove direct HTTP/retry logic from `PaperAnalyzer`; inject gateway and preserve prompt/business semantics.**
- [ ] **Step 4: Run analyzer/gateway/core tests and full suite; verify PASS.**
- [ ] **Step 5: Commit with `refactor(analysis): route PaperAnalyzer through LLMGateway`.**

