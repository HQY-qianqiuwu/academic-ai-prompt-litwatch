from __future__ import annotations

from datetime import UTC, datetime

from litwatch.analysis_models import PaperAnalysis
from litwatch.db import Database


class AnalysisRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(
        self,
        analysis: PaperAnalysis,
        *,
        now: datetime | None = None,
    ) -> PaperAnalysis:
        validated = PaperAnalysis.model_validate(analysis)
        timestamp = self._utc(now).isoformat()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO paper_analyses(
                       canonical_id,analysis_version,evidence_hash,model_config_hash,
                       status,evidence_scope,analysis_json,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(
                       canonical_id,analysis_version,evidence_hash,model_config_hash
                   ) DO NOTHING""",
                (
                    validated.canonical_id,
                    validated.analysis_version,
                    validated.evidence_hash,
                    validated.model_config_hash,
                    validated.status.value,
                    validated.evidence_scope.value,
                    validated.model_dump_json(),
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                """SELECT analysis_json FROM paper_analyses
                   WHERE canonical_id=? AND analysis_version=?
                     AND evidence_hash=? AND model_config_hash=?""",
                (
                    validated.canonical_id,
                    validated.analysis_version,
                    validated.evidence_hash,
                    validated.model_config_hash,
                ),
            ).fetchone()
        if row is None:  # pragma: no cover - insert/select share one transaction
            raise RuntimeError("paper analysis upsert did not persist a row")
        return PaperAnalysis.model_validate_json(str(row[0]))

    def get(
        self,
        *,
        canonical_id: str,
        analysis_version: str,
        evidence_hash: str,
        model_config_hash: str,
    ) -> PaperAnalysis | None:
        with self.database.transaction_lock:
            row = self.database.connection.execute(
                """SELECT analysis_json FROM paper_analyses
                   WHERE canonical_id=? AND analysis_version=?
                     AND evidence_hash=? AND model_config_hash=?""",
                (
                    canonical_id,
                    analysis_version,
                    evidence_hash,
                    model_config_hash,
                ),
            ).fetchone()
        if row is None:
            return None
        return PaperAnalysis.model_validate_json(str(row[0]))

    @staticmethod
    def _utc(value: datetime | None) -> datetime:
        current = value or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("analysis timestamp must be timezone-aware")
        return current.astimezone(UTC)
