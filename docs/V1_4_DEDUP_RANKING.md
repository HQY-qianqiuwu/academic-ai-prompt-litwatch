# Stack v1.4 Deterministic Deduplication and Ranking

Status: implementation design approved for the v1.4 release-candidate branch

## Scope and compatibility boundary

Stack v1.4 changes only the provider-backed `LiteratureSearchService` path:

```text
provider retrieval
    -> candidate pool
    -> deterministic deduplication and metadata merge
    -> deterministic relevance and quality scoring
    -> stable final ranking
    -> final response limit
```

The existing request forms remain valid:

```json
{"topic": "underwater acoustic localization", "limit": 10}
```

```json
{
  "topic": "underwater acoustic localization",
  "limit": 10,
  "providers": ["openalex", "semantic_scholar", "arxiv", "crossref"]
}
```

`paper_count` and `papers` remain present and retain their current meanings.
The stable Workflow v1.1 therefore remains compatible. Stack v1.4 does not
change the legacy scheduled `Pipeline`, its topic gates, or its optional
semantic model. It adds no LLM, embedding, vector database, RSS, Zotero, PDF,
full-text, Research Gap, or Web UI capability.

## Candidate budget and limit semantics

For a requested final `limit = L`, each selected provider receives:

```text
candidate_limit_per_provider = min(50, 2 * L)
```

The API already bounds `L` to `1..50`, so this formula is finite and never asks
one provider for more than 50 candidates. Fetching precedes deduplication and
ranking. The final `limit` is applied only after both operations.

## DOI normalization

The internal canonical DOI is a lowercase bare DOI such as
`10.1234/example`. Normalization uses Unicode NFKC, trims whitespace, and
removes one case-insensitive leading form:

- `doi:`
- `https://doi.org/`
- `http://doi.org/`
- `https://dx.doi.org/`
- `http://dx.doi.org/`

No DOI is inferred. A value that does not start with `10.` after normalization
is treated as absent for deduplication. The merged `Paper.doi` uses the bare
form, matching the existing HTTP contract, and its preferred URL is
`https://doi.org/{canonical_doi}`.

## Title normalization and cautious similarity

Title normalization uses Unicode NFKC and case folding, converts punctuation
and symbol runs to a single space, collapses whitespace, and trims the result.
Letters, technical abbreviations, and digits are retained. Consequently terms
such as `TDOA`, `OFDM`, `MIMO`, `DOA`, `AUV`, `UWSN`, `3D`, `2D`, and the
components of `U-Net` remain available to matching and scoring.

Near-title matching is intentionally conservative. It is allowed only when:

1. both titles contain at least five normalized tokens;
2. both titles contain exactly the same numeric tokens;
3. both titles contain exactly the same protected technical tokens;
4. token-set Jaccard similarity is at least `0.95`; and
5. character-sequence similarity is at least `0.95`.

This level handles harmless word-order or punctuation differences without
merging titles that differ in a method, dimensionality, model name, or other
substantive term.

## Deduplication hierarchy

Pairs are linked in the following order; transitive groups are resolved with a
deterministic union-find pass:

1. exact canonical DOI;
2. exact non-title canonical identifier, for example a shared arXiv identity;
3. exact normalized title;
4. conservative near-title match defined above.

The input is sorted before grouping, and every merged field uses a deterministic
selector. Reversing provider order must therefore produce the same merged paper
and final ordering.

## Metadata merge rules

Only values present in real Provider records participate. No field is generated
or completed by an LLM.

| Field | Deterministic rule |
|---|---|
| `sources` | sorted unique union |
| `source_ids` | sorted keys; conflicting non-empty values choose lexical minimum |
| `doi` | normalized real DOI; lexical minimum if conflicting |
| `canonical_id` | DOI identity, else lexical minimum shared non-title identity, else chosen-title identity |
| `title` | most normalized tokens, then longest normalized text, then lexical minimum |
| `authors` | greatest author count, then greatest total normalized name length, then lexical tuple |
| `publication_date` | earliest real date |
| `venue` | greatest normalized information length, then lexical minimum |
| `abstract` | greatest normalized information length, then lexical minimum |
| `url` | canonical DOI URL when DOI exists; otherwise HTTPS before HTTP, then lexical minimum |
| `pdf_url` | HTTPS before HTTP, then lexical minimum |
| `is_open_access` | logical OR |
| `citation_count` | greatest real non-negative count |

## Tokenization

Query and evidence tokenization uses Unicode NFKC, case folding, and
alphanumeric token extraction. A small fixed English stopword set removes only
common function words such as `the`, `and`, `of`, `for`, `using`, `a`, and
`an`. No stemming, lemmatization, translation, or external NLP model is used.

## Relevance score

Let `Q` be the unique non-stopword query tokens. All coverage values are in
`0..1` and use `0` when `Q` is empty.

```text
title_coverage       = |Q intersect title_tokens| / |Q|
abstract_coverage    = |Q intersect abstract_tokens| / |Q|
ordered_pair_coverage = matched adjacent query-token pairs in title
                        / max(1, number of adjacent query-token pairs)
exact_phrase_title   = 1 when the normalized query is a title phrase, else 0
all_query_title      = 1 when every query token occurs in the title, else 0

relevance_score =
    0.50 * title_coverage
  + 0.15 * abstract_coverage
  + 0.15 * ordered_pair_coverage
  + 0.10 * exact_phrase_title
  + 0.10 * all_query_title
```

Title evidence therefore contributes most of the score. Complete query and
phrase matches receive explicit rewards, so a TDOA-localization or OFDM title
outranks a paper matching only generic underwater terms.

## Quality score

Quality uses only real metadata already present in the unified `Paper` model.
No venue prestige, impact factor, or inferred quality is used.

```text
quality_score =
    0.10 * title_present
  + 0.15 * authors_present
  + 0.10 * publication_date_present
  + 0.10 * venue_present
  + 0.15 * canonical_doi_present
  + 0.25 * abstract_present
  + 0.15 * min(1, unique_source_count / 2)
```

Citation count and recency are deliberately excluded from v1.4: their coverage
is inconsistent across Providers and time-dependent scoring would weaken exact
reproducibility.

## Final score and stable ordering

```text
rank_score = 0.85 * relevance_score + 0.15 * quality_score
```

Relevance is the dominant component. Stable ordering uses:

1. `rank_score` descending;
2. `relevance_score` descending;
3. `quality_score` descending;
4. publication year descending, with missing year last;
5. normalized title ascending;
6. canonical identifier ascending.

Scores are rounded to six decimal places only after component calculation.
No ordering step depends on set or dictionary iteration order.

## Additive diagnostics

The HTTP response adds one top-level `diagnostics` object while leaving each
existing paper projection unchanged:

```json
{
  "raw_count": 40,
  "dedup_count": 31,
  "duplicates_removed": 9,
  "candidate_limit_per_provider": 20,
  "ranking": [
    {
      "canonical_id": "doi:10.1234/example",
      "rank_score": 0.91,
      "relevance_score": 0.95,
      "quality_score": 0.68
    }
  ]
}
```

`dedup_count` means the number of unique candidates before the final response
limit. Ranking diagnostics include only returned papers and remain additive.
Provider status remains additive and sanitized.

## Failure isolation

Provider execution and error classification stay ahead of the processing
pipeline. A Semantic Scholar HTTP 429 remains
`rate_limited/upstream_429`; successful Providers continue through deduplication
and ranking. If every selected Provider fails, the existing aggregate failure
behavior and HTTP mapping remain unchanged.

## Test cases

Synthetic unit fixtures cover:

- DOI equality, case folding, and DOI URL normalization;
- exact-title merging and near-title false-positive protection;
- source union and deterministic author, abstract, date, venue, URL, and
  identifier conflict resolution;
- input-order independence;
- TDOA and OFDM golden relevance ordering;
- quality ordering for equally relevant papers;
- high relevance outranking low relevance with complete metadata;
- deterministic tie-breaking;
- candidate budget and limit-after-dedup behavior;
- additive API diagnostics and the unchanged `paper_count`/`papers` contract;
- OpenAlex-only default, explicit multi-provider selection, Provider status,
  partial failure, BYOK, and SSRF regressions.

Real E2E is performed only after unit gates pass. It compares the TDOA and OFDM
topics without altering Provider results and records raw, deduplicated, merged
source, and top-result evidence for manual release-candidate review.
