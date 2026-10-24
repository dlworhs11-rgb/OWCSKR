@echo off
rem Daily job (task OWCSKR\Daily, 09:00): refresh Liquipedia, rebuild data, schedule the capture.
pushd "%~dp0.."
set "ROOT=%CD%"
popd
if not exist "%ROOT%\tools\live_capture.py" if defined OWCSKR_ROOT set "ROOT=%OWCSKR_ROOT%"
if not defined OWCSKR_SITE_DIR set "OWCSKR_SITE_DIR=C:\Users\dlwor\Documents\Obsidian\LeeJaeGon\02_Projects\OWCS KR Home"
if not defined OWCSKR_RECORDERS_DIR set "OWCSKR_RECORDERS_DIR=C:\Users\dlwor\owcs-kr-recorders"
cd /d "%ROOT%"
if not exist data\live mkdir data\live
node collector\run-lp.mjs --active-only >> data\live\daily.log 2>&1
node collector\build.mjs >> data\live\daily.log 2>&1
python -I tools\republish_recent.py >> data\live\daily.log 2>&1
python -I tools\schedule_today.py --upcoming >> data\live\daily.log 2>&1
rem PC-only site files (recorders, admin, handover notes) to the private repo owcs-kr-recorders; skips when unchanged
if exist "%OWCSKR_RECORDERS_DIR%\backup.py" python -I "%OWCSKR_RECORDERS_DIR%\backup.py" >> data\live\daily.log 2>&1
rem SOOP timestamp comments the night run missed (PC off, replay uploaded late)
if not exist "%OWCSKR_SITE_DIR%\replay_comment.py" goto :eof
pushd "%OWCSKR_SITE_DIR%"
python -X utf8 replay_comment.py --post >> "%ROOT%\data\live\daily.log" 2>&1
popd
