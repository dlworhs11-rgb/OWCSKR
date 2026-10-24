"""Match / game / panel-team resolution of assemble_day (P1-05), on the 2026-10-23 day as captured."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
import assemble_day as AD
import names as NM

FX = json.load(open(os.path.join(HERE, 'fixtures', 'live-2026-10-23.json'), encoding='utf-8'))
DATE = FX['date']


def ctx_of(fx=FX):
    aliases = {k: v for k, v in fx['aliases'].items() if not k.startswith('_')}
    h = {NM.norm(k): NM.norm(v) for k, v in fx['handleAliases'].items()}
    return {'aliases': aliases, 'h': h, 'teams': set(aliases.values()),
            'schedule': AD.day_schedule(fx['schedule'], fx['date'], aliases),
            'rosters': NM.build_rosters(fx['players'], aliases, h)}


def fake_rows(monkeypatch, names):
    """read_rows without images: names per frame from the fixture (None = unknown)"""
    def read_rows(entry, im, lib, unknown, unknown_dir):
        panels = []
        for pi in (0, 1):
            rows = []
            for r in range(pi * 5, pi * 5 + 5):
                nums = {k: entry['rows'][r][k] for k in AD.K}
                nm = names[entry['frame']][r]
                if nm is None:
                    uid = AD.unknown_id(entry['map'], r, unknown); unknown.append({'id': uid, 'map': entry['map'], 'row': r})
                    rows.append({'name': None, 'unknownId': uid, **nums})
                else:
                    rows.append({'name': nm, **nums})
            panels.append(rows)
        return panels
    monkeypatch.setattr(AD, 'read_rows', read_rows)


def run_day(monkeypatch, ocr=None, bans=None, cards=(), ctx=None):
    fake_rows(monkeypatch, FX['names'])
    return AD.assemble(ocr or FX['ocr'], lambda e: None, [tuple(b) for b in (FX['bans'] if bans is None else bans)],
                       list(cards), ctx or ctx_of(), [], 'unused')


def by_map(res):
    return {m['frame'][1:3]: m for m in res['maps']}


def test_fold_matches_sheet_spelling():
    assert NM.fold('Irony') == NM.fold('iR0NY')
    assert NM.fold('D0nghak', {'d0nghak': 'donghak'}) == NM.fold('donghak')
    ctx = ctx_of()
    assert NM.team_of('Irony', ctx['rosters'], ctx['h']) == 'ZANSIDE GAMING'
    assert NM.team_of('Someone', ctx['rosters'], ctx['h']) == 'Team Falcons'


def test_schedule_is_korean_matches_in_time_order():
    s = ctx_of()['schedule']
    assert [(m['team1'], m['team2']) for m in s] == [('Cheeseburger', 'O2 Blast'), ('Team Falcons', 'ZANSIDE GAMING'),
                                                     ('Crazy Raccoon', 'SEIJI ESPORTS')]


def test_misread_match1_with_falcons_zanside_ban_goes_to_match2(monkeypatch):
    m = by_map(run_day(monkeypatch))
    m04 = m['04']
    assert (m04['match'], m04['matchNo'], m04['game']) == ('Team Falcons vs ZANSIDE GAMING', 2, 1)
    assert list(m04['teams']) == ['Team Falcons', 'ZANSIDE GAMING']        # Irony sits in the lower panel
    assert m04['labelVerified'] is True
    assert any('ban screen Team Falcons vs ZANSIDE GAMING is not Cheeseburger vs O2 Blast' in i for i in m04['labelIssues'])
    assert [(m[k]['matchNo'], m[k]['game']) for k in ('05', '06')] == [(2, 2), (2, 3)]
    assert m04['bans'] and m04['seriesBefore'] == {'Team Falcons': 0, 'ZANSIDE GAMING': 0}


def test_only_known_player_without_ban_screen_also_moves_the_map(monkeypatch):
    bans = [b for b in FX['bans'] if b[1]['teams'][0] != 'Team Falcons']
    m04 = by_map(run_day(monkeypatch, bans=bans))['04']
    assert (m04['matchNo'], m04['match']) == (2, 'Team Falcons vs ZANSIDE GAMING')   # Irony -> header dropped -> 18:52 is match 2
    assert any('known players of ZANSIDE GAMING in match 1' in i for i in m04['labelIssues'])
    assert 'match from schedule time' in m04['labelIssues']


def test_cheeseburger_o2_keeps_one_game_1(monkeypatch):
    res = run_day(monkeypatch)
    cb = [(x['game'], x['labelVerified']) for x in res['maps'] if x['match'] == 'Cheeseburger vs O2 Blast']
    assert cb == [(1, True), (2, True), (3, True)]


def test_header_kept_when_it_agrees(monkeypatch):
    m = by_map(run_day(monkeypatch))
    assert (m['02']['matchNo'], m['02']['game'], m['02']['labelVerified']) == (1, 2, True)
    assert not any(i.startswith('match from') for i in m['02']['labelIssues'])
    assert list(m['01']['teams']) == ['Cheeseburger', 'O2 Blast']         # Wutian (O2) is in the lower panel


def test_one_misread_name_of_a_third_team_is_overruled_by_header_and_ban_screen(monkeypatch):
    # m09: header MATCH 3 GAME 3, ban screen CR vs SEIJI 2-0 Aatlis, LIP (CR) lower panel, 'Soae' (Poker Face) upper
    m09 = by_map(run_day(monkeypatch))['09']
    assert (m09['match'], m09['matchNo'], m09['game'], m09['map'], m09['labelVerified']) == (
        'Crazy Raccoon vs SEIJI ESPORTS', 3, 3, 'Aatlis', True)
    assert list(m09['teams']) == ['SEIJI ESPORTS', 'Crazy Raccoon']        # LIP decides the sides, not Soae
    upper, lower = m09['teams'].values()
    assert upper[1]['name'] is None and upper[1]['misreadName'] == 'Soae' and lower[1]['name'] == 'LIP'
    assert any(i.startswith('known name Soae (Poker Face) is not Crazy Raccoon vs SEIJI ESPORTS: overruled by 3 sources')
               for i in m09['labelIssues'])


def test_no_known_player_uses_ban_order(monkeypatch):
    m07 = by_map(run_day(monkeypatch))['07']
    assert list(m07['teams']) == ['Crazy Raccoon', 'SEIJI ESPORTS'] and m07['labelVerified'] is True
    assert 'panel sides from ban-screen order (no known player)' in m07['labelIssues']


def test_no_known_player_and_no_ban_is_not_trusted(monkeypatch):
    bans = [b for b in FX['bans'] if b[1]['teams'][0] != 'Crazy Raccoon']
    m07 = by_map(run_day(monkeypatch, bans=bans))['07']
    assert m07['matchNo'] == 3 and m07['labelVerified'] is False


def test_duplicate_match_game_blocks_both(monkeypatch):
    ocr = json.loads(json.dumps(FX['ocr']))
    ocr[1]['header']['game'] = 1                                          # m02 header misread as game 1, no ban screen
    m01_ts, m02_ts = AD.frame_ts(ocr[0]['frame']), AD.frame_ts(ocr[1]['frame'])
    bans = [b for b in FX['bans'] if not m01_ts < b[0] < m02_ts]
    m = by_map(run_day(monkeypatch, ocr=ocr, bans=bans))
    assert m['01']['labelVerified'] is False and m['02']['labelVerified'] is False
    assert 'duplicate match 1 game 1' in m['01']['labelIssues']


def test_header_game_disagreeing_with_ban_score_is_not_trusted(monkeypatch):
    ocr = json.loads(json.dumps(FX['ocr']))
    ocr[2]['header']['game'] = 2                                          # m03, ban screen says 2-0 -> game 3
    m03 = by_map(run_day(monkeypatch, ocr=ocr))['03']
    assert m03['labelVerified'] is False
    assert 'header game 2 but ban-screen score 2-0' in m03['labelIssues']


def test_ambiguous_header_digit_falls_back(monkeypatch):
    ocr = json.loads(json.dumps(FX['ocr']))
    ocr[3]['header'].update(match=None, matchAmbiguous=True)
    m04 = by_map(run_day(monkeypatch, ocr=ocr))['04']
    assert m04['matchNo'] == 2 and m04['labelVerified'] is True
    assert 'header match digit ambiguous' in m04['labelIssues']


def test_match_number_cannot_go_back_in_time(monkeypatch):
    ocr = json.loads(json.dumps(FX['ocr']))
    ocr[7]['header']['match'] = 1                                         # m08 (CR vs SEIJI) misread as match 1
    m08 = by_map(run_day(monkeypatch, ocr=ocr))['08']
    assert m08['matchNo'] == 3 and any('header match 1 after match 3' in i for i in m08['labelIssues'])


def test_no_schedule_publishes_nothing(monkeypatch):
    ctx = ctx_of(); ctx['schedule'] = []
    res = run_day(monkeypatch, ctx=ctx)
    assert not any(m['labelVerified'] for m in res['maps'])


def test_unknown_names_and_known_ratio(monkeypatch):
    res = run_day(monkeypatch)
    m01 = by_map(res)['01']
    rows = [r for t in m01['teams'].values() for r in t]
    assert rows[0]['name'] is None and rows[0]['unknownId'] == '?10' and rows[0]['e'] == 13
    assert 'known names 1/10' in m01['labelIssues'] and m01['labelVerified'] is True
    assert m01['framesAgree'] is True and m01['totalsVerified'] is True
    assert AD.summary(DATE, res).startswith('2026-10-23: 9 maps, 5 verified by totals, 9 label-verified, 77 unknown names, 9 map(s) under 50% known names, ')


def test_load_context_from_files(tmp_path):
    for rel, data in (('data/aliases.json', FX['aliases']), ('data/manual/handle-aliases.json', FX['handleAliases']),
                      ('data/manual/players.json', FX['players']),
                      ('data/site/matches.json', FX['schedule'])):
        p = tmp_path / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data), encoding='utf-8')
    ctx = AD.load_context(DATE, str(tmp_path))
    assert len(ctx['schedule']) == 3 and 'ZANSIDE GAMING' in ctx['rosters']
    (tmp_path / 'data/site/matches.json').unlink()
    assert AD.load_context(DATE, str(tmp_path))['schedule'] == []
