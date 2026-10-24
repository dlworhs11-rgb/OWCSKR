"""Upload one day's verified map stats to GitHub right away (data/manual/mapstats/<date>.json on main).
A push to this collector repo triggers no workflow: the site (owcs-kr) picks the file up at its next scheduled or
dispatched data build. The site UI is not touched.

usage: python -I tools/publish_day.py YYYY-MM-DD [--branch main] [--as YYYY-MM-DD]
- only maps with totalsVerified True (sums matched the team-totals page) and labelVerified not False
  (match/game label consistent) are uploaded
- a remote file that contains hand-checked maps (reading=manual) is never overwritten
- nothing is uploaded when the content did not change
- a sha conflict (HTTP 409 / 422: the daily job and the capture uploaded the same day at once) re-reads the remote
  file and tries again, at most SHA_RETRIES times, with the same manual / unchanged rules
- map entries are uploaded as assembled: fields this script does not know (e.g. matchKey) are kept
- when nothing is verified (any more), an existing remote file is rewritten with maps [] and matches [] (withdrawn)
exit: 0 uploaded / nothing to do, 1 GitHub request failed, 2 gh (GitHub CLI) not installed
"""
import base64, json, os, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_util as PU

ROOT = PU.ROOT
REPO = 'dlworhs11-rgb/OWCSKR'
WIN_GH = r'C:\Program Files\GitHub CLI\gh.exe'


def find_gh(which=shutil.which) -> str | None:
    """gh on PATH, else the default Windows install location; None when not installed"""
    found = which('gh')
    if found: return found
    return WIN_GH if PU.IS_WIN and os.path.isfile(WIN_GH) else None


def publishable(m: dict) -> bool:
    return m.get('totalsVerified') is True and m.get('labelVerified') is not False


def opt(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv else default


GH_TIMEOUT = 120    # s; live_capture runs this inside its capture loop: a hung request must not stop the frames for long
SHA_RETRIES = 2     # re-reads after a sha conflict
CONFLICT = re.compile(r'HTTP (409|422)(?!\d)')


def gh(*args, data=None, run=subprocess.run):
    try:
        r = run([find_gh() or 'gh', 'api', *args], input=data, capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=GH_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 1, '', f'gh api timed out after {GH_TIMEOUT} s'
    except OSError as e:
        return 1, '', f'gh could not run: {type(e).__name__}: {e}'
    return r.returncode, r.stdout, r.stderr


def remote_file(path, branch):
    """-> (sha, content) of the remote file, (None, None) when it does not exist; raises RuntimeError otherwise"""
    code, out, err = gh(f'repos/{REPO}/contents/{path}?ref={branch}')
    if code == 0:
        cur = json.loads(out)
        return cur['sha'], json.loads(base64.b64decode(cur['content']).decode('utf-8'))
    if '404' in (err or '') or 'Not Found' in (err or ''):
        return None, None
    raise RuntimeError(f'reading {path} failed: {(err or out).strip()[:300]}')


def main(argv=None, root=ROOT) -> int:
    argv = sys.argv[1:] if argv is None else argv
    date = argv[0]
    branch, target = opt(argv, '--branch', 'main'), opt(argv, '--as', date)
    if not find_gh():
        print('publish FAILED: gh (GitHub CLI) not found - install it (https://cli.github.com) or put it on PATH', file=sys.stderr)
        return 2
    src = os.path.join(root, 'data', 'live', date, 'mapstats.json')
    if not os.path.exists(src):
        print('publish: nothing assembled yet for', date); return 0
    with open(src, encoding='utf-8') as fh:
        day = json.load(fh)
    total = len(day['maps'])
    day['maps'] = [m for m in day['maps'] if publishable(m)]
    day['date'] = target
    if not day['maps']:
        day['matches'] = []          # nothing verified: no match results either (they come from the same maps)
    return upload(day, total, f'data/manual/mapstats/{target}.json', target, branch)


def upload(day: dict, total: int, path: str, target: str, branch: str) -> int:
    """PUT day to path unless unchanged or the remote holds hand-checked maps. With no verified map the remote file is
    only rewritten (withdrawn: maps []) when it exists - an earlier upload that a re-assembly no longer verifies
    (e.g. wrong match labels) must not stay on main and in the site's player totals.
    A sha conflict (someone else wrote the file between our read and our PUT) re-reads and retries."""
    for attempt in range(SHA_RETRIES + 1):
        rc, conflict = upload_once(day, total, path, target, branch, last=attempt == SHA_RETRIES)
        if conflict is None: return rc
        print(f'publish: sha conflict on {path} ({conflict[:120]}) - re-reading and retrying ({attempt + 1}/{SHA_RETRIES})')
    return 1


def upload_once(day: dict, total: int, path: str, target: str, branch: str, last: bool = True) -> tuple[int, str | None]:
    """one read + decide + PUT -> (exit code, None), or (1, error text) for a sha conflict worth a retry (not `last`)"""
    try:
        sha, remote = remote_file(path, branch)
    except RuntimeError as e:
        print('publish FAILED:', e, file=sys.stderr); return 1, None
    n = len(day['maps'])
    if remote is None and not n:
        print(f'publish: no verified maps yet ({total} assembled)'); return 0, None
    if remote is not None:
        if any(m.get('reading') == 'manual' for m in remote.get('maps', [])):
            print('publish: remote file has hand-checked maps - not overwritten'); return 0, None
        if remote == day or (not n and not remote.get('maps')):
            print('publish: unchanged'); return 0, None
    message = f'Live stats {target}: {n} verified map(s)' if n else f'Live stats {target}: 0 verified maps (withdrawn)'
    body = {'message': message, 'branch': branch,
            'content': base64.b64encode(json.dumps(day, ensure_ascii=False, indent=1).encode('utf-8')).decode()}
    if sha: body['sha'] = sha
    code, out, err = gh('-X', 'PUT', f'repos/{REPO}/contents/{path}', '--input', '-', data=json.dumps(body))
    if code != 0:
        why = (err or out).strip() or f'gh api PUT exit {code}'
        if CONFLICT.search(why) and not last: return 1, why
        print('publish FAILED:', why[:300], file=sys.stderr); return 1, None
    print(f'publish: uploaded {path} ({n} of {total} maps{", withdrawn" if not n else ""}) to {branch}')
    return 0, None


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace'); sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # names like 'Esperança'
    sys.exit(main())
