"""tools/start_watchers.sh under (stub) systemd: each recorder gets a transient unit that restarts after a crash,
gives up after 5 starts in 10 minutes and then alerts through OnFailure=owcskr-alert@<unit>.service."""
import os, shutil, subprocess

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGGER = '#!/usr/bin/env bash\nprintf "%s\\n" "$(basename "$0")" "$@" "--" >> "$FAKE_LOG"\n'
SYSTEMCTL = LOGGER + '[ "$2" = show ] && echo inactive\nexit 0\n'


def _script(path, text):
    with open(path, 'w', newline='\n') as f:
        f.write(text)
    os.chmod(path, 0o755)


@pytest.fixture
def started(tmp_path):
    bash = shutil.which('bash')
    if not bash or 'system32' in bash.lower():
        pytest.skip('no bash')
    root, stubs, site = tmp_path / 'repo', tmp_path / 'stubs', tmp_path / 'site'
    (root / 'tools').mkdir(parents=True)
    stubs.mkdir()
    site.mkdir()
    (site / 'score_watch.py').write_text('')
    for f in ('env.sh', 'start_watchers.sh'):
        shutil.copy(os.path.join(HERE, 'tools', f), root / 'tools' / f)
    _script(stubs / 'systemctl', SYSTEMCTL)
    _script(stubs / 'systemd-run', LOGGER)
    _script(stubs / 'pgrep', '#!/usr/bin/env bash\nexit 1\n')
    log = tmp_path / 'calls.log'
    env = {k: v for k, v in os.environ.items() if not k.startswith('OWCSKR_')}
    env.update(PATH=str(stubs) + os.pathsep + os.environ.get('PATH', ''), FAKE_LOG=log.as_posix(),
               HOME=tmp_path.as_posix(), OWCSKR_SITE_DIR=site.as_posix(), OWCSKR_PYTHON='python3')
    r = subprocess.run([bash, 'tools/start_watchers.sh'], cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    calls, cur = [], []
    for line in log.read_text().splitlines():
        if line == '--':
            calls.append(cur)
            cur = []
        else:
            cur.append(line)
    return [c for c in calls if c[0] == 'systemd-run']


def test_recorder_unit_has_a_start_limit_and_an_alert(started):
    (cmd,) = started                                  # only score_watch.py is in the site folder
    assert cmd[cmd.index('--unit') + 1] == 'owcskr-score_watch'
    props = [cmd[i + 1] for i, x in enumerate(cmd) if x == '-p']
    assert {'Restart=on-failure', 'RestartSec=30', 'StartLimitIntervalSec=10min', 'StartLimitBurst=5',
            'OnFailure=owcskr-alert@owcskr-score_watch.service.service'} <= set(props)
    assert 'StartLimitIntervalSec=0' not in props    # restarting forever never alerted anyone
    assert cmd[-3:] == ['python3', '-u', 'score_watch.py']
