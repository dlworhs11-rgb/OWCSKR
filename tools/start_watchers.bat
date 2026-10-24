@echo off
rem Match-day live recorders for the site (series score + POTM, map name / bans / first comps, push to GitHub).
rem Started by run_live.bat (scheduled task OWCSKR\LiveCapture_<date>) so they run every match day without a hand start.
rem Each one is skipped when it is already running. day_end.py stops them all once every match has its POTM on GitHub.
rem match_watch.py --shadow (10-23..25 only): the one-recorder rewrite reads alongside, writes only to data\live\<date>\shadow
rem setlocal: run_live.bat calls this and must keep its own LOG / ROOT
setlocal
pushd "%~dp0.."
set "ROOT=%CD%"
popd
if not exist "%ROOT%\tools\live_capture.py" if defined OWCSKR_ROOT set "ROOT=%OWCSKR_ROOT%"
if not defined OWCSKR_SITE_DIR set "OWCSKR_SITE_DIR=C:\Users\dlwor\Documents\Obsidian\LeeJaeGon\02_Projects\OWCS KR Home"
set "SITE=%OWCSKR_SITE_DIR%"
set "LOG=%ROOT%\data\live"
powershell -NoProfile -Command "$p = (Get-CimInstance Win32_Process -Filter \"name like 'python%%'\").CommandLine; foreach ($s in 'score_watch.py','pick_watch.py','caster_watch.py','live_relay.py','admin_server.py','build_owcs_data.py --watch --push','match_watch.py --shadow','day_end.py') { if (-not ($p -match [regex]::Escape($s))) { $n = ($s -split ' ')[0] -replace '\.py',''; Start-Process cmd.exe -ArgumentList '/c',('python -u ' + $s + ' >> \"%LOG%\' + $n + '.log\" 2>&1') -WorkingDirectory '%SITE%' -WindowStyle Minimized; 'started ' + $s } }"
