# V2.0H Acceptance and Release Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove Dify-free runtime parity, perform whole-branch security/recovery review, and prepare a pushed v2.0 Release Candidate without a Stable tag.

**Architecture:** Automated fixtures prove deterministic contracts; local smoke tests prove the real Python lifecycle. Release documents record evidence and explicit residual limitations.

**Tech Stack:** pytest, Ruff, Git, PowerShell lifecycle, real OpenAlex smoke.

## Global Constraints

- Do not run destructive recovery against user data.
- Do not create `litwatch-v2.0`.
- Push only `feat/v2.0-python-native-runtime` to `private-backup`, without force.

---

### Task 1: Automated Dify-free acceptance suite

**Files:**
- Create: `tests/test_v2_acceptance.py`
- Create: `docs/V2_0_E2E_RESULTS.md`

- [ ] **Step 1: Add acceptance tests for startup, Search, Provider Settings, Radar, Subscription, Scheduler, Digest, historical dedup, Paper Analysis, job idempotency/cancel/timeout/restart, migration/backup/recovery, zh-CN, and English in `dify_free` mode.**
- [ ] **Step 2: Run the new test and verify any uncovered requirement fails before changing production code; route each failure back to its owning plan instead of patching acceptance tests.**
- [ ] **Step 3: Once GREEN, record exact automated commands/counts and real-runtime fields in the E2E document.**
- [ ] **Step 4: Run full pytest, Ruff, diff-check, fsck, and stable DSL comparisons.**
- [ ] **Step 5: Commit with `test(v2.0): add Dify-free acceptance gate`.**

### Task 2: Real lifecycle and recovery rehearsal

**Files:**
- Modify: `docs/V2_0_E2E_RESULTS.md`
- Create: `docs/V2_0_MIGRATION_REHEARSAL.md`

- [ ] **Step 1: Copy the current v1.7 database into an isolated temporary directory and record its hash/table counts.**
- [ ] **Step 2: Run migration, integrity verification, failed-migration rollback fixture, backup recovery, and post-recovery count/hash checks.**
- [ ] **Step 3: With Dify/Docker excluded from readiness, run cold start, warm start, stop, restart, real OpenAlex TDOA search, Radar/Subscription persistence, and one local/external-model-safe analysis path.**
- [ ] **Step 4: Record exact evidence without secrets; run final automated gates again.**
- [ ] **Step 5: Commit both evidence documents with `docs(v2.0): record migration and runtime rehearsal`.**

### Task 3: Release Candidate documentation and push

**Files:**
- Modify: `计划表.md`
- Modify: `docs/CODEX_HANDOFF.md`
- Modify: `docs/VERSION_HISTORY.md`
- Modify: `docs/RELEASE_MATRIX.md`
- Modify: `docs/DIFY_ITERATION_PLAN.md`
- Create: `docs/V2_0_PYTHON_NATIVE_RUNTIME.md`

- [ ] **Step 1: Mark v1.7 Stable and v2.0 Release Candidate; document component dispositions, Dify-free core, branch, tests, security, migration, job, and manual-acceptance requirement.**
- [ ] **Step 2: Scan docs/plans/source/tests for placeholders and credential assignment patterns; verify `.env` is ignored and untracked.**
- [ ] **Step 3: Run fresh full pytest, Ruff, diff-check, fsck, v1.0/v1.1 DSL diffs, tag immutability checks, and working-tree review.**
- [ ] **Step 4: Explicitly stage only release documents and commit `docs(release): prepare stack v2.0 release candidate`.**
- [ ] **Step 5: Push `feat/v2.0-python-native-runtime` to `private-backup`, compare local/remote HEAD, confirm GitHub PRIVATE, confirm `litwatch-v2.0` absent, and stop for manual acceptance.**

