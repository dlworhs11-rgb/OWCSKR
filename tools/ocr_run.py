"""Auto-read GAME DATA maps from extracted 1080p frames, verify against the team-totals page.
usage: python -I tools/ocr_run.py OUT.json FRAMEDIR [FRAMEDIR...]
Trains the glyph classifiers on the hand-checked maps in data/manual/mapstats/2026-10-11.json (7 maps)."""
import cv2, json, sys, glob, re, os
sys.path.insert(0, 'tools')
import ocr_table as TB, ocr_totals as TT

K = ['e', 'a', 'd', 'dmg', 'heal', 'mit']
gt = json.load(open('data/manual/mapstats/2026-10-11.json'))
TABLE_TRAIN = {1: 'data/vod/hi_3466.png', 2: 'data/vod/maps/m_5025.png', 3: 'data/vod/maps/m_6120.png', 4: 'data/vod/maps/m_8220.png', 5: 'data/vod/maps/m_9440.png', 6: 'data/vod/maps/m_12540.png', 7: 'data/vod/maps/m_14100.png'}
TOT_TRAIN = {i + 1: glob.glob(f'data/vod/p1a/frames/m0{i+1}_totals_*.png')[0] for i in range(7)}


mt = TB.Model(); mo = TB.Model()
for i, m in enumerate([x for x in gt['maps'] if x.get('reading', 'manual') == 'manual'], 1):
    im = cv2.imread(TABLE_TRAIN[i]); rows = [p for t in m['teams'].values() for p in t]
    for r, p in enumerate(rows):
        for c, k in enumerate(K):
            gl = TB.glyphs(TB.cell(im, r, c)); s = str(p[k])
            if len(gl) == len(s):
                for (x, f, wh), ch in zip(gl, s): mt.add(f, ch)
    imt = cv2.imread(TOT_TRAIN[i])
    for pi, rows_ in enumerate(m['teams'].values()):
        for k in ['e', 'd', 'dmg', 'heal', 'mit']:
            gl = TT.glyphs(imt, (pi, k)); s = str(sum(r[k] for r in rows_))
            if len(gl) == len(s):
                for (x, f), ch in zip(gl, s): mo.add(f, ch)
mt.fit(); mo.fit()

def read_table(im):
    rows, flags = [], []
    for r in range(10):
        row = {}
        for c, k in enumerate(K):
            gl = TB.glyphs(TB.cell(im, r, c))
            if not gl: row[k] = None; flags.append(f'r{r}.{k}:empty'); continue
            digits = ''.join(mt.predict(f)[0] for _, f, _ in gl)
            row[k] = int(digits)
        rows.append(row)
    return rows, flags

def read_totals(im):
    out = []
    for pi in (0, 1):
        t = {}
        for k in ['e', 'd', 'dmg', 'heal', 'mit']:
            gl = TT.glyphs(im, (pi, k))
            t[k] = int(''.join(mo.predict(f)[0] for _, f in gl)) if gl else None
        out.append(t)
    return out

results = []
for d in sys.argv[2:]:
    maps = sorted(set(re.match(r'm(\d+)_', os.path.basename(f)).group(1) for f in glob.glob(d + '/m*.png')))
    for mm in maps:
        tabs = sorted(glob.glob(f'{d}/m{mm}_table*.png')); tots = glob.glob(f'{d}/m{mm}_totals_*.png')
        reads = [read_table(cv2.imread(t)) for t in tabs]
        tot = read_totals(cv2.imread(tots[0])) if tots else None
        def sums_ok(rows):
            if not tot: return None
            for pi in (0, 1):
                part = rows[pi * 5:(pi + 1) * 5]
                for k in ['e', 'd', 'dmg', 'heal', 'mit']:
                    if any(p[k] is None for p in part) or sum(p[k] for p in part) != tot[pi][k]: return False
            return True
        verdicts = [sums_ok(r[0]) for r in reads]
        pick = next((i for i, v in enumerate(verdicts) if v), 0)          # first frame whose sums match the totals page
        rows = reads[pick][0]
        agree = len(reads) >= 2 and all(r[0] == reads[0][0] for r in reads)
        ok = verdicts[pick] if tot else (True if agree else None)
        used = os.path.basename(tabs[pick])
        results.append({'dir': d, 'map': mm, 'frame': used, 'framesAgree': agree, 'totalsOK': ok, 'rows': rows, 'totals': tot})
        print(d, 'map', mm, '| frame', used, '| frames agree:', agree, '| sums match totals page:', ok)
json.dump(results, open(sys.argv[1], 'w'), indent=1)
