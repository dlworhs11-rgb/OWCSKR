"""Start a site build during a match: 'gh workflow run pages.yml -R dlworhs11-rgb/owcs-kr' (P1-15).
The site is otherwise rebuilt by one outside trigger (cron-job.org with a personal token); this is the second one.
usage: python -I tools/dispatch_site.py [--until ISO]
  --until  end of the day's capture window: later runs do nothing (the timer keeps firing until the next morning)
Scheduled by schedule_today.py every 10 minutes from the capture start, only when OWCSKR_SITE_DISPATCH=1:
systemd timer owcskr-dispatch-<date> / task OWCSKR\\SiteDispatch_<date>. Checked again here, so setting it to 0 stops
the builds at once. Needs gh and GH_TOKEN with Actions: Read and write on the site repo (OWCSKR_SITE_REPO, default
dlworhs11-rgb/owcs-kr). Alerts after 3 failed dispatches in a row (again after 3 h), once when it works again.
Exit: 0 dispatched or nothing to do, 1 the dispatch failed, 2 bad arguments."""
import datetime, json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_util as PU

REPO = 'dlworhs11-rgb/owcs-kr'
WORKFLOW = 'pages.yml'
STATE = os.path.join(PU.LIVE_DIR, 'dispatch.json')
FAILS_TO_ALERT = 3
REALERT = datetime.timedelta(hours=3)


def enabled() -> bool:
    return os.environ.get('OWCSKR_SITE_DISPATCH', '0').strip() == '1'


def repo() -> str:
    return os.environ.get('OWCSKR_SITE_REPO') or REPO


def dispatch(run=subprocess.run) -> tuple[bool, str]:
    """(ok, gh's output or why it could not run)"""
    cmd = ['gh', 'workflow', 'run', WORKFLOW, '-R', repo()]
    try:
        r = run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f'{" ".join(cmd)}: {type(e).__name__}: {e}'
    out = ((r.stderr or '') + (r.stdout or '')).strip()
    return r.returncode == 0, f'{" ".join(cmd)}: exit {r.returncode} {out[:400]}'.strip()


def _state() -> dict:
    try:
        with open(STATE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, 'w', encoding='utf-8') as f:
        json.dump(state, f)


def report(ok: bool, detail: str, now: datetime.datetime) -> None:
    """count failures in a row; alert from FAILS_TO_ALERT (again after REALERT), once more when it works again"""
    state = _state()
    if ok:
        if state.get('alerted'):
            PU.notify('OWCSKR 사이트 빌드 호출 회복', detail)
        if state:
            _save_state({})
        return
    state['fails'] = state.get('fails', 0) + 1
    last = state.get('alerted')
    due = state['fails'] >= FAILS_TO_ALERT and not (last and now - datetime.datetime.fromisoformat(last) < REALERT)
    if due:
        PU.notify('OWCSKR 사이트 빌드 호출 실패',
                  f"{state['fails']}번 연속 실패: {detail}\nGH_TOKEN(사이트 저장소 Actions 쓰기 권한, 만료일)과 gh 설치를 확인해 주세요.")
        state['alerted'] = now.isoformat(timespec='seconds')
    _save_state(state)


def parse_until(argv: list[str]) -> datetime.datetime | None:
    """--until ISO (with offset) or None; ValueError when it is malformed"""
    if '--until' not in argv:
        return None
    i = argv.index('--until')
    if i + 1 >= len(argv):
        raise ValueError('--until needs a time')
    until = datetime.datetime.fromisoformat(argv[i + 1])
    if until.tzinfo is None:
        raise ValueError(f'--until {argv[i + 1]}: no UTC offset')
    return until


def main(argv: list[str] | None = None, now: datetime.datetime | None = None, run=subprocess.run) -> int:
    argv = sys.argv[1:] if argv is None else argv
    now = now or datetime.datetime.now().astimezone()
    try:
        until = parse_until(argv)
    except ValueError as e:
        print(f'dispatch_site: {e}', file=sys.stderr)
        return 2
    stamp = f'{now:%Y-%m-%d %H:%M:%S} dispatch_site'
    if not enabled():
        print(f'{stamp}: OWCSKR_SITE_DISPATCH is not 1 - nothing to do')
        return 0
    if until is not None and now > until:
        print(f'{stamp}: capture window over ({until.isoformat()}) - nothing to do')
        return 0
    ok, detail = dispatch(run)
    print(f"{stamp}: {'OK' if ok else 'FAILED'} {detail}")
    report(ok, detail, now)
    return 0 if ok else 1


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):     # Korean alert text into a log on a non-UTF-8 console
        stream.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
