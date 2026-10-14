@echo off
rem Daily job (task OWCSKR\Daily, 09:00): refresh Liquipedia, rebuild data, schedule the capture.
cd /d C:\Users\dlwor\OWCSKR
if not exist data\live mkdir data\live
node collector\run-lp.mjs --active-only >> data\live\daily.log 2>&1
node collector\build.mjs >> data\live\daily.log 2>&1
python -I tools\schedule_today.py >> data\live\daily.log 2>&1
