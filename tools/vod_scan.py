"""Scan a VOD (HLS) every STEP seconds in parallel, keep small frames, flag 'GAME DATA' screens by template match."""
import subprocess, sys, os, glob, json
from concurrent.futures import ThreadPoolExecutor
import cv2, numpy as np

URL = open('data/vod/.url').read().strip()
STEP, END = int(sys.argv[1]), int(sys.argv[2])
OUT = 'data/vod/scan4h'
REF = cv2.imread('data/vod/hi_3466.png')
REF = cv2.resize(REF, (960, 540), interpolation=cv2.INTER_AREA)
# crop: "GAME DATA / WEEK 2 DAY 3" block + "MATCH n GAME n / MAP" block
CROPS = {'title': (128, 48, 300, 95), 'game': (730, 55, 850, 95)}
def crop(img, c): x0, y0, x1, y1 = c; return img[y0:y1, x0:x1]

def grab(t):
    f = f'{OUT}/t_{t:05d}.jpg'
    if os.path.exists(f) and os.path.getsize(f) > 2000: return t
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', str(t), '-i', URL, '-frames:v', '1', '-vf', 'scale=960:-1', '-q:v', '4', f],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    return t

times = list(range(0, END, STEP))
with ThreadPoolExecutor(8) as ex:
    done = 0
    for _ in ex.map(grab, times):
        done += 1
        if done % 100 == 0: print('grabbed', done, '/', len(times), flush=True)

hits = []
rt = crop(REF, CROPS['title'])
for t in times:
    f = f'{OUT}/t_{t:05d}.jpg'
    if not os.path.exists(f): continue
    img = cv2.imread(f)
    if img is None or img.shape[:2] != (540, 960): continue
    s = cv2.matchTemplate(crop(img, CROPS['title']), rt, cv2.TM_CCOEFF_NORMED)[0][0]
    if s > 0.6: hits.append({'t': t, 'score': round(float(s), 3)})
json.dump(hits, open('data/vod/hits.json', 'w'))
print('GAME DATA hits:', len(hits))
print([(h['t'], h['score']) for h in hits])
