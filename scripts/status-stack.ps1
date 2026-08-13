param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "stack-common.ps1")
Set-StackPortPaths -Port $Port

$Checks = [ordered]@{
    "Migration Mode" = $true
    "Python Runtime" = $false
    "LitWatch" = $false
    "Provider Registry" = $false
    "Job Worker/Scheduler" = $false
}
$Details = New-Object System.Collections.Generic.List[string]
$Details.Add("Migration Mode: python_default")

try {
    $ManagedPid = Get-ManagedStackPid
    $PortProcesses = @(Get-PortProcessInfo -Port $Port)
    if ($PortProcesses.Count -eq 0) {
        $Details.Add("LitWatch: port $Port is not listening")
    }
    elseif ($null -eq $ManagedPid) {
        foreach ($PortProcess in $PortProcesses) {
            $Details.Add("Port ${Port}: no managed PID; $(Format-PortProcessInfo -ProcessInfo $PortProcess)")
        }
    }
    else {
        $UnexpectedProcesses = @($PortProcesses | Where-Object {
            $_.PID -ne $ManagedPid -or
            -not (Test-IsCurrentLitWatchProcess -ProcessInfo $_ -Port $Port)
        })
        if ($UnexpectedProcesses.Count -gt 0) {
            foreach ($PortProcess in $UnexpectedProcesses) {
                $Details.Add("Port ${Port}: foreign process; $(Format-PortProcessInfo -ProcessInfo $PortProcess)")
            }
        }
        else {
            $Checks.LitWatch = Test-HttpReady -Url "http://127.0.0.1:$Port/health" -TimeoutSeconds 5
            if (-not $Checks.LitWatch) {
                $Details.Add("LitWatch: health check failed")
            }
        }
    }
}
catch {
    $Details.Add($_.Exception.Message)
}

if ($Checks.LitWatch) {
    $RuntimeStatus = Get-PythonRuntimeStatus -Port $Port
    $Checks["Python Runtime"] = $RuntimeStatus.Ready
    if (-not $RuntimeStatus.Ready) {
        $Details.Add("Python Runtime: $($RuntimeStatus.Detail)")
    }

    $RegistryStatus = Get-OpenAlexRegistryStatus -Port $Port
    $Checks["Provider Registry"] = $RegistryStatus.Ready
    if (-not $RegistryStatus.Ready) {
        $Details.Add("Provider Registry: $($RegistryStatus.Detail)")
    }

    $Checks["Job Worker/Scheduler"] = $RuntimeStatus.Ready
    if (-not $Checks["Job Worker/Scheduler"]) {
        $Details.Add("Job Worker/Scheduler: application runtime validation failed")
    }
}

foreach ($Name in $Checks.Keys) {
    $Result = if ($Checks[$Name]) { "PASS" } else { "FAIL" }
    Write-Output ("{0,-24}{1}" -f $Name, $Result)
}

$SystemReady = -not ($Checks.Values -contains $false)
Write-Output ""
Write-Output ("{0,-24}{1}" -f "System", $(if ($SystemReady) { "READY" } else { "NOT READY" }))
if ($Details.Count -gt 0) {
    Write-Output ""
    foreach ($Detail in $Details) {
        Write-Output "- $Detail"
    }
}

if (-not $SystemReady) {
    exit 1
}
