"""tools/register_tasks.sh with stub systemctl / loginctl / node: the unit files it writes and the calls it makes."""
import os, shutil, subprocess

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGGER = '#!/usr/bin/env bash\necho "$(basename "$0") $*" >> "$FAKE_LOG"\n'


def _script(path, text):
    with open(path, 'w', newline='\n') as f:
        f.write(text)
    os.chmod(path, 0o755)


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
    return (units / 'owcskr-daily.timer').read_text(), (units / 'owcskr-daily.service').read_text(), log.read_text()


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
