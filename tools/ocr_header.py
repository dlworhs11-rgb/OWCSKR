"""Read the map duration 'M:SS' from the GAME DATA header (second line, right aligned)."""
import cv2, numpy as np
X0, Y0 = 250, 95
REG = (1000, 1450, 52, 96)        # crop coords x0,x1,y0,y1 of the 'MAP  M:SS' line

def comps(im):
    x0, x1, y0, y1 = REG
    c = im[Y0 + y0:Y0 + y1, X0 + x0:X0 + x1]
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    b = (g > 200).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 6: continue
        out.append((x, y, w, h, a, i))
    return sorted(out), lab

def split_time(cs):
    """returns (minute_glyphs, second_glyphs) as component lists, using the colon (two small dots)"""
    dots = [c for c in cs if c[3] <= 6 and c[2] <= 6]
    big = [c for c in cs if c[3] >= 12]
    if len(dots) < 2: return None
    # colon = two dots with similar x, rightmost such pair
    best = None
    for i in range(len(dots)):
        for j in range(i + 1, len(dots)):
            if abs(dots[i][0] - dots[j][0]) <= 3 and abs(dots[i][1] - dots[j][1]) >= 6:
                if best is None or dots[i][0] > best[0]: best = (dots[i][0], dots[i][2])
    if best is None: return None
    cx = best[0]
    right = [c for c in big if c[0] > cx][:2]
    left = [c for c in big if c[0] + c[2] <= cx + 1]
    mins = []
    for c in reversed(left):
        if not mins: 
            if cx - (c[0] + c[2]) <= 14: mins.append(c)
            else: break
        else:
            if mins[-1][0] - (c[0] + c[2]) <= 6 and len(mins) < 2: mins.append(c)
            else: break
    return list(reversed(mins)), right


def feat(lab, c):
    x, y, w, h, a, i = c
    m = (lab[y:y + h, x:x + w] == i).astype(np.uint8) * 255
    sc = 22 / h; nw = max(1, int(round(w * sc)))
    m = cv2.resize(m, (nw, 22), interpolation=cv2.INTER_AREA)
    can = np.zeros((24, 16), np.uint8); k = min(nw, 16); ox = max(0, (16 - nw) // 2); can[1:23, ox:ox + k] = m[:, :k]
    return can.astype(np.float32) / 255

def glyph_feats(im):
    cs, lab = comps(im); sp = split_time(cs)
    if not sp: return None
    return [feat(lab, c) for c in sp[0] + sp[1]], len(sp[0])
