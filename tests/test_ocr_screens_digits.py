"""Bold-digit library: distance cutoff and sample counts (P1-06 items 1-2), without Tesseract."""
import os, sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import ocr_screens as S


def glyph(cols, jitter=0.0, seed=0):
    a = np.zeros((36, 28), np.float32); a[2:34, cols] = 1.0
    if jitter: a = np.clip(a + np.random.default_rng(seed).normal(0, jitter, a.shape).astype(np.float32), 0, 1)
    return a


ZERO, ONE = slice(4, 24), slice(12, 16)
LIB = [(d, S._blur(glyph(c, 0.05, i))) for i, (d, c) in enumerate([('0', ZERO)] * 4 + [('1', ONE)] * 4)]


def test_pytesseract_not_needed_to_import():
    assert S._PT is None or 'pytesseract' in sys.modules


def test_cutoff_from_library_spread():
    cut = S.digit_cutoff(LIB)
    same = [min(float(((a - b) ** 2).sum()) for j, (e, b) in enumerate(LIB) if j != i and e == d) for i, (d, a) in enumerate(LIB)]
    assert cut >= np.percentile(same, S.DIGIT_CUTOFF_PCT) * S.DIGIT_CUTOFF_FACTOR - 1e-6


def test_cutoff_env_override(monkeypatch):
    monkeypatch.setenv('OWCSKR_DIGIT_CUTOFF', '12.5')
    assert S.digit_cutoff(LIB) == 12.5


def test_cutoff_needs_two_samples_of_a_digit(monkeypatch):
    monkeypatch.delenv('OWCSKR_DIGIT_CUTOFF', raising=False)
    assert S.digit_cutoff([('0', LIB[0][1]), ('1', LIB[4][1])]) is None


def test_identical_samples_do_not_give_a_zero_cutoff(monkeypatch):
    monkeypatch.delenv('OWCSKR_DIGIT_CUTOFF', raising=False)
    z, o = S._blur(glyph(ZERO)), S._blur(glyph(ONE))
    assert S.digit_cutoff([('0', z), ('0', z.copy()), ('1', o)]) > 0


def test_digits_within_cutoff_are_read(monkeypatch):
    monkeypatch.delenv('OWCSKR_DIGIT_CUTOFF', raising=False)
    cut = S.digit_cutoff(LIB)
    assert S.match_digits(LIB, [glyph(ONE, 0.05, 99), glyph(ZERO, 0.05, 98)], cut) == '10'


def test_noise_glyph_gives_none_so_tesseract_runs(monkeypatch):
    monkeypatch.delenv('OWCSKR_DIGIT_CUTOFF', raising=False)
    cut = S.digit_cutoff(LIB)
    blob = np.zeros((36, 28), np.float32); blob[2:34, 0:28] = 1.0       # an intro-animation slab, not a digit
    assert S.match_digits(LIB, [glyph(ONE), blob], cut) is None
    assert S.match_digits(LIB, [glyph(ONE), blob], None) is not None     # no cutoff: old behaviour


def test_digit_counts_lists_missing_six():
    counts = S.digit_counts([(d, None) for d in '0001112223334445557778889990'])
    assert counts['6'] == 0 and counts['0'] == 4
