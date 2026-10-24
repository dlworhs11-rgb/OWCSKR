# Removes the OWCSKR scheduled tasks (Daily, and each match day's LiveCapture / MatchdayCheck / SoopQuality /
# Freshness / SiteDispatch). A task that is running right now (State Running: a capture mid-broadcast) is LEFT ALONE,
# registered and running: a capture stopped now loses the rest of the day. They are listed with how to stop them;
# run this again afterwards to remove them too. (Same rule as tools/unregister_tasks.sh on Linux.)
$tasks = @(Get-ScheduledTask -TaskPath '\OWCSKR\' -ErrorAction SilentlyContinue)
$running = @($tasks | Where-Object { "$($_.State)" -eq 'Running' })
$idle = @($tasks | Where-Object { "$($_.State)" -ne 'Running' })
foreach ($t in $idle) {
  Unregister-ScheduledTask -TaskPath '\OWCSKR\' -TaskName $t.TaskName -Confirm:$false
}
if ($running.Count -eq 0) {
  Write-Host ('All OWCSKR scheduled tasks removed ({0}).' -f $idle.Count)
  exit 0
}
Write-Host ('Removed {0} OWCSKR scheduled task(s). Left running (a capture stopped now loses the rest of the day):' -f $idle.Count)
foreach ($t in $running) { Write-Host ('  OWCSKR\' + $t.TaskName) }
Write-Host 'To stop one: Stop-ScheduledTask -TaskPath ''\OWCSKR\'' -TaskName <name>  (or let it end), then run this'
Write-Host 'again to remove it.'
