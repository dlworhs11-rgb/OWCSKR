"""Capture a whole broadcast day through OBS and read every GAME DATA screen.

usage: python -I tools/live_capture.py [--url URL] [--date YYYY-MM-DD] [--hours 8] [--interval 10] [--idle-stop 75]

- starts OBS in the tray (dedicated 'OWCSKR' scene collection) unless it is already running with that collection;
  refuses to touch an OBS that is running with the user's own scene collection
- every --interval seconds grabs the OBS browser source; frames that are not GAME DATA screens are discarded
  immediately (nothing else is stored)
- per map keeps up to 3 TABLE frames and 1 TOTALS frame in data/live/<date>/frames; right after each map it runs
  ocr_run.py -> assemble_day.py -> publish_day.py, so verified stats reach GitHub (and the site data) within minutes
- stops after --hours, or when no GAME DATA screen was seen for --idle-stop minutes after at least one map
"""
import argparse, asyncio, datetime, json, os, subprocess, sys, time
import sys as _sys; _sys.stdout.reconfigure(encoding='utf-8', errors='replace'); _sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # logs may contain names like 'Esperança'
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import obs_setup
import ocr_screens as SCR
from obs_client import OBS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

def small(path): return cv2.resize(cv2.imread(path), (960, 540), interpolation=cv2.INTER_AREA)
REF_T, REF_S = small('data/vod/maps/m_3480.png'), small('data/vod/maps/m_9465.png')
TITLE = (slice(48, 95), slice(128, 300)); BODY = (slice(110, 460), slice(200, 900))


def classify(img):
    s = cv2.resize(img, (960, 540), interpolation=cv2.INTER_AREA)
    if cv2.matchTemplate(s[TITLE], REF_T[TITLE], cv2.TM_CCOEFF_NORMED)[0][0] < 0.6: return None
    dt = np.abs(s[BODY].astype(np.float32) - REF_T[BODY]).mean(); ds = np.abs(s[BODY].astype(np.float32) - REF_S[BODY]).mean()
    return 'TOTALS' if ds < dt else 'TABLE'


def update_and_publish(date, log, force_refresh=False):
    """after every map: assemble the day from what was read on screen and upload the verified maps.
    No Liquipedia request here - match/game/map/time come from the broadcast itself."""
    for script in ('tools/assemble_day.py', 'tools/publish_day.py'):
        r = subprocess.run([sys.executable, '-I', script, date], capture_output=True, text=True, encoding='utf-8')
        last = (r.stdout.strip().splitlines() or [r.stderr.strip()[-200:]])[-1]
        log('  ' + os.path.basename(script) + ':', last)


async def collection_ok():
    obs = await OBS().connect()
    cur = (await obs.call('GetSceneCollectionList'))['currentSceneCollectionName']
    await obs.close()
    return cur == obs_setup.COLLECTION


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=obs_setup.LIVE_URL)
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    ap.add_argument('--hours', type=float, default=8)
    ap.add_argument('--interval', type=float, default=5)
    ap.add_argument('--idle-stop', type=float, default=75, help='minutes without GAME DATA (after the first map) before stopping')
    a = ap.parse_args()

    out = os.path.join('data', 'live', a.date); frames = os.path.join(out, 'frames')
    os.makedirs(frames, exist_ok=True)
    logf = open(os.path.join(out, 'capture.log'), 'a', encoding='utf-8')
    def log(*x):
        line = time.strftime('%H:%M:%S ') + ' '.join(str(v) for v in x)
        print(line, flush=True); logf.write(line + '\n'); logf.flush()

    started_obs = False
    if obs_setup.running():
        if not asyncio.run(collection_ok()):
            log('OBS is already running with another scene collection - not touching it. Close OBS and retry.'); return 2
    else:
        started_obs = True
    obs_setup.start(a.url)
    log('capture start', a.url, 'hours', a.hours)
    try:
        asyncio.run(loop(a, frames, out, log))
    finally:
        if started_obs:
            subprocess.run(['taskkill', '/IM', 'obs64.exe'], capture_output=True)
            log('OBS closed')
    subprocess.run([sys.executable, '-I', 'tools/ocr_run.py', os.path.join(out, 'ocr.json'), frames], capture_output=True)
    if os.path.exists(os.path.join(out, 'ocr.json')):
        update_and_publish(a.date, log, force_refresh=True)
    log('done')


async def loop(a, frames, out, log):
    end = time.time() + a.hours * 3600
    obs = await OBS().connect()
    cluster, n, last_hit = None, 0, None
    other = {'BAN': [0.0, 0, 0], 'POTM': [0.0, 0, 0]}    # last time seen, frames kept, first timestamp of the current occurrence

    def finish(c):
        log(f"map {c['n']} closed: tables={c['tables']} totals={c['totals']}")
        r = subprocess.run([sys.executable, '-I', 'tools/ocr_run.py', os.path.join(out, 'ocr.json'), frames], capture_output=True, text=True)
        for line in r.stdout.strip().splitlines()[-1:]: log('  ocr:', line)
        update_and_publish(a.date, log)

    while time.time() < end:
        t0 = time.time()
        try:
            png = await obs.screenshot(obs_setup.SOURCE)
        except Exception as e:
            log('screenshot failed, reconnecting:', type(e).__name__)
            await asyncio.sleep(5)
            try: obs = await OBS().connect()
            except Exception: pass
            continue
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        kind = classify(img) if img is not None else None
        now = time.time()
        if kind:
            if cluster is None or now - cluster['last'] > 60:
                if cluster: finish(cluster)
                n += 1; cluster = {'n': n, 'last': now, 'tables': 0, 'totals': 0}
                log(f'map {n}: GAME DATA detected')
            cluster['last'] = now; last_hit = now
            ts = int(now)
            if kind == 'TABLE' and cluster['tables'] < 3:
                cluster['tables'] += 1
                cv2.imwrite(os.path.join(frames, f"m{n:02d}_table{cluster['tables']}_{ts}.png"), img)
            elif kind == 'TOTALS' and cluster['totals'] < 1:
                cluster['totals'] += 1
                cv2.imwrite(os.path.join(frames, f'm{n:02d}_totals_{ts}.png'), img)
        else:
            k2 = SCR.screen_kind(img) if img is not None else None
            if k2:
                last, kept, first = other[k2]
                if now - last > 40: kept, first = 0, int(now); log(f'{k2} screen detected')
                if kept < (4 if k2 == 'POTM' else 2):      # the POTM card animates in: keep a few frames, the name shows up later
                    cv2.imwrite(os.path.join(frames, f'{k2.lower()}_{first}_{kept + 1}.png'), img); kept += 1
                other[k2] = [now, kept, first]
                if k2 == 'POTM' and kept == 1: update_and_publish(a.date, log)      # POTM decides the match: publish now
            if cluster and now - cluster['last'] > 60:
                finish(cluster); cluster = None
        if last_hit and now - last_hit > a.idle_stop * 60:
            log(f'no GAME DATA for {a.idle_stop} min - broadcast day looks finished'); break
        await asyncio.sleep(max(0.0, a.interval - (time.time() - t0)))
    if cluster: finish(cluster)
    await obs.close()


if __name__ == '__main__':
    sys.exit(main() or 0)
