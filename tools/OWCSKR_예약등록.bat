@echo off
rem Register the daily OWCSKR job in Windows Task Scheduler (current user, runs only while logged on).
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\dlwor\OWCSKR\tools\register_tasks.ps1"
echo.
echo Daily check at 09:00: refreshes the schedule and starts OBS capture 20 min before the first Korean match.
echo Logs: C:\Users\dlwor\OWCSKR\data\live\daily.log and task.log
pause
