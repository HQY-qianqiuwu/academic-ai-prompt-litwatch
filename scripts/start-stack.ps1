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

$StartedIdentity = $null
$StartedProcessHandle = $null
$StartedProcessStartTimeUtc = $null
try {
    $ImportPath = Assert-LitWatchImportPath -Port $Port
    Write-Output "Migration Mode: python_default"
    Write-Output "Python Runtime: $script:StackPython"
    Write-Output "LitWatch import: $ImportPath"

    $ManagedIdentity = Get-ManagedStackIdentity
    $PortProcesses = @(Get-PortProcessInfo -Port $Port)
    if ($PortProcesses.Count -gt 0) {
        if ($null -eq $ManagedIdentity) {
            $Owner = $PortProcesses | Select-Object -First 1
            throw "[Port $Port] Port has no managed PID for the current repository. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $Owner)"
        }
        foreach ($PortProcess in $PortProcesses) {
            if (-not (Test-MatchesManagedStackIdentity -ProcessInfo $PortProcess -Identity $ManagedIdentity -Port $Port)) {
                throw "[Port $Port] Port is owned by a process outside this managed LitWatch instance. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $PortProcess)"
            }
        }
        Write-Output "LitWatch: already running (PID $($ManagedIdentity.PID))"
    }
    else {
        if ($null -ne $ManagedIdentity) {
            $SavedProcess = Get-ProcessInfoById -ProcessId ([int]$ManagedIdentity.PID)
            if ($SavedProcess) {
                throw "[LitWatch] Managed PID $($ManagedIdentity.PID) is still running but does not own port $Port. Refusing to replace its identity record. $(Format-PortProcessInfo -ProcessInfo $SavedProcess)"
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
        $StartedProcessHandle = Start-Process @StartArguments
        $StartedProcessStartTimeUtc = Get-ProcessHandleStartTimeUtc -ProcessHandle $StartedProcessHandle
        if (-not $StartedProcessStartTimeUtc) {
            throw "[LitWatch] Started process creation time could not be captured safely."
        }
        $StartedIdentity = Wait-StartedLitWatchIdentity -ProcessHandle $StartedProcessHandle -HandleStartTimeUtc $StartedProcessStartTimeUtc -Port $Port
        Set-ManagedStackIdentity -Identity $StartedIdentity
        Write-Output "LitWatch: started PID $($StartedIdentity.PID)"
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
    Write-Output "Migration Verification: ready"
    Write-Output "Python Runtime: ready ($($RuntimeStatus.Detail))"

    $RegistryStatus = Get-OpenAlexRegistryStatus -Port $Port
    if (-not $RegistryStatus.Ready) {
        throw "[Provider Registry] Validation failed: $($RegistryStatus.Detail)"
    }
    Write-Output "Provider Registry: ready ($($RegistryStatus.Detail))"
    Write-Output "Job Worker/Scheduler: ready (active=$($RuntimeStatus.WorkerActive))"

    Write-Output "System: READY"
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:$Port/" | Out-Null
    }
}
catch {
    $OriginalError = $_.Exception.Message
    $CleanupError = $null
    if ($null -ne $StartedProcessHandle -and $null -ne $StartedProcessStartTimeUtc) {
        try {
            Stop-StartedProcessHandle -ProcessHandle $StartedProcessHandle -ExpectedStartTimeUtc $StartedProcessStartTimeUtc
        }
        catch {
            $CleanupError = $_.Exception.Message
        }
    }
    if ($null -ne $StartedIdentity -and -not $CleanupError) {
        if (Test-Path -LiteralPath $script:StackPidPath -PathType Leaf) {
            try {
                $RecordedIdentity = Get-ManagedStackIdentity
                if (
                    $RecordedIdentity.PID -eq $StartedIdentity.PID -and
                    $RecordedIdentity.CreationTimeUtc -ceq $StartedIdentity.CreationTimeUtc -and
                    $RecordedIdentity.Fingerprint -ceq $StartedIdentity.Fingerprint
                ) {
                    Remove-Item -LiteralPath $script:StackPidPath -Force
                }
            }
            catch {
                if (-not $CleanupError) {
                    $CleanupError = $_.Exception.Message
                }
            }
        }
    }
    if ($CleanupError) {
        Write-Error "$OriginalError Cleanup failed safely: $CleanupError"
    }
    else {
        Write-Error $OriginalError
    }
    exit 1
}
