r"""Schedule today's (or a given day's) live capture from the Liquipedia match list.
usage: python -I tools/schedule_today.py [YYYY-MM-DD] [--dry]
Finds that day's Korean-league matches in data/site/matches.json (run collector/build.mjs first), and registers a
one-shot Windows task 'OWCSKR\LiveCapture' that starts 10 minutes before the first match and runs until 3.5 hours
after the last one (live_capture.py also stops by itself when GAME DATA screens stop for 75 minutes)."""
import datetime, json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
args = [x for x in sys.argv[1:] if not x.startswith('--')]
day = args[0] if args else datetime.date.today().isoformat()
dry = '--dry' in sys.argv

ms = [m for m in json.load(open('data/site/matches.json', encoding='utf-8')) if m['date'].startswith(day) and '/Korea' in m['competitionTitle']]
if not ms:
    print(day, ': no Korean-league matches - nothing scheduled'); sys.exit(0)
ms.sort(key=lambda m: m['date'])
first = datetime.datetime.fromisoformat(ms[0]['date']); last = datetime.datetime.fromisoformat(ms[-1]['date'])
start = (first - datetime.timedelta(minutes=10)).astimezone()        # local time of this PC
hours = round(((last - first).total_seconds() / 3600) + 3.5 + 10 / 60, 1)
print(day, ':', len(ms), 'matches:', ', '.join(f"{datetime.datetime.fromisoformat(m['date']).astimezone():%H:%M} {m['team1']} vs {m['team2']}" for m in ms))
print('capture starts', start.strftime('%Y-%m-%d %H:%M'), 'for up to', hours, 'h')
if dry: sys.exit(0)
if start < datetime.datetime.now().astimezone():
    print('start time already passed - starting the capture now instead')
    subprocess.Popen(['cmd', '/c', os.path.join(ROOT, 'tools', 'run_live.bat'), str(hours), day]); sys.exit(0)
ps = (f"$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c {os.path.join(ROOT, 'tools', 'run_live.bat')} {hours} {day}' -WorkingDirectory '{ROOT}';"
      f"$t = New-ScheduledTaskTrigger -Once -At '{start.strftime('%Y-%m-%dT%H:%M:%S')}';"
      "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 12);"
      r"Register-ScheduledTask -TaskPath '\OWCSKR\' -TaskName 'LiveCapture' -Action $a -Trigger $t -Settings $s -Force | Out-Null; 'registered'")
print(subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True).stdout.strip() or 'registration failed')
