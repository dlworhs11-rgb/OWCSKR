"""Match-day check that the SOOP picture in OBS is still above 540p (the OBS browser source loses the SOOP login, and
with it 720p, when its login cookie runs out: AuthTicket, valid to 2026-11-17 as of 10-20).
Six OBS frames over about a minute. A 540p picture loses almost nothing when shrunk to 960x540, so its 540/720 loss
ratio is low: 10-17 VOD frames gave 1.66-1.86 at 720p and 0.69-0.92 for the same frames cut to 540p, on game and
waiting screens alike. Below 1.2 a window asks the user to log in again (OBS: SOOP source > Interact).
usage: python soop_quality.py      (scheduled tasks OWCSKR\\SoopQuality_<date>, 2 minutes after the first match)"""
import asyncio, datetime, os, subprocess, sys
import cv2, numpy as np
sys.path.insert(0, r'C:\Users\dlwor\Documents\Obsidian\LeeJaeGon\02_Projects\OWCS KR Home')
import score_watch as W

LOG = r'C:\Users\dlwor\OWCSKR\data\live\soop_quality.log'
LOW = 1.2


def loss(img, w, h):
    s = cv2.resize(cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA), (1920, 1080), interpolation=cv2.INTER_CUBIC)
    return float(np.abs(img.astype(np.float32) - s).mean())


async def ratios():
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
    ps = ('Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('
          f"'{text}', 'OWCS 기록기 화질', 'OK', 'Warning') | Out-Null")
    subprocess.Popen(['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', ps])


def main():
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
        popup('OBS 화면을 못 읽었어요. OBS가 켜져 있는지 확인해 주세요.')
    elif r < LOW:
        popup('SOOP 화질이 540p로 떨어졌어요 (로그아웃 의심).\n'
              'OBS → SOOP 소스 우클릭 → 상호작용 → SOOP 로그인 → 720p 선택.')


if __name__ == '__main__':
    main()
