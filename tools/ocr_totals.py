"""Read the team-totals GAME DATA page (E, D, DAMAGE, HEAL, MITIGATION per team). Used as a checksum for the table OCR."""
import cv2, numpy as np
X0, Y0 = 250, 95
# (name, centre x, centre y, half w, half h)  -- crop coords
FIELDS = {}
for pi, (yb, ye) in enumerate([(297, 155), (685, 543)]):
    FIELDS[(pi, 'dmg')] = (590, yb, 125, 40)
    FIELDS[(pi, 'heal')] = (925, yb, 125, 40)
    FIELDS[(pi, 'mit')] = (1245, yb, 125, 40)
    FIELDS[(pi, 'e')] = (1020, ye, 38, 20)
    FIELDS[(pi, 'd')] = (1158, ye, 30, 20)
    FIELDS[(pi, 'dpm')] = (590, yb + 63, 120, 22)        # '3,908 D/M' under the damage total
    FIELDS[(pi, 'hpm')] = (925, yb + 63, 120, 22)        # '2,475 H/M' under the healing total
CANVAS = (20, 30)

def glyphs(im, key):
    cx, cy, hw, hh = FIELDS[key]
    c = im[Y0 + cy - hh:Y0 + cy + hh, X0 + cx - hw:X0 + cx + hw]
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    b = (g > 190).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    big = key[1] in ('dmg', 'heal', 'mit')
    lo, hi = (30, 60) if big else (15, 34)
    comps = [(st[i][0], st[i][1], st[i][2], st[i][3], i) for i in range(1, n) if lo <= st[i][3] <= hi and st[i][4] > 30 and st[i][2] <= hi]
    comps = sorted(comps)
    if key[1] in ('dpm', 'hpm'):                          # keep the number, drop the 'D/M' / 'H/M' word after it
        keep = comps[:1]
        for c in comps[1:]:
            if c[0] - (keep[-1][0] + keep[-1][2]) > 15: break
            keep.append(c)
        comps = keep
    out = []
    for x, y, w, h, i in comps:
        m = (lab[y:y + h, x:x + w] == i).astype(np.uint8) * 255
        s = (CANVAS[1] - 2) / h; nw = max(1, int(round(w * s)))
        m = cv2.resize(m, (nw, CANVAS[1] - 2), interpolation=cv2.INTER_AREA)
        can = np.zeros((CANVAS[1], CANVAS[0]), np.uint8)
        k = min(nw, CANVAS[0]); ox = max(0, (CANVAS[0] - nw) // 2)
        can[1:CANVAS[1] - 1, ox:ox + k] = m[:, :k]
        out.append((x, can.astype(np.float32) / 255))
    return out
