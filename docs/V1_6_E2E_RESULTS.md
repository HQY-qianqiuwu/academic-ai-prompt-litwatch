# Stack v1.6 E2E Results

Status: PASS for Release Candidate preparation (manual product acceptance still required).

Date: 2026-08-09
Branch: `feat/v1.6-weekly-recommendations`

## Automated gate

- `python -m pytest -q`: 239 passed, one existing FastAPI/Starlette dependency warning;
- `ruff check src tests`: PASS;
- `git diff --check`: PASS;
- scheduler due/not-due, disabled, catch-up, concurrency lease, stale recovery,
  timezone/DST, restart, and lifecycle tests: PASS; and
- subscription history, cross-subscription isolation, recommendation/delivery
  idempotency, and restart persistence tests: PASS.

## Real subscription E2E

### TDOA Weekly

- Topic: `underwater acoustic TDOA localization`;
- Providers: OpenAlex, arXiv, Crossref;
- search limit: 30; recommendation limit: 5;
- first run: `success`, raw 150, deduplicated 145, new 30,
  recommended 5, Dashboard digest created; and
- immediate second run: `success`, previously seen 30, new 0,
  recommended 0, Dashboard empty digest created.

The second run recommended none of the first run's canonical IDs.

### OFDM Weekly

- Topic: `underwater acoustic OFDM communication`;
- Providers: OpenAlex, arXiv, Crossref;
- run: `success`, raw 150, deduplicated 150, new 30,
  recommended 5, Dashboard digest created; and
- recommended canonical IDs were clearly different from the TDOA set.

### Partial Provider failure

- OpenAlex: success;
- Semantic Scholar anonymous: `rate_limited` / `upstream_429`;
- arXiv: success;
- Crossref: success; and
- aggregate run: `partial_success`, new 12, recommended 3, digest created.

The upstream 429 was isolated and only safe Provider status/error codes were
persisted and returned.

## Restart persistence

LitWatch was safely restarted through the existing lifecycle. After restart:

- TDOA and OFDM subscriptions remained available;
- TDOA run history and historical digests remained available;
- a new TDOA Run Now completed with previously seen 30, new 0,
  recommended 0, and a new empty digest;
- paper history and recommendations remained effective; and
- Search, Subscriptions, Weekly Digests, and Provider Settings pages all
  returned HTTP 200.

The project virtual environment was missing the already-declared Windows
`tzdata` dependency. `tzdata 2026.3` was installed into that local venv before
the real `Asia/Shanghai` test; no tracked dependency or source file was changed
by that environment repair.

## Existing-system regression

- Manual Search TDOA: HTTP 200, 3 real OpenAlex papers;
- Manual Search OFDM: HTTP 200, 3 real OpenAlex papers;
- dynamic topic result difference: PASS;
- Provider Registry: 7 capabilities returned, OpenAlex runnable;
- Provider Profiles: HTTP 200;
- Dify: `http://localhost` HTTP 200;
- Docker, LitWatch, OpenAlex, Dify, and SSRF Proxy lifecycle status: READY;
- v1.0 DSL: unchanged; and
- v1.1 DSL: unchanged.

No `dify-v1.6` tag was created. Manual browser acceptance remains required
before Stable finalization.
