"""Re-assemble and re-upload the last two capture days (fills in map names / scores that Liquipedia added later).
Run by the daily job after collector/build.mjs. Exit 1 when any step failed (the daily job reports it).
OWCSKR_PUBLISH=0 (shadow run): re-assembles only, publish_day.py is skipped ('publish off (OWCSKR_PUBLISH=0)')."""
import datetime, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_util as PU  # noqa: E402  (reads .env: the Windows daily job has no other loader)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_step(script: str, day: str, run=subprocess.run) -> bool:
    r = run([sys.executable, '-I', script, day], capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=ROOT)
    sys.stdout.write(r.stdout or ''); sys.stderr.write(r.stderr or '')
    if r.returncode == 0: return True
    print(f'republish: {os.path.basename(script)} {day} FAILED (exit {r.returncode}): {(r.stderr or "").strip()[-500:]}', file=sys.stderr)
    return False


def main(today: datetime.date | None = None, run=subprocess.run, env=None) -> int:
    today = today or datetime.date.today()
    publish = PU.publish_on(env)
    failed = []
    for back in (1, 0):
        day = (today - datetime.timedelta(back)).isoformat()
        if not os.path.exists(os.path.join(ROOT, 'data', 'live', day, 'ocr.json')): continue
        for script in ('tools/assemble_day.py', 'tools/publish_day.py'):
            if script == 'tools/publish_day.py' and not publish:
                print(f'republish: {day} {PU.PUBLISH_OFF}'); break
            if not run_step(script, day, run):
                failed.append(f'{os.path.basename(script)} {day}'); break   # never publish a stale assembly
    if failed: print('republish FAILED:', ', '.join(failed), file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace'); sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # names like 'Esperança'
    sys.exit(main())
