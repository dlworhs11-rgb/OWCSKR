"""Match player-name crops of a GAME DATA table against a library built from hand-labelled maps."""
import cv2, numpy as np, json, glob, os
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


def load_lib(path='data/name_lib'):
    """[(name, feature, tag)] from data/name_lib/<Name>__<tag>.png"""
    lib = []
    for f in glob.glob(os.path.join(path, '*.png')):
        nm, tag = os.path.basename(f)[:-4].split('__', 1)
        lib.append((nm, cv2.imread(f, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255, tag))
    return lib

UNKNOWN_DIST = 175.0     # nearest-name distance above this = a name we have not seen yet
