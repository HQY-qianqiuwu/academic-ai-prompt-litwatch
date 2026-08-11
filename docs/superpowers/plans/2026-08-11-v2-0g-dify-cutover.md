# V2.0G Dify Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Python the default and prove the core lifecycle has no Docker, Dify, or SSRF-proxy dependency.

**Architecture:** Existing Dify assets remain frozen under explicit legacy naming. Root launchers call Python-only lifecycle scripts and status reports runtime mode instead of Dify health.

**Tech Stack:** PowerShell, FastAPI health APIs, pytest subprocess/static contract tests.

## Global Constraints

- Preserve historical DSL, patch, docs, and tags.
- Default scripts must not invoke Docker.
- Legacy Dify helpers remain explicit and opt-in during the RC.

---

### Task 1: Python-default navigation and runtime behavior

**Files:**
- Modify: `src/litwatch/templates/*.html`
- Modify: `src/litwatch/static/i18n.js`
- Test: `tests/test_ui_localization.py`
- Test: `tests/test_local_ui_navigation.py`

- [ ] **Step 1: Add failing tests asserting primary navigation contains Python Analysis/Jobs, has no required `http://localhost` Dify link, and zh-CN/English labels render.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Replace shared navigation consistently while preserving Search, Radar, Subscriptions, Digests, and Provider Settings.**
- [ ] **Step 4: Run UI/navigation tests; verify PASS.**
- [ ] **Step 5: Commit with `feat(web): make Python analysis the default workspace`.**

### Task 2: Dify-free lifecycle scripts

**Files:**
- Create: `scripts/start-legacy-dify-stack.ps1`
- Create: `scripts/stop-legacy-dify-stack.ps1`
- Modify: `scripts/start-stack.ps1`
- Modify: `scripts/stop-stack.ps1`
- Modify: `scripts/status-stack.ps1`
- Modify: `启动科研文献系统.cmd`
- Modify: `停止科研文献系统.cmd`
- Test: `tests/test_lifecycle_scripts.py`

- [ ] **Step 1: Add failing script tests using controlled command shims; assert default start/status/stop never call Docker or resolve Dify and still inspect the port owner safely.**
- [ ] **Step 2: Verify RED because current scripts require Docker/Dify.**
- [ ] **Step 3: Preserve old behavior in explicit legacy files, make default scripts delegate to current-repo Python lifecycle, add worker/migration/runtime health, and retain idempotent port ownership checks.**
- [ ] **Step 4: Run lifecycle tests and safe local cold/warm/stop/restart smoke tests.**
- [ ] **Step 5: Commit with `feat(runtime): cut default lifecycle over to Python`.**

### Task 3: Dify-free configuration and compatibility evidence

**Files:**
- Modify: `README.md`
- Modify: `docs/RESTORE_ON_NEW_PC.md`
- Modify: `docs/DIFY_ITERATION_PLAN.md`
- Modify: `docs/RELEASE_MATRIX.md`
- Test: `tests/test_runtime.py`

- [ ] **Step 1: Add a failing runtime test that constructs/starts the application in `dify_free` mode while Docker/Dify probes raise if called.**
- [ ] **Step 2: Verify RED before removing residual probes.**
- [ ] **Step 3: Complete the Dify-free mode and document Python default plus explicit legacy rollback commands.**
- [ ] **Step 4: Run runtime/lifecycle/full regression and stable DSL diffs.**
- [ ] **Step 5: Commit with `docs(runtime): document Dify-free operation`.**

