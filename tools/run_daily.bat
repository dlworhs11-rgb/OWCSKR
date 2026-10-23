@echo off
rem Daily job (task OWCSKR\Daily, 09:00): refresh Liquipedia, rebuild data, schedule the capture.
cd /d C:\Users\dlwor\OWCSKR
if not exist data\live mkdir data\live
node collector\run-lp.mjs --active-only >> data\live\daily.log 2>&1
node collector\build.mjs >> data\live\daily.log 2>&1
python -I tools\republish_recent.py >> data\live\daily.log 2>&1
python -I tools\schedule_today.py --upcoming >> data\live\daily.log 2>&1
rem PC-only site files (recorders, admin, handover notes) to the private repo owcs-kr-recorders; skips when unchanged
python -I C:\Users\dlwor\owcs-kr-recorders\backup.py >> data\live\daily.log 2>&1
rem SOOP timestamp comments the night run missed (PC off, replay uploaded late)
pushd "C:\Users\dlwor\Documents\Obsidian\LeeJaeGon\02_Projects\OWCS KR Home"
python -X utf8 replay_comment.py --post >> C:\Users\dlwor\OWCSKR\data\live\daily.log 2>&1
popd
