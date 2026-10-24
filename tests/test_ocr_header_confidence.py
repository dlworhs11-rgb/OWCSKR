"""read_header digit confidence (P1-05 item 1) on synthetic glyph features."""
import os, sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import ocr_header as H


def glyph(cols):
    a = np.zeros((24, 16), np.float32); a[2:22, cols] = 1.0
    return a


ONE, TWO = glyph(slice(7, 9)), glyph(slice(2, 14))
LIB = [('1', ONE, 'a'), ('1', glyph(slice(7, 10)), 'b'), ('2', TWO, 'c')]


def test_clear_digits_are_read():
    n, dists = H.read_number(LIB, [ONE, TWO])
    assert n == 12
    assert [d[0] for d in dists] == ['1', '2'] and all(d1 < d2 for _, d1, d2 in dists)


def test_glyph_between_two_digits_gives_none():
    mid = (ONE + TWO) / 2
    n, dists = H.read_number(LIB, [mid])
    assert n is None and dists[0][1] > H.AMBIGUOUS_RATIO * dists[0][2]


def test_second_distance_is_of_another_label():
    lb, d1, d2 = H._nn2(LIB, ONE, blur=True)
    assert lb == '1' and d2 > 0      # the second '1' sample does not count as runner-up


def test_read_header_flags_ambiguous_match(monkeypatch):
    mid = (ONE + TWO) / 2
    monkeypatch.setattr(H, 'header_parts', lambda im: {'match': [mid], 'game': [TWO]})
    r = H.read_header(None, (LIB, []))
    assert r['match'] is None and r['matchAmbiguous'] is True
    assert r['game'] == 2 and r['gameAmbiguous'] is False and r['mapTime'] is None


def test_empty_library_reads_nothing(monkeypatch):
    monkeypatch.setattr(H, 'header_parts', lambda im: {'match': [ONE], 'game': [ONE], 'time': ([ONE, ONE, ONE], 1)})
    r = H.read_header(None, ([], []))
    assert r['match'] is None and r['matchAmbiguous'] is False and r['mapTime'] is None
