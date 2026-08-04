param(
    [int]$Days = 14
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LitWatchExe = Join-Path $ProjectRoot ".venv\Scripts\litwatch.exe"
$DataDirectory = Join-Path $ProjectRoot "data"
$LogPath = Join-Path $DataDirectory "litwatch-weekly.log"

if (-not (Test-Path -LiteralPath $LitWatchExe)) {
    throw "LitWatch environment is missing. Install the project in $ProjectRoot first."
}

New-Item -ItemType Directory -Force -Path $DataDirectory | Out-Null
if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -gt 5MB) {
    Move-Item -LiteralPath $LogPath -Destination ($LogPath + ".previous") -Force
}

$StartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
"[$StartedAt] Weekly scan started (days=$Days)." | Add-Content -LiteralPath $LogPath -Encoding utf8

& $LitWatchExe scan --days $Days 2>&1 | Tee-Object -FilePath $LogPath -Append
$ScanExitCode = $LASTEXITCODE
$FinishedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"

if ($ScanExitCode -ne 0) {
    "[$FinishedAt] Weekly scan failed (exit=$ScanExitCode)." | Add-Content -LiteralPath $LogPath -Encoding utf8
    exit $ScanExitCode
}

"[$FinishedAt] Weekly scan completed." | Add-Content -LiteralPath $LogPath -Encoding utf8
