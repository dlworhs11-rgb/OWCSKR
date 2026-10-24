@echo off
rem OWCSKR: start OBS (tray, dedicated scene collection) with a SOOP page and take 6 test captures.
pushd "%~dp0.."
set "ROOT=%CD%"
popd
if not exist "%ROOT%\tools\live_capture.py" if defined OWCSKR_ROOT set "ROOT=%OWCSKR_ROOT%"
if not exist "%ROOT%\tools\live_capture.py" set "ROOT=C:\Users\dlwor\OWCSKR"
cd /d "%ROOT%"
set "URL=%~1"
if "%URL%"=="" set "URL=https://vod.sooplive.com/player/209539901?change_second=3440"
echo [1/2] Starting OBS and preparing the scene...
python -I tools\obs_setup.py start "%URL%"
if errorlevel 1 goto fail
echo [2/2] Waiting 20 s, then 6 captures every 10 s...
timeout /t 20 >nul
python -I tools\obs_snap.py 6 10
if errorlevel 1 goto fail
echo.
echo DONE. Report: %ROOT%\data\live\snap_report.txt
pause
exit /b 0
:fail
echo FAILED. Please send a screenshot of this window.
pause
exit /b 1
