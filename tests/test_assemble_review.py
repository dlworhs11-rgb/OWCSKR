"""assemble_day decision rules against the ways the broadcast and the schedule really go wrong (review of P1-05/06/07):
stale headers, noisy ban screens, missing start times, TBD slots, out-of-order and repeated matches, missed maps."""
import copy, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
import assemble_day as AD
from test_assemble_labels import FX, by_map, ctx_of, run_day


def ocr_copy():
    return copy.deepcopy(FX['ocr'])


def bans_with(**changes):
    """FX bans with some screens changed: changes = {'m05': {'score': [129, 54]}} (key = the map the screen is before)"""
    out = copy.deepcopy(FX['bans'])
    for mm, ch in changes.items():
        i = int(mm[1:]) - 1
        if ch is None: out[i] = None
        else: out[i][1].update(ch)
    return [b for b in out if b]


def ctx_with_schedule(edit):
    ctx = ctx_of()
    fx = copy.deepcopy(FX['schedule']); edit(fx)
    ctx['schedule'] = AD.day_schedule(fx, FX['date'], ctx['aliases'])
    return ctx


# ---- stale header graphic (10-23 m04-m06) ------------------------------------------------------------------------

def test_stale_header_map_name_loses_to_the_ban_screen(monkeypatch):
    m = by_map(run_day(monkeypatch))
    assert [m[k]['map'] for k in ('04', '05', '06')] == ['Nepal', 'Aatlis', 'Colosseo']      # Liquipedia: the same
    assert 'map: header New Junk City, ban screen Aatlis' in m['05']['labelIssues']


def test_trusted_header_keeps_its_map_name(monkeypatch):
    m02 = by_map(run_day(monkeypatch, bans=bans_with(m02={'map': 'Busan'})))['02']
    assert m02['map'] == 'New Junk City' and 'map: header New Junk City, ban screen Busan' in m02['labelIssues']


def test_unknown_ban_map_text_is_not_used(monkeypatch):
    ocr = ocr_copy(); ocr[4]['header']['map'] = '?'
    m05 = by_map(run_day(monkeypatch, ocr=ocr, bans=bans_with(m05={'map': 'Aat1is |', 'mapKnown': False})))['05']
    assert m05['map'] == '?'                       # no header map, no known ban map, Liquipedia has no names here


def test_rejected_header_game_is_used_only_as_the_next_game(monkeypatch):
    bans = bans_with(m04=None, m05=None, m06=None)
    ocr = ocr_copy(); ocr[3]['header']['game'] = 3                       # a stale 'MATCH 1 GAME 3' over FLC-ZAN game 1
    m04 = by_map(run_day(monkeypatch, ocr=ocr, bans=bans))['04']
    assert (m04['matchNo'], m04['game'], m04['labelVerified']) == (2, 1, False)
    assert 'game from map order only' in m04['labelIssues']


# ---- noisy ban screens -------------------------------------------------------------------------------------------

def test_unreadable_ban_team_leaves_the_header_alone(monkeypatch):
    m01 = by_map(run_day(monkeypatch))['01']               # m01 ban: left team read 'OEE SEBUARG BIR 4021'
    assert (m01['matchNo'], m01['game'], m01['labelVerified']) == (1, 1, True) and 'bans' not in m01


def test_ban_team_snapped_to_an_unscheduled_team_does_not_veto_the_header(monkeypatch):
    m02 = by_map(run_day(monkeypatch, bans=bans_with(m02={'teams': ['Cheeseburger', 'T1']})))['02']
    assert (m02['matchNo'], m02['game'], m02['labelVerified']) == (1, 2, True)
    assert 'ban screen Cheeseburger vs T1 not on the schedule (ignored)' in m02['labelIssues']


def test_ban_screen_of_another_scheduled_match_still_vetoes_the_header(monkeypatch):
    m02 = by_map(run_day(monkeypatch, bans=bans_with(m02={'teams': ['Crazy Raccoon', 'SEIJI ESPORTS']})))['02']
    assert m02['labelVerified'] is False


def test_noise_series_score_neither_numbers_the_game_nor_rejects_a_good_header(monkeypatch):
    m = by_map(run_day(monkeypatch, bans=bans_with(m02={'score': [130, 80]}, m05={'score': [3, 1]})))
    assert (m['02']['game'], m['02']['labelVerified']) == (2, True) and 'seriesBefore' not in m['02']
    # m05: header rejected, '3-1' is a possible score but skips games 2-4 after game 1
    assert (m['05']['game'], m['05']['labelVerified']) == (5, False)
    assert 'ban-screen score gives game 5, game 2 not seen' in m['05']['labelIssues']
    m = by_map(run_day(monkeypatch, bans=bans_with(m06={'score': [0, 0]})))
    assert (m['06']['game'], m['06']['labelVerified']) == (1, False)
    assert 'ban-screen score gives game 1 again' in m['06']['labelIssues']


def test_missed_ban_screen_of_game_2_uses_map_order_untrusted(monkeypatch):
    m05 = by_map(run_day(monkeypatch, bans=bans_with(m05=None)))['05']
    assert (m05['matchNo'], m05['game']) == (2, 2)
    assert m05['labelVerified'] is True and 'game from header' in m05['labelIssues']   # stale header 'GAME 2' = next game


# ---- a misread known name of a third team (RA-14; 10-23 m09 'Soae' of Poker Face in CR vs SEIJI) -------------------

def run_m09(monkeypatch, row_names=None, header=None, bans=None):
    """10-23 with m09's names (index -> name, None = unknown) and header changed"""
    ocr = ocr_copy()
    if header is not None: ocr[8]['header'].update(header)
    names = copy.deepcopy(FX['names'])
    for r, n in (row_names or {}).items(): names[ocr[8]['frame']][r] = n
    import test_assemble_labels as T
    T.fake_rows(monkeypatch, names)
    res = AD.assemble(ocr, lambda e: None, [tuple(b) for b in (FX['bans'] if bans is None else bans)], [], ctx_of(), [],
                      'unused')
    return by_map(res)['09']


def test_two_names_of_a_third_team_still_veto(monkeypatch):
    m09 = run_m09(monkeypatch, {3: 'SORI'})                     # Soae + SORI (both Poker Face) in the upper panel
    assert m09['labelVerified'] is False and 'match unresolved' in m09['labelIssues']
    assert 'known players of Poker Face in match 3 (Crazy Raccoon vs SEIJI ESPORTS)' in m09['labelIssues']


def test_two_third_teams_one_name_each_still_veto(monkeypatch):
    m09 = run_m09(monkeypatch, {6: 'Irony'})                    # Soae (Poker Face) up, Irony (ZAN) down, LIP gone
    assert m09['labelVerified'] is False


def test_lone_third_team_name_loses_to_header_and_ban_screen(monkeypatch):
    m09 = run_m09(monkeypatch, {6: None})                       # LIP not read: Soae is the only known name
    assert (m09['match'], m09['game'], m09['labelVerified']) == ('Crazy Raccoon vs SEIJI ESPORTS', 3, True)
    assert list(m09['teams']) == ['Crazy Raccoon', 'SEIJI ESPORTS']   # no known player left: ban-screen order
    assert 'panel sides from ban-screen order (no known player)' in m09['labelIssues']


def test_lone_third_team_name_against_the_header_alone_vetoes(monkeypatch):
    bans = [b for b in FX['bans'] if b[1].get('map') != 'Aatlis' or b[1]['teams'][0] != 'Crazy Raccoon']
    m09 = run_m09(monkeypatch, {6: None}, bans=bans)            # header only: it may be a stale graphic (m04-m06)
    assert m09['labelVerified'] is False and 'match unresolved' in m09['labelIssues']


def test_ban_screen_and_a_player_of_the_pair_also_overrule_one_name(monkeypatch):
    m09 = run_m09(monkeypatch, header={'match': None, 'game': None})   # header unread; ban screen + LIP vs Soae
    assert (m09['matchNo'], m09['game'], m09['labelVerified']) == (3, 3, True)
    assert 'match from ban screen' in m09['labelIssues']
    assert [r['name'] for r in m09['teams']['SEIJI ESPORTS']] == [None] * 5


# ---- schedule without times, ties, early header ------------------------------------------------------------------

def midnight(fx):
    for m in fx: m['date'] = m['date'][:10] + 'T00:00:00+00:00'      # Liquipedia before the times are posted


def test_no_start_times_header_and_ban_still_work(monkeypatch):
    ctx = ctx_with_schedule(midnight)
    m = by_map(run_day(monkeypatch, ctx=ctx))
    assert [(m[k]['matchNo'], m[k]['game'], m[k]['labelVerified']) for k in ('01', '04', '07')] == [(1, 1, True), (2, 1, True), (3, 1, True)]


def test_no_start_times_means_no_time_guess(monkeypatch):
    bans = [b for b in FX['bans'] if b[1]['teams'][0] != 'Team Falcons']
    m04 = by_map(run_day(monkeypatch, bans=bans, ctx=ctx_with_schedule(midnight)))['04']
    assert m04['labelVerified'] is False and 'no start times on the schedule' in m04['labelIssues']


def test_tied_start_times_give_no_time_guess():
    sched = [{'team1': 'A', 'team2': 'B', 'start': 100, 'timed': True}, {'team1': 'C', 'team2': 'D', 'start': 100, 'timed': True}]
    assert AD.match_by_time(500, sched)[0] is None


def test_header_of_a_match_that_has_not_started_is_rejected(monkeypatch):
    ocr = ocr_copy(); ocr[0]['header']['match'] = 3                      # 17:25 map read as MATCH 3 (20:00)
    m01 = by_map(run_day(monkeypatch, ocr=ocr, bans=bans_with(m01=None)))['01']
    assert m01['matchNo'] == 1 and any(i.startswith('header match 3 starts 20:00') for i in m01['labelIssues'])


def test_time_guess_does_not_block_the_next_header(monkeypatch):
    # match 1 runs past the 17:30 start of match 2. m02 (17:48) has no header, ban screen or known player: the time
    # guess says match 2. m03 then reads 'MATCH 1' without a ban screen: the guess must not reject it as going back.
    def early2(fx): fx[1]['date'] = fx[1]['date'][:11] + '17:30:00+09:00'
    ocr = ocr_copy(); ocr[1]['header'].update(match=None, game=None)
    names = copy.deepcopy(FX['names']); names[ocr[1]['frame']] = [None] * 10
    import test_assemble_labels as T
    T.fake_rows(monkeypatch, names)
    res = AD.assemble(ocr, lambda e: None, [tuple(b) for b in bans_with(m02=None, m03=None)], [],
                      ctx_with_schedule(early2), [], 'unused')
    m = by_map(res)
    assert m['02']['matchNo'] == 2 and m['02']['labelVerified'] is False          # the guess, not published
    assert (m['03']['matchNo'], m['03']['game'], m['03']['labelVerified']) == (1, 3, True)


def test_guessed_game_does_not_make_a_trusted_one_a_duplicate(monkeypatch):
    # m03 without header, ban screen or known player lands in match 2 with a guessed game 1; m04 is FLC-ZAN game 1
    def early2(fx): fx[1]['date'] = fx[1]['date'][:11] + '17:50:00+09:00'
    ocr = ocr_copy(); ocr[2]['header'].update(match=None, game=None)
    names = copy.deepcopy(FX['names']); names[ocr[2]['frame']] = [None] * 10
    import test_assemble_labels as T
    T.fake_rows(monkeypatch, names)
    res = AD.assemble(ocr, lambda e: None, [tuple(b) for b in bans_with(m03=None)], [], ctx_with_schedule(early2), [], 'unused')
    m = by_map(res)
    assert (m['03']['matchNo'], m['03']['labelVerified']) == (2, False)
    assert (m['04']['matchNo'], m['04']['game'], m['04']['labelVerified']) == (2, 1, True)


# ---- TBD slots, out of order, rematch ----------------------------------------------------------------------------

def test_tbd_slot_is_filled_from_the_ban_screen(monkeypatch):
    def tbd(fx): fx[1]['team2'] = 'TBD'
    m = by_map(run_day(monkeypatch, ctx=ctx_with_schedule(tbd)))
    assert (m['04']['match'], m['04']['matchNo'], m['04']['labelVerified']) == ('Team Falcons vs ZANSIDE GAMING', 2, True)


def test_tbd_slot_without_ban_screen_or_known_player_stays_unverified(monkeypatch):
    def tbd(fx): fx[2]['team1'] = 'TBD'
    bans = [b for b in FX['bans'] if b[1]['teams'][0] != 'Crazy Raccoon']
    m07 = by_map(run_day(monkeypatch, bans=bans, ctx=ctx_with_schedule(tbd)))['07']
    assert m07['labelVerified'] is False


def test_matches_played_out_of_order_follow_the_ban_screen(monkeypatch):
    def swap(fx): fx[1], fx[2] = dict(fx[2], date=fx[1]['date']), dict(fx[1], date=fx[2]['date'])   # schedule: CR-SEIJI 2nd
    m = by_map(run_day(monkeypatch, ctx=ctx_with_schedule(swap)))
    assert [(m[k]['match'], m[k]['labelVerified']) for k in ('04', '07')] == [
        ('Team Falcons vs ZANSIDE GAMING', True), ('Crazy Raccoon vs SEIJI ESPORTS', True)]


def test_rematch_on_the_same_day_goes_to_the_later_match():
    sched = [{'team1': 'A', 'team2': 'B'}, {'team1': 'C', 'team2': 'D'}, {'team1': 'B', 'team2': 'A'}]
    assert AD.ban_match(['A', 'B'], sched, None)[0] == 0
    assert AD.ban_match(['A', 'B'], sched, 1)[0] == 2


# ---- winners -----------------------------------------------------------------------------------------------------

def test_last_map_winner_only_when_it_ends_the_series(monkeypatch):
    res = run_day(monkeypatch)
    m = by_map(res)
    assert (m['03'].get('winner'), m['03'].get('winnerSource')) == ('Cheeseburger', 'match end (leader)')   # 2-0 -> 3-0
    assert (m['08'].get('winner'), m['08'].get('winnerSource')) == ('Crazy Raccoon', 'series score')     # m09 ban 2-0
    assert (m['09'].get('winner'), m['09'].get('winnerSource')) == ('Crazy Raccoon', 'match end (leader)')  # LP: 3-0
    assert (m['01'].get('winner'), m['01'].get('winnerSource')) == ('Cheeseburger', 'series score')   # game 1 = 0-0
    wins = {r['match']: r['mapWins'] for r in res['matches']}
    assert wins['Cheeseburger vs O2 Blast'] == {'Cheeseburger': 3}


def test_unresolved_last_map_gives_the_leader_no_win(monkeypatch):
    ocr = ocr_copy(); ocr[8]['header'].update(match=None, game=None)             # m09 header unread
    names = copy.deepcopy(FX['names']); names[ocr[8]['frame']][6] = None             # LIP not read: Soae alone
    import test_assemble_labels as T
    T.fake_rows(monkeypatch, names)
    res = AD.assemble(ocr, lambda e: None, [tuple(b) for b in FX['bans']], [], ctx_of(), [], 'unused')
    m = by_map(res)
    assert m['09']['labelVerified'] is False and 'match unresolved' in m['09']['labelIssues']
    assert m['08'].get('winner') is None              # 1-0 before CR-SEIJI's last resolved map: game 3 was not resolved


def test_missed_last_map_does_not_hand_its_winner_to_the_previous_one(monkeypatch):
    ocr = [e for e in FX['ocr'] if e['map'] != '03']                    # CB-O2 game 3 table not captured
    m02 = by_map(run_day(monkeypatch, ocr=ocr))['02']
    assert m02.get('winner') is None                  # 1-0 leader is not 'the winner of the last map'


def test_last_map_rule_by_series_length():
    assert AD.last_map_winner({'A': 2, 'B': 1}, None, 3) == ('A', 'match end (leader)')
    assert AD.last_map_winner({'A': 2, 'B': 1}, None, 4) == (None, None)        # BO7: 3-1, not over
    assert AD.last_map_winner({'A': 2, 'B': 2}, {'team': 'B'}, 3) == ('B', 'match end (POTM team)')
    assert AD.last_map_winner({'A': 1, 'B': 1}, {'team': 'B'}, 3) == (None, None)
    assert AD.last_map_winner({'A': 2, 'B': 0}, None, None) == (None, None)     # best-of unknown
    assert AD.last_map_winner({'A': 3, 'B': 0}, None, None) == ('A', 'match end (leader)')


def test_series_need_from_schedule():
    assert AD.series_need({'bestof': 7}) == 4
    assert AD.series_need({'competitionTitle': 'x/Korea/Regular Season'}) == 3
    assert AD.series_need({'competitionTitle': 'Overwatch Champions Series/2026/Asia/Stage 1/Korea'}) is None


# ---- unknown names and POTM --------------------------------------------------------------------------------------

def test_unknown_ids_do_not_move_when_a_name_is_learned(monkeypatch):
    before = {(u['map'], u['row']): u['id'] for u in run_day(monkeypatch)['unknownNames']}
    names = copy.deepcopy(FX['names']); names[FX['ocr'][0]['frame']][0] = 'Profit'      # m01 row 0 now known
    import test_assemble_labels as T
    T.fake_rows(monkeypatch, names)
    res = AD.assemble(FX['ocr'], lambda e: None, [tuple(b) for b in FX['bans']], [], ctx_of(), [], 'unused')
    after = {(u['map'], u['row']): u['id'] for u in res['unknownNames']}
    assert ('01', 0) not in after and all(before[k] == v for k, v in after.items())
    assert before[('04', 7)] == '?47'


def test_unknown_id_for_repeated_map_numbers():
    unknown = [{'id': '?46'}]
    assert AD.unknown_id('04', 6, unknown) == '?1046' and AD.unknown_id('x', 0, []) == '?1'


def test_zero_elims_frame_is_not_a_potm_reading():
    assert AD.potm_numbers([{'elims': 0, 'deaths': 0, 'ed': 0.0}]) is None


# ---- playoff days: TBD matches from the stage page (RI-06) -------------------------------------------------------

def write(root, rel, data):
    p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data), encoding='utf-8')


def test_playoff_day_tbd_matches_come_from_the_stage_page(tmp_path, monkeypatch):
    for rel, data in (('data/aliases.json', FX['aliases']), ('data/manual/handle-aliases.json', FX['handleAliases']),
                      ('data/manual/players.json', FX['players'])):
        write(tmp_path, rel, data)
    title = 'Overwatch Champions Series/2026/Asia/Stage 3/Korea'
    # matches.json has the decided first match only; the stage page has the two later ones, teams TBD, no times
    write(tmp_path, 'data/site/matches.json', [dict(FX['schedule'][0], competitionTitle=title)])
    page = [dict(FX['schedule'][0], competition=title, bestof=5),
            {'competition': title, 'date': '2026-10-23T00:00:00+09:00', 'team1': '', 'team2': ''},
            {'competition': title, 'date': '2026-10-23T00:00:00+09:00', 'team1': 'TBD', 'team2': ''},
            {'competition': title, 'date': '2026-10-24T00:00:00+09:00', 'team1': '', 'team2': ''}]
    write(tmp_path, 'data/lp/owcs-2026-asia-stage-3-korea.json', {'matches': page})
    ctx = AD.load_context(FX['date'], str(tmp_path))
    assert [(m['team1'], m['team2'], m['need']) for m in ctx['schedule']] == [
        (None, None, 3), ('TBD', None, 3), ('Cheeseburger', 'O2 Blast', None)]          # bestof carried over
    ctx['schedule'] = sorted(ctx['schedule'], key=lambda m: AD.is_slot(m['team1']))      # CB-O2 first, as on air
    res = run_day(monkeypatch, ctx=ctx)
    m = by_map(res)
    assert [(m[k]['match'], m[k]['matchNo'], m[k]['game'], m[k]['labelVerified']) for k in ('01', '04', '06', '07', '08')] == [
        ('Cheeseburger vs O2 Blast', 1, 1, True), ('Team Falcons vs ZANSIDE GAMING', 2, 1, True),
        ('Team Falcons vs ZANSIDE GAMING', 2, 3, True), ('Crazy Raccoon vs SEIJI ESPORTS', 3, 1, True),
        ('Crazy Raccoon vs SEIJI ESPORTS', 3, 2, True)]
    assert 'ban screen Team Falcons vs ZANSIDE GAMING fills a TBD match' in m['04']['labelIssues']


def test_header_pointing_at_a_tbd_match_is_not_enough(monkeypatch):
    def tbd(fx): fx[0]['team1'] = fx[0]['team2'] = ''                  # match 1 still TBD: m01 header 'MATCH 1'
    m01 = by_map(run_day(monkeypatch, ctx=ctx_with_schedule(tbd)))['01']   # its ban screen is unreadable
    assert m01['labelVerified'] is False and 'header match 1 is TBD on the schedule' in m01['labelIssues']


def test_tbd_match_without_ban_screen_is_not_verified(monkeypatch):
    def tbd(fx): fx[1]['team1'] = fx[1]['team2'] = ''
    bans = [b for b in FX['bans'] if b[1]['teams'][0] != 'Team Falcons']
    m04 = by_map(run_day(monkeypatch, bans=bans, ctx=ctx_with_schedule(tbd)))['04']
    assert m04['labelVerified'] is False


# ---- one assembly at a time, whole files (RI-16) -----------------------------------------------------------------

def test_day_lock_waits_then_times_out(tmp_path):
    (tmp_path / '.assemble.lock').write_text('')
    try:
        with AD.day_lock(str(tmp_path), wait=0, sleep=lambda s: None): pass
        raise AssertionError('lock taken twice')
    except TimeoutError:
        pass
    old = time.time() - 4000; os.utime(tmp_path / '.assemble.lock', (old, old))          # left by a killed run
    with AD.day_lock(str(tmp_path), wait=0):
        assert (tmp_path / '.assemble.lock').exists()
    assert not (tmp_path / '.assemble.lock').exists()


def test_write_result_replaces_the_file_whole(tmp_path, monkeypatch):
    res = run_day(monkeypatch)
    (tmp_path / 'mapstats.json').write_text('{"old": 1}')
    AD.write_result(FX['date'], str(tmp_path), res)
    assert json.loads((tmp_path / 'mapstats.json').read_text(encoding='utf-8'))['date'] == FX['date']
    assert [p.name for p in tmp_path.iterdir()] == ['mapstats.json']


def test_unverified_maps_carry_no_winner(monkeypatch):
    m = by_map(run_day(monkeypatch, bans=bans_with(m06={'score': [0, 0]})))      # m06 game untrusted
    assert m['06']['labelVerified'] is False and 'winner' not in m['06']
    assert all('winner' not in x for x in m.values() if not x['labelVerified'])
