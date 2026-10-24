"""Offset-tolerant template matching for broadcast screens (OCR-07).

Comparing a window of the frame with the same window of a reference at offset (0, 0) only (what live_capture.classify
and ocr_screens.screen_kind did before): a 2 px shift of the graphics drops the score below the threshold, 4 px makes
it 0.27. Here the window is searched +-`search` px with matchTemplate + minMaxLoc, and the offset found is returned so
readers can shift their own boxes by it (live_capture: +-16 px, shifts the saved GAME DATA frame; ocr_screens: +-12 px,
detection only).

All coordinates are on the 960x540 grid; multiply offsets by 2 for 1920x1080 crops (img.shape[1] / 960 in general).
"""
from __future__ import annotations

import cv2, numpy as np

SMALL = (960, 540)
TITLE = (slice(48, 95), slice(128, 300))      # 'GAME DATA' title (same windows as live_capture / vod_pipeline)
BODY = (slice(110, 460), slice(200, 900))     # table body: TABLE vs TOTALS page
TITLE_MIN = 0.6

Window = tuple[slice, slice]


def small(img: np.ndarray) -> np.ndarray:
    """960x540 version of a frame (INTER_AREA, as the references were made)"""
    return img if img.shape[1::-1] == SMALL else cv2.resize(img, SMALL, interpolation=cv2.INTER_AREA)


def locate(small_frame: np.ndarray, ref_small: np.ndarray, window: Window, search: int = 16) -> tuple[float, int, int]:
    """Best match of ref_small[window] inside small_frame[window] padded by +-search px.
    -> (score TM_CCOEFF_NORMED, dx, dy): the template sits at window shifted by (dx, dy) in small_frame.
    Near the frame border the search area is clipped, so offsets towards the border are bounded by it."""
    ys, xs = window
    tpl = ref_small[ys, xs]
    th, tw = tpl.shape[:2]
    fh, fw = small_frame.shape[:2]
    y0, x0 = max(0, ys.start - search), max(0, xs.start - search)
    y1, x1 = min(fh, ys.start + th + search), min(fw, xs.start + tw + search)
    area = small_frame[y0:y1, x0:x1]
    if area.shape[0] < th or area.shape[1] < tw: return 0.0, 0, 0
    res = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
    res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)   # flat template or flat area -> no information, not a match
    _, score, _, (bx, by) = cv2.minMaxLoc(res)
    return float(score), x0 + bx - xs.start, y0 + by - ys.start


def shifted(window: Window, dx: int, dy: int, shape: tuple[int, ...]) -> tuple[Window, Window]:
    """(frame window moved by dx, dy and clipped to shape, matching window in the reference)"""
    ys, xs = window
    h, w = shape[:2]
    fy0, fy1 = max(0, ys.start + dy), min(h, ys.stop + dy)
    fx0, fx1 = max(0, xs.start + dx), min(w, xs.stop + dx)
    return (slice(fy0, fy1), slice(fx0, fx1)), (slice(fy0 - dy, fy1 - dy), slice(fx0 - dx, fx1 - dx))


def classify_gamedata(img: np.ndarray, ref_title_small: np.ndarray, ref_totals_small: np.ndarray,
                      search: int = 16) -> tuple[str | None, float, tuple[int, int]]:
    """live_capture.classify with offset search. ref_title_small = 960 TABLE page (m_3480), ref_totals_small = 960
    TOTALS page (m_9465). -> ('TABLE' | 'TOTALS' | None, title score, (dx, dy) on the 960 grid).
    The body is compared at the offset found for the title, so a shifted page still reads as the right kind."""
    s = small(img)
    score, dx, dy = locate(s, ref_title_small, TITLE, search)
    if score < TITLE_MIN: return None, score, (dx, dy)
    fw, rw = shifted(BODY, dx, dy, s.shape)
    body = s[fw].astype(np.float32)
    dt = np.abs(body - ref_title_small[rw]).mean()
    ds = np.abs(body - ref_totals_small[rw]).mean()
    return ('TOTALS' if ds < dt else 'TABLE'), score, (dx, dy)
