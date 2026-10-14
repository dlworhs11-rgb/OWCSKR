"""Find GAME DATA screens in a SOOP VOD part and save 1080p frames of the TABLE pages.
usage: python -I tools/vod_pipeline.py PART(1|2) START END TAG
  - scans every 15 s at 960px (parallel), template-matches the 'GAME DATA' title
  - classifies each hit as TABLE (per-player) or TOTALS (team sums)
  - extracts 1080p png for the first two TABLE frames and the first TOTALS frame of each map
"""
import subprocess, sys, os, json, cv2, numpy as np
from concurrent.futures import ThreadPoolExecutor

part, START, END, TAG = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
PAGE = 'https://vod.sooplive.com/player/209539901'
def urls(fmt): return subprocess.run(['yt-dlp', '--no-warnings', '-f', fmt, '-g', PAGE], capture_output=True, text=True).stdout.split()
LOW = urls('hls-hd')[part - 1]; HIGH = urls('hls-hd8k')[part - 1]
OUT = f'data/vod/{TAG}'; os.makedirs(OUT + '/scan', exist_ok=True); os.makedirs(OUT + '/frames', exist_ok=True)

def small(f): return cv2.resize(cv2.imread(f), (960, 540), interpolation=cv2.INTER_AREA)
REF_T, REF_S = small('data/vod/maps/m_3480.png'), small('data/vod/maps/m_9465.png')
TITLE = (slice(48, 95), slice(128, 300)); BODY = (slice(110, 460), slice(200, 900))

def grab(t):
    f = f'{OUT}/scan/t_{t:05d}.jpg'
    if not (os.path.exists(f) and os.path.getsize(f) > 2000):
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', str(t), '-i', LOW, '-frames:v', '1', '-vf', 'scale=960:-1', '-q:v', '4', f], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    return t

times = list(range(START, END, 15))
with ThreadPoolExecutor(8) as ex: list(ex.map(grab, times))

hits = []
for t in times:
    im = cv2.imread(f'{OUT}/scan/t_{t:05d}.jpg')
    if im is None or im.shape[:2] != (540, 960): continue
    if cv2.matchTemplate(im[TITLE], REF_T[TITLE], cv2.TM_CCOEFF_NORMED)[0][0] < 0.6: continue
    dt = np.abs(im[BODY].astype(np.float32) - REF_T[BODY]).mean(); ds = np.abs(im[BODY].astype(np.float32) - REF_S[BODY]).mean()
    hits.append({'t': t, 'page': 'TOTALS' if ds < dt else 'TABLE'})

clusters = []
for h in hits:
    if clusters and h['t'] - clusters[-1][-1]['t'] <= 30: clusters[-1].append(h)
    else: clusters.append([h])
jobs = []
for i, c in enumerate(clusters):
    tabs = [h['t'] for h in c if h['page'] == 'TABLE'][:2]; tots = [h['t'] for h in c if h['page'] == 'TOTALS'][:1]
    for k, t in enumerate(tabs): jobs.append((f'{OUT}/frames/m{i+1:02d}_table{k+1}_{t}.png', t))
    for t in tots: jobs.append((f'{OUT}/frames/m{i+1:02d}_totals_{t}.png', t))
def ext(j):
    f, t = j
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', str(t + 1), '-i', HIGH, '-frames:v', '1', f], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
with ThreadPoolExecutor(4) as ex: list(ex.map(ext, jobs))
json.dump({'part': part, 'clusters': [[h for h in c] for c in clusters]}, open(f'{OUT}/clusters.json', 'w'))
print(TAG, 'maps found:', len(clusters), 'frames:', len(jobs))
for i, c in enumerate(clusters): print(' map', i + 1, [(h['t'], h['page'][0]) for h in c])
