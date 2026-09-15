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


def test_ci_separates_linux_core_windows_lifecycle_and_ruff_jobs():
    ci = load_workflow("ci.yml")
    assert "pull_request" in ci["on"]
    assert set(ci["jobs"]) == {"linux-core", "windows-lifecycle", "ruff"}

    linux = ci["jobs"]["linux-core"]
    windows = ci["jobs"]["windows-lifecycle"]
    ruff = ci["jobs"]["ruff"]
    assert linux["runs-on"] == "ubuntu-latest"
    assert windows["runs-on"] == "windows-latest"
    assert ruff["runs-on"] == "ubuntu-latest"

    linux_commands = [step.get("run", "") for step in linux["steps"]]
    windows_commands = [step.get("run", "") for step in windows["steps"]]
    ruff_commands = [step.get("run", "") for step in ruff["steps"]]
    assert "uv run pytest -m \"not windows\"" in linux_commands
    assert "uv run pytest -m windows" in windows_commands
    assert "uv run ruff check ." in ruff_commands

    commands = linux_commands + windows_commands + ruff_commands
    assert all("litwatch scan" not in command for command in commands)
