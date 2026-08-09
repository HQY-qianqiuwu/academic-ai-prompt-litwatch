# Stack v1.5 Web UI E2E Results

Status: **RELEASE CANDIDATE**

Branch: `feat/v1.5-web-ui`

Stable base: `dify-v1.4` at `bb6f2aaff217e5bd4a6fb2f21451e9ad7601fbac`

Stack v1.5 adds a browser interface to the existing FastAPI/Jinja2/vanilla
JavaScript application. It does not change the stable Dify workflow contract or
the deterministic v1.4 retrieval, deduplication, merge, and ranking logic.

## Runtime identity

- LitWatch module: current repository `src/litwatch/web.py`
- Runtime launcher: current repository `.venv/Scripts/litwatch.exe`
- Health: PASS
- OpenAlex capability: `runnable=true`
- Old `D:\\文献查找app` runtime: not used

## Browser Topic A

Query: `underwater acoustic TDOA localization`

Selected Providers: OpenAlex, arXiv, Crossref

Result:

- Search: PASS
- Paper cards: 10
- TDOA-related leading results: PASS
- Backend ranking order preserved: PASS
- Rank, relevance, and quality values rendered: PASS
- Real source badges rendered: PASS
- Raw candidates: 60
- Unique papers: 57
- Duplicates removed: 3
- Dedup arithmetic (`60 - 57 = 3`): PASS
- Multi-source card observed with `crossref` and `openalex`: PASS

The leading result was `Synchronization-Free Underwater Acoustic Localization
for Autonomous Platforms: A Neural Network TDOA Approach and the Role of
Receiver Geometry`.

## Browser Topic B

Query: `underwater acoustic OFDM communication`

Selected Providers: OpenAlex, arXiv, Crossref

Result:

- Search: PASS
- Paper cards: 10
- OFDM-related leading results: PASS
- Result set clearly different from Topic A: PASS
- Raw candidates: 60
- Unique papers: 60
- Duplicates removed: 0

The leading result was `Adaptive Modulation for Underwater Acoustic OFDM
Communication`.

## Partial Provider failure

Query: `underwater acoustic OFDM communication`

Selected Providers: OpenAlex, Semantic Scholar

Result:

- Overall response with available papers: PASS
- OpenAlex: success, 10 returned
- Semantic Scholar anonymous: `rate_limited`, zero returned
- Semantic Scholar authenticated real success: **NOT VERIFIED**
- Successful paper cards remained visible: PASS
- Partial-failure warning and Provider diagnostics: PASS
- Whole-page failure avoided: PASS

## Provider Settings

- Profiles loaded through the existing GET API: PASS
- Provider save through the existing POST API: PASS
- Fake Semantic Scholar key accepted: PASS
- Input cleared after save: PASS
- Credential status changed to configured: PASS
- Fake key absent from page text and GET responses: PASS
- Empty-key preservation contract: PASS by automated test
- Explicit clear contract: PASS by automated test and official Profile API
- Browser clear confirmation displayed: PASS
- Invalid private URL rejection: PASS by automated test
- Valid public HTTPS URL acceptance: PASS by automated test
- Fake runtime key cleanup: PASS
- Final Semantic Scholar credential state: not configured

No real API key was used or recorded during the UI test.

## Responsive and accessibility checks

- Desktop browser interaction: PASS
- 375px effective mobile width, Search: no horizontal overflow
- 375px effective mobile width, Settings: no horizontal overflow
- Provider choices collapse to one column: PASS
- Labels, disabled Provider state, live status text, keyboard focus styles, and
  skip links: PASS

## Deferred items

- Year/date filter: deferred because the stable HTTP search contract does not
  expose a consistent cross-Provider range.
- Provider Test Connection: deferred because there is no existing safe endpoint
  and v1.5 does not expand backend security semantics.
- Stable `dify-v1.5` tag: intentionally absent pending manual UI acceptance.

## Automated gate

- Tests before RC documentation: 179 passed
- Ruff: PASS
- `git diff --check`: PASS
- Provider Registry, retrieval, deduplication, ranking, BYOK, SSRF, redaction,
  and partial-failure regression coverage: PASS
- v1.0 DSL: unchanged
- v1.1 DSL: unchanged

Final RC documentation is followed by one more complete automated gate. The
manual acceptance gate remains open, so this document records a Release
Candidate rather than a Stable release.
