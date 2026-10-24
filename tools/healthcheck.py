"""Is the deployed site still being rebuilt? Reads owcs-ver.json of the live site and alerts when its build time is
older than 30 minutes during a match (from data/site/matches.json) or 6 hours otherwise.
usage: python -I tools/healthcheck.py [--quiet] [--url https://owticker.com/]
  --quiet  no alert, no state change (run_daily.sh puts the result in its own summary)
Run by run_daily.sh and, on match days, every 30 minutes by the owcskr-fresh-<date> timer / OWCSKR\\Freshness_<date>
task (schedule_today.py). One alert per stale spell (again after 3 h), one when it is fresh again.
Exit: 0 fresh, 1 stale, 2 could not read the site.

Which time: owcs-ver.json is {"v": content hash, "checked": time of the last full site build} (owcs-kr cloud_live.py).
'checked' moves on every build, also one whose data step failed and redeployed the old data, so this catches "no
builds" (cron trigger gone, Actions broken) but not "builds run, data stale". A 'dataBuilt' field (owcs-kr P1-04)
is used instead as soon as owcs-ver.json has it."""
import datetime, json, os, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_util as PU

SITE = 'https://owticker.com/'
MATCHES = os.path.join(PU.ROOT, 'data', 'site', 'matches.json')
STATE = os.path.join(PU.LIVE_DIR, 'healthcheck.json')
MATCH_MAX = datetime.timedelta(minutes=30)
IDLE_MAX = datetime.timedelta(hours=6)
REALERT = datetime.timedelta(hours=3)


def fetch_version(site: str) -> dict:
    url = site.rstrip('/') + f'/owcs-ver.json?t={int(datetime.datetime.now().timestamp())}'   # past the Pages cache
    req = urllib.request.Request(url, headers={'User-Agent': 'OWCSKR-healthcheck', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


def built_at(ver: dict) -> datetime.datetime:
    """build time from owcs-ver.json (dataBuilt once the site has it, else checked); ValueError when missing"""
    text = ver.get('dataBuilt') or ver.get('checked')
    if not text:
        raise ValueError(f'no dataBuilt/checked in owcs-ver.json: {ver!r:.200}')
    t = datetime.datetime.fromisoformat(text)
    return t if t.tzinfo else t.astimezone()


def load_matches(path: str = MATCHES) -> list[dict]:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f'healthcheck: no match list ({e}) - using the {IDLE_MAX} limit', file=sys.stderr)
        return []


def in_match_window(now: datetime.datetime, matches: list[dict]) -> bool:
    """a match is on (15 min before its start to its likely end + 30 min; a BO7 can run 4 h, a BO5 about 2.5 h)"""
    for m in matches:
        try:
            start = datetime.datetime.fromisoformat(m['date'])
        except (KeyError, TypeError, ValueError):
            continue
        length = datetime.timedelta(hours=4 if (m.get('bestof') or 5) >= 7 else 2.5)
        if start - datetime.timedelta(minutes=15) <= now <= start + length + datetime.timedelta(minutes=30):
            return True
    return False


def check(now: datetime.datetime, built: datetime.datetime, matches: list[dict]) -> tuple[bool, str]:
    window = in_match_window(now, matches)
    limit = MATCH_MAX if window else IDLE_MAX
    age = now - built
    minutes = int(age.total_seconds() // 60)
    msg = f"last build {built.isoformat(timespec='minutes')} ({minutes} min ago, limit {int(limit.total_seconds() // 60)} min{' - match on' if window else ''})"
    return age <= limit, msg


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


def report(ok: bool, msg: str, now: datetime.datetime, site: str) -> None:
    """alert once per stale spell (again after REALERT) and once when it recovers"""
    state = _state()
    last = state.get('alerted')
    if ok:
        if last:
            PU.notify('OWCSKR 사이트 갱신 회복', f'{site}: {msg}')
            _save_state({})
        return
    if last and now - datetime.datetime.fromisoformat(last) < REALERT:
        print(f'healthcheck: alert already sent at {last}', file=sys.stderr)
        return
    PU.notify('OWCSKR 사이트 갱신 멈춤', f'{site}: {msg}\n사이트 빌드(GitHub Actions pages.yml, cron-job.org 트리거)를 확인해 주세요.')
    _save_state({'alerted': now.isoformat(timespec='seconds')})


def main(argv: list[str] | None = None, now: datetime.datetime | None = None, fetch=fetch_version) -> int:
    argv = sys.argv[1:] if argv is None else argv
    quiet = '--quiet' in argv
    site = argv[argv.index('--url') + 1] if '--url' in argv[:-1] else (os.environ.get('OWCSKR_SITE_URL') or SITE)
    now = now or datetime.datetime.now().astimezone()
    try:
        built = built_at(fetch(site))
    except Exception as e:      # network, HTTP, JSON or field problem: the site is not readable
        ok, msg, code = False, f'could not read owcs-ver.json: {type(e).__name__}: {e}', 2
    else:
        ok, msg = check(now, built, load_matches())
        code = 0 if ok else 1
    print(f"{now:%Y-%m-%d %H:%M:%S} healthcheck {'OK' if ok else 'STALE'} {site} {msg}")
    if not quiet:
        report(ok, msg, now, site)
    return code


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):     # Korean alert text into a log on a non-UTF-8 console
        stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        PU.load_env_file()
    except ValueError as e:
        print(f'healthcheck: .env not loaded: {e}', file=sys.stderr)
    sys.exit(main())
