param(
    [string]$DifyRoot = "",
    [switch]$RestartProxy
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ExpectedVersion = "1.16.1"
$PatchPath = Join-Path $ProjectRoot "integrations\dify\1.16.1\litwatch-ssrf.patch"

try {
    if ([string]::IsNullOrWhiteSpace($DifyRoot)) {
        $DifyRoot = Join-Path (Split-Path $ProjectRoot -Parent) "dify"
    }
    if (-not (Test-Path -LiteralPath $DifyRoot -PathType Container)) {
        throw "Dify repository was not found: $DifyRoot"
    }
    $DifyRoot = (Resolve-Path -LiteralPath $DifyRoot).Path

    $VersionFile = Join-Path $DifyRoot "web\package.json"
    $TargetFile = Join-Path $DifyRoot "docker\ssrf_proxy\squid.conf.template"
    $ComposeDirectory = Join-Path $DifyRoot "docker"
    foreach ($RequiredFile in @($VersionFile, $TargetFile, $PatchPath)) {
        if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
            throw "Required file is missing: $RequiredFile"
        }
    }

    $DifyVersion = (Get-Content -LiteralPath $VersionFile -Raw | ConvertFrom-Json).version
    if ($DifyVersion -ne $ExpectedVersion) {
        throw "Unsupported Dify version '$DifyVersion'. This integration is locked to $ExpectedVersion."
    }

    $TargetContent = Get-Content -LiteralPath $TargetFile -Raw
    $RequiredMarkers = @(
        "acl litwatch_local_dev_host dstdomain host.docker.internal",
        "acl litwatch_local_dev_port port 8000",
        "http_access allow client_localnet litwatch_local_dev_host litwatch_local_dev_port"
    )
    $PresentMarkers = @($RequiredMarkers | Where-Object { $TargetContent.Contains($_) })

    if ($PresentMarkers.Count -eq $RequiredMarkers.Count) {
        Write-Output "Dify SSRF integration: already applied"
    }
    elseif ($PresentMarkers.Count -gt 0) {
        throw "Partial LitWatch SSRF integration detected. Refusing to modify the Squid configuration."
    }
    else {
        & git -C $DifyRoot apply --check --whitespace=nowarn $PatchPath
        if ($LASTEXITCODE -ne 0) {
            throw "The Dify 1.16.1 SSRF patch does not apply cleanly. No files were changed."
        }
        & git -C $DifyRoot apply --whitespace=nowarn $PatchPath
        if ($LASTEXITCODE -ne 0) {
            throw "Applying the Dify SSRF patch failed."
        }
        Write-Output "Dify SSRF integration: applied"
    }

    $VerifiedContent = Get-Content -LiteralPath $TargetFile -Raw
    foreach ($Marker in $RequiredMarkers) {
        if (-not $VerifiedContent.Contains($Marker)) {
            throw "Post-apply verification failed for marker: $Marker"
        }
    }

    if ($RestartProxy) {
        $DockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
        if (-not $DockerCommand) {
            throw "Docker CLI was not found; the patch is present but ssrf_proxy was not restarted."
        }
        Push-Location $ComposeDirectory
        try {
            & docker compose up -d --no-deps --force-recreate ssrf_proxy
            if ($LASTEXITCODE -ne 0) {
                throw "Restarting the Dify ssrf_proxy service failed."
            }
            $ProxyJson = & docker compose ps --format json ssrf_proxy | ConvertFrom-Json
            if (-not $ProxyJson -or $ProxyJson.State -ne "running") {
                throw "Dify ssrf_proxy did not reach the running state."
            }
        }
        finally {
            Pop-Location
        }
        Write-Output "Dify SSRF proxy: restarted"
    }

    Write-Output "Allowed target: host.docker.internal:8000"
    Write-Output "Other private targets remain behind the default Squid deny rule."
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
