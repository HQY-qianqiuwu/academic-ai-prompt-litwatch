# Stack v1.7 Research Radar E2E Results

Status: **RELEASE CANDIDATE**

Branch: `feat/v1.7-research-radar`

Base: `dify-v1.6` (`dec49ea2ecc466bfa2f8a71cf8f22b762e0e24c0`)

## Automated gate

- `python -m pytest -q`: 288 passed with one existing TestClient deprecation warning
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
- Scan: success
- Raw candidates: 750
- Deduplicated Radar papers: 148
- Annual points: 9
- Timeline periods: 3
- Persisted trends: 100
- Representative papers: 8
- Immediate post-restart rescan: success, new papers = 0

## Real OFDM Radar

- Name: Underwater OFDM Evolution
- Topic: `underwater acoustic OFDM communication`
- Range: 2018-2026
- Recent window: 2 years
- Providers: OpenAlex, arXiv, Crossref
- Scan: success
- Raw candidates: 750
- Deduplicated Radar papers: 147
- Annual points: 9
- Timeline periods: 3
- Persisted trends: 100
- Representative papers: 8
- Immediate rescan: success, new papers = 0

The TDOA and OFDM Radar sets had zero overlapping persisted canonical IDs in
this run. Their top terms were also distinct: TDOA emphasized localization,
sensor networks, accuracy, and TDOA; OFDM emphasized OFDM, communication,
channel, frequency, and multiplexing. Radar history remained isolated by
Radar ID.

## Browser and regression evidence

- `/radars`, both Radar detail pages, Manual Search, Subscriptions, Weekly
  Digest, Provider Settings, API docs, and Dify returned HTTP 200.
- The TDOA detail rendered 9 annual columns, 100 trend cards, 8 representative
  paper cards, and 2 scan-history cards without console errors.
- zh-CN and English both rendered annual trends, timeline, trends,
  representative papers, and scan history without `undefined` or `NaN`.
- Trend evidence links resolve to persisted canonical IDs.
- Radar to Subscription prefilled topic, keywords, and runnable Providers;
  no Subscription was created without manual form submission.
- Lifecycle status reported Docker, Dify, LitWatch, OpenAlex, and SSRF Proxy
  ready. Restart retained both Radar histories and duplicate suppression.
- Automated partial-provider and all-provider failure tests passed; successful
  Provider evidence remains available for partial scans.

Manual acceptance is still required. No `dify-v1.7` tag was created.
