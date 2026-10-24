import base64, datetime, json, os, sys, types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import publish_day as PD
import republish_recent as RR

DATE = '2026-10-25'


def write_day(root, maps):
    d = root / 'data' / 'live' / DATE
    d.mkdir(parents=True)
    (d / 'mapstats.json').write_text(json.dumps({'date': DATE, 'maps': maps, 'matches': []}), encoding='utf-8')


class FakeGH:
    """records gh api calls; remote = None (404) or the remote file's JSON"""
    def __init__(self, remote=None, get_err='gh: Not Found (HTTP 404)', put_code=0):
        self.remote, self.get_err, self.put_code, self.calls = remote, get_err, put_code, []

    def __call__(self, *args, data=None):
        self.calls.append((args, data))
        if args[0] == '-X':
            return self.put_code, '{}', '' if self.put_code == 0 else 'HTTP 409 conflict'
        if self.remote is None:
            return 1, '', self.get_err
        content = base64.b64encode(json.dumps(self.remote).encode()).decode()
        return 0, json.dumps({'sha': 'abc', 'content': content}), ''

    def uploaded(self):
        body = json.loads(self.calls[-1][1])
        return body, json.loads(base64.b64decode(body['content']))


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGH()
    monkeypatch.setattr(PD, 'gh', fake)
    monkeypatch.setattr(PD, 'find_gh', lambda which=None: '/usr/bin/gh')
    return fake


def test_publishable_rule():
    assert PD.publishable({'totalsVerified': True})
    assert PD.publishable({'totalsVerified': True, 'labelVerified': True})
    assert not PD.publishable({'totalsVerified': True, 'labelVerified': False})
    assert not PD.publishable({'totalsVerified': None})
    assert not PD.publishable({'totalsVerified': 1})            # strictly True
    assert not PD.publishable({})


def test_only_verified_and_labelled_maps_are_uploaded(tmp_path, gh):
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}, {'map': 'B', 'totalsVerified': False},
                         {'map': 'C', 'totalsVerified': True, 'labelVerified': False}, {'map': 'D', 'totalsVerified': None},
                         {'map': 'E', 'totalsVerified': True, 'labelVerified': True}])
    assert PD.main([DATE], root=str(tmp_path)) == 0
    body, day = gh.uploaded()
    assert [m['map'] for m in day['maps']] == ['A', 'E'] and 'sha' not in body
    assert body['message'] == f'Live stats {DATE}: 2 verified map(s)'


def test_nothing_verified_uploads_nothing(tmp_path, gh):
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': None}])
    assert PD.main([DATE], root=str(tmp_path)) == 0
    assert gh.calls == []


def test_unchanged_remote_is_not_rewritten(tmp_path, gh):
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}])
    gh.remote = {'date': DATE, 'maps': [{'map': 'A', 'totalsVerified': True}], 'matches': []}
    assert PD.main([DATE], root=str(tmp_path)) == 0
    assert len(gh.calls) == 1


def test_manual_remote_is_never_overwritten(tmp_path, gh):
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}])
    gh.remote = {'maps': [{'reading': 'manual'}]}
    assert PD.main([DATE], root=str(tmp_path)) == 0
    assert len(gh.calls) == 1


def test_update_sends_sha(tmp_path, gh):
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}])
    gh.remote = {'maps': []}
    assert PD.main([DATE], root=str(tmp_path)) == 0
    assert gh.uploaded()[0]['sha'] == 'abc'


def test_put_failure_exits_1(tmp_path, gh):
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}])
    gh.put_code = 1
    assert PD.main([DATE], root=str(tmp_path)) == 1


def test_read_error_other_than_404_exits_1(tmp_path, gh):
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}])
    gh.get_err = 'HTTP 401: Bad credentials'
    assert PD.main([DATE], root=str(tmp_path)) == 1
    assert len(gh.calls) == 1                                     # no blind PUT without the sha


def test_missing_gh_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(PD, 'find_gh', lambda which=None: None)
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}])
    assert PD.main([DATE], root=str(tmp_path)) == 2
    assert 'gh (GitHub CLI) not found' in capsys.readouterr().err


def test_find_gh_has_no_windows_default_on_linux(monkeypatch):
    monkeypatch.setattr(PD.PU, 'IS_WIN', False)
    assert PD.find_gh(lambda name: None) is None
    assert PD.find_gh(lambda name: '/usr/bin/gh') == '/usr/bin/gh'


def test_republish_reports_failure_and_skips_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(RR, 'ROOT', str(tmp_path))
    today = datetime.date(2026, 10, 25)
    for day in ('2026-10-24', '2026-10-25'):
        (tmp_path / 'data' / 'live' / day).mkdir(parents=True)
        (tmp_path / 'data' / 'live' / day / 'ocr.json').write_text('[]', encoding='utf-8')
    calls = []
    def fake_run(cmd, **kw):
        calls.append((os.path.basename(cmd[2]), cmd[3]))
        assert kw['encoding'] == 'utf-8'
        rc = 1 if cmd[3] == '2026-10-24' and 'assemble' in cmd[2] else 0
        return types.SimpleNamespace(returncode=rc, stdout='', stderr='boom' if rc else '')
    assert RR.main(today, fake_run) == 1
    assert calls == [('assemble_day.py', '2026-10-24'), ('assemble_day.py', '2026-10-25'), ('publish_day.py', '2026-10-25')]


def test_republish_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(RR, 'ROOT', str(tmp_path))
    ok = lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout='', stderr='')
    assert RR.main(datetime.date(2026, 10, 25), ok) == 0
