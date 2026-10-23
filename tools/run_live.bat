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
rem broadcast over: SOOP timestamp comment as soon as the replay is up (checks every 5 min, up to 6 h; detached so
rem this task can end). replay_comment.py lives with the site files.
start "" /d "C:\Users\dlwor\Documents\Obsidian\LeeJaeGon\02_Projects\OWCS KR Home" pythonw -X utf8 replay_comment.py --wait %2
