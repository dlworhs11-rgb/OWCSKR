"""(one-off) Seed the player-name crop library from the hand-checked maps and the OCR maps of 2026-10-11.
Library = data/name_lib/<Name>__<tag>.png (binarised name crops). Add a new player by saving a crop with their name."""
import cv2, json, os, sys, glob
sys.path.insert(0, os.path.dirname(__file__))
import ocr_names as N

LIB = 'data/name_lib'
os.makedirs(LIB, exist_ok=True)
gt = json.load(open('data/manual/mapstats/2026-10-11.json', encoding='utf-8'))
manual = {3466: 'data/vod/hi_3466.png', 5025: 'data/vod/maps/m_5025.png', 6120: 'data/vod/maps/m_6120.png', 8220: 'data/vod/maps/m_8220.png',
          9440: 'data/vod/maps/m_9440.png', 12540: 'data/vod/maps/m_12540.png', 14100: 'data/vod/maps/m_14100.png'}
ocr = {int(os.path.basename(f).rsplit('_', 1)[1].split('.')[0]): f for f in glob.glob('data/vod/p1b/frames/*table1*.png') + glob.glob('data/vod/p2/frames/*table1*.png')}
n = 0
for m in gt['maps']:
    f = manual.get(m['vodSec']) or ocr.get(m['vodSec'])
    if not f: print('no frame for', m['match'], m['game']); continue
    im = cv2.imread(f)
    names = [p['name'] for t in m['teams'].values() for p in t]
    for r, nm in enumerate(names):
        feat, _ = N.name_feat(im, r)
        if feat is None: continue
        cv2.imwrite(f'{LIB}/{nm}__{m["vodSec"]}_{r}.png', (feat * 255).astype('uint8')); n += 1
print('name crops saved:', n, '| distinct names:', len({os.path.basename(p).split('__')[0] for p in glob.glob(LIB + '/*.png')}))
