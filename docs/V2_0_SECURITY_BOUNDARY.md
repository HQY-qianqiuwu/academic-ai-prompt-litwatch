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
Before dispatch, the egress payload limit checks the serialized user-message
content only. It is not a measurement of the complete outbound HTTP JSON
envelope, the system message, request headers, or a provider response.

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
values; jobs use opaque credential references where applicable. For the model
transport, the shared redactor removes common API-key assignments, bearer
values, cookie headers, credential-bearing URLs, environment credential
assignments, and JSON credential fields from the system instruction and from
the serialized user-message fields.

The redactor is not a general persistence or logging interceptor. Durable jobs
persist reviewed safe codes and messages instead of raw handler exceptions, and
analysis traces store fixed safe step errors instead of raw analyzer exceptions.
The current production runtime has no dedicated application log-emission
boundary for these values; therefore no regression claim is made for production
log redaction. Any future raw exception or evidence logging/persistence path
must either use the redactor at that boundary or use an allowlisted safe value.
The supported
policy rejection codes are `provider_kind_mismatch`, `cloud_consent_required`,
`fulltext_consent_required`, `payload_limit_exceeded`,
`token_limit_exceeded`, `job_cost_limit_exceeded`,
`daily_cost_limit_exceeded`, and `concurrency_limit_exceeded`. Model gateway
codes are `timeout`, `rate_limited`, `authentication`, `upstream`, `parse`, and
`validation`. Job safe-error codes include `timeout`, `upstream_error`,
`handler_error`, `worker_shutdown`, and `unsupported_job_type`; analysis traces
use `invalid_paper`, `analysis_failed`, or `persistence_failed`.

The regression suite uses unmistakably synthetic sentinels only. It checks the
real OpenAI-compatible Provider JSON request body, provider-profile and job
APIs, SQLite rows, and the rendered provider-settings HTML shell. The page
loads its secret-free profile data through the tested API; the server-rendered
shell itself does not interpolate profile values. The LLM serialization test is
mutation-proved by a local bypass of `LLMRequest.user_message_content`, restored
before commit.

## Cost, payload, and concurrency controls

Before dispatch, the runtime calculates an input estimate from the system
instruction plus serialized user-message content and reserves the request
against durable SQLite usage state. The estimate and payload guard do not cover
the complete HTTP envelope, request headers, or a provider response. The request
is rejected before egress when its measured user-message payload, estimated
tokens, per-job cost, daily cost, or active concurrency exceeds the configured
guard. Reservations are renewed while active and settled or released when the
request finishes.

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

## Audit command scope

The credential scan inspects only added lines in Git branch and staged diffs;
it never reads or prints `.env` or diff content. It counts matches for these
credential-shaped patterns: `sk-` values of at least 20 characters, bearer or
basic values of at least 16 characters, assignments for API-key/token/secret/
password/credential names with values of at least 16 characters, and private
key PEM headers. Known synthetic `*_SENTINEL` and `*_PLACEHOLDER` fixtures are
excluded from the count. The exact commands and zero-count evidence are retained
in the Task 3 report.
