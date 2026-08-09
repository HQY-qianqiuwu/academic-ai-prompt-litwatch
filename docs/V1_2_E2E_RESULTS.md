# Stack v1.2 End-to-End Results

## Release status

Stack v1.2: **Stable**

- Backend capability: Provider Configuration Layer + Provider Registry
- Runnable provider: OpenAlex
- Compatible Dify workflow: `dify/workflows/literature-search-v1.1.yml`
- Same-numbered workflow: intentionally absent
- Stable tag: `dify-v1.2`

Stack and Workflow versions are independent. Reusing Workflow v1.1 is expected
because Stack v1.2 preserves the `topic + limit` request and response contract.

## Provider configuration and API

| Check | Result |
|---|---|
| Provider Configuration Layer | PASS |
| Provider Registry | PASS |
| OpenAlex `runnable=true` | PASS |
| Non-runnable providers do not fabricate results | PASS |
| v1.1 `topic + limit` request | PASS |
| Explicit `providers=["openalex"]` | PASS |
| Invalid provider returns HTTP 422 | PASS |
| Provider Profile GET/POST | PASS |
| Secret redaction | PASS |
| Restart clears in-memory credentials | PASS |

Semantic Scholar, arXiv, Crossref, IEEE Xplore, Scopus, and Web of Science remain
non-runnable capability declarations in Stack v1.2.

## Docker and SSRF

Docker-to-LitWatch access passed. Dify 1.16.1 SSRF regression results:

| Target | Result |
|---|---|
| `host.docker.internal:8000` | ALLOW — PASS |
| `host.docker.internal:80` | BLOCK — PASS |
| `host.docker.internal:8001` | BLOCK — PASS |
| `db_postgres:5432` | BLOCK — PASS |

The reproducible integration permits only the LitWatch host and port
combination. Other private and local targets remain protected by Squid.

## Local lifecycle

| Check | Result |
|---|---|
| Cold Start | PASS |
| Warm Start | PASS |
| Safe Stop | PASS |
| Restart | PASS |
| Dify idempotency | PASS |
| LitWatch idempotency | PASS |
| Docker volumes preserved | PASS |
| Provider Registry readiness | PASS |
| SSRF proxy readiness | PASS |

Warm Start retained one LitWatch listener and the same API, Worker, Nginx, and
SSRF Proxy container identities. Stop removed no volumes or containers.

## Real search

Request:

```json
{
  "topic": "underwater acoustic TDOA localization",
  "limit": 5
}
```

Result:

- HTTP 200
- `paper_count=5`
- five papers returned
- every paper's `sources` contains `openalex`

## Dify UI compatibility

| Topic | Result |
|---|---|
| `underwater acoustic TDOA localization` | PASS |
| `underwater acoustic OFDM communication` | PASS |
| Clearly different dynamic result sets | PASS |

Both topics ran through Dify -> LitWatch v1.2 -> Provider Registry -> OpenAlex.

## Final quality gates

| Gate | Result |
|---|---|
| `python -m pytest -q` | 58 passed |
| `ruff check src tests` | PASS |
| v1.0 stable DSL unchanged | PASS |
| v1.1 stable DSL unchanged | PASS |
| `git diff --check` | PASS |

No provider metadata was fabricated, no stable DSL was modified, and no
same-numbered Workflow v1.2 file was created.
