"""Re-assemble and re-upload the last two capture days (fills in map names / scores that Liquipedia added later).
Run by the daily job after collector/build.mjs."""
import datetime, os, subprocess, sys
import sys as _sys; _sys.stdout.reconfigure(encoding='utf-8', errors='replace'); _sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # logs may contain names like 'Esperança'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
for back in (1, 0):
    day = (datetime.date.today() - datetime.timedelta(back)).isoformat()
    if os.path.exists(os.path.join('data', 'live', day, 'ocr.json')):
        for script in ('tools/assemble_day.py', 'tools/publish_day.py'):
            subprocess.run([sys.executable, '-I', script, day])
