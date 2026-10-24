"""tools/register_tasks.sh with stub systemctl / loginctl / node: the unit files it writes and the calls it makes."""
import os, shutil, subprocess

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGGER = '#!/usr/bin/env bash\necho "$(basename "$0") $*" >> "$FAKE_LOG"\n'


def _script(path, text):
    with open(path, 'w', newline='\n') as f:
        f.write(text)
    os.chmod(path, 0o755)


class Registered(tuple):
    """(daily timer, daily service, calls) plus .alert (owcskr-alert@.service)"""


@pytest.fixture
def registered(tmp_path):
    bash = shutil.which('bash')
    if not bash or 'system32' in bash.lower():
        pytest.skip('no bash')
    root, stubs = tmp_path / 'repo', tmp_path / 'stubs'
    (root / 'tools').mkdir(parents=True)
    stubs.mkdir()
    for f in ('env.sh', 'register_tasks.sh'):
        shutil.copy(os.path.join(HERE, 'tools', f), root / 'tools' / f)
    _script(stubs / 'systemctl', LOGGER)
    _script(stubs / 'loginctl', LOGGER + '[ "$1" = show-user ] && echo yes\nexit 0\n')
    _script(stubs / 'node', '#!/usr/bin/env bash\necho 20\n')
    log = tmp_path / 'calls.log'
    env = {k: v for k, v in os.environ.items() if not k.startswith('OWCSKR_')}
    env.update(PATH=str(stubs) + os.pathsep + os.environ.get('PATH', ''), XDG_CONFIG_HOME=(tmp_path / 'cfg').as_posix(),
               FAKE_LOG=log.as_posix(), USER='owcskr', HOME=tmp_path.as_posix())
    r = subprocess.run([bash, 'tools/register_tasks.sh'], cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    units = tmp_path / 'cfg' / 'systemd' / 'user'
    out = Registered(((units / 'owcskr-daily.timer').read_text(), (units / 'owcskr-daily.service').read_text(),
                      log.read_text()))
    out.alert = (units / 'owcskr-alert@.service').read_text()
    return out


def test_timer_runs_at_9_kst_and_3_min_after_boot(registered):
    timer, service, calls = registered
    lines = [x for x in timer.splitlines() if x and not x.startswith('#')]
    assert 'OnCalendar=*-*-* 09:00:00 Asia/Seoul' in lines and 'OnStartupSec=3min' in lines
    assert not any(x.startswith('Persistent=') for x in lines)   # would add a run at boot, before the network
    assert 'Type=oneshot' in service and 'run_daily.sh"' in service


def test_registration_restarts_the_timer_and_runs_once(registered):
    calls = registered[2].splitlines()
    assert 'systemctl --user daemon-reload' in calls
    assert 'systemctl --user restart owcskr-daily.timer' in calls
    assert calls[-1] == 'systemctl --user start --no-block owcskr-daily.service'


def test_daily_service_alerts_on_failure(registered):
    service = registered[1]
    unit_part = service[:service.index('[Service]')]
    assert 'OnFailure=owcskr-alert@%n.service' in unit_part.splitlines()       # a [Unit] setting


def test_alert_template_runs_notify_for_the_failed_unit(registered):
    lines = registered.alert.splitlines()
    exec_start = next(x for x in lines if x.startswith('ExecStart='))
    assert exec_start.endswith('/tools/notify.py" --unit-failed %i') and ' -I ' in exec_start
    assert 'Type=oneshot' in lines
    assert any(x.startswith('EnvironmentFile=-/') and x.endswith('/repo/.env') for x in lines)
    assert not any(x.startswith('OnFailure=') for x in lines)                  # never alerts about itself


def test_ensure_alert_unit_reloads_only_on_a_change(tmp_path):
    """run_daily.sh calls it every day: no daemon-reload when the file is already right"""
    bash = shutil.which('bash')
    if not bash or 'system32' in bash.lower():
        pytest.skip('no bash')
    root, stubs = tmp_path / 'repo', tmp_path / 'stubs'
    (root / 'tools').mkdir(parents=True)
    stubs.mkdir()
    shutil.copy(os.path.join(HERE, 'tools', 'env.sh'), root / 'tools' / 'env.sh')
    _script(stubs / 'systemctl', LOGGER)
    log = tmp_path / 'calls.log'
    env = {k: v for k, v in os.environ.items() if not k.startswith('OWCSKR_')}
    env.update(PATH=str(stubs) + os.pathsep + os.environ.get('PATH', ''), XDG_CONFIG_HOME=(tmp_path / 'cfg').as_posix(),
               FAKE_LOG=log.as_posix(), HOME=tmp_path.as_posix())
    script = '. tools/env.sh; ensure_alert_unit && ensure_alert_unit && echo ok'
    r = subprocess.run([bash, '-c', script], cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == 'ok', r.stderr
    assert log.read_text().splitlines() == ['systemctl --user daemon-reload']
    assert (tmp_path / 'cfg' / 'systemd' / 'user' / 'owcskr-alert@.service').is_file()
