from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
POWERSHELL = shutil.which("powershell.exe")


def _powershell_literal(value: str | Path) -> str:
    return str(value).replace("'", "''")


def _run_controlled_script(
    tmp_path: Path,
    script_name: str,
    *,
    mode: str = "none",
    port: int = 8000,
    managed_pid: int | None = None,
    no_browser: bool = True,
    health_ready: bool = True,
    migration_ready: bool = True,
    runtime_ready: bool = True,
    worker_ready: bool = True,
    scheduler_ready: bool = True,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    assert POWERSHELL is not None
    sandbox = tmp_path / "scripts"
    sandbox.mkdir()
    shutil.copy2(SCRIPTS / script_name, sandbox / script_name)
    common = (SCRIPTS / "stack-common.ps1").read_text(encoding="utf-8-sig")
    event_log = tmp_path / "events.log"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shim = textwrap.dedent(
        rf"""

        $script:StackProjectRoot = '{_powershell_literal(ROOT)}'
        $script:StackSourceDirectory = '{_powershell_literal(ROOT / 'src')}'
        $script:StackPython = '{_powershell_literal(sys.executable)}'
        $script:StackLitWatchExe = '{_powershell_literal(ROOT / '.venv/Scripts/litwatch.exe')}'
        $script:StackDataDirectory = '{_powershell_literal(data_dir)}'
        $script:StackPidPath = Join-Path $script:StackDataDirectory 'litwatch-stack.pid'
        $script:StackLogPath = Join-Path $script:StackDataDirectory 'litwatch-stack.log'
        $script:StackErrorLogPath = Join-Path $script:StackDataDirectory 'litwatch-stack-error.log'
        $script:LifecycleEventLog = '{_powershell_literal(event_log)}'
        $script:LifecycleStartedPid = $null

        function Add-LifecycleTestEvent {{
            param([string]$Event)
            Add-Content -LiteralPath $script:LifecycleEventLog -Value $Event -Encoding utf8
        }}

        function Resolve-LitWatchPython {{
            param([int]$Port = 8000)
            Add-LifecycleTestEvent "resolve-python:$Port"
            return $script:StackPython
        }}

        function Get-DockerCommand {{
            Add-LifecycleTestEvent 'FORBIDDEN:docker'
            throw 'CONTROLLED FORBIDDEN Docker probe'
        }}

        function Resolve-DifyDockerDirectory {{
            Add-LifecycleTestEvent 'FORBIDDEN:dify'
            throw 'CONTROLLED FORBIDDEN Dify resolution'
        }}

        function Test-ComposeServiceRunning {{
            Add-LifecycleTestEvent 'FORBIDDEN:ssrf-proxy'
            throw 'CONTROLLED FORBIDDEN SSRF proxy probe'
        }}

        function Get-PortProcessInfo {{
            param([int]$Port = 8000)
            Add-LifecycleTestEvent "inspect-port:$Port"
            if ($env:LITWATCH_TEST_MODE -eq 'none') {{ return @() }}
            $CommandLine = if ($env:LITWATCH_TEST_MODE -eq 'spoof-source') {{
                '"' + $script:StackPython + '" -m uvicorn litwatch.web:app --app-dir "' +
                    $script:StackSourceDirectory + '-foreign" --host 127.0.0.1 --port ' + $Port
            }} elseif ($env:LITWATCH_TEST_MODE -eq 'spoof-port') {{
                '"' + $script:StackPython + '" -m uvicorn litwatch.web:app --app-dir "' +
                    $script:StackSourceDirectory + '" --host 127.0.0.1 --port ' + $Port + '0'
            }} elseif ($env:LITWATCH_TEST_MODE -in @('owned', 'toctou', 'pid-reused')) {{
                '"' + $script:StackPython + '" -m uvicorn litwatch.web:app --app-dir "' +
                    $script:StackSourceDirectory + '" --host 127.0.0.1 --port ' + $Port
            }} else {{
                '"C:\foreign\python.exe" -m uvicorn other.web:app --port ' + $Port
            }}
            return [PSCustomObject]@{{
                PID = [int]$env:LITWATCH_TEST_PID
                CreationDate = if ($env:LITWATCH_TEST_MODE -eq 'pid-reused') {{
                    '2026-08-14T00:00:01.0000000+00:00'
                }} else {{
                    '2026-08-14T00:00:00.0000000+00:00'
                }}
                ExecutablePath = if ($env:LITWATCH_TEST_MODE -in @(
                    'owned', 'toctou', 'pid-reused', 'spoof-source', 'spoof-port'
                )) {{
                    $script:StackPython
                }} else {{
                    'C:\foreign\python.exe'
                }}
                CommandLine = $CommandLine
            }}
        }}

        function Get-ProcessInfoById {{
            param([int]$ProcessId)
            if ($env:LITWATCH_TEST_MODE -eq 'toctou') {{
                Add-LifecycleTestEvent "recheck:$ProcessId"
                return [PSCustomObject]@{{
                    PID = $ProcessId
                    CreationDate = '2026-08-14T00:00:01.0000000+00:00'
                    ExecutablePath = 'C:\foreign\python.exe'
                    CommandLine = '"C:\foreign\python.exe" -m uvicorn other.web:app --port ' +
                        $env:LITWATCH_TEST_PORT
                }}
            }}
            if ($script:LifecycleStartedPid -eq $ProcessId) {{
                return [PSCustomObject]@{{
                    PID = $ProcessId
                    CreationDate = '2026-08-14T00:00:00.0000000+00:00'
                    ExecutablePath = $script:StackPython
                    CommandLine = '"' + $script:StackPython +
                        '" -m uvicorn litwatch.web:app --app-dir "' +
                        $script:StackSourceDirectory + '" --host 127.0.0.1 --port ' +
                        $env:LITWATCH_TEST_PORT
                }}
            }}
            if ($env:LITWATCH_TEST_MODE -eq 'none') {{ return $null }}
            return Get-PortProcessInfo -Port ([int]$env:LITWATCH_TEST_PORT)
        }}

        function Test-HttpReady {{
            param([string]$Url, [int]$TimeoutSeconds = 5)
            Add-LifecycleTestEvent "http:$Url"
            return ($env:LITWATCH_TEST_HEALTH_READY -eq 'true')
        }}

        function Wait-StackCondition {{
            param([scriptblock]$Condition, [int]$TimeoutSeconds, [int]$IntervalSeconds = 2)
            return [bool](& $Condition)
        }}

        function Get-PythonRuntimeStatus {{
            param([int]$Port = 8000, [int]$TimeoutSeconds = 10)
            Add-LifecycleTestEvent "runtime:$Port"
            $MigrationReady = $env:LITWATCH_TEST_MIGRATION_READY -eq 'true'
            $RuntimeReady = $env:LITWATCH_TEST_RUNTIME_READY -eq 'true'
            $WorkerReady = $env:LITWATCH_TEST_WORKER_READY -eq 'true'
            $SchedulerReady = $env:LITWATCH_TEST_SCHEDULER_READY -eq 'true'
            return [PSCustomObject]@{{
                Ready = $MigrationReady -and $RuntimeReady -and $WorkerReady -and $SchedulerReady
                MigrationReady = $MigrationReady
                RuntimeReady = $RuntimeReady
                WorkerReady = $WorkerReady
                SchedulerReady = $SchedulerReady
                WorkerActive = 0
                SchedulerLastError = ''
                Detail = 'mode=python_default'
            }}
        }}

        function Get-OpenAlexRegistryStatus {{
            param([int]$Port = 8000, [int]$TimeoutSeconds = 10)
            Add-LifecycleTestEvent "providers:$Port"
            return [PSCustomObject]@{{ Ready = $true; Detail = 'OpenAlex runnable=true' }}
        }}

        function Start-Process {{
            [CmdletBinding()]
            param(
                [Parameter(Position = 0)][string]$FilePath,
                [object]$ArgumentList,
                [string]$WorkingDirectory,
                [string]$WindowStyle,
                [string]$RedirectStandardOutput,
                [string]$RedirectStandardError,
                [switch]$PassThru
            )
            if ($FilePath -match '^https?://') {{
                Add-LifecycleTestEvent "browser:$FilePath"
                return
            }}
            Add-LifecycleTestEvent "start:$FilePath|$ArgumentList|$WorkingDirectory"
            $script:LifecycleStartedPid = [int]$env:LITWATCH_TEST_PID
            return [PSCustomObject]@{{ Id = [int]$env:LITWATCH_TEST_PID }}
        }}

        function Stop-Process {{
            param([int]$Id, [object]$ErrorAction)
            Add-LifecycleTestEvent "stop:$Id"
        }}
        """
    )
    (sandbox / "stack-common.ps1").write_text(common + shim, encoding="utf-8-sig")

    pid_path = data_dir / ("litwatch-stack.pid" if port == 8000 else f"litwatch-stack-{port}.pid")
    if managed_pid is not None:
        fingerprint_fields = (
            str(Path(sys.executable).resolve()).rstrip("\\/").lower(),
            str((ROOT / "src").resolve()).rstrip("\\/").lower(),
            "127.0.0.1",
            str(port),
        )
        fingerprint = hashlib.sha256("\n".join(fingerprint_fields).encode()).hexdigest()
        pid_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "pid": managed_pid,
                    "creation_time_utc": "2026-08-14T00:00:00.0000000+00:00",
                    "fingerprint": fingerprint,
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

    env = os.environ.copy()
    env.update(
        {
            "LITWATCH_PYTHON": sys.executable,
            "LITWATCH_TEST_MODE": mode,
            "LITWATCH_TEST_PID": str(managed_pid or 4242),
            "LITWATCH_TEST_PORT": str(port),
            "LITWATCH_TEST_HEALTH_READY": str(health_ready).lower(),
            "LITWATCH_TEST_MIGRATION_READY": str(migration_ready).lower(),
            "LITWATCH_TEST_RUNTIME_READY": str(runtime_ready).lower(),
            "LITWATCH_TEST_WORKER_READY": str(worker_ready).lower(),
            "LITWATCH_TEST_SCHEDULER_READY": str(scheduler_ready).lower(),
        }
    )
    command = [
        POWERSHELL,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(sandbox / script_name),
    ]
    if port != 8000:
        command += ["-Port", str(port)]
    if script_name == "start-stack.ps1" and no_browser:
        command += ["-NoBrowser"]
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    events = event_log.read_text(encoding="utf-8-sig").splitlines() if event_log.exists() else []
    return result, events


def _script_text(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8-sig")


def test_default_scripts_do_not_reference_legacy_dependencies():
    forbidden = ("docker", "dify", "ssrf_proxy", "resolve-dify")
    for name in ("start-stack.ps1", "status-stack.ps1", "stop-stack.ps1"):
        lowered = _script_text(name).lower()
        assert not any(marker in lowered for marker in forbidden), name


def test_default_start_is_python_only_under_controlled_shims(tmp_path: Path):
    result, events = _run_controlled_script(tmp_path, "start-stack.ps1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not [event for event in events if event.startswith("FORBIDDEN:")]
    assert "inspect-port:8000" in events
    assert any(event.startswith(f"start:{sys.executable}") for event in events)
    assert "runtime:8000" in events
    assert "providers:8000" in events


def test_default_start_opens_litwatch_not_legacy_ui(tmp_path: Path):
    result, events = _run_controlled_script(
        tmp_path, "start-stack.ps1", no_browser=False
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "browser:http://127.0.0.1:8000/" in events
    assert "browser:http://localhost" not in events


def test_default_start_is_idempotent_only_for_its_saved_pid(tmp_path: Path):
    result, events = _run_controlled_script(
        tmp_path, "start-stack.ps1", mode="owned", managed_pid=4242
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "LitWatch: already running (PID 4242)" in result.stdout
    assert not [event for event in events if event.startswith("start:")]


def test_default_start_rejects_unknown_port_owner_without_stopping_it(tmp_path: Path):
    result, events = _run_controlled_script(
        tmp_path, "start-stack.ps1", mode="foreign", managed_pid=4242
    )

    assert result.returncode != 0
    assert "Refusing to stop it" in result.stderr
    assert "stop:4242" not in events


def test_default_start_cleans_up_only_the_process_it_started_on_health_failure(
    tmp_path: Path,
):
    result, events = _run_controlled_script(
        tmp_path, "start-stack.ps1", health_ready=False
    )

    assert result.returncode != 0
    assert "stop:4242" in events
    assert "Health check failed" in result.stderr


def test_default_stop_stops_only_the_saved_current_repository_pid(tmp_path: Path):
    result, events = _run_controlled_script(
        tmp_path, "stop-stack.ps1", mode="owned", managed_pid=4242
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "stop:4242" in events
    assert "resolve-python:8000" in events
    assert not [event for event in events if event.startswith("FORBIDDEN:")]
    assert "LitWatch: stopped PID 4242" in result.stdout


def test_default_stop_rejects_foreign_owner_even_with_stale_pid_file(tmp_path: Path):
    result, events = _run_controlled_script(
        tmp_path, "stop-stack.ps1", mode="foreign", managed_pid=4242
    )

    assert result.returncode != 0
    assert "Refusing to stop it" in result.stderr
    assert "stop:4242" not in events


def test_default_stop_rejects_source_path_substring_spoof(tmp_path: Path):
    result, events = _run_controlled_script(
        tmp_path, "stop-stack.ps1", mode="spoof-source", managed_pid=4242
    )

    assert result.returncode != 0
    assert "Refusing to stop it" in result.stderr
    assert "stop:4242" not in events


def test_default_stop_rejects_port_prefix_spoof(tmp_path: Path):
    result, events = _run_controlled_script(
        tmp_path, "stop-stack.ps1", mode="spoof-port", managed_pid=4242
    )

    assert result.returncode != 0
    assert "Refusing to stop it" in result.stderr
    assert "stop:4242" not in events


def test_default_stop_rechecks_identity_immediately_before_stop(tmp_path: Path):
    result, events = _run_controlled_script(
        tmp_path, "stop-stack.ps1", mode="toctou", managed_pid=4242
    )

    assert result.returncode != 0
    assert "recheck:4242" in events
    assert "stop:4242" not in events


def test_default_stop_rejects_reused_pid_with_same_command(tmp_path: Path):
    result, events = _run_controlled_script(
        tmp_path, "stop-stack.ps1", mode="pid-reused", managed_pid=4242
    )

    assert result.returncode != 0
    assert "Refusing to stop it" in result.stderr
    assert "stop:4242" not in events


def test_default_stop_requires_a_saved_pid_even_for_a_matching_command(tmp_path: Path):
    result, events = _run_controlled_script(
        tmp_path, "stop-stack.ps1", mode="owned"
    )

    assert result.returncode != 0
    assert "managed PID" in result.stderr
    assert "stop:4242" not in events


def test_default_stop_is_idempotent_without_legacy_probes(tmp_path: Path):
    result, events = _run_controlled_script(tmp_path, "stop-stack.ps1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "LitWatch: already stopped" in result.stdout
    assert not [event for event in events if event.startswith("FORBIDDEN:")]


def test_default_status_reports_python_runtime_components_without_legacy_probes(
    tmp_path: Path,
):
    result, events = _run_controlled_script(
        tmp_path, "status-stack.ps1", mode="owned", managed_pid=4242
    )

    assert result.returncode == 0, result.stdout + result.stderr
    for label in (
        "Migration Verification",
        "Python Runtime",
        "LitWatch",
        "Provider Registry",
        "Job Worker/Scheduler",
        "System",
        "READY",
    ):
        assert label in result.stdout
    assert not [event for event in events if event.startswith("FORBIDDEN:")]
    assert "resolve-python:8000" in events


def test_default_status_rejects_failed_migration_verification(tmp_path: Path):
    result, _ = _run_controlled_script(
        tmp_path,
        "status-stack.ps1",
        mode="owned",
        managed_pid=4242,
        migration_ready=False,
    )

    assert result.returncode != 0
    assert "Migration Verification  FAIL" in result.stdout
    assert "Python Runtime          PASS" in result.stdout
    assert "System                  NOT READY" in result.stdout


def test_default_status_rejects_stopped_job_worker(tmp_path: Path):
    result, _ = _run_controlled_script(
        tmp_path,
        "status-stack.ps1",
        mode="owned",
        managed_pid=4242,
        worker_ready=False,
    )

    assert result.returncode != 0
    assert "Migration Verification  PASS" in result.stdout
    assert "Python Runtime          PASS" in result.stdout
    assert "Job Worker/Scheduler    FAIL" in result.stdout
    assert "System                  NOT READY" in result.stdout


def test_default_status_rejects_stopped_scheduler(tmp_path: Path):
    result, _ = _run_controlled_script(
        tmp_path,
        "status-stack.ps1",
        mode="owned",
        managed_pid=4242,
        scheduler_ready=False,
    )

    assert result.returncode != 0
    assert "Migration Verification  PASS" in result.stdout
    assert "Python Runtime          PASS" in result.stdout
    assert "Job Worker/Scheduler    FAIL" in result.stdout
    assert "System                  NOT READY" in result.stdout


def test_provider_registry_status_selects_only_openalex_from_rest_array(tmp_path: Path):
    assert POWERSHELL is not None
    probe = tmp_path / "provider-probe.ps1"
    probe.write_text(
        textwrap.dedent(
            rf"""
            . '{_powershell_literal(SCRIPTS / 'stack-common.ps1')}'
            $script:ProviderResponse = @(
                [PSCustomObject]@{{ provider_type = 'openalex'; runnable = $true }},
                [PSCustomObject]@{{ provider_type = 'arxiv'; runnable = $false }}
            )
            function Invoke-RestMethod {{
                Write-Output -NoEnumerate $script:ProviderResponse
            }}
            Get-OpenAlexRegistryStatus -Port 18080 | ConvertTo-Json -Compress
            """
        ),
        encoding="utf-8-sig",
    )

    result = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(probe),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "Ready": True,
        "Detail": "OpenAlex runnable=True",
    }


def _run_python_resolution_probe(
    tmp_path: Path, *, port: int, allow_external: bool
) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    probe = tmp_path / f"python-resolution-{port}.ps1"
    probe.write_text(
        textwrap.dedent(
            rf"""
            . '{_powershell_literal(SCRIPTS / 'stack-common.ps1')}'
            $env:LITWATCH_PYTHON = '{_powershell_literal(sys.executable)}'
            $env:LITWATCH_ALLOW_EXTERNAL_PYTHON = '{int(allow_external)}'
            try {{
                Resolve-LitWatchPython -Port {port}
                exit 0
            }} catch {{
                Write-Output $_.Exception.Message
                exit 1
            }}
            """
        ),
        encoding="utf-8-sig",
    )
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(probe),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_default_port_rejects_external_python_even_with_smoke_switch(tmp_path: Path):
    result = _run_python_resolution_probe(tmp_path, port=8000, allow_external=True)

    assert result.returncode != 0
    assert "current worktree" in result.stdout


def test_nondefault_port_rejects_external_python_without_smoke_switch(tmp_path: Path):
    result = _run_python_resolution_probe(tmp_path, port=18080, allow_external=False)

    assert result.returncode != 0
    assert "smoke" in result.stdout.lower()


def test_nondefault_port_allows_explicit_external_python_for_smoke(tmp_path: Path):
    result = _run_python_resolution_probe(tmp_path, port=18080, allow_external=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert str(Path(sys.executable).resolve()) in result.stdout


def test_legacy_full_stack_scripts_remain_explicit_and_volume_preserving():
    start = _script_text("start-legacy-dify-stack.ps1").lower()
    stop = _script_text("stop-legacy-dify-stack.ps1").lower()

    assert "get-dockercommand" in start
    assert "resolve-difydockerdirectory" in start
    assert "ssrf_proxy" in start
    assert "docker compose up -d" in start
    assert "docker compose stop" in stop
    assert "down -v" not in stop
    assert "resolve-litwatchpython" in stop
    assert "stop-managedlitwatchprocess" in stop
    assert "stop-process" not in stop


def test_root_launchers_make_python_default_and_legacy_dify_explicit():
    default_start = (ROOT / "启动科研文献系统.cmd").read_text(encoding="utf-8-sig")
    default_stop = (ROOT / "停止科研文献系统.cmd").read_text(encoding="utf-8-sig")
    legacy_start = (ROOT / "启动旧版 Dify 科研文献系统.cmd").read_text(encoding="utf-8-sig")
    legacy_stop = (ROOT / "停止旧版 Dify 科研文献系统.cmd").read_text(encoding="utf-8-sig")

    assert r"scripts\start-stack.ps1" in default_start
    assert r"scripts\stop-stack.ps1" in default_stop
    assert r"scripts\start-legacy-dify-stack.ps1" in legacy_start
    assert r"scripts\stop-legacy-dify-stack.ps1" in legacy_stop
