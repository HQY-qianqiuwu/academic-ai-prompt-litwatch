param([int]$Port = 8000)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "stack-common.ps1")

$Checks = [ordered]@{
    Docker = $false
    Dify = $false
    LitWatch = $false
    OpenAlex = $false
    "SSRF Proxy" = $false
}
$Details = New-Object System.Collections.Generic.List[string]

try {
    $DockerCommand = Get-DockerCommand
    $Checks.Docker = Test-DockerDaemon -DockerCommand $DockerCommand
    if (-not $Checks.Docker) {
        $Details.Add("Docker: daemon is not running")
    }
}
catch {
    $Details.Add($_.Exception.Message)
}

$DifyDockerDirectory = $null
try {
    $DifyDockerDirectory = Resolve-DifyDockerDirectory
    if ($Checks.Docker) {
        $Checks.Dify = Test-HttpReady -Url "http://localhost" -TimeoutSeconds 5
        $Checks["SSRF Proxy"] = Test-ComposeServiceRunning -DifyDockerDirectory $DifyDockerDirectory -Service "ssrf_proxy"
        if (-not $Checks.Dify) {
            $Details.Add("Dify: http://localhost is not ready")
        }
        if (-not $Checks["SSRF Proxy"]) {
            $Details.Add("SSRF Proxy: container is missing or stopped")
        }
    }
}
catch {
    $Details.Add($_.Exception.Message)
}

$PortProcesses = @(Get-PortProcessInfo -Port $Port)
if ($PortProcesses.Count -eq 0) {
    $Details.Add("LitWatch: port $Port is not listening")
}
else {
    $CurrentProcesses = @($PortProcesses | Where-Object {
        Test-IsCurrentLitWatchProcess -ProcessInfo $_ -Port $Port
    })
    if ($CurrentProcesses.Count -ne $PortProcesses.Count) {
        foreach ($PortProcess in $PortProcesses | Where-Object {
            -not (Test-IsCurrentLitWatchProcess -ProcessInfo $_ -Port $Port)
        }) {
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

if ($Checks.LitWatch) {
    $RegistryStatus = Get-OpenAlexRegistryStatus
    $Checks.OpenAlex = $RegistryStatus.Ready
    if (-not $Checks.OpenAlex) {
        $Details.Add("OpenAlex: $($RegistryStatus.Detail)")
    }
}

foreach ($Name in $Checks.Keys) {
    $Result = if ($Checks[$Name]) { "PASS" } else { "FAIL" }
    Write-Output ("{0,-16}{1}" -f $Name, $Result)
}

$SystemReady = -not ($Checks.Values -contains $false)
Write-Output ""
Write-Output ("{0,-16}{1}" -f "System", $(if ($SystemReady) { "READY" } else { "NOT READY" }))
if ($Details.Count -gt 0) {
    Write-Output ""
    foreach ($Detail in $Details) {
        Write-Output "- $Detail"
    }
}

if (-not $SystemReady) {
    exit 1
}
