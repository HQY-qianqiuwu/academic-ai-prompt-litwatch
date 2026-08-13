param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "stack-common.ps1")
Set-StackPortPaths -Port $Port

try {
    Set-LitWatchRuntimeExecutables -Port $Port
    $ManagedIdentity = Get-ManagedStackIdentity
    $PortProcesses = @(Get-PortProcessInfo -Port $Port)
    if ($PortProcesses.Count -eq 0) {
        if ($null -ne $ManagedIdentity) {
            $SavedProcess = Get-ProcessInfoById -ProcessId ([int]$ManagedIdentity.PID)
            $SavedPortOwner = if ([int]$ManagedIdentity.Version -eq 2) {
                Get-ProcessInfoById -ProcessId ([int]$ManagedIdentity.PortOwnerProcess.PID)
            }
            else {
                $null
            }
            if ([int]$ManagedIdentity.Version -eq 2 -and $SavedProcess -and -not $SavedPortOwner) {
                Stop-ManagedLaunchProcessWithoutPortOwner -Identity $ManagedIdentity -Port $Port
                Write-Output "LitWatch: stopped PID $($ManagedIdentity.PID)"
                Remove-StackOwnershipRecord -ExpectedRecord $ManagedIdentity
                exit 0
            }
            if ($SavedProcess -or $SavedPortOwner) {
                $Remaining = if ($SavedPortOwner) { $SavedPortOwner } else { $SavedProcess }
                throw "[LitWatch] Managed PID $($ManagedIdentity.PID) is still running but does not own port $Port. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $Remaining)"
            }
            Remove-StackOwnershipRecord -ExpectedRecord $ManagedIdentity
        }
        Write-Output "LitWatch: already stopped"
        exit 0
    }

    if ($null -eq $ManagedIdentity) {
        $Owner = $PortProcesses | Select-Object -First 1
        throw "[Port $Port] Port has no managed PID for the current repository. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $Owner)"
    }
    if (-not (Test-ManagedStackOwnership -Identity $ManagedIdentity -Port $Port -PortProcesses $PortProcesses)) {
        $Owner = $PortProcesses | Select-Object -First 1
        throw "[Port $Port] Port is owned by a process outside this managed LitWatch instance. Refusing to stop it. $(Format-PortProcessInfo -ProcessInfo $Owner)"
    }

    Stop-ManagedLitWatchStack -Identity $ManagedIdentity -Port $Port
    Write-Output "LitWatch: stopped PID $($ManagedIdentity.PID)"
    Remove-StackOwnershipRecord -ExpectedRecord $ManagedIdentity
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
