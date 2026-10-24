"""Glyph classifiers for the GAME DATA table and the team-totals page, cached in data/models/{table,totals}.npz.

They are trained on the hand-checked maps of 2026-10-11 (data/manual/mapstats/2026-10-11.json) and the matching
broadcast frames under data/vod (local only, not in git). Each .npz carries a hash of those inputs:
- training frames present: the cache is used while the hash matches, otherwise rebuilt
- training frames absent (the server): the cache is used as it is - build it on the PC and copy data/models/*.npz over
- neither: ModelError

usage: python -I tools/glyph_models.py [--rebuild]      (builds the cache and prints the training statistics)
"""
import glob, hashlib, json, os, sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_table as TB, ocr_totals as TT

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GT = 'data/manual/mapstats/2026-10-11.json'
# manual map i (in file order) <-> its table frame and totals frame
TABLE_TRAIN = {1: 'data/vod/hi_3466.png', 2: 'data/vod/maps/m_5025.png', 3: 'data/vod/maps/m_6120.png', 4: 'data/vod/maps/m_8220.png',
               5: 'data/vod/maps/m_9440.png', 6: 'data/vod/maps/m_12540.png', 7: 'data/vod/maps/m_14100.png'}
TOT_TRAIN = 'data/vod/p1a/frames/m{:02d}_totals_*.png'
K = ['e', 'a', 'd', 'dmg', 'heal', 'mit']
TOT_KEYS = ['e', 'd', 'dmg', 'heal', 'mit']
DIGITS = '0123456789'
KINDS = ('table', 'totals')


class ModelError(RuntimeError):
    pass


def model_path(kind: str, root: str = ROOT) -> str:
    return os.path.join(root, 'data', 'models', f'{kind}.npz')


def training_inputs(root: str = ROOT) -> tuple[str, list[str], list[str | None]]:
    """(ground-truth json, table frames, totals frames); a totals frame that is not on disk is None"""
    keys = sorted(TABLE_TRAIN)
    tables = [os.path.join(root, TABLE_TRAIN[i]) for i in keys]
    tots = [(sorted(glob.glob(os.path.join(root, TOT_TRAIN.format(i)))) or [None])[0] for i in keys]
    return os.path.join(root, GT), tables, tots


def inputs_present(gt: str, files: list) -> bool:
    return os.path.isfile(gt) and all(f and os.path.isfile(f) for f in files)


def inputs_hash(gt: str, files: list[str], root: str = ROOT) -> str:
    """ground truth content + every training frame's path, size and mtime"""
    h = hashlib.sha256()
    with open(gt, 'rb') as fh:
        h.update(fh.read())
    for f in files:
        st = os.stat(f)
        rel = os.path.relpath(f, root).replace('\\', '/')
        h.update(f'\n{rel}|{st.st_size}|{int(st.st_mtime)}'.encode('utf-8'))
    return h.hexdigest()


def _imread(path: str):
    import cv2
    im = cv2.imread(path)
    if im is None:
        raise ModelError(f'cannot read training frame {path}')
    return im


def _learn(model, stats: dict, glyphs: list, text: str) -> None:
    """one cell: its glyphs are labelled only when their count matches the known value's digit count"""
    stats['cells'] += 1
    if len(glyphs) != len(text):
        stats['skipped'] += 1
        return
    for f, ch in zip(glyphs, text):
        model.add(f, ch)
        stats['classes'][ch] += 1


def train(gt: str, tables: list[str], tots: list[str]) -> tuple:
    """-> (table model, totals model, stats); stats[kind] = {'cells', 'skipped', 'classes': {digit: samples}}"""
    with open(gt, encoding='utf-8') as fh:
        maps = [m for m in json.load(fh)['maps'] if m.get('reading', 'manual') == 'manual']
    if len(maps) != len(tables):     # pairing is by order: a changed ground-truth file must not label the wrong frames
        raise ModelError(f'{gt}: {len(maps)} hand-checked maps but {len(tables)} training frames')
    mt, mo = TB.Model(), TB.Model()
    stats = {k: {'cells': 0, 'skipped': 0, 'classes': Counter()} for k in KINDS}
    for m, tpath, opath in zip(maps, tables, tots):
        im, imt = _imread(tpath), _imread(opath)
        rows = [p for t in m['teams'].values() for p in t]
        for r, p in enumerate(rows):
            for c, k in enumerate(K):
                _learn(mt, stats['table'], [f for _, f, _ in TB.glyphs(TB.cell(im, r, c))], str(p[k]))
        for pi, team in enumerate(m['teams'].values()):
            for k in TOT_KEYS:
                _learn(mo, stats['totals'], [f for _, f in TT.glyphs(imt, (pi, k))], str(sum(r[k] for r in team)))
    for k in KINDS:
        stats[k]['classes'] = dict(sorted(stats[k]['classes'].items()))
    mt.fit(); mo.fit()
    return mt, mo, stats


def check_digits(model, kind: str) -> None:
    missing = [d for d in DIGITS if d not in set(model.ya.tolist())]
    if missing:
        raise ModelError(f'{kind} glyph model has no sample of digit(s) {", ".join(missing)}')


def save(path: str, model, digest: str, stats: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as fh:
        np.savez(fh, X=model.Xa.astype(np.float32), y=model.ya.astype('<U1'), hash=np.array(digest), stats=np.array(json.dumps(stats)))
    os.replace(tmp, path)


def load(path: str):
    """-> (model, hash, stats) or None when the file is missing or unreadable"""
    if not os.path.isfile(path):
        return None
    try:
        with np.load(path, allow_pickle=False) as z:
            m = TB.Model()
            m.Xa, m.ya = z['X'], z['y']
            return m, str(z['hash']), json.loads(str(z['stats']))
    except Exception as e:
        print(f'glyph models: {path} unreadable ({type(e).__name__}: {e}) - ignored', file=sys.stderr)
        return None


def print_stats(stats: dict, log=print) -> None:
    for k in KINDS:
        s = stats[k]
        counts = ' '.join(f'{d}:{s["classes"].get(d, 0)}' for d in DIGITS)
        log(f'glyph model {k}: {s["cells"]} cells, {s["skipped"]} skipped (digit count mismatch) | samples {counts}')


def _build(root: str, gt: str, tables: list, tots: list, digest: str, log) -> tuple:
    mt, mo, stats = train(gt, tables, tots)
    print_stats(stats, log)
    check_digits(mt, 'table'); check_digits(mo, 'totals')
    for kind, m in zip(KINDS, (mt, mo)):
        try:
            save(model_path(kind, root), m, digest, stats)
        except OSError as e:                              # still usable for this run
            log(f'glyph models: could not write {model_path(kind, root)}: {e}')
    return mt, mo


def get_models(root: str = ROOT, log=print, rebuild: bool = False) -> tuple:
    """(table model, totals model): cached when possible, trained when the cache is stale; ModelError if neither works"""
    gt, tables, tots = training_inputs(root)
    files = tables + tots
    cached = [load(model_path(k, root)) for k in KINDS]
    if inputs_present(gt, files):
        digest = inputs_hash(gt, files, root)
        if not rebuild and all(c and c[1] == digest for c in cached):
            models = tuple(c[0] for c in cached)
        else:
            log('glyph models: training inputs changed or no cache - rebuilding')
            models = _build(root, gt, tables, tots, digest, log)
    elif all(cached):
        models = tuple(c[0] for c in cached)              # server: frames not here, cache copied from the PC
    else:
        missing = [os.path.relpath(f, root) for f in [gt] + tables if not os.path.isfile(f)]
        missing += [TOT_TRAIN.format(i) for i, f in zip(sorted(TABLE_TRAIN), tots) if not f]
        raise ModelError('no glyph models: data/models/table.npz / totals.npz missing and training inputs not found '
                         f'({", ".join(missing[:4])}{" ..." if len(missing) > 4 else ""}). Build them on the PC that has data/vod '
                         '(python -I tools/glyph_models.py) and copy data/models/*.npz here.')
    for kind, m in zip(KINDS, models):
        check_digits(m, kind)
    return models


def status(root: str = ROOT) -> tuple[str | None, str]:
    """for the self-check, without training: (None|'warn'|'fatal', detail)"""
    gt, tables, tots = training_inputs(root)
    cached = [load(model_path(k, root)) for k in KINDS]
    present = inputs_present(gt, tables + tots)
    if all(cached):
        try:
            for kind, c in zip(KINDS, cached):
                check_digits(c[0], kind)
        except ModelError as e:
            return 'fatal', str(e)
        if present and any(c[1] != inputs_hash(gt, tables + tots, root) for c in cached):
            return 'warn', 'cache is stale - rebuilt from the training frames at the first OCR run'
        return None, 'cached'
    if present:
        return 'warn', 'no cache yet - built from the training frames at the first OCR run'
    return 'fatal', 'data/models/table.npz / totals.npz missing and training frames (data/vod) not on this machine'


if __name__ == '__main__':
    try:
        get_models(rebuild='--rebuild' in sys.argv)
    except ModelError as e:
        print('glyph models FAILED:', e, file=sys.stderr)
        sys.exit(2)
    print('glyph models ready:', ', '.join(model_path(k) for k in KINDS))
