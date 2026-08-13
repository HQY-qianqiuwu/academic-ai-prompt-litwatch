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
    param([int]$Port = 8000)

    $WorktreePython = Join-Path $script:StackProjectRoot ".venv\Scripts\python.exe"
    $ResolvedWorktreePython = if (Test-Path -LiteralPath $WorktreePython -PathType Leaf) {
        (Resolve-Path -LiteralPath $WorktreePython).Path
    }
    else {
        $null
    }
    if ([string]::IsNullOrWhiteSpace($env:LITWATCH_PYTHON)) {
        if ($ResolvedWorktreePython) {
            return $ResolvedWorktreePython
        }
        throw "[Python Runtime] The current worktree virtual environment is missing: $WorktreePython"
    }

    if (-not (Test-Path -LiteralPath $env:LITWATCH_PYTHON -PathType Leaf)) {
        throw "[Python Runtime] Configured Python executable was not found: $($env:LITWATCH_PYTHON)"
    }
    $ConfiguredPython = (Resolve-Path -LiteralPath $env:LITWATCH_PYTHON).Path
    if (
        $ResolvedWorktreePython -and
        $ConfiguredPython.Equals(
            $ResolvedWorktreePython,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        return $ConfiguredPython
    }
    if ($Port -eq 8000) {
        throw "[Python Runtime] Default port 8000 requires the current worktree interpreter: $WorktreePython"
    }
    if ($env:LITWATCH_ALLOW_EXTERNAL_PYTHON -ne "1") {
        throw "[Python Runtime] External Python is restricted to explicit non-default-port smoke runs. Set LITWATCH_ALLOW_EXTERNAL_PYTHON=1."
    }
    return $ConfiguredPython
}

function Get-ManagedStackIdentity {
    if (-not (Test-Path -LiteralPath $script:StackPidPath -PathType Leaf)) {
        return $null
    }
    try {
        $Identity = Get-Content -Raw -LiteralPath $script:StackPidPath | ConvertFrom-Json
    }
    catch {
        throw "[LitWatch] Invalid managed process identity file: $script:StackPidPath"
    }
    $ManagedPid = 0
    if (
        $Identity.version -ne 1 -or
        -not [int]::TryParse([string]$Identity.pid, [ref]$ManagedPid) -or
        $ManagedPid -le 0 -or
        [string]::IsNullOrWhiteSpace([string]$Identity.creation_time_utc) -or
        [string]$Identity.fingerprint -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "[LitWatch] Invalid managed process identity file: $script:StackPidPath"
    }
    return [PSCustomObject]@{
        Version = 1
        PID = $ManagedPid
        CreationTimeUtc = [string]$Identity.creation_time_utc
        Fingerprint = [string]$Identity.fingerprint
    }
}

function Set-ManagedStackIdentity {
    param([Parameter(Mandatory = $true)]$Identity)

    $Document = [ordered]@{
        version = 1
        pid = [int]$Identity.PID
        creation_time_utc = [string]$Identity.CreationTimeUtc
        fingerprint = [string]$Identity.Fingerprint
    }
    $Document | ConvertTo-Json -Compress | Set-Content -LiteralPath $script:StackPidPath -Encoding utf8
}

function Get-ProcessInfoById {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $ProcessInfo) {
        return $null
    }
    return [PSCustomObject]@{
        PID = [int]$ProcessInfo.ProcessId
        CreationDate = $ProcessInfo.CreationDate
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
                CreationDate = $ProcessInfo.CreationDate
                ExecutablePath = [string]$ProcessInfo.ExecutablePath
                CommandLine = [string]$ProcessInfo.CommandLine
            }
        }
    }
    return $Results
}

function ConvertFrom-WindowsCommandLine {
    param([Parameter(Mandatory = $true)][string]$CommandLine)

    if (-not ("LitWatchCommandLineNative" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class LitWatchCommandLineNative
{
    [DllImport("shell32.dll", SetLastError = true)]
    private static extern IntPtr CommandLineToArgvW(
        [MarshalAs(UnmanagedType.LPWStr)] string commandLine,
        out int argumentCount
    );

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr handle);

    public static string[] Split(string commandLine)
    {
        int argumentCount;
        IntPtr argumentVector = CommandLineToArgvW(commandLine, out argumentCount);
        if (argumentVector == IntPtr.Zero)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        try
        {
            var arguments = new List<string>(argumentCount);
            for (int index = 0; index < argumentCount; index++)
            {
                IntPtr argument = Marshal.ReadIntPtr(
                    argumentVector,
                    index * IntPtr.Size
                );
                arguments.Add(Marshal.PtrToStringUni(argument));
            }
            return arguments.ToArray();
        }
        finally
        {
            LocalFree(argumentVector);
        }
    }
}
"@
    }
    return [LitWatchCommandLineNative]::Split($CommandLine)
}

function Get-CanonicalPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        return [System.IO.Path]::GetFullPath($Path).TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
    }
    catch {
        return $null
    }
}

function Test-CanonicalPathEquals {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    $CanonicalLeft = Get-CanonicalPath -Path $Left
    $CanonicalRight = Get-CanonicalPath -Path $Right
    return (
        $CanonicalLeft -and
        $CanonicalRight -and
        $CanonicalLeft.Equals(
            $CanonicalRight,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Test-IsCurrentLitWatchProcess {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [int]$Port = 8000,
        [string]$ExpectedHost = "127.0.0.1"
    )

    $CommandLine = [string]$ProcessInfo.CommandLine
    $ExecutablePath = [string]$ProcessInfo.ExecutablePath
    if (
        [string]::IsNullOrWhiteSpace($CommandLine) -or
        [string]::IsNullOrWhiteSpace($ExecutablePath)
    ) {
        return $false
    }
    try {
        $Arguments = @(ConvertFrom-WindowsCommandLine -CommandLine $CommandLine)
    }
    catch {
        return $false
    }
    if ($Arguments.Count -ne 10) {
        return $false
    }
    return (
        (Test-CanonicalPathEquals -Left $ExecutablePath -Right $script:StackPython) -and
        (Test-CanonicalPathEquals -Left $Arguments[0] -Right $script:StackPython) -and
        $Arguments[1] -ceq "-m" -and
        $Arguments[2] -ceq "uvicorn" -and
        $Arguments[3] -ceq "litwatch.web:app" -and
        $Arguments[4] -ceq "--app-dir" -and
        (Test-CanonicalPathEquals -Left $Arguments[5] -Right $script:StackSourceDirectory) -and
        $Arguments[6] -ceq "--host" -and
        $Arguments[7] -ceq $ExpectedHost -and
        $Arguments[8] -ceq "--port" -and
        $Arguments[9] -ceq ([string]$Port)
    )
}

function Get-ProcessCreationTimeUtc {
    param([Parameter(Mandatory = $true)]$ProcessInfo)

    try {
        return ([DateTimeOffset]$ProcessInfo.CreationDate).ToUniversalTime().ToString("o")
    }
    catch {
        return $null
    }
}

function Get-LitWatchProcessFingerprint {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [int]$Port = 8000,
        [string]$ExpectedHost = "127.0.0.1"
    )

    if (-not (Test-IsCurrentLitWatchProcess -ProcessInfo $ProcessInfo -Port $Port -ExpectedHost $ExpectedHost)) {
        return $null
    }
    $Fields = @(
        (Get-CanonicalPath -Path ([string]$ProcessInfo.ExecutablePath)).ToLowerInvariant(),
        (Get-CanonicalPath -Path $script:StackSourceDirectory).ToLowerInvariant(),
        $ExpectedHost.ToLowerInvariant(),
        [string]$Port
    )
    $Bytes = [System.Text.Encoding]::UTF8.GetBytes(($Fields -join "`n"))
    $Hash = [System.Security.Cryptography.SHA256]::Create()
    try {
        return (($Hash.ComputeHash($Bytes) | ForEach-Object { $_.ToString("x2") }) -join "")
    }
    finally {
        $Hash.Dispose()
    }
}

function New-ManagedStackIdentity {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [int]$Port = 8000,
        [string]$ExpectedHost = "127.0.0.1"
    )

    $CreationTimeUtc = Get-ProcessCreationTimeUtc -ProcessInfo $ProcessInfo
    $Fingerprint = Get-LitWatchProcessFingerprint -ProcessInfo $ProcessInfo -Port $Port -ExpectedHost $ExpectedHost
    if (-not $CreationTimeUtc -or -not $Fingerprint) {
        throw "[LitWatch] Process identity does not match the expected current-worktree command."
    }
    return [PSCustomObject]@{
        Version = 1
        PID = [int]$ProcessInfo.PID
        CreationTimeUtc = $CreationTimeUtc
        Fingerprint = $Fingerprint
    }
}

function Get-ProcessHandleStartTimeUtc {
    param([Parameter(Mandatory = $true)]$ProcessHandle)

    try {
        return ([DateTimeOffset]$ProcessHandle.StartTime).ToUniversalTime().ToString("o")
    }
    catch {
        return $null
    }
}

function Test-ProcessStartTimeMatches {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    try {
        $LeftUtc = ([DateTimeOffset]$Left).ToUniversalTime()
        $RightUtc = ([DateTimeOffset]$Right).ToUniversalTime()
        return [Math]::Abs(($LeftUtc - $RightUtc).Ticks) -lt 10
    }
    catch {
        return $false
    }
}

function Wait-StartedLitWatchIdentity {
    param(
        [Parameter(Mandatory = $true)]$ProcessHandle,
        [Parameter(Mandatory = $true)][string]$HandleStartTimeUtc,
        [int]$Port = 8000,
        [ValidateRange(1, 100)][int]$MaxAttempts = 20,
        [ValidateRange(0, 5000)][int]$RetryDelayMilliseconds = 100
    )

    $LastFailure = "process information was unavailable"
    for ($Attempt = 1; $Attempt -le $MaxAttempts; $Attempt += 1) {
        try {
            if ($ProcessHandle.HasExited) {
                $LastFailure = "the process exited before identity capture"
                break
            }
            $ProcessInfo = Get-ProcessInfoById -ProcessId ([int]$ProcessHandle.Id)
            if ($ProcessInfo) {
                $CimStartTimeUtc = Get-ProcessCreationTimeUtc -ProcessInfo $ProcessInfo
                if (-not $CimStartTimeUtc) {
                    $LastFailure = "the process creation time was unavailable"
                }
                elseif (-not (Test-ProcessStartTimeMatches -Left $HandleStartTimeUtc -Right $CimStartTimeUtc)) {
                    $LastFailure = "the process creation time did not match the retained handle"
                }
                else {
                    try {
                        return New-ManagedStackIdentity -ProcessInfo $ProcessInfo -Port $Port
                    }
                    catch {
                        $LastFailure = $_.Exception.Message
                    }
                }
            }
        }
        catch {
            $LastFailure = $_.Exception.Message
        }
        if ($Attempt -lt $MaxAttempts -and $RetryDelayMilliseconds -gt 0) {
            Start-Sleep -Milliseconds $RetryDelayMilliseconds
        }
    }
    throw "[LitWatch] Started PID $($ProcessHandle.Id) could not be identified safely after $MaxAttempts attempts. $LastFailure"
}

function Stop-StartedProcessHandle {
    param(
        [Parameter(Mandatory = $true)]$ProcessHandle,
        [Parameter(Mandatory = $true)][string]$ExpectedStartTimeUtc,
        [ValidateRange(1, 60000)][int]$WaitTimeoutMilliseconds = 5000
    )

    $CurrentStartTimeUtc = Get-ProcessHandleStartTimeUtc -ProcessHandle $ProcessHandle
    if (
        -not $CurrentStartTimeUtc -or
        -not (Test-ProcessStartTimeMatches -Left $ExpectedStartTimeUtc -Right $CurrentStartTimeUtc)
    ) {
        throw "[LitWatch] Retained process handle creation time changed. Refusing cleanup."
    }
    if ($ProcessHandle.HasExited) {
        return
    }
    $ProcessHandle.Kill()
    if (-not $ProcessHandle.WaitForExit($WaitTimeoutMilliseconds)) {
        throw "[LitWatch] Started process did not exit within $WaitTimeoutMilliseconds milliseconds."
    }
}

function Test-MatchesManagedStackIdentity {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [Parameter(Mandatory = $true)]$Identity,
        [int]$Port = 8000,
        [string]$ExpectedHost = "127.0.0.1"
    )

    if ([int]$ProcessInfo.PID -ne [int]$Identity.PID) {
        return $false
    }
    $CreationTimeUtc = Get-ProcessCreationTimeUtc -ProcessInfo $ProcessInfo
    $Fingerprint = Get-LitWatchProcessFingerprint -ProcessInfo $ProcessInfo -Port $Port -ExpectedHost $ExpectedHost
    return (
        $CreationTimeUtc -and
        $Fingerprint -and
        $CreationTimeUtc -ceq [string]$Identity.CreationTimeUtc -and
        $Fingerprint -ceq [string]$Identity.Fingerprint
    )
}

function Stop-ManagedLitWatchProcess {
    param(
        [Parameter(Mandatory = $true)]$Identity,
        [int]$Port = 8000,
        [string]$ExpectedHost = "127.0.0.1"
    )

    $CurrentProcess = Get-ProcessInfoById -ProcessId ([int]$Identity.PID)
    if (
        -not $CurrentProcess -or
        -not (Test-MatchesManagedStackIdentity -ProcessInfo $CurrentProcess -Identity $Identity -Port $Port -ExpectedHost $ExpectedHost)
    ) {
        throw "[LitWatch] Managed process identity changed before stop. Refusing to stop PID $($Identity.PID)."
    }
    Stop-Process -Id ([int]$Identity.PID) -ErrorAction Stop
}

function Format-PortProcessInfo {
    param([Parameter(Mandatory = $true)]$ProcessInfo)

    return "PID=$($ProcessInfo.PID); Created=$($ProcessInfo.CreationDate); Executable=$($ProcessInfo.ExecutablePath); CommandLine=$($ProcessInfo.CommandLine)"
}

function Assert-LitWatchImportPath {
    param([int]$Port = 8000)

    $script:StackPython = Resolve-LitWatchPython -Port $Port

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
        $DependenciesReady = (
            $Runtime.mode -eq "python_default" -and
            $Runtime.python_primary -eq $true -and
            $Runtime.requires_dify -eq $false -and
            $Runtime.requires_docker -eq $false -and
            $Runtime.requires_ssrf_proxy -eq $false
        )
        $MigrationReady = $Runtime.migration_verified -eq $true
        $RuntimeReady = $DependenciesReady -and $Runtime.runtime_started -eq $true
        $WorkerReady = $RuntimeReady -and $Runtime.job_worker_running -eq $true
        $SchedulerReady = (
            $RuntimeReady -and
            $Runtime.scheduler_running -eq $true -and
            [string]::IsNullOrWhiteSpace([string]$Runtime.scheduler_last_error)
        )
        return [PSCustomObject]@{
            Ready = [bool]($MigrationReady -and $RuntimeReady -and $WorkerReady -and $SchedulerReady)
            MigrationReady = [bool]$MigrationReady
            RuntimeReady = [bool]$RuntimeReady
            WorkerReady = [bool]$WorkerReady
            SchedulerReady = [bool]$SchedulerReady
            WorkerActive = [int]$Runtime.job_worker_active
            SchedulerLastError = [string]$Runtime.scheduler_last_error
            Detail = "mode=$($Runtime.mode); migration_verified=$($Runtime.migration_verified); runtime_started=$($Runtime.runtime_started); worker_running=$($Runtime.job_worker_running); worker_active=$($Runtime.job_worker_active); scheduler_running=$($Runtime.scheduler_running); scheduler_last_error=$($Runtime.scheduler_last_error)"
        }
    }
    catch {
        return [PSCustomObject]@{
            Ready = $false
            MigrationReady = $false
            RuntimeReady = $false
            WorkerReady = $false
            SchedulerReady = $false
            WorkerActive = 0
            SchedulerLastError = "runtime_status_unavailable"
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
