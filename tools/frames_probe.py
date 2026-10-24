"""Check the HLS frame source on a live broadcast: which formats SOOP serves without login, and a few real frames.

usage: python -I tools/frames_probe.py [--channel owesports] [--count 3] [--interval 5] [--max-height 1080]
                                        [--keyframes-only] [--out DIR]

Prints every video format yt-dlp sees (answers "what resolution do we get without login"), the one chosen, then grabs
--count frames through HlsFrames and saves raw + normalized PNGs (default data/live/probe/<time>). Exit 1 if the
channel cannot be resolved or no frame arrived within a minute. --keyframes-only decodes keyframes only (much less
CPU); the printed frame times then show the stream's keyframe spacing.
"""
from __future__ import annotations

import argparse, os, sys, time

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frames as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def show_formats(info: dict) -> None:
    print(f"page   {info.get('page')}  live={info.get('is_live')}  title={info.get('title')!r}")
    for f in info.get('formats', []):
        print(f"  {str(f['format_id']):<14} {f.get('width') or '?':>5}x{f.get('height') or '?':<5} {f.get('tbr') or '':>8} {f.get('vcodec') or ''} {f.get('protocol') or ''}")
    print(f"chosen {info.get('format_id')} {info.get('width')}x{info.get('height')}")


def grab_frames(resolved: tuple, a: argparse.Namespace, out: str) -> int:
    first = [resolved]     # reuse the probe's URL for the first start, re-resolve on restarts
    resolver = lambda: first.pop() if first else F.resolve_hls(a.channel, a.max_height)
    saved, seen, deadline = 0, None, time.time() + 60 + a.count * a.interval
    with F.HlsFrames(interval=a.interval, resolver=resolver, log=print, keyframes_only=a.keyframes_only) as src:
        while saved < a.count and time.time() < deadline:
            time.sleep(0.5)
            got = src.latest()
            if not got or got[0] == seen: continue
            seen, frame = got
            img, info = F.normalize(frame)
            saved += 1
            cv2.imwrite(os.path.join(out, f'raw_{saved}.png'), frame)
            cv2.imwrite(os.path.join(out, f'norm_{saved}.png'), img)
            print(f'frame {saved} at {time.strftime("%H:%M:%S", time.localtime(seen))}: crop={info["crop"]} '
                  f'aspect={info["aspect"]} warn={info["warn"]}')
        print(f'restarts={src.restarts} last_error={src.last_error}')
    return saved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--channel', default='owesports')
    ap.add_argument('--count', type=int, default=3)
    ap.add_argument('--interval', type=float, default=5)
    ap.add_argument('--max-height', type=int, default=1080)
    ap.add_argument('--keyframes-only', action='store_true')
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'live', 'probe', time.strftime('%Y%m%d_%H%M%S')))
    a = ap.parse_args()
    try:
        resolved = F.resolve_hls(a.channel, a.max_height)
    except F.ResolveError as e:
        print('resolve failed:', e); return 1
    show_formats(resolved[2])
    if a.count <= 0: return 0
    os.makedirs(a.out, exist_ok=True)
    saved = grab_frames(resolved, a, a.out)
    print(f'{saved} frame(s) saved to {a.out}')
    return 0 if saved else 1


if __name__ == '__main__':
    sys.exit(main())
