"""Frame source for the server: SOOP live HLS -> ffmpeg -> BGR frames, without OBS (P1-17, OPS-05, OCR-07/11).

    with HlsFrames('owesports', interval=5) as src:
        while True:
            f = src.grab()                    # latest frame or None; never raises for stream trouble
            if f is not None: img, info = normalize(f)   # every reader gets exactly 1920x1080 BGR
            time.sleep(5)

- resolve_hls(): yt-dlp -J on https://play.sooplive.com/<channel>, picks the best format <= max_height
- HlsFrames: one ffmpeg process decoding 1 frame per interval to raw bgr24 on stdout; a reader thread keeps the latest
  frame; a supervisor re-resolves the URL (tokens expire) and restarts ffmpeg on exit / stall / HTTP 403 with
  exponential backoff (cap 60 s)
- normalize(): crops uniform, centred black letter/pillar-box bars and resizes to 1920x1080 (INTER_CUBIC);
  StableCrop: the same for a stream, following only a crop that lasts several frames
- HlsSource: live_capture's frame-source interface (as ObsSource) over HlsFrames + StableCrop; grab() raises

Binaries: FFMPEG_CMD / YTDLP_CMD env override, else ffmpeg / yt-dlp on PATH.
"""
from __future__ import annotations

import collections, json, os, re, subprocess, threading, time, weakref
from collections.abc import Callable

import cv2, numpy as np

W, H = 1920, 1080
CHANNEL_URL = 'https://play.sooplive.com/{}'     # canonical page; yt-dlp also takes the /embed URL but then sends it as Referer
REFERER = 'https://play.sooplive.com/'           # SOOP's HLS server refuses playlist/segment requests without it


class ResolveError(RuntimeError):
    """yt-dlp could not produce a playable HLS URL (offline channel, extractor broken, binary missing...)."""


def ffmpeg_bin() -> str: return os.environ.get('FFMPEG_CMD') or 'ffmpeg'
def ytdlp_bin() -> str: return os.environ.get('YTDLP_CMD') or 'yt-dlp'


def _tail(text: str | bytes, n: int = 600) -> str:
    if isinstance(text, bytes): text = text.decode('utf-8', 'replace')
    return (text or '').strip()[-n:]


# ---------------------------------------------------------------- resolve

def channel_page(url: str) -> str:
    """'owesports', the play page or its /embed?autoPlay=... player URL -> the canonical play page"""
    m = re.match(r'https?://play\.sooplive\.com/([^/?#]+)', url)
    if m: return CHANNEL_URL.format(m.group(1))
    return url if url.startswith('http') else CHANNEL_URL.format(url)


def _is_video(f: dict) -> bool:
    """audio-only HLS renditions: vcodec 'none', or (no CODECS in the playlist) only video_ext / resolution say so"""
    return bool(f.get('url')) and f.get('vcodec') != 'none' and f.get('video_ext') != 'none' \
        and f.get('resolution') != 'audio only'


def _video_formats(info: dict) -> list[dict]:
    fmts = info.get('formats') or ([info] if info.get('url') else [])
    return [f for f in fmts if _is_video(f)]


def pick_format(info: dict, max_height: int = 1080) -> dict:
    """best video format with height <= max_height (unknown height counts as fitting); else the smallest one.
    Ties (no height / tbr, e.g. a media playlist without RESOLUTION) go to the later one: yt-dlp lists worst -> best."""
    fmts = _video_formats(info)
    if not fmts: raise ResolveError('yt-dlp returned no video formats')
    key = lambda i: (fmts[i].get('height') or 0, fmts[i].get('tbr') or 0, i)
    fit = [i for i, f in enumerate(fmts) if (f.get('height') or 0) <= max_height]
    return fmts[max(fit, key=key) if fit else min(range(len(fmts)), key=key)]


def format_summary(info: dict) -> list[dict]:
    return [{k: f.get(k) for k in ('format_id', 'width', 'height', 'tbr', 'vcodec', 'protocol')} for f in _video_formats(info)]


def resolve_hls(channel: str = 'owesports', max_height: int = 1080, timeout: float = 60,
                run: Callable = subprocess.run) -> tuple[str, dict, dict]:
    """(hls_url, http_headers, info) for a SOOP live channel (or any page URL yt-dlp understands).
    info: format_id/width/height of the chosen format, is_live, title and a summary of all formats."""
    page = channel_page(channel)
    cmd = [ytdlp_bin(), '--no-warnings', '--no-playlist', '-J', page]
    try:
        r = run(cmd, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as e:
        raise ResolveError(f'{cmd[0]} not found (install yt-dlp or set YTDLP_CMD): {e}') from e
    except subprocess.TimeoutExpired as e:
        raise ResolveError(f'yt-dlp timed out after {timeout}s for {page}: {_tail(e.stderr or b"")}') from e
    if r.returncode != 0:
        raise ResolveError(f'yt-dlp exit {r.returncode} for {page}: {_tail(r.stderr)}')
    try:
        info = json.loads(r.stdout)
    except (ValueError, TypeError) as e:
        raise ResolveError(f'yt-dlp printed no JSON for {page}: {_tail(r.stdout)} | {_tail(r.stderr)}') from e
    f = pick_format(info, max_height)
    headers = dict(f.get('http_headers') or info.get('http_headers') or {})
    if not any(k.lower() == 'referer' for k in headers): headers['Referer'] = REFERER
    meta = {'page': page, 'format_id': f.get('format_id'), 'width': f.get('width'), 'height': f.get('height'),
            'tbr': f.get('tbr'), 'is_live': info.get('is_live'), 'title': info.get('title'), 'formats': format_summary(info)}
    return f['url'], headers, meta


# ---------------------------------------------------------------- ffmpeg

def ffmpeg_cmd(url: str, headers: dict | None = None, interval: float = 5, size: tuple[int, int] = (W, H),
               ffmpeg: str | None = None, keyframes_only: bool = False) -> list[str]:
    """Raw-video pipeline. The output size must be fixed, otherwise a mid-stream resolution change (ad break, ABR
    switch, discontinuity) would desync the byte framing of stdout. Scaling keeps the aspect ratio and pads black
    instead of stretching: normalize() then sees any non-16:9 content as bars and crops them, which it could not undo
    after a stretch. Normal case (16:9 source) = one bicubic scale here, normalize() is a no-op."""
    w, h = size
    # warning, not error: ffmpeg logs HTTP 4xx ("HTTP error 403 Forbidden", "Failed to open segment") at warning
    # level and then exits 0, so at 'error' the 403 check never fired and last_error carried no reason at all
    cmd = [ffmpeg or ffmpeg_bin(), '-hide_banner', '-loglevel', 'warning', '-nostats', '-nostdin']
    if url.startswith(('http://', 'https://')):
        cmd += ['-rw_timeout', '15000000']       # a dead HTTP read errors out after 15 s instead of hanging forever
        safe = {k: v for k, v in (headers or {}).items() if not re.search(r'[\r\n]', f'{k}{v}')}
        if safe: cmd += ['-headers', ''.join(f'{k}: {v}\r\n' for k, v in safe.items())]   # hls demuxer reuses them for segments
    vf = (f'fps=1/{interval:g},scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=bicubic,'
          f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black')
    if keyframes_only: cmd += ['-skip_frame', 'nokey']   # decode only keyframes: ~1/60 of the CPU, frames land on GOP boundaries
    return cmd + ['-i', url, '-an', '-sn', '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']


def _spawn(cmd: list[str]) -> subprocess.Popen:
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _kill(proc) -> None:
    if proc is None: return
    try:
        if proc.poll() is None: proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass
    for s in (getattr(proc, 'stdout', None), getattr(proc, 'stderr', None)):
        try:
            if s: s.close()
        except Exception:
            pass


def _kill_holder(holder: list, lock: threading.Lock) -> None:   # finalizer target: must not reference HlsFrames itself
    with lock:
        proc, holder[0] = holder[0], None
    _kill(proc)


def backoff_delay(failures: int, base: float = 2.0, cap: float = 60.0) -> float:
    """2, 4, 8, ... seconds after the 1st, 2nd, 3rd consecutive failure, capped"""
    return min(cap, base * 2 ** max(0, failures - 1))


FORBIDDEN = re.compile(rb'HTTP error 403|403 Forbidden')     # not a bare 403: 'Failed to open segment 403 of playlist 0'


class HlsFrames:
    """Latest decoded frame of a live HLS stream, kept fresh by a self-healing ffmpeg process.

    restarts: recoveries attempted (ffmpeg exit, stall, 403, resolve/spawn failure, kick()); failures: consecutive ones
    (reset once a process has delivered frames for healthy_after seconds); last_error: why the last recovery happened;
    frames: number of the latest frame (counts on across restarts).
    """

    def __init__(self, channel: str = 'owesports', interval: float = 5.0, size: tuple[int, int] = (W, H),
                 max_height: int = 1080, resolver: Callable | None = None, popen: Callable = _spawn,
                 stall_after: float | None = None, startup_grace: float = 20.0, backoff: tuple[float, float] = (2.0, 60.0),
                 healthy_after: float = 60.0, log: Callable[[str], None] | None = None, clock: Callable[[], float] = time.monotonic,
                 keyframes_only: bool = False):
        self.interval, self.size, self.keyframes_only = float(interval), (int(size[0]), int(size[1])), keyframes_only
        self._resolver = resolver or (lambda: resolve_hls(channel, max_height))
        self._popen, self._log, self._clock = popen, log or (lambda m: None), clock
        self.stall_after = stall_after if stall_after is not None else 3 * self.interval
        self.startup_grace, self.backoff, self.healthy_after = startup_grace, backoff, healthy_after
        self.restarts, self.failures, self.frames = 0, 0, 0
        self.last_error: str | None = None
        self.info: dict = {}
        self._latest: tuple[float, float, int, np.ndarray] | None = None     # (wall time, monotonic, number, frame)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._stop, self._wake = threading.Event(), threading.Event()       # wake: close() / kick() cut a wait short
        self._kick: str | None = None
        self._holder, self._plock = [None], threading.Lock()                # current ffmpeg process, shared with the finalizer
        self._thread: threading.Thread | None = None
        self._finalizer = weakref.finalize(self, _kill_holder, self._holder, self._plock)   # also runs at interpreter exit

    # -------------------------------------------------- public
    def start(self) -> HlsFrames:
        if not self._stop.is_set() and not self.alive():
            self._thread = threading.Thread(target=self._supervise, name='hls-supervisor', daemon=True)
            self._thread.start()
        return self

    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def grab(self, max_age: float | None = None) -> np.ndarray | None:
        """latest frame if it is at most max_age seconds old (default 2 x interval + 1), else None"""
        got = self.next_frame(self.frames, 0, max_age)
        return got[1] if got else None

    def next_frame(self, after: int, timeout: float, max_age: float | None = None) -> tuple[int, np.ndarray] | None:
        """(number, frame): the first frame numbered > after, waiting up to timeout s for it, else the latest one;
        None when that one is older than max_age (default 2 x interval + 1)"""
        age = max_age if max_age is not None else 2 * self.interval + 1
        with self._cond:
            self._cond.wait_for(lambda: (self._latest and self._latest[2] > after) or self._stop.is_set(), timeout)
            latest = self._latest
        if latest is None or self._clock() - latest[1] > age: return None
        return latest[2], latest[3]

    def latest(self) -> tuple[float, np.ndarray] | None:
        """(wall-clock time the frame was decoded, frame) regardless of age"""
        with self._lock:
            return (self._latest[0], self._latest[3]) if self._latest else None

    def kick(self, reason: str = 'restart requested') -> None:
        """drop the running ffmpeg and resolve the URL again now, skipping a pending backoff wait"""
        self._kick = reason
        self._wake.set()

    def close(self) -> None:
        self._stop.set(); self._wake.set()
        with self._cond: self._cond.notify_all()
        _kill_holder(self._holder, self._plock)
        if self._thread and self._thread is not threading.current_thread(): self._thread.join(timeout=10)
        _kill_holder(self._holder, self._plock)
        self._finalizer.detach()

    def __enter__(self) -> HlsFrames: return self.start()
    def __exit__(self, *exc) -> None: self.close()

    # -------------------------------------------------- supervisor
    def _supervise(self) -> None:
        while not self._stop.is_set():
            try:
                reason = self._cycle()
            except Exception as e:      # a bug here must not end the thread: alive() would stay False for good
                reason = f'supervisor error: {type(e).__name__}: {e}'
            if self._stop.is_set(): break
            self._recover(reason)

    def _cycle(self) -> str:
        try:
            url, headers, info = self._resolver()
        except Exception as e:          # offline channel, yt-dlp hiccup: same backoff as a dead ffmpeg
            return f'resolve failed: {e}'
        self.info = info or {}
        self._take_kick()               # a kick that came in while resolving is served by this fresh URL
        return self._run_once(url, headers)

    def _take_kick(self) -> str | None:
        if not self._stop.is_set(): self._wake.clear()
        reason, self._kick = self._kick, None
        return reason

    def _recover(self, reason: str) -> None:
        self.restarts += 1; self.last_error = reason
        if reason.startswith('kicked: ') or self._take_kick() is not None:     # asked for, not a failure: no backoff
            self._log(f'hls: {reason} -> retry #{self.restarts} now')
            return
        self.failures += 1
        delay = backoff_delay(self.failures, *self.backoff)
        self._log(f'hls: {reason} -> retry #{self.restarts} in {delay:.0f}s')
        self._wake.wait(delay)
        self._take_kick()               # a kick during the wait is served by this very retry

    def _run_once(self, url: str, headers: dict) -> str:
        try:
            proc = self._popen(ffmpeg_cmd(url, headers, self.interval, self.size, keyframes_only=self.keyframes_only))
        except Exception as e:
            return f'ffmpeg spawn failed: {e}'
        with self._plock:                # close() either finds this process in the holder or we see its stop flag
            closed = self._stop.is_set()
            if not closed: self._holder[0] = proc
        if closed: _kill(proc); return 'closed'
        st = {'started': self._clock(), 'last': None, 'eof': threading.Event(), 'forbidden': False,
              'err': collections.deque(maxlen=20)}
        readers = [threading.Thread(target=self._read_frames, args=(proc, st), daemon=True),
                   threading.Thread(target=self._read_err, args=(proc, st), daemon=True)]
        for t in readers: t.start()
        try:
            reason = self._watch(proc, st)
        finally:
            with self._plock:
                if self._holder[0] is proc: self._holder[0] = None
            _kill(proc)                  # our own reference: the holder may already have been emptied by close()
            for t in readers: t.join(timeout=5)
        err = ' | '.join(st['err'])
        return f'{reason}: {err[-400:]}' if err else reason

    def _watch(self, proc, st: dict) -> str:
        step = min(0.5, self.interval / 4)
        while True:
            self._wake.wait(step)
            if self._stop.is_set(): return 'closed'
            kick = self._take_kick()
            if kick: return f'kicked: {kick}'
            if st['forbidden']: return 'HTTP 403 (URL expired?)'
            if st['eof'].is_set() or proc.poll() is not None:
                try: proc.wait(timeout=2)        # stdout EOF comes just before the exit: report the real code, not None
                except Exception: pass
                return f'ffmpeg exited ({proc.poll()})'
            last = st['last']
            idle = self._clock() - (last if last is not None else st['started'] + self.startup_grace)
            if idle > self.stall_after: return f'stall: no frame for {self.stall_after:.0f}s'

    def _read_frames(self, proc, st: dict) -> None:
        w, h = self.size; n = w * h * 3
        try:
            while True:
                buf = proc.stdout.read(n)
                if not buf or len(buf) < n: break        # EOF (or killed mid-frame)
                frame = np.frombuffer(bytearray(buf), np.uint8).reshape(h, w, 3)   # writable copy: readers may draw on it
                now = self._clock()
                with self._cond:
                    self.frames += 1
                    self._latest = (time.time(), now, self.frames, frame)
                    self._cond.notify_all()
                st['last'] = now
                if now - st['started'] >= self.healthy_after: self.failures = 0
        except Exception:
            pass                                          # pipe closed by kill(): the watcher decides what happens next
        finally:
            st['eof'].set()

    def _read_err(self, proc, st: dict) -> None:
        try:
            for line in iter(proc.stderr.readline, b''):
                st['err'].append(line.decode('utf-8', 'replace').strip())
                if FORBIDDEN.search(line): st['forbidden'] = True
        except Exception:
            pass


# ---------------------------------------------------------------- normalize

def _edge_run(flags: np.ndarray) -> int:
    """length of the leading run of True"""
    return len(flags) if flags.all() else int(np.argmin(flags))


def _bars(gray: np.ndarray, axis: int, black: float, max_std: float) -> tuple[int, int]:
    """uniform dark lines at both ends along an axis (axis=1: rows, axis=0: columns)"""
    g = gray.astype(np.float32)
    dark = (g.mean(axis=axis) < black) & (g.std(axis=axis) < max_std)
    return _edge_run(dark), _edge_run(dark[::-1])


def find_content(img: np.ndarray, black: float = 20, max_std: float = 4.0, min_bar: float = 0.01,
                 sym_tol: float = 0.01) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) inside black bars. black=20 also catches TV-range black (16) left unconverted.
    Bars thinner than min_bar of the side are ignored (encoder edge junk); so are bars leaving less than half, and a
    pair whose two sides differ by more than sym_tol of the side (min 2 px): ffmpeg's pad and a source's own
    letter/pillarbox are centred, a dark area on one side only is content (a panel on a black background)."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    top, bottom = _bars(gray, 1, black, max_std)
    left, right = _bars(gray, 0, black, max_std)
    def axis(a: int, b: int, side: int) -> tuple[int, int]:
        if a < min_bar * side: a = 0
        if b < min_bar * side: b = 0
        if side - a - b < side / 2 or abs(a - b) > max(2, sym_tol * side): return 0, side
        return a, side - b
    y0, y1 = axis(top, bottom, h); x0, x1 = axis(left, right, w)
    return x0, y0, x1, y1


def _as_bgr(frame: np.ndarray) -> np.ndarray:
    if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0: raise ValueError('normalize: empty frame')
    if frame.dtype != np.uint8: frame = np.clip(frame, 0, 255).astype(np.uint8)
    if frame.ndim == 2: return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    if frame.ndim == 3 and frame.shape[2] == 4: return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    if frame.ndim == 3 and frame.shape[2] == 3: return frame
    raise ValueError(f'normalize: unsupported frame shape {frame.shape}')


def _aspect_ok(box: tuple[int, int, int, int], tol: float) -> bool:
    return abs(((box[2] - box[0]) / (box[3] - box[1])) / (W / H) - 1) <= tol


def choose_crop(img: np.ndarray, aspect_tol: float = 0.03) -> tuple[tuple[int, int, int, int], str | None]:
    """(crop box, warn) normalize() would use for this BGR frame"""
    h, w = img.shape[:2]
    full, box = (0, 0, w, h), find_content(img)
    if box != full and not _aspect_ok(box, aspect_tol):
        if _aspect_ok(full, aspect_tol): return full, 'dark edges look like bars but cropping would break 16:9 - kept'
        return box, f'aspect {(box[2] - box[0]) / (box[3] - box[1]):.3f} after crop, not 16:9 - stretched'
    if box == full and not _aspect_ok(full, aspect_tol): return full, f'aspect {w / h:.3f}, not 16:9 - stretched'
    return box, None


def normalize(frame: np.ndarray, aspect_tol: float = 0.03, box: tuple[int, int, int, int] | None = None
              ) -> tuple[np.ndarray, dict]:
    """-> (1920x1080 BGR, info). info: src (w, h), crop (x0, y0, x1, y1) in source pixels, scale (sx, sy) source->1080,
    aspect of the kept area, warn (None or why the result may be distorted). box: use this crop instead of detecting.
    A crop is only taken when it leaves ~16:9 (the broadcast itself is always 16:9) and its bars are centred: dark
    edges of a 16:9 frame (fade, dark scene) are kept, so dark content is not cut. A centred 16:9 picture on black
    still is: for a stream use StableCrop, which only follows a crop that lasts."""
    img = _as_bgr(frame)
    h, w = img.shape[:2]
    if box is None: box, warn = choose_crop(img, aspect_tol)
    else: box, warn = _clip_box(box, w, h), None
    x0, y0, x1, y1 = box
    cw, ch = x1 - x0, y1 - y0
    out = img[y0:y1, x0:x1]
    if (cw, ch) != (W, H): out = cv2.resize(out, (W, H), interpolation=cv2.INTER_CUBIC)   # same interpolation as the dictionaries
    info = {'src': (w, h), 'crop': box, 'scale': (W / cw, H / ch), 'aspect': round(cw / ch, 4), 'warn': warn}
    return np.ascontiguousarray(out), info


def _clip_box(box: tuple[int, int, int, int], w: int, h: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = (int(v) for v in box)
    x0, y0 = min(max(0, x0), w - 1), min(max(0, y0), h - 1)
    return x0, y0, min(max(x0 + 1, x1), w), min(max(y0 + 1, y1), h)


def _near(a: tuple | None, b: tuple | None, px: int) -> bool:
    return a is not None and b is not None and all(abs(p - q) <= px for p, q in zip(a, b))


class StableCrop:
    """normalize() for a stream. Real bars (ffmpeg's pad, a non-16:9 source) are the same on every frame; a fade to
    black or a 16:9 picture on a black screen lasts a few frames. A crop other than the current one is therefore taken
    only after choose_crop() found it (within jitter px) in `hold` consecutive frames. Starts uncropped."""

    def __init__(self, hold: int = 3, aspect_tol: float = 0.03, jitter: int = 4):
        self.hold, self.aspect_tol, self.jitter = hold, aspect_tol, jitter
        self.box: tuple[int, int, int, int] | None = None
        self._cand: tuple[int, int, int, int] | None = None
        self._n, self._size = 0, None

    def __call__(self, frame: np.ndarray) -> tuple[np.ndarray, dict]:
        img = _as_bgr(frame)
        h, w = img.shape[:2]
        if (w, h) != self._size: self.box, self._size, self._cand = (0, 0, w, h), (w, h), None   # first frame / new size
        found, warn = choose_crop(img, self.aspect_tol)
        self._n = self._n + 1 if _near(found, self._cand, self.jitter) else 1
        self._cand = found
        if not _near(found, self.box, self.jitter) and self._n >= self.hold: self.box = found
        out, info = normalize(img, box=self.box)
        held = not _near(found, self.box, self.jitter)
        info.update(found=found, warn=f'crop {found} seen {self._n}/{self.hold} times - kept {self.box}' if held else warn)
        return out, info


# ---------------------------------------------------------------- live_capture frame source

class HlsSource:
    """live_capture's frame-source interface (ready / start / grab / reconnect / restart / refresh / alive / close, as
    ObsSource) over HlsFrames + StableCrop. Not wired into live_capture yet (P1-17 4).
    grab() -> 1920x1080 BGR, a frame newer than the last one when it comes within `interval`; raises when there is no
    fresh frame, so live_capture's Grabber counts the failure, alerts after 3 min and calls restart() after 1 min.
    interval 2 s: the capture loop polls every 2 s during the POTM tail, every 5 s otherwise."""

    def __init__(self, url: str = 'owesports', log: Callable[..., None] = print, interval: float = 2.0,
                 max_height: int = 1080, keyframes_only: bool = False, hold: int = 3, frames: HlsFrames | None = None):
        self.src = frames or HlsFrames(channel_page(url), interval, max_height=max_height,
                                       keyframes_only=keyframes_only, log=lambda m: log(m))
        self.crop, self.last_info, self._seen = StableCrop(hold), {}, 0

    def ready(self) -> bool: return True            # nothing shared to refuse (ObsSource: an OBS with the user's scenes)
    def start(self) -> None: self.src.start()
    def alive(self) -> bool: return self.src.alive()
    def reconnect(self) -> None: pass               # the supervisor reconnects by itself, with backoff
    def refresh(self) -> None: self.src.kick('frozen or black frame')
    def close(self) -> None: self.src.close()

    def restart(self) -> None:
        self.src.kick('restart requested by the capture loop')
        self.src.start()                            # no-op unless the supervisor thread is gone

    def grab(self) -> np.ndarray:
        got = self.src.next_frame(self._seen, self.src.interval)
        if got is None:
            last = self.src.latest()
            age = f'{time.time() - last[0]:.0f} s old' if last else 'none yet'
            raise RuntimeError(f'no fresh HLS frame (latest {age}; restarts {self.src.restarts}): '
                               f'{self.src.last_error or "starting"}')
        self._seen, frame = got
        img, self.last_info = self.crop(frame)
        return img
