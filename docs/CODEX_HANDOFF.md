# Codex Handoff

## Latest stable

- Stack: v1.7 - Research Radar and Historical Trend Intelligence
- Tag: `dify-v1.7`
- Branch: `feat/v1.7-research-radar`
- Base tag: `dify-v1.6`
- State: Stable; automated, real E2E, and final manual acceptance passed.
- Scope: Radar persistence, bounded historical backfill, deterministic annual
  and keyword statistics, trends, timeline, representative papers, evidence,
  scan history, bilingual Web UI, and Radar-to-Subscription prefill.
- Validation: 305 tests passed; Ruff and diff checks passed; real 2018-2026
  TDOA and OFDM scans, immediate rescan suppression, restart persistence,
  browser rendering, lifecycle, topic isolation, technical-topic evolution,
  semantic-quality filtering, and regression checks passed.
- Evidence navigation: trend evidence auto-expands, displays normalized DOI
  labels, and opens `https://doi.org/...` with safe external-link attributes.
- Final DOI fix: `1f821a4 fix(radar): repair evidence DOI navigation`.
- Stable DSL protection: v1.0 and v1.1 files unchanged.
- Release: annotated `dify-v1.7` tag on the Stable release commit.
- Records: `docs/V1_7_RESEARCH_RADAR.md` and
  `docs/V1_7_E2E_RESULTS.md`.

## Current work (v2.0 Release Candidate)

- Stack: v2.0 - Python-native Runtime Migration
- Tag: none (Release Candidate, not Stable)
- Branch: `feat/v2.0-python-native-runtime`
- Base tag: `dify-v1.7`
- State: Release Candidate; automated Dify-free acceptance and isolated real
  migration / Python-only lifecycle rehearsal passed. Final manual acceptance
  and the promotion decision remain outstanding.
- Scope: default Python-only lifecycle and workspace, durable paper-analysis
  jobs, structured analysis through the Python LLM gateway, retained
  Search/Provider Settings/Radar/Subscriptions/Weekly Digest, and removal of
  Dify launchers/scripts/DSL from the working tree.
- Validation: 604 tests passed; Ruff and `git diff --check` passed; real v1.7
  SQLite snapshot migrated v6 -> v10 with verified rollback and byte-identical
  backup recovery; Python-only cold/warm/status/stop/restart on port 18080
  passed; real OpenAlex TDOA search returned 5 papers with OpenAlex
  provenance and provider `success`; no-key extractive analysis and
  subscription/Radar restart persistence passed.
- Security: `mode=python_default` reports `requires_dify=false`,
  `requires_docker=false`, and `requires_ssrf_proxy=false`; default launchers
  never probe or start Dify/Docker/SSRF; Dify entry points have been removed.
- Historical DSL: v1.0/v1.1 tags unchanged; DSL files removed from the working
  tree by user decision.
- Protected v1.7 process: port 8000 PID 37408 was never signalled or replaced.
- Records: `docs/V2_0_PYTHON_NATIVE_RUNTIME.md`,
  `docs/V2_0_E2E_RESULTS.md`, `docs/V2_0_MIGRATION_REHEARSAL.md`,
  `docs/V2_0_SECURITY_BOUNDARY.md`, and
  `docs/V2_0_RUNTIME_DEPENDENCY_AUDIT.md`.

## Previous stable

- Stack: v1.6 - Research Subscriptions and Weekly Recommendations
- Tag: `dify-v1.6`
- Branch: `feat/v1.6-weekly-recommendations`
- Base: `dify-v1.5`
- State: Stable; automated, real E2E, and final manual acceptance passed.
- Scope: subscription persistence, per-subscription novelty, unified run
  engine, ranking-preserving recommendations, weekly scheduling, catch-up,
  concurrency leases, stale recovery, responsive Subscription UI, and
  idempotent Dashboard Weekly Digests. The UI now defaults to Simplified
  Chinese (`zh-CN`) and supports an English (`en`) switch stored only as the
  non-sensitive `litwatch.locale` browser preference.
- Validation: 250 tests passed; Ruff and `git diff --check` passed; real TDOA,
  OFDM, repeat-run suppression, partial failure, restart persistence, Manual
  Search, Provider Settings, Dify, lifecycle, Chinese-default, English-switch,
  brand-preservation, metadata-preservation, and secret-redaction checks passed.
  Final manual acceptance also passed for Manual Search, Research Subscription,
  Run Now, Run History, Weekly Digest, historical deduplication, immediate
  duplicate suppression, restart persistence, and post-restart deduplication.
- Stable DSL protection: v1.0 and v1.1 files unchanged.
- Deferred: optional email delivery.
- Release: annotated `dify-v1.6` tag on the Stable release commit.
- Architecture: `docs/V1_6_WEEKLY_RECOMMENDATIONS.md`
- E2E evidence: `docs/V1_6_E2E_RESULTS.md`

Do not move historical Stable tags. The v1.0/v1.1 Workflow DSL files were
removed from the working tree by user decision and remain recoverable from
their Git tags.
