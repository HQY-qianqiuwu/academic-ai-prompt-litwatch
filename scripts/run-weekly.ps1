param(
    [int]$Days = 14,
    [string]$LitWatchExecutable = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LitWatchExe = if ([string]::IsNullOrWhiteSpace($LitWatchExecutable)) {
    Join-Path $ProjectRoot ".venv\Scripts\litwatch.exe"
}
else {
    $LitWatchExecutable
}
$DataDirectory = Join-Path $ProjectRoot "data"
if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $LogPath = Join-Path $DataDirectory "litwatch-weekly.log"
}

if (-not (Test-Path -LiteralPath $LitWatchExe)) {
    throw "LitWatch environment is missing. Install the project in $ProjectRoot first."
}

New-Item -ItemType Directory -Force -Path $DataDirectory | Out-Null
if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -gt 5MB) {
    Move-Item -LiteralPath $LogPath -Destination ($LogPath + ".previous") -Force
}

$StartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
"[$StartedAt] Weekly scan started (days=$Days)." | Add-Content -LiteralPath $LogPath -Encoding utf8

$PreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    & $LitWatchExe scan --days $Days 2>&1 | ForEach-Object {
        $Line = $_.ToString()
        Write-Output $Line
        $Line | Add-Content -LiteralPath $LogPath -Encoding utf8
    }
    $ScanExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
$FinishedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"

if ($ScanExitCode -ne 0) {
    "[$FinishedAt] Weekly scan failed (exit=$ScanExitCode)." | Add-Content -LiteralPath $LogPath -Encoding utf8
    exit $ScanExitCode
}

"[$FinishedAt] Weekly scan completed." | Add-Content -LiteralPath $LogPath -Encoding utf8
