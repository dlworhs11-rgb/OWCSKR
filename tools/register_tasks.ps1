# Registers the daily OWCSKR job (09:00). The job refreshes Liquipedia and schedules that day's capture task.
$root = Split-Path -Parent $PSScriptRoot
$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "' + $root + '\tools\run_daily.bat"') -WorkingDirectory $root
$t = New-ScheduledTaskTrigger -Daily -At '09:00'
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskPath '\OWCSKR\' -TaskName 'Daily' -Action $a -Trigger $t -Settings $s -Force | Out-Null
Write-Host 'Registered: OWCSKR\Daily (every day 09:00)'
Write-Host 'Running it once now...'
Start-ScheduledTask -TaskPath '\OWCSKR\' -TaskName 'Daily'
