"""One-shot check: grab the OBS browser source as an image and test the GAME DATA detector on it.
usage: python -I tools/obs_snap.py [count] [interval_s]   -> data/live/snap_*.png + data/live/snap_report.txt"""
import asyncio, os, sys, time
import sys as _sys; _sys.stdout.reconfigure(encoding='utf-8', errors='replace'); _sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # logs may contain names like 'Esperança'
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from obs_client import OBS

SOURCE = 'SOOP'
REF = cv2.resize(cv2.imread('data/vod/maps/m_3480.png'), (960, 540), interpolation=cv2.INTER_AREA)
TITLE = (slice(48, 95), slice(128, 300))


def score(img):
    s = cv2.resize(img, (960, 540), interpolation=cv2.INTER_AREA)
    return float(cv2.matchTemplate(s[TITLE], REF[TITLE], cv2.TM_CCOEFF_NORMED)[0][0])


async def main(count, interval):
    os.makedirs('data/live', exist_ok=True)
    obs = await OBS().connect()
    lines = []
    for k in range(count):
        png = await obs.screenshot(SOURCE)
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        f = f'data/live/snap_{k:02d}.png'
        cv2.imwrite(f, img)
        line = f'{time.strftime("%H:%M:%S")} {f} size={img.shape[1]}x{img.shape[0]} mean_brightness={img.mean():.1f} gamedata_score={score(img):.3f}'
        print(line, flush=True); lines.append(line)
        if k < count - 1: await asyncio.sleep(interval)
    await obs.close()
    open('data/live/snap_report.txt', 'w', encoding='utf-8').write('\n'.join(lines) + '\n')

if __name__ == '__main__':
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3, float(sys.argv[2]) if len(sys.argv) > 2 else 10))
