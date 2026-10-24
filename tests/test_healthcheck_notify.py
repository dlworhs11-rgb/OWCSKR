import datetime, os, sys

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
    monkeypatch.setattr(H.PU, 'notify', lambda title, text: sent.append(title))
    return sent


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


def test_unreadable_site_is_exit_2(alerts):
    def boom(site): raise OSError('no route')
    assert H.main([], now=NOW, fetch=boom) == 2
    assert len(alerts) == 1


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
