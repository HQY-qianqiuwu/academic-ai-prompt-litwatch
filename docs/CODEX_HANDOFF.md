# Codex Handoff

## Latest stable

- Stack: v1.5
- Tag: `dify-v1.5`
- Commit: `9539c56df31c1af34cfe5bb7f0ce5afb921719bb`
- State: Stable; post-release smoke verification passed.

## Current development

- Stack: v1.6 - Research Subscriptions and Weekly Recommendations
- Branch: `feat/v1.6-weekly-recommendations`
- Base: `dify-v1.5`
- State: Release Candidate; not Stable and no `dify-v1.6` tag exists.
- RC scope: subscription persistence, per-subscription novelty, unified run
  engine, ranking-preserving recommendations, weekly scheduling, catch-up,
  concurrency leases, stale recovery, responsive Subscription UI, and
  idempotent Dashboard Weekly Digests. The UI now defaults to Simplified
  Chinese (`zh-CN`) and supports an English (`en`) switch stored only as the
  non-sensitive `litwatch.locale` browser preference.
- Validation: 245 tests passed; Ruff and `git diff --check` passed; real TDOA,
  OFDM, repeat-run suppression, partial failure, restart persistence, Manual
  Search, Provider Settings, Dify, lifecycle, Chinese-default, English-switch,
  brand-preservation, metadata-preservation, and secret-redaction checks passed.
- Stable DSL protection: v1.0 and v1.1 files unchanged.
- Deferred: optional email delivery.
- Next action: perform manual v1.6 acceptance. Only after it passes may release
  documentation be promoted to Stable and an annotated `dify-v1.6` tag be
  created.
- Architecture: `docs/V1_6_WEEKLY_RECOMMENDATIONS.md`
- E2E evidence: `docs/V1_6_E2E_RESULTS.md`

Do not modify historical Stable tags or the v1.0/v1.1 Workflow DSL files.
Do not create or move `dify-v1.6` before explicit manual acceptance.
