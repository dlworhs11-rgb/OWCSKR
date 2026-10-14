"""Upload one day's verified map stats to GitHub right away (data/manual/mapstats/<date>.json on main).
The push triggers the deploy workflow, so the site data follows within ~2 minutes. The site UI is not touched.

usage: python -I tools/publish_day.py YYYY-MM-DD [--branch main] [--as YYYY-MM-DD]
- only maps whose sums matched the team-totals page are uploaded
- a remote file that contains hand-checked maps (reading=manual) is never overwritten
- nothing is uploaded when the content did not change
"""
import base64, json, os, shutil, subprocess, sys
import sys as _sys; _sys.stdout.reconfigure(encoding='utf-8', errors='replace'); _sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # logs may contain names like 'Esperança'

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
REPO = 'dlworhs11-rgb/OWCSKR'
GH = shutil.which('gh') or r'C:\Program Files\GitHub CLI\gh.exe'


def opt(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def gh(*args, data=None):
    r = subprocess.run([GH, 'api', *args], input=data, capture_output=True, text=True, encoding='utf-8')
    return r.returncode, r.stdout, r.stderr


def main():
    date = sys.argv[1]
    branch, target = opt('--branch', 'main'), opt('--as', date)
    src = os.path.join('data', 'live', date, 'mapstats.json')
    if not os.path.exists(src):
        print('publish: nothing assembled yet for', date); return 0
    day = json.load(open(src, encoding='utf-8'))
    day['maps'] = [m for m in day['maps'] if m.get('totalsVerified')]
    if not day['maps']:
        print('publish: no verified maps yet'); return 0
    day['date'] = target
    path = f'data/manual/mapstats/{target}.json'

    code, out, _ = gh(f'repos/{REPO}/contents/{path}?ref={branch}')
    sha = None
    if code == 0:
        cur = json.loads(out); sha = cur['sha']
        remote = json.loads(base64.b64decode(cur['content']).decode('utf-8'))
        if any(m.get('reading') == 'manual' for m in remote.get('maps', [])):
            print('publish: remote file has hand-checked maps - not overwritten'); return 0
        if remote == day:
            print('publish: unchanged'); return 0
    body = {'message': f'Live stats {target}: {len(day["maps"])} verified map(s)', 'branch': branch,
            'content': base64.b64encode(json.dumps(day, ensure_ascii=False, indent=1).encode('utf-8')).decode()}
    if sha: body['sha'] = sha
    code, out, err = gh('-X', 'PUT', f'repos/{REPO}/contents/{path}', '--input', '-', data=json.dumps(body))
    if code != 0:
        print('publish FAILED:', (err or out).strip()[:300]); return 1
    print(f'publish: uploaded {path} ({len(day["maps"])} maps) to {branch}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
