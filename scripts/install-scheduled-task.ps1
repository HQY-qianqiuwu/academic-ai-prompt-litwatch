param(
    [string]$WeeklyDay = "",
    [string]$WeeklyAt = ""
)

Write-Warning "This legacy installer ignores weekly schedule options and only registers web startup; subscription scans are scheduled by LitWatch."
& (Join-Path $PSScriptRoot "install-local.ps1")
