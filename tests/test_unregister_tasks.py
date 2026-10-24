"""tools/unregister_tasks.sh with a stub systemctl: unit names parsed past status marks, running captures and
recorders left alone unless --stop-running."""
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
