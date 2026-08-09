# Stack v1.4 Ranking E2E Results

Status: Stable; automated and manual validation complete

Validation date: 2026-08-09

## Runtime

- Branch: `feat/v1.4-dedup-ranking`
- Base tag: `dify-v1.3`
- Base commit: `29967e2e77361611bc7340fbba4ca5f568ca7055`
- LitWatch module: current repository `src/litwatch/web.py`
- Endpoint: `POST http://127.0.0.1:8000/api/v1/literature/search`
- Selected Providers: OpenAlex, Semantic Scholar, arXiv, Crossref
- Final limit: 10
- Candidate limit per Provider: 20
- Stable tag: `dify-v1.4`

No runtime result was manually reordered or edited.

## Topic A: TDOA localization

Query:

```text
underwater acoustic TDOA localization
```

Result:

- HTTP 200
- `paper_count=10`
- `raw_count=60`
- `dedup_count=57`
- `duplicates_removed=3`
- OpenAlex: success
- arXiv: success
- Crossref: success
- Semantic Scholar: `rate_limited/upstream_429`

Top five deterministic results:

1. **Synchronization-Free Underwater Acoustic Localization for Autonomous
   Platforms: A Neural Network TDOA Approach and the Role of Receiver
   Geometry** — relevance `0.800000`, quality `1.000000`, rank `0.830000`,
   sources `crossref, openalex`
2. **Impulse Response Shortening in TDOA Algorithm for Underwater Acoustic
   Localization** — relevance `0.800000`, quality `0.925000`, rank `0.818750`
3. **An Anti-noise and High-precision TDOA Positioning Framework for Underwater
   Acoustic Localization** — relevance `0.800000`, quality `0.825000`, rank
   `0.803750`
4. **An Enhanced AUV-Aided TDoA Localization Algorithm for Underwater Acoustic
   Sensor Networks** — relevance `0.700000`, quality `0.675000`, rank `0.696250`
5. **Net Fishing Localization: Performance of TDOA-based Positioning Technique
   in Underwater Acoustic Channels Using Chirp Signals** — relevance
   `0.650000`, quality `0.675000`, rank `0.653750`

The first result demonstrates a real cross-source merge: one returned Paper
contains both `crossref` and `openalex` provenance.

## Topic B: OFDM communication

Query:

```text
underwater acoustic OFDM communication
```

Result:

- HTTP 200
- `paper_count=10`
- `raw_count=60`
- `dedup_count=60`
- `duplicates_removed=0`
- OpenAlex: success
- arXiv: success
- Crossref: success
- Semantic Scholar: `rate_limited/upstream_429`

Top five deterministic results:

1. **Adaptive Modulation for Underwater Acoustic OFDM Communication** —
   relevance `0.850000`, quality `0.675000`, rank `0.823750`
2. **An underwater acoustic OFDM communication system with shrimp (impulsive)
   noise cancelling** — relevance `0.850000`, quality `0.525000`, rank
   `0.801250`
3. **OFDM Underwater Acoustic Communication Receiver Based on Deep Learning** —
   relevance `0.650000`, quality `0.675000`, rank `0.653750`
4. **MIMO-OFDM underwater acoustic communication systems—A review** — relevance
   `0.650000`, quality `0.675000`, rank `0.653750`
5. **HEU OFDM-modem for Underwater Acoustic Communication and Networking** —
   relevance `0.650000`, quality `0.675000`, rank `0.653750`

The Topic A and Topic B top sets are clearly different, and Topic B is led by
explicit OFDM underwater-acoustic communication titles rather than generic AUV
routing papers.

## Partial failure

Semantic Scholar anonymous access returned HTTP 429 and was classified as
`rate_limited/upstream_429`. The other three Providers completed normally and
their candidates continued through deduplication and ranking. Partial failure
isolation: PASS.

No Semantic Scholar API key was configured for this run. Authenticated real
Semantic Scholar success remains **NOT VERIFIED**; the environment and runtime
Profile BYOK paths remain covered by offline tests.

## Dify compatibility regression

The running Dify Worker sent the existing Workflow-compatible request through
the actual `ssrf_proxy:3128` path to:

```text
http://host.docker.internal:8000/api/v1/literature/search
```

Result:

- HTTP 200
- `paper_count=3`
- `raw_count=6`
- `dedup_count=6`
- default Provider: OpenAlex success
- returned sources: `openalex`
- v1.0 DSL diff from `dify-v1.0`: empty
- v1.1 DSL diff from `dify-v1.1`: empty
- both stable YAML files parse successfully

This automated check validates the Dify Worker -> SSRF Proxy -> LitWatch
transport and the unchanged response fields used by Workflow v1.1.

## Automated gates

- Full test suite: 164 passed
- conflicting canonical DOI merge protection: PASS
- Ruff: PASS
- `git diff --check`: PASS
- OpenAlex regression: PASS
- Semantic Scholar 429 isolation: PASS
- arXiv regression: PASS
- Crossref regression: PASS
- Provider status regression: PASS
- default OpenAlex-only behavior: PASS
- explicit multi-provider behavior: PASS
- environment and Profile BYOK tests: PASS
- SSRF-safe custom Base URL tests: PASS
- secret-redaction tests: PASS

## Manual validation

Final manual acceptance passed:

- TDOA ranking: PASS
- OFDM ranking: PASS
- Dynamic ranking: PASS
- Deduplication: 60 raw, 57 unique, 3 removed — PASS
- Final duplicate DOI count: 0 — PASS
- Multi-source merge: PASS
- Dify Topic A, `underwater acoustic TDOA localization`: PASS
- Dify Topic B, `underwater acoustic OFDM communication`: PASS

Stack v1.4 is approved for the annotated `dify-v1.4` Stable tag. Semantic
Scholar authenticated real success remains **NOT VERIFIED** and is not claimed
by this release.
