import importlib, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import platform_util as PU


def test_tesseract_env_override(monkeypatch):
    monkeypatch.setenv('TESSERACT_CMD', '/opt/tess/bin/tesseract')
    assert PU.tesseract_cmd() == '/opt/tess/bin/tesseract'


def test_tesseract_from_path(monkeypatch):
    monkeypatch.delenv('TESSERACT_CMD', raising=False)
    monkeypatch.setattr(PU.shutil, 'which', lambda name: '/usr/bin/tesseract' if name == 'tesseract' else None)
    assert PU.tesseract_cmd() == '/usr/bin/tesseract'


def test_obs_config_dir_linux(monkeypatch):
    monkeypatch.setattr(PU, 'IS_WIN', False)
    monkeypatch.setenv('XDG_CONFIG_HOME', '/home/u/.config')
    assert PU.obs_config_dir() == os.path.join('/home/u/.config', 'obs-studio')


def test_obs_config_dir_windows(monkeypatch):
    monkeypatch.setattr(PU, 'IS_WIN', True)
    monkeypatch.setenv('APPDATA', 'C:/Users/u/AppData/Roaming')
    assert PU.obs_config_dir() == os.path.join('C:/Users/u/AppData/Roaming', 'obs-studio')


def test_site_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv('OWCSKR_SITE_DIR', str(tmp_path))
    assert importlib.reload(PU).SITE_DIR == str(tmp_path)
    monkeypatch.delenv('OWCSKR_SITE_DIR')
    importlib.reload(PU)


def test_process_running_false_for_unknown_name():
    assert PU.process_running('owcskr-no-such-process-xyz') is False


def test_notify_posts_to_discord(monkeypatch, capsys):
    sent = {}

    class Resp:
        def close(self): pass

    def fake_urlopen(req, timeout):
        sent['url'], sent['body'] = req.full_url, json.loads(req.data)
        return Resp()

    monkeypatch.setenv('OWCSKR_DISCORD_WEBHOOK', 'https://discord.example/hook')
    monkeypatch.setattr(PU.urllib.request, 'urlopen', fake_urlopen)
    PU.notify('제목', '본문')
    assert sent['url'] == 'https://discord.example/hook'
    assert sent['body']['content'] == '**제목**\n본문'
    assert '[제목] 본문' in capsys.readouterr().err


def test_notify_webhook_failure_is_logged_not_raised(monkeypatch, capsys):
    def boom(req, timeout): raise OSError('network down')

    monkeypatch.setenv('OWCSKR_DISCORD_WEBHOOK', 'https://discord.example/hook')
    monkeypatch.setattr(PU.urllib.request, 'urlopen', boom)
    PU.notify('t', 'x')
    assert 'Discord webhook failed' in capsys.readouterr().err


def test_notify_without_webhook_on_linux_only_logs(monkeypatch, capsys):
    monkeypatch.delenv('OWCSKR_DISCORD_WEBHOOK', raising=False)
    monkeypatch.setattr(PU, 'IS_WIN', False)
    monkeypatch.setattr(PU.subprocess, 'Popen', lambda *a, **k: (_ for _ in ()).throw(AssertionError('no popup on Linux')))
    PU.notify('t', 'x')
    assert '[t] x' in capsys.readouterr().err


def test_notify_message_box_escapes_quotes_in_the_title(monkeypatch):
    """PowerShell single-quoted strings: a ' in the title must be doubled, like the one in the text"""
    started = []
    monkeypatch.delenv('OWCSKR_DISCORD_WEBHOOK', raising=False)
    monkeypatch.setattr(PU, 'IS_WIN', True)
    monkeypatch.setattr(PU.subprocess, 'Popen', lambda cmd, **k: started.append(cmd))
    PU.notify("it's down", "can't read")
    script = started[0][-1]
    assert "'it''s down'" in script and "'can''t read'" in script


def test_frame_source(monkeypatch, capsys):
    monkeypatch.delenv('OWCSKR_FRAME_SOURCE', raising=False)
    assert PU.frame_source() == 'obs'
    monkeypatch.setenv('OWCSKR_FRAME_SOURCE', ' HLS ')
    assert PU.frame_source() == 'hls'
    monkeypatch.setenv('OWCSKR_FRAME_SOURCE', 'ffmpeg')
    assert PU.frame_source() == 'obs' and 'not obs or hls' in capsys.readouterr().err


def _import_with_env(tmp_path, content: bytes, **env):
    """import a copy of platform_util next to a test .env, in a fresh interpreter"""
    import shutil, subprocess
    (tmp_path / 'tools').mkdir(exist_ok=True)
    shutil.copy(PU.__file__, tmp_path / 'tools' / 'platform_util.py')
    (tmp_path / '.env').write_bytes(content)
    code = 'import os, platform_util as P; print(os.environ.get("OWCSKR_HC_LIVE"), P.SITE_DIR)'
    clean = {k: v for k, v in os.environ.items() if not k.startswith('OWCSKR_')}
    return subprocess.run([sys.executable, '-c', code], cwd=tmp_path / 'tools', capture_output=True, text=True,
                          env=dict(clean, **env), timeout=60)


def test_env_file_is_read_at_import(tmp_path):
    r = _import_with_env(tmp_path, b'OWCSKR_HC_LIVE=https://hc.example/x\nOWCSKR_SITE_DIR="/srv/OWCS KR Home"\n')
    assert r.stdout.split(None, 1) == ['https://hc.example/x', '/srv/OWCS KR Home\n']


def test_env_file_never_overrides_and_a_bad_one_only_warns(tmp_path):
    r = _import_with_env(tmp_path, b'OWCSKR_HC_LIVE=from-file\r\n')
    assert r.returncode == 0 and r.stdout.startswith('None ')    # CRLF file: refused as a whole, nothing set
    assert '.env not loaded' in r.stderr
    r = _import_with_env(tmp_path, b'OWCSKR_HC_LIVE=from-file\n', OWCSKR_HC_LIVE='already')
    assert r.stdout.startswith('already ')
