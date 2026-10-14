@echo off
rem Runs the capture for one broadcast day. Called by the scheduled task OWCSKR\LiveCapture.
rem args: HOURS DATE
cd /d C:\Users\dlwor\OWCSKR
if not exist data\live mkdir data\live
python -I tools\live_capture.py --hours %1 --date %2 >> data\live\task.log 2>&1
