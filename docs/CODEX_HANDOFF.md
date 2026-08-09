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
- State: Stage 2 complete; not Release Candidate or Stable.
- Stage 2 implementation HEAD: `5df7abbdb43d8e17e79e6f5c2bda067b6f29ac95`
- Stage 2 scope: subscription model, additive SQLite migration, validated
  persistence, and GET/POST/GET-detail/PATCH API foundation.
- Validation: 203 tests passed; Ruff and `git diff --check` passed; v1.0/v1.1
  DSL files unchanged.
- Deferred: historical paper tracking, run engine, scheduling, catch-up,
  recommendations, deliveries, Weekly Digest, and email.
- Next action: review Stage 2, then begin Stage 3 historical paper tracking.
- Architecture: `docs/V1_6_WEEKLY_RECOMMENDATIONS.md`

Do not modify historical Stable tags or the v1.0/v1.1 Workflow DSL files.
Do not begin Stage 3 without explicit approval.
