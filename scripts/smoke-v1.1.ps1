[CmdletBinding()]
param(
    [string]$Topic = "underwater acoustic TDOA localization",
    [ValidateRange(1, 50)]
    [int]$Limit = 10,
    [string]$ContainerName = "docker-worker-1",
    [switch]$SkipDocker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$endpoint = "http://127.0.0.1:8000/api/v1/literature/search"
$requestBody = @{
    topic = $Topic
    limit = $Limit
} | ConvertTo-Json

$hostResponse = Invoke-RestMethod `
    -Method Post `
    -Uri $endpoint `
    -ContentType "application/json" `
    -Body $requestBody `
    -TimeoutSec 90

if ($hostResponse.paper_count -ne @($hostResponse.papers).Count) {
    throw "Host API paper_count does not match papers."
}
if ($hostResponse.paper_count -lt 1) {
    throw "Host API returned no papers."
}

Write-Output "[PASS] Host API returned $($hostResponse.paper_count) papers."

if ($SkipDocker) {
    Write-Output "[SKIP] Docker network test was disabled."
    exit 0
}

$containerId = docker ps --filter "name=^/$ContainerName$" --format "{{.ID}}"
if (-not $containerId) {
    throw "Dify worker container '$ContainerName' is not running."
}

$pythonCode = @'
import json
import os
import urllib.request

payload = json.dumps(
    {
        "topic": os.environ["LITWATCH_SMOKE_TOPIC"],
        "limit": int(os.environ["LITWATCH_SMOKE_LIMIT"]),
    }
).encode()
request = urllib.request.Request(
    "http://host.docker.internal:8000/api/v1/literature/search",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=90) as response:
    result = json.load(response)
    status = response.status

if status != 200:
    raise RuntimeError(f"Unexpected HTTP status: {status}")
if result["paper_count"] != len(result["papers"]):
    raise RuntimeError("Docker API paper_count does not match papers")
if result["paper_count"] < 1:
    raise RuntimeError("Docker API returned no papers")

print(json.dumps({"status": status, "paper_count": result["paper_count"]}))
'@

$encodedPython = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pythonCode))
$pythonRunner = "import base64; exec(base64.b64decode('$encodedPython'))"

$dockerResult = docker exec `
    -e "LITWATCH_SMOKE_TOPIC=$Topic" `
    -e "LITWATCH_SMOKE_LIMIT=$Limit" `
    $ContainerName `
    python -c $pythonRunner

if ($LASTEXITCODE -ne 0) {
    throw "Docker network smoke test failed."
}

$dockerPayload = $dockerResult | ConvertFrom-Json
Write-Output "[PASS] Docker API returned $($dockerPayload.paper_count) papers."
