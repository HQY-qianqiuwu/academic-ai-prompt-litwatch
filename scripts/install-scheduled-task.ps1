Write-Warning "This legacy installer now only registers web startup; subscription scans are scheduled by LitWatch."
& (Join-Path $PSScriptRoot "install-local.ps1") @args
