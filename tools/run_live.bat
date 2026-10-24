@echo off
rem Runs the capture for one broadcast day. Called by the scheduled tasks OWCSKR\LiveCapture_YYYY-MM-DD.
rem args: HOURS DATE [URL]   (URL only for tests; default = live embed of owesports)
rem The first start of a day fixes the end time (now + HOURS) in data\live\<DATE>\until.txt; a later start of the
rem same day (after a crash or a reboot) reuses it, so it never extends the day. A day with
rem data\live\<DATE>\summary.txt is finished (its summary went out): a start exits at once.
rem Exit: live_capture.py's code (0 ok, 1 failed, 2 self-check failed, 4 capture ended but its final OCR / publish
rem failed), 0 for a finished or past day, 2 bad arguments / no end time.
setlocal
pushd "%~dp0.."
set "ROOT=%CD%"
popd
if not exist "%ROOT%\tools\live_capture.py" if defined OWCSKR_ROOT set "ROOT=%OWCSKR_ROOT%"
if not defined OWCSKR_SITE_DIR set "OWCSKR_SITE_DIR=C:\Users\dlwor\Documents\Obsidian\LeeJaeGon\02_Projects\OWCS KR Home"
cd /d "%ROOT%"
if "%~2"=="" (
  echo usage: run_live.bat HOURS DATE [URL]
  exit /b 2
)
if not exist data\live mkdir data\live
set "LOG=%ROOT%\data\live\task.log"
rem a reboot or a hand re-run after the summary went out must not capture the finished day again
if exist "data\live\%~2\summary.txt" goto finished
python -I tools\platform_util.py live-until %1 %2 >nul 2>> "%LOG%"
if errorlevel 3 goto dayover
if errorlevel 1 goto nountil
set /p UNTIL=<"data\live\%~2\until.txt"
echo %DATE% %TIME% run_live %2: start (hours %1, until %UNTIL%)>> "%LOG%"
if defined OWCSKR_HC_LIVE curl -fsS -m 10 --retry 3 -o NUL "%OWCSKR_HC_LIVE%/start" >nul 2>&1
rem the site recorders (score / bans / first comps / push) start with the capture, so no match day is missed
call tools\start_watchers.bat >> "%LOG%" 2>&1
set "URLARG="
if not "%~3"=="" set URLARG=--url "%~3"
python -I tools\live_capture.py --until %UNTIL% --date %2 %URLARG% >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo %DATE% %TIME% run_live %2: live_capture exit %RC%>> "%LOG%"
if "%RC%"=="0" goto ok
set "WHY=live_capture.py exit %RC%"
if "%RC%"=="2" set "WHY=live_capture.py exit 2 (self-check failed)"
if "%RC%"=="4" set "WHY=live_capture.py exit 4 (capture ended, final OCR / publish failed)"
python -I tools\notify.py "OWCSKR capture %2" "%WHY% (log: %LOG%)"
if defined OWCSKR_HC_LIVE curl -fsS -m 10 --retry 3 -o NUL "%OWCSKR_HC_LIVE%/fail" >nul 2>&1
rem 4: the broadcast is over all the same, so the replay comment still goes out; any other failure: no comment
rem (the daily job's 'replay_comment.py --post' catches the day later)
if "%RC%"=="4" goto replay
exit /b %RC%
:ok
if defined OWCSKR_HC_LIVE curl -fsS -m 10 --retry 3 -o NUL "%OWCSKR_HC_LIVE%" >nul 2>&1
:replay
rem broadcast over: SOOP timestamp comment as soon as the replay is up (checks every 5 min, up to 6 h; detached so
rem this task can end). replay_comment.py lives with the site files. OWCSKR_PUBLISH=0 (shadow run; python reads
rem .env too): no comment, the machine that publishes posts it.
python -I tools\platform_util.py publish >nul 2>&1
if errorlevel 1 goto nopublish
if exist "%OWCSKR_SITE_DIR%\replay_comment.py" start "" /d "%OWCSKR_SITE_DIR%" pythonw -X utf8 replay_comment.py --wait %2
exit /b %RC%
:nopublish
echo %DATE% %TIME% run_live %2: publish off (OWCSKR_PUBLISH=0) - replay comment not posted>> "%LOG%"
exit /b %RC%
:finished
echo %DATE% %TIME% run_live %2: day already finished (summary sent) - nothing to do>> "%LOG%"
exit /b 0
:dayover
echo %DATE% %TIME% run_live %2: day over (until.txt end time passed) - nothing to do>> "%LOG%"
exit /b 0
:nountil
python -I tools\notify.py "OWCSKR capture %2" "run_live.bat: could not work out the end time (log: %LOG%)"
exit /b 2
