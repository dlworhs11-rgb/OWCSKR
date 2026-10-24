"""Seed data/digit_lib (bold digits of the series-score bar and the POTM card) from 1080p grabs of 2026-10-11.

These values contain no 6 and few 3/5/8/9, so assemble_day warns that the library is incomplete. To add samples:
save a ban or POTM frame whose numbers show the missing digits as data/live/grab/<sec>_BAN.png / <sec>_POTM.png,
add its true values below (scores: (left, right); potm: elims / deaths / dmgPerMin as strings) and run this again.
Target: every digit 0-9 at least ocr_screens.DIGIT_MIN_SAMPLES times. Glyph counts that do not match the
text are skipped and printed."""
import cv2, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ocr_screens as S
os.makedirs(S.DIGIT_LIB, exist_ok=True)
scores = {2505: (0, 0), 3645: (0, 1), 5085: (0, 2), 6210: (1, 2), 8265: (2, 2), 11280: (0, 0), 12600: (0, 1), 14160: (1, 1), 15345: (1, 2),
          18478: (0, 0), 19528: (0, 1), 20908: (0, 2)}
potm = {9495: {'elims': '98', 'deaths': '40', 'dmgPerMin': '743'}, 21763: {'elims': '54', 'deaths': '17', 'dmgPerMin': '1021'}}
n = 0
def save(tag, glyphs, text):
    global n
    if len(glyphs) != len(text): print('skip', tag, len(glyphs), text); return
    for i, (g, ch) in enumerate(zip(glyphs, text)):
        cv2.imencode('.png', (g * 255).astype('uint8'))[1].tofile(os.path.join(S.DIGIT_LIB, f'{ch}__{tag}_{i}.png')); n += 1
for t, (l, r) in scores.items():
    im = cv2.imread(f'data/live/grab/{t}_BAN.png')
    save(f's{t}L', S.digit_glyphs(im, (315, 375, 18, 58)), str(l)); save(f's{t}R', S.digit_glyphs(im, (585, 645, 18, 58)), str(r))
for t, vals in potm.items():
    im = cv2.imread(f'data/live/grab/{t}_POTM.png')
    for k, v in vals.items():
        x0, x1 = S.POTM_FIELDS[k]; save(f'p{t}{k}', S.digit_glyphs(im, (x0, x1, 486, 519)), v)
print('digit samples saved:', n)
