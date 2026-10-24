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
