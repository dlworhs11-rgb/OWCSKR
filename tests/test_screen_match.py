import os, sys

import cv2, numpy as np, pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import screen_match as SM


def page(seed, title=True):
    """synthetic 960x540 broadcast page: noisy dark background, a textured body, optional 'GAME DATA' title"""
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(rng.integers(0, 80, (540, 960, 3), dtype=np.uint8), (0, 0), 3)
    body = cv2.GaussianBlur(rng.integers(0, 255, (350, 700, 3), dtype=np.uint8), (0, 0), 2)
    img[110:460, 200:900] = body
    if title:
        cv2.putText(img, 'GAME DATA', (135, 85), cv2.FONT_HERSHEY_DUPLEX, 1.2, (240, 240, 240), 2, cv2.LINE_AA)
    return img


def shift(img, dx, dy):
    return cv2.warpAffine(img, np.float32([[1, 0, dx], [0, 1, dy]]), img.shape[1::-1], borderMode=cv2.BORDER_REPLICATE)


REF_T, REF_S = page(1), page(2)


@pytest.mark.parametrize('dx,dy', [(0, 0), (12, 0), (-12, 0), (0, 12), (0, -12), (7, -9), (-12, 12)])
def test_locate_finds_shift(dx, dy):
    score, fx, fy = SM.locate(shift(REF_T, dx, dy), REF_T, SM.TITLE, search=16)
    assert score > 0.99 and (fx, fy) == (dx, dy)


def test_locate_without_search_misses_shift():
    score, _, _ = SM.locate(shift(REF_T, 8, 0), REF_T, SM.TITLE, search=0)
    assert score < SM.TITLE_MIN


def test_locate_flat_frame_scores_zero():
    score, _, _ = SM.locate(np.zeros_like(REF_T), REF_T, SM.TITLE)
    assert score == 0.0


def test_classify_shifted_title_table_and_totals():
    kind, score, off = SM.classify_gamedata(shift(REF_T, 8, 8), REF_T, REF_S)
    assert (kind, off) == ('TABLE', (8, 8)) and score > 0.99
    kind, score, off = SM.classify_gamedata(shift(REF_S, -8, 5), REF_T, REF_S)
    assert (kind, off) == ('TOTALS', (-8, 5)) and score > 0.9


def test_classify_full_hd_frame_reports_960_offsets():
    big = cv2.resize(shift(REF_T, 6, -4), (1920, 1080), interpolation=cv2.INTER_CUBIC)
    kind, score, off = SM.classify_gamedata(big, REF_T, REF_S)
    assert kind == 'TABLE' and off == (6, -4) and score > 0.9


def test_classify_rejects_frame_without_title():
    kind, score, _ = SM.classify_gamedata(page(3, title=False), REF_T, REF_S)
    assert kind is None and score < SM.TITLE_MIN


def test_shifted_window_clips_to_frame():
    fw, rw = SM.shifted(SM.BODY, 0, 100, (540, 960))
    assert fw[0] == slice(210, 540) and rw[0] == slice(110, 440)
