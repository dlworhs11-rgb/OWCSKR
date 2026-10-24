"""tools/unregister_tasks.sh with a stub systemctl: unit names parsed past status marks, running captures and
recorders left alone unless --stop-running. tools/unregister_tasks.ps1 with stub ScheduledTasks cmdlets: a Running
task is left registered (and running), the rest are removed."""
import os, shutil, subprocess

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEMCTL = r'''#!/usr/bin/env bash
case "$*" in
  *list-units*--state=*) printf '%s\n' \
      'owcskr-live-2026-10-25.service loaded active running OWCSKR live capture 2026-10-25' \
      'owcskr-score_watch.service loaded activating auto-restart recorder' \
      'owcskr-alert@owcskr-x.service.service loaded active running OWCSKR alert' ;;
  *list-units*owcskr-\*.timer*) printf '%s\n' \
      'owcskr-live-2026-10-25.timer loaded active waiting OWCSKR live capture 2026-10-25' \
      '● owcskr-soop-2026-10-24.timer loaded failed failed OWCSKR soop 2026-10-24' ;;
  *) echo "systemctl $*" >> "$FAKE_LOG" ;;
esac
exit 0
'''


@pytest.fixture
def unregister(tmp_path):
    bash = shutil.which('bash')
    if not bash or 'system32' in bash.lower():
        pytest.skip('no bash')
    root, stubs, units = tmp_path / 'repo', tmp_path / 'stubs', tmp_path / 'cfg' / 'systemd' / 'user'
    (root / 'tools').mkdir(parents=True)
    stubs.mkdir()
    units.mkdir(parents=True)
    for name in ('owcskr-daily.service', 'owcskr-daily.timer', 'owcskr-alert@.service'):
        (units / name).write_text('x')
    shutil.copy(os.path.join(HERE, 'tools', 'unregister_tasks.sh'), root / 'tools' / 'unregister_tasks.sh')
    with open(stubs / 'systemctl', 'w', newline='\n', encoding='utf-8') as f:
        f.write(SYSTEMCTL)
    os.chmod(stubs / 'systemctl', 0o755)
    log = tmp_path / 'calls.log'
    env = dict(os.environ, PATH=str(stubs) + os.pathsep + os.environ.get('PATH', ''),
               XDG_CONFIG_HOME=(tmp_path / 'cfg').as_posix(), FAKE_LOG=log.as_posix())

    def run(*args):
        r = subprocess.run([bash, 'tools/unregister_tasks.sh', *args], cwd=root, env=env, capture_output=True,
                           text=True, encoding='utf-8', timeout=60)
        calls = log.read_text(encoding='utf-8').splitlines() if log.exists() else []
        log.unlink(missing_ok=True)
        return r, calls
    run.units = units
    return run


def test_stops_every_timer_and_leaves_running_units(unregister):
    r, calls = unregister()
    assert r.returncode == 0, r.stderr
    assert 'systemctl --user stop owcskr-live-2026-10-25.timer' in calls
    assert 'systemctl --user stop owcskr-soop-2026-10-24.timer' in calls        # not '●'
    assert not any('stop owcskr-live-2026-10-25.service' in c or '●' in c for c in calls)
    assert 'Left running' in r.stdout and 'owcskr-live-2026-10-25.service' in r.stdout
    assert 'owcskr-alert@' not in r.stdout
    assert "systemctl --user reset-failed owcskr-*" in calls
    assert list(unregister.units.iterdir()) == []


def test_stop_running_stops_captures_and_recorders(unregister):
    r, calls = unregister('--stop-running')
    assert r.returncode == 0, r.stderr
    assert 'systemctl --user stop owcskr-live-2026-10-25.service owcskr-score_watch.service' in calls


def test_unknown_argument_is_refused(unregister):
    r, calls = unregister('--all')
    assert r.returncode == 2 and calls == []


# functions win over cmdlets of the same name: nothing touches the real Task Scheduler
PS_STUBS = r'''
function Get-ScheduledTask { [CmdletBinding()] param($TaskPath)
  foreach ($t in ($env:FAKE_TASKS -split ';' | Where-Object { $_ })) {
    $name, $state = $t -split '='
    [pscustomobject]@{ TaskPath = $TaskPath; TaskName = $name; State = $state }
  }
}
function Unregister-ScheduledTask { [CmdletBinding()] param($TaskPath, $TaskName, [switch]$Confirm)
  Write-Host "UNREGISTER $TaskPath$TaskName confirm=$Confirm"
}
'''


def run_ps1(tasks):
    ps = shutil.which('powershell')
    if os.name != 'nt' or not ps:
        pytest.skip('Windows PowerShell')
    script = os.path.join(HERE, 'tools', 'unregister_tasks.ps1')
    cmd = PS_STUBS + f"& '{script}'"
    r = subprocess.run([ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', cmd], capture_output=True,
                       text=True, timeout=120, env=dict(os.environ, FAKE_TASKS=tasks))
    assert r.returncode == 0 and not r.stderr.strip(), r.stderr
    return r.stdout.splitlines()


def test_ps1_leaves_a_running_capture_registered():
    out = run_ps1('Daily=Ready;LiveCapture_2026-10-25=Running;Freshness_2026-10-25=Ready;SoopQuality_2026-10-24=Disabled')
    removed = [x for x in out if x.startswith('UNREGISTER')]
    assert removed == [r'UNREGISTER \OWCSKR\Daily confirm=False', r'UNREGISTER \OWCSKR\Freshness_2026-10-25 confirm=False',
                       r'UNREGISTER \OWCSKR\SoopQuality_2026-10-24 confirm=False']
    assert r'  OWCSKR\LiveCapture_2026-10-25' in out
    assert any('Stop-ScheduledTask' in x for x in out) and any('Left running' in x for x in out)


def test_ps1_removes_everything_when_nothing_runs():
    out = run_ps1('Daily=Ready;LiveCapture_2026-10-25=Ready')
    assert len([x for x in out if x.startswith('UNREGISTER')]) == 2
    assert out[-1] == 'All OWCSKR scheduled tasks removed (2).'
    assert run_ps1('')[-1] == 'All OWCSKR scheduled tasks removed (0).'
