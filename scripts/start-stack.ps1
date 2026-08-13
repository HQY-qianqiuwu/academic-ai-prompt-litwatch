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
        $Process = Start-Process @StartArguments
        $StartedPid = [int]$Process.Id
        $StartedProcess = Get-ProcessInfoById -ProcessId $StartedPid
        if (-not $StartedProcess) {
            throw "[LitWatch] Started PID $StartedPid could not be identified safely."
        }
        $StartedIdentity = New-ManagedStackIdentity -ProcessInfo $StartedProcess -Port $Port
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
    if ($null -ne $StartedIdentity) {
        Stop-ManagedLitWatchProcess -Identity $StartedIdentity -Port $Port
        if (Test-Path -LiteralPath $script:StackPidPath -PathType Leaf) {
            $RecordedIdentity = Get-ManagedStackIdentity
            if (
                $RecordedIdentity.PID -eq $StartedIdentity.PID -and
                $RecordedIdentity.CreationTimeUtc -ceq $StartedIdentity.CreationTimeUtc -and
                $RecordedIdentity.Fingerprint -ceq $StartedIdentity.Fingerprint
            ) {
                Remove-Item -LiteralPath $script:StackPidPath -Force
            }
        }
    }
    Write-Error $_.Exception.Message
    exit 1
}
