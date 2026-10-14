"""Read the per-player GAME DATA table from a 1080p frame by glyph template matching (no AI).
Layout is fixed: 2 panels x 5 rows x 6 numeric columns (E A D DMG H MIT). Commas are ignored
(thousands separators are implied by the digit count)."""
import cv2, numpy as np

X0, Y0 = 250, 95                                   # crop origin used while measuring
COLS = [930, 981, 1031, 1112, 1203, 1293]          # column centres (crop coords)
HALF_W = [22, 22, 22, 46, 46, 46]
ROWS = [133, 198, 262, 327, 391, 530, 594, 658, 723, 787]
HALF_H = 19
THR = 205
CANVAS = (16, 24)                                   # (w, h)

def cell(im, r, c):
    x, y = X0 + COLS[c], Y0 + ROWS[r]
    return im[y - HALF_H:y + HALF_H, x - HALF_W[c]:x + HALF_W[c]]

def _segment(g, thr):
    b = (g > thr).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    good, oversize = [], 0
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if h < 8 or h > 14 or a < 8: continue                    # drops commas, noise, panel edges
        if w > 11: oversize += 1; continue                       # merged digits -> this threshold is too low
        good.append((x, y, w, h, i))
    return lab, good, oversize

def glyphs(cellimg):
    """Try several brightness thresholds; keep the one that separates the most clean digits."""
    g = cv2.cvtColor(cellimg, cv2.COLOR_BGR2GRAY)
    mx = float(g.max())
    best = None
    for frac in (0.78, 0.70, 0.62, 0.55):
        thr = max(128.0, frac * mx)
        lab, good, over = _segment(g, thr)
        if over: continue
        if best is None or len(good) > len(best[1]): best = (lab, good)
    if best is None:                                              # every threshold merged something: split wide blobs by width
        thr = max(128.0, 0.78 * mx)
        b = (g > thr).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
        good = []
        for i in range(1, n):
            x, y, w, h, a = st[i]
            if h < 8 or h > 14 or a < 8: continue
            k = max(1, int(round(w / 8.5)))
            for j in range(k):
                good.append((x + j * w // k, y, w // k, h, (i, j, k)))
        return _pack(lab, good)
    lab, good = best
    return _pack(lab, good)

def _pack(lab, good):
    out = []
    for x, y, w, h, i in sorted(good, key=lambda t: t[0]):
        if isinstance(i, tuple):
            ci, j, k = i; cw = (lab == ci)
            ys, xs = np.nonzero(cw); bx0 = xs.min(); bw = xs.max() - bx0 + 1
            x0 = bx0 + j * bw // k; x1 = bx0 + (j + 1) * bw // k
            m = cw[y:y + h, x0:x1].astype(np.uint8) * 255; w = x1 - x0
        else:
            m = (lab[y:y + h, x:x + w] == i).astype(np.uint8) * 255
        s = (CANVAS[1] - 2) / h
        nw = max(1, int(round(w * s)))
        m = cv2.resize(m, (nw, CANVAS[1] - 2), interpolation=cv2.INTER_AREA)
        can = np.zeros((CANVAS[1], CANVAS[0]), np.uint8)
        ox = max(0, (CANVAS[0] - nw) // 2)
        k = min(nw, CANVAS[0])
        can[1:CANVAS[1] - 1, ox:ox + k] = m[:, :k]
        out.append((x, can.astype(np.float32) / 255, (w, h)))
    return out

class Model:
    def __init__(self): self.X, self.y = [], []
    def add(self, feat, ch): self.X.append(feat.ravel()); self.y.append(ch)
    def fit(self): self.Xa = np.array(self.X); self.ya = np.array(self.y)
    def predict(self, feat):
        d = ((self.Xa - feat.ravel()) ** 2).sum(1)
        i = int(np.argmin(d))
        # distance to the nearest sample of a *different* digit (margin = confidence)
        other = d[self.ya != self.ya[i]].min() if (self.ya != self.ya[i]).any() else 1e9
        return self.ya[i], float(d[i]), float(other)
