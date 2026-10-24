"""Player of the Match: frame choice, roster check, one card per match (P1-06 items 3-5)."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
import assemble_day as AD
from test_assemble_labels import FX, ctx_of, run_day

# 10-23 card frames: the intro frame has the numbers half drawn and no E/D yet
INTRO = {'name': '?51', 'elims': 0, 'deaths': 2, 'dmgPerMin': 1}
DRAWN = {'name': 'HeeSang', 'elims': 73, 'deaths': 10, 'ed': 7.3, 'dmgPerMin': 924}


def ts_of(mm):
    return next(AD.frame_ts(e['frame']) for e in FX['ocr'] if e['map'] == mm)


def test_intro_frame_without_ed_loses_to_drawn_frame():
    assert AD.potm_numbers([INTRO, DRAWN]) == DRAWN
    assert AD.potm_numbers([INTRO]) is None                       # intro only -> no numbers


def test_inconsistent_or_partial_frames_are_not_candidates():
    half = {'elims': 40, 'deaths': 10, 'ed': 7.3}                  # numbers still counting up
    assert AD.potm_numbers([half]) is None
    assert AD.potm_numbers([half, DRAWN, {'elims': 7, 'deaths': 1, 'ed': 7.0}]) == DRAWN   # most elims wins
    assert AD.potm_numbers([{'elims': 12, 'deaths': 0, 'ed': 12.0}])['elims'] == 12       # no deaths: E/D = elims


def test_card_name_ignores_intro_noise():
    assert AD.card_name([INTRO, DRAWN, {'name': 'HeeSang'}, {'name': 'HeeSanq'}]) == 'HeeSang'
    assert AD.card_name([INTRO]) == ''


def test_name_from_the_other_match_is_rejected():
    card = {'name': 'Someone', 'numbers': {'elims': 0, 'deaths': 2, 'ed': None, 'dmgPerMin': 1}}
    potm, method = AD.pick_potm(card, [], ['Cheeseburger', 'O2 Blast'], ctx_of())   # Someone plays for Falcons
    assert potm is None and method == 'unresolved'


def test_team_comes_from_the_roster():
    potm, method = AD.pick_potm(AD.potm_card([INTRO, DRAWN]), [], ['Crazy Raccoon', 'SEIJI ESPORTS'], ctx_of())
    assert method == 'name'
    assert potm == {'name': 'HeeSang', 'team': 'Crazy Raccoon', 'elims': 73, 'deaths': 10, 'dmgPerMin': 924,
                    'screenName': 'HeeSang', 'method': 'name'}


def test_unreadable_name_resolved_by_unique_table_totals_only_for_named_rows():
    maps = [{'teams': {'Crazy Raccoon': [{'name': 'LIP', 'e': 40, 'd': 5}, {'name': None, 'unknownId': '?3', 'e': 73, 'd': 10}],
                       'SEIJI ESPORTS': [{'name': None, 'unknownId': '?4', 'e': 1, 'd': 1}]}},
            {'teams': {'Crazy Raccoon': [{'name': 'LIP', 'e': 33, 'd': 5}]}}]
    card = {'name': '', 'numbers': {'elims': 73, 'deaths': 10, 'ed': 7.3, 'dmgPerMin': 900}}
    potm, method = AD.pick_potm(card, maps, ['Crazy Raccoon', 'SEIJI ESPORTS'], ctx_of())
    assert method == 'elims+deaths match' and potm['name'] == 'LIP' and potm['team'] == 'Crazy Raccoon'
    card['numbers'] = {'elims': 1, 'deaths': 1, 'ed': 1.0}            # only a '?k' row fits: never its team
    assert AD.pick_potm(card, maps, ['Crazy Raccoon', 'SEIJI ESPORTS'], ctx_of()) == (None, 'unresolved')


def test_one_card_goes_to_one_match():
    groups = [('A', 100, 200), ('B', 300, 400)]
    assert AD.assign_cards(groups, [(450, 'card')]) == {'B': (450, 'card')}   # after B's last map only
    assert AD.assign_cards(groups, [(250, 'c1'), (260, 'c2')]) == {'A': (250, 'c1')}
    assert AD.assign_cards([('A', 100, 200), ('B', 210, 220)], [(205, 'x')]) == {'A': (205, 'x')}
    assert AD.assign_cards([('A', 100, 200)], [(200 + AD.POTM_WINDOW + 1, 'late')]) == {}


def test_1023_day_potm(monkeypatch):
    cards = [(ts_of('03') + 400, AD.potm_card([{'name': 'Belosrea', 'elims': 60, 'deaths': 20, 'ed': 3.0, 'dmgPerMin': 800}])),
             (ts_of('06') + 400, AD.potm_card([dict(INTRO, name='Someone'), {'name': 'Someone', 'elims': 50, 'deaths': 25, 'ed': 2.0, 'dmgPerMin': 700}])),
             (ts_of('09') + 300, AD.potm_card([INTRO, DRAWN]))]
    res = run_day(monkeypatch, cards=cards)
    potm = {r['match']: (r['potm'] or {}).get('name') for r in res['matches']}
    team = {r['match']: (r['potm'] or {}).get('team') for r in res['matches']}
    assert potm == {'Cheeseburger vs O2 Blast': 'Belosrea', 'Team Falcons vs ZANSIDE GAMING': 'Someone',
                    'Crazy Raccoon vs SEIJI ESPORTS': 'HeeSang'}
    assert team['Crazy Raccoon vs SEIJI ESPORTS'] == 'Crazy Raccoon'
    assert [r['potm']['elims'] for r in res['matches']] == [60, 50, 73]
    assert AD.summary('2026-10-23', res).endswith('POTM: Belosrea, Someone, HeeSang')


def test_card_with_foreign_name_leaves_potm_empty(monkeypatch):
    cards = [(ts_of('03') + 400, AD.potm_card([{'name': 'Someone', 'elims': 0, 'deaths': 2, 'dmgPerMin': 1}]))]
    res = run_day(monkeypatch, cards=cards)
    cb = next(r for r in res['matches'] if r['match'] == 'Cheeseburger vs O2 Blast')
    assert cb['potm'] is None and cb['potmMethod'] == 'unresolved' and cb['potmScreenName'] == 'Someone'
