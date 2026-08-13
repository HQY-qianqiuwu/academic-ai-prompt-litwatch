Set-StrictMode -Version Latest

$script:StackProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:StackSourceDirectory = Join-Path $script:StackProjectRoot "src"
$script:StackPython = Join-Path $script:StackProjectRoot ".venv\Scripts\python.exe"
$script:StackLitWatchExe = Join-Path $script:StackProjectRoot ".venv\Scripts\litwatch.exe"
$script:StackDataDirectory = Join-Path $script:StackProjectRoot "data"
$script:StackPidPath = Join-Path $script:StackDataDirectory "litwatch-stack.pid"
$script:StackLogPath = Join-Path $script:StackDataDirectory "litwatch-stack.log"
$script:StackErrorLogPath = Join-Path $script:StackDataDirectory "litwatch-stack-error.log"

function Set-StackPortPaths {
    param([int]$Port = 8000)

    if ($Port -eq 8000) {
        $Suffix = ""
    }
    else {
        $Suffix = "-$Port"
    }
    $script:StackPidPath = Join-Path $script:StackDataDirectory "litwatch-stack$Suffix.pid"
    $script:StackLogPath = Join-Path $script:StackDataDirectory "litwatch-stack$Suffix.log"
    $script:StackErrorLogPath = Join-Path $script:StackDataDirectory "litwatch-stack$Suffix-error.log"
}

function Resolve-LitWatchPython {
    $Candidates = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($env:LITWATCH_PYTHON)) {
        $Candidates.Add($env:LITWATCH_PYTHON)
    }
    $Candidates.Add((Join-Path $script:StackProjectRoot ".venv\Scripts\python.exe"))

    foreach ($Candidate in $Candidates | Select-Object -Unique) {
        if ($Candidate -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    throw "[Python Runtime] No trusted Python executable was found for '$script:StackProjectRoot'. Set LITWATCH_PYTHON to an explicit Python executable or install the current repository virtual environment."
}

function Get-ManagedStackPid {
    if (-not (Test-Path -LiteralPath $script:StackPidPath -PathType Leaf)) {
        return $null
    }
    $RawPid = (Get-Content -Raw -LiteralPath $script:StackPidPath).Trim()
    $ManagedPid = 0
    if (-not [int]::TryParse($RawPid, [ref]$ManagedPid) -or $ManagedPid -le 0) {
        throw "[LitWatch] Invalid managed PID file: $script:StackPidPath"
    }
    return $ManagedPid
}

function Get-ProcessInfoById {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $ProcessInfo) {
        return $null
    }
    return [PSCustomObject]@{
        PID = [int]$ProcessInfo.ProcessId
        ExecutablePath = [string]$ProcessInfo.ExecutablePath
        CommandLine = [string]$ProcessInfo.CommandLine
    }
}

function Resolve-DifyDockerDirectory {
    $Candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:DIFY_DOCKER_DIR)) {
        $Candidates += $env:DIFY_DOCKER_DIR
    }
    $Candidates += Join-Path (Split-Path $script:StackProjectRoot -Parent) "dify\docker"

    foreach ($Candidate in $Candidates) {
        if (-not (Test-Path -LiteralPath $Candidate -PathType Container)) {
            continue
        }
        $Resolved = (Resolve-Path -LiteralPath $Candidate).Path
        $ComposeFiles = @("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml")
        foreach ($ComposeFile in $ComposeFiles) {
            if (Test-Path -LiteralPath (Join-Path $Resolved $ComposeFile) -PathType Leaf) {
                return $Resolved
            }
        }
    }

    throw "[Dify] Compose directory was not found. Checked DIFY_DOCKER_DIR and the sibling dify\docker directory."
}

function Get-DockerCommand {
    $Command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if (-not $Command) {
        throw "[Docker] Docker CLI was not found in PATH. Install Docker Desktop first."
    }
    return $Command
}

function Test-DockerDaemon {
    param([Parameter(Mandatory = $true)]$DockerCommand)

    $Version = & $DockerCommand.Source info --format "{{.ServerVersion}}" 2>$null
    return ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace(($Version -join "")))
}

function Find-DockerDesktopExecutable {
    param([Parameter(Mandatory = $true)]$DockerCommand)

    $Candidates = New-Object System.Collections.Generic.List[string]
    $Running = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($Running) {
        try {
            if ($Running.Path) {
                $Candidates.Add($Running.Path)
            }
        }
        catch {
            # Access to the process path can be restricted; continue with known locations.
        }
    }

    try {
        $RegistryKey = Get-Item -LiteralPath "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Docker Desktop.exe" -ErrorAction Stop
        $RegistryPath = $RegistryKey.GetValue("")
        if ($RegistryPath) {
            $Candidates.Add([string]$RegistryPath)
        }
    }
    catch {
        # Docker Desktop does not always register an App Paths entry.
    }

    if ($env:ProgramFiles) {
        $Candidates.Add((Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"))
    }

    $DockerBin = Split-Path $DockerCommand.Source -Parent
    $DockerResources = Split-Path $DockerBin -Parent
    $DockerInstallRoot = Split-Path $DockerResources -Parent
    if ($DockerInstallRoot) {
        $Candidates.Add((Join-Path $DockerInstallRoot "Docker Desktop.exe"))
        $Candidates.Add((Join-Path $DockerInstallRoot "frontend\Docker Desktop.exe"))
        $DockerInstallParent = Split-Path $DockerInstallRoot -Parent
        if ($DockerInstallParent) {
            $Candidates.Add((Join-Path $DockerInstallParent "App\frontend\Docker Desktop.exe"))
        }
    }

    foreach ($Candidate in $Candidates | Select-Object -Unique) {
        if ($Candidate -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    return $null
}

function Wait-StackCondition {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Condition,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [int]$IntervalSeconds = 2
    )

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) {
            return $true
        }
        Start-Sleep -Seconds $IntervalSeconds
    } while ((Get-Date) -lt $Deadline)
    return $false
}

function Test-HttpReady {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSeconds = 5
    )

    try {
        $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSeconds
        return ($Response.StatusCode -ge 200 -and $Response.StatusCode -lt 400)
    }
    catch {
        return $false
    }
}

function Get-ComposeServiceContainerId {
    param(
        [Parameter(Mandatory = $true)][string]$DifyDockerDirectory,
        [Parameter(Mandatory = $true)][string]$Service
    )

    Push-Location $DifyDockerDirectory
    try {
        $ComposeJson = & docker compose ps --format json $Service 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        if ([string]::IsNullOrWhiteSpace(($ComposeJson -join ""))) {
            return $null
        }
        $Container = $ComposeJson | ConvertFrom-Json | Select-Object -First 1
        return [string]$Container.ID
    }
    finally {
        Pop-Location
    }
}

function Test-ComposeServiceRunning {
    param(
        [Parameter(Mandatory = $true)][string]$DifyDockerDirectory,
        [Parameter(Mandatory = $true)][string]$Service
    )

    $ContainerId = Get-ComposeServiceContainerId -DifyDockerDirectory $DifyDockerDirectory -Service $Service
    if ([string]::IsNullOrWhiteSpace($ContainerId)) {
        return $false
    }
    $Running = & docker inspect --format "{{.State.Running}}" $ContainerId 2>$null
    return ($LASTEXITCODE -eq 0 -and ($Running -join "").Trim() -eq "true")
}

function Get-PortProcessInfo {
    param([int]$Port = 8000)

    $Listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    $Results = @()
    foreach ($Listener in $Listeners) {
        $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($Listener.OwningProcess)" -ErrorAction SilentlyContinue
        if ($ProcessInfo) {
            $Results += [PSCustomObject]@{
                PID = [int]$ProcessInfo.ProcessId
                ExecutablePath = [string]$ProcessInfo.ExecutablePath
                CommandLine = [string]$ProcessInfo.CommandLine
            }
        }
    }
    return $Results
}

function Test-IsCurrentLitWatchProcess {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [int]$Port = 8000
    )

    $CommandLine = [string]$ProcessInfo.CommandLine
    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }

    $Comparison = [System.StringComparison]::OrdinalIgnoreCase
    $UsesManagedServer = (
        $CommandLine.IndexOf("litwatch.web:app", $Comparison) -ge 0 -and
        $CommandLine.IndexOf($script:StackSourceDirectory, $Comparison) -ge 0
    )
    $UsesProjectCli = $CommandLine.IndexOf($script:StackLitWatchExe, $Comparison) -ge 0
    $UsesRequestedPort = (
        $CommandLine.IndexOf("--port $Port", $Comparison) -ge 0 -or
        $CommandLine.IndexOf("--port=$Port", $Comparison) -ge 0
    )
    return (($UsesManagedServer -or $UsesProjectCli) -and $UsesRequestedPort)
}

function Format-PortProcessInfo {
    param([Parameter(Mandatory = $true)]$ProcessInfo)

    return "PID=$($ProcessInfo.PID); Executable=$($ProcessInfo.ExecutablePath); CommandLine=$($ProcessInfo.CommandLine)"
}

function Assert-LitWatchImportPath {
    $script:StackPython = Resolve-LitWatchPython

    $Expected = (Resolve-Path -LiteralPath (Join-Path $script:StackSourceDirectory "litwatch\web.py")).Path
    $PreviousSource = $env:LITWATCH_STACK_SOURCE
    $PreviousExpected = $env:LITWATCH_STACK_EXPECTED_WEB
    $env:LITWATCH_STACK_SOURCE = $script:StackSourceDirectory
    $env:LITWATCH_STACK_EXPECTED_WEB = $Expected
    try {
        $PythonCode = "import os, pathlib, sys; sys.path.insert(0, os.environ['LITWATCH_STACK_SOURCE']); import litwatch.web; actual=pathlib.Path(litwatch.web.__file__).resolve(); expected=pathlib.Path(os.environ['LITWATCH_STACK_EXPECTED_WEB']).resolve(); print('MATCH' if actual == expected else 'MISMATCH'); sys.exit(0 if actual == expected else 3)"
        $ImportResult = & $script:StackPython -c $PythonCode 2>$null | Select-Object -Last 1
        if ($LASTEXITCODE -ne 0 -or $ImportResult -ne "MATCH") {
            throw "[LitWatch] Import path mismatch or import failure. Expected '$Expected'."
        }
    }
    finally {
        if ($null -eq $PreviousSource) {
            Remove-Item Env:LITWATCH_STACK_SOURCE -ErrorAction SilentlyContinue
        }
        else {
            $env:LITWATCH_STACK_SOURCE = $PreviousSource
        }
        if ($null -eq $PreviousExpected) {
            Remove-Item Env:LITWATCH_STACK_EXPECTED_WEB -ErrorAction SilentlyContinue
        }
        else {
            $env:LITWATCH_STACK_EXPECTED_WEB = $PreviousExpected
        }
    }
    return $Expected
}

function Get-PythonRuntimeStatus {
    param(
        [int]$Port = 8000,
        [int]$TimeoutSeconds = 10
    )

    try {
        $Runtime = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v2/runtime" -TimeoutSec $TimeoutSeconds
        $Ready = (
            $Runtime.mode -eq "python_default" -and
            $Runtime.python_primary -eq $true -and
            $Runtime.requires_dify -eq $false -and
            $Runtime.requires_docker -eq $false -and
            $Runtime.requires_ssrf_proxy -eq $false
        )
        return [PSCustomObject]@{
            Ready = [bool]$Ready
            Detail = "mode=$($Runtime.mode); python_primary=$($Runtime.python_primary)"
        }
    }
    catch {
        return [PSCustomObject]@{
            Ready = $false
            Detail = $_.Exception.Message
        }
    }
}

function Get-OpenAlexRegistryStatus {
    param(
        [int]$Port = 8000,
        [int]$TimeoutSeconds = 10
    )

    try {
        $ProviderResponse = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/providers" -TimeoutSec $TimeoutSeconds
        $OpenAlex = $null
        foreach ($Provider in $ProviderResponse) {
            if ($Provider.provider_type -eq "openalex") {
                $OpenAlex = $Provider
                break
            }
        }
        return [PSCustomObject]@{
            Ready = [bool]($OpenAlex -and $OpenAlex.runnable -eq $true)
            Detail = if ($OpenAlex) { "OpenAlex runnable=$($OpenAlex.runnable)" } else { "OpenAlex provider missing" }
        }
    }
    catch {
        return [PSCustomObject]@{
            Ready = $false
            Detail = $_.Exception.Message
        }
    }
}
