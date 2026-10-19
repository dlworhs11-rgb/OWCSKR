"""Hero-ban screen and Player-of-the-Match screen of the OWCS Korea broadcast (Tesseract OCR + word lists).

Ban screen (before every map): left hero = left team's ban, right hero = right team's ban; the small label under each
hero says INITIAL BAN or FOLLOW-UP BAN. Centre: SELECTED MAP. Top bar: team names and the series score before this map.
POTM screen (after a match): player name + ELIMS DEATH E/D DMG DMG/M for the whole match.

All coordinates are measured on a 960x540 frame; frames of any 16:9 size are resized to 1920x1080 and scaled by 2.
"""
import difflib, json, os, re
import cv2, numpy as np, pytesseract

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_BAN = cv2.imread(os.path.join(ROOT, 'data', 'ref', 'ban_960.jpg'))
REF_POTM = cv2.imread(os.path.join(ROOT, 'data', 'ref', 'potm_960.jpg'))
BAN_KEY = (slice(440, 458), slice(430, 530))       # 'SELECTED MAP' label (same in both ban layouts)
POTM_KEY = (slice(26, 54), slice(130, 830))        # 'PLAYER OF THE MATCH' title


def small(img): return cv2.resize(img, (960, 540), interpolation=cv2.INTER_AREA)


def screen_kind(img):
    """'BAN', 'POTM' or None for a broadcast frame."""
    s = small(img)
    if cv2.matchTemplate(s[BAN_KEY], REF_BAN[BAN_KEY], cv2.TM_CCOEFF_NORMED)[0][0] > 0.8: return 'BAN'
    if cv2.matchTemplate(s[POTM_KEY], REF_POTM[POTM_KEY], cv2.TM_CCOEFF_NORMED)[0][0] > 0.85: return 'POTM'
    return None


def _ocr(img, box, psm=7, cfg=''):
    """box = (x0, x1, y0, y1) on the 960x540 grid; cropped from the original frame, then enlarged to 4x of 960 scale"""
    sx = img.shape[1] / 960.0
    x0, x1, y0, y1 = (int(round(v * sx)) for v in box)
    g = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=4 / sx, fy=4 / sx, interpolation=cv2.INTER_CUBIC)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    b = cv2.copyMakeBorder(b, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
    return pytesseract.image_to_string(b, config=f'--psm {psm} {cfg}').strip(), b


DIGIT_LIB = os.path.join(ROOT, 'data', 'digit_lib')      # bold bar/POTM digits: <d>__<tag>.png (tools/build_digit_lib.py)


def digit_glyphs(img, box):
    """Otsu-binarised digit glyphs (left to right) in a 960-grid box; brightness varies while the graphics animate in"""
    sx = img.shape[1] / 960.0
    x0, x1, y0, y1 = (int(round(v * sx)) for v in box)
    g = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, lab, st, _ = cv2.connectedComponentsWithStats((b > 0).astype(np.uint8), 8)
    H = y1 - y0
    cs = sorted((int(st[i][0]), int(st[i][1]), int(st[i][2]), int(st[i][3]), i) for i in range(1, n) if st[i][3] >= 0.45 * H and st[i][4] > 30)
    out = []
    for x, y, w, h, i in cs:
        m = (lab[y:y + h, x:x + w] == i).astype(np.uint8) * 255
        sc = 34 / h; nw = max(1, int(round(w * sc)))
        m = cv2.resize(m, (nw, 34), interpolation=cv2.INTER_AREA)
        can = np.zeros((36, 28), np.uint8); k = min(nw, 28); ox = max(0, (28 - nw) // 2)
        can[1:35, ox:ox + k] = m[:, :k]
        out.append(can.astype(np.float32) / 255)
    return out


_DLIB = None
def _digit_lib():
    global _DLIB
    if _DLIB is None:
        import glob
        _DLIB = []
        for f in glob.glob(os.path.join(DIGIT_LIB, '*.png')):
            d = os.path.basename(f).split('__')[0]
            _DLIB.append((d, cv2.GaussianBlur(cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255, (5, 5), 1.2)))
    return _DLIB


def read_digits(img, box):
    """digits in a box via the bold-digit library; None when the library is empty or nothing is there"""
    lib, gl = _digit_lib(), digit_glyphs(img, box)
    if not lib or not gl: return None
    out = ''
    for f in gl:
        f = cv2.GaussianBlur(f, (5, 5), 1.2)
        out += min(lib, key=lambda e: float(((e[1] - f) ** 2).sum()))[0]
    return out


def _score(img, box):
    d = read_digits(img, box)
    if d is not None and d.isdigit(): return int(d)
    return _score_tesseract(img, box)


def _score_tesseract(img, box):
    txt, b = _ocr(img, box, 8, '-c tessedit_char_whitelist=0123456789')
    if txt.isdigit(): return int(txt)
    ink = (b < 128).mean()
    return 0 if ink > 0.02 else None          # Tesseract misses a lone '0'; a visible glyph with no reading is 0


def _snap(text, words, cutoff=0.72):
    """closest known word (case/accents ignored); unknown words are kept as read"""
    if not text: return None
    key = lambda s: re.sub(r'[^a-z0-9]', '', s.lower().replace('ç', 'c').replace('ø', 'o').replace('@', 'o'))
    table = {key(w): w for w in words}
    hit = difflib.get_close_matches(key(text), list(table), n=1, cutoff=cutoff)
    return table[hit[0]] if hit else text


def word_lists():
    """heroes and map names seen on Liquipedia (data/site/matches.json) + team names (aliases)"""
    heroes, maps = set(), set()
    try:
        for m in json.load(open(os.path.join(ROOT, 'data', 'site', 'matches.json'), encoding='utf-8')):
            for mp in m.get('maps', []):
                if mp.get('map'): maps.add(mp['map'])
                for h in (mp.get('bans') or {}).values():
                    if h: heroes.add(h)
    except FileNotFoundError:
        pass
    aliases = json.load(open(os.path.join(ROOT, 'data', 'aliases.json'), encoding='utf-8'))
    teams = {k: v for k, v in aliases.items() if not k.startswith('_')}
    return sorted(heroes), sorted(maps), teams


def read_ban(img, lists=None):
    heroes, maps, teams = lists or word_lists()
    lab_l, _ = _ocr(img, (80, 250, 442, 457)); lab_r, _ = _ocr(img, (710, 880, 442, 457))
    hero_l, _ = _ocr(img, (80, 250, 458, 476)); hero_r, _ = _ocr(img, (710, 880, 458, 476))
    sel, _ = _ocr(img, (380, 580, 458, 476))
    if not sel:   # a short one-word name ('Nepal', 10-18 map 1) can come back empty as a line: read it as one word
        sel, _ = _ocr(img, (380, 580, 458, 476), 8)
    team_l, _ = _ocr(img, (60, 300, 20, 40)); team_r, _ = _ocr(img, (640, 900, 20, 40))
    tkey = lambda t: re.sub(r'[^a-z0-9 ]', '', t.lower().replace('@', 'o').replace('ø', 'o')).strip()
    def team(t):
        hit = difflib.get_close_matches(tkey(t), list(teams), n=1, cutoff=0.6)
        return teams[hit[0]] if hit else t.strip(' |')
    init_left = 'INITIAL' in lab_l.upper() or 'FOLLOW' in lab_r.upper()
    hl, hr = _snap(hero_l, heroes), _snap(hero_r, heroes)
    tl, tr = team(team_l), team(team_r)
    return {'teams': [tl, tr], 'score': [_score(img, (315, 375, 18, 58)), _score(img, (585, 645, 18, 58))],
            'map': _snap(sel, maps),
            'initial': {'team': tl if init_left else tr, 'hero': hl if init_left else hr},
            'followUp': {'team': tr if init_left else tl, 'hero': hr if init_left else hl},
            'raw': {'labels': [lab_l, lab_r], 'heroes': [hero_l, hero_r], 'map': sel, 'teams': [team_l, team_r]}}


POTM_FIELDS = {'elims': (562, 624), 'deaths': (636, 696), 'ed': (704, 772), 'dmg': (780, 862), 'dmgPerMin': (864, 932)}


def read_potm(img):
    name, _ = _ocr(img, (80, 300, 480, 515))
    if not name.strip(' |'):           # one short word ('Someone', 10-09): psm 7 returns nothing, psm 8 reads it
        name, _ = _ocr(img, (80, 300, 480, 515), 8)
    out = {'name': name.strip(' |‘’\'"`'), 'raw': {}}
    for k, (x0, x1) in POTM_FIELDS.items():
        txt = read_digits(img, (x0, x1, 486, 519)) if k in ('elims', 'deaths', 'dmgPerMin') else None
        if not txt: txt, _ = _ocr(img, (x0, x1, 486, 519), 7, '-c tessedit_char_whitelist=0123456789.K')
        out['raw'][k] = txt
        try:
            if k == 'ed': out[k] = float(txt)
            elif k == 'dmg': out['dmgK'] = float(txt.upper().rstrip('K')) if txt.upper().endswith('K') else round(int(txt) / 1000, 1)
            else: out[k] = int(txt)
        except ValueError:
            pass
    return out
