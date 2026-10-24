r"""Schedule today's (or a given day's) live capture from the Liquipedia match list.
usage: python -I tools/schedule_today.py [YYYY-MM-DD | --upcoming] [--dry]
Finds that day's Korean-league matches in data/site/matches.json (run collector/build.mjs first), and registers a
one-shot job that starts 10 minutes before the first match and runs until 3.5 hours after the last one
(live_capture.py also stops by itself when GAME DATA screens stop for 75 minutes):
  Windows: Task Scheduler task 'OWCSKR\LiveCapture_<date>' running tools/run_live.bat
  Linux:   systemd user timer 'owcskr-live-<date>' (systemd-run) running tools/run_live.sh"""
import datetime, json, os, re, subprocess, sys
import sys as _sys; _sys.stdout.reconfigure(encoding='utf-8', errors='replace'); _sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # logs may contain names like 'Esperança'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from platform_util import IS_WIN
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
args = [x for x in sys.argv[1:] if not x.startswith('--')]
dry = '--dry' in sys.argv
ALL = json.load(open('data/site/matches.json', encoding='utf-8'))
DAY_START = {4: '17:00', 5: '15:00', 6: '15:00'}   # usual first-match time per weekday (same as owcs_build.py)


def playoff_matches(day):
    """playoff / seeding-decider matches of that day from the stage's Liquipedia page (data/lp/*-korea.json).
    site/matches.json drops matches whose teams are still TBD, which is every playoff match until the round before
    is over, so the capture of a playoff day would never get scheduled. A match without a start time comes as 00:00 KST:
    it gets the usual first-match time of that weekday (re-registered each morning once Liquipedia has the time).
    Liquipedia writes 'bestof' only on a round's first match: the rest of the round carries it over."""
    out = []
    for f in sorted(os.listdir('data/lp')):
        if not f.endswith('-korea.json'):
            continue
        bo = None
        for m in json.load(open(os.path.join('data/lp', f), encoding='utf-8')).get('matches', []):
            bo = m.get('bestof') or bo
            m = dict(m, bestof=bo)
            d = m.get('date') or ''
            if not d.startswith(day):
                continue
            dt = datetime.datetime.fromisoformat(d)
            if dt.strftime('%H:%M') == '00:00':
                h, mi = map(int, DAY_START.get(dt.weekday(), '19:00').split(':'))
                dt = dt.replace(hour=h, minute=mi)
                m = dict(m, guessed=True)
            out.append(dict(m, date=dt.isoformat()))
    return out


def plan(day):
    ms = [m for m in ALL if m['date'].startswith(day) and '/Korea' in m['competitionTitle']]
    seen = {m['date'] for m in ms}
    ms += [m for m in playoff_matches(day) if m['date'] not in seen]
    ms = sorted(ms, key=lambda m: m['date'])
    if not ms: return None
    first = datetime.datetime.fromisoformat(ms[0]['date']); last = datetime.datetime.fromisoformat(ms[-1]['date'])
    start = (first - datetime.timedelta(minutes=10)).astimezone()        # local time of this PC
    # a BO7 (playoffs) can run 4 hours, a BO5 about 2.5; the last match gets an hour more on top
    length = lambda m: 4 if (m.get('bestof') or 5) >= 7 else 2.5
    hours = round(((last - first).total_seconds() / 3600) + length(ms[-1]) + 1 + 10 / 60, 1)
    if any(m.get('guessed') for m in ms):   # start times not out yet: all on one guessed time, so add up every match
        hours = max(hours, round(sum(length(m) for m in ms) + 1 + 10 / 60, 1))
    return ms, start, hours


LIVE_SCRIPT = os.path.join(ROOT, 'tools', 'run_live.bat' if IS_WIN else 'run_live.sh')


def register(day, start, hours):
    return register_win(day, start, hours) if IS_WIN else register_systemd(day, start, hours)


def cleanup(today):
    return cleanup_win(today) if IS_WIN else cleanup_systemd(today)


def launch_now(day, hours):
    if IS_WIN:
        subprocess.Popen(['cmd', '/c', LIVE_SCRIPT, str(hours), day])
    else:   # own session: the capture keeps running after the daily job that started it ends
        subprocess.Popen(['bash', LIVE_SCRIPT, str(hours), day], cwd=ROOT, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def systemctl(*a):
    return subprocess.run(['systemctl', '--user', *a], capture_output=True, text=True)


def register_systemd(day, start, hours):
    """transient user timer; re-registering a day replaces it (same as -Force on Windows).
    Needs 'loginctl enable-linger <user>' so user timers run without a login session (tools/register_tasks.sh)."""
    unit = f'owcskr-live-{day}'
    systemctl('stop', unit + '.timer', unit + '.service')
    systemctl('reset-failed', unit + '.timer', unit + '.service')
    r = subprocess.run(['systemd-run', '--user', '--unit', unit, '--description', f'OWCSKR live capture {day}',
                        '--on-calendar', start.strftime('%Y-%m-%d %H:%M:%S'), '--timer-property=AccuracySec=1s',
                        '--working-directory', ROOT, '-p', 'RuntimeMaxSec=12h',
                        '/bin/bash', LIVE_SCRIPT, str(hours), day], capture_output=True, text=True)
    return 'registered' if r.returncode == 0 else 'registration failed: ' + (r.stderr or r.stdout).strip()[:200]


def cleanup_systemd(today):
    """stop capture timers of past days (transient units disappear on their own after a reboot)"""
    out = systemctl('list-units', '--all', '--plain', '--no-legend', 'owcskr-live-*.timer').stdout
    for unit in re.findall(r'owcskr-live-(\d{4}-\d{2}-\d{2})\.timer', out):
        if unit < today:
            systemctl('stop', f'owcskr-live-{unit}.timer')


def register_win(day, start, hours):
    ps = (f"$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c {LIVE_SCRIPT} {hours} {day}' -WorkingDirectory '{ROOT}';"
          f"$t = New-ScheduledTaskTrigger -Once -At '{start.strftime('%Y-%m-%dT%H:%M:%S')}';"
          "$s = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 12);"
          rf"Register-ScheduledTask -TaskPath '\OWCSKR\' -TaskName 'LiveCapture_{day}' -Action $a -Trigger $t -Settings $s -Force | Out-Null; 'registered'")
    return subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True).stdout.strip() or 'registration failed'


def cleanup_win(today):
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
            launch_now(day, hours)
        else: print('-> past')
        continue
    print('->', register(day, start, hours))
