param(
    [int]$DockerTimeoutSeconds = 120,
    [int]$DifyTimeoutSeconds = 120,
    [int]$LitWatchTimeoutSeconds = 60,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "stack-common.ps1")

try {
    $DockerCommand = Get-DockerCommand
    Write-Output "Docker CLI: $($DockerCommand.Source)"

    if (-not (Test-DockerDaemon -DockerCommand $DockerCommand)) {
        Write-Output "Docker Desktop is not running."
        $DockerDesktop = Find-DockerDesktopExecutable -DockerCommand $DockerCommand
        if (-not $DockerDesktop) {
            throw "[Docker] Docker Desktop is not running and its executable could not be located. Start Docker Desktop manually."
        }
        Write-Output "Docker: starting $DockerDesktop"
        Start-Process -FilePath $DockerDesktop -WindowStyle Hidden | Out-Null
        $DockerReady = Wait-StackCondition -TimeoutSeconds $DockerTimeoutSeconds -IntervalSeconds 3 -Condition {
            Test-DockerDaemon -DockerCommand $DockerCommand
        }
        if (-not $DockerReady) {
            throw "[Docker] Docker daemon did not become ready within $DockerTimeoutSeconds seconds."
        }
        Write-Output "Docker: ready"
    }
    else {
        Write-Output "Docker: already running"
    }

    $DifyDockerDirectory = Resolve-DifyDockerDirectory
    Write-Output "Dify compose: $DifyDockerDirectory"
    $DifyWasReady = Test-HttpReady -Url "http://localhost" -TimeoutSeconds 5
    if ($DifyWasReady) {
        Write-Output "Dify: already running"
    }
    else {
        Write-Output "Dify: starting"
    }

    Push-Location $DifyDockerDirectory
    try {
        & docker compose up -d
        if ($LASTEXITCODE -ne 0) {
            throw "[Dify] docker compose up -d failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }

    $DifyReady = Wait-StackCondition -TimeoutSeconds $DifyTimeoutSeconds -IntervalSeconds 3 -Condition {
        Test-HttpReady -Url "http://localhost" -TimeoutSeconds 5
    }
    if (-not $DifyReady) {
        throw "[Dify] http://localhost did not become ready within $DifyTimeoutSeconds seconds."
    }
    Write-Output "Dify: ready"

    if (-not (Test-ComposeServiceRunning -DifyDockerDirectory $DifyDockerDirectory -Service "ssrf_proxy")) {
        throw "[SSRF Proxy] Dify service 'ssrf_proxy' is missing or not running."
    }
    Write-Output "SSRF Proxy: running"

    $ImportPath = Assert-LitWatchImportPath
    Write-Output "LitWatch import: $ImportPath"

    $PortProcesses = @(Get-PortProcessInfo -Port 8000)
    if ($PortProcesses.Count -gt 0) {
        foreach ($PortProcess in $PortProcesses) {
            if (-not (Test-IsCurrentLitWatchProcess -ProcessInfo $PortProcess -Port 8000)) {
                throw "[Port 8000] Port is owned by a process outside the current LitWatch repository. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $PortProcess)"
            }
        }
        Write-Output "LitWatch: already running"
    }
    else {
        Write-Output "LitWatch: starting"
        New-Item -ItemType Directory -Force -Path $script:StackDataDirectory | Out-Null
        $Arguments = '-m uvicorn litwatch.web:app --app-dir "{0}" --host 0.0.0.0 --port 8000' -f $script:StackSourceDirectory
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
        Set-Content -LiteralPath $script:StackPidPath -Value $Process.Id -Encoding ascii
    }

    $LitWatchReady = Wait-StackCondition -TimeoutSeconds $LitWatchTimeoutSeconds -IntervalSeconds 2 -Condition {
        Test-HttpReady -Url "http://127.0.0.1:8000/health" -TimeoutSeconds 3
    }
    if (-not $LitWatchReady) {
        throw "[LitWatch] Health check failed. See '$script:StackErrorLogPath'."
    }
    Write-Output "LitWatch: ready"

    $RegistryStatus = Get-OpenAlexRegistryStatus
    if (-not $RegistryStatus.Ready) {
        throw "[LitWatch] Provider Registry validation failed: $($RegistryStatus.Detail)"
    }
    Write-Output "OpenAlex: runnable=true"

    Write-Output "System: READY"
    if (-not $NoBrowser) {
        Start-Process "http://localhost" | Out-Null
    }
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
