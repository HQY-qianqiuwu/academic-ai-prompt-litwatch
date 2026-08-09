# V1.3 Provider BYOK Configuration

## 1. What BYOK Means

BYOK (Bring Your Own Key) lets a user supply an optional credential and a compatible
endpoint for a provider adapter that LitWatch already implements. It does not turn an
arbitrary URL into a new literature provider. Every configured provider continues to use
its known request contract and response parser.

The v1.3 runnable provider types are OpenAlex, Semantic Scholar, arXiv, and Crossref.
IEEE Xplore, Scopus, and Web of Science remain declarations only and are not made runnable
by adding a URL or credential.

## 2. Supported Providers and Defaults

| Provider | Default endpoint | Credential | Default selected |
| --- | --- | --- | --- |
| OpenAlex | `https://api.openalex.org/works` | Not required | Yes |
| Semantic Scholar | `https://api.semanticscholar.org` | Optional `x-api-key` | No |
| arXiv | `https://export.arxiv.org/api/query` | Not required | No |
| Crossref | `https://api.crossref.org/v1/works` | Not required; `mailto` supported | No |

The Semantic Scholar adapter accepts both the API root above and the legacy full search
endpoint. When given the API root, it appends `/graph/v1/paper/search`.

## 3. Semantic Scholar Anonymous and Authenticated Modes

Semantic Scholar remains usable without a key. Anonymous access uses the upstream shared
pool and may return HTTP 429. LitWatch reports that condition as `rate_limited` and
`upstream_429`; it does not disguise the failure as an empty result.

Authenticated access uses the provider-specific `x-api-key` header. The Provider Profile
layer stores only the secret value and an opaque credential reference. It does not store a
complete authorization header or assume that every provider uses bearer authentication.

Credential precedence is:

1. Runtime Provider Profile secret.
2. `LITWATCH_SEMANTIC_SCHOLAR_API_KEY` loaded from the process environment or local `.env`.
3. Anonymous access.

Clearing a runtime secret removes only the runtime override. An environment credential, if
configured, becomes active again.

## 4. Environment Configuration

For a credential that survives LitWatch restarts, set the following only in the local
environment or the repository-root `.env` file:

```dotenv
LITWATCH_SEMANTIC_SCHOLAR_API_KEY=test-secret-not-real
```

The repository contains the empty variable in `.env.example`; never put a real value in
that tracked example. `.env` is ignored by Git.

## 5. Provider Profile API

The existing endpoints remain authoritative:

- `GET /api/v1/provider-profiles`
- `POST /api/v1/provider-profiles`

A full Semantic Scholar configuration can be submitted as follows. The value shown is a
deliberately fake example:

```json
{
  "profile_id": "default",
  "providers": [
    {
      "provider_id": "semantic_scholar",
      "provider_type": "semantic_scholar",
      "enabled": true,
      "default_selected": false,
      "base_url": "https://api.semanticscholar.org",
      "api_key": "test-secret-not-real"
    }
  ]
}
```

`api_key` is write-only. The response reports `credential_configured` but never returns the
secret:

```json
{
  "provider_id": "semantic_scholar",
  "provider_type": "semantic_scholar",
  "enabled": true,
  "default_selected": false,
  "base_url": "https://api.semanticscholar.org/",
  "requires_api_key": false,
  "credential_reference": "semantic_scholar_default",
  "options": {},
  "configured": true,
  "credential_configured": true
}
```

`configured` is retained for v1.2 compatibility and describes whether the provider can run;
an optional-key provider can therefore be configured for anonymous use.
`credential_configured` specifically describes whether a credential is present.

## 6. Partial Updates and Secret Preservation

The legacy full POST remains a profile replacement. A provider entry that omits one of
`provider_type`, `enabled`, or `base_url` is treated as a partial update to an existing
profile. Fields that are not supplied are preserved. In particular, omitting `api_key`
does not clear the current runtime secret:

```json
{
  "profile_id": "default",
  "providers": [
    {
      "provider_id": "semantic_scholar",
      "enabled": false
    }
  ]
}
```

Secret removal must be explicit:

```json
{
  "profile_id": "default",
  "providers": [
    {
      "provider_id": "semantic_scholar",
      "clear_secret": true
    }
  ]
}
```

`api_key` and `clear_secret` cannot be submitted together.

## 7. Base URL Overrides

An override selects a compatible endpoint for the same known adapter. For example, a
Semantic Scholar-compatible gateway still uses `SemanticScholarSource` and must return the
Semantic Scholar response schema. LitWatch does not infer unknown JSON schemas and does not
provide a generic arbitrary provider.

Crossref can receive a polite-pool identity through the provider `options` object:

```json
{
  "options": {
    "mailto": "researcher@example.com"
  }
}
```

If omitted, `LITWATCH_CROSSREF_EMAIL` remains the fallback.

## 8. SSRF and Redirect Protection

User-controlled provider endpoints are checked when a profile URL is saved and again
immediately before a provider is built for a search. The validator:

- Requires HTTPS.
- Rejects credentials embedded in URLs.
- Rejects `localhost`, subdomains of `localhost`, local Docker/service names, and scoped IPs.
- Rejects loopback, private, link-local, CGNAT, multicast, reserved, and unspecified IPv4
  and IPv6 addresses.
- Resolves hostnames and rejects the entire endpoint if any returned address is non-public.
- Rejects DNS failures instead of allowing an unverifiable endpoint.

All four provider HTTP clients disable automatic redirects. A public endpoint therefore
cannot redirect LitWatch to a private or metadata address. A redirect is surfaced as an
upstream failure rather than followed.

## 9. Secret Redaction and Persistence

Secrets are excluded from provider models, GET responses, provider status, ordinary logs,
and safe HTTP errors. Validation errors do not echo the submitted request body. Runtime
profile secrets are process-memory only and are cleared by a LitWatch restart. Use a local
`.env` or process environment variable for persistence across restarts.

No Provider secret is written to SQLite, Dify Workflow DSL, source code, or Git.

## 10. Current Scope

This extension does not add a Provider Settings Web UI or a Test Connection endpoint. A
future UI may safely build on the existing profile API and display only readiness and safe
error codes. It must not expose raw responses, headers, or credentials.
