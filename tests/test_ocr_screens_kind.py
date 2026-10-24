"""ocr_screens.screen_kind with a small position search: a ban or POTM screen whose graphics sit a few pixels off the
reference is still recognised; at offset 0 it scores as before. Synthetic 960x540 references stand in for
data/ref/ban_960.jpg and potm_960.jpg (local to the capture PC)."""
import os, sys

import cv2, numpy as np, pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import ocr_screens as S


def backdrop(seed):
    rng = np.random.default_rng(seed)
    return cv2.GaussianBlur(rng.integers(0, 90, (540, 960, 3), dtype=np.uint8), (0, 0), 3)


def ban_ref():
    img = backdrop(1)
    cv2.putText(img, 'SELECTED MAP', (433, 455), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (235, 235, 235), 1, cv2.LINE_AA)
    return img


def potm_ref():
    img = backdrop(2)
    cv2.putText(img, 'PLAYER OF THE MATCH', (150, 50), cv2.FONT_HERSHEY_DUPLEX, 1.1, (245, 245, 245), 2, cv2.LINE_AA)
    return img


def gamedata_page():
    img = backdrop(3)
    cv2.putText(img, 'GAME DATA', (135, 85), cv2.FONT_HERSHEY_DUPLEX, 1.2, (240, 240, 240), 2, cv2.LINE_AA)
    for r in range(10):
        cv2.putText(img, f'PLAYER{r}  12  3  4  9876', (220, 140 + r * 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 1)
    return img


def broadcast(img960, dx=0, dy=0):
    """the 1920x1080 frame OBS saves, its graphics moved by (dx, dy) px of the 960 grid"""
    moved = cv2.warpAffine(img960, np.float32([[1, 0, dx], [0, 1, dy]]), (960, 540), borderMode=cv2.BORDER_REPLICATE)
    return cv2.resize(moved, (1920, 1080), interpolation=cv2.INTER_CUBIC)


@pytest.fixture(autouse=True)
def refs(monkeypatch):
    monkeypatch.setattr(S, 'REF_BAN', ban_ref())
    monkeypatch.setattr(S, 'REF_POTM', potm_ref())


@pytest.mark.parametrize('dx,dy', [(0, 0), (4, 0), (-8, 0), (0, 8), (0, -6), (12, -4), (-10, 10)])
def test_shifted_screens_are_still_found(dx, dy):
    assert S.screen_kind(broadcast(ban_ref(), dx, dy)) == 'BAN'
    assert S.screen_kind(broadcast(potm_ref(), dx, dy)) == 'POTM'


def test_offset_zero_only_misses_the_shift():
    assert S.screen_kind(broadcast(ban_ref(), 8, 0), search=0) is None
    assert S.screen_kind(broadcast(potm_ref(), 0, 8), search=0) is None


def test_offset_zero_score_is_the_old_one():
    s = S.small(broadcast(ban_ref()))
    old = cv2.matchTemplate(s[S.BAN_KEY], S.REF_BAN[S.BAN_KEY], cv2.TM_CCOEFF_NORMED)[0][0]
    assert S.key_score(s, S.REF_BAN, S.BAN_KEY, search=0) == pytest.approx(float(old))
    assert S.key_score(s, S.REF_BAN, S.BAN_KEY) >= S.key_score(s, S.REF_BAN, S.BAN_KEY, search=0)
    assert (S.BAN_MIN, S.POTM_MIN) == (0.8, 0.85)


@pytest.mark.parametrize('frame', [gamedata_page(), backdrop(4), np.zeros((540, 960, 3), np.uint8),
                                   np.full((540, 960, 3), 255, np.uint8)])
def test_other_screens_stay_unrecognised(frame):
    assert S.screen_kind(broadcast(frame)) is None
    assert S.screen_kind(broadcast(frame, 6, -6)) is None


def test_shift_beyond_the_search_is_not_claimed():
    assert S.screen_kind(broadcast(ban_ref(), 40, 0)) is None
