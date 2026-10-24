import datetime, json, os, subprocess, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import platform_util as PU
import schedule_today as S

KST = datetime.timezone(datetime.timedelta(hours=9))
DAY = '2026-10-25'          # a Sunday
UNIT = f'owcskr-live-{DAY}'


def kr(date, bestof=5, title='Overwatch Champions Series/2026/Asia/Stage 3/Korea/Regular Season'):
    return {'date': date, 'bestof': bestof, 'competitionTitle': title, 'team1': 'A', 'team2': 'B'}


MATCHES = [
    kr(f'{DAY}T15:00:00+09:00'),
    kr(f'{DAY}T17:30:00+09:00'),
    kr(f'{DAY}T12:00:00+09:00', title='Overwatch Champions Series/2026/EMEA/Stage 3/Regular Season'),
]


class FakeRun:
    """stands in for subprocess.run: records every command; 'systemctl show' answers from states"""

    def __init__(self, states=None, fail=()):
        self.calls, self.states, self.fail = [], dict(states or {}), fail

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[:3] == ['systemctl', '--user', 'show']:
            return subprocess.CompletedProcess(cmd, 0, self.states.get(cmd[-1], 'inactive') + '\n', '')
        if cmd[0] == 'systemd-run' and any(f in cmd for f in self.fail):
            return subprocess.CompletedProcess(cmd, 1, '', 'Failed to start transient timer unit: boom')
        return subprocess.CompletedProcess(cmd, 0, '', '')

    def runs(self, unit=None):
        return [c for c in self.calls if c[0] == 'systemd-run' and (unit is None or c[c.index('--unit') + 1] == unit)]


def props(cmd):
    return [cmd[i + 1] for i, x in enumerate(cmd) if x == '-p']


@pytest.fixture
def linux(monkeypatch, tmp_path):
    fake = FakeRun()
    monkeypatch.setattr(S, 'IS_WIN', False)
    monkeypatch.setattr(S, 'run', fake)
    monkeypatch.setattr(S, 'LP_DIR', str(tmp_path / 'lp'))
    monkeypatch.setattr(PU, 'LIVE_DIR', str(tmp_path / 'live'))
    monkeypatch.setattr(S, 'load_matches', lambda path=None: MATCHES)
    os.makedirs(tmp_path / 'lp')
    return fake


def start_of(day=DAY, hm='14:50'):
    return datetime.datetime.fromisoformat(f'{day}T{hm}:00+09:00').astimezone()


# ---------------------------------------------------------------- plan()

def test_plan_korean_matches_only(linux):
    ms, start, hours = S.plan(DAY, MATCHES)
    assert len(ms) == 2
    assert start == start_of()                       # 10 min before the first match
    assert hours == round(2.5 + 2.5 + 1 + 10 / 60, 1)  # gap between the matches + last BO5 + 1 h + 10 min


def test_plan_none_without_korean_matches(linux):
    assert S.plan('2026-10-26', MATCHES) is None


def test_plan_guessed_playoff_day_adds_up_every_match(linux, tmp_path):
    page = {'matches': [{'date': '2026-10-31T00:00:00+09:00', 'bestof': 7},
                        {'date': '2026-10-31T00:00:00+09:00', 'bestof': None}]}   # bestof carried over: BO7
    (tmp_path / 'lp' / 'owcs-2026-asia-stage-3-korea.json').write_text(json.dumps(page), encoding='utf-8')
    ms, start, hours = S.plan('2026-10-31', [])
    assert [m['guessed'] for m in ms] == [True, True]
    assert start == start_of('2026-10-31', '14:50')   # Saturday's usual 15:00
    assert hours == round(4 + 4 + 1 + 10 / 60, 1)


def test_import_has_no_side_effects():
    assert callable(S.main) and os.getcwd()   # importing did not chdir, read matches.json or schedule anything


# ---------------------------------------------------------------- systemd command lines

def test_register_systemd_command_line(linux):
    start = start_of()
    assert S.register_systemd(DAY, start, 6.2) == 'registered'
    (cmd,) = linux.runs(UNIT)
    assert cmd[:4] == ['systemd-run', '--user', '--unit', UNIT]
    assert cmd[cmd.index('--on-calendar') + 1] == start.strftime('%Y-%m-%d %H:%M:%S')
    assert cmd[-4:] == ['/bin/bash', os.path.join(S.ROOT, 'tools', 'run_live.sh'), '6.2', DAY]
    p = props(cmd)
    assert S.ENV_PROP in p and S.ENV_PROP.startswith('EnvironmentFile=-')
    assert {'Restart=on-failure', 'RestartSec=60', 'TimeoutStopSec=5min', 'RestartPreventExitStatus=2'} <= set(p)
    assert f'RuntimeMaxSec={round(7.2 * 3600)}s' in p          # planned length + 1 h
    assert ['systemctl', '--user', 'stop', UNIT + '.timer'] in linux.calls
    assert not any('stop' in c and UNIT + '.service' in c for c in linux.calls)


def test_register_systemd_leaves_running_capture_alone(linux):
    linux.states[UNIT + '.service'] = 'active'
    assert S.register_systemd(DAY, start_of(), 6.2) == 'capture running - left as is'
    assert linux.runs() == []
    assert not any(c[2] in ('stop', 'reset-failed') for c in linux.calls if c[0] == 'systemctl')


def test_register_clears_old_until_but_launch_now_keeps_it(linux):
    path = os.path.join(PU.LIVE_DIR, DAY, 'until.txt')
    os.makedirs(os.path.dirname(path))
    open(path, 'w').write('2026-10-25T21:00:00+09:00')
    S.launch_now_systemd(DAY, 3.0)
    assert os.path.exists(path)                      # a restart must end at the old time
    S.register_systemd(DAY, start_of(), 6.2)
    assert not os.path.exists(path)                  # a newly planned start is a new run


def test_already_started_day_uses_systemd_run_now(linux):
    now = start_of() + datetime.timedelta(hours=1)
    assert S.main([DAY], now=now) == 0
    (cmd,) = linux.runs(UNIT)
    assert '--on-calendar' not in cmd                # started now, in its own unit (outlives the daily job)
    assert cmd[-2:] == [str(S.left_hours(start_of() + datetime.timedelta(hours=6.2), now)), DAY]
    assert cmd[-2] == '5.2'
    assert f'RuntimeMaxSec={round(6.2 * 3600)}s' in props(cmd)
    assert not any(c[0] in ('bash', '/bin/bash') for c in linux.calls)   # no plain child process


def test_already_started_day_not_launched_twice(linux):
    linux.states[UNIT + '.service'] = 'activating'   # e.g. waiting for its automatic restart
    assert S.main([DAY], now=start_of() + datetime.timedelta(hours=1)) == 0
    assert linux.runs(UNIT) == []


def test_future_day_registers_capture_and_checks(linux):
    now = start_of() - datetime.timedelta(hours=5)
    assert S.main([DAY], now=now) == 0
    check, = linux.runs(f'owcskr-check-{DAY}')
    soop, = linux.runs(f'owcskr-soop-{DAY}')
    fresh, = linux.runs(f'owcskr-fresh-{DAY}')
    first = datetime.datetime.fromisoformat(f'{DAY}T15:00:00+09:00')
    assert check[check.index('--on-calendar') + 1] == (first - datetime.timedelta(minutes=5)).astimezone().strftime('%Y-%m-%d %H:%M:%S')
    assert soop[soop.index('--on-calendar') + 1] == (first + datetime.timedelta(minutes=2)).astimezone().strftime('%Y-%m-%d %H:%M:%S')
    assert check[-1].endswith('matchday_check.py') and soop[-1].endswith('soop_quality.py')
    assert fresh[-1].endswith('healthcheck.py') and '--timer-property=OnUnitActiveSec=30min' in fresh
    for cmd in (check, soop, fresh):
        assert S.ENV_PROP in props(cmd)
    assert len(linux.runs(UNIT)) == 1


def test_already_started_day_skips_past_checks(linux):
    S.main([DAY], now=start_of() + datetime.timedelta(hours=1))
    assert linux.runs(f'owcskr-check-{DAY}') == [] and linux.runs(f'owcskr-soop-{DAY}') == []
    assert len(linux.runs(f'owcskr-fresh-{DAY}')) == 1


def test_past_day_does_nothing(linux):
    assert S.main([DAY], now=start_of() + datetime.timedelta(hours=7)) == 0
    assert linux.runs() == []


def test_registration_failure_exits_1(linux):
    linux.fail = (UNIT,)
    assert S.main([DAY], now=start_of() - datetime.timedelta(hours=5)) == 1


def test_dry_registers_nothing(linux):
    assert S.main(['--upcoming', '--dry'], now=start_of() - datetime.timedelta(days=1)) == 0
    assert linux.calls == []


def test_cleanup_systemd_stops_only_past_days(linux):
    listing = '\n'.join(f'{u}.timer loaded active waiting x' for u in (
        'owcskr-live-2026-10-24', 'owcskr-check-2026-10-24', 'owcskr-fresh-2026-10-24', 'owcskr-live-2026-10-25',
        'owcskr-daily'))
    linux.calls.clear()
    orig = linux.__call__

    def run(cmd):
        if 'list-units' in cmd:
            linux.calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, listing, '')
        return orig(cmd)
    S.run = run
    S.cleanup_systemd('2026-10-25')
    stopped = [c[-1] for c in linux.calls if c[:3] == ['systemctl', '--user', 'stop']]
    assert stopped == ['owcskr-live-2026-10-24.timer', 'owcskr-check-2026-10-24.timer', 'owcskr-fresh-2026-10-24.timer']


# ---------------------------------------------------------------- Windows

class FakePs(FakeRun):
    def __init__(self, state=''):
        super().__init__()
        self.state = state

    def __call__(self, cmd):
        self.calls.append(cmd)
        if 'State' in cmd[-1] and 'Register-ScheduledTask' not in cmd[-1]:
            return subprocess.CompletedProcess(cmd, 0, self.state + '\n', '')
        return subprocess.CompletedProcess(cmd, 0, 'started' if 'Start-ScheduledTask' in cmd[-1] else 'registered', '')


@pytest.fixture
def win(monkeypatch, tmp_path):
    def make(state=''):
        fake = FakePs(state)
        monkeypatch.setattr(S, 'IS_WIN', True)
        monkeypatch.setattr(S, 'run', fake)
        monkeypatch.setattr(PU, 'LIVE_DIR', str(tmp_path / 'live'))
        return fake
    return make


def test_windows_running_task_is_left_alone(win):
    fake = win('Running')
    assert S.register_win(DAY, start_of(), 6.2) == 'capture running - left as is'
    assert S.launch_now_win(DAY, 3.0) == 'capture already running'
    assert not any('Register-ScheduledTask' in c[-1] for c in fake.calls)


def test_windows_launch_now_goes_through_the_task(win):
    fake = win('Ready')
    assert S.launch_now_win(DAY, 3.0) == 'started'
    script = fake.calls[-1][-1]
    assert rf"-TaskName 'LiveCapture_{DAY}'" in script and 'Start-ScheduledTask' in script
    assert rf'/c tools\run_live.bat 3.0 {DAY}' in script
    assert '(New-TimeSpan -Minutes 240)' in script        # 3 h + 1 h


def test_windows_check_tasks(win):
    fake = win('')
    when = start_of()
    assert S.register_check_win('fresh', DAY, when, 'healthcheck.py', 30, when + datetime.timedelta(hours=6)) == 'registered'
    script = fake.calls[-1][-1]
    assert f"'Freshness_{DAY}'" in script and '-RepetitionInterval (New-TimeSpan -Minutes 30)' in script
    assert S.register_check_win('check', DAY, when, 'matchday_check.py', 0, when) == 'registered'
    assert f"'MatchdayCheck_{DAY}'" in fake.calls[-1][-1] and 'Repetition' not in fake.calls[-1][-1]


def test_powershell_quoting():
    assert S.q("C:\\it's here") == "'C:\\it''s here'"
