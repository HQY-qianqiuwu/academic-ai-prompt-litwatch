$ErrorActionPreference = "Stop"

foreach ($TaskName in @("LitWatch Web", "LitWatch Weekly Scan", "LitWatch Weekly Radar")) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Removed task: $TaskName"
    }
}

& (Join-Path $PSScriptRoot "stop-local.ps1")
