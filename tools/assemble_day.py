"""Turn one capture day (data/live/<date>/ocr.json + frames) into a mapstats file.

usage: python -I tools/assemble_day.py YYYY-MM-DD

- player names: nearest crop in data/name_lib; unknown names -> name None + unknownId '?k' (k = map * 10 + row, stable
  across runs), feature and raw crop saved to data/live/<date>/unknown/<k>_m<map>_r<row>.feat.png / .raw.png
  (label them with tools/label_unknown.py)
- team of each panel: roster overlap with data/manual/players.json (community sheet)
- match: the header number ("MATCH 2") only when it agrees with time order, the ban screen before the map and the
  known players' teams; otherwise the ban-screen teams, then the scheduled start times (Korean matches of the day in
  data/site/matches.json). A map whose match, game or panel sides cannot be trusted gets labelVerified False.
- writes data/live/<date>/mapstats.json (tools/publish_day.py uploads the verified maps)
"""
import contextlib, glob, json, os, re, sys, time
from collections import Counter
from datetime import datetime, timedelta, timezone

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import names as NM

ROOT = os.path.dirname(TOOLS)
K = ['e', 'a', 'd', 'dmg', 'heal', 'mit']
BAN_WINDOW = 3 * 3600        # a ban screen older than this is not this map's
POTM_WINDOW = 1800           # the POTM card follows the last map of a match within this
ED_TOL = 0.06                # |elims/deaths - E/D| of a fully drawn POTM card (E/D is shown rounded)
MIN_KNOWN = 0.5              # share of the 10 names read below this -> labelIssues entry
EARLY = 3600                 # a map ends at most this long before its match's scheduled start (times are estimates)
MAX_SERIES = 3               # a side's series score before a map (BO7: first to 4)
KST = timezone(timedelta(hours=9))
COPY_FIELDS = ('framesAgree', 'verifiedFields', 'aVerified')


# ---- context: rosters, team names, the day's schedule ---------------------------------------------------------

def is_slot(team: str | None) -> bool:
    """an undecided bracket slot: Liquipedia writes 'TBD' or nothing until the team is known"""
    return not team or team.strip().upper() == 'TBD'


def series_need(m: dict) -> int | None:
    """maps to win the series; None when Liquipedia gives no best-of outside the BO5 regular season / groups"""
    if m.get('bestof'): return int(m['bestof']) // 2 + 1
    title = m.get('competitionTitle', '')
    return 3 if 'Regular Season' in title or 'Group Stage' in title else None


def day_schedule(matches: list, date: str, aliases: dict) -> list:
    """Korean matches of the day in time order: [{'team1', 'team2', 'start' (unix s), 'timed', 'need', 'maps'}].
    timed False = Liquipedia has no start time yet (written as 00:00)."""
    out = []
    for m in matches:
        if not (m.get('date') or '').startswith(date) or '/Korea' not in m.get('competitionTitle', ''): continue
        dt = datetime.fromisoformat(m['date'])
        out.append({'team1': NM.canon_team(m['team1'], aliases), 'team2': NM.canon_team(m['team2'], aliases),
                    'start': int(dt.timestamp()), 'timed': (dt.hour, dt.minute) != (0, 0), 'need': series_need(m),
                    'maps': m.get('maps') or []})
    return sorted(out, key=lambda m: m['start'])


def known_teams(aliases: dict, sched: list, rosters: dict) -> set:
    """team names a ban screen may show: aliases, rosters and today's scheduled teams (a new team may have no alias)"""
    teams = set(aliases.values()) | set(rosters)
    return teams | {t for m in sched for t in (m['team1'], m['team2']) if not is_slot(t)}


def playoff_slots(date: str, root: str) -> list:
    """the day's matches with a TBD team from the stage pages (data/lp/*-korea.json), in the shape of
    data/site/matches.json: that file drops them, so a playoff match decided earlier the same day had no schedule
    entry (same source as schedule_today.playoff_matches; 'bestof' is written on a round's first match only)"""
    lp_dir, out = os.path.join(root, 'data', 'lp'), []
    if not os.path.isdir(lp_dir): return out
    for f in sorted(os.listdir(lp_dir)):
        if not f.endswith('-korea.json'): continue
        bo = None
        for m in NM.load_json(os.path.join('data', 'lp', f), root).get('matches', []):
            bo = m.get('bestof') or bo
            if not (m.get('date') or '').startswith(date) or not (is_slot(m.get('team1')) or is_slot(m.get('team2'))): continue
            out.append(dict(m, bestof=bo, competitionTitle=m.get('competitionTitle') or m.get('competition', '')))
    return out


def load_context(date: str, root: str | None = None) -> dict:
    root = root or ROOT
    aliases, h_aliases = NM.team_aliases(root), NM.handle_aliases(root)
    try:
        matches = NM.load_json('data/site/matches.json', root)
    except FileNotFoundError:
        matches = []
    sched = day_schedule(matches + playoff_slots(date, root), date, aliases)
    rosters = NM.build_rosters(NM.load_json('data/manual/players.json', root), aliases, h_aliases)
    return {'aliases': aliases, 'h': h_aliases, 'teams': known_teams(aliases, sched, rosters), 'schedule': sched,
            'rosters': rosters}


# ---- match / game / panel sides (pure) ---------------------------------------------------------------------------

def panel_team(names: list, ctx: dict) -> str | None:
    """roster team most of the panel's known names belong to; None when none is known or two teams tie"""
    votes = Counter(t for t in (NM.team_of(n, ctx['rosters'], ctx['h']) for n in names if n) if t)
    if not votes: return None
    top = votes.most_common(2)
    return top[0][0] if len(top) == 1 or top[0][1] > top[1][1] else None


def ban_before(ts: int, prev_ts: int | None, bans: list):
    """(ts, ban) of the last ban screen after the previous map and before this one, or None"""
    lo = max(prev_ts or 0, ts - BAN_WINDOW)
    hits = [(bt, b) for bt, b in bans if lo < bt < ts]
    return hits[-1] if hits else None


def ban_teams(ban: dict | None, ctx: dict) -> list | None:
    """the two teams of a ban screen when both read as known team names"""
    if not ban: return None
    ts = [NM.canon_team(t, ctx['aliases']) for t in ban.get('teams') or []]
    return ts if len(ts) == 2 and ts[0] != ts[1] and all(t in ctx['teams'] for t in ts) else None


def fill_slots(pair: list, teams) -> list | None:
    """the scheduled pair with its undecided slots taken by those of `teams` not in it; None when they do not fit"""
    extra = [t for t in dict.fromkeys(teams) if t and t not in pair]
    if len(extra) > sum(map(is_slot, pair)): return None
    it = iter(extra)
    return [next(it, t) if is_slot(t) else t for t in pair]


def fits(m: dict, teams) -> bool:
    """two teams (of a ban screen) can be this scheduled match: the same pair, or the same once TBD slots are filled"""
    filled = fill_slots([m['team1'], m['team2']], teams)
    return filled is not None and set(filled) == set(teams)


def scheduled_pair(m: dict, rec: dict) -> list:
    """[team1, team2] of a scheduled match; a TBD slot takes the ban-screen team, else the known panel team"""
    pair = [m['team1'], m['team2']]
    if not any(map(is_slot, pair)): return pair
    if rec['banTeams'] and fits(m, rec['banTeams']): return fill_slots(pair, rec['banTeams'])
    return fill_slots(pair, [t for t in rec['panelTeams'] if t]) or pair


def outside_teams(rec: dict, pair: list) -> list:
    return sorted({t for t in rec['panelTeams'] if t} - set(pair))


def clock(ts: int) -> str:
    return datetime.fromtimestamp(ts, KST).strftime('%H:%M')


def header_issues(no: int, rec: dict, sched: list, prev_idx: int | None) -> list:
    """reasons not to trust the header's match number (empty = trust it)"""
    if not 1 <= no <= len(sched): return [f'header match {no} not on the schedule ({len(sched)} matches)']
    m = sched[no - 1]
    pair, out = scheduled_pair(m, rec), []
    if prev_idx is not None and no - 1 < prev_idx: out.append(f'header match {no} after match {prev_idx + 1}')
    if m['timed'] and m['start'] - rec['ts'] > EARLY:
        out.append(f"header match {no} starts {clock(m['start'])}, this map ended {clock(rec['ts'])}")
    if any(map(is_slot, pair)): out.append(f'header match {no} is TBD on the schedule')
    if rec['banTeams'] and set(rec['banTeams']) != set(pair):
        out.append(f"ban screen {' vs '.join(rec['banTeams'])} is not {pair[0]} vs {pair[1]}")
    if outside_teams(rec, pair):
        out.append(f"known players of {', '.join(outside_teams(rec, pair))} in match {no} ({pair[0]} vs {pair[1]})")
    return out


def match_by_time(ts: int, sched: list) -> tuple:
    """-> (index of the last match started before the map | None, issues); no guess from missing or tied times"""
    if not sched or not all(m['timed'] for m in sched): return None, ['no start times on the schedule']
    started = [i for i, m in enumerate(sched) if m['start'] <= ts]
    if not started: return None, ['no scheduled match started before this map']
    last = sched[started[-1]]['start']
    if sum(1 for m in sched if m['start'] == last) > 1: return None, [f'matches scheduled at the same time ({clock(last)})']
    return started[-1], []


def ban_match(bteams: list, sched: list, prev_idx: int | None, ts: int = 0) -> tuple:
    """-> (schedule index | None, issues): the scheduled match of the ban-screen teams; the same pair twice a day
    (a rematch) -> the first one not before the previous map's match. No such pair: the first TBD match that can
    be it (started by then when Liquipedia has times); label_maps then writes the pair into that slot."""
    exact = [i for i, m in enumerate(sched) if {m['team1'], m['team2']} == set(bteams)]
    later = [i for i in exact if prev_idx is None or i >= prev_idx]
    if exact: return (later or exact)[0], []
    cands = [i for i, m in enumerate(sched) if fits(m, bteams)]
    started = [i for i in cands if not sched[i]['timed'] or sched[i]['start'] - EARLY <= ts] or cands
    later = [i for i in started if prev_idx is None or i >= prev_idx]
    if not cands: return None, [f"ban screen {' vs '.join(bteams)} not on the schedule"]
    return (later or started)[0], [f"ban screen {' vs '.join(bteams)} fills a TBD match"]


def fallback_match(rec: dict, sched: list, prev_idx: int | None) -> tuple:
    """header dropped: the ban-screen teams (a broadcast may play matches out of order), else the schedule time"""
    if rec['banTeams']:
        idx, issues = ban_match(rec['banTeams'], sched, prev_idx, rec['ts'])
        if idx is not None and prev_idx is not None and idx < prev_idx:
            issues.append(f'ban screen gives match {idx + 1} after match {prev_idx + 1} (played out of order)')
        return idx, 'ban screen', issues
    idx, issues = match_by_time(rec['ts'], sched)
    if idx is not None and prev_idx is not None and idx < prev_idx:
        return None, 'schedule time', [f'schedule time gives match {idx + 1}, after match {prev_idx + 1}']
    return idx, 'schedule time', issues


def resolve_match(rec: dict, sched: list, prev_idx: int | None) -> tuple:
    """-> (schedule index | None, source 'header' | 'ban screen' | 'schedule time' | None, header state, issues);
    header state: 'ok', 'unread' (no or an ambiguous digit) or 'rejected' (read, but contradicted)"""
    no, issues = rec['header'].get('match'), []
    if no is None:
        issues.append('header match digit ambiguous' if rec['header'].get('matchAmbiguous') else 'header match not read')
    else:
        bad = header_issues(no, rec, sched, prev_idx)
        if not bad: return no - 1, 'header', 'ok', issues
        issues += bad
    state = 'unread' if no is None else 'rejected'
    idx, src, more = fallback_match(rec, sched, prev_idx)
    issues += more
    if idx is None: return None, None, state, issues
    pair = scheduled_pair(sched[idx], rec)
    if outside_teams(rec, pair):
        return None, None, state, issues + [f"known players of {', '.join(outside_teams(rec, pair))} in match {idx + 1} ({src})"]
    return idx, src, state, issues + [f'match from {src}']


def assign_panels(panel_teams: list, pair: list, bteams: list | None) -> tuple:
    """-> ([team of panel 0, team of panel 1], issues, trusted); pair = scheduled [team1, team2]"""
    t0, t1 = panel_teams
    if t0 and t1:
        if t0 == t1: return list(pair), [f'both panels look like {t0}'], False
        return [t0, t1], [], True
    if t0 or t1:
        other = [t for t in pair if t != (t0 or t1)][0]
        return ([t0, other] if t0 else [other, t1]), [], True
    if bteams and set(bteams) == set(pair):
        # ban screen left = upper table panel (10-23 m02/m03); to be confirmed on more frames
        return list(bteams), ['panel sides from ban-screen order (no known player)'], True
    return list(pair), ['panel sides unknown (no known player, no ban screen)'], False


def series_score(ban: dict | None) -> list | None:
    """the ban screen's series score when it is a possible one (each side 0..3, BO7 at most 3-3 before a map);
    the score bar can read as noise (a 10-23 reading of the same screens gave '130-80')"""
    score = (ban or {}).get('score') or []
    ok = len(score) == 2 and all(isinstance(s, int) and not isinstance(s, bool) and 0 <= s <= MAX_SERIES for s in score)
    return list(score) if ok else None


def resolve_game(rec: dict, state: str, prev_game: int) -> tuple:
    """-> (game, issues, trusted); state = header state of resolve_match, prev_game = last game of the same match"""
    hg = rec['header'].get('game')
    score = series_score(rec.get('ban'))
    by_score = sum(score) + 1 if score else None
    if state == 'ok' and hg:
        if by_score and by_score != hg:
            return hg, [f'header game {hg} but ban-screen score {score[0]}-{score[1]}'], False
        return hg, [], True
    if by_score:
        if by_score <= prev_game: return by_score, [f'ban-screen score gives game {by_score} again'], False
        if by_score > prev_game + 1:      # a misread score as often as a missed map: not on its own
            return by_score, [f'ban-screen score gives game {by_score}, game {prev_game + 1} not seen'], False
        return by_score, ['game from ban-screen score'], True
    # a header whose match number was contradicted may be a stale graphic: its game only when it is the next one
    if hg and (hg > prev_game if state == 'unread' else hg == prev_game + 1):
        return hg, ['game from header'], True
    return prev_game + 1, ['game from map order only'], False


def ignore_foreign_ban(rec: dict, sched: list) -> tuple:
    """a ban screen whose two teams are no scheduled match is a misread (team names snap to the nearest known name):
    it must not overrule the header"""
    if not rec['banTeams'] or any(fits(m, rec['banTeams']) for m in sched): return rec, []
    return dict(rec, banTeams=None), [f"ban screen {' vs '.join(rec['banTeams'])} not on the schedule (ignored)"]


def unresolved(rec: dict, sched: list, issues: list) -> dict:
    no = rec['header'].get('match')
    guess = rec['banTeams'] or ([sched[no - 1]['team1'], sched[no - 1]['team2']] if no and 1 <= no <= len(sched) else None)
    panels = [t or f'panel{i + 1}' for i, t in enumerate(rec['panelTeams'])]
    return {'idx': None, 'src': None, 'matchNo': no, 'game': rec['header'].get('game'), 'pair': guess,
            'label': ' vs '.join(t or 'TBD' for t in (guess or panels)), 'panels': panels,
            'labelVerified': False, 'labelIssues': issues + ['match unresolved']}


def label_one(rec: dict, sched: list, prev_idx: int | None, games: dict) -> dict:
    """match, game, panel teams and labelVerified of one map; games = {schedule index: last game given}"""
    rec, pre = ignore_foreign_ban(rec, sched)
    idx, src, state, issues = resolve_match(rec, sched, prev_idx)
    issues = pre + issues
    if idx is None: return unresolved(rec, sched, issues)
    pair = scheduled_pair(sched[idx], rec)
    open_slot = any(map(is_slot, pair))
    if open_slot: issues.append('a team of this match is still TBD on the schedule')
    panels, p_issues, p_ok = assign_panels(rec['panelTeams'], pair, rec['banTeams'])
    game, g_issues, g_ok = resolve_game(rec, state, games.get(idx, 0))
    return {'idx': idx, 'src': src, 'gameTrusted': g_ok, 'matchNo': idx + 1, 'game': game, 'pair': pair,
            'label': ' vs '.join(t or 'TBD' for t in pair), 'panels': [t or f'panel{i + 1}' for i, t in enumerate(panels)],
            'labelVerified': p_ok and g_ok and not open_slot, 'labelIssues': issues + p_issues + g_issues}


def label_maps(recs: list, sched: list) -> list:
    """labels for the maps of a day in time order. rec = {'ts', 'header', 'ban' (dict|None), 'banTeams', 'panelTeams'}.
    Only a header or ban-screen match moves the 'no going back' mark: a time guess must not reject the next header."""
    out, prev_idx, games = [], None, {}
    sched = [dict(m) for m in sched]
    for rec in recs:
        lab = label_one(rec, sched, prev_idx, games)
        if lab['idx'] is not None and rec['banTeams'] and lab['src'] in ('header', 'ban screen'):
            claim_slots(sched[lab['idx']], lab['pair'])
        if lab['idx'] is not None:
            if lab['gameTrusted']: games[lab['idx']] = max(games.get(lab['idx'], 0), lab['game'] or 0)
            if lab['src'] in ('header', 'ban screen'): prev_idx = lab['idx']
        out.append(lab)
    mark_duplicates(out)
    return out


def claim_slots(m: dict, pair: list) -> None:
    """a TBD match given to a ban-screen pair is that pair for the rest of the day: another pair cannot fit it"""
    if any(map(is_slot, (m['team1'], m['team2']))) and not any(map(is_slot, pair)):
        m['team1'], m['team2'] = pair


def mark_duplicates(labels: list) -> None:
    """the same (match, game) twice on a day: neither can be trusted (10-23: two 'match 1 game 1'). A game number
    that is only a guess (map order, a contradicted score) is unverified already and does not make another a duplicate."""
    seen = Counter((x['matchNo'], x['game']) for x in labels if x['idx'] is not None and x['gameTrusted'])
    for x in labels:
        if x['idx'] is not None and seen[(x['matchNo'], x['game'])] > 1:
            x['labelVerified'] = False
            x['labelIssues'].append(f"duplicate match {x['matchNo']} game {x['game']}")


# ---- Player of the Match (pure) ----------------------------------------------------------------------------------

def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def potm_numbers(reads: list) -> dict | None:
    """the fully drawn POTM frame: elims, deaths and E/D all read and consistent; most elims wins (the numbers count
    up while the card animates in; a 0-elims frame is one that has not counted up yet, 0/0/0.0 would pass the E/D
    check). None when no frame qualifies (10-23: intro frame 0/2/1 without E/D)."""
    good = [r for r in reads if _num(r.get('elims')) and _num(r.get('deaths')) and _num(r.get('ed'))
            and r['elims'] > 0 and abs(r['elims'] / max(r['deaths'], 1) - r['ed']) < ED_TOL]
    return max(good, key=lambda r: r['elims']) if good else None


def card_name(reads: list) -> str:
    """the intro frames have no name yet and read as noise ('?51'): the most common clean name wins"""
    names = [r['name'] for r in reads if re.fullmatch(r'[A-Za-z0-9_]{2,}', r.get('name') or '')]
    return max(sorted(set(names)), key=names.count) if names else ''


def potm_card(reads: list) -> dict:
    return {'name': card_name(reads), 'numbers': potm_numbers(reads)}


def assign_cards(groups: list, cards: list) -> dict:
    """{key: (ts, card)}: a card belongs to a match when it comes after the match's last map, before the next
    match's first map and within POTM_WINDOW; each card is used once. groups = [(key, first_ts, last_ts)]"""
    order, used, out = sorted(groups, key=lambda g: g[1]), set(), {}
    for label, first, last in order:
        nxt = min((f for _, f, _ in order if f > last), default=float('inf'))
        for ts, card in sorted(cards, key=lambda c: c[0]):
            if ts in used or not last < ts < min(nxt, last + POTM_WINDOW): continue
            out[label] = (ts, card); used.add(ts)
            break
    return out


def table_totals(maps: list) -> dict:
    """{table name: [elims, deaths]} over the match's maps; unknown names (None) left out"""
    tot = {}
    for m in maps:
        for rows in m['teams'].values():
            for r in rows:
                if not r.get('name'): continue
                t = tot.setdefault(r['name'], [0, 0]); t[0] += r['e'] or 0; t[1] += r['d'] or 0
    return tot


def pick_potm(card: dict, maps: list, pair: list, ctx: dict) -> tuple:
    """-> (potm dict | None, method). The name must be on one of the two rosters (team from the roster, never from
    a table row); otherwise a unique elims+deaths match with a named table row whose roster team is in the pair."""
    nums = card.get('numbers') or {}
    name, method = card.get('name') or None, 'name'
    team = NM.team_of(name, ctx['rosters'], ctx['h'], among=pair)
    if not team and nums:
        exact = [n for n, (e, d) in table_totals(maps).items() if e == nums.get('elims') and d == nums.get('deaths')]
        if len(exact) == 1:
            team = NM.team_of(exact[0], ctx['rosters'], ctx['h'], among=pair)
            name, method = exact[0], 'elims+deaths match'
    if not team: return None, 'unresolved'
    return {'name': name, 'team': team, 'elims': nums.get('elims'), 'deaths': nums.get('deaths'),
            'dmgPerMin': nums.get('dmgPerMin'), 'screenName': card.get('name'), 'method': method}, method


# ---- series results (pure) ---------------------------------------------------------------------------------------

def last_map_winner(sb: dict, potm: dict | None, need: int | None) -> tuple:
    """-> (team, source) | (None, None) for the last map given to a match: the leader before it (a tie: the POTM
    team), only when that team wins the series with this map. Otherwise a later map was not captured or not
    resolved, and the leader may have lost this one. need None (best-of unknown): only a 3-x leader (BO7 clinch)."""
    if len(sb) != 2 or any(v is None for v in sb.values()): return None, None
    (ta, a_), (tb, b_) = sb.items()
    if a_ != b_: team, src = (ta if a_ > b_ else tb), 'match end (leader)'
    elif potm and potm.get('team') in sb: team, src = potm['team'], 'match end (POTM team)'
    else: return None, None
    return (team, src) if sb[team] + 1 == (need or MAX_SERIES + 1) else (None, None)


def set_winners(ms: list, potm: dict | None, need: int | None = None) -> None:
    """ms = the maps given to one match in time order. map winner = the side whose series score went up at the next
    ban screen; last map: last_map_winner"""
    for m, nxt in zip(ms, ms[1:]):
        after = nxt.get('seriesBefore')
        # game 1 without a readable ban screen (10-23 m01) still starts at 0-0
        before = m.get('seriesBefore') or ({t: 0 for t in after} if after and m['game'] == 1 and m['labelVerified'] else None)
        if before and after:
            up = [t for t in before if (after.get(t) or 0) > (before[t] or 0)]
            if len(up) == 1: m['winner'], m['winnerSource'] = up[0], 'series score'
    lm = ms[-1]
    if lm.get('seriesBefore') and 'winner' not in lm:
        team, src = last_map_winner(lm['seriesBefore'], potm, need)
        if team: lm['winner'], lm['winnerSource'] = team, src


def match_results(out_maps: list, cards: list, ctx: dict) -> list:
    """per match with a label-verified map: map winners, map wins (verified maps) and Player of the Match.
    Every map given to the match counts for the series order and the POTM window, verified or not."""
    by_idx = {}
    for m in sorted(out_maps, key=lambda x: x['_ts']):
        if m['_idx'] is not None: by_idx.setdefault(m['_idx'], []).append(m)
    owner = assign_cards([(i, ms[0]['_ts'], ms[-1]['_ts']) for i, ms in by_idx.items()], cards)
    results = []
    for idx, ms in by_idx.items():
        ok = [m for m in ms if m['labelVerified']]
        if not ok: continue
        potm, method = None, None
        if idx in owner: potm, method = pick_potm(owner[idx][1], ms, ok[0]['_pair'], ctx)
        set_winners(ms, potm, ctx['schedule'][idx].get('need') if idx < len(ctx['schedule']) else None)
        for m in ms:          # an unverified map's game may be a guess: no winner the site could put on another game
            if not m['labelVerified']: m.pop('winner', None); m.pop('winnerSource', None)
        res = {'match': ok[0]['match'], 'matchNo': idx + 1,
               'mapWins': dict(Counter(m['winner'] for m in ok if m.get('winner'))), 'potm': potm}
        if idx in owner and potm is None:
            res['potmMethod'], res['potmScreenName'] = method, owner[idx][1].get('name')
        results.append(res)
    return results


# ---- reading frames (needs the image libraries of the capture PC) ------------------------------------------------

def warn_once(day: str, key: str, title: str, text: str) -> None:
    """notify once per day and message (assembly runs after every map), always log"""
    import platform_util as PU
    mark = os.path.join(day, f'.warned_{key}')
    try:
        with open(mark, encoding='utf-8') as f:
            if f.read() == text:
                print(f'[{title}] {text}', file=sys.stderr); return
    except FileNotFoundError:
        pass
    PU.notify(title, text)
    with open(mark, 'w', encoding='utf-8') as f: f.write(text)


def digit_lib_gaps(counts: dict, need: int) -> str:
    """'' when every digit has `need` samples, else e.g. '6: 0, 9: 1'"""
    return ', '.join(f'{d}: {n}' for d, n in sorted(counts.items()) if n < need)


def save_unknown(unknown_dir: str, uid: str, map_no: str, row: int, feat, crop) -> None:
    import ocr_header as H
    import ocr_names as N
    base = os.path.join(unknown_dir, f'{uid[1:]}_m{map_no}_r{row}')
    if feat is not None: H.imwrite_u(base + '.feat.png', N.feat_png(feat))
    if crop is not None and crop.size: H.imwrite_u(base + '.raw.png', crop)


def unknown_id(map_no: str, row: int, unknown: list) -> str:
    """'?<map><row>' (map 4 row 6 -> '?46'): the same name crop keeps its id when the day is assembled again (after
    every map, after every label_unknown run), so an id read off an older mapstats.json still means the same crop"""
    used = {u['id'] for u in unknown}
    k = int(map_no) * 10 + row if str(map_no).isdigit() else len(unknown) + 1
    while f'?{k}' in used: k += 1000          # the same map number from two frame folders
    return f'?{k}'


def read_rows(entry: dict, im, lib: list, unknown: list, unknown_dir: str) -> list:
    """two panels of 5 rows; unknown names -> {'name': None, 'unknownId': '?k'} and their crops saved"""
    import ocr_names as N
    panels = []
    for pi in (0, 1):
        rows = []
        for r in range(pi * 5, pi * 5 + 5):
            f, crop = N.name_feat(im, r) if im is not None else (None, None)
            nm, d = N.match(lib, f) if f is not None else (None, 1e9)
            nums = {k: entry['rows'][r][k] for k in K}
            if d > N.UNKNOWN_DIST:
                uid = unknown_id(entry['map'], r, unknown)
                save_unknown(unknown_dir, uid, entry['map'], r, f, crop)
                unknown.append({'id': uid, 'map': entry['map'], 'row': r})
                rows.append({'name': None, 'unknownId': uid, **nums})
            else:
                rows.append({'name': nm, **nums})
        panels.append(rows)
    return panels


def frame_ts(frame: str) -> int:
    return int(os.path.splitext(frame)[0].rsplit('_', 1)[1])


def read_bans(frames_dir: str) -> list:
    """[(ts, ban)] of the ban screens; mapKnown = the map name snapped to one Liquipedia has (else the raw reading)"""
    import cv2
    import ocr_screens as SCR
    lists, ev = SCR.word_lists(), {}
    for f in sorted(glob.glob(os.path.join(frames_dir, 'ban_*_1.png'))):
        b = SCR.read_ban(cv2.imread(f), lists)
        ev[int(os.path.basename(f).split('_')[1])] = dict(b, mapKnown=b.get('map') in lists[1])
    return sorted(ev.items())


def read_cards(frames_dir: str) -> list:
    """one POTM card = the frames with the same first timestamp (potm_<ts>_<k>.png, potm_<ts>_t<k>.png)"""
    import cv2
    import ocr_screens as SCR
    groups = {}
    for f in sorted(glob.glob(os.path.join(frames_dir, 'potm_*.png'))):
        groups.setdefault(int(os.path.basename(f).split('_')[1]), []).append(SCR.read_potm(cv2.imread(f)))
    return [(ts, potm_card(reads)) for ts, reads in sorted(groups.items())]


# ---- assembly ----------------------------------------------------------------------------------------------------

def pick_map(hd: dict, ban: dict | None, lab: dict, m: dict | None) -> tuple:
    """-> (map name | None, issues). A header whose match number was not trusted may be a stale graphic (10-23 m05/m06
    showed match 1's 'New Junk City' / 'Esperança' over Aatlis / Colosseo): then the ban screen's map comes first."""
    head = hd.get('map') if hd.get('map') not in (None, '?') else None
    seen = (ban or {}).get('map') if (ban or {}).get('mapKnown', True) else None
    order = [head, seen] if lab['src'] == 'header' else [seen, head]
    if m and lab['game'] and lab['game'] - 1 < len(m['maps']): order.append(m['maps'][lab['game'] - 1].get('map'))
    name = next((x for x in order if x), None)
    return name, [f'map: header {head}, ban screen {seen}'] if head and seen and head != seen else []


def build_map(entry: dict, panels_rows: list, lab: dict, rec: dict, sched: list) -> dict:
    m = sched[lab['idx']] if lab['idx'] is not None else None
    map_name, m_issues = pick_map(entry.get('header') or {}, rec.get('ban'), lab, m)
    known = sum(1 for rows in panels_rows for r in rows if r['name'])
    issues = lab['labelIssues'] + m_issues + ([f'known names {known}/10'] if known < MIN_KNOWN * 10 else [])
    out = {'match': lab['label'], 'matchNo': lab['matchNo'], 'game': lab['game'], 'map': map_name or '?',
           'mapTime': entry.get('mapTime'), 'frame': entry['frame'],
           'teams': {t: rows for t, rows in zip(lab['panels'], panels_rows)},
           'totalsVerified': entry.get('totalsOK') is True, 'labelVerified': lab['labelVerified'], 'labelIssues': issues,
           'reading': 'ocr', '_ts': rec['ts'], '_known': known, '_pair': lab['pair'], '_idx': lab['idx']}
    out.update({k: entry[k] for k in COPY_FIELDS if k in entry})
    b = rec.get('ban')
    if b and len(out['teams']) == 2 and set(b.get('teams') or []) == set(out['teams']):
        out['bans'] = {'initial': b['initial'], 'followUp': b['followUp']}
        score = series_score(b)
        if score: out['seriesBefore'] = {b['teams'][0]: score[0], b['teams'][1]: score[1]}
    return out


def map_record(ts: int, entry: dict, panels_rows: list, prev_ts: int | None, bans: list, ctx: dict) -> dict:
    """what the labelling needs to know about one map"""
    hit = ban_before(ts, prev_ts, bans)
    ban = dict(hit[1], teams=[NM.canon_team(t, ctx['aliases']) for t in hit[1].get('teams') or []]) if hit else None
    return {'ts': ts, 'header': entry.get('header') or {}, 'ban': ban, 'banTeams': ban_teams(ban, ctx),
            'panelTeams': [panel_team([r['name'] for r in p], ctx) for p in panels_rows]}


def assemble(ocr: list, read_frame, bans: list, cards: list, ctx: dict, lib: list, unknown_dir: str) -> dict:
    """the day's mapstats from ocr.json entries; read_frame(entry) -> image or None"""
    entries = sorted(ocr, key=lambda e: frame_ts(e['frame']))
    unknown, unknown_maps, recs, rows, prev_ts = [], [], [], [], None
    for entry in entries:
        ts = frame_ts(entry['frame'])
        rows.append(read_rows(entry, read_frame(entry), lib, unknown, unknown_dir))
        recs.append(map_record(ts, entry, rows[-1], prev_ts, bans, ctx)); prev_ts = ts
        if (entry.get('header') or {}).get('map') == '?': unknown_maps.append({'map': entry['map'], 'frame': entry['frame']})
    labels = label_maps(recs, ctx['schedule'])
    out_maps = [build_map(*args, ctx['schedule']) for args in zip(entries, rows, labels, recs)]
    return {'maps': out_maps, 'matches': match_results(out_maps, cards, ctx), 'unknownNames': unknown, 'unknownMaps': unknown_maps}


def summary(date: str, res: dict) -> str:
    maps = res['maps']
    pot = ', '.join((r['potm'] or {}).get('name') or r.get('potmMethod') or '-' for r in res['matches'])
    return (f"{date}: {len(maps)} maps, {sum(1 for x in maps if x['totalsVerified'])} verified by totals, "
            f"{sum(1 for x in maps if x['labelVerified'])} label-verified, {len(res['unknownNames'])} unknown names, "
            f"{sum(1 for x in maps if x['_known'] < MIN_KNOWN * 10)} map(s) under {int(MIN_KNOWN * 100)}% known names, "
            f"{sum(1 for x in maps if x.get('bans'))} with bans, {sum(1 for x in maps if x.get('winner'))} with winner, "
            f"POTM: {pot}")


def prepare_unknown_dir(day: str) -> str:
    """unknown/ holds the crops of the current mapstats only (a name added to the library drops out; ids are stable)"""
    d = os.path.join(day, 'unknown'); os.makedirs(d, exist_ok=True)
    for f in glob.glob(os.path.join(d, '*.png')): os.remove(f)
    return d


def check_libraries(date: str, day: str, lib: list) -> bool:
    """stop on an empty name library; warn about an incomplete bold-digit library"""
    import ocr_screens as SCR
    if not lib:
        warn_once(day, 'name_lib', 'OWCSKR assemble stopped',
                  f'{date}: data/name_lib is empty or unreadable - no names, no teams. Copy the name library to this machine.')
        return False
    gaps = digit_lib_gaps(SCR.digit_counts(), SCR.DIGIT_MIN_SAMPLES)
    if gaps:
        warn_once(day, 'digit_lib', 'OWCSKR digit library incomplete',
                  f'data/digit_lib samples under {SCR.DIGIT_MIN_SAMPLES}: {gaps} (POTM/score digits; see tools/build_digit_lib.py)')
    return True


def write_result(date: str, day: str, res: dict) -> None:
    for m in res['maps']:
        for k in ('_ts', '_known', '_pair', '_idx'): m.pop(k, None)
    out = {'date': date, 'source': 'OBS capture of the SOOP broadcast (owesports), GAME DATA screens', **res,
           'note': 'reading=ocr: numbers, match/game/map read from the broadcast screen; totalsVerified = sums match the team-totals page; '
                   'labelVerified = match, game and panel teams agree with the schedule, ban screen and rosters (labelIssues say why not); '
                   'name None + unknownId = a player name not in the name library; mapTime = damage / damage-per-minute from the totals page.'}
    path = os.path.join(day, 'mapstats.json')
    tmp = f'{path}.{os.getpid()}.tmp'       # publish_day / a second assembly never see a half-written file
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


@contextlib.contextmanager
def day_lock(day: str, wait: float = 600, stale: float = 1800, sleep=time.sleep):
    """one assembly of a day at a time (the capture after every map, label_unknown, the daily republish_recent):
    both rewrite unknown/ and mapstats.json. A lock older than `stale` s is left from a killed run and is taken over."""
    path, t0 = os.path.join(day, '.assemble.lock'), time.time()
    while True:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)); break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > stale: os.remove(path); continue
            except FileNotFoundError:
                continue
            if time.time() - t0 > wait: raise TimeoutError(f'{path} held for more than {wait:.0f} s')
            sleep(2)
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError): os.remove(path)


def main(date: str) -> int:
    os.chdir(ROOT)                      # the OCR modules use paths relative to the repo
    import cv2
    import ocr_names as N
    day = os.path.join('data', 'live', date)
    if not os.path.exists(os.path.join(day, 'ocr.json')):
        print(f'{date}: no map read yet'); return 0
    if not check_libraries(date, day, lib := N.load_lib()): return 2
    ctx = load_context(date)
    if not ctx['schedule']:
        warn_once(day, 'schedule', 'OWCSKR no schedule',
                  f'{date}: no Korean match in data/site/matches.json - map labels cannot be verified, nothing will be published')
    try:
        with day_lock(day):
            with open(os.path.join(day, 'ocr.json'), encoding='utf-8') as f: ocr = json.load(f)
            frames_dir = os.path.join(day, 'frames')
            res = assemble(ocr, lambda e: cv2.imread(os.path.join(e['dir'], e['frame'])), read_bans(frames_dir),
                           read_cards(frames_dir), ctx, lib, prepare_unknown_dir(day))
            line = summary(date, res)
            write_result(date, day, res)
    except TimeoutError as e:
        print(f'{date}: assembly FAILED: another assembly of this day is still running ({e})', file=sys.stderr); return 1
    print(line)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace'); sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # names like 'Esperança'
    if len(sys.argv) != 2 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', sys.argv[1]):
        print('usage: python -I tools/assemble_day.py YYYY-MM-DD', file=sys.stderr); sys.exit(2)
    sys.exit(main(sys.argv[1]))
