"""Start-of-capture self-check: everything the capture -> OCR -> assemble -> publish chain needs on this machine.

usage: python -I tools/selfcheck.py [--notify]      exit 2 when a fatal problem was found, else 0
API:   check(root) -> [Problem(severity 'fatal'|'warn', item, detail)]; fatal(problems) -> the fatal ones
live_capture.py runs check() at start and exits 2 (with an alert) on any fatal problem.
"""
import glob, importlib.util, json, os, shutil, subprocess, sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_util as PU

ROOT = PU.ROOT
DIGITS = '0123456789'
REFERENCE_IMAGES = [
    ('data/vod/maps/m_3480.png', 'GAME DATA table reference (live_capture.classify)'),
    ('data/vod/maps/m_9465.png', 'team-totals reference (live_capture.classify)'),
    ('data/ref/ban_960.jpg', 'hero-ban screen reference (ocr_screens)'),
    ('data/ref/potm_960.jpg', 'POTM screen reference (ocr_screens)'),
]
WIN_TESSERACT = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


@dataclass(frozen=True)
class Problem:
    severity: str        # 'fatal' | 'warn'
    item: str
    detail: str

    def __str__(self) -> str:
        return f'{self.severity.upper()} {self.item}: {self.detail}'


def fatal(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.severity == 'fatal']


def _image_ok(path: str) -> bool:
    if not os.path.isfile(path) or os.path.getsize(path) == 0: return False
    import cv2
    return cv2.imread(path) is not None


def check_references(root: str) -> list[Problem]:
    return [Problem('fatal', rel, f'missing or unreadable: {what}') for rel, what in REFERENCE_IMAGES
            if not _image_ok(os.path.join(root, rel))]


def _labels(folder: str, label) -> list[str]:
    return [label(os.path.basename(f)[:-4]) for f in glob.glob(os.path.join(folder, '*.png'))]


def check_libs(root: str) -> list[Problem]:
    """name_lib, header_lib, digit_lib: present and non-empty (fatal); every digit 0-9 sampled (warn)"""
    out = []
    names = _labels(os.path.join(root, 'data', 'name_lib'), lambda b: b.split('__')[0])
    if not names: out.append(Problem('fatal', 'data/name_lib', 'empty or missing: every player name would be unknown'))
    header = _labels(os.path.join(root, 'data', 'header_lib'), lambda b: b.split('__')[0])
    hdigits = {h.split('_', 1)[1] for h in header if h.startswith('digit_')}
    bold = set(_labels(os.path.join(root, 'data', 'digit_lib'), lambda b: b.split('__')[0]))
    for rel, labels, digits in (('data/header_lib', header, hdigits), ('data/digit_lib', bold, bold)):
        if not labels:
            out.append(Problem('fatal', rel, 'empty or missing')); continue
        missing = [d for d in DIGITS if d not in digits]
        if missing: out.append(Problem('warn', rel, f'no sample of digit(s) {", ".join(missing)}'))
    return out


def _json_list(path: str) -> bool:
    try:
        with open(path, encoding='utf-8') as fh:
            return bool(json.load(fh))
    except (OSError, ValueError):
        return False


def check_data(root: str) -> list[Problem]:
    out = []
    for rel, what in (('data/manual/players.json', 'rosters (team of each panel)'),
                      ('data/site/matches.json', "the day's schedule and word lists (built by collector/build.mjs)")):
        if not _json_list(os.path.join(root, rel)): out.append(Problem('fatal', rel, f'missing, empty or invalid: {what}'))
    try:
        import glyph_models as GM
        sev, detail = GM.status(root)
    except Exception as e:
        sev, detail = 'fatal', f'{type(e).__name__}: {e}'
    if sev: out.append(Problem(sev, 'data/models', detail))
    return out


def _gh_token(gh: str, env, run) -> Problem | None:
    """None when a token is available. 'gh auth token' only reads the local login (no request): 'gh auth status' asks
    api.github.com and fails without network, and a fatal there (exit 2, never restarted) would lose the whole day.
    The token itself is never printed or kept."""
    if env.get('GH_TOKEN') or env.get('GITHUB_TOKEN'): return None
    try:
        r = run([gh, 'auth', 'token'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return Problem('warn', 'GitHub token', f'gh auth token could not run: {type(e).__name__}: {e}')
    if r.returncode == 0 and (r.stdout or '').strip(): return None
    err = (r.stderr or '').strip()
    if 'unknown command' in err:
        return Problem('warn', 'GitHub token', 'gh is too old for "gh auth token" - login not checked')
    return Problem('fatal', 'GitHub token', 'no GH_TOKEN and gh is not logged in (gh auth login)')


def check_tools(env=None, which=shutil.which, run=subprocess.run, find_spec=importlib.util.find_spec) -> list[Problem]:
    import publish_day as PD
    env = os.environ if env is None else env
    out = []
    gh = PD.find_gh(which)
    if not gh:
        out.append(Problem('fatal', 'gh', 'GitHub CLI not found: verified maps cannot be uploaded'))
    else:
        token = _gh_token(gh, env, run)
        if token: out.append(token)
    tess = env.get('TESSERACT_CMD') or which('tesseract') or (WIN_TESSERACT if PU.IS_WIN and os.path.isfile(WIN_TESSERACT) else None)
    if not tess or not (os.path.isfile(tess) or which(tess)):
        out.append(Problem('fatal', 'tesseract', 'Tesseract OCR binary not found (set TESSERACT_CMD or install it)'))
    if find_spec('pytesseract') is None:
        out.append(Problem('fatal', 'pytesseract', 'Python package missing (ban / POTM screens cannot be read)'))
    for tool in ('ffmpeg', 'yt-dlp'):
        if not which(tool): out.append(Problem('warn', tool, 'not found (needed only for the HLS frame source)'))
    return out


def check(root: str = ROOT, env=None, which=shutil.which, run=subprocess.run, find_spec=importlib.util.find_spec) -> list[Problem]:
    return check_references(root) + check_libs(root) + check_data(root) + check_tools(env, which, run, find_spec)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    problems = check()
    for p in problems: print(p)
    bad = fatal(problems)
    if bad and '--notify' in argv:
        PU.notify('OWCSKR 자가 점검 실패', '\n'.join(str(p) for p in bad))
    print('selfcheck:', f'{len(bad)} fatal, {len(problems) - len(bad)} warning(s)' if problems else 'OK')
    return 2 if bad else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
