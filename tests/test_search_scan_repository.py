from datetime import date

from litwatch.db import Database
from litwatch.models import Paper
from litwatch.search_scan_repository import SearchScanRepository
from litwatch.services.scan import ScanResult, ScanStatus


def sample_result() -> ScanResult:
    return ScanResult(
        query="underwater acoustic localization",
        status=ScanStatus.SUCCESS,
        papers=[
            Paper(
                canonical_id="doi:10.1000/a",
                title="Provider-owned title",
                abstract="A grounded abstract.",
                publication_date=date(2026, 8, 1),
                sources=["openalex"],
                score=0.9,
            )
        ],
    )


def test_saved_scan_round_trips_standardized_paper_after_reopen(tmp_path):
    path = tmp_path / "search.db"
    database = Database(path)
    saved = SearchScanRepository(database).save(sample_result())
    database.connection.close()

    reopened = Database(path)
    repository = SearchScanRepository(reopened)
    restored_scan = repository.get_scan(saved.scan_id)
    paper_id = saved.paper_ids["doi:10.1000/a"]
    restored_paper = repository.get_paper(saved.scan_id, paper_id)

    assert restored_scan is not None
    assert restored_scan.status is ScanStatus.SUCCESS
    assert restored_scan.papers[0].title == "Provider-owned title"
    assert restored_paper is not None
    assert restored_paper.paper.canonical_id == "doi:10.1000/a"
    assert restored_paper.paper.abstract == "A grounded abstract."
    assert restored_paper.query == "underwater acoustic localization"
    assert repository.get_paper("unknown-scan", paper_id) is None
    reopened.connection.close()


def test_paper_id_is_stable_across_scans_and_each_scan_is_distinct(tmp_path):
    database = Database(tmp_path / "stable.db")
    repository = SearchScanRepository(database)

    first = repository.save(sample_result())
    second = repository.save(sample_result())

    assert first.scan_id != second.scan_id
    assert first.paper_ids == second.paper_ids
    assert database.connection.execute("SELECT COUNT(*) FROM paper_identities").fetchone()[0] == 1
    assert database.connection.execute("SELECT COUNT(*) FROM search_scan_papers").fetchone()[0] == 2
    database.connection.close()


def test_empty_scan_is_persisted_without_fake_papers(tmp_path):
    database = Database(tmp_path / "empty.db")
    repository = SearchScanRepository(database)

    saved = repository.save(ScanResult(query="acoustics", status=ScanStatus.SUCCESS_EMPTY))

    assert saved.paper_ids == {}
    assert repository.get_scan(saved.scan_id).status is ScanStatus.SUCCESS_EMPTY
    assert database.connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
    database.connection.close()
