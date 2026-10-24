"""tools/dispatch_site.py: gh workflow run on the site repo, only when turned on and within the capture window; alerts
after 3 failures in a row. gh is never run: subprocess.run is replaced."""
import datetime, os, subprocess, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import dispatch_site as D

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime(2026, 10, 25, 16, 0, tzinfo=KST)
UNTIL = ['--until', '2026-10-25T21:00:00+09:00']


class FakeGh:
    def __init__(self, rc=0):
        self.rc, self.calls = rc, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.rc, '', '' if self.rc == 0 else 'HTTP 403: Resource not accessible')


@pytest.fixture
def alerts(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(D, 'STATE', str(tmp_path / 'dispatch.json'))
    monkeypatch.setattr(D.PU, 'notify', lambda title, text: sent.append(title))
    monkeypatch.setenv('OWCSKR_SITE_DISPATCH', '1')
    monkeypatch.delenv('OWCSKR_SITE_REPO', raising=False)
    return sent


def test_dispatches_pages_yml_on_the_site_repo(alerts):
    gh = FakeGh()
    assert D.main(UNTIL, now=NOW, run=gh) == 0
    assert gh.calls == [['gh', 'workflow', 'run', 'pages.yml', '-R', 'dlworhs11-rgb/owcs-kr']]


def test_off_or_past_the_window_does_nothing(alerts, monkeypatch):
    gh = FakeGh()
    assert D.main(UNTIL, now=NOW + datetime.timedelta(hours=6), run=gh) == 0
    monkeypatch.setenv('OWCSKR_SITE_DISPATCH', '0')
    assert D.main(UNTIL, now=NOW, run=gh) == 0
    assert gh.calls == []


def test_bad_until_is_exit_2(alerts):
    assert D.main(['--until', '2026-10-25T21:00'], now=NOW, run=FakeGh()) == 2     # no offset
    assert D.main(['--until'], now=NOW, run=FakeGh()) == 2


def test_alerts_from_the_third_failure_then_recovers(alerts):
    for i in range(4):
        assert D.main(UNTIL, now=NOW + datetime.timedelta(minutes=10 * i), run=FakeGh(1)) == 1
    assert len(alerts) == 1 and '실패' in alerts[0]              # 3rd failure; the 4th is within 3 h
    assert D.main(UNTIL, now=NOW + datetime.timedelta(minutes=40), run=FakeGh()) == 0
    assert len(alerts) == 2 and '회복' in alerts[1]


def test_gh_missing_is_a_failure_not_a_crash(alerts):
    def missing(cmd, **kw): raise FileNotFoundError('gh')
    assert D.main(UNTIL, now=NOW, run=missing) == 1
