"""Send an alert from a shell script: platform_util.notify (Discord webhook when OWCSKR_DISCORD_WEBHOOK is set, a
message box on a Windows desktop without one, always stderr).
usage: python -I tools/notify.py "TITLE" "BODY"      (BODY '-' = read it from stdin)
       python -I tools/notify.py --unit-failed UNIT  (Linux: the systemd user unit UNIT failed)
--unit-failed is run by owcskr-alert@<unit>.service (tools/register_tasks.sh), which the capture, recorder and daily
units name in OnFailure=: a unit that gave up (start limit hit, a crash with no restart, a timeout, killed) alerts
with its result, the last journal lines and the end of its log file. Skipped when the unit's own script already
alerted for that exit code (SELF_ALERTED), and at most once per unit every 30 minutes.
Always exits 0: a failed alert must never turn a job's result into something else."""
import datetime, fnmatch, json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DIR = os.path.join(ROOT, 'data', 'live')
UNIT_STATE = os.path.join(LIVE_DIR, 'unit_alerts.json')
UNIT_REALERT = datetime.timedelta(minutes=30)
JOURNAL_LINES = 30
LOG_LINES = 15
# exit codes after which the unit's script sent its own alert: run_daily.sh (1 = a step failed), run_live.sh
# (1 crashed, 2 self-check / bad arguments, 4 final OCR / publish failed)
SELF_ALERTED = {'owcskr-daily.service': {1}, 'owcskr-live-*.service': {1, 2, 4}}


def unit_name(unit: str) -> str:
    """the instance of owcskr-alert@<instance>.service is the failed unit's full name; a bare name is a service"""
    return unit if unit.endswith(('.service', '.timer')) else unit + '.service'


def _cmd(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return f'({cmd[0]} failed: {type(e).__name__}: {e})'
    return (r.stdout or '').strip() or (r.stderr or '').strip()


def unit_result(unit: str) -> dict[str, str]:
    """Result / ExecMainStatus / ActiveState of the unit, from systemctl --user show"""
    out = _cmd(['systemctl', '--user', 'show', '-p', 'Result', '-p', 'ExecMainStatus', '-p', 'ActiveState', unit])
    return dict(line.split('=', 1) for line in out.splitlines() if '=' in line)


def self_alerted(unit: str, result: dict[str, str]) -> bool:
    if result.get('Result') != 'exit-code':
        return False
    try:
        status = int(result.get('ExecMainStatus', ''))
    except ValueError:
        return False
    return any(fnmatch.fnmatch(unit, pat) and status in codes for pat, codes in SELF_ALERTED.items())


def log_file(unit: str) -> str:
    """the log file the unit's script writes: task.log (capture), daily.log, <recorder>.log"""
    name = unit.removeprefix('owcskr-').rsplit('.', 1)[0]
    if name.startswith('live-'):
        name = 'task'
    return os.path.join(LIVE_DIR, f'{name}.log')


def retry_hint(unit: str) -> str:
    """how to start it again (a failed transient unit is gone after reset-failed: its script makes a new one)"""
    name = unit.removeprefix('owcskr-').rsplit('.', 1)[0]
    if name == 'daily':
        return 'systemctl --user start owcskr-daily.service'
    if name.startswith('live-'):
        return f'.venv/bin/python -I tools/schedule_today.py {name.removeprefix("live-")}'
    return 'bash tools/start_watchers.sh'


def tail(path: str, n: int) -> str:
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return ''.join(f.readlines()[-n:]).strip()
    except OSError:
        return ''


def throttled(unit: str, now: datetime.datetime) -> bool:
    """True when this unit alerted less than UNIT_REALERT ago; else records now"""
    try:
        with open(UNIT_STATE, encoding='utf-8') as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    last = state.get(unit)
    try:
        if last and now - datetime.datetime.fromisoformat(last) < UNIT_REALERT:
            return True
    except (TypeError, ValueError):
        pass
    state[unit] = now.isoformat(timespec='seconds')
    os.makedirs(LIVE_DIR, exist_ok=True)
    with open(UNIT_STATE, 'w', encoding='utf-8') as f:
        json.dump(state, f)
    return False


def unit_failed(unit: str, PU, now: datetime.datetime | None = None) -> None:
    unit = unit_name(unit)
    result = unit_result(unit)
    if self_alerted(unit, result):
        print(f"notify: {unit} exit {result.get('ExecMainStatus')} - its script alerted already", file=sys.stderr)
        return
    if throttled(unit, now or datetime.datetime.now().astimezone()):
        print(f'notify: {unit} alerted less than {UNIT_REALERT} ago - skipped', file=sys.stderr)
        return
    journal = _cmd(['journalctl', '--user', '-u', unit, '-n', str(JOURNAL_LINES), '--no-pager', '-o', 'short-iso'])
    body = (f"result {result.get('Result', '?')}, exit status {result.get('ExecMainStatus', '?')}, "
            f"now {result.get('ActiveState', '?')}\n\njournal:\n{journal[-900:] or '(no journal lines)'}")
    log = log_file(unit)
    text = tail(log, LOG_LINES)
    if text:
        body += f'\n\n{log}:\n{text[-600:]}'          # the webhook message holds 1900 characters
    body += f'\n\n(systemctl --user status {unit}; again: {retry_hint(unit)})'
    PU.notify(f'OWCSKR 유닛 실패: {unit}', body)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # Korean text on a cp949 console
        import platform_util as PU
        if len(argv) < 2:
            print('usage: notify.py TITLE BODY | notify.py --unit-failed UNIT', file=sys.stderr)
            return 0
        try:
            PU.load_env_file()          # run by hand outside the tools/*.sh scripts: still find the webhook
        except ValueError as e:
            print(f'notify: .env not loaded: {e}', file=sys.stderr)
        if argv[0] == '--unit-failed':
            unit_failed(argv[1], PU)
            return 0
        title, body = argv[0], argv[1]
        if body == '-':
            body = sys.stdin.read()
        PU.notify(title, body.strip() or '(no details)')
    except Exception as e:      # never fail the caller
        print(f'notify: failed: {type(e).__name__}: {e}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
