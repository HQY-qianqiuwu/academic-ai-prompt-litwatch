param([int]$Port = 8000)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LitWatchExe = Join-Path $ProjectRoot ".venv\Scripts\litwatch.exe"
$Listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue

if (-not $Listeners) {
    Write-Output "LitWatch is not running."
    exit 0
}

foreach ($Listener in $Listeners) {
    $Process = Get-Process -Id $Listener.OwningProcess -ErrorAction Stop
    $ProcessPath = $Process.Path
    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($Process.Id)"
    $CommandLine = $ProcessInfo.CommandLine
    $IsProjectProcess = $ProcessPath -and $ProcessPath.StartsWith(
        $ProjectRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    )
    $IsLitWatchCommand = $CommandLine -and ($CommandLine.IndexOf(
        $LitWatchExe,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -ge 0)
    if (-not $IsProjectProcess -and -not $IsLitWatchCommand) {
        throw "Port $Port belongs to another program; refusing to stop it: $ProcessPath"
    }
    Stop-Process -Id $Process.Id
    Write-Output "LitWatch stopped (PID $($Process.Id))."
}
