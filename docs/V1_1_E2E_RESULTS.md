# V1.1 End-to-End Results

Test date: 2026-08-08

Status: Stable — automated checks and authenticated Dify workflow runtime validation passed.

## Architecture Under Test

```text
Dify Workflow
  -> POST http://host.docker.internal:8000/api/v1/literature/search
  -> LitWatch FastAPI
  -> LiteratureSearchService
  -> OpenAlexSource
  -> normalized Paper response
```

## Static Workflow Validation

- `dify/workflows/literature-search-v1.1.yml` parses as YAML.
- The HTTP node uses `POST` and the existing Dify variable expression
  `{{#1786118013273.topic#}}`.
- The HTTP node targets LitWatch at `host.docker.internal:8000`.
- The workflow contains no direct `api.openalex.org` request.
- The Code node parses only the normalized `query`, `paper_count`, and `papers` fields.
- The stable v1.0 DSL SHA-256 remains
  `3889B27663316540441B05EF70C1417DFB4A0583CF3547290BF88B729471EE59`.

## Automated Validation

### Python checks

- `python -m pytest -q`: 37 passed, 1 existing dependency deprecation warning.
- `ruff check src tests`: all checks passed.

### Windows host test

- Endpoint: `POST http://127.0.0.1:8000/api/v1/literature/search`
- Topic: `underwater acoustic TDOA localization`
- Limit: 10
- Result: PASS, 10 real provider-backed papers returned.
- Observed source: `openalex`.

### Docker network test

- Origin: running Dify `docker-worker-1` container.
- Endpoint: `POST http://host.docker.internal:8000/api/v1/literature/search`
- Result: PASS, HTTP 200 and 2 real provider-backed papers returned.

The repeatable command is:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/smoke-v1.1.ps1
```

LitWatch must already be listening on `0.0.0.0:8000`, and Docker Desktop plus the Dify
worker container must be running.

## Dify Runtime Status

Status: PASS.

Dify DSL import: PASS.

LitWatch API runtime: PASS.

Docker to `host.docker.internal:8000`: PASS.

Workflow runtime: PASS.

Validated topics:

1. `underwater acoustic TDOA localization`
   - Returned real, relevant provider-backed papers.
2. `underwater acoustic communication OFDM`
   - Dynamic topic test passed and returned a different set of real, relevant papers.

Final release evidence:

- Host API: PASS
- Docker network: PASS
- Dify DSL import: PASS
- Dify workflow runtime: PASS
- Dynamic topic behavior: PASS
- `python -m pytest -q`: 37 passed
- `ruff check src tests`: PASS
- v1.0 stable DSL: unchanged
