@echo off
rem Removes every OWCSKR scheduled task except one that is running right now (a capture mid-broadcast): that one is
rem listed with how to stop it, and a second run after it ended removes it too (tools\unregister_tasks.ps1).
set "PS1=%~dp0unregister_tasks.ps1"
if not exist "%PS1%" if defined OWCSKR_ROOT set "PS1=%OWCSKR_ROOT%\tools\unregister_tasks.ps1"
if not exist "%PS1%" set "PS1=C:\Users\dlwor\OWCSKR\tools\unregister_tasks.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
pause
