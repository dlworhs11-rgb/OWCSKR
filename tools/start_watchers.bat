@echo off
rem Match-day live recorders for the site (series score + POTM, map name / bans / first comps, push to GitHub).
rem Started by run_live.bat (scheduled task OWCSKR\LiveCapture_<date>) so they run every match day without a hand start.
rem Each one is skipped when it is already running.
rem match_watch.py --shadow (10-23..25 only): the one-recorder rewrite reads alongside, writes only to data\live\<date>\shadow
set SITE=C:\Users\dlwor\Documents\Obsidian\LeeJaeGon\02_Projects\OWCS KR Home
set LOG=C:\Users\dlwor\OWCSKR\data\live
powershell -NoProfile -Command "$p = (Get-CimInstance Win32_Process -Filter \"name like 'python%%'\").CommandLine; foreach ($s in 'score_watch.py','pick_watch.py','caster_watch.py','live_relay.py','admin_server.py','build_owcs_data.py --watch --push','match_watch.py --shadow') { if (-not ($p -match [regex]::Escape($s))) { $n = ($s -split ' ')[0] -replace '\.py',''; Start-Process cmd.exe -ArgumentList '/c',('python -u ' + $s + ' >> \"%LOG%\' + $n + '.log\" 2>&1') -WorkingDirectory '%SITE%' -WindowStyle Minimized; 'started ' + $s } }"
