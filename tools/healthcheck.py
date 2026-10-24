"""Is the deployed site still being rebuilt? Reads owcs-ver.json of the live site and alerts when its build time is
older than 30 minutes during a match or 6 hours otherwise. Matches: data/site/matches.json plus the playoff matches
whose teams are still TBD (schedule_today.playoff_matches, from data/lp), which matches.json leaves out.
usage: python -I tools/healthcheck.py [--quiet] [--url https://owticker.com/]
  --quiet  no alert, no state change (run_daily.sh puts the result in its own summary); a failed read is tried
           once more after 30 s instead (a one-shot run has no "two in a row")
Run by run_daily.sh and, on match days, every 15 minutes by the owcskr-fresh-<date> timer / OWCSKR\\Freshness_<date>
task (schedule_today.py). One alert per stale spell (again after 3 h), one when it is fresh again. "Could not read
the site" alerts only from the 2nd failed read in a row (a network blip is not worth an alert and a "recovered").
Exit: 0 fresh, 1 stale, 2 could not read the site.

Which time: 'dataBuilt' of owcs-ver.json, the time of the last successful data build (owcs-kr P1-04). It does not move
when a build's data step fails and the old data is redeployed, so it catches "no builds" (trigger gone, Actions
broken) and "builds run, data stale" alike; 'buildFails' (failed data builds since) goes into the message when there.
A site deployed before that change has only 'checked' (time of the last site build, moves on every build, also a
failed one): then that is used, which catches "no builds" only."""
import datetime, json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_util as PU
import schedule_today as S

SITE = 'https://owticker.com/'
MATCHES = os.path.join(PU.ROOT, 'data', 'site', 'matches.json')
STATE = os.path.join(PU.LIVE_DIR, 'healthcheck.json')
MATCH_MAX = datetime.timedelta(minutes=30)
IDLE_MAX = datetime.timedelta(hours=6)
REALERT = datetime.timedelta(hours=3)
READ_FAILS_TO_ALERT = 2          # failed reads in a row before "could not read the site" alerts
QUIET_RETRY_SEC = 30


def fetch_version(site: str) -> dict:
    url = site.rstrip('/') + f'/owcs-ver.json?t={int(datetime.datetime.now().timestamp())}'   # past the Pages cache
    req = urllib.request.Request(url, headers={'User-Agent': 'OWCSKR-healthcheck', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


def built_at(ver: dict) -> datetime.datetime:
    """last successful data build (dataBuilt; checked on a site deployed before it existed); ValueError when missing"""
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


def match_list(now: datetime.datetime) -> list[dict]:
    """matches.json plus the TBD playoff matches of yesterday and today (KST; a capture runs past midnight)"""
    ms = load_matches()
    today = now.astimezone(S.KST).date()
    for day in (today - datetime.timedelta(days=1), today):
        try:
            ms += S.playoff_matches(day.isoformat())
        except (OSError, ValueError, TypeError, AttributeError) as e:
            print(f'healthcheck: playoff matches of {day} not read ({type(e).__name__}: {e})', file=sys.stderr)
    return ms


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


def _below_read_fail_limit(state: dict, unreadable: bool) -> bool:
    """count failed reads in a row in STATE; True while this one is still below READ_FAILS_TO_ALERT (no alert yet)"""
    if not unreadable:
        if state.pop('read_fails', None) is not None:
            _save_state(state)
        return False
    state['read_fails'] = state.get('read_fails', 0) + 1
    _save_state(state)
    if state['read_fails'] >= READ_FAILS_TO_ALERT:
        return False
    print(f"healthcheck: read failed ({state['read_fails']} in a row) - alerts from {READ_FAILS_TO_ALERT} in a row",
          file=sys.stderr)
    return True


def report(ok: bool, msg: str, now: datetime.datetime, site: str, unreadable: bool = False) -> None:
    """alert once per stale spell (again after REALERT) and once when it recovers; an unreadable site only from the
    READ_FAILS_TO_ALERT-th failed read in a row"""
    state = _state()
    if _below_read_fail_limit(state, unreadable):
        return
    last = state.get('alerted')
    if ok:
        if last:
            PU.notify('OWCSKR 사이트 갱신 회복', f'{site}: {msg}')
            _save_state({})
        return
    if last and now - datetime.datetime.fromisoformat(last) < REALERT:
        print(f'healthcheck: alert already sent at {last}', file=sys.stderr)
        return
    PU.notify('OWCSKR 사이트 갱신 멈춤', f'{site}: {msg}\n사이트 빌드(GitHub Actions pages.yml)를 확인해 주세요: '
              '사이트 저장소 README의 "빌드는 누가 일으키나" 참고.')
    _save_state(dict(state, alerted=now.isoformat(timespec='seconds')))


def read_built(site: str, fetch) -> tuple[datetime.datetime | None, str]:
    """(build time, note for the message: failed data builds since) or (None, why the site could not be read)"""
    try:
        ver = fetch(site)
        built = built_at(ver)
    except Exception as e:      # network, HTTP, JSON or field problem: the site is not readable
        return None, f'{type(e).__name__}: {e}'
    fails = ver.get('buildFails')
    return built, (f', {fails} failed data build(s) since' if isinstance(fails, int) and fails > 0 else '')


def main(argv: list[str] | None = None, now: datetime.datetime | None = None, fetch=fetch_version,
         sleep=time.sleep) -> int:
    argv = sys.argv[1:] if argv is None else argv
    quiet = '--quiet' in argv
    site = argv[argv.index('--url') + 1] if '--url' in argv[:-1] else (os.environ.get('OWCSKR_SITE_URL') or SITE)
    now = now or datetime.datetime.now().astimezone()
    built, info = read_built(site, fetch)
    if built is None and quiet:
        print(f'healthcheck: read failed ({info}) - trying again in {QUIET_RETRY_SEC} s', file=sys.stderr)
        sleep(QUIET_RETRY_SEC)
        built, info = read_built(site, fetch)
    if built is None:
        ok, msg, code = False, f'could not read owcs-ver.json: {info}', 2
    else:
        ok, msg = check(now, built, match_list(now))
        msg += info                                    # failed data builds since, if any
        code = 0 if ok else 1
    print(f"{now:%Y-%m-%d %H:%M:%S} healthcheck {'OK' if ok else 'STALE'} {site} {msg}")
    if not quiet:
        report(ok, msg, now, site, unreadable=code == 2)
    return code


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):     # Korean alert text into a log on a non-UTF-8 console
        stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        PU.load_env_file()
    except ValueError as e:
        print(f'healthcheck: .env not loaded: {e}', file=sys.stderr)
    sys.exit(main())
