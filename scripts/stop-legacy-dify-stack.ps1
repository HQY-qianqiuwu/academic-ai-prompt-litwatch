param([int]$Port = 8000)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "stack-common.ps1")

try {
    $PortProcesses = @(Get-PortProcessInfo -Port $Port)
    if ($PortProcesses.Count -eq 0) {
        Write-Output "LitWatch: already stopped"
    }
    else {
        foreach ($PortProcess in $PortProcesses) {
            if (-not (Test-IsCurrentLitWatchProcess -ProcessInfo $PortProcess -Port $Port)) {
                throw "[Port $Port] Port is owned by a process outside the current LitWatch repository. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $PortProcess)"
            }
        }
        foreach ($PortProcess in $PortProcesses) {
            Stop-Process -Id $PortProcess.PID -ErrorAction Stop
            Write-Output "LitWatch: stopped PID $($PortProcess.PID)"
        }
        if (Test-Path -LiteralPath $script:StackPidPath) {
            Remove-Item -LiteralPath $script:StackPidPath -Force
        }
    }

    $DifyDockerDirectory = Resolve-DifyDockerDirectory
    $DockerCommand = Get-DockerCommand
    if (-not (Test-DockerDaemon -DockerCommand $DockerCommand)) {
        Write-Output "Docker: daemon is not running; Dify containers are already unavailable."
        exit 0
    }

    Push-Location $DifyDockerDirectory
    try {
        & docker compose stop
        if ($LASTEXITCODE -ne 0) {
            throw "[Dify] docker compose stop failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
    Write-Output "Dify: stopped (volumes preserved)"
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
