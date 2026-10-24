"""tools/run_live.sh with a python stub: which runs reach live_capture.py, with what arguments, and the exit code.
DISPLAY is set so no Xvfb starts; there is no systemctl and no OWCSKR_SITE_DIR, so nothing is detached or sent."""
import os, shutil, subprocess

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = '2026-10-25'
UNTIL = '2026-10-25T23:00:00+09:00'
PY = r'''#!/usr/bin/env bash
echo "py $*" >> "$FAKE_LOG"
case "$2" in
  tools/platform_util.py) echo "$FAKE_UNTIL"; exit "${FAKE_LU_RC:-0}" ;;
  tools/live_capture.py) exit "${FAKE_LC_RC:-0}" ;;
esac
exit 0
'''


@pytest.fixture
def live(tmp_path):
    bash = shutil.which('bash')
    if not bash or 'system32' in bash.lower():
        pytest.skip('no bash')
    root = tmp_path / 'repo'
    (root / 'tools').mkdir(parents=True)
    for f in ('env.sh', 'run_live.sh', 'start_watchers.sh'):
        shutil.copy(os.path.join(HERE, 'tools', f), root / 'tools' / f)
    py = tmp_path / 'fakepy'
    with open(py, 'w', newline='\n') as f:
        f.write(PY)
    os.chmod(py, 0o755)
    stubs = tmp_path / 'stubs'
    stubs.mkdir()
    with open(stubs / 'Xvfb', 'w', newline='\n') as f:          # logs and dies: run_live.sh goes on without a display
        f.write('#!/usr/bin/env bash\necho "Xvfb $*" >> "$FAKE_LOG"\nexit 1\n')
    os.chmod(stubs / 'Xvfb', 0o755)
    log = tmp_path / 'calls.log'
    base = {k: v for k, v in os.environ.items() if not k.startswith('OWCSKR_')}
    base.update(OWCSKR_PYTHON=py.as_posix(), FAKE_LOG=log.as_posix(), FAKE_UNTIL=UNTIL, DISPLAY=':0',
                HOME=tmp_path.as_posix(), PATH=str(stubs) + os.pathsep + os.environ.get('PATH', ''))

    def run(args=('6.5', DAY), **env):
        r = subprocess.run([bash, 'tools/run_live.sh', *args], cwd=root, env=dict(base, **env),
                           capture_output=True, text=True, timeout=60)
        calls = log.read_text(encoding='utf-8').splitlines() if log.exists() else []
        run.all_calls = calls
        return r.returncode, [c for c in calls if 'live_capture.py' in c or 'notify.py' in c]
    run.day = root / 'data' / 'live' / DAY
    return run


def test_capture_gets_until_and_date(live):
    rc, calls = live()
    assert rc == 0
    assert calls == [f'py -I tools/live_capture.py --until {UNTIL} --date {DAY}']


def test_exit_code_is_passed_on(live):
    rc, calls = live(FAKE_LC_RC='4')
    assert rc == 4                                    # RestartPreventExitStatus=2 4: not restarted
    assert any('notify.py' in c for c in calls)


def test_finished_day_is_not_captured_again(live):
    live.day.mkdir(parents=True)
    (live.day / 'summary.txt').write_text('sent')
    rc, calls = live()
    assert rc == 0 and calls == []


def test_day_over_after_a_crash_runs_the_final_pass_once(live):
    (live.day / 'frames').mkdir(parents=True)
    rc, calls = live(FAKE_LU_RC='3', FAKE_LC_RC='1')
    assert rc == 0                                    # the final pass's result never restarts the unit
    assert calls == [f'py -I tools/live_capture.py --until {UNTIL} --date {DAY}']


def test_day_over_without_frames_does_nothing(live):
    rc, calls = live(FAKE_LU_RC='3')
    assert rc == 0 and calls == []


def test_bad_end_time_is_exit_2_with_an_alert(live):
    rc, calls = live(FAKE_LU_RC='2', FAKE_UNTIL='')
    assert rc == 2 and any('notify.py' in c for c in calls)


def test_obs_source_without_a_display_starts_xvfb(live):
    rc, calls = live(DISPLAY='')
    assert rc == 0 and any(c.startswith('Xvfb :99') for c in live.all_calls)
    assert calls == [f'py -I tools/live_capture.py --until {UNTIL} --date {DAY}']


@pytest.mark.parametrize('value', ['webcam', '   '])
def test_unknown_source_is_obs_with_a_warning(live, value):
    """as platform_util.frame_source reads it for live_capture.py: anything but hls / obs is obs (so Xvfb starts)"""
    rc, calls = live(DISPLAY='', OWCSKR_FRAME_SOURCE=value)
    assert rc == 0 and any(c.startswith('Xvfb :99') for c in live.all_calls)
    task = (live.day.parent / 'task.log').read_text(encoding='utf-8')
    assert f"OWCSKR_FRAME_SOURCE='{value}' is not obs or hls - using obs" in task


def test_hls_source_never_starts_xvfb(live):
    rc, calls = live(DISPLAY='', OWCSKR_FRAME_SOURCE=' HLS ')
    assert rc == 0 and not any(c.startswith('Xvfb') for c in live.all_calls)
    assert calls == [f'py -I tools/live_capture.py --until {UNTIL} --date {DAY}']


def test_shadow_run_posts_no_replay_comment(live, tmp_path):
    """OWCSKR_PUBLISH=0 (P1-R5): the capture runs as usual, the replay comment is left to the publishing machine"""
    site = tmp_path / 'site'
    site.mkdir()
    (site / 'replay_comment.py').write_text('', encoding='utf-8')
    rc, calls = live(OWCSKR_SITE_DIR=site.as_posix(), OWCSKR_PUBLISH='0')
    assert rc == 0 and calls == [f'py -I tools/live_capture.py --until {UNTIL} --date {DAY}']
    assert not any('replay_comment' in c for c in live.all_calls)
    task = (live.day.parent / 'task.log').read_text(encoding='utf-8')
    assert 'publish off (OWCSKR_PUBLISH=0) - replay comment not posted' in task


@pytest.mark.parametrize('args', [(), ('6.5',), ('6.5', '25-10-2026')])
def test_bad_arguments_exit_2_with_an_alert(live, args):
    """exit 2 is not restarted and notify.py --unit-failed skips it (run_live.sh alerts on 2 itself): a unit with
    bad arguments must not fail silently"""
    rc, calls = live(args)
    assert rc == 2
    assert len(calls) == 1 and calls[0].startswith('py -I ') and calls[0].split()[2].endswith('/repo/tools/notify.py')
    assert 'OWCSKR 캡처 시작 실패' in calls[0]
