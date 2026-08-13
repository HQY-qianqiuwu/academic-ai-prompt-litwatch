Set-StrictMode -Version Latest

$script:StackProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:StackSourceDirectory = Join-Path $script:StackProjectRoot "src"
$script:StackPython = Join-Path $script:StackProjectRoot ".venv\Scripts\python.exe"
$script:StackBasePython = $script:StackPython
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

function Resolve-LitWatchBasePython {
    if (-not (Test-Path -LiteralPath $script:StackPython -PathType Leaf)) {
        throw "[Python Runtime] Configured Python executable was not found: $script:StackPython"
    }
    $BasePython = & $script:StackPython -c "import pathlib,sys; print(pathlib.Path(getattr(sys, '_base_executable', sys.executable)).resolve())" 2>$null | Select-Object -Last 1
    if (
        $LASTEXITCODE -ne 0 -or
        [string]::IsNullOrWhiteSpace([string]$BasePython) -or
        -not (Test-Path -LiteralPath ([string]$BasePython) -PathType Leaf)
    ) {
        throw "[Python Runtime] The trusted Python base executable could not be resolved safely."
    }
    return (Resolve-Path -LiteralPath ([string]$BasePython)).Path
}

function Set-LitWatchRuntimeExecutables {
    param([int]$Port = 8000)

    $script:StackPython = Resolve-LitWatchPython -Port $Port
    $script:StackBasePython = Resolve-LitWatchBasePython
}

function Get-StackOwnershipRecord {
    if (-not (Test-Path -LiteralPath $script:StackPidPath -PathType Leaf)) {
        return $null
    }
    try {
        $Record = Get-Content -Raw -Encoding utf8 -LiteralPath $script:StackPidPath | ConvertFrom-Json
    }
    catch {
        throw "[LitWatch] Invalid managed process identity file: $script:StackPidPath"
    }
    $ManagedPid = 0
    if ($Record.version -notin @(1, 2)) {
        throw "[LitWatch] Invalid managed process identity file: $script:StackPidPath"
    }

    if ($Record.version -eq 2) {
        if (
            [string]$Record.state -cne "final" -or
            [string]$Record.topology -cne "launcher_child"
        ) {
            throw "[LitWatch] Invalid managed process identity file: $script:StackPidPath"
        }
        $LaunchPid = 0
        $OwnerPid = 0
        if (
            $null -eq $Record.launch_process -or
            $null -eq $Record.port_owner_process -or
            -not [int]::TryParse([string]$Record.launch_process.pid, [ref]$LaunchPid) -or
            -not [int]::TryParse([string]$Record.port_owner_process.pid, [ref]$OwnerPid) -or
            $LaunchPid -le 0 -or
            $OwnerPid -le 0 -or
            $LaunchPid -eq $OwnerPid -or
            [string]::IsNullOrWhiteSpace([string]$Record.launch_process.creation_time_utc) -or
            [string]::IsNullOrWhiteSpace([string]$Record.port_owner_process.creation_time_utc) -or
            [string]$Record.launch_process.fingerprint -notmatch '^[0-9a-f]{64}$' -or
            [string]$Record.port_owner_process.fingerprint -notmatch '^[0-9a-f]{64}$'
        ) {
            throw "[LitWatch] Invalid managed process identity file: $script:StackPidPath"
        }
        try {
            [void][DateTimeOffset]$Record.launch_process.creation_time_utc
            [void][DateTimeOffset]$Record.port_owner_process.creation_time_utc
        }
        catch {
            throw "[LitWatch] Invalid managed process identity file: $script:StackPidPath"
        }
        $LaunchIdentity = [PSCustomObject]@{
            Version = 1
            PID = $LaunchPid
            CreationTimeUtc = [string]$Record.launch_process.creation_time_utc
            Fingerprint = [string]$Record.launch_process.fingerprint
        }
        $PortOwnerIdentity = [PSCustomObject]@{
            Version = 1
            PID = $OwnerPid
            CreationTimeUtc = [string]$Record.port_owner_process.creation_time_utc
            Fingerprint = [string]$Record.port_owner_process.fingerprint
        }
        return [PSCustomObject]@{
            Version = 2
            State = "final"
            Topology = "launcher_child"
            PID = $LaunchPid
            CreationTimeUtc = $LaunchIdentity.CreationTimeUtc
            Fingerprint = $LaunchIdentity.Fingerprint
            LaunchProcess = $LaunchIdentity
            PortOwnerProcess = $PortOwnerIdentity
        }
    }

    if (
        -not [int]::TryParse([string]$Record.pid, [ref]$ManagedPid) -or
        $ManagedPid -le 0
    ) {
        throw "[LitWatch] Invalid managed process identity file: $script:StackPidPath"
    }

    $StateProperty = $Record.PSObject.Properties["state"]
    $State = if (-not $StateProperty -or [string]::IsNullOrWhiteSpace([string]$StateProperty.Value)) {
        "final"
    }
    else {
        ([string]$StateProperty.Value).ToLowerInvariant()
    }
    if ($State -eq "final") {
        if (
            [string]::IsNullOrWhiteSpace([string]$Record.creation_time_utc) -or
            [string]$Record.fingerprint -notmatch '^[0-9a-f]{64}$'
        ) {
            throw "[LitWatch] Invalid managed process identity file: $script:StackPidPath"
        }
        return [PSCustomObject]@{
            Version = 1
            State = "final"
            Topology = "direct"
            PID = $ManagedPid
            CreationTimeUtc = [string]$Record.creation_time_utc
            Fingerprint = [string]$Record.fingerprint
        }
    }
    if ($State -ne "provisional") {
        throw "[LitWatch] Invalid managed process identity file: $script:StackPidPath"
    }

    $LaunchId = [guid]::Empty
    $ExpectedPort = 0
    $HandleStartTimeProperty = $Record.PSObject.Properties["handle_start_time_utc"]
    $HandleStartTimeUtc = if ($HandleStartTimeProperty) {
        [string]$HandleStartTimeProperty.Value
    }
    else {
        $null
    }
    if (
        -not [guid]::TryParse([string]$Record.launch_id, [ref]$LaunchId) -or
        $LaunchId -eq [guid]::Empty -or
        -not [int]::TryParse([string]$Record.expected_port, [ref]$ExpectedPort) -or
        $ExpectedPort -lt 1 -or
        $ExpectedPort -gt 65535 -or
        [string]::IsNullOrWhiteSpace([string]$Record.expected_executable) -or
        [string]::IsNullOrWhiteSpace([string]$Record.expected_app_dir) -or
        [string]::IsNullOrWhiteSpace([string]$Record.expected_host)
    ) {
        throw "[LitWatch] Invalid provisional ownership record: $script:StackPidPath"
    }
    if (-not [string]::IsNullOrWhiteSpace($HandleStartTimeUtc)) {
        try {
            [void][DateTimeOffset]$HandleStartTimeUtc
        }
        catch {
            throw "[LitWatch] Invalid provisional ownership record: $script:StackPidPath"
        }
    }
    return [PSCustomObject]@{
        Version = 1
        State = "provisional"
        LaunchId = $LaunchId.ToString("D")
        PID = $ManagedPid
        HandleStartTimeUtc = $HandleStartTimeUtc
        ExpectedExecutable = [string]$Record.expected_executable
        ExpectedAppDirectory = [string]$Record.expected_app_dir
        ExpectedHost = [string]$Record.expected_host
        ExpectedPort = $ExpectedPort
    }
}

function Get-ManagedStackIdentity {
    $Record = Get-StackOwnershipRecord
    if ($null -eq $Record) {
        return $null
    }
    if ($Record.State -eq "provisional") {
        throw "[LitWatch] Provisional ownership record for PID $($Record.PID) does not authorize normal lifecycle operations. Resolve the failed startup before retrying."
    }
    return $Record
}

function Write-StackOwnershipRecordAtomic {
    param(
        [Parameter(Mandatory = $true)]$Document,
        [switch]$RequireAbsent,
        $ExpectedRecord = $null
    )

    $Json = $Document | ConvertTo-Json -Compress
    $WriteId = [guid]::NewGuid().ToString('N')
    $TemporaryPath = "$script:StackPidPath.$WriteId.tmp"
    $BackupPath = "$script:StackPidPath.$WriteId.bak"
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($TemporaryPath, $Json, $Utf8NoBom)
    try {
        if ($RequireAbsent) {
            if (Test-Path -LiteralPath $script:StackPidPath -PathType Leaf) {
                throw "[LitWatch] Ownership record already exists: $script:StackPidPath"
            }
            [System.IO.File]::Move($TemporaryPath, $script:StackPidPath)
            return
        }
        if ($null -eq $ExpectedRecord) {
            throw "[LitWatch] Atomic ownership replacement requires an expected record."
        }
        $CurrentRecord = Get-StackOwnershipRecord
        if (-not (Test-StackOwnershipRecordEquals -Left $CurrentRecord -Right $ExpectedRecord)) {
            throw "[LitWatch] Ownership record changed before atomic replacement. Refusing overwrite."
        }
        [System.IO.File]::Replace($TemporaryPath, $script:StackPidPath, $BackupPath)
    }
    finally {
        if (Test-Path -LiteralPath $TemporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $TemporaryPath -Force
        }
        if (Test-Path -LiteralPath $BackupPath -PathType Leaf) {
            Remove-Item -LiteralPath $BackupPath -Force
        }
    }
}

function Test-StackOwnershipRecordEquals {
    param(
        $Left,
        $Right
    )

    if ($null -eq $Left -or $null -eq $Right -or $Left.State -cne $Right.State) {
        return $false
    }
    if ([int]$Left.PID -ne [int]$Right.PID) {
        return $false
    }
    if ($Left.State -eq "final") {
        if ([int]$Left.Version -ne [int]$Right.Version) {
            return $false
        }
        if ([int]$Left.Version -eq 2) {
            return (
                $Left.Topology -ceq $Right.Topology -and
                (Test-StackProcessIdentityEquals -Left $Left.LaunchProcess -Right $Right.LaunchProcess) -and
                (Test-StackProcessIdentityEquals -Left $Left.PortOwnerProcess -Right $Right.PortOwnerProcess)
            )
        }
        return (
            $Left.CreationTimeUtc -ceq $Right.CreationTimeUtc -and
            $Left.Fingerprint -ceq $Right.Fingerprint
        )
    }
    return (
        $Left.LaunchId -ceq $Right.LaunchId -and
        [string]$Left.HandleStartTimeUtc -ceq [string]$Right.HandleStartTimeUtc -and
        $Left.ExpectedExecutable -ceq $Right.ExpectedExecutable -and
        $Left.ExpectedAppDirectory -ceq $Right.ExpectedAppDirectory -and
        $Left.ExpectedHost -ceq $Right.ExpectedHost -and
        [int]$Left.ExpectedPort -eq [int]$Right.ExpectedPort
    )
}

function Test-StackProcessIdentityEquals {
    param($Left, $Right)

    return (
        $null -ne $Left -and
        $null -ne $Right -and
        [int]$Left.PID -eq [int]$Right.PID -and
        [string]$Left.CreationTimeUtc -ceq [string]$Right.CreationTimeUtc -and
        [string]$Left.Fingerprint -ceq [string]$Right.Fingerprint
    )
}

function New-ProvisionalStackIdentity {
    param(
        [Parameter(Mandatory = $true)]$ProcessHandle,
        [AllowNull()][string]$HandleStartTimeUtc,
        [int]$Port = 8000,
        [string]$ExpectedHost = "127.0.0.1"
    )

    return [PSCustomObject]@{
        Version = 1
        State = "provisional"
        LaunchId = [guid]::NewGuid().ToString("D")
        PID = [int]$ProcessHandle.Id
        HandleStartTimeUtc = $HandleStartTimeUtc
        ExpectedExecutable = Get-CanonicalPath -Path $script:StackPython
        ExpectedAppDirectory = Get-CanonicalPath -Path $script:StackSourceDirectory
        ExpectedHost = $ExpectedHost
        ExpectedPort = $Port
    }
}

function Set-ProvisionalStackIdentity {
    param([Parameter(Mandatory = $true)]$Identity)

    $Document = [ordered]@{
        version = 1
        state = "provisional"
        launch_id = [string]$Identity.LaunchId
        pid = [int]$Identity.PID
        handle_start_time_utc = if ([string]::IsNullOrWhiteSpace([string]$Identity.HandleStartTimeUtc)) { $null } else { [string]$Identity.HandleStartTimeUtc }
        expected_executable = [string]$Identity.ExpectedExecutable
        expected_app_dir = [string]$Identity.ExpectedAppDirectory
        expected_host = [string]$Identity.ExpectedHost
        expected_port = [int]$Identity.ExpectedPort
    }
    Write-StackOwnershipRecordAtomic -Document $Document -RequireAbsent
}

function Set-ManagedStackIdentity {
    param(
        [Parameter(Mandatory = $true)]$Identity,
        [Parameter(Mandatory = $true)]$ExpectedProvisional
    )

    if ($ExpectedProvisional.State -cne "provisional") {
        throw "[LitWatch] Final identity upgrade requires a provisional ownership record."
    }
    if (
        [int]$Identity.PID -ne [int]$ExpectedProvisional.PID -or
        -not (Test-ProcessStartTimeMatches -Left $Identity.CreationTimeUtc -Right $ExpectedProvisional.HandleStartTimeUtc)
    ) {
        throw "[LitWatch] Final identity does not match the provisional process creation identity."
    }

    if ([int]$Identity.Version -eq 2) {
        if (
            $Identity.Topology -cne "launcher_child" -or
            [int]$Identity.LaunchProcess.PID -ne [int]$ExpectedProvisional.PID
        ) {
            throw "[LitWatch] Final stack identity does not match the provisional launch process."
        }
        $Document = [ordered]@{
            version = 2
            state = "final"
            topology = "launcher_child"
            launch_process = [ordered]@{
                pid = [int]$Identity.LaunchProcess.PID
                creation_time_utc = [string]$Identity.LaunchProcess.CreationTimeUtc
                fingerprint = [string]$Identity.LaunchProcess.Fingerprint
            }
            port_owner_process = [ordered]@{
                pid = [int]$Identity.PortOwnerProcess.PID
                creation_time_utc = [string]$Identity.PortOwnerProcess.CreationTimeUtc
                fingerprint = [string]$Identity.PortOwnerProcess.Fingerprint
            }
        }
    }
    else {
        $Document = [ordered]@{
            version = 1
            state = "final"
            pid = [int]$Identity.PID
            creation_time_utc = [string]$Identity.CreationTimeUtc
            fingerprint = [string]$Identity.Fingerprint
        }
    }
    Write-StackOwnershipRecordAtomic -Document $Document -ExpectedRecord $ExpectedProvisional
}

function Remove-StackOwnershipRecord {
    param([Parameter(Mandatory = $true)]$ExpectedRecord)

    if (-not (Test-Path -LiteralPath $script:StackPidPath -PathType Leaf)) {
        return
    }
    $CurrentRecord = Get-StackOwnershipRecord
    if (-not (Test-StackOwnershipRecordEquals -Left $CurrentRecord -Right $ExpectedRecord)) {
        throw "[LitWatch] Ownership record changed before cleanup. Refusing removal."
    }
    Remove-Item -LiteralPath $script:StackPidPath -Force
}

function Get-ProcessInfoById {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $ProcessInfo) {
        return $null
    }
    return [PSCustomObject]@{
        PID = [int]$ProcessInfo.ProcessId
        ParentPID = [int]$ProcessInfo.ParentProcessId
        CreationDate = $ProcessInfo.CreationDate
        ExecutablePath = [string]$ProcessInfo.ExecutablePath
        CommandLine = [string]$ProcessInfo.CommandLine
    }
}

function Get-DirectChildProcessInfos {
    param([Parameter(Mandatory = $true)][int]$ParentProcessId)

    $Children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentProcessId" -ErrorAction SilentlyContinue)
    return @($Children | ForEach-Object {
        [PSCustomObject]@{
            PID = [int]$_.ProcessId
            ParentPID = [int]$_.ParentProcessId
            CreationDate = $_.CreationDate
            ExecutablePath = [string]$_.ExecutablePath
            CommandLine = [string]$_.CommandLine
        }
    })
}

function Get-ProcessHandleById {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    return Get-Process -Id $ProcessId -ErrorAction Stop
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
                ParentPID = [int]$ProcessInfo.ParentProcessId
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
        [string]$ExpectedHost = "127.0.0.1",
        [string]$ExpectedExecutable = $script:StackPython
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
        (Test-CanonicalPathEquals -Left $ExecutablePath -Right $ExpectedExecutable) -and
        (Test-CanonicalPathEquals -Left $Arguments[0] -Right $ExpectedExecutable) -and
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
        [string]$ExpectedHost = "127.0.0.1",
        [string]$ExpectedExecutable = $script:StackPython
    )

    if (-not (Test-IsCurrentLitWatchProcess -ProcessInfo $ProcessInfo -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $ExpectedExecutable)) {
        return $null
    }
    $Fields = @(
        (Get-CanonicalPath -Path $ExpectedExecutable).ToLowerInvariant(),
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
        [string]$ExpectedHost = "127.0.0.1",
        [string]$ExpectedExecutable = $script:StackPython
    )

    $CreationTimeUtc = Get-ProcessCreationTimeUtc -ProcessInfo $ProcessInfo
    $Fingerprint = Get-LitWatchProcessFingerprint -ProcessInfo $ProcessInfo -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $ExpectedExecutable
    if (-not $CreationTimeUtc -or -not $Fingerprint) {
        throw "[LitWatch] Process identity does not match the expected current-worktree command."
    }
    return [PSCustomObject]@{
        Version = 1
        State = "final"
        Topology = "direct"
        PID = [int]$ProcessInfo.PID
        CreationTimeUtc = $CreationTimeUtc
        Fingerprint = $Fingerprint
    }
}

function New-ManagedLauncherChildIdentity {
    param(
        [Parameter(Mandatory = $true)]$LaunchIdentity,
        [Parameter(Mandatory = $true)]$PortOwnerIdentity
    )

    return [PSCustomObject]@{
        Version = 2
        State = "final"
        Topology = "launcher_child"
        PID = [int]$LaunchIdentity.PID
        CreationTimeUtc = [string]$LaunchIdentity.CreationTimeUtc
        Fingerprint = [string]$LaunchIdentity.Fingerprint
        LaunchProcess = $LaunchIdentity
        PortOwnerProcess = $PortOwnerIdentity
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

function Test-ProcessCreationLineage {
    param(
        [Parameter(Mandatory = $true)][string]$ParentCreationTimeUtc,
        [Parameter(Mandatory = $true)][string]$ChildCreationTimeUtc,
        [ValidateRange(1, 300)][int]$MaximumDelaySeconds = 30
    )

    try {
        $ParentUtc = ([DateTimeOffset]$ParentCreationTimeUtc).ToUniversalTime()
        $ChildUtc = ([DateTimeOffset]$ChildCreationTimeUtc).ToUniversalTime()
        $Delay = ($ChildUtc - $ParentUtc).TotalSeconds
        return $Delay -ge 0 -and $Delay -le $MaximumDelaySeconds
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
        [string]$ExpectedHost = "127.0.0.1",
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
            $LaunchProcessInfo = Get-ProcessInfoById -ProcessId ([int]$ProcessHandle.Id)
            if ($LaunchProcessInfo) {
                $CimStartTimeUtc = Get-ProcessCreationTimeUtc -ProcessInfo $LaunchProcessInfo
                if (-not $CimStartTimeUtc) {
                    $LastFailure = "the process creation time was unavailable"
                }
                elseif (-not (Test-ProcessStartTimeMatches -Left $HandleStartTimeUtc -Right $CimStartTimeUtc)) {
                    $LastFailure = "the process creation time did not match the retained handle"
                }
                else {
                    try {
                        $LaunchIdentity = New-ManagedStackIdentity -ProcessInfo $LaunchProcessInfo -Port $Port -ExpectedExecutable $script:StackPython
                        $PortProcesses = @(Get-PortProcessInfo -Port $Port)
                        if ($PortProcesses.Count -ne 1) {
                            $LastFailure = "the expected port did not have exactly one owner"
                            throw $LastFailure
                        }
                        $PortOwner = $PortProcesses[0]
                        if ([int]$PortOwner.PID -eq [int]$LaunchIdentity.PID) {
                            if (-not (Test-MatchesManagedProcessIdentity -ProcessInfo $PortOwner -Identity $LaunchIdentity -Port $Port -ExpectedExecutable $script:StackPython)) {
                                $LastFailure = "the launch process did not exactly own the expected port"
                                throw $LastFailure
                            }
                            return $LaunchIdentity
                        }

                        $Children = @(Get-DirectChildProcessInfos -ParentProcessId ([int]$LaunchIdentity.PID))
                        $CandidateChildren = @($Children | Where-Object {
                            Test-IsCurrentLitWatchProcess -ProcessInfo $_ -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackBasePython
                        })
                        if ($CandidateChildren.Count -ne 1 -or [int]$CandidateChildren[0].PID -ne [int]$PortOwner.PID) {
                            $LastFailure = "the launcher did not have exactly one direct port-owner child"
                            throw $LastFailure
                        }
                        $ChildCreationTimeUtc = Get-ProcessCreationTimeUtc -ProcessInfo $PortOwner
                        if (
                            [int]$PortOwner.ParentPID -ne [int]$LaunchIdentity.PID -or
                            -not (Test-ProcessCreationLineage -ParentCreationTimeUtc $LaunchIdentity.CreationTimeUtc -ChildCreationTimeUtc $ChildCreationTimeUtc)
                        ) {
                            $LastFailure = "the port owner did not have the expected launch lineage"
                            throw $LastFailure
                        }
                        $PortOwnerIdentity = New-ManagedStackIdentity -ProcessInfo $PortOwner -Port $Port -ExpectedExecutable $script:StackBasePython
                        if (-not (Test-MatchesManagedProcessIdentity -ProcessInfo $CandidateChildren[0] -Identity $PortOwnerIdentity -Port $Port -ExpectedExecutable $script:StackBasePython)) {
                            $LastFailure = "the direct child did not exactly match the port owner"
                            throw $LastFailure
                        }
                        return New-ManagedLauncherChildIdentity -LaunchIdentity $LaunchIdentity -PortOwnerIdentity $PortOwnerIdentity
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
        [AllowNull()][string]$ExpectedStartTimeUtc,
        [ValidateRange(1, 60000)][int]$WaitTimeoutMilliseconds = 5000
    )

    if (-not [string]::IsNullOrWhiteSpace($ExpectedStartTimeUtc)) {
        $CurrentStartTimeUtc = Get-ProcessHandleStartTimeUtc -ProcessHandle $ProcessHandle
        if (
            -not $CurrentStartTimeUtc -or
            -not (Test-ProcessStartTimeMatches -Left $ExpectedStartTimeUtc -Right $CurrentStartTimeUtc)
        ) {
            throw "[LitWatch] Retained process handle creation time changed. Refusing cleanup."
        }
    }
    if ($ProcessHandle.HasExited) {
        return
    }
    $ProcessHandle.Kill()
    if (-not $ProcessHandle.WaitForExit($WaitTimeoutMilliseconds)) {
        throw "[LitWatch] Started process did not exit within $WaitTimeoutMilliseconds milliseconds."
    }
}

function Test-MatchesManagedProcessIdentity {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [Parameter(Mandatory = $true)]$Identity,
        [int]$Port = 8000,
        [string]$ExpectedHost = "127.0.0.1",
        [string]$ExpectedExecutable = $script:StackPython
    )

    if ([int]$ProcessInfo.PID -ne [int]$Identity.PID) {
        return $false
    }
    $CreationTimeUtc = Get-ProcessCreationTimeUtc -ProcessInfo $ProcessInfo
    $Fingerprint = Get-LitWatchProcessFingerprint -ProcessInfo $ProcessInfo -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $ExpectedExecutable
    return (
        $CreationTimeUtc -and
        $Fingerprint -and
        $CreationTimeUtc -ceq [string]$Identity.CreationTimeUtc -and
        $Fingerprint -ceq [string]$Identity.Fingerprint
    )
}

function Test-MatchesManagedStackIdentity {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [Parameter(Mandatory = $true)]$Identity,
        [int]$Port = 8000,
        [string]$ExpectedHost = "127.0.0.1"
    )

    if ([int]$Identity.Version -eq 2) {
        return Test-MatchesManagedProcessIdentity -ProcessInfo $ProcessInfo -Identity $Identity.PortOwnerProcess -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackBasePython
    }
    return Test-MatchesManagedProcessIdentity -ProcessInfo $ProcessInfo -Identity $Identity -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackPython
}

function Format-PortProcessInfo {
    param([Parameter(Mandatory = $true)]$ProcessInfo)

    return "PID=$($ProcessInfo.PID); Created=$($ProcessInfo.CreationDate); Executable=$($ProcessInfo.ExecutablePath); CommandLine=$($ProcessInfo.CommandLine)"
}

function Assert-LitWatchImportPath {
    param([int]$Port = 8000)

    Set-LitWatchRuntimeExecutables -Port $Port

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

. (Join-Path $PSScriptRoot "stack-process-lineage.ps1")
