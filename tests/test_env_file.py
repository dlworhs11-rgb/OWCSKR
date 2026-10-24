""".env reading: tools/env.sh (bash) and platform_util.parse_env_lines (python) must agree, and both must give the
values systemd EnvironmentFile= gives for the accepted subset."""
import datetime, os, shutil, subprocess, sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'tools'))
import platform_util as PU

GOOD = (
    '# settings\n'
    '\n'
    '   # indented comment\n'
    'A=plain\n'
    'B="/home/u/OWCS KR Home"\n'
    "C='single quoted'\n"
    'D=/home/u/OWCS KR Home\n'
    'E=\n'
    'F="a#b"\n'
    'G=https://x.example/hook?a=1&b=2\n'
    'H=trailing   \n'
    'P=$HOME/x\n'
    'Q=""\n'
    'LAST=no newline'
)
WANT = {'A': 'plain', 'B': '/home/u/OWCS KR Home', 'C': 'single quoted', 'D': '/home/u/OWCS KR Home', 'E': '',
        'F': 'a#b', 'G': 'https://x.example/hook?a=1&b=2', 'H': 'trailing', 'P': '$HOME/x', 'Q': '',
        'LAST': 'no newline'}
BAD = {
    'crlf': ('A=1\r\nB=2\r\n', 'CRLF'),
    'export': ('export A=1\n', 'KEY=VALUE'),
    'spaces': ('A = 1\n', 'KEY=VALUE'),
    'unbalanced': ('A="abc\n', 'unbalanced'),
    'backslash': ('A=C:\\Users\\x\n', 'backslash'),
    'no equals': ('JUSTTEXT\n', 'KEY=VALUE'),
}


def test_python_parser_good():
    assert PU.parse_env_lines(GOOD.split('\n')) == WANT


@pytest.mark.parametrize('name', sorted(BAD))
def test_python_parser_bad(name):
    text, msg = BAD[name]
    with pytest.raises(ValueError, match=msg):
        PU.parse_env_lines(text.split('\n'))


def test_load_env_file_does_not_override(monkeypatch, tmp_path):
    f = tmp_path / '.env'
    f.write_bytes(b'OWCSKR_T1=from-file\nOWCSKR_T2="b c"\n')
    monkeypatch.setenv('OWCSKR_T1', 'already-set')
    monkeypatch.delenv('OWCSKR_T2', raising=False)
    PU.load_env_file(str(f))
    assert os.environ['OWCSKR_T1'] == 'already-set' and os.environ['OWCSKR_T2'] == 'b c'


def _bash():
    b = shutil.which('bash')
    if not b or 'system32' in b.lower():      # WSL's launcher is not the bash these scripts are tested with
        pytest.skip('no bash')
    return b


def run_env_sh(tmp_path, content: bytes):
    """source a copy of tools/env.sh next to a test .env and print the variables"""
    os.makedirs(tmp_path / 'tools', exist_ok=True)
    shutil.copy(os.path.join(HERE, 'tools', 'env.sh'), tmp_path / 'tools' / 'env.sh')
    (tmp_path / '.env').write_bytes(content)
    keys = ' '.join(WANT)
    script = '. tools/env.sh || exit 9; for k in ' + keys + '; do printf "%s=[%s]\\n" "$k" "${!k-<unset>}"; done'
    env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(tmp_path)}
    if os.name == 'nt':
        env['SYSTEMROOT'] = os.environ.get('SYSTEMROOT', '')
    return subprocess.run([_bash(), '-c', script], cwd=tmp_path, capture_output=True, text=True, env=env, timeout=60)


def test_env_sh_matches_python_parser(tmp_path):
    r = run_env_sh(tmp_path, GOOD.encode('utf-8'))
    assert r.returncode == 0, r.stderr
    got = dict(line.split('=', 1) for line in r.stdout.splitlines())
    assert got == {k: f'[{v}]' for k, v in WANT.items()}


@pytest.mark.parametrize('name', sorted(BAD))
def test_env_sh_refuses_what_python_refuses(tmp_path, name):
    text, msg = BAD[name]
    r = run_env_sh(tmp_path, text.encode('utf-8'))
    assert r.returncode != 0
    assert msg in r.stderr


def test_live_until_first_start_then_reused(monkeypatch, tmp_path):
    monkeypatch.setattr(PU, 'LIVE_DIR', str(tmp_path))
    now = datetime.datetime(2026, 10, 25, 14, 50, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
    iso, past = PU.live_until('2026-10-25', 6.5, now)
    assert iso == '2026-10-25T21:20:00+09:00' and not past
    later = now + datetime.timedelta(hours=2)
    assert PU.live_until('2026-10-25', 6.5, later) == (iso, False)        # restart: same end, not +6.5 h
    assert PU.live_until('2026-10-25', 6.5, now + datetime.timedelta(hours=7)) == (iso, True)


def test_live_until_rewrites_a_broken_file(monkeypatch, tmp_path):
    monkeypatch.setattr(PU, 'LIVE_DIR', str(tmp_path))
    os.makedirs(tmp_path / '2026-10-25')
    (tmp_path / '2026-10-25' / 'until.txt').write_text('garbage')
    now = datetime.datetime(2026, 10, 25, 15, 0, tzinfo=datetime.timezone.utc)
    assert PU.live_until('2026-10-25', 1, now) == ('2026-10-25T16:00:00+00:00', False)


def test_live_until_cli_bad_args(capsys):
    assert PU._cli(['live-until', 'x', '2026-10-25']) == 2
    assert PU._cli([]) == 2


def test_env_example_is_valid():
    with open(os.path.join(HERE, '.env.example'), encoding='utf-8') as f:   # a Windows checkout may have CRLF
        values = PU.parse_env_lines(f.read().split('\n'))
    assert {'OWCSKR_HC_DAILY', 'OWCSKR_HC_LIVE', 'OWCSKR_AUTOCOMMIT', 'OWCSKR_AUTOPUSH', 'GH_TOKEN'} <= set(values)
    assert values['OWCSKR_AUTOPUSH'] == '0'


def test_env_sh_site_dir_state(tmp_path):
    os.makedirs(tmp_path / 'site')
    out = []
    for value in ('', str(tmp_path / 'site').replace(os.sep, '/'), '/no/such/dir'):
        r = run_env_sh(tmp_path, f'OWCSKR_SITE_DIR="{value}"\n'.encode('utf-8'))
        assert r.returncode == 0, r.stderr
        script = '. tools/env.sh; site_dir_state; echo $?; hc_ping ""; echo ping=$?'
        r = subprocess.run([_bash(), '-c', script], cwd=tmp_path, capture_output=True, text=True, timeout=60,
                           env={'PATH': os.environ.get('PATH', ''), 'HOME': str(tmp_path)})
        out.append(r.stdout.split())
    assert out == [['1', 'ping=0'], ['0', 'ping=0'], ['2', 'ping=0']]
