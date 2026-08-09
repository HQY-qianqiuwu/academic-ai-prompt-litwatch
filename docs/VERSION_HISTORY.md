# Version History

## Version Naming

Headings in this file are **Stack / System Release** versions. They describe the
combined system and do not imply that the Dify Workflow DSL has the same version.
Backend-only releases may reuse an older compatible workflow. The exact mapping
is recorded in `docs/RELEASE_MATRIX.md`.

## Stack v1.0

Status: Stable Baseline

Architecture:

```text
Dify -> OpenAlex
```

Features:

- User-defined research topic
- Direct OpenAlex literature search
- Title, author, year, venue, DOI, URL, and abstract extraction
- JSON output

Dify Workflow:

`dify/workflows/literature-search-v1.0.yml`

Stable tag: `dify-v1.0`

## Stack v1.1

Status: Stable

Architecture:

```text
Dify -> LitWatch API -> LiteratureSearchService -> OpenAlex
```

Features:

- Unified `POST /api/v1/literature/search` endpoint
- Provider-backed normalized `Paper` response
- Explicit 422, 502, and 504 error boundaries
- Offline API contract tests
- Docker Desktop access through `host.docker.internal:8000`

Dify Workflow:

`dify/workflows/literature-search-v1.1.yml`

Stable tag: `dify-v1.1`

Validation record: `docs/V1_1_E2E_RESULTS.md`

## Stack v1.2

Status: Stable

Architecture:

```text
Dify
    -> LitWatch API
    -> Provider Configuration Layer
    -> Provider Registry
    -> OpenAlex
```

Backend additions:

- Provider configuration and profile models
- Provider registry separated from `LiteratureSearchService`
- Provider enable/disable state
- Configurable OpenAlex base URL
- Optional `providers` search parameter
- BYOK credential-reference architecture
- Redacted profile and validation responses
- Process-local credential submission without JSON or SQLite persistence
- Backward compatibility with the v1.1 `topic + limit` request

System integration additions:

- Idempotent local lifecycle management for Docker, Dify, LitWatch, Provider
  Registry, OpenAlex, and the SSRF proxy
- Recoverable Dify 1.16.1 Squid integration restricted to
  `host.docker.internal:8000`
- Safe port-owner inspection and Docker-volume-preserving stop behavior

Dify Workflow:

`dify/workflows/literature-search-v1.1.yml` (compatible reuse)

Provider state:

- OpenAlex: runnable
- Semantic Scholar: non-runnable capability declaration
- arXiv: non-runnable capability declaration
- Crossref: non-runnable capability declaration
- IEEE Xplore: non-runnable capability declaration
- Scopus: non-runnable capability declaration
- Web of Science: non-runnable capability declaration

Validation state:

- Backend, Provider Registry, real OpenAlex, profile, credential-redaction, and
  Docker-to-host checks: pass
- Dify import, backward-compatible workflow, and dynamic-topic runs: pass
- Dify SSRF allow target and blocked regression targets: pass
- Cold start, warm start, safe stop, restart, and idempotency: pass
- Tests: 58 passed; Ruff: pass
- Stable v1.0 and v1.1 DSL protection: pass
- `literature-search-v1.2.yml`: intentionally absent
- Stable tag: `dify-v1.2`

Architecture record: `docs/V1_2_PROVIDER_CONFIGURATION.md`

Validation record: `docs/V1_2_E2E_RESULTS.md`
