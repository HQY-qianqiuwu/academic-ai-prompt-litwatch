param(
    [int]$Port = 8000,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LitWatchExe = Join-Path $ProjectRoot ".venv\Scripts\litwatch.exe"
$DataDirectory = Join-Path $ProjectRoot "data"
$LogPath = Join-Path $DataDirectory "litwatch-web.log"
$ErrorLogPath = Join-Path $DataDirectory "litwatch-web-error.log"
$Url = "http://127.0.0.1:$Port/"

if (-not (Test-Path -LiteralPath $LitWatchExe)) {
    throw "LitWatch environment is missing. Install the project in $ProjectRoot first."
}

New-Item -ItemType Directory -Force -Path $DataDirectory | Out-Null
$Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $Listener) {
    Start-Process `
        -FilePath $LitWatchExe `
        -ArgumentList @("serve", "--host", "127.0.0.1", "--port", "$Port") `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $LogPath `
        -RedirectStandardError $ErrorLogPath

    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        try {
            $Response = Invoke-WebRequest -UseBasicParsing -Uri ($Url + "health") -TimeoutSec 2
            if ($Response.StatusCode -eq 200) {
                $Ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $Ready) {
        throw "LitWatch failed to start. Check $ErrorLogPath"
    }
}

if (-not $NoBrowser) {
    Start-Process $Url
}

Write-Output "LitWatch is running: $Url"
