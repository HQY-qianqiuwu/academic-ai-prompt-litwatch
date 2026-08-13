# V2.0 AI security boundary

This document defines the runtime boundary for optional AI analysis and PDF
retrieval. It applies to the Python-native LitWatch runtime; legacy Dify
workflows do not add a second execution path or a credentials boundary.

## Consent and cloud egress

No model runtime is constructed unless `LITWATCH_LLM_API_KEY` is configured.
Local providers may receive the declared evidence scope. Cloud providers are
fail-closed: any cloud request requires explicit
`LITWATCH_LLM_CLOUD_EGRESS_CONSENT`. Cloud requests that include
`fulltext_excerpt`, `fulltext`, or `notes` also require the separate
`LITWATCH_LLM_FULLTEXT_EGRESS_CONSENT` consent.

The configured provider kind must match the trusted runtime classification;
caller-provided classification cannot turn a cloud endpoint into a local one.
The actual serialized payload length is checked before provider dispatch.

## Prompt and evidence boundary

Trusted system instructions are supplied in exactly one system message. Trusted
user instructions and untrusted evidence are serialized into distinct fields in
one user message. Evidence is data, never a role, tool instruction, or trusted
system prompt. Analysis facts declare an evidence scope:

- `metadata_only`: provider-owned metadata only.
- `abstract`: provider-owned abstract evidence.
- `fulltext_excerpt`: a bounded retrieved excerpt.
- `fulltext`: reserved gateway scope; the paper-analysis job rejects complete
  full-text input.
- `notes`: a gateway policy scope, treated as full-text-like cloud egress.

The model may not invent literature metadata. Titles, authors, DOI, venue,
publication date, and URLs remain provider-owned data.

## Secret and error handling

Credentials are write-only at the provider-profile API and are held only in the
runtime credential store. Provider options and job payloads reject credential
values; jobs use opaque credential references where applicable. The shared
redactor removes common API-key assignments, bearer values, cookie headers,
credential-bearing URLs, environment credential assignments, and JSON
credential fields before text crosses a persistence, model, or log projection.

Do not persist or log raw upstream exception text. Jobs persist reviewed safe
codes and messages; analysis traces record safe step errors only. The supported
policy rejection codes are `provider_kind_mismatch`, `cloud_consent_required`,
`fulltext_consent_required`, `payload_limit_exceeded`,
`token_limit_exceeded`, `job_cost_limit_exceeded`,
`daily_cost_limit_exceeded`, and `concurrency_limit_exceeded`. Model gateway
codes are `timeout`, `rate_limited`, `authentication`, `upstream`, `parse`, and
`validation`. Job safe-error codes include `timeout`, `upstream_error`,
`handler_error`, `worker_shutdown`, and `unsupported_job_type`; analysis traces
use `invalid_paper`, `analysis_failed`, or `persistence_failed`.

The regression suite uses unmistakably synthetic sentinels only. It checks API,
SQLite, HTML, log, and serialized-model projections and is mutation-proved with
a local redaction bypass that is restored before commit.

## Cost, payload, and concurrency controls

Before dispatch, the runtime calculates a conservative input estimate from the
serialized payload and reserves the request against durable SQLite usage state.
The request is rejected before egress when its payload, estimated tokens,
per-job cost, daily cost, or active concurrency exceeds the configured guard.
Reservations are renewed while active and settled or released when the request
finishes.

The boundary environment-setting names are:

- `LITWATCH_LLM_API_KEY`
- `LITWATCH_LLM_BASE_URL`
- `LITWATCH_LLM_MODEL`
- `LITWATCH_LLM_PROVIDER_KIND`
- `LITWATCH_LLM_MAX_OUTPUT_TOKENS`
- `LITWATCH_LLM_MAX_PAYLOAD_CHARS`
- `LITWATCH_LLM_INPUT_COST_PER_MILLION`
- `LITWATCH_LLM_OUTPUT_COST_PER_MILLION`
- `LITWATCH_LLM_CLOUD_EGRESS_CONSENT`
- `LITWATCH_LLM_FULLTEXT_EGRESS_CONSENT`
- `LITWATCH_MAX_TOKENS_PER_JOB`
- `LITWATCH_MAX_COST_PER_JOB`
- `LITWATCH_MAX_DAILY_COST`
- `LITWATCH_MAX_CONCURRENT_LLM_JOBS`
- `LITWATCH_REQUEST_TIMEOUT_SECONDS`
- `LITWATCH_JOB_POLL_SECONDS`
- `LITWATCH_JOB_CONCURRENCY`
- `LITWATCH_JOB_DEFAULT_TIMEOUT_SECONDS`
- `LITWATCH_JOB_LEASE_SECONDS`
- `LITWATCH_FULLTEXT_TOP_N`

`LITWATCH_REQUEST_TIMEOUT_SECONDS` bounds outbound request timing.
`LITWATCH_JOB_POLL_SECONDS`, `LITWATCH_JOB_CONCURRENCY`,
`LITWATCH_JOB_DEFAULT_TIMEOUT_SECONDS`, and `LITWATCH_JOB_LEASE_SECONDS`
govern the durable worker boundary. `LITWATCH_FULLTEXT_TOP_N` bounds selection
for full-text work. Review these settings together when changing throughput or
cost posture.

## PDF network boundary

PDF retrieval accepts only HTTPS URLs without URL credentials, fragments, local
hosts, or non-public DNS/IP results. Every redirect is followed manually only
after validating its next URL; redirects are bounded and automatic redirects
are disabled. The request connects to a validated resolved address while
retaining the validated host/SNI, so DNS resolution is part of the decision.

The extractor requires `application/pdf` content type or a `%PDF` signature,
enforces configured byte and character limits while streaming, uses a bounded
timeout, disables environment proxy trust, and returns generic safe failures
rather than reflecting remote response content. These rules also apply to
redirect destinations; no private-network allowlist exists.
