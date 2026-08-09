# Stack v1.3 End-to-End Results

## Release status

Stack v1.3: **Stable**

- Capability: Multi-Source Literature Retrieval
- Runnable providers: OpenAlex, Semantic Scholar, arXiv, Crossref
- Compatible Dify workflow: `dify/workflows/literature-search-v1.1.yml`
- Same-numbered workflow: intentionally absent
- Stable tag: `dify-v1.3`

Stack and Workflow versions remain independent. Workflow v1.1 keeps its
backward-compatible `topic + limit` contract and omits `providers`, so Dify uses
the default OpenAlex-only selection. Explicit multi-source selection is
available through the LitWatch API.

## Provider validation

| Provider | Adapter and tests | Real E2E | Release interpretation |
|---|---|---|---|
| OpenAlex | PASS | PASS | Real retrieval verified |
| Semantic Scholar | PASS | Anonymous HTTP 429 | Upstream rate limit isolated; authenticated real success **NOT VERIFIED** |
| arXiv | PASS | PASS | Real retrieval verified |
| Crossref | PASS | PASS | Real retrieval verified |

Semantic Scholar anonymous access returned `rate_limited/upstream_429`. This is
recorded as **UPSTREAM RATE LIMITED HTTP 429**, not as a successful real
Semantic Scholar retrieval. The failure remained isolated and did not prevent
the other providers from returning results.

Semantic Scholar environment BYOK and runtime Provider Profile BYOK paths pass
offline tests. A real authenticated Semantic Scholar response was not verified
and is not claimed by this release.

## Multi-provider E2E

The four-provider request selected OpenAlex, Semantic Scholar, arXiv, and
Crossref explicitly.

- HTTP 200
- `paper_count=12`
- OpenAlex: success
- arXiv: success
- Crossref: success
- Semantic Scholar: `rate_limited/upstream_429`
- Partial failure isolation: PASS
- Round-robin aggregation regression: PASS

The response remained successful because at least one selected provider
succeeded. Provider diagnostics retained the Semantic Scholar failure without
leaking upstream response bodies or credentials.

## Dynamic topic E2E

Two real multi-provider searches were compared:

1. `underwater acoustic localization`
2. `underwater acoustic OFDM communication`

Both returned 12 papers. The result sets were different, with one overlapping
canonical identifier and 23 unique identifiers across the union. Dynamic topic
behavior: PASS.

## Dify UI compatibility

| Topic | Workflow | Result |
|---|---|---|
| `underwater acoustic TDOA localization` | SUCCESS | `paper_count > 0`, non-empty `papers_json` |
| `underwater acoustic OFDM communication` | SUCCESS | `paper_count > 0`, non-empty `papers_json` |

The second topic returned real underwater acoustic communication papers,
including work on joint signal processing and coding for underwater acoustic
communications. The two result sets were clearly different. Dynamic Topic:
PASS.

The compatible v1.1 workflow omits explicit provider selection, so the Dify UI
results retained `sources=openalex`: PASS. Docker Worker -> Dify SSRF Proxy ->
LitWatch also returned HTTP 200 during the automated transport regression.

## BYOK and endpoint security

| Check | Result |
|---|---|
| Existing Provider Profile GET/POST reused | PASS |
| Optional write-only secret | PASS |
| Profile secret over environment secret precedence | PASS |
| Environment secret fallback | PASS |
| Anonymous fallback | PASS |
| Partial update preserves secret | PASS |
| Explicit runtime secret clearing | PASS |
| GET and errors redact secret | PASS |
| Known-provider-compatible endpoint boundary | PASS |
| HTTPS enforcement | PASS |
| Local/private/link-local/reserved IP blocking | PASS |
| DNS resolution and rebinding checks | PASS |
| DNS failure rejects configuration | PASS |
| Redirect to private target blocked | PASS |

Runtime Provider Profile secrets remain in memory only. Persistent local
credentials must come from `.env` or environment variables. No real credential
is stored in Git, SQLite, Dify DSL, provider status, or release documentation.

## Final quality gates

| Gate | Result |
|---|---|
| `python -m pytest -q` | 143 passed |
| `ruff check src tests` | PASS |
| `git diff --check` | PASS |
| OpenAlex real E2E | PASS |
| arXiv real E2E | PASS |
| Crossref real E2E | PASS |
| Four-provider E2E | PASS |
| Partial failure isolation | PASS |
| Dynamic topic E2E | PASS |
| Dify Topic A | PASS |
| Dify Topic B | PASS |
| v1.0 stable DSL unchanged | PASS |
| v1.1 stable DSL unchanged | PASS |

No provider metadata was fabricated, no stable DSL was modified, and no
same-numbered Workflow v1.3 file was created.
