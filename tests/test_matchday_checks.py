"""tools/matchday_check.py and tools/soop_quality.py on an HLS server (OWCSKR_FRAME_SOURCE=hls): no OBS checks."""
import os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import platform_util as PU
import matchday_check as MC

SQ = pytest.importorskip('soop_quality')   # needs cv2


def _no_obs_calls(monkeypatch):
    def boom(*a): raise AssertionError('OBS checked on an HLS machine')
    monkeypatch.setattr(PU, 'obs_installed', boom)
    monkeypatch.setattr(PU, 'process_running', boom)


@pytest.fixture
def capture_only(monkeypatch):
    """a server without the site recorders whose capture is running"""
    monkeypatch.setattr(PU, 'SITE_DIR', '')
    monkeypatch.setattr(PU, 'python_cmdlines', lambda: '/srv/.venv/bin/python -I tools/live_capture.py --until x')


def test_matchday_check_skips_obs_with_hls(monkeypatch, capture_only):
    monkeypatch.setenv('OWCSKR_FRAME_SOURCE', 'hls')
    _no_obs_calls(monkeypatch)
    out, notes = MC.problems()
    assert out == [] and any('hls' in n for n in notes)


def test_matchday_check_still_checks_obs_by_default(monkeypatch, capture_only):
    monkeypatch.delenv('OWCSKR_FRAME_SOURCE', raising=False)
    monkeypatch.setattr(PU, 'obs_installed', lambda: True)
    monkeypatch.setattr(PU, 'process_running', lambda name: False)
    out, _ = MC.problems()
    assert out == ['OBS가 안 켜져 있음']


def test_soop_quality_only_logs_with_hls(monkeypatch, tmp_path):
    monkeypatch.setenv('OWCSKR_FRAME_SOURCE', 'hls')
    _no_obs_calls(monkeypatch)
    monkeypatch.setattr(PU, 'LIVE_DIR', str(tmp_path))
    monkeypatch.setattr(SQ, 'LOG', str(tmp_path / 'soop_quality.log'))
    monkeypatch.setattr(SQ, 'popup', lambda text: (_ for _ in ()).throw(AssertionError('alerted')))
    assert SQ.main() == 0
    assert 'skipped: frame source hls' in (tmp_path / 'soop_quality.log').read_text(encoding='utf-8')
