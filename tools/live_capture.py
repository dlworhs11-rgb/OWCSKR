"""Capture a whole broadcast day through OBS and read every GAME DATA screen.

usage: python -I tools/live_capture.py [--url URL] [--date YYYY-MM-DD] (--until ISO-DATETIME | --hours 8)
                                       [--interval 5] [--idle-stop 75]

- runs tools/selfcheck.py first: a fatal problem (missing reference image, library, token, tesseract ...) -> alert, exit 2
- starts OBS in the tray (dedicated 'OWCSKR' scene collection) unless it is already running with that collection;
  refuses to touch an OBS that is running with the user's own scene collection (exit 2)
- every --interval seconds grabs a frame from the frame source (default: the OBS browser source); frames that are not
  GAME DATA screens are discarded immediately (nothing else is stored)
- per map keeps up to 3 TABLE frames (seen >= 2 s after the first one, which may be mid-transition; that one is only a
  fallback) and up to 3 TOTALS frames (+0 / +5 / +10 s) in data/live/<date>/frames; right after each map it runs
  ocr_run.py -> assemble_day.py -> publish_day.py, so verified stats reach GitHub within minutes
- stops at --until (wins over --hours; a restart keeps the same end), on SIGTERM (after the final OCR and publish), or
  when no GAME DATA screen was seen for --idle-stop minutes after at least one map
- recovers by itself: loop errors are logged and skipped, the frame source is restarted after a minute of failed
  grabs or when OBS is gone, a frozen / black frame for 60 s refreshes the browser source; alerts go through
  platform_util.notify (each kind at most once per 15 min, also across restarts: data/live/<date>/alerts.json);
  an end-of-day summary is sent at the end
exit: 0 ok, 1 unexpected error (the capture crashed: systemd restarts it), 2 self-check failed or OBS busy,
      4 the capture ended (--until / idle stop / signal) but the final OCR / assemble / publish failed - alerted,
      and a restart would only capture an empty stream until --until (not restarted: RestartPreventExitStatus=2 4)
"""
import argparse, asyncio, datetime, glob, hashlib, json, os, re, signal, subprocess, sys, time, traceback

import cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import obs_setup
import platform_util as PU
import selfcheck
from obs_client import OBS

ROOT = PU.ROOT
REF_TABLE, REF_TOTALS = 'data/vod/maps/m_3480.png', 'data/vod/maps/m_9465.png'
TITLE = (slice(48, 95), slice(128, 300)); BODY = (slice(110, 460), slice(200, 900))
ALERT_PERIOD = 15 * 60          # one alert of a kind per 15 min
PARTIAL_ALERT_PERIOD = 24 * 3600  # the same 'map could not be read' message: once a day
ALERT_STATE = 'alerts.json'     # in data/live/<date>: alert times, kept across restarts
STEP_TIMEOUT = 30 * 60          # an OCR / assemble / publish step that hangs longer is killed
RESTART_AFTER = 60              # s of failed grabs before the frame source is restarted
DOWN_ALERT_AFTER = 3 * 60       # s of failed grabs (restarts included) before an alert
ERROR_ALERT_AFTER = 10          # the same loop error this many times -> one alert
TABLE_SETTLE = 2.0              # s after the first TABLE frame of a map before frames are kept
TOTALS_STEP = 5.0               # TOTALS frames at +0 / +5 / +10 s
MAX_TABLES = MAX_TOTALS = 3
SUMMARY_MARK = 'summary.txt'    # written once the end-of-day summary went out (a restart after the window resends none)
FINALIZE_FAILED = 4             # exit code: the day was captured, only the final steps failed
SUMMARY_NEAR_END = 5 * 60       # a crash / stop this close to --until has no successor run: it sends the summary itself
_REFS = None


def _small(img): return cv2.resize(img, (960, 540), interpolation=cv2.INTER_AREA)


def refs():
    global _REFS
    if _REFS is None:
        ims = [cv2.imread(os.path.join(ROOT, p)) for p in (REF_TABLE, REF_TOTALS)]
        if any(im is None for im in ims):
            raise FileNotFoundError(f'reference image missing: {REF_TABLE} / {REF_TOTALS}')
        _REFS = tuple(_small(im) for im in ims)
    return _REFS


def classify(img):
    ref_t, ref_s = refs()
    s = _small(img)
    if cv2.matchTemplate(s[TITLE], ref_t[TITLE], cv2.TM_CCOEFF_NORMED)[0][0] < 0.6: return None
    dt = np.abs(s[BODY].astype(np.float32) - ref_t[BODY]).mean(); ds = np.abs(s[BODY].astype(np.float32) - ref_s[BODY]).mean()
    return 'TOTALS' if ds < dt else 'TABLE'


def screens():
    import ocr_screens          # needs pytesseract: imported on first use so the module stays importable without it
    return ocr_screens


# ---- alerts and sub-steps -------------------------------------------------------------------------------------

class Alerter:
    """platform_util.notify, at most once per key per period. With `state` (a JSON file) the times survive a restart:
    systemd restarts a failed capture after a minute, and a limit kept only in memory alerted again on every start."""
    def __init__(self, notify=None, period=ALERT_PERIOD, clock=time.time, state=None):
        self.notify, self.period, self.clock, self.state = notify or PU.notify, period, clock, state
        self.last = self._load()

    def _load(self) -> dict:
        if not self.state: return {}
        try:
            with open(self.state, encoding='utf-8') as fh:
                return {str(k): float(v) for k, v in json.load(fh).items()}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def _save(self) -> None:
        if not self.state: return
        tmp = self.state + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as fh: json.dump(self.last, fh)
            os.replace(tmp, self.state)
        except OSError as e:
            print(f'alert state not saved ({self.state}): {e}', file=sys.stderr)

    def __call__(self, key: str, title: str, text: str, period: float | None = None) -> bool:
        now = self.clock()
        if key in self.last and now - self.last[key] < (self.period if period is None else period): return False
        self.last[key] = now
        self._save()
        try:
            self.notify(title, text)
        except Exception as e:                       # an alert must never stop the capture
            print(f'notify failed: {type(e).__name__}: {e}', file=sys.stderr)
        return True


def last_line(text: str) -> str:
    return (text.strip().splitlines() or [''])[-1]


def run_script(args, log, alert, timeout=STEP_TIMEOUT, partial_rc=None):
    """python -I <args> in the repo root; -> CompletedProcess, or None after logging + alerting a failure.
    partial_rc: the exit code of 'done, but something was left out' (ocr_run 1 = a map could not be read). ocr_run
    reads the whole day again after every map, so the same map fails every time: that is alerted once per message."""
    name = os.path.basename(args[0])
    try:
        r = subprocess.run([sys.executable, '-I', *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=timeout, cwd=ROOT)
    except (OSError, subprocess.SubprocessError) as e:
        log(f'  {name} FAILED to run:', type(e).__name__, e)
        alert(name, 'OWCSKR 캡처', f'{name} {" ".join(args[1:])} could not run: {type(e).__name__} {e}')
        return None
    if r.returncode == 0: return r
    tail = (r.stderr or '').strip()[-500:] or last_line(r.stdout or '')
    log(f'  {name} FAILED (exit {r.returncode}):', tail)
    text = f'{name} {" ".join(args[1:])} failed (exit {r.returncode}): {tail[-300:]}'
    if partial_rc is not None and r.returncode == partial_rc:
        alert(f'{name}:{last_line(r.stderr or "")[:200]}', 'OWCSKR 캡처', text, period=PARTIAL_ALERT_PERIOD)
    else:
        alert(name, 'OWCSKR 캡처', text)
    return None


def run_ocr(out, frames, log, alert) -> bool:
    r = run_script(['tools/ocr_run.py', os.path.join(out, 'ocr.json'), frames], log, alert, partial_rc=1)
    if r: log('  ocr:', last_line(r.stdout))
    return r is not None


def update_and_publish(date, log, alert) -> bool:
    """after every map: assemble the day from what was read on screen and upload the verified maps.
    No Liquipedia request here - match/game/map/time come from the broadcast itself."""
    for script in ('tools/assemble_day.py', 'tools/publish_day.py'):
        r = run_script([script, date], log, alert)
        if r is None: return False                   # a failed assembly must not be published from the old file
        log('  ' + os.path.basename(script) + ':', last_line(r.stdout))
    return True


# ---- frame source ---------------------------------------------------------------------------------------------

class ObsSource:
    """Default frame source: screenshots of the OWCSKR browser source over obs-websocket.
    Interface used by the loop: grab() -> BGR frame | None (undecodable), raises when no frame could be fetched;
    reconnect(), restart(), refresh() (reload the player), alive() -> bool, close()."""
    def __init__(self, url, log):
        self.url, self.log = url, log
        self.loop, self.obs, self.started = asyncio.new_event_loop(), None, False

    def _run(self, coro, timeout=45):
        return self.loop.run_until_complete(asyncio.wait_for(coro, timeout))

    def ready(self) -> bool:
        """False when OBS runs with the user's own scene collection (not ours to touch)"""
        if not obs_setup.running(): return True
        obs = self._run(OBS().connect())
        try:
            cur = self._run(obs.call('GetSceneCollectionList'))['currentSceneCollectionName']
        finally:
            self._run(obs.close(), 10)
        return cur == obs_setup.COLLECTION

    def start(self):
        if not obs_setup.running(): self.started = True
        try:
            obs_setup.start(self.url)
        except StopRequested:                        # SIGTERM while waiting for OBS: still a stop, not an error
            raise
        except SystemExit as e:                      # obs_setup gives up with SystemExit after ~2 min
            raise RuntimeError(str(e)) from None
        self.connect()

    def connect(self):
        self._close_ws()
        self.obs = self._run(OBS().connect())

    def grab(self):
        if self.obs is None: self.connect()
        png = self._run(self.obs.screenshot(obs_setup.SOURCE))
        return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)

    def reconnect(self):
        self.connect()

    def alive(self) -> bool:
        return obs_setup.running()

    def restart(self):
        self._close_ws()
        if self.started and self.alive():            # ours and hung: kill it so obs_setup.start launches a fresh one
            PU.kill_process(PU.OBS_PROC)
            for _ in range(20):
                if not self.alive(): break
                time.sleep(0.5)
        self.start()

    def refresh(self):
        if self.obs is None: self.connect()
        self._run(self.obs.call('PressInputPropertiesButton', {'inputName': obs_setup.SOURCE, 'propertyName': 'refreshnocache'}))

    def _close_ws(self):
        if self.obs is not None:
            try: self._run(self.obs.close(), 10)
            except Exception: pass
        self.obs = None

    def close(self):
        self._close_ws()
        if self.started:
            PU.kill_process(PU.OBS_PROC)             # tray mode turns a normal close into 'hide'
            self.log('OBS closed')
        self.loop.close()


class Grabber:
    """source.grab() with recovery: reconnect after a failure, restart after RESTART_AFTER s or when the source died"""
    def __init__(self, source, log, alert, clock=time.time, sleep=time.sleep):
        self.source, self.log, self.alert, self.clock, self.sleep = source, log, alert, clock, sleep
        self.fail_since = self.down_since = None

    def grab(self):
        """-> (True, frame or None) or (False, None) when no frame could be fetched"""
        try:
            img = self.source.grab()
        except Exception as e:
            self._failed(e); return False, None
        if self.down_since is not None: self.log(f'frame source back after {self.clock() - self.down_since:.0f} s')
        self.fail_since = self.down_since = None
        return True, img

    def _alive(self) -> bool:
        try: return self.source.alive()
        except Exception: return True

    def _failed(self, e):
        now = self.clock()
        if self.fail_since is None: self.fail_since = self.down_since = now
        self.log('screenshot failed, reconnecting:', type(e).__name__, str(e)[:120])
        if now - self.down_since >= DOWN_ALERT_AFTER:
            self.alert('frames-down', 'OWCSKR 캡처', f'no frame from the source for {now - self.down_since:.0f} s: {type(e).__name__} {e}'[:400])
        self.sleep(5)
        dead = not self._alive()
        if dead or now - self.fail_since >= RESTART_AFTER:
            self._restart('source process gone' if dead else f'failing for {now - self.fail_since:.0f} s')
            return
        try: self.source.reconnect()
        except Exception: pass

    def _restart(self, why):
        self.log('restarting the frame source:', why)
        try:
            self.source.restart(); self.log('frame source restarted')
        except Exception as e:
            self.log('frame source restart FAILED:', type(e).__name__, e)
            self.alert('restart', 'OWCSKR 캡처', f'frame source restart failed ({why}): {type(e).__name__} {e}'[:400])
        finally:
            # the next restart a full minute after this one ended: obs_setup.start waits up to 2 min, and counting
            # from its start killed a slow OBS again right after every failed wait
            self.fail_since = self.clock()


class FrozenDetector:
    """A frame that stays identical (stalled player, ended stream) or black: 'refresh' after `window` s and again every
    `refresh_every` s while it lasts, 'alert' once after `alert_after` s."""
    def __init__(self, window=60, alert_after=300, refresh_every=120, dark=8.0):
        self.window, self.alert_after, self.refresh_every, self.dark = window, alert_after, refresh_every, dark
        self.sig = self.last_t = self.since = self.refreshed = None
        self.alerted = False

    def update(self, img, now):
        sub = np.ascontiguousarray(img[::4, ::4])
        sig, dark = hashlib.md5(sub.tobytes()).hexdigest(), float(sub.mean()) < self.dark
        same, prev_t = sig == self.sig, self.last_t
        self.sig, self.last_t = sig, now
        if not (same or dark):
            self.since = self.refreshed = None; self.alerted = False
            return None
        if self.since is None: self.since = prev_t if same and prev_t is not None else now
        stale = now - self.since
        if stale >= self.alert_after and not self.alerted:
            self.alerted = True; return 'alert'
        if stale >= self.window and (self.refreshed is None or now - self.refreshed >= self.refresh_every):
            self.refreshed = now; return 'refresh'
        return None


# ---- per-frame capture logic ----------------------------------------------------------------------------------

def next_map_number(frames) -> int:
    # map numbers go on from frames already saved today: a restart mid-day reused m01.. and mixed two matches up
    return max([int(m.group(1)) for f in os.listdir(frames) for m in [re.match(r'm(\d+)_', f)] if m] or [0])


class Capture:
    """What to keep from each frame. on_map_closed() / on_publish() run OCR + assemble + publish."""
    def __init__(self, frames, log, on_map_closed, on_publish, interval=5.0, idle_stop=75.0):
        self.frames, self.log, self.on_map_closed, self.on_publish = frames, log, on_map_closed, on_publish
        self.interval, self.idle_stop = interval, idle_stop
        self.n, self.detected = next_map_number(frames), 0
        self.cluster, self.last_hit = None, None
        self.other = {'BAN': [0.0, 0, 0], 'POTM': [0.0, 0, 0]}    # last time seen, frames kept, first timestamp of the current occurrence
        self.potm_close = 0
        self.potm_tail = [0.0, 0, 0.0]   # POTM card: once the intro shows, also keep a frame every 3 s for 24 s - the name card no longer looks like the intro

    def save(self, name, img):
        if not cv2.imwrite(os.path.join(self.frames, name), img): self.log('could not write frame', name)

    def finish(self, c, process=True):
        if c['tables'] < MAX_TABLES and c['pending'] is not None:      # the first TABLE frame only fills a missing slot
            c['tables'] += 1; ts, img = c['pending']
            self.save(f"m{c['n']:02d}_table{c['tables']}_{ts}.png", img)
        c['pending'] = None
        self.log(f"map {c['n']} closed: tables={c['tables']} totals={c['totals']}")
        if process: self.on_map_closed()

    def close_cluster(self, process=True):
        c, self.cluster = self.cluster, None
        if c: self.finish(c, process)

    def handle(self, img, now):
        kind = classify(img) if img is not None else None
        if self.potm_close and now >= self.potm_close:
            self.potm_close = 0
            if self.cluster: self.close_cluster()      # finish() publishes already
            else: self.on_publish()
        if img is not None and now < self.potm_tail[0] and now - self.potm_tail[2] >= 1.5:
            self.potm_tail[1] += 1; self.potm_tail[2] = now
            self.save(f'potm_{self.other["POTM"][2]}_t{self.potm_tail[1]}.png', img)
        if kind: self._game_data(kind, img, now)
        else: self._other(img, now)

    def _game_data(self, kind, img, now):
        c = self.cluster
        if c is None or now - c['last'] > 60:
            self.close_cluster()
            self.n += 1; self.detected += 1
            c = self.cluster = {'n': self.n, 'last': now, 'tables': 0, 'totals': 0, 'first': {}, 'pending': None}
            self.log(f'map {self.n}: GAME DATA detected')
        c['last'] = now; self.last_hit = now
        ts, first = int(now), c['first'].setdefault(kind, now)
        if kind == 'TABLE' and c['tables'] < MAX_TABLES:
            if now - first < TABLE_SETTLE:            # may be mid fade / slide-in: kept only if nothing better comes
                if c['pending'] is None: c['pending'] = (ts, img)
                return
            c['tables'] += 1
            self.save(f"m{self.n:02d}_table{c['tables']}_{ts}.png", img)
        elif kind == 'TOTALS' and c['totals'] < MAX_TOTALS and now - first >= TOTALS_STEP * c['totals'] - 1:
            c['totals'] += 1
            self.save(f'm{self.n:02d}_totals_{ts}.png', img)

    def _other(self, img, now):
        k2 = screens().screen_kind(img) if img is not None else None
        if k2:
            last, kept, first = self.other[k2]
            if now - last > 40:
                kept, first = 0, int(now); self.log(f'{k2} screen detected')
                if k2 == 'POTM': self.potm_tail[:] = [now + 24, 0, now]
            if kept < (4 if k2 == 'POTM' else 2):      # the POTM card animates in: keep a few frames, the name shows up later
                self.save(f'{k2.lower()}_{first}_{kept + 1}.png', img); kept += 1
            self.other[k2] = [now, kept, first]
            if k2 == 'POTM' and kept == 1:            # the match is over: close the last map and publish once the name card is in
                self.potm_close = now + 26            # (OCR + publish take long: done now, they made the loop miss the name card)
        if self.cluster and now - self.cluster['last'] > 60 and now >= self.potm_tail[0]:
            self.close_cluster()

    def idle_over(self, now) -> bool:
        return bool(self.last_hit) and now - self.last_hit > self.idle_stop * 60

    def period(self, now) -> float:
        return 2 if now < self.potm_tail[0] else self.interval


# ---- loop -----------------------------------------------------------------------------------------------------

def paused(out) -> float:
    """caster_watch.py saw the waiting-screen countdown: seconds to rest (until 20 s before it ends)"""
    try:
        with open(os.path.join(out, 'pause.json'), encoding='utf-8') as fh:
            return max(0, json.load(fh)['until'] - 20 - time.time())
    except Exception:
        return 0


class ErrorCounter:
    def __init__(self, threshold=ERROR_ALERT_AFTER): self.threshold, self.counts = threshold, {}

    def record(self, sig) -> bool:
        """True exactly once per error signature, when it has happened `threshold` times"""
        self.counts[sig] = self.counts.get(sig, 0) + 1
        return self.counts[sig] == self.threshold


def watch_frozen(frozen, source, img, now, log, alert):
    act = frozen.update(img, now)
    if act == 'refresh':
        log('frame frozen or black for 60 s - refreshing the source')
        try: source.refresh()
        except Exception as e: log('refresh failed:', type(e).__name__, e)
    elif act == 'alert':
        alert('frozen', 'OWCSKR 캡처', 'the frame has been frozen or black for 5 min (stream down or player stuck)')


def step(cap, frozen, errors, source, img, now, log, alert):
    try:
        if img is not None: watch_frozen(frozen, source, img, now, log, alert)
        cap.handle(img, now)
    except Exception as e:
        sig = f'{type(e).__name__}: {e}'[:200]
        log('loop error (skipped):', traceback.format_exc().strip()[-1500:])
        if errors.record(sig):
            alert('loop:' + sig, 'OWCSKR 캡처', f'capture loop error x{errors.threshold}: {sig}')


def capture_loop(source, cap, end, out, log, alert, clock=time.time, sleep=time.sleep):
    grabber, frozen, errors = Grabber(source, log, alert, clock, sleep), FrozenDetector(), ErrorCounter()
    try:
        while clock() < end:
            t0 = clock()
            rest = paused(out)
            if rest:
                sleep(min(rest, 10)); continue
            ok, img = grabber.grab()
            if not ok: continue
            now = clock()
            step(cap, frozen, errors, source, img, now, log, alert)
            if cap.idle_over(now):
                log(f'no GAME DATA for {cap.idle_stop} min - broadcast day looks finished'); break
            sleep(max(0.0, cap.period(now) - (clock() - t0)))
    finally:
        cap.close_cluster(process=False)       # the final OCR + publish follows right after (finalize)


# ---- signals, arguments, end of day ---------------------------------------------------------------------------

_STOPPING = False


class StopRequested(SystemExit):
    """SIGTERM: told apart from obs_setup's SystemExit, which ObsSource turns into an error"""


def _on_sigterm(signum, frame):
    global _STOPPING
    if _STOPPING: return           # a second signal while finishing: let the final OCR / publish complete
    _STOPPING = True
    raise StopRequested(0)


def finishing():
    """from here on a SIGTERM must not cut the final OCR / publish short (systemd kills after TimeoutStopSec)"""
    global _STOPPING
    _STOPPING = True


def install_sigterm():
    signal.signal(signal.SIGTERM, _on_sigterm)


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=obs_setup.LIVE_URL)
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    ap.add_argument('--hours', type=float, default=None, help='capture length (default 8) when --until is not given')
    ap.add_argument('--until', type=datetime.datetime.fromisoformat, default=None,
                    help='end of the capture window, ISO with offset (e.g. 2026-10-25T23:30:00+09:00); wins over --hours')
    ap.add_argument('--interval', type=float, default=5)
    ap.add_argument('--idle-stop', type=float, default=75, help='minutes without GAME DATA (after the first map) before stopping')
    return ap.parse_args(argv)


def end_time(a, now: float) -> float:
    if a.until is not None: return a.until.timestamp()    # naive = local time
    return now + (8 if a.hours is None else a.hours) * 3600


def day_summary(out, frames) -> dict:
    """what the day produced: detected / read / verified / published maps, unknown names, POTM methods"""
    import publish_day as PD
    def load(name, default):
        try:
            with open(os.path.join(out, name), encoding='utf-8') as fh: return json.load(fh)
        except (OSError, ValueError): return default
    ocr, day = load('ocr.json', []), load('mapstats.json', {})
    detected = {m.group(1) for f in glob.glob(os.path.join(frames, 'm*_*.png')) for m in [re.match(r'm(\d+)_', os.path.basename(f))] if m}
    rows = [r for m in day.get('maps', []) for team in m.get('teams', {}).values() for r in team]
    unknown = sum(1 for r in rows if r.get('name') is None or str(r['name']).startswith('?'))
    return {'detected': len(detected), 'read': len(ocr), 'verified': sum(1 for e in ocr if e.get('totalsOK') is True),
            'published': sum(1 for m in day.get('maps', []) if PD.publishable(m)),
            'failed': [f"m{e['map']} ({e.get('verifyReason') or 'not verified'})" for e in ocr if e.get('totalsOK') is not True],
            'unknown': unknown, 'rows': len(rows),
            'potm': [f"{r.get('match')}: {(r.get('potm') or {}).get('method') or r.get('potmMethod') or 'none'}" for r in day.get('matches', [])]}


def summary_text(date, s) -> str:
    ratio = f"{s['unknown']}/{s['rows']} ({100 * s['unknown'] / s['rows']:.0f}%)" if s['rows'] else '-'
    return (f"{date}: maps {s['detected']} detected, {s['read']} read, {s['verified']} verified, {s['published']} published\n"
            f"unknown names {ratio}\n"
            f"not verified: {', '.join(s['failed']) or '-'}\n"
            f"POTM: {'; '.join(s['potm']) or '-'}")


def send_summary(date, out, frames, log, notify=None):
    notify = notify or PU.notify
    try:
        s = day_summary(out, frames)
    except Exception as e:
        log('summary failed:', type(e).__name__, e); return
    text = summary_text(date, s)
    log('summary:', text.replace('\n', ' | '))
    if s['detected'] == 0:
        notify('OWCSKR 캡처 경고', f'{date}: no GAME DATA screen was detected during the capture window\n' + text)
    else:
        notify('OWCSKR 하루 요약', text)
    try:
        with open(os.path.join(out, SUMMARY_MARK), 'w', encoding='utf-8') as fh: fh.write(text)
    except OSError as e:
        log('could not write', SUMMARY_MARK, e)


# ---- main -----------------------------------------------------------------------------------------------------

def finalize(a, out, frames, log, alert) -> int:
    ok = run_ocr(out, frames, log, alert)
    if os.path.exists(os.path.join(out, 'ocr.json')):
        ok = update_and_publish(a.date, log, alert) and ok
    return 0 if ok else 1


def preflight(log) -> bool:
    problems = selfcheck.check()
    for p in problems: log('selfcheck', p)
    bad = selfcheck.fatal(problems)
    if bad: PU.notify('OWCSKR 캡처 시작 실패', 'self-check failed:\n' + '\n'.join(str(p) for p in bad))
    return not bad


def capture(a, out, frames, log, alert, end, source) -> str:
    """the capture itself -> 'done' (--until / idle stop), 'stopped' (signal) or 'crashed'; the source is always closed"""
    def after_map():
        run_ocr(out, frames, log, alert)
        update_and_publish(a.date, log, alert)
    cap = Capture(frames, log, after_map, lambda: update_and_publish(a.date, log, alert), a.interval, a.idle_stop)
    try:
        source.start()
        log('capture start', a.url, 'until', datetime.datetime.fromtimestamp(end).astimezone().isoformat(timespec='seconds'))
        capture_loop(source, cap, end, out, log, alert)
        return 'done'
    except SystemExit:
        log('stop requested - finishing the day'); return 'stopped'
    except KeyboardInterrupt:
        log('interrupted - finishing the day'); return 'stopped'
    except Exception as e:
        log('capture FAILED:', traceback.format_exc().strip()[-1500:])
        alert('capture', 'OWCSKR 캡처', f'capture stopped by an error: {type(e).__name__} {e}'[:400])
        return 'crashed'
    finally:
        try: source.close()
        except Exception as e: log('closing the frame source failed:', type(e).__name__, e)


def summary_due(how, end, now, out) -> bool:
    """one summary per day, from the run that finishes it. A crash or a stop before the end (reboot, systemctl stop) is
    followed by a run that does, unless the window is (nearly) over: then run_live.sh starts nothing more."""
    if os.path.exists(os.path.join(out, SUMMARY_MARK)): return False
    return how == 'done' or now >= end - SUMMARY_NEAR_END


def source_busy(source, log, alert) -> int | None:
    """None when the capture may start, else the exit code: 2 = OBS runs with another scene collection (not ours to
    touch, a restart would not help), 1 = OBS runs but did not answer (systemd retries; alerted once per period)"""
    try:
        if source.ready(): return None
    except Exception as e:
        log('OBS is running but did not answer:', type(e).__name__, e)
        alert('obs-ready', 'OWCSKR 캡처 시작 실패', f'OBS is running but its websocket did not answer: {type(e).__name__} {e}'[:400])
        return 1
    log('OBS is already running with another scene collection - not touching it. Close OBS and retry.')
    PU.notify('OWCSKR 캡처 시작 실패', 'OBS is running with another scene collection - capture not started')
    return 2


def run(a, out, frames, log, alert, source_factory=ObsSource) -> int:
    end = end_time(a, time.time())
    if end <= time.time():           # restarted after the window: only redo the final OCR / publish
        log('capture window already over - final OCR and publish only')
        finishing()
        rc = FINALIZE_FAILED if finalize(a, out, frames, log, alert) != 0 else 0
        if not os.path.exists(os.path.join(out, SUMMARY_MARK)): send_summary(a.date, out, frames, log)
        return rc
    if not preflight(log): return 2
    source = source_factory(a.url, log)
    busy = source_busy(source, log, alert)
    if busy is not None: return busy
    how = capture(a, out, frames, log, alert, end, source)
    finishing()
    finalized = finalize(a, out, frames, log, alert) == 0
    rc = 1 if how == 'crashed' else (0 if finalized else FINALIZE_FAILED)
    if summary_due(how, end, time.time(), out): send_summary(a.date, out, frames, log)
    else: log(f'capture {how} - no summary from this run')
    log('done')
    return rc


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace'); sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # names like 'Esperança'
    a = parse_args(argv)
    os.chdir(ROOT)
    out = os.path.join('data', 'live', a.date); frames = os.path.join(out, 'frames')
    os.makedirs(frames, exist_ok=True)
    install_sigterm()
    with open(os.path.join(out, 'capture.log'), 'a', encoding='utf-8') as logf:
        def log(*x):
            line = time.strftime('%H:%M:%S ') + ' '.join(str(v) for v in x)
            print(line, flush=True); logf.write(line + '\n'); logf.flush()
        alert = Alerter(state=os.path.join(out, ALERT_STATE))
        try:
            return run(a, out, frames, log, alert)
        except SystemExit:
            log('stopped by signal'); return 0
        except Exception as e:
            log('FAILED:', traceback.format_exc().strip()[-1500:])
            alert('live_capture', 'OWCSKR 캡처', f'live_capture failed: {type(e).__name__} {e}'[:400])
            return 1


if __name__ == '__main__':
    sys.exit(main())
