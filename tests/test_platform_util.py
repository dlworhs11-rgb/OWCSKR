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
