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
- normalize(): crops uniform black letter/pillar-box bars at the edges and resizes to 1920x1080 (INTER_CUBIC)

Binaries: FFMPEG_CMD / YTDLP_CMD env override, else ffmpeg / yt-dlp on PATH.
"""
from __future__ import annotations

import collections, json, os, re, subprocess, threading, time, weakref
from collections.abc import Callable

import cv2, numpy as np

W, H = 1920, 1080
CHANNEL_URL = 'https://play.sooplive.com/{}'     # the yt-dlp SOOP live extractor does not match the /embed player URL
REFERER = 'https://play.sooplive.com/'           # SOOP's HLS server refuses playlist/segment requests without it


class ResolveError(RuntimeError):
    """yt-dlp could not produce a playable HLS URL (offline channel, extractor broken, binary missing...)."""


def ffmpeg_bin() -> str: return os.environ.get('FFMPEG_CMD') or 'ffmpeg'
def ytdlp_bin() -> str: return os.environ.get('YTDLP_CMD') or 'yt-dlp'


def _tail(text: str | bytes, n: int = 600) -> str:
    if isinstance(text, bytes): text = text.decode('utf-8', 'replace')
    return (text or '').strip()[-n:]


# ---------------------------------------------------------------- resolve

def _video_formats(info: dict) -> list[dict]:
    fmts = info.get('formats') or ([info] if info.get('url') else [])
    return [f for f in fmts if f.get('url') and f.get('vcodec') != 'none']


def pick_format(info: dict, max_height: int = 1080) -> dict:
    """best video format with height <= max_height (unknown height counts as fitting); else the smallest one"""
    fmts = _video_formats(info)
    if not fmts: raise ResolveError('yt-dlp returned no video formats')
    key = lambda f: (f.get('height') or 0, f.get('tbr') or 0)
    fit = [f for f in fmts if (f.get('height') or 0) <= max_height]
    return max(fit, key=key) if fit else min(fmts, key=key)


def format_summary(info: dict) -> list[dict]:
    return [{k: f.get(k) for k in ('format_id', 'width', 'height', 'tbr', 'vcodec', 'protocol')} for f in _video_formats(info)]


def resolve_hls(channel: str = 'owesports', max_height: int = 1080, timeout: float = 60,
                run: Callable = subprocess.run) -> tuple[str, dict, dict]:
    """(hls_url, http_headers, info) for a SOOP live channel (or any page URL yt-dlp understands).
    info: format_id/width/height of the chosen format, is_live, title and a summary of all formats."""
    page = channel if channel.startswith('http') else CHANNEL_URL.format(channel)
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
               ffmpeg: str | None = None) -> list[str]:
    """Raw-video pipeline. The output size must be fixed, otherwise a mid-stream resolution change (ad break, ABR
    switch, discontinuity) would desync the byte framing of stdout. Scaling keeps the aspect ratio and pads black
    instead of stretching: normalize() then sees any non-16:9 content as bars and crops them, which it could not undo
    after a stretch. Normal case (16:9 source) = one bicubic scale here, normalize() is a no-op."""
    w, h = size
    cmd = [ffmpeg or ffmpeg_bin(), '-hide_banner', '-loglevel', 'error', '-nostdin']
    if url.startswith(('http://', 'https://')):
        cmd += ['-rw_timeout', '15000000']       # a dead HTTP read errors out after 15 s instead of hanging forever
        safe = {k: v for k, v in (headers or {}).items() if not re.search(r'[\r\n]', f'{k}{v}')}
        if safe: cmd += ['-headers', ''.join(f'{k}: {v}\r\n' for k, v in safe.items())]   # hls demuxer reuses them for segments
    vf = (f'fps=1/{interval:g},scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=bicubic,'
          f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black')
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


def _kill_holder(holder: list) -> None:     # finalizer target: must not reference the HlsFrames object itself
    _kill(holder[0]); holder[0] = None


def backoff_delay(failures: int, base: float = 2.0, cap: float = 60.0) -> float:
    """2, 4, 8, ... seconds after the 1st, 2nd, 3rd consecutive failure, capped"""
    return min(cap, base * 2 ** max(0, failures - 1))


FORBIDDEN = re.compile(rb'\b403\b')


class HlsFrames:
    """Latest decoded frame of a live HLS stream, kept fresh by a self-healing ffmpeg process.

    restarts: recoveries attempted (ffmpeg exit, stall, 403, resolve/spawn failure); failures: consecutive ones
    (reset once a process has delivered frames for healthy_after seconds); last_error: why the last recovery happened.
    """

    def __init__(self, channel: str = 'owesports', interval: float = 5.0, size: tuple[int, int] = (W, H),
                 max_height: int = 1080, resolver: Callable | None = None, popen: Callable = _spawn,
                 stall_after: float | None = None, startup_grace: float = 20.0, backoff: tuple[float, float] = (2.0, 60.0),
                 healthy_after: float = 60.0, log: Callable[[str], None] | None = None, clock: Callable[[], float] = time.monotonic):
        self.interval, self.size = float(interval), (int(size[0]), int(size[1]))
        self._resolver = resolver or (lambda: resolve_hls(channel, max_height))
        self._popen, self._log, self._clock = popen, log or (lambda m: None), clock
        self.stall_after = stall_after if stall_after is not None else 3 * self.interval
        self.startup_grace, self.backoff, self.healthy_after = startup_grace, backoff, healthy_after
        self.restarts, self.failures, self.frames = 0, 0, 0
        self.last_error: str | None = None
        self.info: dict = {}
        self._latest: tuple[float, float, np.ndarray] | None = None     # (wall time, monotonic, frame)
        self._lock, self._stop = threading.Lock(), threading.Event()
        self._holder: list = [None]            # current ffmpeg process, shared with the finalizer
        self._thread: threading.Thread | None = None
        self._finalizer = weakref.finalize(self, _kill_holder, self._holder)   # also runs at interpreter exit

    # -------------------------------------------------- public
    def start(self) -> HlsFrames:
        if self._thread is None:
            self._thread = threading.Thread(target=self._supervise, name='hls-supervisor', daemon=True)
            self._thread.start()
        return self

    def grab(self, max_age: float | None = None) -> np.ndarray | None:
        """latest frame if it is at most max_age seconds old (default 2 x interval + 1), else None"""
        age = max_age if max_age is not None else 2 * self.interval + 1
        with self._lock:
            latest = self._latest
        if latest is None or self._clock() - latest[1] > age: return None
        return latest[2]

    def latest(self) -> tuple[float, np.ndarray] | None:
        """(wall-clock time the frame was decoded, frame) regardless of age"""
        with self._lock:
            return (self._latest[0], self._latest[2]) if self._latest else None

    def close(self) -> None:
        self._stop.set()
        _kill_holder(self._holder)
        if self._thread and self._thread is not threading.current_thread(): self._thread.join(timeout=10)
        _kill_holder(self._holder)             # a process spawned while we were joining
        self._finalizer.detach()

    def __enter__(self) -> HlsFrames: return self.start()
    def __exit__(self, *exc) -> None: self.close()

    # -------------------------------------------------- supervisor
    def _supervise(self) -> None:
        while not self._stop.is_set():
            try:
                url, headers, info = self._resolver()
                self.info = info or {}
            except Exception as e:     # offline channel, yt-dlp hiccup: same backoff as a dead ffmpeg
                self._recover(f'resolve failed: {e}')
                continue
            reason = self._run_once(url, headers)
            if self._stop.is_set(): break
            self._recover(reason)

    def _recover(self, reason: str) -> None:
        if self._stop.is_set(): return
        self.restarts += 1; self.failures += 1; self.last_error = reason
        delay = backoff_delay(self.failures, *self.backoff)
        self._log(f'hls: {reason} -> retry #{self.restarts} in {delay:.0f}s')
        self._stop.wait(delay)

    def _run_once(self, url: str, headers: dict) -> str:
        try:
            proc = self._popen(ffmpeg_cmd(url, headers, self.interval, self.size))
        except Exception as e:
            return f'ffmpeg spawn failed: {e}'
        self._holder[0] = proc
        if self._stop.is_set(): _kill_holder(self._holder); return 'closed'   # close() raced with the spawn
        st = {'started': self._clock(), 'last': None, 'eof': threading.Event(), 'forbidden': False,
              'err': collections.deque(maxlen=20)}
        readers = [threading.Thread(target=self._read_frames, args=(proc, st), daemon=True),
                   threading.Thread(target=self._read_err, args=(proc, st), daemon=True)]
        for t in readers: t.start()
        try:
            reason = self._watch(proc, st)
        finally:
            _kill_holder(self._holder)
            for t in readers: t.join(timeout=5)
        err = ' | '.join(st['err'])
        return f'{reason}: {err[-400:]}' if err else reason

    def _watch(self, proc, st: dict) -> str:
        while not self._stop.wait(min(0.5, self.interval / 4)):
            if st['forbidden']: return 'HTTP 403 (URL expired?)'
            if st['eof'].is_set() or proc.poll() is not None: return f'ffmpeg exited ({proc.poll()})'
            last = st['last']
            idle = self._clock() - (last if last is not None else st['started'] + self.startup_grace)
            if idle > self.stall_after: return f'stall: no frame for {self.stall_after:.0f}s'
        return 'closed'

    def _read_frames(self, proc, st: dict) -> None:
        w, h = self.size; n = w * h * 3
        try:
            while True:
                buf = proc.stdout.read(n)
                if not buf or len(buf) < n: break        # EOF (or killed mid-frame)
                frame = np.frombuffer(bytearray(buf), np.uint8).reshape(h, w, 3)   # writable copy: readers may draw on it
                now = self._clock()
                with self._lock:
                    self._latest = (time.time(), now, frame)
                st['last'] = now; self.frames += 1
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


def find_content(img: np.ndarray, black: float = 20, max_std: float = 4.0, min_bar: float = 0.01) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) inside black bars. black=20 also catches TV-range black (16) left unconverted.
    Bars thinner than min_bar of the side are ignored (encoder edge junk); bars leaving less than half are ignored."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    top, bottom = _bars(gray, 1, black, max_std)
    left, right = _bars(gray, 0, black, max_std)
    def axis(a: int, b: int, side: int) -> tuple[int, int]:
        if a < min_bar * side: a = 0
        if b < min_bar * side: b = 0
        return (0, side) if side - a - b < side / 2 else (a, side - b)
    y0, y1 = axis(top, bottom, h); x0, x1 = axis(left, right, w)
    return x0, y0, x1, y1


def _as_bgr(frame: np.ndarray) -> np.ndarray:
    if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0: raise ValueError('normalize: empty frame')
    if frame.ndim == 2: return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    if frame.ndim == 3 and frame.shape[2] == 4: return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    if frame.ndim == 3 and frame.shape[2] == 3: return frame
    raise ValueError(f'normalize: unsupported frame shape {frame.shape}')


def normalize(frame: np.ndarray, aspect_tol: float = 0.03) -> tuple[np.ndarray, dict]:
    """-> (1920x1080 BGR, info). info: src (w, h), crop (x0, y0, x1, y1) in source pixels, scale (sx, sy) source->1080,
    aspect of the kept area, warn (None or why the result may be distorted).
    A crop is only taken when it leaves ~16:9 (the broadcast itself is always 16:9): dark-but-uniform edges of a 16:9
    frame (fade, dark scene) are kept, so dark content is never cut."""
    img = _as_bgr(frame)
    if img.dtype != np.uint8: img = np.clip(img, 0, 255).astype(np.uint8)
    h, w = img.shape[:2]
    full, target, warn = (0, 0, w, h), W / H, None
    box = find_content(img)
    ok = lambda b: abs(((b[2] - b[0]) / (b[3] - b[1])) / target - 1) <= aspect_tol
    if box != full and not ok(box):
        if ok(full): box, warn = full, 'dark edges look like bars but cropping would break 16:9 - kept'
        else: warn = f'aspect {(box[2] - box[0]) / (box[3] - box[1]):.3f} after crop, not 16:9 - stretched'
    elif box == full and not ok(full):
        warn = f'aspect {w / h:.3f}, not 16:9 - stretched'
    x0, y0, x1, y1 = box
    cw, ch = x1 - x0, y1 - y0
    out = img[y0:y1, x0:x1]
    if (cw, ch) != (W, H): out = cv2.resize(out, (W, H), interpolation=cv2.INTER_CUBIC)   # same interpolation as the dictionaries
    info = {'src': (w, h), 'crop': box, 'scale': (W / cw, H / ch), 'aspect': round(cw / ch, 4), 'warn': warn}
    return np.ascontiguousarray(out), info
