# V1.2 Provider Configuration

## 1. Status and Scope

v1.2 establishes the provider-configuration boundary for LitWatch. The code and
offline tests are complete, but local end-to-end validation is still pending.
Therefore v1.2 is not yet Stable and no `dify-v1.2` tag exists.

OpenAlex is the only runnable literature provider in v1.2. Semantic Scholar,
arXiv, Crossref, IEEE Xplore, Scopus, and Web of Science are capability records
only. Selecting one of those providers returns a configuration error instead of
fabricated papers or an empty success response.

This release does not add RSS, Zotero, LLM analysis, PDF/full-text processing,
research-gap analysis, SQLite provider persistence, or a new Dify DSL.

## 2. Architecture

```text
User / Dify
    -> POST /api/v1/literature/search
    -> LiteratureSearchService
    -> ProviderProfileStore
    -> ProviderRegistry
    -> OpenAlexSource
    -> list[Paper]
```

The service selects providers by stable `provider_id`. The registry owns the
mapping from `provider_type` to a runnable `PaperSource` factory. This keeps the
service free of provider-specific HTTP clients and permits future adapters to be
added through a factory registration and configuration rather than another
search-service branch.

## 3. Provider Configuration Model

Each non-secret provider configuration contains:

- `provider_id`: unique lowercase identifier inside a profile.
- `provider_type`: stable capability identifier.
- `enabled`: whether the provider participates in default searches.
- `base_url`: user-configurable HTTPS/HTTP endpoint.
- `requires_api_key`: whether a credential must resolve before execution.
- `credential_reference`: opaque lookup name, never the credential value.
- `options`: provider parameters that are safe to serialize.

Credential-like option names are rejected. Keys, tokens, passwords, and bearer
values must not be placed in `options`, YAML, Python, Dify DSL, or Git.

The default profile contains one enabled, keyless OpenAlex provider and preserves
the v1.1 behavior.

## 4. Provider API

### List capabilities

```http
GET /api/v1/providers
```

The response reports `provider_type`, display name, and `runnable`. In v1.2 only
OpenAlex reports `runnable: true`.

### List profiles

```http
GET /api/v1/provider-profiles
```

Responses include safe configuration plus `configured`. They never include an
API key or credential value.

### Create or replace a profile

```http
POST /api/v1/provider-profiles
```

POST uses full-profile replacement semantics. A caller updating the `default`
profile should include OpenAlex if backward-compatible default search must remain
available. An API key may be supplied only with `requires_api_key: true` and a
`credential_reference`; the response returns only `configured: true`.

Credentials submitted through this local API remain in process memory and are
lost when LitWatch restarts. They are not written to JSON, YAML, SQLite, logs, or
API responses. For restart-safe local configuration, use environment variables
or an ignored `.env` file.

## 5. Search Compatibility and Selection

The v1.1 request remains valid:

```json
{
  "topic": "underwater acoustic TDOA localization",
  "limit": 10
}
```

Without `providers`, LitWatch uses all enabled providers in the active profile.
The v1.2 request may select providers explicitly:

```json
{
  "topic": "underwater acoustic TDOA localization",
  "limit": 10,
  "providers": ["openalex"]
}
```

Unknown, disabled, duplicate, unconfigured, or non-runnable provider selections
return HTTP 422. Provider timeouts and upstream failures retain the v1.1 504/502
boundary. Provider exceptions are never converted into empty search results.

## 6. Environment and Credential References

The repository tracks only `.env.example`; `.env` is ignored by Git. Leave all
credential values empty in the tracked example.

Current predefined references are:

| Credential reference | Environment setting |
| --- | --- |
| `semantic_scholar_default` | `LITWATCH_SEMANTIC_SCHOLAR_API_KEY` |
| `ieee_xplore_default` | `LITWATCH_IEEE_XPLORE_API_KEY` |

These references prepare future adapters; they do not make those providers
runnable in v1.2.

## 7. Validation and Release Boundary

Checkpoint validation requires:

```powershell
python -m pytest -q
.venv\Scripts\ruff.exe check src tests
```

Both stable DSL files must remain byte-for-byte unchanged relative to their tags:

```powershell
git diff dify-v1.0 -- dify/workflows/literature-search-v1.0.yml
git diff dify-v1.1 -- dify/workflows/literature-search-v1.1.yml
```

Before v1.2 can become Stable, perform local host API, Docker networking, and Dify
runtime tests. Do not create `dify-v1.2` until those manual checks pass.
