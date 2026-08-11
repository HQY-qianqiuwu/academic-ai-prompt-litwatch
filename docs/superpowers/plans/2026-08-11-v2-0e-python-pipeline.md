# V2.0E Python Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the existing Pipeline into one typed Python analysis path backed by `LLMGateway` and durable jobs.

**Architecture:** `PaperAnalysis` is the stable contract. Focused step functions operate on `AnalysisContext`; `Pipeline.run()` remains a compatibility adapter and does not construct a second retrieval stack.

**Tech Stack:** Pydantic, SQLite, existing Pipeline and LiteratureSearchService, pytest.

## Global Constraints

- Canonical metadata is Provider-owned and immutable to LLM output.
- Missing facts are `None`/`[]`, never guessed.
- Complete deep reading remains outside v2.0.

---

### Task 1: Structured PaperAnalysis and persistence

**Files:**
- Create: `src/litwatch/analysis_models.py`
- Create: `src/litwatch/analysis_repository.py`
- Modify: `src/litwatch/db.py`
- Test: `tests/test_paper_analysis.py`

**Interfaces:**
- `EvidenceScope`: metadata_only/abstract/fulltext_excerpt/fulltext.
- `AnalysisEvidence(field, excerpt, evidence_scope, section, page)`.
- `PaperAnalysis` fields and statuses exactly match the design spec.
- `AnalysisRepository.upsert()` keyed by canonical ID, analysis version, evidence hash, and model-config hash.

- [ ] **Step 1: Add failing tests for strict unknown-field rejection, missing values, evidence scope, metadata exclusion, idempotent upsert, and restart retrieval.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Add migration 8 for typed analysis records and implement the models/repository.**
- [ ] **Step 4: Run analysis and migration tests; verify PASS.**
- [ ] **Step 5: Commit with `feat(analysis): add structured paper analysis contract`.**

### Task 2: Refactor the existing Pipeline

**Files:**
- Modify: `src/litwatch/pipeline.py`
- Modify: `src/litwatch/analysis.py`
- Create: `src/litwatch/services/paper_analysis.py`
- Test: `tests/test_pipeline_runtime.py`

**Interfaces:**
- `AnalysisContext(paper, topic, evidence, evidence_scope, trace)`.
- `PaperAnalysisService.analyze(context) -> PaperAnalysis`.
- Compatibility `Pipeline.run(days=None, topics=None)` retains its public return type.

- [ ] **Step 1: Add failing tests proving Pipeline receives `LiteratureSearchService`, does not instantiate Provider classes, runs typed steps in order, skips LLM when evidence/key is absent, validates output, persists once, and traces safe step status.**
- [ ] **Step 2: Verify RED and identify direct source construction as the expected failure.**
- [ ] **Step 3: Refactor `Pipeline` to delegate retrieval, convert extractive/model results to `PaperAnalysis`, and remove duplicate retry/persistence logic.**
- [ ] **Step 4: Run pipeline, search, core, and analysis tests; verify PASS.**
- [ ] **Step 5: Commit with `refactor(pipeline): unify Python paper analysis flow`.**

### Task 3: Paper analysis job handler and API

**Files:**
- Modify: `src/litwatch/services/paper_analysis.py`
- Modify: `src/litwatch/runtime.py`
- Modify: `src/litwatch/web.py`
- Modify: `src/litwatch/api_models.py`
- Test: `tests/test_paper_analysis_api.py`

- [ ] **Step 1: Add failing tests for 202 analysis creation, idempotent duplicate submission, completed result reference, cancellation/timeout propagation, and canonical metadata unchanged.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Register `paper_analysis` handler, validate canonical ID/evidence scope, and expose create/read routes through generic jobs.**
- [ ] **Step 4: Run API/job/pipeline tests and full suite; verify PASS.**
- [ ] **Step 5: Commit with `feat(analysis): execute paper analysis as durable jobs`.**

