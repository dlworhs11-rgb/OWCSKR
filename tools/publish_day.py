"""Upload one day's verified map stats to GitHub right away (data/manual/mapstats/<date>.json on main).
A push to this collector repo triggers no workflow: the site (owcs-kr) picks the file up at its next scheduled or
dispatched data build. The site UI is not touched.

usage: python -I tools/publish_day.py YYYY-MM-DD [--branch main] [--as YYYY-MM-DD]
- only maps with totalsVerified True (sums matched the team-totals page) and labelVerified not False
  (match/game label consistent) are uploaded
- a remote file that contains hand-checked maps (reading=manual) is never overwritten
- nothing is uploaded when the content did not change
exit: 0 uploaded / nothing to do, 1 GitHub request failed, 2 gh (GitHub CLI) not installed
"""
import base64, json, os, shutil, subprocess, sys

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


def gh(*args, data=None):
    r = subprocess.run([find_gh() or 'gh', 'api', *args], input=data, capture_output=True, text=True, encoding='utf-8')
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
    if not day['maps']:
        print(f'publish: no verified maps yet ({total} assembled)'); return 0
    day['date'] = target
    path = f'data/manual/mapstats/{target}.json'
    try:
        sha, remote = remote_file(path, branch)
    except RuntimeError as e:
        print('publish FAILED:', e, file=sys.stderr); return 1
    if remote is not None:
        if any(m.get('reading') == 'manual' for m in remote.get('maps', [])):
            print('publish: remote file has hand-checked maps - not overwritten'); return 0
        if remote == day:
            print('publish: unchanged'); return 0
    body = {'message': f'Live stats {target}: {len(day["maps"])} verified map(s)', 'branch': branch,
            'content': base64.b64encode(json.dumps(day, ensure_ascii=False, indent=1).encode('utf-8')).decode()}
    if sha: body['sha'] = sha
    code, out, err = gh('-X', 'PUT', f'repos/{REPO}/contents/{path}', '--input', '-', data=json.dumps(body))
    if code != 0:
        print('publish FAILED:', (err or out).strip()[:300], file=sys.stderr); return 1
    print(f'publish: uploaded {path} ({len(day["maps"])} of {total} maps) to {branch}')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace'); sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # names like 'Esperança'
    sys.exit(main())
