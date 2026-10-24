r"""Schedule today's (or a given day's) live capture from the Liquipedia match list.
usage: python -I tools/schedule_today.py [YYYY-MM-DD | --upcoming] [--dry]
Finds that day's Korean-league matches in data/site/matches.json (run collector/build.mjs first) and registers:
  capture  10 minutes before the first match, until 3.5 hours after the last one (live_capture.py also stops by itself
           when GAME DATA screens stop for 75 minutes); restarted after a crash, never past the planned end
  check    tools/matchday_check.py 5 minutes before the first match
  soop     tools/soop_quality.py 2 minutes after the first match
  fresh    tools/healthcheck.py every 15 minutes from the capture start
  Windows: Task Scheduler tasks OWCSKR\LiveCapture_<date>, MatchdayCheck_<date>, SoopQuality_<date>, Freshness_<date>
  Linux:   systemd user timers owcskr-live-<date>, owcskr-check-<date>, owcskr-soop-<date>, owcskr-fresh-<date>
A capture that is already running is never touched (re-registering would kill it). A day whose start has passed but
not its end starts at once, in its own unit / task, so it outlives the daily job that started it.
Exit 1 when a registration failed."""
import datetime, json, os, re, subprocess, sys, time

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import platform_util as PU  # noqa: E402

IS_WIN = PU.IS_WIN
ROOT = os.path.dirname(TOOLS)
MATCHES = os.path.join(ROOT, 'data', 'site', 'matches.json')
LP_DIR = os.path.join(ROOT, 'data', 'lp')
PY = sys.executable
ENV_PROP = 'EnvironmentFile=-' + os.path.join(ROOT, '.env')   # '-': no .env is fine
DAY_START = {4: '17:00', 5: '15:00', 6: '15:00'}   # usual first-match time per weekday (same as owcs_build.py)
CHECKS = (   # kind, minutes after the first match, script
    ('check', -5, 'matchday_check.py'),
    ('soop', 2, 'soop_quality.py'),
)
FRESH_EVERY_MIN = 15      # healthcheck.py: alerts past 30 min during a match, so a stale site is seen within 45 min
WIN_TASK = {'live': 'LiveCapture', 'check': 'MatchdayCheck', 'soop': 'SoopQuality', 'fresh': 'Freshness'}
FAILED = ('registration failed', 'start failed')
KST = datetime.timezone(datetime.timedelta(hours=9))   # match days are Korean dates, whatever this machine's zone


def load_matches(path: str | None = None) -> list[dict]:
    with open(path or MATCHES, encoding='utf-8') as f:
        return json.load(f)


def playoff_matches(day: str, lp_dir: str | None = None) -> list[dict]:
    """playoff / seeding-decider matches of that day from the stage's Liquipedia page (data/lp/*-korea.json).
    site/matches.json drops matches whose teams are still TBD, which is every playoff match until the round before
    is over, so the capture of a playoff day would never get scheduled. A match without a start time comes as 00:00 KST:
    it gets the usual first-match time of that weekday (re-registered each morning once Liquipedia has the time).
    Liquipedia writes 'bestof' only on a round's first match: the rest of the round carries it over."""
    lp_dir = lp_dir or LP_DIR
    out = []
    for f in sorted(os.listdir(lp_dir)):
        if not f.endswith('-korea.json'):
            continue
        bo = None
        with open(os.path.join(lp_dir, f), encoding='utf-8') as fh:
            page = json.load(fh)
        for m in page.get('matches', []):
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


def plan(day: str, matches: list[dict], lp_dir: str | None = None):
    """(matches, capture start as local time, hours) of that day, or None without Korean-league matches"""
    ms = [m for m in matches if m['date'].startswith(day) and '/Korea' in m['competitionTitle']]
    seen = {m['date'] for m in ms}
    ms += [m for m in playoff_matches(day, lp_dir) if m['date'] not in seen]
    ms = sorted(ms, key=lambda m: m['date'])
    if not ms: return None
    first = datetime.datetime.fromisoformat(ms[0]['date']); last = datetime.datetime.fromisoformat(ms[-1]['date'])
    start = (first - datetime.timedelta(minutes=10)).astimezone()        # local time of this machine
    # a BO7 (playoffs) can run 4 hours, a BO5 about 2.5; the last match gets an hour more on top
    length = lambda m: 4 if (m.get('bestof') or 5) >= 7 else 2.5
    hours = round(((last - first).total_seconds() / 3600) + length(ms[-1]) + 1 + 10 / 60, 1)
    if any(m.get('guessed') for m in ms):   # start times not out yet: all on one guessed time, so add up every match
        hours = max(hours, round(sum(length(m) for m in ms) + 1 + 10 / 60, 1))
    return ms, start, hours


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    """every systemctl / systemd-run / powershell call goes through here (tests replace it)"""
    return subprocess.run(cmd, capture_output=True, text=True)


def live_script() -> str:
    return os.path.join(ROOT, 'tools', 'run_live.bat' if IS_WIN else 'run_live.sh')


def clear_until(day: str) -> None:
    """a newly planned start is a new run: drop the end time and the "day finished" mark (summary.txt) a test or an
    earlier start of that day left behind"""
    for name in ('until.txt', 'summary.txt'):
        path = os.path.join(PU.LIVE_DIR, day, name)
        if os.path.isfile(path):
            os.remove(path)


def left_hours(end: datetime.datetime, now: datetime.datetime) -> float:
    return round(max(0.5, (end - now).total_seconds() / 3600), 1)


# ---------------------------------------------------------------- Linux: systemd user units

def systemctl(*a: str) -> subprocess.CompletedProcess:
    return run(['systemctl', '--user', *a])


def unit_busy(unit: str) -> bool:
    """running, starting, stopping, or waiting for its automatic restart"""
    state = systemctl('show', '-p', 'ActiveState', '--value', unit).stdout.strip()
    return state in ('active', 'activating', 'deactivating', 'reloading')


def free_name(unit: str) -> None:
    """stop the old timer and forget failed runs, so systemd-run can reuse the name (the service is not running)"""
    systemctl('stop', unit + '.timer')
    systemctl('reset-failed', unit + '.timer', unit + '.service')


def capture_props(hours: float) -> list[str]:
    """the capture unit, the same whether a timer or launch_now starts it. RuntimeMaxSec is only a backstop: run_live.sh
    ends at the planned time itself (until.txt). Not restarted: exit 2 = live_capture's self-check failed, 4 = the capture
    ended but its final OCR / publish failed (a restart would capture an empty screen until the end time)."""
    return [ENV_PROP, f'RuntimeMaxSec={round((hours + 1) * 3600)}s', 'Restart=on-failure', 'RestartSec=60',
            'RestartPreventExitStatus=2 4', 'TimeoutStopSec=5min']


def utc_calendar(when: datetime.datetime) -> str:
    return when.astimezone(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def systemd_run(unit: str, desc: str, argv: list[str], props: list[str], when: datetime.datetime | None = None,
                timer_props: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    """transient service (with a timer at WHEN, else started now). WHEN goes in UTC with its zone named: right
    whatever this machine's zone, and never ambiguous (a local wall time in a DST fall-back hour can mean two times)."""
    cmd = ['systemd-run', '--user', '--unit', unit, '--description', desc]
    if when is not None:
        cmd += ['--on-calendar', utc_calendar(when), '--timer-property=AccuracySec=1s']
        cmd += [f'--timer-property={p}' for p in timer_props]
    cmd += ['--working-directory', ROOT]
    for p in props:
        cmd += ['-p', p]
    r = run(cmd + argv)
    if r.returncode != 0 and 'already' in (r.stderr or ''):   # the stopped old unit not unloaded yet
        time.sleep(2)
        r = run(cmd + argv)
    return r


def _result(r: subprocess.CompletedProcess, ok: str, failed: str) -> str:
    return ok if r.returncode == 0 else f'{failed}: ' + ((r.stderr or '') + (r.stdout or '')).strip()[:200]


def register_systemd(day: str, start: datetime.datetime, hours: float) -> str:
    """transient user timer; re-registering a day replaces the timer only. A running capture keeps going untouched
    (systemd-run cannot add a timer to a running unit of the same name, and stopping it would lose the day).
    Needs 'loginctl enable-linger <user>' so user timers run without a login session (tools/register_tasks.sh)."""
    unit = f'owcskr-live-{day}'
    if unit_busy(unit + '.service'):
        return 'capture running - left as is'
    free_name(unit)
    clear_until(day)
    r = systemd_run(unit, f'OWCSKR live capture {day}', ['/bin/bash', live_script(), str(hours), day],
                    capture_props(hours), when=start)
    return _result(r, 'registered', 'registration failed')


def launch_now_systemd(day: str, hours: float) -> str:
    """start time already passed: the same unit, started now (its own unit: a child of the daily job would be killed
    with the daily job's cgroup when it ends). until.txt is kept, so a restart after a reboot ends at the old time."""
    unit = f'owcskr-live-{day}'
    if unit_busy(unit + '.service'):
        return 'capture already running'
    free_name(unit)
    r = systemd_run(unit, f'OWCSKR live capture {day}', ['/bin/bash', live_script(), str(hours), day],
                    capture_props(hours))
    return _result(r, 'started', 'start failed')


def register_check_systemd(kind: str, day: str, when: datetime.datetime, script: str, repeat_min: int,
                           end: datetime.datetime) -> str:
    """one-shot timer for a check script (repeat_min: again every n minutes after the first run, until the next
    morning's cleanup stops the timer); the .env values come with EnvironmentFile="""
    unit = f'owcskr-{kind}-{day}'
    if unit_busy(unit + '.service'):
        return 'running - left as is'
    free_name(unit)
    tprops = (f'OnUnitActiveSec={repeat_min}min',) if repeat_min else ()
    r = systemd_run(unit, f'OWCSKR {kind} {day}', [PY, '-I', os.path.join(TOOLS, script)],
                    [ENV_PROP, 'RuntimeMaxSec=10min'], when=when, timer_props=tprops)
    return _result(r, 'registered', 'registration failed')


def cleanup_systemd(today: str) -> None:
    """stop the timers of past days (transient units disappear on their own after a reboot)"""
    out = systemctl('list-units', '--all', '--plain', '--no-legend', 'owcskr-*.timer').stdout
    for kind, day in re.findall(r'owcskr-(live|check|soop|fresh)-(\d{4}-\d{2}-\d{2})\.timer', out):
        if day < today:
            systemctl('stop', f'owcskr-{kind}-{day}.timer')


# ---------------------------------------------------------------- Windows: Task Scheduler

def q(s: object) -> str:
    """PowerShell single-quoted string"""
    return "'" + str(s).replace("'", "''") + "'"


def ps(script: str) -> subprocess.CompletedProcess:
    return run(['powershell', '-NoProfile', '-Command', script])


def win_task_state(name: str) -> str:
    return ps(rf"(Get-ScheduledTask -TaskPath '\OWCSKR\' -TaskName {q(name)} -ErrorAction SilentlyContinue).State").stdout.strip()


def register_task_win(name: str, when: datetime.datetime, command: str, limit_min: int, repeat_min: int = 0,
                      repeat_for_min: int = 0, start_now: bool = False) -> str:
    """one-time task running 'cmd /c COMMAND' in the repo folder (-Force replaces an older one of that name)"""
    rep = (f' -RepetitionInterval (New-TimeSpan -Minutes {repeat_min}) -RepetitionDuration (New-TimeSpan -Minutes {repeat_for_min})'
           if repeat_min else '')
    script = (f"$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument {q('/c ' + command)} -WorkingDirectory {q(ROOT)};"
              f"$t = New-ScheduledTaskTrigger -Once -At {q(when.astimezone().strftime('%Y-%m-%dT%H:%M:%S'))}{rep};"
              f"$s = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes {limit_min});"
              rf"Register-ScheduledTask -TaskPath '\OWCSKR\' -TaskName {q(name)} -Action $a -Trigger $t -Settings $s -Force | Out-Null;")
    if start_now:
        script += rf" Start-ScheduledTask -TaskPath '\OWCSKR\' -TaskName {q(name)}; 'started'"
    else:
        script += " 'registered'"
    r = ps(script)
    out = r.stdout.strip()
    if out.endswith(('registered', 'started')):
        return out.splitlines()[-1]
    return ('start failed: ' if start_now else 'registration failed: ') + (r.stderr or out).strip()[:200]


def capture_command_win(hours: float, day: str) -> str:
    return rf'tools\run_live.bat {hours} {day}'


def register_win(day: str, start: datetime.datetime, hours: float) -> str:
    name = f'LiveCapture_{day}'
    if win_task_state(name) == 'Running':
        return 'capture running - left as is'
    clear_until(day)
    return register_task_win(name, start, capture_command_win(hours, day), round((hours + 1) * 60))


def launch_now_win(day: str, hours: float) -> str:
    """through the day's task, so a second daily run sees it as Running and leaves it alone"""
    name = f'LiveCapture_{day}'
    if win_task_state(name) == 'Running':
        return 'capture already running'
    now = datetime.datetime.now()
    return register_task_win(name, now, capture_command_win(hours, day), round((hours + 1) * 60), start_now=True)


def register_check_win(kind: str, day: str, when: datetime.datetime, script: str, repeat_min: int,
                       end: datetime.datetime) -> str:
    name = f'{WIN_TASK[kind]}_{day}'
    if win_task_state(name) == 'Running':
        return 'running - left as is'
    log = 'healthcheck.log' if kind == 'fresh' else 'checks.log'
    command = rf'python -I tools\{script} >> data\live\{log} 2>&1'
    span = max(repeat_min, round((end - when).total_seconds() / 60) + 60) if repeat_min else 0
    return register_task_win(name, when, command, 10, repeat_min, span)


def cleanup_win(today: str) -> None:
    """remove the tasks of past days (and the old single 'LiveCapture' task)"""
    script = (r"Get-ScheduledTask -TaskPath '\OWCSKR\' -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -eq 'LiveCapture' -or "
              r"($_.TaskName -match '^(LiveCapture|MatchdayCheck|SoopQuality|Freshness)_(\d{4}-\d{2}-\d{2})$' -and $Matches[2] -lt "
              + q(today) + ") } | Unregister-ScheduledTask -Confirm:$false")
    ps(script)


# ---------------------------------------------------------------- both

def register(day: str, start: datetime.datetime, hours: float) -> str:
    return register_win(day, start, hours) if IS_WIN else register_systemd(day, start, hours)


def launch_now(day: str, hours: float) -> str:
    return launch_now_win(day, hours) if IS_WIN else launch_now_systemd(day, hours)


def register_check(kind: str, day: str, when: datetime.datetime, script: str, repeat_min: int,
                   end: datetime.datetime) -> str:
    fn = register_check_win if IS_WIN else register_check_systemd
    return fn(kind, day, when, script, repeat_min, end)


def cleanup(today: str) -> None:
    return cleanup_win(today) if IS_WIN else cleanup_systemd(today)


def register_checks(day: str, first: datetime.datetime, start: datetime.datetime, end: datetime.datetime,
                    now: datetime.datetime) -> list[str]:
    """the match-day checks next to the capture; a check whose time has passed is left out"""
    items = [(kind, first + datetime.timedelta(minutes=mins), script, 0) for kind, mins, script in CHECKS]
    items.append(('fresh', max(start, now + datetime.timedelta(minutes=1)), 'healthcheck.py', FRESH_EVERY_MIN))
    out = []
    for kind, when, script, repeat in items:
        if when <= now or (repeat and when >= end):
            out.append(f'{kind}: time passed - not scheduled')
            continue
        out.append(f"{kind} {when.astimezone():%H:%M}: {register_check(kind, day, when, script, repeat, end)}")
    return out


def schedule(day: str, ms: list[dict], start: datetime.datetime, hours: float, now: datetime.datetime) -> bool:
    """register (or start) one day's capture and checks; False when something could not be registered"""
    end = start + datetime.timedelta(hours=hours)
    if start < now:
        if now >= end:
            print('-> past')
            return True
        res = launch_now(day, left_hours(end, now))
        print('-> already started time,', res)
    else:
        res = register(day, start, hours)
        print('->', res)
    lines = register_checks(day, datetime.datetime.fromisoformat(ms[0]['date']), start, end, now)
    for line in lines:
        print('  ', line)
    return not any(f in x for x in [res, *lines] for f in FAILED)


def main(argv: list[str] | None = None, now: datetime.datetime | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):   # logs may contain names like 'Esperança'
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    now = now or datetime.datetime.now().astimezone()
    dry, upcoming = '--dry' in argv, '--upcoming' in argv
    args = [x for x in argv if not x.startswith('--')]
    matches = load_matches()
    today = now.astimezone(KST).date()
    if upcoming:            # every match day in the next 14 days, each with its own units / tasks; yesterday too, whose
        # capture runs past midnight (a reboot at 00:30 must start it again), but only while it is still on
        days = [(today + datetime.timedelta(d)).isoformat() for d in range(-1, 15)]
        if not dry: cleanup(today.isoformat())
    else:
        days = [args[0] if args else today.isoformat()]
    ok = True
    for day in days:
        p = plan(day, matches)
        if not p:
            if not upcoming: print(day, ': no Korean-league matches - nothing scheduled')
            continue
        ms, start, hours = p
        if day < today.isoformat() and not start < now < start + datetime.timedelta(hours=hours):
            continue
        print(day, ':', len(ms), 'matches, first', f"{datetime.datetime.fromisoformat(ms[0]['date']).astimezone():%H:%M}",
              '-> capture', start.strftime('%m-%d %H:%M'), f'(up to {hours} h)', end=' ')
        if dry:
            print()
            continue
        ok = schedule(day, ms, start, hours, now) and ok
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
