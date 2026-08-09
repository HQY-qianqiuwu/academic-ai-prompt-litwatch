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
- State: Stage 3 complete; not Release Candidate or Stable.
- Stage 3 implementation HEAD: this Stage 3 checkpoint commit,
  `feat(recommendations): add historical paper tracking`.
- Stage 3 scope: additive global paper history, per-subscription novelty,
  metadata enrichment, and recommendation-state persistence foundation.
- Validation: 216 tests passed; Ruff and `git diff --check` passed; v1.0/v1.1
  DSL files unchanged.
- Deferred: run engine, scheduling, catch-up, recommendations, deliveries,
  Weekly Digest, and email.
- Next action: review Stage 3, then begin Stage 4 Subscription Run Engine.
- Architecture: `docs/V1_6_WEEKLY_RECOMMENDATIONS.md`

Do not modify historical Stable tags or the v1.0/v1.1 Workflow DSL files.
Do not begin Stage 4 without explicit approval.
