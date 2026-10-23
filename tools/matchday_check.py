"""Match-day pre-flight, 5 minutes before the first match: are the recorders, OBS and the SOOP picture up?
Pops one window listing what is wrong (nothing when all is well) and appends a line to data/live/matchday_check.log.
usage: python matchday_check.py      (scheduled tasks OWCSKR\\MatchdayCheck_<date>)"""
import asyncio, datetime, os, subprocess, sys
sys.path.insert(0, r'C:\Users\dlwor\Documents\Obsidian\LeeJaeGon\02_Projects\OWCS KR Home')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from soop_quality import popup

LOG = r'C:\Users\dlwor\OWCSKR\data\live\matchday_check.log'
NEED = ('score_watch.py', 'pick_watch.py', 'caster_watch.py', 'live_relay.py', 'build_owcs_data.py', 'live_capture.py')


def problems():
    out = []
    ps = subprocess.run(['powershell', '-NoProfile', '-Command',
                         "(Get-CimInstance Win32_Process -Filter \"name like 'python%'\").CommandLine"],
                        capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    missing = [n for n in NEED if n not in ps]
    if missing:
        out.append('안 켜진 기록기: ' + ', '.join(m.replace('.py', '') for m in missing))
    if 'obs64.exe' not in subprocess.run(['tasklist', '/FI', 'IMAGENAME eq obs64.exe'], capture_output=True, text=True).stdout:
        out.append('OBS가 안 켜져 있음')
        return out
    try:
        import score_watch as W

        async def grab():
            src = await W.ObsSource().open()
            try:
                return await src.full()
            finally:
                await src.close()
        img = asyncio.run(grab())
        if img is None or float(img.mean()) < 8:
            out.append('OBS SOOP 화면이 검은색 (방송 전이거나 SOOP 소스 문제)')
    except Exception as e:
        out.append(f'OBS 화면을 못 읽음: {type(e).__name__}')
    return out


def main():
    p = problems()
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {'OK' if not p else ' | '.join(p)}\n")
    if p:
        popup('경기 5분 전 점검에서 문제가 있어요:\n- ' + '\n- '.join(p) +
              '\n\n바탕화면 "OWCS 사이트 관리자 모드.bat" 또는 C:\\Users\\dlwor\\OWCSKR\\tools\\start_watchers.bat 실행')


if __name__ == '__main__':
    main()
