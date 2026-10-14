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


# ---------------------------------------------------------------------------------------------------------
# Full header: "MATCH m GAME g" (line 1) and "<MAP NAME> M:SS" (line 2), read with crop libraries in
# data/header_lib/  (digit_<d>__<tag>.png, map_<Name>__<tag>.png). Built by tools/build_header_lib.py.
import glob as _glob, os as _os

LINES = {1: (20, 60), 2: (52, 96)}
XR = (950, 1450)
HEADER_LIB = 'data/header_lib'


def imread_u(path, flags=cv2.IMREAD_GRAYSCALE):
    """cv2.imread that also works with non-ASCII file names on Windows (e.g. 'Esperança')"""
    return cv2.imdecode(np.fromfile(path, np.uint8), flags)


def imwrite_u(path, img):
    ok, buf = cv2.imencode('.png', img)
    buf.tofile(path)
MAP_UNKNOWN_DIST = 600.0


def _line(im, n):
    y0, y1 = LINES[n]
    c = im[Y0 + y0:Y0 + y1, X0 + XR[0]:X0 + XR[1]]
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    b = (g > 200).astype(np.uint8)
    k, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    cs = sorted((int(st[i][0]), int(st[i][1]), int(st[i][2]), int(st[i][3]), int(st[i][4]), i) for i in range(1, k) if st[i][4] >= 6)
    return cs, lab, b


def _words(cs, gap=7):
    big = [c for c in cs if c[3] >= 12]
    words = []
    for c in big:
        if words and c[0] - (words[-1][-1][0] + words[-1][-1][2]) <= gap: words[-1].append(c)
        else: words.append([c])
    return words


def _map_feat(b, comps):
    x0 = min(c[0] for c in comps); x1 = max(c[0] + c[2] for c in comps)
    crop = b[:, x0:x1] * 255
    ys = np.nonzero(crop.any(1))[0]
    crop = crop[ys.min():ys.max() + 1]
    return cv2.resize(crop.astype(np.uint8), (200, 20), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


def header_parts(im):
    """glyph features of the header: {'match': [feat], 'game': [feat], 'time': ([feats], n_min_digits), 'map': feat}"""
    out = {}
    cs1, lab1, _ = _line(im, 1); w1 = _words(cs1)
    if len(w1) == 4:
        out['match'] = [feat(lab1, c) for c in w1[1]]
        out['game'] = [feat(lab1, c) for c in w1[3]]
    cs2, lab2, b2 = _line(im, 2)
    sp = split_time(cs2)
    if sp and sp[0]:
        out['time'] = ([feat(lab2, c) for c in sp[0] + sp[1]], len(sp[0]))
        name = [c for c in cs2 if c[3] >= 12 and c[0] + c[2] < sp[0][0][0] - 4]
        if name: out['map'] = _map_feat(b2, name)
    return out


def load_header_lib(path=HEADER_LIB):
    digits, maps = [], []
    for f in _glob.glob(_os.path.join(path, '*.png')):
        kind, rest = _os.path.basename(f)[:-4].split('_', 1)
        label, tag = rest.split('__', 1)
        arr = imread_u(f).astype(np.float32) / 255
        (digits if kind == 'digit' else maps).append((label, arr, tag))
    return digits, maps


def _nn(lib, f, exclude=None, blur=False):
    best = (None, 1e9)
    if blur: f = cv2.GaussianBlur(f, (5, 5), 1.2)
    for lb, arr, tag in lib:
        if exclude and tag.startswith(exclude): continue
        if blur: arr = cv2.GaussianBlur(arr, (5, 5), 1.2)
        d = float(((arr - f) ** 2).sum())
        if d < best[1]: best = (lb, d)
    return best


def read_header(im, lib=None, exclude=None):
    """-> dict(match=int|None, game=int|None, map=str|None ('?' if unknown), mapTime='M:SS'|None)"""
    digits, maps = lib or load_header_lib()
    p = header_parts(im); r = {'match': None, 'game': None, 'map': None, 'mapTime': None}
    num = lambda fs: int(''.join(_nn(digits, f, exclude, blur=True)[0] for f in fs)) if fs and digits else None
    if 'match' in p: r['match'], r['game'] = num(p['match']), num(p['game'])
    if 'time' in p:
        fs, nm = p['time']; s = ''.join(_nn(digits, f, exclude, blur=True)[0] for f in fs)
        r['mapTime'] = f'{int(s[:nm])}:{s[nm:]}' if len(s) == nm + 2 else None
    if 'map' in p and maps:
        name, d = _nn(maps, p['map'], exclude)
        r['map'] = name if d <= MAP_UNKNOWN_DIST else '?'
        r['mapDist'] = round(d, 1)
    return r
