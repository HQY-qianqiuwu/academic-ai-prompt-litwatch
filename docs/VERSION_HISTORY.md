# Version History

## Dify v1.0

Status: Stable Baseline

Features:

- User-defined research topic
- OpenAlex literature search
- HTTP-based external literature retrieval
- OpenAlex metadata normalization
- Title extraction
- Author extraction
- Publication year extraction
- Venue extraction
- DOI normalization
- URL extraction
- Abstract reconstruction
- JSON output

Not included yet:

- Semantic Scholar
- arXiv
- Crossref
- RSS
- Multi-source deduplication
- Zotero synchronization
- LLM relevance filtering
- Paper summarization
- Full-text analysis
- Research Gap analysis

Stable DSL:

dify/workflows/literature-search-v1.0.yml

## Dify v1.1

Status: Stable

Features:

- Unified `POST /api/v1/literature/search` endpoint
- Dify → LitWatch → OpenAlex architecture
- Provider-backed normalized Paper response
- Explicit 422, 502, and 504 error boundaries
- Offline API contract test coverage
- Docker Desktop access through `host.docker.internal:8000`

Stable DSL:

dify/workflows/literature-search-v1.1.yml

Stable tag:

dify-v1.1

Validation record:

docs/V1_1_E2E_RESULTS.md
