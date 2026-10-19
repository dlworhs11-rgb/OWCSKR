@echo off
rem Runs the capture for one broadcast day. Called by the scheduled tasks OWCSKR\LiveCapture_YYYY-MM-DD.
rem args: HOURS DATE [URL]   (URL only for tests; default = live embed of owesports)
cd /d C:\Users\dlwor\OWCSKR
if not exist data\live mkdir data\live
rem the site recorders (score / bans / first comps / push) start with the capture, so no match day is missed
call tools\start_watchers.bat >> data\live\task.log 2>&1
if "%~3"=="" (
  python -I tools\live_capture.py --hours %1 --date %2 >> data\live\task.log 2>&1
) else (
  python -I tools\live_capture.py --hours %1 --date %2 --url "%~3" >> data\live\task.log 2>&1
)
