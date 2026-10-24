"""Windows / Linux differences in one place: folders, process checks, OBS locations, Tesseract, notifications.

Settings come from environment variables; .env in the repo root fills in the ones not set (read at import here,
and on the server also by the tools/*.sh scripts and the units' EnvironmentFile=):
  OWCSKR_SITE_DIR         folder with the site recorders (score_watch.py, pick_watch.py, ...); empty = not on this machine
  OWCSKR_DISCORD_WEBHOOK  Discord webhook for every notify() alert; empty = log only (+ a message box on Windows)
  OWCSKR_FRAME_SOURCE     obs (default) or hls: frame_source(), for the checks that skip OBS on an hls machine
  TESSERACT_CMD           tesseract binary when it is not on PATH

CLI (for the shell scripts):
  python -I tools/platform_util.py live-until HOURS DATE
      end time of that day's capture (ISO with offset) on stdout; kept in data/live/<DATE>/until.txt from the first
      start, so a restart ends at the same time. Exit 0 = still to come, 3 = already past, 2 = bad arguments.
"""
import datetime, json, os, re, shutil, subprocess, sys, urllib.request

IS_WIN = os.name == 'nt'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DIR = os.path.join(ROOT, 'data', 'live')
_LEGACY_SITE_DIR = r'C:\Users\dlwor\Documents\Obsidian\LeeJaeGon\02_Projects\OWCS KR Home'   # the original capture PC
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


def obs_installed() -> bool:
    """is OBS on this machine at all? (a server that reads the stream without OBS skips the OBS checks)"""
    cmd, _ = obs_command()
    return os.path.isfile(cmd[0]) or bool(shutil.which(cmd[0]))


FRAME_SOURCES = ('obs', 'hls')


def frame_source() -> str:
    """where the capture takes its frames: OWCSKR_FRAME_SOURCE=obs (default, OBS browser source) or hls (SOOP HLS
    through yt-dlp + ffmpeg, no OBS). An unknown value counts as obs, with a warning."""
    value = (os.environ.get('OWCSKR_FRAME_SOURCE') or 'obs').strip().lower()
    if value in FRAME_SOURCES:
        return value
    print(f'platform_util: OWCSKR_FRAME_SOURCE={value!r} is not obs or hls - using obs', file=sys.stderr)
    return 'obs'


KST = datetime.timezone(datetime.timedelta(hours=9))   # match days are Korean dates, whatever this machine's zone
DAY_START = {4: '17:00', 5: '15:00', 6: '15:00'}   # usual first-match time per weekday (same as the site's owcs_build.py)
DAY_START_OTHER = '19:00'


def match_start(date: str) -> tuple[datetime.datetime, bool]:
    """(start in KST, time known?) of a schedule date. Liquipedia's date-only matches come as 00:00 UTC (the collector's
    parseDate without a zone) or 00:00 KST: no start time yet, so the KST calendar date of that match at the weekday's
    usual first-match time (DAY_START, KST). Every other time is kept as written, in KST."""
    dt = datetime.datetime.fromisoformat(date)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    kst = dt.astimezone(KST)
    utc_midnight = dt.utcoffset() == datetime.timedelta(0) and (dt.hour, dt.minute) == (0, 0)
    if not utc_midnight and (kst.hour, kst.minute) != (0, 0):
        return kst, True
    h, mi = map(int, DAY_START.get(kst.weekday(), DAY_START_OTHER).split(':'))
    return kst.replace(hour=h, minute=mi, second=0, microsecond=0), False


def kst_day(date: str) -> str:
    """the Korean calendar date (YYYY-MM-DD) of a schedule date; '' when it is empty or not a date"""
    try:
        return match_start(date)[0].date().isoformat() if date else ''
    except (TypeError, ValueError):
        return ''


ENV_FILE = os.path.join(ROOT, '.env')
_ENV_KEY = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=(.*)')


def parse_env_lines(lines: list[str]) -> dict[str, str]:
    """.env as plain KEY=VALUE lines, the subset where tools/env.sh and systemd EnvironmentFile= read the same values:
    blank lines and '#' lines are skipped, a value fully inside "..." or '...' loses the quotes, no $ expansion.
    CR (a Windows-saved file), backslashes and unbalanced quotes are refused: the two readers would differ there."""
    out = {}
    for n, raw in enumerate(lines, 1):
        line = raw.rstrip('\n')
        if '\r' in line:
            raise ValueError(f'line {n}: CRLF line ending (save .env with LF: dos2unix .env)')
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        m = _ENV_KEY.fullmatch(line)
        if not m:
            raise ValueError(f'line {n}: not KEY=VALUE (no spaces around =, no "export")')
        key, val = m.group(1), m.group(2).strip(' \t')
        if '\\' in val:
            raise ValueError(f'line {n}: {key}: backslashes are not supported')
        if len(val) >= 2 and val[0] == val[-1] and val[0] in '"\'' and val[0] not in val[1:-1]:
            val = val[1:-1]
        elif val[:1] in ('"', "'"):
            raise ValueError(f'line {n}: {key}: unbalanced quote')
        out[key] = val
    return out


def load_env_file(path: str = ENV_FILE) -> dict[str, str]:
    """put .env values into os.environ where not already set (the tools/*.sh scripts and systemd units set them first);
    a missing file is fine, a malformed one raises ValueError"""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8', newline='') as f:
        values = parse_env_lines(f.read().split('\n'))
    for k, v in values.items():
        os.environ.setdefault(k, v)
    return values


# every python entry point sees .env, also on Windows where no env.sh / EnvironmentFile= loads it first
try:
    load_env_file()
except (OSError, ValueError) as _e:
    print(f'platform_util: .env not loaded: {_e}', file=sys.stderr)
SITE_DIR = os.environ.get('OWCSKR_SITE_DIR') or (_LEGACY_SITE_DIR if IS_WIN and os.path.isdir(_LEGACY_SITE_DIR) else '')


def live_until(day: str, hours: float, now: datetime.datetime | None = None) -> tuple[str, bool]:
    """(end time ISO, already past?) of DAY's capture. The first start writes now + HOURS to data/live/<day>/until.txt;
    later starts (restart after a crash, a reboot) reuse it, so a restart never extends the day."""
    now = now or datetime.datetime.now().astimezone()
    path = os.path.join(LIVE_DIR, day, 'until.txt')
    until = None
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            text = f.read().strip()
        try:
            until = datetime.datetime.fromisoformat(text)
            if until.tzinfo is None:
                raise ValueError('no UTC offset')
        except ValueError as e:
            print(f'live_until: ignoring bad {path} ({text!r}: {e})', file=sys.stderr)
            until = None
    if until is None:
        until = (now + datetime.timedelta(hours=hours)).replace(microsecond=0)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(until.isoformat())
    return until.isoformat(), until <= now


def _cli(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == 'live-until':
        try:
            hours = float(argv[1])
            datetime.date.fromisoformat(argv[2])
        except ValueError as e:
            print(f'live-until: bad HOURS or DATE: {e}', file=sys.stderr)
            return 2
        iso, past = live_until(argv[2], hours)
        print(iso)
        return 3 if past else 0
    print('usage: platform_util.py live-until HOURS DATE', file=sys.stderr)
    return 2


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
        safe, safe_title = text.replace("'", "''"), title.replace("'", "''")
        ps = ('Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('
              f"'{safe}', '{safe_title}', 'OK', 'Warning') | Out-Null")
        subprocess.Popen(['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', ps])


if __name__ == '__main__':
    sys.exit(_cli(sys.argv[1:]))
