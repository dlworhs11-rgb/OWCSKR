"""Windows / Linux differences in one place: folders, process checks, OBS locations, Tesseract, notifications.

Settings come from environment variables (on the server: .env in the repo root, loaded by the tools/*.sh scripts):
  OWCSKR_SITE_DIR         folder with the site recorders (score_watch.py, pick_watch.py, ...); empty = not on this machine
  OWCSKR_DISCORD_WEBHOOK  Discord webhook for alerts (match-day check, SOOP quality); empty = log only
  TESSERACT_CMD           tesseract binary when it is not on PATH
"""
import json, os, shutil, subprocess, sys, urllib.request

IS_WIN = os.name == 'nt'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DIR = os.path.join(ROOT, 'data', 'live')
_LEGACY_SITE_DIR = r'C:\Users\dlwor\Documents\Obsidian\LeeJaeGon\02_Projects\OWCS KR Home'   # the original capture PC
SITE_DIR = os.environ.get('OWCSKR_SITE_DIR') or (_LEGACY_SITE_DIR if IS_WIN and os.path.isdir(_LEGACY_SITE_DIR) else '')
OBS_PROC = 'obs64.exe' if IS_WIN else 'obs'


def process_running(name: str) -> bool:
    """is a process with this image name (obs64.exe / obs) running?"""
    if IS_WIN:
        out = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {name}'], capture_output=True, text=True).stdout
        return name.lower() in out.lower()
    return subprocess.run(['pgrep', '-x', name], capture_output=True).returncode == 0


def kill_process(name: str) -> None:
    if IS_WIN:
        subprocess.run(['taskkill', '/F', '/IM', name], capture_output=True)
    else:
        subprocess.run(['pkill', '-KILL', '-x', name], capture_output=True)


def python_cmdlines() -> str:
    """command lines of every running python process, one per line (to see which recorders are up)"""
    if IS_WIN:
        cmd = ['powershell', '-NoProfile', '-Command', "(Get-CimInstance Win32_Process -Filter \"name like 'python%'\").CommandLine"]
    else:
        cmd = ['ps', '-eo', 'args']
    out = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    return '\n'.join(line for line in out.splitlines() if 'python' in line.lower())


def obs_config_dir() -> str:
    """obs-studio settings folder: %APPDATA%\\obs-studio or ~/.config/obs-studio"""
    if IS_WIN:
        return os.path.join(os.environ.get('APPDATA', ''), 'obs-studio')
    return os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'obs-studio')


def obs_command() -> tuple[list[str], str | None]:
    """(argv prefix, working dir) that launches OBS"""
    if IS_WIN:
        d = r'C:\Program Files\obs-studio\bin\64bit'
        return [os.path.join(d, 'obs64.exe')], d
    return [shutil.which('obs') or '/usr/bin/obs'], None


def tesseract_cmd() -> str:
    win_default = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    return os.environ.get('TESSERACT_CMD') or shutil.which('tesseract') or (win_default if IS_WIN else 'tesseract')


def notify(title: str, text: str) -> None:
    """alert a person: Discord webhook when configured, a message box on a Windows desktop, always stderr"""
    print(f'[{title}] {text}', file=sys.stderr, flush=True)
    hook = os.environ.get('OWCSKR_DISCORD_WEBHOOK')
    if hook:
        body = json.dumps({'content': f'**{title}**\n{text}'[:1900]}).encode('utf-8')
        req = urllib.request.Request(hook, data=body, headers={'Content-Type': 'application/json', 'User-Agent': 'OWCSKR'})
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except Exception as e:
            print(f'notify: Discord webhook failed: {type(e).__name__} {e}', file=sys.stderr, flush=True)
    if IS_WIN and not hook:
        safe = text.replace("'", "''")
        ps = ('Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('
              f"'{safe}', '{title}', 'OK', 'Warning') | Out-Null")
        subprocess.Popen(['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', ps])
