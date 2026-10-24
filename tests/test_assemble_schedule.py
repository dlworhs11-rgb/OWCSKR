"""Schedule entries of assemble_day: matchKey (RA-17) and the header's match numbers on a day with a second Korea page
(RA-19), on the 2026-10-23 capture."""
import copy, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
import assemble_day as AD
from test_assemble_labels import FX, by_map, ctx_of, fake_rows, run_day

RS = 'Overwatch Champions Series/2026/Asia/Stage 3/Korea/Regular Season'
OQ = 'Overwatch Champions Series/2026/Asia/Stage 3/Korea/Open Qualifier'
PO = 'Overwatch Champions Series/2026/Asia/Stage 3/Korea'


def oq(idx, time, t1, t2):
    """an open-qualifier match as data/lp writes it: no stream ('broadcast': {}), several at the same time"""
    return {'date': f'2026-10-23T{time}:00+09:00', 'team1': t1, 'team2': t2, 'competitionTitle': OQ, 'idx': idx,
            'broadcast': {}, 'maps': []}


# the 2026-08-29 open-qualifier day shape (data/lp owcs-2026-asia-stage-3-korea-open-qualifier.json) put next to 10-23
QUALIFIER = [oq(0, '15:00', 'RTplz', 'GiNi'), oq(1, '15:00', 'SHFSCDS', 'OOPS'), oq(5, '15:50', 'LIGNEUS', 'SHFSCDS'),
             oq(6, '16:20', 'SuperBad', 'New Era'), oq(11, '17:10', 'SuperBad', 'OOPS')]


def ctx_for(matches):
    ctx = ctx_of()
    ctx['schedule'] = AD.day_schedule(matches, FX['date'], ctx['aliases'])
    return ctx


# ---- matchKey ------------------------------------------------------------------------------------------------------

def test_maps_and_matches_carry_the_match_key(monkeypatch):
    res = run_day(monkeypatch)
    m = by_map(res)
    assert [m[k]['matchKey'] for k in ('01', '04', '07', '09')] == [f'{RS}#27', f'{RS}#28', f'{RS}#29', f'{RS}#29']
    assert {r['match']: r['matchKey'] for r in res['matches']} == {
        'Cheeseburger vs O2 Blast': f'{RS}#27', 'Team Falcons vs ZANSIDE GAMING': f'{RS}#28',
        'Crazy Raccoon vs SEIJI ESPORTS': f'{RS}#29'}
    assert m['04']['match'] == 'Team Falcons vs ZANSIDE GAMING'          # the label stays as it was


def test_unresolved_map_has_no_match_key(monkeypatch):
    ocr = copy.deepcopy(FX['ocr']); ocr[8]['header'].update(match=None, game=None)
    names = copy.deepcopy(FX['names']); names[ocr[8]['frame']][6] = None          # Soae alone, no header
    fake_rows(monkeypatch, names)
    res = AD.assemble(ocr, lambda e: None, [tuple(b) for b in FX['bans']], [], ctx_of(), [], 'unused')
    m09 = by_map(res)['09']
    assert m09['labelVerified'] is False and 'matchKey' not in m09


def test_schedule_without_idx_gives_no_key(monkeypatch):
    plain = [{k: v for k, v in s.items() if k != 'idx'} for s in FX['schedule']]
    res = run_day(monkeypatch, ctx=ctx_for(plain))
    assert not any('matchKey' in x for x in res['maps']) and not any('matchKey' in r for r in res['matches'])


def test_same_day_rematch_stays_two_matches(monkeypatch):
    # playoff day: CB beats O2 in the upper final (match 1), O2 comes back through the lower final (match 2, FLC-ZAN
    # stands in) and they meet again in the grand final (match 3): same label twice, two match keys
    sched = copy.deepcopy(FX['schedule'])
    for i, s in enumerate(sched): s.update(competitionTitle=PO, idx=10 + i)
    sched[2].update(team1='O2 Blast', team2='Cheeseburger')
    bans = copy.deepcopy(FX['bans'])
    for b in bans[6:]: b[1]['teams'] = ['O2 Blast', 'Cheeseburger']
    names = copy.deepcopy(FX['names'])
    for e in FX['ocr'][6:]: names[e['frame']] = [None] * 10
    fake_rows(monkeypatch, names)
    res = AD.assemble(FX['ocr'], lambda e: None, [tuple(b) for b in bans], [], ctx_for(sched), [], 'unused')
    m = by_map(res)
    assert [(m[k]['match'], m[k]['matchKey'], m[k]['labelVerified']) for k in ('01', '07', '09')] == [
        ('Cheeseburger vs O2 Blast', f'{PO}#10', True), ('O2 Blast vs Cheeseburger', f'{PO}#12', True),
        ('O2 Blast vs Cheeseburger', f'{PO}#12', True)]
    assert sorted(r['matchKey'] for r in res['matches']) == [f'{PO}#10', f'{PO}#11', f'{PO}#12']


def test_playoff_slot_key_uses_the_page_title(tmp_path):
    for rel, data in (('data/aliases.json', FX['aliases']), ('data/manual/handle-aliases.json', FX['handleAliases']),
                      ('data/manual/players.json', FX['players']), ('data/site/matches.json', [])):
        p = tmp_path / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data), encoding='utf-8')
    page = {'title': PO, 'matches': [
        {'competition': PO, 'idx': 6, 'date': '2026-10-23T00:00:00+09:00', 'team1': '', 'team2': '', 'bestof': 5,
         'broadcast': {'afreeca': 'owesports'}},
        {'competition': PO, 'idx': 0, 'date': '2026-10-23T00:00:00+09:00', 'team1': '', 'team2': '',
         'broadcast': {'afreeca': 'owesports'}}]}
    (tmp_path / 'data/lp').mkdir()
    (tmp_path / 'data/lp/owcs-2026-asia-stage-3-korea.json').write_text(json.dumps(page), encoding='utf-8')
    sched = AD.load_context(FX['date'], str(tmp_path))['schedule']
    assert [m['key'] for m in sched] == [f'{PO}#0', f'{PO}#6']          # untimed: Liquipedia (idx) order


# ---- header numbers on a day with a second Korea page (RA-19) ------------------------------------------------------

def test_data_lp_never_has_two_korea_pages_on_one_day():
    """the assumption behind number_matches, checked on the stage pages in the repo: open qualifiers and relegations
    have their own days and no stream; when a day does have both, number_matches counts the streamed page only"""
    lp = os.path.join(os.path.dirname(HERE), 'data', 'lp')
    pages, side = {}, set()
    for f in os.listdir(lp):
        if not f.endswith('.json') or f.startswith('_'): continue
        with open(os.path.join(lp, f), encoding='utf-8') as fh: d = json.load(fh)
        if '/Korea' not in d.get('title', ''): continue
        for m in d['matches']:
            if m.get('date'): pages.setdefault(m['date'][:10], set()).add(d['title'])
            if d['title'].endswith(('Open Qualifier', 'Relegation')): side.add(bool(m.get('broadcast')))
    assert pages and all(len(t) == 1 for t in pages.values())
    assert side == {False}


def test_qualifier_page_does_not_shift_the_header_numbers(monkeypatch):
    m = by_map(run_day(monkeypatch, ctx=ctx_for(QUALIFIER + FX['schedule'])))
    got = [(m[k]['match'], m[k]['matchNo'], m[k]['game'], m[k]['labelVerified']) for k in ('01', '02', '07', '09')]
    assert got == [('Cheeseburger vs O2 Blast', 1, 1, True), ('Cheeseburger vs O2 Blast', 1, 2, True),
                   ('Crazy Raccoon vs SEIJI ESPORTS', 3, 1, True), ('Crazy Raccoon vs SEIJI ESPORTS', 3, 3, True)]
    assert not any(i.startswith('match from') for i in m['02']['labelIssues'])        # by the header, not a fallback


def test_qualifier_page_is_not_a_time_guess(monkeypatch):
    # m04: stale 'MATCH 1' header, no ban screen, Irony (ZAN) -> time guess. SuperBad-OOPS (17:10, not on air)
    # must not be 'the last match started before 18:52'
    bans = [b for b in FX['bans'] if b[1]['teams'][0] != 'Team Falcons']
    m04 = by_map(run_day(monkeypatch, bans=bans, ctx=ctx_for(QUALIFIER + FX['schedule'])))['04']
    assert (m04['match'], m04['matchNo']) == ('Team Falcons vs ZANSIDE GAMING', 2)
    assert 'match from schedule time' in m04['labelIssues']


def test_without_the_fix_the_header_would_point_at_the_qualifier():
    sched = AD.day_schedule(QUALIFIER + FX['schedule'], FX['date'], ctx_of()['aliases'])
    numbered = AD.number_matches([dict(s) for s in sched])
    assert [s['no'] for s in numbered] == [None] * 4 + [1, None, 2, 3]       # OQ 17:10 between matches 1 and 2
    assert (sched[0]['team1'], sched[0]['page']) == ('SEIJI ESPORTS', OQ)        # time order alone: match 1 = OQ (RTplz)


def test_ban_screen_still_finds_a_streamed_qualifier_match(monkeypatch):
    # a qualifier match the broadcast did show has no header number: its ban screens still place its maps
    q = [dict(QUALIFIER[0], team1='Cheeseburger', team2='O2 Blast')]
    rest = [s for s in FX['schedule'] if s['team1'] != 'Cheeseburger']
    m02 = by_map(run_day(monkeypatch, ctx=ctx_for(q + rest)))['02']
    assert (m02['match'], m02['matchKey']) == ('Cheeseburger vs O2 Blast', f'{OQ}#0')
    assert 'match from ban screen' in m02['labelIssues']


def test_numbering_counts_everything_without_stream_information():
    one_page_no_stream = [dict(q, broadcast={}) for q in QUALIFIER]
    assert [s['no'] for s in AD.number_matches(AD.day_schedule(one_page_no_stream, FX['date'], {}))] == [1, 2, 3, 4, 5]
    no_field = [{k: v for k, v in s.items() if k != 'broadcast'} for s in FX['schedule']]
    assert [s['no'] for s in AD.number_matches(AD.day_schedule(no_field, FX['date'], {}))] == [1, 2, 3]
    one_unstreamed = copy.deepcopy(FX['schedule']); one_unstreamed[1]['broadcast'] = {}   # 2024 stage 1: one '{}'
    assert [s['no'] for s in AD.number_matches(AD.day_schedule(one_unstreamed, FX['date'], {}))] == [1, 2, 3]


# ---- dates without a start time (N-01) -----------------------------------------------------------------------------

def test_date_only_matches_are_untimed_on_their_kst_date():
    """00:00 UTC (collector parseDate without a zone) and 00:00 KST are "no time yet": timed False, start on the
    weekday's usual first-match time in KST (10-25 is a Sunday: 15:00); a real time stays timed"""
    rs = lambda date, idx: {'date': date, 'team1': 'A', 'team2': 'B', 'competitionTitle': RS, 'idx': idx}
    day = [rs('2026-10-25T00:00:00+00:00', 0), rs('2026-10-25T00:00:00+09:00', 1), rs('2026-10-25T17:00:00+09:00', 2)]
    sched = AD.day_schedule(day, '2026-10-25', {})
    guess = int(AD.datetime(2026, 10, 25, 15, tzinfo=AD.KST).timestamp())
    real = int(AD.datetime(2026, 10, 25, 17, tzinfo=AD.KST).timestamp())
    assert [(s['idx'], s['timed'], s['start']) for s in sched] == [(0, False, guess), (1, False, guess), (2, True, real)]
    assert AD.day_schedule(day, '2026-10-24', {}) == []
