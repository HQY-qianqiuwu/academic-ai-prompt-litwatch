# LitWatch Stack v2.0 — Python-native Runtime Migration

## Status

**RELEASE CANDIDATE — NOT STABLE**

Branch: `feat/v2.0-python-native-runtime`

Base: `dify-v1.7`

No v2.0 Stable tag exists. Final manual acceptance must complete before a
promotion decision and before any Stable tag is created.

## Goal

Make Python the single default runtime for the LitWatch research system and
remove Dify as a required runtime dependency, without deleting the historical
Dify assets before acceptance.

## Architecture

```text
启动科研文献系统.cmd / 停止科研文献系统.cmd / status-stack.ps1
    -> Python lifecycle (identity, health, owner validation)
    -> FastAPI
       -> LiteratureSearchService -> Provider Registry -> providers
       -> Research Radar / Subscriptions / Scheduler / Weekly Digest
       -> PaperAnalysisService -> LLMGateway -> deterministic no-key fallback
       -> durable JobWorker + SQLite job repository
    -> SQLite (source of truth) + migration / backup / recovery
```

Default start, stop, and status never probe, start, or require Docker, Dify,
Compose, or the Dify SSRF proxy. A Python startup failure is reported and
never automatically falls back to Dify.

Legacy rollback is explicit and separate:

- `启动旧版 Dify 科研文献系统.cmd`
- `停止旧版 Dify 科研文献系统.cmd`

## Component disposition

| Component | v2.0 disposition |
|---|---|
| Search / Provider Registry / BYOK | Python, retained and default |
| Research Radar | Python, retained and default |
| Subscriptions / Scheduler / Weekly Digest | Python, retained and default |
| Deduplication / Ranking | Python, retained and default |
| Paper Analysis / LLM Gateway | Python, newly default with no-key extractive path |
| Durable Jobs | Python, newly default |
| SQLite migration / backup / recovery | Python, verified against a real v1.7 snapshot copy |
| Bilingual Web UI | Python/Jinja2/vanilla JS, retained |
| Dify runtime / Docker / SSRF proxy | Not a default dependency; legacy rollback only |
| v1.0 / v1.1 Workflow DSL | Frozen release-history artifacts; unchanged |

## Verification evidence

### Automated Dify-free acceptance

`tests/test_v2_acceptance.py` composes the real production runtime and
services with deterministic external I/O only:

- FastAPI lifespan starts in `dify_free` mode with live migration, runtime,
  JobWorker, and Scheduler health.
- Manual Search runs through the production `LiteratureSearchService`,
  registry, profile, aggregation, deduplication, and ranking.
- Provider Settings writes a sentinel credential; no response, page, or static
  asset reflects it.
- Subscriptions, scheduler, Weekly Digest, historical deduplication, and Radar
  share the same production search configuration and isolated SQLite.
- Paper Analysis uses the real gateway, analyzer, service, usage ledger, and
  repository with a deterministic LLM transport.
- Durable jobs prove enqueue idempotency, completion, cancellation, timeout,
  and stale-lease restart recovery.
- Migration coordinator verifies SQLite, creates a pending backup, restores it,
  and rejects invalid backups.
- zh-CN and English pages and navigation pass.

Full suite: `604 passed, 1 warning`. Ruff: `All checks passed!`.
`git diff --check` and `git fsck --no-dangling`: pass. Stable v1.0/v1.1 DSL
diffs: empty.

### Real migration and lifecycle rehearsal (isolated)

The live v1.7 database was opened read-only and copied with SQLite backup. Its
SHA-256 was unchanged after the rehearsal. On the copy:

- schema v6 -> v10 migration verified;
- an invalid v11 migration left no partial table/version/audit row;
- backup recovery was byte-identical;
- cold start, warm start, status, stop, and restart passed on port 18080 with
  `mode=python_default`, `requires_dify=false`, and no leftover listener or
  identity;
- real OpenAlex `underwater acoustic TDOA localization` returned HTTP 200,
  5 papers, OpenAlex provenance 5/5, provider status `success`;
- a no-key extractive analysis returned abstract-level evidence with no cloud
  LLM enabled;
- one subscription and one Radar persisted across restart.

Full procedure and sanitized evidence:
`docs/V2_0_MIGRATION_REHEARSAL.md`.

## Known constraints

- Port 8000 remains owned by the protected v1.7 process (PID 37408) on this
  machine. The v2.0 rehearsal used isolated port 18080 and cleaned it up.
- Semantic Scholar anonymous access remains upstream-rate-limited; authenticated
  real success is not re-verified in v2.0 evidence. BYOK and failure isolation
  remain covered by tests.
- Cloud AI requires explicit consent and a key; the no-key extractive path is
  the deterministic default.
- The historical Dify repository, volumes, integration patch, and stable DSL
  files remain frozen until manual acceptance and separate deletion
  authorization.

## Manual acceptance checklist

Release owner should confirm the following before promotion:

1. Start with `启动科研文献系统.cmd`; status reports READY and
   `/health` shows `python_primary=true`, `requires_dify=false`.
2. Manual Search opens at `http://127.0.0.1:8000/`; run
   `underwater acoustic TDOA localization` and
   `underwater acoustic OFDM communication`; both return real papers and
   clearly different results.
3. Provider Settings opens; saving/clearing a test credential does not reflect
   it in any page or response.
4. Research Radar, Subscriptions, Run Now, Run History, and Weekly Digest
   still work in both zh-CN and English.
5. Paper Analysis workspace opens; a no-key run completes with extractive
   evidence; a job can be enqueued, viewed, and cancelled.
6. Stop with `停止科研文献系统.cmd`; no LitWatch listener remains on the
   managed port and volumes/data are preserved.
7. Restart; subscriptions, Radar history, job history, and analysis history
   persist.
8. Optionally practice legacy rollback with
   `启动旧版 Dify 科研文献系统.cmd`; the default Python path must remain
   unaffected.
9. Confirm repository `HQY-qianqiuwu/dify-literature-search-workflow` is
   PRIVATE and `feat/v2.0-python-native-runtime` is backed up.
10. Decide promotion. Only after acceptance may a v2.0 Stable tag be created
    (candidate name `litwatch-v2.0`); deleting Dify assets then requires a
    separate explicit authorization.
