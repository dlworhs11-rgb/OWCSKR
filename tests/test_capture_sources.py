"""live_capture: frame-source selection (obs / hls), GAME DATA offset search + alignment, broadcast window (RP-15),
map continuation across outages / restarts (RP-16), FrozenDetector reset (RP-17)."""
import datetime
import json
import os
import sys
import time

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import frames as F
import live_capture as LC
import screen_match as SM
from test_capture_live import Clock, FakeSource, Screens, StubCapture, frame, noisy
from test_frames import FFMPEG, live_hls  # noqa: F401  (live_hls is a fixture)

KST = datetime.timezone(datetime.timedelta(hours=9))


# ---- source selection ----------------------------------------------------------------------------------------

def test_default_source_is_obs_with_the_player_page():
    a = LC.parse_args([], env={})
    assert a.source == 'obs' and a.url == LC.obs_setup.LIVE_URL and a.keyframes is False
    assert LC.source_factory_for(a) is LC.ObsSource


def test_hls_from_env_with_channel_and_keyframes():
    env = {'OWCSKR_FRAME_SOURCE': 'hls', 'OWCSKR_HLS_CHANNEL': 'otherchan', 'OWCSKR_HLS_KEYFRAMES': '1'}
    a = LC.parse_args([], env=env)
    assert (a.source, a.url, a.keyframes) == ('hls', 'otherchan', True)
    src = LC.source_factory_for(a)(a.url, lambda *x: None)
    try:
        assert isinstance(src, F.HlsSource) and src.src.keyframes_only is True and src.ready() is True
    finally:
        src.close()                                     # never started: no yt-dlp, no ffmpeg


def test_hls_defaults_and_cli_wins_over_env():
    assert LC.parse_args(['--source', 'hls'], env={}).url == 'owesports'
    assert LC.parse_args(['--source', 'hls'], env={'OWCSKR_HLS_KEYFRAMES': '0'}).keyframes is False
    a = LC.parse_args(['--source', 'OBS', '--url', 'https://x/'], env={'OWCSKR_FRAME_SOURCE': 'hls'})
    assert (a.source, a.url) == ('obs', 'https://x/')


def test_unknown_env_source_is_obs_with_a_warning(capsys):
    """the same as every other reader of OWCSKR_FRAME_SOURCE (platform_util.frame_source, run_live.sh)"""
    a = LC.parse_args([], env={'OWCSKR_FRAME_SOURCE': 'webcam'})
    assert a.source == 'obs' and a.url == LC.obs_setup.LIVE_URL
    assert "OWCSKR_FRAME_SOURCE='webcam' is not obs or hls - using obs" in capsys.readouterr().err
    assert LC.parse_args([], env={'OWCSKR_FRAME_SOURCE': ' HLS '}).source == 'hls'


def test_unknown_cli_source_is_rejected(capsys):
    with pytest.raises(SystemExit) as e:
        LC.parse_args(['--source', 'webcam'], env={'OWCSKR_FRAME_SOURCE': 'hls'})
    assert e.value.code == 2 and 'webcam' in capsys.readouterr().err


class Ready(FakeSource):
    def __init__(self): super().__init__([])
    def ready(self): return True
    def start(self): pass


def test_run_checks_and_builds_the_chosen_source(tmp_path, monkeypatch):
    seen, built = {}, []
    monkeypatch.setattr(LC.selfcheck, 'check', lambda **k: seen.update(k) or [])
    monkeypatch.setattr(LC, 'source_factory_for', lambda a: lambda url, log: built.append(url) or Ready())
    monkeypatch.setattr(LC, 'capture_loop', lambda *a, **k: None)
    monkeypatch.setattr(LC, 'broadcast_window', lambda day, log: None)
    monkeypatch.setattr(LC, 'run_ocr', lambda *x: True)
    monkeypatch.setattr(LC, 'send_summary', lambda *x, **k: None)
    a = LC.parse_args(['--date', '2026-10-25', '--hours', '1'], env={'OWCSKR_FRAME_SOURCE': 'hls'})
    assert LC.run(a, str(tmp_path), str(tmp_path), lambda *x: None, LC.Alerter(lambda t, x: None)) == 0
    assert seen == {'source': 'hls', 'publish': True} and built == ['owesports']


# ---- GAME DATA: offset search and alignment ------------------------------------------------------------------

@pytest.fixture
def refs(monkeypatch):
    rng = np.random.default_rng(7)
    ref_t = cv2.GaussianBlur(rng.integers(0, 255, (540, 960, 3), dtype=np.uint8), (5, 5), 0)
    ref_s = ref_t.copy()
    ref_s[SM.BODY] = cv2.GaussianBlur(rng.integers(0, 255, ref_s[SM.BODY].shape, dtype=np.uint8), (5, 5), 0)
    monkeypatch.setattr(LC, '_REFS', (ref_t, ref_s))
    return ref_t, ref_s


def shift(img, dx, dy):
    return cv2.warpAffine(img, np.float32([[1, 0, dx], [0, 1, dy]]), (img.shape[1], img.shape[0]))


def big(small_img):
    return cv2.resize(small_img, (1920, 1080), interpolation=cv2.INTER_NEAREST)


def old_score(img, ref_t):
    """the fixed-position title check live_capture.classify used before the search"""
    s = SM.small(img)
    return cv2.matchTemplate(s[SM.TITLE], ref_t[SM.TITLE], cv2.TM_CCOEFF_NORMED)[0][0]


def test_aligned_page_classifies_at_offset_zero(refs):
    ref_t, ref_s = refs
    assert LC.classify(big(ref_t)) == ('TABLE', (0, 0)) and LC.classify(big(ref_s)) == ('TOTALS', (0, 0))


def test_shifted_page_is_found_and_old_check_missed_it(refs):
    ref_t, _ = refs
    img = big(shift(ref_t, 5, -3))
    assert old_score(img, ref_t) < SM.TITLE_MIN
    assert LC.classify(img) == ('TABLE', (5, -3))


def test_search_score_is_never_below_the_old_check(refs):
    ref_t, _ = refs
    rng = np.random.default_rng(1)
    for i in range(12):
        dx, dy = (int(v) for v in rng.integers(-20, 21, 2))
        img = big(shift(ref_t, dx, dy)) if i % 3 else rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        _, score, _ = SM.classify_gamedata(img, *refs, LC.SEARCH)
        assert score >= old_score(img, ref_t) - 1e-6


def test_aligned_shifts_back_by_twice_the_offset():
    img = np.zeros((1080, 1920, 3), np.uint8)
    img[500:520, 900:940] = 255
    moved = LC.aligned(img, (3, -2))
    assert moved[504:524, 894:934].min() == 255 and moved[500:504].max() == 0 and moved.sum() == img.sum()
    assert LC.aligned(img, (0, 0)) is img


def test_shifted_game_data_is_saved_shifted_back(tmp_path, refs, monkeypatch):
    ref_t, _ = refs
    monkeypatch.setattr(LC, 'screens', lambda: Screens)
    logs = []
    cap = LC.Capture(str(tmp_path), lambda *x: logs.append(' '.join(map(str, x))), lambda: None, lambda: None)
    for dt in (0, 5, 10):
        cap.handle(big(shift(ref_t, 4, 2)), 1_000_000 + dt)
    saved = sorted(f for f in os.listdir(tmp_path) if 'table' in f)
    out = cv2.imread(str(tmp_path / saved[0]))
    want = big(ref_t)
    assert np.abs(out[40:1040, 40:1880].astype(int) - want[40:1040, 40:1880]).max() == 0
    assert sum('offset (4, 2)' in ln for ln in logs) == 1                     # logged once per map, not per frame


def test_unshifted_game_data_is_saved_as_is(tmp_path, refs, monkeypatch):
    ref_t, _ = refs
    monkeypatch.setattr(LC, 'screens', lambda: Screens)
    logs = []
    cap = LC.Capture(str(tmp_path), lambda *x: logs.append(' '.join(map(str, x))), lambda: None, lambda: None)
    for dt in (0, 5):
        cap.handle(big(ref_t), 1_000_000 + dt)
    out = cv2.imread(str(tmp_path / min(os.listdir(tmp_path))))
    assert np.array_equal(out, big(ref_t)) and not any('offset' in ln for ln in logs)


# ---- RP-15: broadcast window ---------------------------------------------------------------------------------

def match(hhmm, bestof=None, day='2026-10-25', title='OWCS 2026/Asia/Stage 3/Korea/Regular Season'):
    return {'date': f'{day}T{hhmm}:00+09:00', 'bestof': bestof, 'competitionTitle': title, 'team1': 'A', 'team2': 'B'}


def at(hhmm, day='2026-10-25'):
    h, m = map(int, hhmm.split(':'))
    return datetime.datetime.fromisoformat(day).replace(hour=h, minute=m, tzinfo=KST).timestamp()


def test_window_covers_matches_and_breaks_only():
    w = LC.BroadcastWindow([match('15:00'), match('17:30')])
    assert not w.active(at('14:55')) and w.active(at('15:00')) and w.active(at('17:10'))   # break between matches
    assert w.active(at('19:59')) and not w.active(at('20:00'))                              # 17:30 + 2.5 h
    assert LC.BroadcastWindow([match('15:00', bestof=7)]).active(at('18:30'))              # a BO7 gets 4 h


def test_window_ends_at_the_last_potm_but_not_an_earlier_one():
    w = LC.BroadcastWindow([match('15:00'), match('17:30')])
    assert w.active(at('17:20'), [at('17:15')])                       # first match's POTM: the second is still to come
    assert w.active(at('17:50'), [at('17:15'), at('17:45')])          # a POTM 15 min into the last match: too early
    assert not w.active(at('19:20'), [at('17:15'), at('19:10')])      # the last match's POTM: the day is over


def test_window_with_guessed_playoff_times_needs_every_potm():
    w = LC.BroadcastWindow([match('15:00', 7), match('15:00', 7)])    # TBD times: all on the weekday's usual start
    assert w.active(at('18:00'), [at('17:50')])
    assert not w.active(at('20:00'), [at('17:50'), at('19:50')])


def write_schedule(tmp_path, matches, lp=None):
    p = tmp_path / 'matches.json'
    p.write_text(json.dumps(matches), encoding='utf-8')
    if lp is not None:
        (tmp_path / 'lp').mkdir()
        (tmp_path / 'lp' / 'owcs-2026-asia-stage-3-korea.json').write_text(json.dumps({'matches': lp}), encoding='utf-8')
    return str(p), str(tmp_path / 'lp')


def test_schedule_from_matches_and_tbd_playoffs(tmp_path):
    other = match('12:00', title='OWCS 2026/NA/Stage 3')
    path, lp = write_schedule(tmp_path, [match('15:00'), other, match('18:00', day='2026-10-26')],
                              lp=[{'date': '2026-10-25T19:00:00+09:00', 'bestof': 7}])
    ms = LC.todays_matches('2026-10-25', lambda *x: None, path, lp)
    assert [m['date'][11:16] for m in ms] == ['15:00', '19:00']
    w = LC.broadcast_window('2026-10-25', lambda *x: None, path, lp)
    assert w.active(at('22:30')) and not w.active(at('23:00'))


def test_schedule_without_lp_pages_or_matches(tmp_path):
    path, _ = write_schedule(tmp_path, [match('15:00')])
    assert len(LC.todays_matches('2026-10-25', lambda *x: None, path, str(tmp_path / 'missing'))) == 1
    logs = []
    assert LC.broadcast_window('2026-10-27', lambda *x: logs.append(x), path, str(tmp_path / 'missing')) is None
    assert LC.broadcast_window('2026-10-25', lambda *x: logs.append(x), str(tmp_path / 'nope.json')) is None
    assert sum('stay on' in str(ln) for ln in logs) == 2


def window_loop(tmp_path, src, start, seconds, window, potms=(), alert=None):
    clock, logs = Clock(start), []
    cap = StubCapture()
    cap.potms = list(potms)
    LC.capture_loop(src, cap, clock() + seconds, str(tmp_path), lambda *x: logs.append(' '.join(map(str, x))),
                    alert or (lambda *a, **k: True), clock=clock, sleep=clock.sleep, window=window)
    return logs


def test_offline_page_after_the_window_neither_refreshes_nor_alerts(tmp_path):
    w, sent = LC.BroadcastWindow([match('15:00')]), []
    src = FakeSource([noisy(3)] * 400)
    logs = window_loop(tmp_path, src, at('17:40'), 1200, w, alert=lambda k, t, x: sent.append(k))
    assert src.refreshes == 0 and sent == []
    assert sum('outside the broadcast window' in ln for ln in logs) == 1


def test_offline_page_after_the_last_potm_is_quiet(tmp_path):
    w, sent = LC.BroadcastWindow([match('15:00')]), []
    src = FakeSource([noisy(3)] * 400)
    window_loop(tmp_path, src, at('17:00'), 900, w, potms=[at('16:50')], alert=lambda k, t, x: sent.append(k))
    assert src.refreshes == 0 and sent == []


def test_frozen_stream_in_a_break_is_still_detected(tmp_path):
    w, sent = LC.BroadcastWindow([match('15:00'), match('17:30')]), []
    src = FakeSource([noisy(3)] * 400)
    window_loop(tmp_path, src, at('17:05'), 400, w, potms=[at('17:00')], alert=lambda k, t, x: sent.append(k))
    assert src.refreshes >= 1 and sent == ['frozen']


def test_outage_alert_only_inside_the_window(tmp_path):
    w = LC.BroadcastWindow([match('15:00')])
    inside, outside = [], []
    window_loop(tmp_path, FakeSource([RuntimeError('down')] * 80), at('16:00'), 600, w, alert=lambda k, t, x: inside.append(k))
    window_loop(tmp_path, FakeSource([RuntimeError('down')] * 80), at('18:00'), 600, w, alert=lambda k, t, x: outside.append(k))
    assert 'frames-down' in inside and 'frames-down' not in outside


def test_frozen_before_the_window_counts_from_its_start(tmp_path):
    w, sent = LC.BroadcastWindow([match('15:00')]), []
    src = FakeSource([noisy(3)] * 400)
    clock = Clock(at('14:50'))
    cap = StubCapture()
    cap.potms = []
    LC.capture_loop(src, cap, at('15:04'), str(tmp_path), lambda *x: None, lambda k, t, x: sent.append(k),
                    clock=clock, sleep=clock.sleep, window=w)
    assert sent == [] and src.refreshes == 2                 # 15:01 and 15:03; 14 min frozen, but only 4 in the window


# ---- RP-16: continuing a map ---------------------------------------------------------------------------------

@pytest.fixture
def kinds(monkeypatch):
    monkeypatch.setattr(LC, 'classify', lambda img: ({1: 'TABLE', 2: 'TOTALS'}.get(int(img[0, 0, 0])), (0, 0)))
    monkeypatch.setattr(LC, 'screens', lambda: Screens)


def capture(tmp_path):
    closed = []
    return LC.Capture(str(tmp_path), lambda *x: None, lambda: closed.append(1), lambda: None), closed


def test_restart_mid_map_continues_its_number(tmp_path, kinds):
    t0 = 1_000_000
    first, _ = capture(tmp_path)
    for dt in (0, 5, 10):
        first.handle(frame(1), t0 + dt)
    first.handle(frame(2), t0 + 15)
    first.close_cluster(process=False)                        # SIGTERM / crash: the finally of capture_loop
    again, closed = capture(tmp_path)                          # systemd restarts it ~1.5 min later
    for dt in (110, 115, 121):
        again.handle(frame(2), t0 + dt)
    again.handle(frame(9), t0 + 200)
    names = sorted(os.listdir(tmp_path))
    assert all(n.startswith('m01_') for n in names), names
    assert [n for n in names if 'totals' in n] == [f'm01_totals_{t0 + 15}.png', f'm01_totals_{t0 + 110}.png',
                                                   f'm01_totals_{t0 + 115}.png']
    assert again.detected == 0 and closed == [1]


def test_restart_long_after_the_map_starts_a_new_one(tmp_path, kinds):
    (tmp_path / 'm03_table1_1000.png').write_bytes(b'')
    cap, _ = capture(tmp_path)
    cap.handle(frame(1), 1000 + LC.MAP_RESUME_GAP + 1)
    assert cap.cluster['n'] == 4 and cap.detected == 1


def test_source_outage_mid_map_keeps_the_number(tmp_path, kinds):
    cap, closed = capture(tmp_path)
    t0 = 1_000_000
    cap.handle(frame(1), t0)
    cap.handle(frame(1), t0 + 5)
    cap.handle(frame(2), t0 + 100)                             # no frame for 95 s, then the same GAME DATA page
    assert cap.cluster['n'] == 1 and closed == []
    cap.handle(frame(2), t0 + 100 + LC.MAP_RESUME_GAP + 1)      # far too long for one page: the next map
    assert cap.cluster['n'] == 2 and closed == [1]


def test_other_screens_in_between_still_close_the_map(tmp_path, kinds):
    cap, closed = capture(tmp_path)
    t0 = 1_000_000
    cap.handle(frame(1), t0)
    cap.handle(frame(9), t0 + 70)
    cap.handle(frame(1), t0 + 90)
    assert closed == [1] and cap.cluster['n'] == 2


def test_potm_cards_saved_earlier_are_remembered(tmp_path, kinds):
    for f in ('potm_1500_1.png', 'potm_1500_2.png', 'potm_1500_t1.png', 'potm_9000_1.png', 'ban_1_1.png'):
        (tmp_path / f).write_bytes(b'')
    assert capture(tmp_path)[0].potms == [1500.0, 9000.0]


# ---- RP-17: FrozenDetector reset -----------------------------------------------------------------------------

def test_pause_resets_the_frozen_detector(tmp_path, monkeypatch):
    clock = Clock()
    pause = {'from': clock() + 40, 'until': clock() + 90}
    monkeypatch.setattr(LC, 'paused', lambda out: pause['until'] - clock() if pause['from'] <= clock() < pause['until'] else 0)
    src = FakeSource([noisy(3)] * 200)
    LC.capture_loop(src, StubCapture(), clock() + 145, str(tmp_path), lambda *x: None, lambda *a, **k: True,
                    clock=clock, sleep=clock.sleep)
    # the same frame 40 s before the pause and 55 s after it: 95 s would refresh without the reset
    assert src.refreshes == 0


def test_outage_resets_the_frozen_detector(tmp_path):
    img = noisy(3)
    src = FakeSource([img] * 8 + [RuntimeError('down')] + [img] * 10)       # 40 s same, a failed grab, 50 s same
    clock = Clock()
    LC.capture_loop(src, StubCapture(), clock() + 100, str(tmp_path), lambda *x: None, lambda *a, **k: True,
                    clock=clock, sleep=clock.sleep)
    assert src.refreshes == 0


def test_reset_forgets_everything():
    det = LC.FrozenDetector()
    for t in range(0, 70, 5):
        det.update(noisy(1), float(t))
    det.reset()
    assert (det.sig, det.since, det.refreshed, det.alerted) == (None, None, None, False)


# ---- the HLS source inside the real capture loop (ffmpeg) ----------------------------------------------------

@pytest.mark.skipif(not FFMPEG, reason='ffmpeg not installed (set FFMPEG_CMD to run)')
def test_real_hls_frames_through_the_capture(live_hls, monkeypatch, tmp_path):  # noqa: F811 (the fixture)
    monkeypatch.setenv('FFMPEG_CMD', FFMPEG)
    hls = F.HlsFrames(interval=1, resolver=lambda: (live_hls.url, {'Referer': F.REFERER}, {}))
    src = F.HlsSource(frames=hls, interval=1)
    shapes = []

    class Keep(StubCapture):
        def handle(self, img, now): shapes.append(img.shape)
        def period(self, now): return 1

    src.start()
    try:
        LC.capture_loop(src, Keep(), time.time() + 10, str(tmp_path / 'out'), lambda *x: None, lambda *a, **k: True)
    finally:
        src.close()
    assert shapes and set(shapes) == {(1080, 1920, 3)}
