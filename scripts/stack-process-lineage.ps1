function Test-ManagedStackOwnership {
    param(
        [Parameter(Mandatory = $true)]$Identity,
        [int]$Port = 8000,
        $PortProcesses = $null,
        [string]$ExpectedHost = "127.0.0.1"
    )

    if ($null -eq $PortProcesses) {
        $PortProcesses = @(Get-PortProcessInfo -Port $Port)
    }
    else {
        $PortProcesses = @($PortProcesses)
    }
    if ($PortProcesses.Count -ne 1) {
        return $false
    }
    if ([int]$Identity.Version -eq 1) {
        return Test-MatchesManagedProcessIdentity -ProcessInfo $PortProcesses[0] -Identity $Identity -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackPython
    }
    if ($Identity.Topology -cne "launcher_child") {
        return $false
    }
    $LaunchProcess = Get-ProcessInfoById -ProcessId ([int]$Identity.LaunchProcess.PID)
    $PortOwner = $PortProcesses[0]
    if (
        $null -eq $LaunchProcess -or
        -not (Test-MatchesManagedProcessIdentity -ProcessInfo $LaunchProcess -Identity $Identity.LaunchProcess -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackPython) -or
        -not (Test-MatchesManagedProcessIdentity -ProcessInfo $PortOwner -Identity $Identity.PortOwnerProcess -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackBasePython) -or
        [int]$PortOwner.ParentPID -ne [int]$Identity.LaunchProcess.PID -or
        -not (Test-ProcessCreationLineage -ParentCreationTimeUtc $Identity.LaunchProcess.CreationTimeUtc -ChildCreationTimeUtc $Identity.PortOwnerProcess.CreationTimeUtc)
    ) {
        return $false
    }
    $Children = @(Get-DirectChildProcessInfos -ParentProcessId ([int]$Identity.LaunchProcess.PID))
    $CandidateChildren = @($Children | Where-Object {
        Test-IsCurrentLitWatchProcess -ProcessInfo $_ -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackBasePython
    })
    return (
        $CandidateChildren.Count -eq 1 -and
        (Test-MatchesManagedProcessIdentity -ProcessInfo $CandidateChildren[0] -Identity $Identity.PortOwnerProcess -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackBasePython)
    )
}

function Stop-ManagedLitWatchProcess {
    param(
        [Parameter(Mandatory = $true)]$Identity,
        [int]$Port = 8000,
        [string]$ExpectedHost = "127.0.0.1"
    )

    $CurrentProcess = Get-ProcessInfoById -ProcessId ([int]$Identity.PID)
    if (
        -not $CurrentProcess -or
        -not (Test-MatchesManagedStackIdentity -ProcessInfo $CurrentProcess -Identity $Identity -Port $Port -ExpectedHost $ExpectedHost)
    ) {
        throw "[LitWatch] Managed process identity changed before stop. Refusing to stop PID $($Identity.PID)."
    }
    $ProcessHandle = Get-ProcessHandleById -ProcessId ([int]$Identity.PID)
    $HandleStartTimeUtc = Get-ProcessHandleStartTimeUtc -ProcessHandle $ProcessHandle
    if (-not (Test-ProcessStartTimeMatches -Left $HandleStartTimeUtc -Right $Identity.CreationTimeUtc)) {
        throw "[LitWatch] Retained process handle creation identity changed. Refusing cleanup."
    }
    $ImmediateProcess = Get-ProcessInfoById -ProcessId ([int]$Identity.PID)
    if (
        -not $ImmediateProcess -or
        -not (Test-MatchesManagedStackIdentity -ProcessInfo $ImmediateProcess -Identity $Identity -Port $Port -ExpectedHost $ExpectedHost)
    ) {
        throw "[LitWatch] Managed process identity changed immediately before stop. Refusing to stop PID $($Identity.PID)."
    }
    Stop-StartedProcessHandle -ProcessHandle $ProcessHandle -ExpectedStartTimeUtc $Identity.CreationTimeUtc
}

function Stop-ManagedLitWatchStack {
    param(
        [Parameter(Mandatory = $true)]$Identity,
        [int]$Port = 8000,
        [string]$ExpectedHost = "127.0.0.1",
        [ValidateRange(1, 60000)][int]$WaitTimeoutMilliseconds = 5000
    )

    if ([int]$Identity.Version -eq 1) {
        Stop-ManagedLitWatchProcess -Identity $Identity -Port $Port -ExpectedHost $ExpectedHost
        return
    }
    $InitialPortProcesses = @(Get-PortProcessInfo -Port $Port)
    if (-not (Test-ManagedStackOwnership -Identity $Identity -Port $Port -PortProcesses $InitialPortProcesses -ExpectedHost $ExpectedHost)) {
        throw "[LitWatch] Managed process lineage changed before stop. Refusing to stop PID $($Identity.PID)."
    }
    $CapturedChild = Get-ProcessInfoById -ProcessId ([int]$Identity.PortOwnerProcess.PID)
    $CapturedParent = Get-ProcessInfoById -ProcessId ([int]$Identity.LaunchProcess.PID)
    if (
        $null -eq $CapturedChild -or
        $null -eq $CapturedParent -or
        [int]$CapturedChild.ParentPID -ne [int]$Identity.LaunchProcess.PID -or
        -not (Test-MatchesManagedProcessIdentity -ProcessInfo $CapturedChild -Identity $Identity.PortOwnerProcess -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackBasePython) -or
        -not (Test-MatchesManagedProcessIdentity -ProcessInfo $CapturedParent -Identity $Identity.LaunchProcess -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackPython)
    ) {
        throw "[LitWatch] Managed process lineage changed before handle capture. Refusing cleanup."
    }

    $ChildHandle = Get-ProcessHandleById -ProcessId ([int]$Identity.PortOwnerProcess.PID)
    $ParentHandle = Get-ProcessHandleById -ProcessId ([int]$Identity.LaunchProcess.PID)
    $ChildHandleStart = Get-ProcessHandleStartTimeUtc -ProcessHandle $ChildHandle
    $ParentHandleStart = Get-ProcessHandleStartTimeUtc -ProcessHandle $ParentHandle
    if (
        -not (Test-ProcessStartTimeMatches -Left $ChildHandleStart -Right $Identity.PortOwnerProcess.CreationTimeUtc) -or
        -not (Test-ProcessStartTimeMatches -Left $ParentHandleStart -Right $Identity.LaunchProcess.CreationTimeUtc)
    ) {
        throw "[LitWatch] Retained process handle creation identity changed. Refusing cleanup."
    }

    $ImmediatePortProcesses = @(Get-PortProcessInfo -Port $Port)
    $ImmediateChild = Get-ProcessInfoById -ProcessId ([int]$Identity.PortOwnerProcess.PID)
    $ImmediateParent = Get-ProcessInfoById -ProcessId ([int]$Identity.LaunchProcess.PID)
    if (
        $null -eq $ImmediateChild -or
        $null -eq $ImmediateParent -or
        [int]$ImmediateChild.ParentPID -ne [int]$Identity.LaunchProcess.PID -or
        -not (Test-MatchesManagedProcessIdentity -ProcessInfo $ImmediateChild -Identity $Identity.PortOwnerProcess -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackBasePython) -or
        -not (Test-MatchesManagedProcessIdentity -ProcessInfo $ImmediateParent -Identity $Identity.LaunchProcess -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackPython) -or
        -not (Test-ManagedStackOwnership -Identity $Identity -Port $Port -PortProcesses $ImmediatePortProcesses -ExpectedHost $ExpectedHost)
    ) {
        throw "[LitWatch] Managed process lineage changed immediately before stop. Refusing to stop PID $($Identity.PID)."
    }
    Stop-StartedProcessHandle -ProcessHandle $ChildHandle -ExpectedStartTimeUtc $Identity.PortOwnerProcess.CreationTimeUtc -WaitTimeoutMilliseconds $WaitTimeoutMilliseconds

    $RemainingPortProcesses = @(Get-PortProcessInfo -Port $Port)
    if ($RemainingPortProcesses.Count -ne 0) {
        throw "[LitWatch] Port owner survived validated child cleanup. Refusing parent cleanup."
    }
    $CurrentParent = Get-ProcessInfoById -ProcessId ([int]$Identity.LaunchProcess.PID)
    if ($CurrentParent) {
        if (-not (Test-MatchesManagedProcessIdentity -ProcessInfo $CurrentParent -Identity $Identity.LaunchProcess -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackPython)) {
            throw "[LitWatch] Managed launch process identity changed after child cleanup. Refusing parent cleanup."
        }
        Stop-StartedProcessHandle -ProcessHandle $ParentHandle -ExpectedStartTimeUtc $Identity.LaunchProcess.CreationTimeUtc -WaitTimeoutMilliseconds $WaitTimeoutMilliseconds
    }
}

function Stop-ManagedLaunchProcessWithoutPortOwner {
    param(
        [Parameter(Mandatory = $true)]$Identity,
        [int]$Port = 8000,
        [string]$ExpectedHost = "127.0.0.1",
        [ValidateRange(1, 60000)][int]$WaitTimeoutMilliseconds = 5000
    )

    if ([int]$Identity.Version -ne 2 -or $Identity.Topology -cne "launcher_child") {
        throw "[LitWatch] Parent-only cleanup requires a final launcher-child identity."
    }
    if (@(Get-PortProcessInfo -Port $Port).Count -ne 0) {
        throw "[LitWatch] Parent-only cleanup requires an unowned port."
    }
    if (Get-ProcessInfoById -ProcessId ([int]$Identity.PortOwnerProcess.PID)) {
        throw "[LitWatch] Saved port owner still exists without listening. Refusing parent-only cleanup."
    }
    $Parent = Get-ProcessInfoById -ProcessId ([int]$Identity.LaunchProcess.PID)
    if (
        -not $Parent -or
        -not (Test-MatchesManagedProcessIdentity -ProcessInfo $Parent -Identity $Identity.LaunchProcess -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackPython)
    ) {
        throw "[LitWatch] Managed launch process identity changed. Refusing parent-only cleanup."
    }
    $Children = @(Get-DirectChildProcessInfos -ParentProcessId ([int]$Identity.LaunchProcess.PID))
    $CandidateChildren = @($Children | Where-Object {
        Test-IsCurrentLitWatchProcess -ProcessInfo $_ -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackBasePython
    })
    if ($CandidateChildren.Count -ne 0) {
        throw "[LitWatch] A matching direct child remains without listening. Refusing parent-only cleanup."
    }
    $ParentHandle = Get-ProcessHandleById -ProcessId ([int]$Identity.LaunchProcess.PID)
    if (-not (Test-ProcessStartTimeMatches -Left (Get-ProcessHandleStartTimeUtc -ProcessHandle $ParentHandle) -Right $Identity.LaunchProcess.CreationTimeUtc)) {
        throw "[LitWatch] Retained launch handle creation identity changed. Refusing parent-only cleanup."
    }
    $ImmediateParent = Get-ProcessInfoById -ProcessId ([int]$Identity.LaunchProcess.PID)
    $ImmediateChildren = @(Get-DirectChildProcessInfos -ParentProcessId ([int]$Identity.LaunchProcess.PID) | Where-Object {
        Test-IsCurrentLitWatchProcess -ProcessInfo $_ -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackBasePython
    })
    if (
        @(Get-PortProcessInfo -Port $Port).Count -ne 0 -or
        $ImmediateChildren.Count -ne 0 -or
        -not $ImmediateParent -or
        -not (Test-MatchesManagedProcessIdentity -ProcessInfo $ImmediateParent -Identity $Identity.LaunchProcess -Port $Port -ExpectedHost $ExpectedHost -ExpectedExecutable $script:StackPython)
    ) {
        throw "[LitWatch] Parent-only lineage changed immediately before cleanup. Refusing stop."
    }
    Stop-StartedProcessHandle -ProcessHandle $ParentHandle -ExpectedStartTimeUtc $Identity.LaunchProcess.CreationTimeUtc -WaitTimeoutMilliseconds $WaitTimeoutMilliseconds
}
