param(
    [string]$TaskName = "LitWatch Weekly Radar",
    [string]$DayOfWeek = "Monday",
    [string]$At = "08:00"
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$UvCommand = Get-Command uv -ErrorAction Stop
$Action = New-ScheduledTaskAction -Execute $UvCommand.Source -Argument "run litwatch scan --days 14 --email" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $DayOfWeek -At $At
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "LitWatch weekly literature scan and email digest"

