$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LitWatchExe = Join-Path $ProjectRoot ".venv\Scripts\litwatch.exe"
$StartScript = Join-Path $PSScriptRoot "start-local.ps1"

if (-not (Test-Path -LiteralPath $LitWatchExe)) {
    throw "Missing $LitWatchExe. Create .venv and install LitWatch first."
}

$PowerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
$WebArguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -NoBrowser' -f $StartScript
$WebAction = New-ScheduledTaskAction `
    -Execute $PowerShellExe `
    -Argument $WebArguments `
    -WorkingDirectory $ProjectRoot
$WebTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$WebSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask `
    -TaskName "LitWatch Web" `
    -Action $WebAction `
    -Trigger $WebTrigger `
    -Settings $WebSettings `
    -Description "Start the local LitWatch web app after Windows logon" `
    -Force | Out-Null

Start-ScheduledTask -TaskName "LitWatch Web"
Write-Output "Installed LitWatch Web logon task."
Write-Output "Subscription scans are scheduled by the LitWatch web service."
Write-Output "Open http://127.0.0.1:8000/"
