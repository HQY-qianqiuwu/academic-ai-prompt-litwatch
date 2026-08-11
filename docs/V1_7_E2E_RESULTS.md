# Stack v1.7 Research Radar E2E Results

Status: **STABLE**

Branch: `feat/v1.7-research-radar`

Base: `dify-v1.6` (`dec49ea2ecc466bfa2f8a71cf8f22b762e0e24c0`)

## Automated gate

- `python -m pytest -q`: 305 passed with one existing TestClient deprecation warning
- `ruff check src tests`: pass
- `git diff --check`: pass
- v1.0 Workflow DSL: unchanged from `dify-v1.0`
- v1.1 Workflow DSL: unchanged from `dify-v1.1`
- secret review: pass; no credentials are modeled or returned by Radar

## Real TDOA Radar

- Name: Underwater TDOA Evolution
- Topic: `underwater acoustic TDOA localization`
- Range: 2018-2026
- Recent window: 2 years
- Providers: OpenAlex, arXiv, Crossref
- Scan: partial success; an upstream rate limit was isolated
- Raw candidates: 500
- Deduplicated candidates: 150
- Persisted Radar papers: 171
- Annual points: 9
- Timeline periods: 3
- Persisted technical trends: 10
- Representative papers: 8
- Semantic-quality rescan: partial success, new papers = 23

## Real OFDM Radar

- Name: Underwater OFDM Evolution
- Topic: `underwater acoustic OFDM communication`
- Range: 2018-2026
- Recent window: 2 years
- Providers: OpenAlex, arXiv, Crossref
- Scan: partial success; an upstream rate limit was isolated
- Raw candidates: 500
- Deduplicated candidates: 150
- Persisted Radar papers: 164
- Annual points: 9
- Timeline periods: 3
- Persisted technical trends: 19
- Representative papers: 8
- Semantic-quality rescan: partial success, new papers = 6

The semantic-quality rescans produced clearly different technical themes.
TDOA emphasized robustness, multipath, neural networks, sensor networks, AUV,
TDOA measurement, and beamforming. OFDM emphasized channel behavior,
multipath, OFDM multiplexing, MIMO, adaptive modulation, channel estimation,
and deep learning. Radar history remained isolated by Radar ID.

## Trend semantic-quality gate

- Extraction is phrase-first: known technical phrases, validated two-/three-
  token concepts, and preserved acronyms are evaluated before standalone terms.
- Standalone vocabulary is restricted to maintained technical terms; academic
  boilerplate such as `demonstrate`, `proposes`, `used`, `however`, `two`, and
  `better` is not eligible.
- Conservative morphology normalization merges safe variants without stemming
  arbitrary domain vocabulary.
- Query-only background concepts remain available in corpus summaries but do
  not automatically become hot trends.
- Candidate frequency and evidence use distinct canonical IDs. A trend requires
  at least the greater of 3 documents or 2% corpus coverage; recent emerging/hot
  candidates require 3 recent documents.
- Real TDOA and OFDM trend-card checks found zero target generic-word leaks and
  zero trends without evidence IDs.

## Browser and regression evidence

- `/radars`, both Radar detail pages, Manual Search, Subscriptions, Weekly
  Digest, Provider Settings, API docs, and Dify returned HTTP 200.
- The TDOA detail rendered 9 annual columns, 10 trend cards, 8 representative
  paper cards, and scan-history cards without console errors.
- The OFDM detail rendered 19 trend cards after a real partial-success rescan.
- zh-CN and English both rendered Technical Theme Evolution, annual trends, timeline, trends,
  representative papers, and scan history without `undefined` or `NaN`.
- Trend evidence links resolve to persisted canonical IDs.
- Radar to Subscription prefilled topic, keywords, and runnable Providers;
  no Subscription was created without manual form submission.
- Lifecycle status reported Docker, Dify, LitWatch, OpenAlex, and SSRF Proxy
  ready. Restart retained both Radar histories and duplicate suppression.
- Automated partial-provider and all-provider failure tests passed; successful
  Provider evidence remains available for partial scans.

## Final manual acceptance

- TDOA Radar: pass
- OFDM Radar: pass
- Historical Research Radar and bounded backfill: pass
- Technical Topic Evolution: pass
- Generic Vocabulary Filtering: pass
- Trend Semantic Quality: pass
- Emerging / Sustained Trend Classification: pass
- Representative Papers and paper-grounded trend evidence: pass
- Evidence auto-expand: pass
- DOI display as `doi:10.xxxx/...`: pass
- DOI external navigation to `https://doi.org/10.xxxx/...`: pass
- DOI external-link security (`target="_blank"` and
  `rel="noopener noreferrer"`): pass
- Rescan duplicate suppression and restart persistence: pass
- Topic isolation: pass
- zh-CN and English UI: pass

The final DOI fix is `1f821a4 fix(radar): repair evidence DOI navigation`.
Stack v1.7 is Stable at the annotated `dify-v1.7` tag.
