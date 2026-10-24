@echo off
rem Daily job (task OWCSKR\Daily, 09:00): find new Liquipedia pages, refresh Liquipedia, rebuild data, schedule the
rem captures and the match-day checks, check that the site is fresh. Every step runs even when an earlier one
rem failed; the failures go out as one alert (tools\notify.py) at the end. Exit 1 when a step failed (warnings -
rem some Liquipedia pages, the freshness check - only alert). Healthcheck ping: OWCSKR_HC_DAILY when set.
setlocal
pushd "%~dp0.."
set "ROOT=%CD%"
popd
if not exist "%ROOT%\tools\live_capture.py" if defined OWCSKR_ROOT set "ROOT=%OWCSKR_ROOT%"
if not defined OWCSKR_SITE_DIR set "OWCSKR_SITE_DIR=C:\Users\dlwor\Documents\Obsidian\LeeJaeGon\02_Projects\OWCS KR Home"
if not defined OWCSKR_RECORDERS_DIR set "OWCSKR_RECORDERS_DIR=C:\Users\dlwor\owcs-kr-recorders"
cd /d "%ROOT%"
if not exist data\live mkdir data\live
set "LOG=%ROOT%\data\live\daily.log"
set "FAILED="
set "WARNED="
echo === %DATE% %TIME% daily>> "%LOG%"
node collector\run-lp.mjs --discover --strict >> "%LOG%" 2>&1
call :lp run-lp-discover %ERRORLEVEL%
node collector\run-lp.mjs --active-only --strict >> "%LOG%" 2>&1
call :lp run-lp %ERRORLEVEL%
node collector\build.mjs >> "%LOG%" 2>&1
if errorlevel 1 set "FAILED=%FAILED% build.mjs"
python -I tools\republish_recent.py >> "%LOG%" 2>&1
if errorlevel 1 set "FAILED=%FAILED% republish_recent"
python -I tools\schedule_today.py --upcoming >> "%LOG%" 2>&1
if errorlevel 1 set "FAILED=%FAILED% schedule_today"
rem PC-only site files (recorders, admin, handover notes) to the private repo owcs-kr-recorders; skips when unchanged
if not exist "%OWCSKR_RECORDERS_DIR%\backup.py" goto replay
python -I "%OWCSKR_RECORDERS_DIR%\backup.py" >> "%LOG%" 2>&1
if errorlevel 1 set "FAILED=%FAILED% backup"
:replay
rem SOOP timestamp comments the night run missed (PC off, replay uploaded late)
if not exist "%OWCSKR_SITE_DIR%\replay_comment.py" goto fresh
pushd "%OWCSKR_SITE_DIR%"
python -X utf8 replay_comment.py --post >> "%LOG%" 2>&1
if errorlevel 1 set "FAILED=%FAILED% replay_comment"
popd
:fresh
python -I tools\healthcheck.py --quiet >> "%LOG%" 2>&1
if errorlevel 1 set "WARNED=%WARNED% site-freshness"
if not defined FAILED if not defined WARNED goto done
echo %DATE% %TIME% daily: failed:%FAILED% warnings:%WARNED%>> "%LOG%"
python -I tools\notify.py "OWCSKR daily job" "failed:%FAILED%  warnings:%WARNED%  (log: %LOG%)"
:done
if not defined FAILED goto ok
if defined OWCSKR_HC_DAILY curl -fsS -m 10 --retry 3 -o NUL "%OWCSKR_HC_DAILY%/fail" >nul 2>&1
exit /b 1
:ok
if defined OWCSKR_HC_DAILY curl -fsS -m 10 --retry 3 -o NUL "%OWCSKR_HC_DAILY%" >nul 2>&1
exit /b 0

rem :lp NAME EXITCODE - the collector's exit codes: 2 = some pages failed (old copies kept) is a warning
:lp
if "%~2"=="0" exit /b 0
if "%~2"=="2" (set "WARNED=%WARNED% %~1") else (set "FAILED=%FAILED% %~1")
exit /b 0
