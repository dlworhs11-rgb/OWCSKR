@echo off
rem Register the daily OWCSKR job in Windows Task Scheduler (current user, runs only while logged on).
rem Works from tools\, from a copy anywhere with OWCSKR_ROOT set, and from a desktop copy on the original PC.
set "PS1=%~dp0register_tasks.ps1"
if not exist "%PS1%" if defined OWCSKR_ROOT set "PS1=%OWCSKR_ROOT%\tools\register_tasks.ps1"
if not exist "%PS1%" set "PS1=C:\Users\dlwor\OWCSKR\tools\register_tasks.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
echo.
echo Daily check at 09:00: refreshes the schedule and starts OBS capture 10 min before the first Korean match.
echo Logs: data\live\daily.log and task.log in the OWCSKR folder
pause
