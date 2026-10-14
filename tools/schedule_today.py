r"""Schedule today's (or a given day's) live capture from the Liquipedia match list.
usage: python -I tools/schedule_today.py [YYYY-MM-DD | --upcoming] [--dry]
Finds that day's Korean-league matches in data/site/matches.json (run collector/build.mjs first), and registers a
one-shot Windows task 'OWCSKR\LiveCapture' that starts 10 minutes before the first match and runs until 3.5 hours
after the last one (live_capture.py also stops by itself when GAME DATA screens stop for 75 minutes)."""
import datetime, json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
args = [x for x in sys.argv[1:] if not x.startswith('--')]
dry = '--dry' in sys.argv
ALL = json.load(open('data/site/matches.json', encoding='utf-8'))


def plan(day):
    ms = sorted([m for m in ALL if m['date'].startswith(day) and '/Korea' in m['competitionTitle']], key=lambda m: m['date'])
    if not ms: return None
    first = datetime.datetime.fromisoformat(ms[0]['date']); last = datetime.datetime.fromisoformat(ms[-1]['date'])
    start = (first - datetime.timedelta(minutes=10)).astimezone()        # local time of this PC
    hours = round(((last - first).total_seconds() / 3600) + 3.5 + 10 / 60, 1)
    return ms, start, hours


def register(day, start, hours):
    ps = (f"$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c {os.path.join(ROOT, 'tools', 'run_live.bat')} {hours} {day}' -WorkingDirectory '{ROOT}';"
          f"$t = New-ScheduledTaskTrigger -Once -At '{start.strftime('%Y-%m-%dT%H:%M:%S')}';"
          "$s = New-ScheduledTaskSettingsSet -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 12);"
          rf"Register-ScheduledTask -TaskPath '\OWCSKR' -TaskName 'LiveCapture_{day}' -Action $a -Trigger $t -Settings $s -Force | Out-Null; 'registered'")
    return subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True).stdout.strip() or 'registration failed'


def cleanup(today):
    """remove capture tasks of past days (and the old single 'LiveCapture' task)"""
    ps = (r"Get-ScheduledTask -TaskPath '\OWCSKR\' -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -eq 'LiveCapture' -or "
          f"($_.TaskName -like 'LiveCapture_*' -and $_.TaskName.Substring(12) -lt '{today}') }} | Unregister-ScheduledTask -Confirm:$false")
    subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True)


today = datetime.date.today()
if '--upcoming' in sys.argv:            # every match day in the next 14 days, each with its own task
    days = [(today + datetime.timedelta(d)).isoformat() for d in range(15)]
    if not dry: cleanup(today.isoformat())
else:
    days = [args[0] if args else today.isoformat()]
for day in days:
    p = plan(day)
    if not p:
        if '--upcoming' not in sys.argv: print(day, ': no Korean-league matches - nothing scheduled')
        continue
    ms, start, hours = p
    print(day, ':', len(ms), 'matches, first', f"{datetime.datetime.fromisoformat(ms[0]['date']).astimezone():%H:%M}", '-> capture', start.strftime('%m-%d %H:%M'), f'(up to {hours} h)', end=' ')
    if dry: print(); continue
    if start < datetime.datetime.now().astimezone():
        if datetime.datetime.now().astimezone() < start + datetime.timedelta(hours=hours):
            print('-> already started time, launching now')
            subprocess.Popen(['cmd', '/c', os.path.join(ROOT, 'tools', 'run_live.bat'), str(hours), day])
        else: print('-> past')
        continue
    print('->', register(day, start, hours))
