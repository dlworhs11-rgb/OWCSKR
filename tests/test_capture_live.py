import datetime, json, os, signal, sys, types

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import live_capture as LC


class Clock:
    def __init__(self, t=1_000_000.0): self.t = t
    def __call__(self): return self.t
    def sleep(self, s): self.t += max(0.0, s)


def frame(value):
    return np.full((36, 64, 3), value, np.uint8)


def noisy(seed):
    return np.random.default_rng(seed).integers(40, 200, (36, 64, 3), dtype=np.uint8)


# ---- arguments / signals / alerts -----------------------------------------------------------------------------

def test_until_wins_over_hours():
    a = LC.parse_args(['--until', '2026-10-25T23:30:00+09:00', '--hours', '2'])
    want = datetime.datetime(2026, 10, 25, 14, 30, tzinfo=datetime.timezone.utc).timestamp()
    assert LC.end_time(a, 0) == want


def test_hours_and_default():
    assert LC.end_time(LC.parse_args(['--hours', '2']), 100.0) == 100.0 + 7200
    assert LC.end_time(LC.parse_args([]), 100.0) == 100.0 + 8 * 3600


def test_bad_until_is_rejected():
    with pytest.raises(SystemExit):
        LC.parse_args(['--until', 'tonight'])


def test_sigterm_raises_systemexit_once(monkeypatch):
    old = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(LC, '_STOPPING', False)
    try:
        LC.install_sigterm()
        handler = signal.getsignal(signal.SIGTERM)
        with pytest.raises(SystemExit) as e:
            handler(signal.SIGTERM, None)
        assert e.value.code == 0
        assert handler(signal.SIGTERM, None) is None          # second signal: let the final steps finish
    finally:
        signal.signal(signal.SIGTERM, old)


def test_sigterm_during_final_ocr_does_not_cut_it_short(tmp_path, monkeypatch):
    old = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(LC, '_STOPPING', False)
    done = []
    def ocr(*x):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)        # systemctl stop while the final OCR runs
        done.append('ocr'); return True
    monkeypatch.setattr(LC, 'run_ocr', ocr)
    monkeypatch.setattr(LC, 'update_and_publish', lambda *x: done.append('publish') or True)
    monkeypatch.setattr(LC, 'send_summary', lambda *x, **k: done.append('summary'))
    (tmp_path / 'ocr.json').write_text('[]', encoding='utf-8')
    a = LC.parse_args(['--date', '2026-10-25', '--until', '2020-01-01T00:00:00+00:00'])
    try:
        LC.install_sigterm()
        assert LC.run(a, str(tmp_path), str(tmp_path), lambda *x: None, LC.Alerter(lambda t, x: None)) == 0
    finally:
        signal.signal(signal.SIGTERM, old)
    assert done == ['ocr', 'publish', 'summary']


def test_alerts_are_rate_limited_per_key():
    clock, sent = Clock(), []
    alert = LC.Alerter(lambda t, x: sent.append(x), clock=clock)
    assert alert('ocr_run.py', 'T', 'a') and not alert('ocr_run.py', 'T', 'b')
    assert alert('publish_day.py', 'T', 'c')
    clock.t += 14 * 60
    assert not alert('ocr_run.py', 'T', 'd')
    clock.t += 61
    assert alert('ocr_run.py', 'T', 'e')
    assert sent == ['a', 'c', 'e']


def test_alert_limits_survive_a_restart(tmp_path):
    clock, sent, state = Clock(), [], str(tmp_path / 'alerts.json')
    assert LC.Alerter(lambda t, x: sent.append(x), clock=clock, state=state)('capture', 'T', 'first run')
    clock.t += 90                                                   # systemd restarts the crashed capture
    assert not LC.Alerter(lambda t, x: sent.append(x), clock=clock, state=state)('capture', 'T', 'second run')
    clock.t += 15 * 60
    assert LC.Alerter(lambda t, x: sent.append(x), clock=clock, state=state)('capture', 'T', 'later')
    assert sent == ['first run', 'later']
    (tmp_path / 'alerts.json').write_text('[not a dict', encoding='utf-8')
    assert LC.Alerter(lambda t, x: None, clock=clock, state=state).last == {}


def test_unreadable_map_is_alerted_once_not_after_every_map(monkeypatch):
    sent, clock = [], Clock()
    msg = {'err': 'Traceback ...\nocr_run: maps that could not be read: 03'}
    monkeypatch.setattr(LC.subprocess, 'run', lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout='5 maps', stderr=msg['err']))
    alert = LC.Alerter(lambda t, x: sent.append(x), clock=clock)
    for _ in range(4):                                              # ocr_run re-reads the whole day after each map
        assert LC.run_ocr('out', 'frames', lambda *x: None, alert) is False
        clock.t += 20 * 60
    assert len(sent) == 1
    msg['err'] = 'ocr_run: maps that could not be read: 03, 07'
    LC.run_ocr('out', 'frames', lambda *x: None, alert)
    assert len(sent) == 2


def test_alert_failure_never_raises(capsys):
    alert = LC.Alerter(lambda t, x: (_ for _ in ()).throw(OSError('no network')))
    assert alert('k', 'T', 'x') is True
    assert 'notify failed' in capsys.readouterr().err


def test_failed_step_logs_stderr_tail_and_alerts(monkeypatch):
    calls, logs, sent = [], [], []
    def fake_run(cmd, **kw):
        calls.append(kw)
        return types.SimpleNamespace(returncode=1, stdout='', stderr='x' * 900 + 'TAIL')
    monkeypatch.setattr(LC.subprocess, 'run', fake_run)
    alert = LC.Alerter(lambda t, x: sent.append(x), clock=Clock())
    log = lambda *x: logs.append(' '.join(map(str, x)))
    assert LC.run_script(['tools/assemble_day.py', '2026-10-25'], log, alert) is None
    assert LC.run_script(['tools/assemble_day.py', '2026-10-25'], log, alert) is None
    assert calls[0]['encoding'] == 'utf-8' and calls[0]['cwd'] == LC.ROOT
    assert logs[0].endswith('x' * 496 + 'TAIL') and 'x' * 501 not in logs[0]
    assert len(sent) == 1 and 'assemble_day.py 2026-10-25 failed (exit 1)' in sent[0]


def test_failed_assembly_is_not_published(monkeypatch):
    ran = []
    def fake_run(cmd, **kw):
        ran.append(os.path.basename(cmd[2]))
        return types.SimpleNamespace(returncode=1, stdout='', stderr='boom')
    monkeypatch.setattr(LC.subprocess, 'run', fake_run)
    assert LC.update_and_publish('2026-10-25', lambda *x: None, LC.Alerter(lambda t, x: None)) is False
    assert ran == ['assemble_day.py']


# ---- frozen / black frames -----------------------------------------------------------------------------------

def test_frozen_frame_refreshes_then_alerts_once():
    det, acts = LC.FrozenDetector(), {}
    img = noisy(1)
    for t in range(0, 601, 5):
        act = det.update(img, float(t))
        if act: acts.setdefault(act, []).append(t)
    assert acts['refresh'][0] == 60 and acts['alert'] == [300]
    assert all(b - a >= 120 for a, b in zip(acts['refresh'], acts['refresh'][1:]))


def test_black_frames_count_even_when_they_differ():
    det = LC.FrozenDetector()
    acts = [det.update(frame(t % 5), float(t)) for t in range(0, 70, 5)]
    assert 'refresh' in acts


def test_changing_frames_are_fine_and_reset():
    det = LC.FrozenDetector()
    assert all(det.update(noisy(t), float(t)) is None for t in range(0, 400, 5))
    for t in range(400, 455, 5):
        assert det.update(noisy(0), float(t)) is None              # 50 s frozen: not yet
    assert det.update(noisy(1), 455.0) is None and det.since is None


# ---- what is kept per map ------------------------------------------------------------------------------------

class Screens:
    @staticmethod
    def screen_kind(img): return None


@pytest.fixture
def kinds(monkeypatch):
    """frame pixel value -> GAME DATA kind: 1 = TABLE, 2 = TOTALS, else nothing"""
    monkeypatch.setattr(LC, 'classify', lambda img: {1: 'TABLE', 2: 'TOTALS'}.get(int(img[0, 0, 0])))
    monkeypatch.setattr(LC, 'screens', lambda: Screens)


def make_capture(tmp_path):
    closed, published = [], []
    cap = LC.Capture(str(tmp_path), lambda *x: None, lambda: closed.append(1), lambda: published.append(1))
    return cap, closed, published


def test_three_totals_frames_spaced_and_settled_tables(tmp_path, kinds):
    cap, closed, _ = make_capture(tmp_path)
    t0 = 1_000_000
    for dt in (0, 5, 10, 15, 20):
        cap.handle(frame(1), t0 + dt)
    for dt in (25, 27, 30, 32, 35, 40, 45):
        cap.handle(frame(2), t0 + dt)
    cap.handle(frame(9), t0 + 110)
    files = sorted(os.listdir(tmp_path))
    assert files == [f'm01_table1_{t0 + 5}.png', f'm01_table2_{t0 + 10}.png', f'm01_table3_{t0 + 15}.png',
                     f'm01_totals_{t0 + 25}.png', f'm01_totals_{t0 + 30}.png', f'm01_totals_{t0 + 35}.png']
    assert closed == [1] and cap.cluster is None and cap.detected == 1


def test_first_table_frame_is_only_a_fallback(tmp_path, kinds):
    cap, closed, _ = make_capture(tmp_path)
    t0 = 1_000_000
    cap.handle(frame(1), t0)
    cap.handle(frame(1), t0 + 1)
    cap.handle(frame(1), t0 + 6)
    cap.close_cluster()
    assert sorted(os.listdir(tmp_path)) == [f'm01_table1_{t0 + 6}.png', f'm01_table2_{t0}.png']
    assert closed == [1]


def test_map_numbers_continue_after_restart(tmp_path, kinds):
    (tmp_path / 'm07_table1_5.png').write_bytes(b'')
    cap, _, _ = make_capture(tmp_path)
    cap.handle(frame(1), 1_000_000)
    assert cap.cluster['n'] == 8


def test_potm_close_publishes_once(tmp_path, kinds):
    cap, closed, published = make_capture(tmp_path)
    cap.handle(frame(1), 1_000_000)
    cap.potm_close = 1_000_010
    cap.handle(frame(9), 1_000_011)
    assert closed == [1] and published == []                       # finish() publishes; no second update
    cap.potm_close = 1_000_020
    cap.handle(frame(9), 1_000_021)
    assert published == [1]


# ---- loop: recovery, frozen frames, errors -------------------------------------------------------------------

class FakeSource:
    def __init__(self, frames, alive=True):
        self.frames, self.is_alive = list(frames), alive
        self.restarts = self.refreshes = self.reconnects = 0

    def grab(self):
        f = self.frames.pop(0) if self.frames else noisy(len(self.frames))
        if isinstance(f, Exception): raise f
        return f() if callable(f) else f

    def reconnect(self): self.reconnects += 1
    def restart(self): self.restarts += 1; self.is_alive = True
    def refresh(self): self.refreshes += 1
    def alive(self): return self.is_alive
    def close(self): pass


class StubCapture:
    def __init__(self, fail=None):
        self.seen, self.fail, self.idle_stop, self.closed = [], fail, 75, False
    def handle(self, img, now):
        if self.fail: raise self.fail
        self.seen.append(now)
    def idle_over(self, now): return False
    def period(self, now): return 5
    def close_cluster(self, process=True): self.closed = True


def loop(tmp_path, source, cap, seconds, alert=None):
    clock, logs = Clock(), []
    LC.capture_loop(source, cap, clock() + seconds, str(tmp_path), lambda *x: logs.append(' '.join(map(str, x))),
                    alert or (lambda *a: True), clock=clock, sleep=clock.sleep)
    return logs


def test_source_restarted_after_a_minute_of_failures(tmp_path):
    src = FakeSource([RuntimeError('ws closed')] * 30)
    cap = StubCapture()
    logs = loop(tmp_path, src, cap, 400)
    assert src.restarts >= 1 and src.reconnects >= 5
    first = next(i for i, ln in enumerate(logs) if 'restarting the frame source' in ln)
    assert sum('screenshot failed' in ln for ln in logs[:first]) >= 12      # about a minute of 5 s retries first
    assert cap.seen and cap.closed


def test_source_restarted_at_once_when_process_is_gone(tmp_path):
    src = FakeSource([RuntimeError('refused')], alive=False)
    loop(tmp_path, src, StubCapture(), 30)
    assert src.restarts == 1 and src.reconnects == 0


def test_long_outage_alerts(tmp_path):
    src, sent = FakeSource([RuntimeError('down')] * 60), []
    loop(tmp_path, src, StubCapture(), 600, alert=lambda key, t, x: sent.append(key))
    assert 'frames-down' in sent


def test_frozen_stream_triggers_refresh(tmp_path):
    img = noisy(3)
    src = FakeSource([img] * 30)
    loop(tmp_path, src, StubCapture(), 120)
    assert src.refreshes == 1


def test_loop_errors_are_skipped_and_alerted_once(tmp_path):
    src, sent = FakeSource([]), []
    cap = StubCapture(fail=ValueError('bad frame'))
    logs = loop(tmp_path, src, cap, 200, alert=lambda key, t, x: sent.append(key))
    assert sum('loop error' in ln for ln in logs) >= 30
    assert sent == ['loop:ValueError: bad frame']


def test_sigterm_in_loop_still_closes_the_map(tmp_path):
    class Stop(StubCapture):
        def handle(self, img, now): raise SystemExit(0)
    cap = Stop()
    with pytest.raises(SystemExit):
        loop(tmp_path, FakeSource([]), cap, 100)
    assert cap.closed


def test_pause_file_skips_grabs(tmp_path):
    (tmp_path / 'pause.json').write_text(json.dumps({'until': 4e9}), encoding='utf-8')
    src = FakeSource([RuntimeError('should not grab')])
    loop(tmp_path, src, StubCapture(), 60)
    assert len(src.frames) == 1


# ---- end of day -----------------------------------------------------------------------------------------------

def write_day(out, ocr, maps, matches):
    os.makedirs(os.path.join(out, 'frames'), exist_ok=True)
    with open(os.path.join(out, 'ocr.json'), 'w', encoding='utf-8') as fh: json.dump(ocr, fh)
    with open(os.path.join(out, 'mapstats.json'), 'w', encoding='utf-8') as fh: json.dump({'maps': maps, 'matches': matches}, fh)


def test_summary_counts(tmp_path):
    out = str(tmp_path)
    write_day(out, [{'map': '01', 'totalsOK': True}, {'map': '02', 'totalsOK': False, 'verifyReason': 'sums do not match the totals page'},
                    {'map': '03', 'totalsOK': None, 'verifyReason': 'no totals frame'}],
              [{'totalsVerified': True, 'teams': {'A': [{'name': 'Faith'}, {'name': None, 'unknownId': '?1'}]}},
               {'totalsVerified': True, 'labelVerified': False, 'teams': {'B': [{'name': '?2'}, {'name': 'Bliss'}]}},
               {'totalsVerified': False, 'teams': {}}],
              [{'match': 'CR vs O2', 'potm': {'method': 'name'}}, {'match': 'ZAN vs TF', 'potm': None}])
    for n in ('01', '02', '03', '04'):
        open(os.path.join(out, 'frames', f'm{n}_table1_1.png'), 'wb').close()
    s = LC.day_summary(out, os.path.join(out, 'frames'))
    assert (s['detected'], s['read'], s['verified'], s['published']) == (4, 3, 1, 1)
    assert s['failed'] == ['m02 (sums do not match the totals page)', 'm03 (no totals frame)']
    assert (s['unknown'], s['rows']) == (2, 4)
    text = LC.summary_text('2026-10-25', s)
    assert 'unknown names 2/4 (50%)' in text and 'CR vs O2: name' in text and 'ZAN vs TF: none' in text


def test_zero_maps_sends_a_warning(tmp_path):
    sent = []
    os.makedirs(tmp_path / 'frames')
    LC.send_summary('2026-10-25', str(tmp_path), str(tmp_path / 'frames'), lambda *x: None, notify=lambda t, x: sent.append(t))
    assert sent == ['OWCSKR 캡처 경고'] and (tmp_path / LC.SUMMARY_MARK).exists()


# ---- run(): self-check, finishing, exit codes ----------------------------------------------------------------

def args(**kw):
    a = LC.parse_args(['--date', '2026-10-25', '--hours', '1'])
    for k, v in kw.items(): setattr(a, k, v)
    return a


@pytest.fixture
def steps(monkeypatch):
    done = []
    monkeypatch.setattr(LC, 'run_ocr', lambda *x: done.append('ocr') or True)
    monkeypatch.setattr(LC, 'update_and_publish', lambda *x: done.append('publish') or True)
    monkeypatch.setattr(LC, 'send_summary', lambda *x, **k: done.append('summary'))
    return done


def test_selfcheck_failure_exits_2(tmp_path, monkeypatch, steps):
    sent = []
    monkeypatch.setattr(LC.selfcheck, 'check', lambda: [LC.selfcheck.Problem('fatal', 'tesseract', 'missing')])
    monkeypatch.setattr(LC.PU, 'notify', lambda t, x: sent.append(x))
    rc = LC.run(args(), str(tmp_path), str(tmp_path), lambda *x: None, LC.Alerter(lambda t, x: None),
                source_factory=lambda *a: pytest.fail('source must not start'))
    assert rc == 2 and 'tesseract' in sent[0] and steps == []


def test_window_over_only_finalizes(tmp_path, steps):
    a = args(until=datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc))
    (tmp_path / 'ocr.json').write_text('[]', encoding='utf-8')
    assert LC.run(a, str(tmp_path), str(tmp_path), lambda *x: None, LC.Alerter(lambda t, x: None)) == 0
    assert steps == ['ocr', 'publish', 'summary']                 # no summary went out yet today
    (tmp_path / LC.SUMMARY_MARK).write_text('sent', encoding='utf-8')
    steps.clear()
    assert LC.run(a, str(tmp_path), str(tmp_path), lambda *x: None, LC.Alerter(lambda t, x: None)) == 0
    assert steps == ['ocr', 'publish']


class ReadySource(FakeSource):
    def __init__(self): super().__init__([]); self.started = self.closed = False
    def ready(self): return True
    def start(self): self.started = True
    def close(self): self.closed = True


def test_sigterm_during_capture_finishes_the_day(tmp_path, monkeypatch, steps):
    monkeypatch.setattr(LC.selfcheck, 'check', lambda: [])
    src = ReadySource()
    monkeypatch.setattr(LC, 'capture_loop', lambda *a, **k: (_ for _ in ()).throw(SystemExit(0)))
    (tmp_path / 'ocr.json').write_text('[]', encoding='utf-8')
    rc = LC.run(args(), str(tmp_path), str(tmp_path), lambda *x: None, LC.Alerter(lambda t, x: None), source_factory=lambda *a: src)
    assert rc == 0 and src.started and src.closed and steps == ['ocr', 'publish']
    # stopped an hour before --until (reboot, systemctl stop): the run after it sends the day's one summary


def test_crash_at_the_end_sends_the_summary(tmp_path, monkeypatch, steps):
    monkeypatch.setattr(LC.selfcheck, 'check', lambda: [])
    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=2)
    monkeypatch.setattr(LC, 'capture_loop', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    rc = LC.run(args(until=end), str(tmp_path), str(tmp_path), lambda *x: None, LC.Alerter(lambda t, x: None),
                source_factory=lambda *a: ReadySource())
    assert rc == 1 and steps == ['ocr', 'summary']                 # its restart would find the day over: nothing follows


def test_summary_due_rules(tmp_path):
    out, end = str(tmp_path), 10_000.0
    assert LC.summary_due('done', end, 100.0, out)                              # idle stop: the day is over
    assert not LC.summary_due('stopped', end, 100.0, out) and not LC.summary_due('crashed', end, 100.0, out)
    assert LC.summary_due('stopped', end, end - 60, out) and LC.summary_due('crashed', end, end - 60, out)
    (tmp_path / LC.SUMMARY_MARK).write_text('sent', encoding='utf-8')
    assert not LC.summary_due('done', end, end, out)                            # never twice a day


def test_crash_exits_1_without_summary(tmp_path, monkeypatch, steps):
    monkeypatch.setattr(LC.selfcheck, 'check', lambda: [])
    src, sent = ReadySource(), []
    monkeypatch.setattr(LC, 'capture_loop', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    rc = LC.run(args(), str(tmp_path), str(tmp_path), lambda *x: None, LC.Alerter(lambda t, x: sent.append(x)),
                source_factory=lambda *a: src)
    assert rc == 1 and src.closed and 'summary' not in steps and 'boom' in sent[0]


def test_failed_final_publish_exits_1(tmp_path, monkeypatch, steps):
    monkeypatch.setattr(LC.selfcheck, 'check', lambda: [])
    monkeypatch.setattr(LC, 'capture_loop', lambda *a, **k: None)
    monkeypatch.setattr(LC, 'update_and_publish', lambda *x: False)
    (tmp_path / 'ocr.json').write_text('[]', encoding='utf-8')
    rc = LC.run(args(), str(tmp_path), str(tmp_path), lambda *x: None, LC.Alerter(lambda t, x: None),
                source_factory=lambda *a: ReadySource())
    assert rc == 1 and steps == ['ocr', 'summary']                # the day still gets its summary


def test_busy_obs_exits_2(tmp_path, monkeypatch, steps):
    monkeypatch.setattr(LC.selfcheck, 'check', lambda: [])
    monkeypatch.setattr(LC.PU, 'notify', lambda t, x: None)
    src = ReadySource(); src.ready = lambda: False
    assert LC.run(args(), str(tmp_path), str(tmp_path), lambda *x: None, LC.Alerter(lambda t, x: None),
                  source_factory=lambda *a: src) == 2
    assert not src.started


def test_obs_not_answering_exits_1_and_alerts(tmp_path, monkeypatch, steps):
    monkeypatch.setattr(LC.selfcheck, 'check', lambda: [])
    sent = []
    src = ReadySource()
    def ready(): raise TimeoutError('websocket')
    src.ready = ready
    assert LC.run(args(), str(tmp_path), str(tmp_path), lambda *x: None, LC.Alerter(lambda t, x: sent.append(x)),
                  source_factory=lambda *a: src) == 1
    assert not src.started and steps == [] and 'did not answer' in sent[0]


# ---- OBS frame source (no OBS: obs_setup and the websocket client are faked) ---------------------------------

class FakeOBS:
    instances = []
    def __init__(self): self.closed, self.calls = False, []; FakeOBS.instances.append(self)
    async def connect(self): return self
    async def close(self): self.closed = True
    async def screenshot(self, source):
        import cv2
        return cv2.imencode('.png', frame(77))[1].tobytes()
    async def call(self, req, data=None):
        self.calls.append((req, data))
        return {'currentSceneCollectionName': 'OWCSKR'}


@pytest.fixture
def obs(monkeypatch):
    state = {'running': False, 'starts': 0, 'kills': 0, 'fail': False}
    def start(url):
        if state['fail']: raise SystemExit('could not reach OBS websocket: refused')
        state['starts'] += 1; state['running'] = True
    def kill(name): state['kills'] += 1; state['running'] = False
    FakeOBS.instances.clear()
    monkeypatch.setattr(LC.obs_setup, 'running', lambda: state['running'])
    monkeypatch.setattr(LC.obs_setup, 'start', start)
    monkeypatch.setattr(LC.PU, 'kill_process', kill)
    monkeypatch.setattr(LC, 'OBS', FakeOBS)
    return state


def test_obs_source_grab_restart_close(obs):
    src = LC.ObsSource('url', lambda *x: None)
    assert src.ready()
    src.start()
    assert src.started and obs['starts'] == 1
    assert int(src.grab()[0, 0, 0]) == 77
    old = src.obs
    src.restart()                                                 # ours and running: killed, relaunched, new socket
    assert old.closed and obs['kills'] == 1 and obs['starts'] == 2 and src.obs is not old
    src.refresh()
    assert src.obs.calls[-1] == ('PressInputPropertiesButton', {'inputName': LC.obs_setup.SOURCE, 'propertyName': 'refreshnocache'})
    src.close()
    assert obs['kills'] == 2 and src.obs is None


def test_obs_source_start_failure_is_an_error_not_an_exit(obs):
    obs['fail'] = True
    src = LC.ObsSource('url', lambda *x: None)
    with pytest.raises(RuntimeError, match='could not reach'):
        src.start()


def test_sigterm_while_waiting_for_obs_is_a_stop_not_an_error(obs, monkeypatch, tmp_path):
    def start(url): raise LC.StopRequested(0)
    monkeypatch.setattr(LC.obs_setup, 'start', start)
    src = LC.ObsSource('url', lambda *x: None)
    with pytest.raises(LC.StopRequested):
        src.start()

    class Dead(FakeSource):
        def restart(self): src.restart()                          # the real ObsSource restart, OBS start interrupted
    cap = StubCapture()
    with pytest.raises(LC.StopRequested):                         # not swallowed as 'restart FAILED' by the loop
        loop(tmp_path, Dead([RuntimeError('gone')], alive=False), cap, 30)
    assert cap.closed


def test_foreign_obs_is_not_ours(obs, monkeypatch):
    obs['running'] = True
    async def other(self, req, data=None): return {'currentSceneCollectionName': 'My scenes'}
    monkeypatch.setattr(FakeOBS, 'call', other)
    src = LC.ObsSource('url', lambda *x: None)
    assert src.ready() is False
    src.start()
    assert src.started is False                                   # already running: never killed by us
    src.close()
    assert obs['kills'] == 0
