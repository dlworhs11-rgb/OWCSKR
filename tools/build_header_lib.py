"""Seed data/header_lib from the 12 maps of 2026-10-11 (match/game digits, map-time digits, map-name crops)."""
import cv2, glob, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import ocr_header as H
os.makedirs(H.HEADER_LIB, exist_ok=True)
gt = json.load(open('data/manual/mapstats/2026-10-11.json', encoding='utf-8'))
manual = {3466: 'data/vod/hi_3466.png', 5025: 'data/vod/maps/m_5025.png', 6120: 'data/vod/maps/m_6120.png', 8220: 'data/vod/maps/m_8220.png',
          9440: 'data/vod/maps/m_9440.png', 12540: 'data/vod/maps/m_12540.png', 14100: 'data/vod/maps/m_14100.png'}
ocr = {int(os.path.basename(f).rsplit('_', 1)[1].split('.')[0]): f for f in glob.glob('data/vod/p1b/frames/*table1*.png') + glob.glob('data/vod/p2/frames/*table1*.png')}
NAMES = {'Esperanca': 'Esperança'}
order, n = [], 0
for m in gt['maps']:
    if m['match'] not in order: order.append(m['match'])
for m in gt['maps']:
    im = cv2.imread(manual.get(m['vodSec']) or ocr[m['vodSec']])
    p = H.header_parts(im); tag = str(m['vodSec'])
    match_no = order.index(m['match']) + 1
    labels = [(str(match_no), p['match']), (str(m['game']), p['game'])]
    t = m['mapTime'].replace(':', ''); labels += list(zip(t, p['time'][0]))
    for i, (lb, fs) in enumerate(labels):
        for j, f in enumerate(fs if isinstance(fs, list) else [fs]):
            H.imwrite_u(f'{H.HEADER_LIB}/digit_{lb}__{tag}_{i}{j}.png', (f * 255).astype('uint8')); n += 1
    name = NAMES.get(m['map'], m['map'])
    H.imwrite_u(f'{H.HEADER_LIB}/map_{name}__{tag}.png', (p['map'] * 255).astype('uint8')); n += 1
print('header crops saved:', n)
