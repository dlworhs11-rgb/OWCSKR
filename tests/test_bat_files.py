"""tools/*.bat: ASCII + CRLF (cmd misparses LF-only files), and start_watchers.bat keeps run_live.bat's variables."""
import glob, os, subprocess

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATS = sorted(glob.glob(os.path.join(HERE, 'tools', '*.bat')))


@pytest.mark.parametrize('path', BATS, ids=os.path.basename)
def test_bat_is_ascii_crlf(path):
    data = open(path, 'rb').read()
    assert all(b < 128 for b in data)
    assert b'\n' not in data.replace(b'\r\n', b'')


@pytest.mark.skipif(os.name != 'nt', reason='cmd.exe')
def test_start_watchers_keeps_the_callers_log(tmp_path):
    """run_live.bat logs to %LOG% after 'call tools\\start_watchers.bat'; that file used to set LOG to the
    data\\live folder, so the capture's '>> "%LOG%"' failed with 'Access is denied' and live_capture never ran"""
    (tmp_path / 'tools').mkdir()
    with open(os.path.join(HERE, 'tools', 'start_watchers.bat'), encoding='ascii', newline='') as f:
        body = f.read()
    body = body[:body.index('powershell')]          # everything but the recorder launch
    (tmp_path / 'tools' / 'start_watchers.bat').write_bytes(body.encode('ascii'))
    caller = ('@echo off\r\nsetlocal\r\nset "LOG=%CD%\\task.log"\r\n'
              'call tools\\start_watchers.bat >> "%LOG%" 2>&1\r\necho LOG=%LOG%\r\n')
    (tmp_path / 'caller.bat').write_bytes(caller.encode('ascii'))
    r = subprocess.run(['cmd', '/c', str(tmp_path / 'caller.bat')], cwd=tmp_path, capture_output=True, text=True)
    assert r.stdout.strip() == f'LOG={tmp_path}\\task.log'


STUB = r'''import os, sys
args = sys.argv[1:]
name = os.path.basename(sys.argv[0])
with open(os.environ['FAKE_LOG'], 'a', encoding='utf-8') as f:
    f.write(name + ' ' + ' '.join(args) + '\n')
if name == 'platform_util.py' and args == ['publish']:
    sys.exit(int(os.environ.get('FAKE_PUB_RC', '0')))
if name == 'platform_util.py':
    rc = int(os.environ.get('FAKE_LU_RC', '0'))
    if rc == 0:
        d = os.path.join('data', 'live', args[2])
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, 'until.txt'), 'w').write('2026-10-25T23:00:00+09:00')
    sys.exit(rc)
if name == 'live_capture.py':
    sys.exit(int(os.environ.get('FAKE_LC_RC', '0')))
'''


@pytest.fixture
def run_live_bat(tmp_path):
    """tools/run_live.bat in a copy of the repo whose python scripts are stubs that log their arguments"""
    import shutil, sys, time
    root, site = tmp_path / 'repo', tmp_path / 'site'
    (root / 'tools').mkdir(parents=True)
    site.mkdir()
    shutil.copy(os.path.join(HERE, 'tools', 'run_live.bat'), root / 'tools' / 'run_live.bat')
    (root / 'tools' / 'start_watchers.bat').write_bytes(b'@echo off\r\nexit /b 0\r\n')
    for f in ('platform_util.py', 'live_capture.py', 'notify.py'):
        (root / 'tools' / f).write_text(STUB, encoding='utf-8')
    (site / 'replay_comment.py').write_text(STUB, encoding='utf-8')
    log = tmp_path / 'calls.log'
    env = {k: v for k, v in os.environ.items() if not k.startswith('OWCSKR_')}
    env.update(PATH=os.path.dirname(sys.executable) + os.pathsep + env.get('PATH', ''), FAKE_LOG=str(log),
               OWCSKR_SITE_DIR=str(site))

    def run(day_done=False, wait_replay=False, **fake):
        if day_done:
            (root / 'data' / 'live' / '2026-10-25').mkdir(parents=True)
            (root / 'data' / 'live' / '2026-10-25' / 'summary.txt').write_text('sent')
        r = subprocess.run(['cmd', '/c', str(root / 'tools' / 'run_live.bat'), '6.5', '2026-10-25'], cwd=root,
                           env=dict(env, **fake), capture_output=True, text=True, timeout=60)
        for _ in range(100 if wait_replay else 20):          # replay_comment.py is started detached
            if log.exists() and 'replay_comment.py' in log.read_text(encoding='utf-8'):
                break
            time.sleep(0.1)
        calls = log.read_text(encoding='utf-8').split('\n') if log.exists() else []
        return r.returncode, [c.split()[0] for c in calls if c]
    return run


@pytest.mark.skipif(os.name != 'nt', reason='cmd.exe')
def test_run_live_bat_finished_day_exits_at_once(run_live_bat):
    rc, calls = run_live_bat(day_done=True)
    assert rc == 0 and calls == []


@pytest.mark.skipif(os.name != 'nt', reason='cmd.exe')
def test_run_live_bat_replay_comment_after_a_good_capture(run_live_bat):
    rc, calls = run_live_bat(wait_replay=True)
    assert rc == 0 and calls == ['platform_util.py', 'live_capture.py', 'platform_util.py', 'replay_comment.py']


@pytest.mark.skipif(os.name != 'nt', reason='cmd.exe')
def test_run_live_bat_shadow_run_posts_no_replay_comment(run_live_bat):
    """OWCSKR_PUBLISH=0 (platform_util.py publish exits 1): the capture runs, the comment is the other machine's"""
    rc, calls = run_live_bat(FAKE_PUB_RC='1')
    assert rc == 0 and calls == ['platform_util.py', 'live_capture.py', 'platform_util.py']


@pytest.mark.skipif(os.name != 'nt', reason='cmd.exe')
def test_run_live_bat_no_replay_comment_after_a_failed_capture(run_live_bat):
    rc, calls = run_live_bat(FAKE_LC_RC='1')
    assert rc == 1 and calls == ['platform_util.py', 'live_capture.py', 'notify.py']


@pytest.mark.skipif(os.name != 'nt', reason='cmd.exe')
def test_run_live_bat_exit_4_alerts_and_still_comments(run_live_bat):
    rc, calls = run_live_bat(FAKE_LC_RC='4', wait_replay=True)
    assert rc == 4 and calls == ['platform_util.py', 'live_capture.py', 'notify.py', 'platform_util.py', 'replay_comment.py']
