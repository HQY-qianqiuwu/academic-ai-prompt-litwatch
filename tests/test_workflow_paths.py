from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def load_workflow(name: str) -> dict:
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_only_manual_pages_workflow_can_scan_providers():
    assert not (WORKFLOWS / "weekly.yml").exists()
    pages = load_workflow("pages.yml")
    assert list(pages["on"]) == ["workflow_dispatch"]
    steps = pages["jobs"]["build-and-deploy"]["steps"]
    commands = [step.get("run", "") for step in steps]
    assert sum("litwatch scan" in command for command in commands) == 1
    assert all("pytest" not in command and "ruff" not in command for command in commands)


def test_ci_runs_checks_without_scanning_providers():
    ci = load_workflow("ci.yml")
    assert "pull_request" in ci["on"]
    commands = [
        step.get("run", "")
        for job in ci["jobs"].values()
        for step in job["steps"]
    ]
    assert any("pytest" in command for command in commands)
    assert any("ruff check ." in command for command in commands)
    assert all("litwatch scan" not in command for command in commands)
