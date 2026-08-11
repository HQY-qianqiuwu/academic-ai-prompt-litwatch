from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from litwatch.analysis_models import AnalysisEvidence, EvidenceScope, PaperAnalysis
from litwatch.analysis_repository import AnalysisRepository
from litwatch.db import MIGRATION_REGISTRY, Database
from litwatch.models import Paper


def _analysis(**overrides) -> PaperAnalysis:
    values = {
        "canonical_id": "doi:10.1000/example",
        "analysis_version": "v1",
        "evidence_hash": "a" * 64,
        "model_config_hash": "b" * 64,
        "status": "completed",
        "evidence_scope": "abstract",
        "research_question": "How is robust localization achieved?",
        "methods": ["time-difference estimation"],
        "evidence": [
            {
                "field": "methods",
                "excerpt": "We estimate time differences using a robust estimator.",
                "evidence_scope": "abstract",
                "section": "Abstract",
                "page": None,
            }
        ],
    }
    values.update(overrides)
    return PaperAnalysis.model_validate(values)


def _database_with_paper(path) -> Database:
    database = Database(path)
    run_id = database.start_run()
    database.upsert(
        Paper(
            canonical_id="doi:10.1000/example",
            title="Provider-owned title",
            doi="10.1000/example",
        ),
        run_id,
    )
    return database


def test_structured_analysis_defaults_missing_facts_to_none_and_empty_lists():
    analysis = PaperAnalysis(
        canonical_id="doi:10.1000/example",
        analysis_version="v1",
        evidence_hash="a" * 64,
        model_config_hash="b" * 64,
        status="skipped",
        evidence_scope=EvidenceScope.METADATA_ONLY,
    )

    assert analysis.research_question is None
    assert analysis.motivation is None
    assert analysis.methods == []
    assert analysis.key_modules == []
    assert analysis.baselines == []
    assert analysis.datasets == []
    assert analysis.experimental_setup == []
    assert analysis.metrics == []
    assert analysis.main_results == []
    assert analysis.contributions == []
    assert analysis.limitations == []
    assert analysis.future_work == []
    assert analysis.evidence == []


@pytest.mark.parametrize(
    "scope",
    ["metadata_only", "abstract", "fulltext_excerpt", "fulltext"],
)
def test_evidence_scope_accepts_only_the_approved_values(scope):
    evidence = AnalysisEvidence(
        field="main_results",
        excerpt="The measured error decreased.",
        evidence_scope=scope,
    )
    assert evidence.evidence_scope.value == scope

    with pytest.raises(ValidationError):
        AnalysisEvidence(
            field="main_results",
            excerpt="Unsupported scope.",
            evidence_scope="complete_pdf",
        )


def test_models_reject_unknown_fields_and_provider_owned_metadata():
    with pytest.raises(ValidationError):
        _analysis(unsupported_claim="not allowed")

    for field, value in {
        "title": "LLM title",
        "authors": ["Invented Author"],
        "venue": "Invented Venue",
        "publication_date": "2026-08-11",
        "doi": "10.9999/invented",
        "url": "https://example.test/invented",
        "pdf_url": "https://example.test/invented.pdf",
    }.items():
        with pytest.raises(ValidationError):
            _analysis(**{field: value})

    with pytest.raises(ValidationError):
        AnalysisEvidence(
            field="methods",
            excerpt="Evidence.",
            evidence_scope="abstract",
            unknown_locator="not allowed",
        )


def test_analysis_and_evidence_models_are_frozen():
    analysis = _analysis()

    with pytest.raises(ValidationError):
        analysis.research_question = "Mutated question"
    with pytest.raises(ValidationError):
        analysis.evidence[0].excerpt = "Mutated evidence"


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_hash", "a" * 63),
        ("evidence_hash", "a" * 65),
        ("evidence_hash", "A" * 64),
        ("evidence_hash", " " + "a" * 64),
        ("evidence_hash", "g" * 64),
        ("model_config_hash", "b" * 63),
        ("model_config_hash", "B" * 64),
        ("model_config_hash", "b" * 64 + " "),
    ],
)
def test_analysis_identity_requires_normalized_sha256_hex(field, value):
    with pytest.raises(ValidationError):
        _analysis(**{field: value})


def test_evidence_excerpt_is_bounded_and_page_is_positive():
    with pytest.raises(ValidationError):
        AnalysisEvidence(
            field="methods",
            excerpt="x" * 2001,
            evidence_scope="abstract",
        )
    with pytest.raises(ValidationError):
        AnalysisEvidence(
            field="methods",
            excerpt="Evidence.",
            evidence_scope="fulltext_excerpt",
            page=0,
        )


def test_migration_10_is_appended_without_rewriting_prior_migrations(tmp_path):
    assert [migration.version for migration in MIGRATION_REGISTRY] == list(range(1, 11))
    assert MIGRATION_REGISTRY[-1].name == "paper_analyses"

    database = Database(tmp_path / "analysis-migration.db")
    columns = {
        row[1]
        for row in database.connection.execute("PRAGMA table_info(paper_analyses)")
    }
    assert {
        "canonical_id",
        "analysis_version",
        "evidence_hash",
        "model_config_hash",
        "analysis_json",
        "created_at",
        "updated_at",
    } <= columns
    database.connection.close()


def test_repository_upsert_is_idempotent_for_composite_identity(tmp_path):
    database = _database_with_paper(tmp_path / "analysis.db")
    repository = AnalysisRepository(database)
    analysis = _analysis()
    created_at = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)

    first = repository.upsert(analysis, now=created_at)
    second = repository.upsert(analysis, now=created_at)

    assert first == analysis
    assert second == analysis
    count = database.connection.execute(
        "SELECT COUNT(*) FROM paper_analyses"
    ).fetchone()[0]
    assert count == 1
    assert repository.get(
        canonical_id=analysis.canonical_id,
        analysis_version=analysis.analysis_version,
        evidence_hash=analysis.evidence_hash,
        model_config_hash=analysis.model_config_hash,
    ) == analysis
    database.connection.close()


def test_repository_composite_collision_is_first_writer_wins(tmp_path):
    path = tmp_path / "first-writer.db"
    database = _database_with_paper(path)
    repository = AnalysisRepository(database)
    first = _analysis(research_question="First grounded result")
    divergent_retry = _analysis(research_question="Divergent retry result")

    assert repository.upsert(first) == first
    assert repository.upsert(divergent_retry) == first
    database.connection.close()

    restarted = Database(path)
    stored = AnalysisRepository(restarted).get(
        canonical_id=first.canonical_id,
        analysis_version=first.analysis_version,
        evidence_hash=first.evidence_hash,
        model_config_hash=first.model_config_hash,
    )
    assert stored == first
    restarted.connection.close()


def test_repository_retrieves_typed_analysis_after_restart(tmp_path):
    path = tmp_path / "restart.db"
    database = _database_with_paper(path)
    analysis = _analysis(status="extractive", motivation=None)
    AnalysisRepository(database).upsert(analysis)
    database.connection.close()

    restarted = Database(path)
    restored = AnalysisRepository(restarted).get(
        canonical_id=analysis.canonical_id,
        analysis_version=analysis.analysis_version,
        evidence_hash=analysis.evidence_hash,
        model_config_hash=analysis.model_config_hash,
    )

    assert restored == analysis
    assert isinstance(restored, PaperAnalysis)
    assert restored is not None and restored.motivation is None
    restarted.connection.close()
