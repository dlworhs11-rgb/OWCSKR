"""Auto-read GAME DATA maps from extracted 1080p frames, verify against the team-totals page.
usage: python -I tools/ocr_run.py OUT.json FRAMEDIR [FRAMEDIR...]
Glyph classifiers come from data/models/*.npz (tools/glyph_models.py; rebuilt there when the training inputs changed).

Per map every table frame x every totals frame is tried; the map passes when any pair's sums match.
- totalsOK: True = sums match, False = totals frame(s) present but no pair matches, None = no totals frame
- framesAgree: all table frames read the same (not a verification: a still screen repeats the same misreading)
- a (assists) is not on the totals page: kept only when >= 2 table frames read the same value, else null (aVerified)
- verifyFailed: totalsOK is not True (the map is not published); verifyReason says why
exit: 0 ok, 1 some map could not be read (ocr.json still written), 2 no glyph models
"""
import glob, json, os, re, sys, traceback
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_table as TB, ocr_totals as TT

K = ['e', 'a', 'd', 'dmg', 'heal', 'mit']
VERIFIED_FIELDS = ['e', 'd', 'dmg', 'heal', 'mit']
_MODELS = None


def models() -> tuple:
    """(table model, totals model), loaded once per process - importing this module trains nothing"""
    global _MODELS
    if _MODELS is None:
        import glyph_models as GM
        _MODELS = GM.get_models(log=lambda *x: print(*x, file=sys.stderr))
    return _MODELS


def read_table(im):
    mt = models()[0]
    rows, flags = [], []
    for r in range(10):
        row = {}
        for c, k in enumerate(K):
            gl = TB.glyphs(TB.cell(im, r, c))
            if not gl: row[k] = None; flags.append(f'r{r}.{k}:empty'); continue
            row[k] = int(''.join(mt.predict(f)[0] for _, f, _ in gl))
        rows.append(row)
    return rows, flags


def read_totals(im):
    mo = models()[1]
    out = []
    for pi in (0, 1):
        t = {}
        for k in ['e', 'd', 'dmg', 'heal', 'mit', 'dpm', 'hpm']:
            gl = TT.glyphs(im, (pi, k))
            t[k] = int(''.join(mo.predict(f)[0] for _, f in gl)) if gl else None
        out.append(t)
    return out


def map_duration(tot):
    """map length from the totals page: damage / (damage per minute), same for healing, both teams.
    Returns (seconds, 'M:SS') or (None, None) when the four estimates disagree by more than 3 s."""
    est = [t[a] / t[b] * 60 for t in tot for a, b in (('dmg', 'dpm'), ('heal', 'hpm')) if t.get(a) and t.get(b)]
    if len(est) < 2 or max(est) - min(est) > 3: return None, None
    est.sort(); sec = round(est[len(est) // 2])
    return sec, f'{sec // 60}:{sec % 60:02d}'


def sums_ok(rows, tot) -> bool:
    """each team's E, D, DMG, HEAL, MIT column sums equal the totals page"""
    for pi in (0, 1):
        part = rows[pi * 5:(pi + 1) * 5]
        for k in VERIFIED_FIELDS:
            if any(p[k] is None for p in part) or sum(p[k] for p in part) != tot[pi][k]: return False
    return True


def verify(reads, tots):
    """-> (table index, totals index, totalsOK): the first table x totals pair whose sums match"""
    if not tots: return 0, None, None
    for ti, rows in enumerate(reads):
        for oi, tot in enumerate(tots):
            if sums_ok(rows, tot): return ti, oi, True
    return 0, 0, False


def agreed_assists(reads, rows):
    """rows with 'a' = the value >= 2 table frames agree on, else None; -> (rows, every row agreed)"""
    out = []
    for r, row in enumerate(rows):
        votes = Counter(rd[r]['a'] for rd in reads if rd[r]['a'] is not None).most_common(2)
        top = votes[0] if votes and votes[0][1] >= 2 and (len(votes) == 1 or votes[1][1] < votes[0][1]) else None
        out.append({**row, 'a': top[0] if top else None})
    return out, all(row['a'] is not None for row in out)


def assess(reads, tots) -> dict:
    """the verification fields of one map from its table reads and totals reads"""
    ti, oi, ok = verify(reads, tots)
    rows, a_ok = agreed_assists(reads, reads[ti])
    reason = None if ok else ('no totals frame' if ok is None else 'sums do not match the totals page')
    return {'pick': ti, 'totIndex': oi, 'totalsOK': ok, 'framesAgree': len(reads) >= 2 and all(r == reads[0] for r in reads),
            'rows': rows, 'aVerified': a_ok, 'verifyFailed': ok is not True, 'verifyReason': reason}


def _frames(pattern):
    """[(path, image)] for the readable files matching pattern, sorted by name"""
    import cv2
    out = []
    for f in sorted(glob.glob(pattern)):
        im = cv2.imread(f)
        if im is None: print(f'ocr_run: unreadable frame {f} - skipped', file=sys.stderr); continue
        out.append((f, im))
    return out


def read_map(d, mm, hlib):
    import ocr_header as HD
    tabs = _frames(f'{d}/m{mm}_table*.png')
    if not tabs: return None
    tot_files = _frames(f'{d}/m{mm}_totals_*.png')
    reads = [read_table(im)[0] for _, im in tabs]
    tots = [read_totals(im) for _, im in tot_files]
    v = assess(reads, tots)
    tot = tots[v['totIndex']] if v['totIndex'] is not None else None
    used = os.path.basename(tabs[v['pick']][0])
    header = HD.read_header(tabs[v['pick']][1], hlib)
    sec, mt = map_duration(tot) if tot else (None, None)
    print(d, 'map', mm, '| frame', used, '| sums match totals page:', v['totalsOK'], f'({len(tabs)} table x {len(tots)} totals)',
          '| header', header.get('match'), header.get('game'), header.get('map'), '| time', mt)
    return {'dir': d, 'map': mm, 'frame': used, 'framesAgree': v['framesAgree'], 'totalsOK': v['totalsOK'], 'rows': v['rows'],
            'totals': tot, 'header': header, 'durationSec': sec, 'mapTime': mt,
            'totalsFrame': os.path.basename(tot_files[v['totIndex']][0]) if tot else None,
            'verifiedFields': VERIFIED_FIELDS, 'aVerified': v['aVerified'], 'verifyFailed': v['verifyFailed'], 'verifyReason': v['verifyReason']}


def main(out_path, dirs) -> int:
    import glyph_models as GM, ocr_header as HD
    try:
        models()
    except GM.ModelError as e:
        print('ocr_run FAILED:', e, file=sys.stderr); return 2
    hlib = HD.load_header_lib()
    results, failed = [], []
    for d in dirs:
        maps = sorted(set(re.match(r'm(\d+)_', os.path.basename(f)).group(1) for f in glob.glob(d + '/m*.png')))
        for mm in maps:
            try:
                entry = read_map(d, mm, hlib)
            except Exception:
                failed.append(mm)
                print(f'ocr_run: map {mm} in {d} failed:\n{traceback.format_exc()}', file=sys.stderr); continue
            if entry: results.append(entry)
    tmp = out_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:       # assemble_day must never read a half-written file
        json.dump(results, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, out_path)
    if failed: print('ocr_run: maps that could not be read:', ', '.join(failed), file=sys.stderr)
    bad = [f"{e['map']} ({e['verifyReason']})" for e in results if e['verifyFailed']]
    print(f'{len(results)} maps, {len(results) - len(bad)} verified' + (' | not verified: ' + ', '.join(bad) if bad else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace'); sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # names like 'Esperança'
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main(sys.argv[1], sys.argv[2:]))
