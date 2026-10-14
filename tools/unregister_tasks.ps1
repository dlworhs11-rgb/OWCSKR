Get-ScheduledTask -TaskPath '\OWCSKR\' -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
Write-Host 'All OWCSKR scheduled tasks removed.'
