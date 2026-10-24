"""Match player-name crops of a GAME DATA table against a library built from hand-labelled maps."""
import cv2, numpy as np, json, glob, os, sys
X0, Y0 = 250, 95
ROWS = [133, 198, 262, 327, 391, 530, 594, 658, 723, 787]
NX = (600, 775)       # name column (crop coords x), measured from the 1080p crop

def name_feat(im, r):
    y = Y0 + ROWS[r]
    c = im[y - 20:y + 6, X0 + NX[0]:X0 + NX[1]]
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    b = (g > 195).astype(np.uint8) * 255
    ys, xs = np.nonzero(b)
    if len(xs) < 20: return None, c
    b = b[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return cv2.resize(b, (96, 18), interpolation=cv2.INTER_AREA).astype(np.float32) / 255, c

def build(gt, frames):
    lib = []
    for i, m in enumerate(gt['maps'], 1):
        im = cv2.imread(frames[i]); names = [p['name'] for t in m['teams'].values() for p in t]
        for r, nm in enumerate(names):
            f, _ = name_feat(im, r)
            if f is not None: lib.append((nm, f, i))
    return lib

def match(lib, f, exclude_map=None):
    best = (None, 1e9)
    for nm, lf, mi in lib:
        if mi == exclude_map: continue
        d = float(((lf - f) ** 2).sum())
        if d < best[1]: best = (nm, d)
    return best


FEAT_SHAPE = (18, 96)


def feat_png(f):
    """name feature (float 0..1, 18x96) as the uint8 image stored in data/name_lib"""
    return (f * 255).astype(np.uint8)


def load_lib(path='data/name_lib'):
    """[(name, feature, tag)] from data/name_lib/<Name>__<tag>.png; files that are not 96x18 name features
    (e.g. a raw crop copied from unknown/) are skipped with a warning instead of breaking every match"""
    lib = []
    for f in glob.glob(os.path.join(path, '*.png')):
        base = os.path.basename(f)[:-4]
        if '__' not in base:
            print(f'name_lib: skipped {f}: name is not <Name>__<tag>.png', file=sys.stderr); continue
        nm, tag = base.split('__', 1)
        im = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_GRAYSCALE)     # non-ASCII names on Windows
        if im is None or im.shape != FEAT_SHAPE:
            print(f'name_lib: skipped {f}: shape {None if im is None else im.shape}, expected {FEAT_SHAPE} '
                  '(use tools/label_unknown.py to add names)', file=sys.stderr); continue
        lib.append((nm, im.astype(np.float32) / 255, tag))
    return lib

UNKNOWN_DIST = 175.0     # nearest-name distance above this = a name we have not seen yet
