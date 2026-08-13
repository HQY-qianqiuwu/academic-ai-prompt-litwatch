param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [ValidateRange(1, 600)]
    [int]$LitWatchTimeoutSeconds = 60,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "stack-common.ps1")
Set-StackPortPaths -Port $Port

$StartedPid = $null
try {
    $ImportPath = Assert-LitWatchImportPath
    Write-Output "Migration Mode: python_default"
    Write-Output "Python Runtime: $script:StackPython"
    Write-Output "LitWatch import: $ImportPath"

    $ManagedPid = Get-ManagedStackPid
    $PortProcesses = @(Get-PortProcessInfo -Port $Port)
    if ($PortProcesses.Count -gt 0) {
        if ($null -eq $ManagedPid) {
            $Owner = $PortProcesses | Select-Object -First 1
            throw "[Port $Port] Port has no managed PID for the current repository. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $Owner)"
        }
        foreach ($PortProcess in $PortProcesses) {
            if (
                $PortProcess.PID -ne $ManagedPid -or
                -not (Test-IsCurrentLitWatchProcess -ProcessInfo $PortProcess -Port $Port)
            ) {
                throw "[Port $Port] Port is owned by a process outside this managed LitWatch instance. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $PortProcess)"
            }
        }
        Write-Output "LitWatch: already running (PID $ManagedPid)"
    }
    else {
        if ($null -ne $ManagedPid) {
            $SavedProcess = Get-ProcessInfoById -ProcessId $ManagedPid
            if ($SavedProcess) {
                throw "[LitWatch] Managed PID $ManagedPid is still running but does not own port $Port. Refusing to replace its PID record. $(Format-PortProcessInfo -ProcessInfo $SavedProcess)"
            }
            Remove-Item -LiteralPath $script:StackPidPath -Force
        }

        Write-Output "LitWatch: starting"
        New-Item -ItemType Directory -Force -Path $script:StackDataDirectory | Out-Null
        $Arguments = '-m uvicorn litwatch.web:app --app-dir "{0}" --host 127.0.0.1 --port {1}' -f $script:StackSourceDirectory, $Port
        $StartArguments = @{
            FilePath = $script:StackPython
            ArgumentList = $Arguments
            WorkingDirectory = $script:StackProjectRoot
            WindowStyle = "Hidden"
            RedirectStandardOutput = $script:StackLogPath
            RedirectStandardError = $script:StackErrorLogPath
            PassThru = $true
        }
        $Process = Start-Process @StartArguments
        $StartedPid = [int]$Process.Id
        Set-Content -LiteralPath $script:StackPidPath -Value $StartedPid -Encoding ascii
        Write-Output "LitWatch: started PID $StartedPid"
    }

    $LitWatchReady = Wait-StackCondition -TimeoutSeconds $LitWatchTimeoutSeconds -IntervalSeconds 2 -Condition {
        Test-HttpReady -Url "http://127.0.0.1:$Port/health" -TimeoutSeconds 3
    }
    if (-not $LitWatchReady) {
        throw "[LitWatch] Health check failed. See '$script:StackErrorLogPath'."
    }
    Write-Output "LitWatch: ready"

    $RuntimeStatus = Get-PythonRuntimeStatus -Port $Port
    if (-not $RuntimeStatus.Ready) {
        throw "[Python Runtime] Validation failed: $($RuntimeStatus.Detail)"
    }
    Write-Output "Python Runtime: ready ($($RuntimeStatus.Detail))"

    $RegistryStatus = Get-OpenAlexRegistryStatus -Port $Port
    if (-not $RegistryStatus.Ready) {
        throw "[Provider Registry] Validation failed: $($RegistryStatus.Detail)"
    }
    Write-Output "Provider Registry: ready ($($RegistryStatus.Detail))"
    Write-Output "Job Worker/Scheduler: ready"

    Write-Output "System: READY"
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:$Port/" | Out-Null
    }
}
catch {
    if ($null -ne $StartedPid) {
        $StartedProcess = Get-ProcessInfoById -ProcessId $StartedPid
        if (
            $StartedProcess -and
            $StartedProcess.PID -eq $StartedPid -and
            (Test-IsCurrentLitWatchProcess -ProcessInfo $StartedProcess -Port $Port)
        ) {
            Stop-Process -Id $StartedPid -ErrorAction Stop
        }
        if (Test-Path -LiteralPath $script:StackPidPath -PathType Leaf) {
            $RecordedPid = Get-ManagedStackPid
            if ($RecordedPid -eq $StartedPid) {
                Remove-Item -LiteralPath $script:StackPidPath -Force
            }
        }
    }
    Write-Error $_.Exception.Message
    exit 1
}
