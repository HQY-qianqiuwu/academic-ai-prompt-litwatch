# LitWatch v2.0 Python-default, Dify-legacy Cutover Design

## Decision

LitWatch v2.0 will make the Python application the only default runtime. Dify,
its Docker compose files, and historical DSL artifacts remain in the workspace
as explicit legacy recovery material until the user completes manual acceptance
and separately authorizes deletion.

## Scope

The Python-default runtime must operate without Docker Desktop or Dify:

- FastAPI web application and health endpoints;
- Literature Search and Provider Settings;
- Research Radar;
- research subscriptions, scheduler, run history, and Dashboard Weekly Digest;
- durable jobs and Paper Analysis through the Python LLM gateway.

The migration does not delete, rewrite, or move historical Dify DSL files,
Docker volumes, or the `dify` repository. It also does not make e-mail delivery
a v2.0 requirement; Dashboard delivery remains the implemented weekly channel.

## Runtime Boundary

```text
Default launcher
  -> Python lifecycle scripts
  -> LitWatch FastAPI + SQLite + Scheduler + JobWorker + LLMGateway
  -> Search / Radar / Subscriptions / Digest / Paper Analysis

Explicit legacy launcher
  -> Docker Desktop + Dify compose + historical DSL
```

The default launcher must never probe, start, or require Docker, Dify, or the
Dify SSRF proxy. Legacy Dify lifecycle commands remain available under names
that make their legacy status unambiguous.

## Cutover Components

1. Complete the in-progress typed Python paper-analysis pipeline and durable
   `paper_analysis` job/API path.
2. Add Python workspace navigation for analysis and jobs while keeping existing
   Search, Radar, Subscriptions, Digests, and Provider Settings routes.
3. Convert root default lifecycle scripts to Python-only startup, shutdown, and
   status behavior. Preserve current Docker/Dify behavior in explicit legacy
   scripts.
4. Remove residual runtime Dify assumptions from configuration and operational
   documentation, without removing historical artifacts.
5. Verify parity and Dify-free operation with Docker Desktop stopped.

## Safety and Data Rules

- Existing stable tags and v1.0/v1.1 DSL are immutable.
- Python remains the authority for business logic and persistent state.
- Provider metadata is never generated or modified by an LLM.
- LLM cloud egress, evidence scope, secret redaction, and cost controls remain
  fail-closed.
- No `.env`, API key, credential, cookie, or Dify secret may be committed.
- Dify deletion is out of scope until separate user authorization after manual
  acceptance.

## Validation and Acceptance

Automated gates must include `pytest`, `ruff check src tests`, and
`git diff --check`. Dify-free acceptance must prove cold start, warm start,
stop/restart, real search, Provider Settings, Radar, subscriptions, scheduler,
Dashboard Digest, durable jobs, and Paper Analysis with Docker/Dify unavailable.

The old Dify path is retained as an explicit optional rollback path during this
acceptance period. A v2.0 Stable tag is not created before manual acceptance.
