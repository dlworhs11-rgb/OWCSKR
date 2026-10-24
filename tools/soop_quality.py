"""Match-day check that the SOOP picture in OBS is still above 540p (the OBS browser source loses the SOOP login, and
with it 720p, when its login cookie runs out: AuthTicket, valid to 2026-11-17 as of 10-20).
Six OBS frames over about a minute. A 540p picture loses almost nothing when shrunk to 960x540, so its 540/720 loss
ratio is low: 10-17 VOD frames gave 1.66-1.86 at 720p and 0.69-0.92 for the same frames cut to 540p, on game and
waiting screens alike. Below 1.2 an alert (platform_util.notify) asks the user to log in again (OBS: SOOP source > Interact).
usage: python -I tools/soop_quality.py   (2 minutes after the first match, scheduled by schedule_today.py: task
       OWCSKR\\SoopQuality_<date> / systemd timer owcskr-soop-<date>)
Without OBS on this machine or without the site recorders (score_watch.py reads the OBS picture) it only logs."""
import asyncio, datetime, os, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_util as PU
if PU.SITE_DIR: sys.path.insert(0, PU.SITE_DIR)

LOG = os.path.join(PU.LIVE_DIR, 'soop_quality.log')
LOW = 1.2


def loss(img, w, h):
    s = cv2.resize(cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA), (1920, 1080), interpolation=cv2.INTER_CUBIC)
    return float(np.abs(img.astype(np.float32) - s).mean())


async def ratios():
    import score_watch as W          # site recorder (OWCSKR_SITE_DIR); a missing one is reported by main()
    src = await W.ObsSource().open()
    out = []
    try:
        for _ in range(6):
            img = await src.full()
            l720 = loss(img, 1280, 720)
            if l720 > 0.05:                      # a black or still frame says nothing
                out.append(loss(img, 960, 540) / l720)
            await asyncio.sleep(10)
    finally:
        await src.close()
    return out


def popup(text):
    PU.notify('OWCS 기록기 화질', text)


def skip_reason():
    """why this machine cannot run the check at all (then it logs, no alert): no OBS, or no site recorders"""
    if not PU.obs_installed():
        return 'OBS not installed'
    if not PU.SITE_DIR:
        return 'site recorders not on this machine (OWCSKR_SITE_DIR not set)'
    return ''


def main():
    os.makedirs(PU.LIVE_DIR, exist_ok=True)
    skip = skip_reason()
    if skip:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} skipped: {skip}\n")
        return 0
    try:
        rs = asyncio.run(ratios())
    except Exception as e:
        rs, err = [], repr(e)
    else:
        err = ''
    r = float(np.median(rs)) if rs else None
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} ratio {r if r is None else round(r, 2)} {[round(x, 2) for x in rs]} {err}\n")
    if r is None:
        popup('OBS 화면을 못 읽었어요. OBS가 켜져 있는지 확인해 주세요.' + (f'\n({err[:200]})' if err else ''))
    elif r < LOW:
        popup('SOOP 화질이 540p로 떨어졌어요 (로그아웃 의심).\n'
              'OBS → SOOP 소스 우클릭 → 상호작용 → SOOP 로그인 → 720p 선택.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
