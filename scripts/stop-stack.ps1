param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "stack-common.ps1")
Set-StackPortPaths -Port $Port

try {
    $ManagedPid = Get-ManagedStackPid
    $PortProcesses = @(Get-PortProcessInfo -Port $Port)
    if ($PortProcesses.Count -eq 0) {
        if ($null -ne $ManagedPid) {
            $SavedProcess = Get-ProcessInfoById -ProcessId $ManagedPid
            if ($SavedProcess) {
                throw "[LitWatch] Managed PID $ManagedPid is still running but does not own port $Port. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $SavedProcess)"
            }
            Remove-Item -LiteralPath $script:StackPidPath -Force
        }
        Write-Output "LitWatch: already stopped"
        exit 0
    }

    if ($null -eq $ManagedPid) {
        $Owner = $PortProcesses | Select-Object -First 1
        throw "[Port $Port] Port has no managed PID for the current repository. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $Owner)"
    }
    foreach ($PortProcess in $PortProcesses) {
        if (
            $PortProcess.PID -ne $ManagedPid -or
            -not (Test-IsCurrentLitWatchProcess -ProcessInfo $PortProcess -Port $Port)
        ) {
            throw "[Port $Port] Port is owned by a process outside this managed LitWatch instance. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $PortProcess)"
        }
    }

    Stop-Process -Id $ManagedPid -ErrorAction Stop
    Write-Output "LitWatch: stopped PID $ManagedPid"
    Remove-Item -LiteralPath $script:StackPidPath -Force
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
