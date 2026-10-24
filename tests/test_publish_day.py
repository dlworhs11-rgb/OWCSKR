import base64, datetime, json, os, sys, types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import publish_day as PD
REAL_GH = PD.gh                          # the 'gh' fixture replaces PD.gh
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
    assert len(gh.calls) == 1 and gh.calls[0][0][0] != '-X'              # looked (404), no PUT


def test_no_longer_verified_maps_are_withdrawn(tmp_path, gh):
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True, 'labelVerified': False}])
    gh.remote = {'date': DATE, 'maps': [{'map': 'A', 'totalsVerified': True}], 'matches': [{'match': 'X'}], 'note': 'n'}
    assert PD.main([DATE], root=str(tmp_path)) == 0
    body, day = gh.uploaded()
    assert day['maps'] == [] and day['matches'] == [] and day['date'] == DATE and body['sha'] == 'abc'
    assert 'withdrawn' in body['message']


def test_withdrawal_spares_manual_files_and_is_idempotent(tmp_path, gh):
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': False}])
    gh.remote = {'maps': [{'reading': 'manual'}]}
    assert PD.main([DATE], root=str(tmp_path)) == 0 and len(gh.calls) == 1
    gh.remote, gh.calls = {'date': DATE, 'maps': [], 'matches': []}, []
    assert PD.main([DATE], root=str(tmp_path)) == 0 and len(gh.calls) == 1   # already withdrawn: no PUT


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


def test_hung_gh_is_a_failure_not_a_hang(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(PD, 'find_gh', lambda which=None: '/usr/bin/gh')
    seen = {}
    def hangs(cmd, **kw):
        seen.update(kw)
        raise subprocess.TimeoutExpired(cmd, kw['timeout'])
    monkeypatch.setattr(PD, 'gh', lambda *a, data=None: REAL_GH(*a, data=data, run=hangs))
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}])
    assert PD.main([DATE], root=str(tmp_path)) == 1                    # the GET timed out: no PUT without the sha
    assert seen['timeout'] == PD.GH_TIMEOUT


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


class RacingGH(FakeGH):
    """the first PUTs fail with a sha conflict: someone else wrote the file between our GET and our PUT"""
    def __init__(self, conflicts, after=None, code='409', **kw):
        super().__init__(**kw)
        self.conflicts, self.after, self.code = conflicts, after, code

    def __call__(self, *args, data=None):
        if args[0] == '-X' and self.conflicts:
            self.calls.append((args, data)); self.conflicts -= 1
            if self.after is not None: self.remote = self.after
            return 1, '', f'gh: sha does not match (HTTP {self.code})'
        return super().__call__(*args, data=data)


def puts(fake): return [c for c in fake.calls if c[0][0] == '-X']


@pytest.mark.parametrize('code', ['409', '422'])
def test_sha_conflict_rereads_and_retries(tmp_path, monkeypatch, code):
    fake = RacingGH(1, code=code, remote={'maps': []})
    monkeypatch.setattr(PD, 'gh', fake); monkeypatch.setattr(PD, 'find_gh', lambda which=None: '/usr/bin/gh')
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}])
    assert PD.main([DATE], root=str(tmp_path)) == 0
    assert [c[0][0] for c in fake.calls] == ['repos/dlworhs11-rgb/OWCSKR/contents/data/manual/mapstats/2026-10-25.json?ref=main',
                                             '-X'] * 2                       # GET, PUT (409), GET again, PUT
    assert fake.uploaded()[1]['maps'][0]['map'] == 'A'


def test_sha_conflict_gives_up_after_two_retries(tmp_path, monkeypatch):
    fake = RacingGH(5, remote={'maps': []})
    monkeypatch.setattr(PD, 'gh', fake); monkeypatch.setattr(PD, 'find_gh', lambda which=None: '/usr/bin/gh')
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}])
    assert PD.main([DATE], root=str(tmp_path)) == 1
    assert len(puts(fake)) == 1 + PD.SHA_RETRIES == 3


def test_sha_conflict_never_overwrites_a_manual_file_written_meanwhile(tmp_path, monkeypatch):
    fake = RacingGH(1, after={'maps': [{'reading': 'manual'}]}, remote={'maps': []})
    monkeypatch.setattr(PD, 'gh', fake); monkeypatch.setattr(PD, 'find_gh', lambda which=None: '/usr/bin/gh')
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}])
    assert PD.main([DATE], root=str(tmp_path)) == 0
    assert len(puts(fake)) == 1                                              # re-read saw the manual file: no second PUT


def test_other_put_errors_are_not_retried(tmp_path, monkeypatch):
    fake = RacingGH(5, code='403', remote={'maps': []})
    monkeypatch.setattr(PD, 'gh', fake); monkeypatch.setattr(PD, 'find_gh', lambda which=None: '/usr/bin/gh')
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True}])
    assert PD.main([DATE], root=str(tmp_path)) == 1
    assert len(puts(fake)) == 1


def test_unknown_map_fields_like_matchkey_are_kept(tmp_path, gh):
    write_day(tmp_path, [{'map': 'A', 'totalsVerified': True, 'matchKey': '2026-10-25T18:00:00+09:00|ZETA|CR', 'extra': {'x': 1}}])
    assert PD.main([DATE], root=str(tmp_path)) == 0
    m = gh.uploaded()[1]['maps'][0]
    assert m['matchKey'] == '2026-10-25T18:00:00+09:00|ZETA|CR' and m['extra'] == {'x': 1}
