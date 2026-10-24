@echo off
set "PS1=%~dp0unregister_tasks.ps1"
if not exist "%PS1%" set "PS1=%OWCSKR_ROOT%\tools\unregister_tasks.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
pause
