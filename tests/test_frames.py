import io, json, os, shutil, subprocess, sys, threading, time

import cv2, numpy as np, pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import frames as F


def content(w, h, seed=0):
    """bright, textured 'broadcast' content"""
    rng = np.random.default_rng(seed)
    return cv2.GaussianBlur(rng.integers(60, 255, (h, w, 3), dtype=np.uint8), (0, 0), 2)


def wait_until(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond(): return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------- normalize

def test_normalize_passthrough_1080():
    img = content(1920, 1080)
    out, info = F.normalize(img)
    assert out.shape == (1080, 1920, 3) and np.array_equal(out, img)
    assert info['crop'] == (0, 0, 1920, 1080) and info['warn'] is None


def test_normalize_upscales_540():
    out, info = F.normalize(content(960, 540))
    assert out.shape == (1080, 1920, 3) and info['scale'] == (2.0, 2.0) and info['warn'] is None


def test_normalize_crops_letterbox():
    img = np.zeros((1200, 1920, 3), np.uint8); img[60:1140] = content(1920, 1080)
    out, info = F.normalize(img)
    assert out.shape == (1080, 1920, 3) and info['crop'] == (0, 60, 1920, 1140) and info['warn'] is None
    assert np.array_equal(out, img[60:1140])


def test_normalize_crops_pillarbox_tv_range_black():
    img = np.full((720, 1440, 3), 16, np.uint8); img[:, 80:1360] = content(1280, 720)   # 1280x720 inside, black = 16
    out, info = F.normalize(img)
    assert out.shape == (1080, 1920, 3) and info['crop'] == (80, 0, 1360, 720) and info['scale'] == (1.5, 1.5)


def test_normalize_crops_windowbox_from_ffmpeg_pad():
    # 16:9 broadcast letterboxed in a 1920x1200 stream, after ffmpeg's fit + pad: bars on all four sides
    img = np.zeros((1080, 1920, 3), np.uint8); img[54:1026, 96:1824] = content(1728, 972)
    out, info = F.normalize(img)
    assert info['crop'] == (96, 54, 1824, 1026) and info['warn'] is None and out.shape == (1080, 1920, 3)


def test_normalize_keeps_padded_non_16x9_content():
    # a 16:10 source after ffmpeg's fit + pad: 1728x1080 content pillarboxed; cropping would give 1.6, not 16:9
    img = np.zeros((1080, 1920, 3), np.uint8); img[:, 96:1824] = content(1728, 1080)
    out, info = F.normalize(img)
    assert out.shape == (1080, 1920, 3) and info['crop'] == (0, 0, 1920, 1080)
    assert 'kept' in info['warn']           # 1728x1080 = 1.6, cropping would break 16:9: dark edges are kept


def test_normalize_keeps_dark_middle():
    img = content(1920, 1080); img[200:880, 300:1620] = 0
    out, info = F.normalize(img)
    assert info['crop'] == (0, 0, 1920, 1080) and np.array_equal(out, img)


def test_normalize_keeps_dark_edges_of_16x9_frame():
    img = content(1920, 1080); img[:150] = 3; img[-150:] = 3      # dark scene top/bottom, not a letterbox
    out, info = F.normalize(img)
    assert info['crop'] == (0, 0, 1920, 1080) and np.array_equal(out, img) and info['warn']


def test_normalize_ignores_noisy_dark_edges():
    img = content(1920, 1200); rng = np.random.default_rng(5)
    img[:60] = rng.integers(0, 22, (60, 1920, 3), dtype=np.uint8)   # dark but textured: content, not a bar
    _, info = F.normalize(img)
    assert info['crop'][1] == 0


def test_normalize_black_frame_and_input_types():
    out, info = F.normalize(np.zeros((540, 960), np.uint8))
    assert out.shape == (1080, 1920, 3) and info['crop'] == (0, 0, 960, 540)
    out, _ = F.normalize(np.zeros((1080, 1920, 4), np.uint8))
    assert out.shape == (1080, 1920, 3)
    with pytest.raises(ValueError): F.normalize(np.zeros((0, 0, 3), np.uint8))
    with pytest.raises(ValueError): F.normalize(None)


def test_normalize_4x3_warns():
    _, info = F.normalize(content(1440, 1080))
    assert info['warn'] and 'stretched' in info['warn']


def panel_on_black(x0, y0, w, h):
    img = np.zeros((1080, 1920, 3), np.uint8); img[y0:y0 + h, x0:x0 + w] = content(w, h)
    return img


def test_normalize_keeps_off_centre_16x9_panel_on_black():
    # a 16:9 graphic in the top-left of a black screen used to be zoomed by 11 %, moving every reader's boxes
    _, info = F.normalize(panel_on_black(0, 0, 1728, 972))
    assert info['crop'] == (0, 0, 1920, 1080)


def test_normalize_crops_bars_with_compression_noise():
    rng = np.random.default_rng(3)
    img = np.clip(rng.normal(16, 1.5, (1080, 1920, 3)), 0, 255).astype(np.uint8)   # TV-range black, not perfectly flat
    img[:, 240:1680] = content(1440, 1080)[:, :1440]
    img[135:945, 240:1680] = content(1440, 810)                                     # 16:9 inside a 4:3 inside the pad
    img[:135, 240:1680] = img[945:, 240:1680] = 16
    _, info = F.normalize(img)
    assert info['crop'] == (240, 135, 1680, 945) and info['warn'] is None


def test_normalize_with_given_box():
    img = panel_on_black(160, 90, 1600, 900)
    out, info = F.normalize(img, box=(160, 90, 1760, 990))
    assert info['crop'] == (160, 90, 1760, 990) and info['scale'] == (1.2, 1.2) and out.shape == (1080, 1920, 3)
    assert F.normalize(img, box=(-5, -5, 5000, 5000))[1]['crop'] == (0, 0, 1920, 1080)


def test_stable_crop_ignores_a_short_centred_picture_on_black():
    sc, normal = F.StableCrop(hold=3), content(1920, 1080)
    assert F.normalize(panel_on_black(160, 90, 1600, 900))[1]['crop'] == (160, 90, 1760, 990)   # alone it would zoom
    for img in (normal, panel_on_black(160, 90, 1600, 900), panel_on_black(160, 90, 1600, 900), normal):
        out, info = sc(img)
        assert info['crop'] == (0, 0, 1920, 1080)
    assert 'kept' in sc(panel_on_black(160, 90, 1600, 900))[1]['warn']


def test_stable_crop_follows_lasting_bars_despite_jitter():
    sc = F.StableCrop(hold=3)
    crops = [sc(panel_on_black(96, 54 + j, 1728, 972 - 2 * j))[1]['crop'] for j in (0, 1, 0, 1, 0)]
    assert crops[:2] == [(0, 0, 1920, 1080)] * 2 and crops[2] == (96, 54, 1824, 1026)
    assert crops[3] == crops[4] == (96, 54, 1824, 1026)           # 1 px jitter does not re-frame
    assert sc(content(1920, 1080))[1]['crop'] == (96, 54, 1824, 1026)   # nor does one frame without bars


# ---------------------------------------------------------------- resolve

class Run:
    def __init__(self, rc=0, out=b'', err=b'', exc=None): self.rc, self.out, self.err, self.exc, self.cmd = rc, out, err, exc, None
    def __call__(self, cmd, **kw):
        self.cmd = cmd
        if self.exc: raise self.exc
        return subprocess.CompletedProcess(cmd, self.rc, self.out, self.err)


INFO = {'title': 'OWCS', 'is_live': True, 'http_headers': {'User-Agent': 'UA'}, 'formats': [
    {'format_id': 'audio', 'url': 'a', 'vcodec': 'none'},
    {'format_id': 'sd', 'url': 'u540', 'height': 540, 'width': 960, 'tbr': 1000},
    {'format_id': 'hd', 'url': 'u720', 'height': 720, 'width': 1280, 'tbr': 2500},
    {'format_id': 'src', 'url': 'u1440', 'height': 1440, 'width': 2560, 'tbr': 9000}]}


def test_resolve_picks_best_under_max_height():
    run = Run(out=json.dumps(INFO).encode())
    url, headers, info = F.resolve_hls('owesports', 1080, run=run)
    assert url == 'u720' and info['height'] == 720 and info['format_id'] == 'hd'
    assert headers == {'User-Agent': 'UA', 'Referer': F.REFERER}
    assert run.cmd[-1] == 'https://play.sooplive.com/owesports' and len(info['formats']) == 3


def test_resolve_falls_back_to_smallest_when_all_too_big():
    url, _, _ = F.resolve_hls('x', 360, run=Run(out=json.dumps(INFO).encode()))
    assert url == 'u540'


def test_pick_format_without_heights_takes_yt_dlps_best():
    # media playlists without RESOLUTION: no height / tbr at all; yt-dlp lists worst -> best
    info = {'formats': [{'format_id': 'hls-0', 'url': 'low'}, {'format_id': 'hls-1', 'url': 'high'},
                        {'format_id': 'aud', 'url': 'a', 'vcodec': None, 'resolution': 'audio only', 'video_ext': 'none'}]}
    assert F.pick_format(info)['url'] == 'high'


def test_channel_page_canonicalizes_the_embed_url():
    assert F.channel_page('https://play.sooplive.com/owesports/embed?autoPlay=true&mutePlay=true') == 'https://play.sooplive.com/owesports'
    assert F.channel_page('owesports') == F.channel_page('https://play.sooplive.com/owesports') == 'https://play.sooplive.com/owesports'
    assert F.channel_page('https://example.com/v.m3u8') == 'https://example.com/v.m3u8'


@pytest.mark.parametrize('run,msg', [
    (Run(rc=1, err=b'ERROR: [soop] owesports: The channel is not currently live'), 'not currently live'),
    (Run(out=b'not json'), 'no JSON'),
    (Run(out=json.dumps({'formats': []}).encode()), 'no video formats'),
    (Run(exc=FileNotFoundError('yt-dlp')), 'not found'),
    (Run(exc=subprocess.TimeoutExpired('yt-dlp', 60)), 'timed out'),
])
def test_resolve_errors(run, msg):
    with pytest.raises(F.ResolveError, match=msg): F.resolve_hls('owesports', run=run)


def test_ffmpeg_cmd_headers_and_fixed_size():
    cmd = F.ffmpeg_cmd('https://h/master.m3u8', {'Referer': F.REFERER, 'Bad': 'x\r\nInjected: 1'}, 5, (1920, 1080), ffmpeg='ff')
    hdr = cmd[cmd.index('-headers') + 1]
    assert hdr == f'Referer: {F.REFERER}\r\n' and cmd.index('-headers') < cmd.index('-i')
    vf = cmd[cmd.index('-vf') + 1]
    assert vf.startswith('fps=1/5,scale=1920:1080:') and 'pad=1920:1080' in vf and cmd[-5:] == ['-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    assert '-headers' not in F.ffmpeg_cmd('/tmp/file.mp4', {'Referer': 'r'})


def test_backoff_delay():
    assert [F.backoff_delay(n) for n in range(1, 8)] == [2, 4, 8, 16, 32, 60, 60]


# ---------------------------------------------------------------- HlsFrames with fake processes

SIZE = (32, 18)
NBYTES = SIZE[0] * SIZE[1] * 3


class FakeStdout:
    def __init__(self, proc, frames, then):
        self.proc, self.frames, self.then = proc, list(frames), then
    def read(self, n):
        assert n == NBYTES
        if self.frames:
            time.sleep(0.01)
            return self.frames.pop(0)
        if self.then == 'exit':
            self.proc.returncode = 1
            return b''
        if self.then == 'exit_late':      # real order: stdout EOF first, the exit status a moment later
            threading.Timer(0.2, self.proc.exit, (3,)).start()
            return b''
        self.proc.killed.wait()          # stall: block until killed, like a pipe with no data
        return b''
    def close(self): pass


class FakeProc:
    def __init__(self, frames=(), then='exit', stderr=b''):
        self.returncode, self.killed = None, threading.Event()
        self.stdout, self.stderr = FakeStdout(self, frames, then), io.BytesIO(stderr)
        self.exited = threading.Event()
    def poll(self): return self.returncode
    def exit(self, rc):
        if self.returncode is None: self.returncode = rc
        self.exited.set()
    def kill(self): self.killed.set(); self.exit(-9)
    def wait(self, timeout=None):
        if self.returncode is None and not self.exited.wait(timeout): raise subprocess.TimeoutExpired('ffmpeg', timeout)
        return self.returncode


class Factory:
    def __init__(self, procs): self.procs, self.cmds, self.made = list(procs), [], []
    def __call__(self, cmd):
        self.cmds.append(cmd)
        p = self.procs.pop(0) if self.procs else FakeProc(then='stall')
        self.made.append(p)
        return p


def frame_bytes(v): return bytes([v]) * NBYTES


def make(factory, resolver=None, **kw):
    kw = {'interval': 0.05, 'size': SIZE, 'startup_grace': 0.1, 'backoff': (0.01, 0.05), 'healthy_after': 100, **kw}
    return F.HlsFrames(resolver=resolver or (lambda: ('https://h/m.m3u8', {'Referer': F.REFERER}, {'height': 720})), popen=factory, **kw)


def test_grab_latest_frame_then_none_when_old():
    fac = Factory([FakeProc([frame_bytes(1), frame_bytes(2)], then='stall')])
    with make(fac, stall_after=10) as src:
        assert wait_until(lambda: src.frames == 2)
        f = src.grab()
        assert f.shape == (18, 32, 3) and f[0, 0, 0] == 2 and f.flags.writeable
        assert src.grab(max_age=0.0) is None or wait_until(lambda: src.grab(max_age=0.0) is None)
        assert src.info == {'height': 720} and src.restarts == 0
    assert fac.made[0].killed.is_set()


def test_restart_after_exit_with_backoff():
    fac = Factory([FakeProc([frame_bytes(1)], then='exit', stderr=b'Connection reset\n'), FakeProc(then='exit'), FakeProc([frame_bytes(9)], then='stall')])
    with make(fac, stall_after=10) as src:
        assert wait_until(lambda: src.frames == 2 and src.grab() is not None and src.grab()[0, 0, 0] == 9)
        assert src.restarts == 2 and src.failures == 2 and 'exited' in src.last_error and len(fac.cmds) == 3


def test_restart_after_stall_and_reresolve():
    calls = []
    def resolver():
        calls.append(1)
        return f'https://h/{len(calls)}.m3u8', {}, {}
    fac = Factory([FakeProc([frame_bytes(1)], then='stall'), FakeProc([frame_bytes(2)], then='stall')])
    src = make(fac, resolver, stall_after=0.15).start()
    try:
        assert wait_until(lambda: src.restarts >= 1 and len(fac.cmds) >= 2)
        assert 'stall' in (src.last_error or '') and fac.made[0].killed.is_set()
        assert 'https://h/2.m3u8' in fac.cmds[1]          # a fresh URL for every restart (tokens expire)
    finally:
        src.close()


def test_restart_on_http_403():
    fac = Factory([FakeProc(then='stall', stderr=b'[https @ 0x1] HTTP error 403 Forbidden\n'), FakeProc([frame_bytes(3)], then='stall')])
    with make(fac, stall_after=10, startup_grace=10) as src:      # no stall timeout in play: the 403 alone restarts
        assert wait_until(lambda: src.grab() is not None)
        assert src.restarts == 1 and '403' in src.last_error


def test_forbidden_pattern_matches_ffmpeg_403_lines_only():
    assert F.FORBIDDEN.search(b'[http @ 0x1] HTTP error 403 Forbidden')
    assert F.FORBIDDEN.search(b'https://h/m.m3u8: Server returned 403 Forbidden (access denied)')
    assert not F.FORBIDDEN.search(b'[hls @ 0x1] Failed to open segment 403 of playlist 0')
    assert not F.FORBIDDEN.search(b'[http @ 0x1] HTTP error 404 Not Found')


def test_ffmpeg_cmd_logs_warnings():       # the 4xx lines the 403 check reads are warnings
    cmd = F.ffmpeg_cmd('https://h/m.m3u8')
    assert cmd[cmd.index('-loglevel') + 1] == 'warning' and '-nostats' in cmd


def test_resolve_failure_is_retried_and_grab_never_raises():
    n = []
    def resolver():
        n.append(1)
        if len(n) < 3: raise F.ResolveError('offline')
        return 'https://h/m.m3u8', {}, {}
    fac = Factory([FakeProc([frame_bytes(4)], then='stall')])
    with make(fac, resolver, stall_after=10) as src:
        assert src.grab() is None
        assert wait_until(lambda: src.grab() is not None)
        assert src.restarts == 2 and 'offline' in src.last_error


def test_spawn_failure_is_retried():
    procs = [FakeProc([frame_bytes(5)], then='stall')]
    def popen(cmd):
        if not hasattr(popen, 'n'): popen.n = 0
        popen.n += 1
        if popen.n == 1: raise FileNotFoundError('ffmpeg')
        return procs.pop(0) if procs else FakeProc(then='stall')
    with make(popen, stall_after=10) as src:
        assert wait_until(lambda: src.grab() is not None) and 'spawn' in src.last_error


def test_failures_reset_after_healthy_run():
    fac = Factory([FakeProc(then='exit'), FakeProc([frame_bytes(1)] * 30, then='stall')])
    with make(fac, stall_after=10, healthy_after=0.0) as src:
        assert wait_until(lambda: src.frames >= 5)
        assert src.restarts == 1 and src.failures == 0


def test_close_kills_ffmpeg_and_stops_restarting():
    fac = Factory([FakeProc([frame_bytes(1)], then='stall')])
    src = make(fac, stall_after=10).start()
    assert wait_until(lambda: src.frames == 1)
    src.close()
    assert fac.made[0].killed.is_set() and not src._thread.is_alive()
    n = len(fac.cmds); time.sleep(0.2)
    assert len(fac.cmds) == n


def test_context_manager_kills_on_exception():
    fac = Factory([FakeProc([frame_bytes(1)], then='stall')])
    with pytest.raises(KeyboardInterrupt):
        with make(fac, stall_after=10) as src:
            assert wait_until(lambda: src.frames == 1)
            raise KeyboardInterrupt
    assert fac.made[0].killed.is_set()


def test_exit_reports_the_real_exit_code():
    fac = Factory([FakeProc([frame_bytes(1)], then='exit_late')])
    with make(fac, stall_after=10, backoff=(5, 5)) as src:
        assert wait_until(lambda: src.restarts == 1)
        assert src.last_error == 'ffmpeg exited (3)'       # was 'ffmpeg exited (None)': EOF is seen before the exit


def test_kick_restarts_now_without_backoff_or_failure():
    fac = Factory([FakeProc([frame_bytes(1)], then='stall'), FakeProc([frame_bytes(2)], then='stall')])
    with make(fac, stall_after=10, backoff=(30, 30)) as src:
        assert wait_until(lambda: src.frames == 1)
        src.kick('frozen frame')
        assert wait_until(lambda: src.frames == 2), src.last_error
        assert fac.made[0].killed.is_set() and src.failures == 0 and src.last_error == 'kicked: frozen frame'


def test_kick_cuts_a_backoff_wait_short():
    calls = []
    def resolver():
        calls.append(time.time())
        if len(calls) == 1: raise F.ResolveError('offline')
        return 'https://h/m.m3u8', {}, {}
    fac = Factory([FakeProc([frame_bytes(7)], then='stall')])
    with make(fac, resolver, stall_after=10, backoff=(60, 60)) as src:
        assert wait_until(lambda: src.restarts == 1)
        src.kick()
        assert wait_until(lambda: src.grab() is not None, timeout=3) and len(fac.cmds) == 1


def test_supervisor_survives_its_own_errors():
    class Broken(FakeProc):
        def poll(self): raise OSError('poll broke')
    fac = Factory([Broken(), FakeProc([frame_bytes(8)], then='stall')])
    with make(fac, stall_after=10) as src:
        assert wait_until(lambda: src.grab() is not None), src.last_error
        assert src.alive() and 'supervisor error' in src.last_error


def test_close_during_spawn_kills_the_new_process():
    made = []
    def popen(cmd):
        src._stop.wait(5)                  # close() runs while ffmpeg is being spawned
        made.append(FakeProc(then='stall')); return made[-1]
    src = make(popen, stall_after=10).start()
    time.sleep(0.05)
    src.close()
    assert wait_until(lambda: made and made[0].killed.is_set()) and src._holder[0] is None


def test_next_frame_waits_for_a_newer_frame():
    frames = [frame_bytes(1)] + [frame_bytes(2)]
    class Slow(FakeStdout):
        def read(self, n):
            if len(self.frames) == 1: time.sleep(0.3)
            return super().read(n)
    p = FakeProc(then='stall'); p.stdout = Slow(p, frames, 'stall')
    with make(Factory([p]), stall_after=10, interval=1) as src:
        assert wait_until(lambda: src.frames == 1)
        n, f = src.next_frame(1, timeout=2)
        assert n == 2 and f[0, 0, 0] == 2
        n, f = src.next_frame(2, timeout=0.05)    # nothing newer: the latest one, still fresh
        assert n == 2


# ---------------------------------------------------------------- HlsSource (live_capture interface)

SOURCE_API = ('ready', 'start', 'grab', 'reconnect', 'restart', 'refresh', 'alive', 'close')


def test_hls_source_has_the_obs_source_interface():
    import live_capture
    for name in SOURCE_API:
        assert callable(getattr(live_capture.ObsSource, name)) and callable(getattr(F.HlsSource, name))


def test_hls_source_grab_normalizes_and_raises_without_a_fresh_frame():
    fac = Factory([FakeProc([frame_bytes(200)], then='stall')])
    src = F.HlsSource(frames=make(fac, stall_after=10, interval=0.1))
    assert src.ready()
    with pytest.raises(RuntimeError, match='none yet'): src.grab()          # not started: raises, never returns None
    src.start()
    try:
        assert wait_until(lambda: src.src.frames == 1) and src.alive()
        img = src.grab()
        assert img.shape == (1080, 1920, 3) and img[0, 0, 0] == 200 and src.last_info['src'] == SIZE
        time.sleep(1.3)                                                         # older than 2 x interval + 1 s
        with pytest.raises(RuntimeError, match='s old'): src.grab()
    finally:
        src.close()
    assert not src.alive()


def test_hls_source_restart_and_refresh_kick_the_stream():
    fac = Factory([FakeProc([frame_bytes(10)], then='stall'), FakeProc([frame_bytes(20)], then='stall'),
                   FakeProc([frame_bytes(30)], then='stall')])
    src = F.HlsSource(frames=make(fac, stall_after=10, backoff=(30, 30)))
    src.start()
    try:
        assert wait_until(lambda: src.src.frames == 1)
        src.reconnect(); assert len(fac.cmds) == 1                              # no-op: the supervisor heals itself
        src.refresh()
        assert wait_until(lambda: src.src.frames == 2) and 'frozen' in src.src.last_error
        src.restart()
        assert wait_until(lambda: src.src.frames == 3) and src.grab()[0, 0, 0] == 30 and src.src.failures == 0
    finally:
        src.close()


def test_hls_source_inside_live_capture_grabber():
    import live_capture
    fac = Factory([FakeProc(then='exit'), FakeProc([frame_bytes(90)], then='stall')])
    src = F.HlsSource(frames=make(fac, stall_after=10, backoff=(0.2, 0.2), interval=0.1))
    logs, alerts = [], []
    g = live_capture.Grabber(src, lambda *a: logs.append(a), lambda *a: alerts.append(a), sleep=lambda s: None)
    src.start()
    try:
        ok, _ = g.grab()
        assert not ok and 'screenshot failed' in logs[0][0]                    # an exception, so the Grabber counts it
        assert wait_until(lambda: g.grab()[0], timeout=5)
        ok, img = g.grab()
        assert ok and img.shape == (1080, 1920, 3)
    finally:
        src.close()


# ---------------------------------------------------------------- real ffmpeg (optional)

FFMPEG = os.environ.get('FFMPEG_CMD') or shutil.which('ffmpeg')


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg not installed (set FFMPEG_CMD to run)')
def test_real_ffmpeg_local_file(tmp_path, monkeypatch):
    src_file = str(tmp_path / 'test.mp4')
    r = subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=640x360:rate=10:duration=4',
                        '-pix_fmt', 'yuv420p', src_file], capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr
    monkeypatch.setenv('FFMPEG_CMD', FFMPEG)
    with F.HlsFrames(interval=0.5, resolver=lambda: (src_file, {}, {}), stall_after=30, startup_grace=30) as src:
        assert wait_until(lambda: src.frames >= 2, timeout=60), src.last_error
        f = src.grab(max_age=60)
        assert f.shape == (1080, 1920, 3) and f.mean() > 30
        img, info = F.normalize(f)
        assert img.shape == (1080, 1920, 3) and info['crop'] == (0, 0, 1920, 1080)


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg not installed (set FFMPEG_CMD to run)')
def test_real_ffmpeg_pads_4x3_then_normalize_warns(tmp_path, monkeypatch):
    src_file = str(tmp_path / 'sq.mp4')
    r = subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=480x360:rate=10:duration=3',
                        '-pix_fmt', 'yuv420p', src_file], capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr
    monkeypatch.setenv('FFMPEG_CMD', FFMPEG)
    with F.HlsFrames(interval=0.5, resolver=lambda: (src_file, {}, {}), stall_after=30, startup_grace=30) as src:
        assert wait_until(lambda: src.frames >= 1, timeout=60), src.last_error
        f = src.grab(max_age=60)
        assert f[:, :200].max() < 20 and f[:, -200:].max() < 20       # 4:3 padded, not stretched


class LiveHls:
    """local 'live' HLS server over pre-made 1 s segments: sliding playlist, Referer required like SOOP.
    mode: ok | forbid (segments 403, as when the token expired)"""
    def __init__(self, seg_dir):
        import http.server
        self.dir, self.mode, self.t0, self.requests = seg_dir, 'ok', time.time(), []
        self.n = len([f for f in os.listdir(seg_dir) if f.endswith('.ts')])
        live = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                live.requests.append((self.path, self.headers.get('Referer')))
                if self.headers.get('Referer') != F.REFERER: return self.send(403, b'')
                if self.path.startswith('/live.m3u8'): return self.send(200, live.playlist())
                if self.path.endswith('.ts') and live.mode == 'ok':
                    with open(os.path.join(live.dir, self.path.lstrip('/')), 'rb') as f: return self.send(200, f.read())
                self.send(403 if live.mode == 'forbid' else 404, b'')
            def send(self, code, body):
                self.send_response(code); self.send_header('Content-Length', str(len(body))); self.end_headers()
                self.wfile.write(body)

        self.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.srv.server_address[1]}/live.m3u8'
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def playlist(self):
        k = min(int(time.time() - self.t0) + 3, self.n - 1)
        return (f'#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:{k - 3}\n' +
                ''.join(f'#EXTINF:1.0,\ns{i:03d}.ts\n' for i in range(k - 3, k + 1))).encode()

    def close(self): self.srv.shutdown(); self.srv.server_close()


@pytest.fixture
def live_hls(tmp_path):
    r = subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=640x360:rate=10:duration=40',
                        '-c:v', 'libx264', '-g', '10', '-pix_fmt', 'yuv420p', '-f', 'hls', '-hls_time', '1', '-hls_list_size', '0',
                        '-hls_segment_filename', str(tmp_path / 's%03d.ts'), str(tmp_path / 'vod.m3u8')], capture_output=True, timeout=120, check=False)
    assert r.returncode == 0, r.stderr
    srv = LiveHls(str(tmp_path))
    yield srv
    srv.close()


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg not installed (set FFMPEG_CMD to run)')
def test_real_ffmpeg_live_hls_headers_reach_segments_and_403_restarts(live_hls, monkeypatch):
    monkeypatch.setenv('FFMPEG_CMD', FFMPEG)
    resolver = lambda: (live_hls.url, {'Referer': F.REFERER, 'User-Agent': 'UA'}, {})
    with F.HlsFrames(interval=0.5, size=(320, 180), resolver=resolver, stall_after=20, startup_grace=20, backoff=(0.2, 0.5)) as src:
        assert wait_until(lambda: src.frames >= 2, timeout=30), src.last_error
        assert any(p.endswith('.ts') for p, _ in live_hls.requests)          # the server 403s segments without Referer
        assert src.grab().shape == (180, 320, 3) and src.restarts == 0
        live_hls.mode = 'forbid'
        assert wait_until(lambda: src.restarts >= 1, timeout=30)
        assert '403' in src.last_error, src.last_error                        # read from real ffmpeg stderr
        live_hls.mode = 'ok'
        n = src.frames
        assert wait_until(lambda: src.frames > n, timeout=30), src.last_error


def test_ffmpeg_cmd_keyframes_only_is_an_input_option():
    cmd = F.ffmpeg_cmd('https://h/m.m3u8', keyframes_only=True)
    assert cmd[cmd.index('-skip_frame') + 1] == 'nokey' and cmd.index('-skip_frame') < cmd.index('-i')
    assert '-skip_frame' not in F.ffmpeg_cmd('https://h/m.m3u8')


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg not installed (set FFMPEG_CMD to run)')
def test_real_ffmpeg_hls_source_keyframes_only(live_hls, monkeypatch):
    monkeypatch.setenv('FFMPEG_CMD', FFMPEG)
    frames = F.HlsFrames(interval=1, resolver=lambda: (live_hls.url, {'Referer': F.REFERER}, {}), keyframes_only=True)
    src = F.HlsSource(frames=frames)
    src.start()
    try:
        assert wait_until(lambda: frames.frames >= 2, timeout=30), frames.last_error
        img = src.grab()
        assert img.shape == (1080, 1920, 3) and img.mean() > 30 and src.last_info['crop'] == (0, 0, 1920, 1080)
    finally:
        src.close()
