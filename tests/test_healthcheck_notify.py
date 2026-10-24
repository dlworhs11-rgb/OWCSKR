import datetime, json, os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import healthcheck as H
import notify as N
import platform_util as PU

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime(2026, 10, 25, 16, 0, tzinfo=KST)
MATCH = [{'date': '2026-10-25T15:00:00+09:00', 'bestof': 5}]


def test_match_window():
    assert H.in_match_window(NOW, MATCH)
    assert not H.in_match_window(NOW + datetime.timedelta(hours=4), MATCH)
    assert H.in_match_window(datetime.datetime(2026, 10, 25, 14, 50, tzinfo=KST), MATCH)
    assert not H.in_match_window(NOW, [{'date': None}, {}])


@pytest.mark.parametrize('age_min, matches, ok', [(20, MATCH, True), (45, MATCH, False), (45, [], True), (400, [], False)])
def test_check_limits(age_min, matches, ok):
    assert H.check(NOW, NOW - datetime.timedelta(minutes=age_min), matches)[0] is ok


def test_built_at_prefers_databuilt():
    assert H.built_at({'v': 'x', 'checked': '2026-10-25T10:00:00+09:00', 'dataBuilt': '2026-10-25T09:00:00+09:00'}).hour == 9
    assert H.built_at({'v': 'x', 'checked': '2026-10-25T10:00:00+09:00'}).hour == 10
    with pytest.raises(ValueError):
        H.built_at({'v': 'x'})


@pytest.fixture
def alerts(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(H, 'STATE', str(tmp_path / 'healthcheck.json'))
    monkeypatch.setattr(H, 'load_matches', lambda path=None: MATCH)
    monkeypatch.setattr(H.S, 'LP_DIR', str(tmp_path / 'lp'))
    os.makedirs(tmp_path / 'lp')
    monkeypatch.setattr(H.PU, 'notify', lambda title, text: sent.append(title))
    return sent


def test_tbd_playoff_match_opens_the_match_window(alerts, tmp_path, monkeypatch):
    """matches.json leaves out playoff matches whose teams are TBD: the stage page in data/lp still has them"""
    monkeypatch.setattr(H, 'load_matches', lambda path=None: [])
    page = {'matches': [{'date': '2026-10-31T15:00:00+09:00', 'bestof': 7, 'team1': 'TBD', 'team2': 'TBD'}]}
    (tmp_path / 'lp' / 'owcs-2026-asia-stage-3-korea.json').write_text(json.dumps(page), encoding='utf-8')
    during = datetime.datetime(2026, 10, 31, 17, 0, tzinfo=KST)
    assert H.main(['--quiet'], now=during, fetch=ver(45, during)) == 1          # 30 min limit: a match is on
    after = during + datetime.timedelta(days=1)
    assert H.main(['--quiet'], now=after, fetch=ver(45, after)) == 0             # no match: 6 h limit


def test_playoff_page_problems_do_not_stop_the_check(alerts, tmp_path):
    (tmp_path / 'lp' / 'x-korea.json').write_text('{not json', encoding='utf-8')
    assert H.main([], now=NOW, fetch=ver(20)) == 0


def ver(minutes_ago, now=NOW):
    return lambda site: {'v': 'h', 'checked': (now - datetime.timedelta(minutes=minutes_ago)).isoformat()}


def test_stale_alerts_once_then_recovers(alerts):
    assert H.main([], now=NOW, fetch=ver(60)) == 1
    assert H.main([], now=NOW + datetime.timedelta(minutes=30), fetch=ver(90, NOW + datetime.timedelta(minutes=30))) == 1
    assert len(alerts) == 1                                   # no repeat within 3 h
    assert H.main([], now=NOW + datetime.timedelta(minutes=40), fetch=ver(5, NOW + datetime.timedelta(minutes=40))) == 0
    assert len(alerts) == 2 and '회복' in alerts[-1]


def test_quiet_never_alerts(alerts):
    assert H.main(['--quiet'], now=NOW, fetch=ver(60)) == 1
    assert alerts == [] and not os.path.exists(H.STATE)


def boom(site): raise OSError('no route')


def test_unreadable_site_alerts_from_the_second_failed_read(alerts):
    assert H.main([], now=NOW, fetch=boom) == 2
    assert alerts == []                                       # one blip: no alert
    assert H.main([], now=NOW + datetime.timedelta(minutes=15), fetch=boom) == 2
    assert len(alerts) == 1 and '멈춤' in alerts[0]
    later = NOW + datetime.timedelta(minutes=30)
    assert H.main([], now=later, fetch=ver(5, later)) == 0
    assert len(alerts) == 2 and '회복' in alerts[-1]


def test_a_good_read_resets_the_failed_reads(alerts):
    assert H.main([], now=NOW, fetch=boom) == 2
    assert H.main([], now=NOW + datetime.timedelta(minutes=15), fetch=ver(5, NOW + datetime.timedelta(minutes=15))) == 0
    assert H.main([], now=NOW + datetime.timedelta(minutes=30), fetch=boom) == 2
    assert alerts == []


def test_quiet_reads_again_before_giving_up(alerts):
    calls, slept = [], []

    def flaky(site):
        calls.append(site)
        if len(calls) == 1:
            raise OSError('blip')
        return ver(5)(site)
    assert H.main(['--quiet'], now=NOW, fetch=flaky, sleep=slept.append) == 0
    assert len(calls) == 2 and slept == [H.QUIET_RETRY_SEC]
    assert H.main(['--quiet'], now=NOW, fetch=boom, sleep=slept.append) == 2
    assert alerts == [] and not os.path.exists(H.STATE)


def test_notify_cli_calls_platform_notify(monkeypatch):
    sent = []
    monkeypatch.setattr(PU, 'notify', lambda t, b: sent.append((t, b)))
    monkeypatch.setattr(PU, 'load_env_file', lambda *a: {})
    assert N.main(['제목', '본문']) == 0
    assert sent == [('제목', '본문')]


def test_notify_cli_always_exits_0(monkeypatch):
    def boom(t, b): raise RuntimeError('webhook exploded')
    monkeypatch.setattr(PU, 'notify', boom)
    monkeypatch.setattr(PU, 'load_env_file', lambda *a: {})
    assert N.main(['t', 'b']) == 0
    assert N.main([]) == 0
