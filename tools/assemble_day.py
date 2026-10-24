"""Turn one capture day (data/live/<date>/ocr.json + frames) into a mapstats file.

usage: python -I tools/assemble_day.py YYYY-MM-DD

- player names: nearest crop in data/name_lib; unknown names -> name None + unknownId '?k', feature and raw crop saved
  to data/live/<date>/unknown/<k>_m<map>_r<row>.feat.png / .raw.png (label them with tools/label_unknown.py)
- team of each panel: roster overlap with data/manual/players.json (community sheet)
- match: the header number ("MATCH 2") only when it agrees with time order, the ban screen before the map and the
  known players' teams; otherwise the ban-screen teams, then the scheduled start times (Korean matches of the day in
  data/site/matches.json). A map whose match, game or panel sides cannot be trusted gets labelVerified False.
- writes data/live/<date>/mapstats.json (tools/publish_day.py uploads the verified maps)
"""
import glob, json, os, re, sys
from collections import Counter
from datetime import datetime

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import names as NM

ROOT = os.path.dirname(TOOLS)
K = ['e', 'a', 'd', 'dmg', 'heal', 'mit']
BAN_WINDOW = 3 * 3600        # a ban screen older than this is not this map's
POTM_WINDOW = 1800           # the POTM card follows the last map of a match within this
ED_TOL = 0.06                # |elims/deaths - E/D| of a fully drawn POTM card (E/D is shown rounded)
MIN_KNOWN = 0.5              # share of the 10 names read below this -> labelIssues entry
COPY_FIELDS = ('framesAgree', 'verifiedFields', 'aVerified')


# ---- context: rosters, team names, the day's schedule ---------------------------------------------------------

def day_schedule(matches: list, date: str, aliases: dict) -> list:
    """Korean matches of the day in time order: [{'team1', 'team2', 'start' (unix s), 'maps'}]"""
    out = []
    for m in matches:
        if not (m.get('date') or '').startswith(date) or '/Korea' not in m.get('competitionTitle', ''): continue
        out.append({'team1': NM.canon_team(m['team1'], aliases), 'team2': NM.canon_team(m['team2'], aliases),
                    'start': int(datetime.fromisoformat(m['date']).timestamp()), 'maps': m.get('maps') or []})
    return sorted(out, key=lambda m: m['start'])


def load_context(date: str, root: str | None = None) -> dict:
    root = root or ROOT
    aliases, h_aliases = NM.team_aliases(root), NM.handle_aliases(root)
    try:
        sched = day_schedule(NM.load_json('data/site/matches.json', root), date, aliases)
    except FileNotFoundError:
        sched = []
    return {'aliases': aliases, 'h': h_aliases, 'teams': set(aliases.values()), 'schedule': sched,
            'rosters': NM.build_rosters(NM.load_json('data/manual/players.json', root), aliases, h_aliases)}


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


def pair_of(m: dict) -> set:
    return {m['team1'], m['team2']}


def outside_teams(rec: dict, m: dict) -> list:
    return sorted({t for t in rec['panelTeams'] if t} - pair_of(m))


def header_issues(no: int, rec: dict, sched: list, prev_idx: int | None) -> list:
    """reasons not to trust the header's match number (empty = trust it)"""
    if not 1 <= no <= len(sched): return [f'header match {no} not on the schedule ({len(sched)} matches)']
    out, m = [], sched[no - 1]
    if prev_idx is not None and no - 1 < prev_idx: out.append(f'header match {no} after match {prev_idx + 1}')
    if rec['banTeams'] and set(rec['banTeams']) != pair_of(m):
        out.append(f"ban screen {' vs '.join(rec['banTeams'])} is not {m['team1']} vs {m['team2']}")
    if outside_teams(rec, m):
        out.append(f"known players of {', '.join(outside_teams(rec, m))} in match {no} ({m['team1']} vs {m['team2']})")
    return out


def match_by_time(ts: int, sched: list) -> int | None:
    started = [i for i, m in enumerate(sched) if m['start'] <= ts]
    return started[-1] if started else None


def fallback_match(rec: dict, sched: list) -> tuple:
    """header dropped: the scheduled pair of the ban-screen teams, else the last match started before the map"""
    if rec['banTeams']:
        hits = [i for i, m in enumerate(sched) if pair_of(m) == set(rec['banTeams'])]
        if hits: return hits[0], 'ban screen', []
        return None, 'ban screen', [f"ban screen {' vs '.join(rec['banTeams'])} not on the schedule"]
    idx = match_by_time(rec['ts'], sched)
    return idx, 'schedule time', [] if idx is not None else ['no scheduled match started before this map']


def resolve_match(rec: dict, sched: list, prev_idx: int | None) -> tuple:
    """-> (schedule index | None, source 'header' | 'ban screen' | 'schedule time' | None, issues)"""
    hd, issues = rec['header'], []
    no = hd.get('match')
    if no is None:
        issues.append('header match digit ambiguous' if hd.get('matchAmbiguous') else 'header match not read')
    else:
        bad = header_issues(no, rec, sched, prev_idx)
        if not bad: return no - 1, 'header', issues
        issues += bad
    idx, src, more = fallback_match(rec, sched)
    issues += more
    if idx is None: return None, None, issues
    if prev_idx is not None and idx < prev_idx:
        return None, None, issues + [f'{src} gives match {idx + 1}, after match {prev_idx + 1}']
    if outside_teams(rec, sched[idx]):
        return None, None, issues + [f"known players of {', '.join(outside_teams(rec, sched[idx]))} in match {idx + 1} ({src})"]
    return idx, src, issues + [f'match from {src}']


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


def resolve_game(rec: dict, header_ok: bool, prev_game: int) -> tuple:
    """-> (game, issues, trusted); prev_game = last game given to the same match (0 = none)"""
    hg = rec['header'].get('game')
    score = (rec.get('ban') or {}).get('score') or []
    by_score = sum(score) + 1 if len(score) == 2 and all(isinstance(s, int) for s in score) else None
    if header_ok and hg:
        if by_score and by_score != hg:
            return hg, [f'header game {hg} but ban-screen score {score[0]}-{score[1]}'], False
        return hg, [], True
    if by_score: return by_score, ['game from ban-screen score'], True
    if hg and hg > prev_game: return hg, ['game from header'], True
    return prev_game + 1, ['game from map order only'], False


def label_one(rec: dict, sched: list, prev_idx: int | None, games: dict) -> dict:
    """match, game, panel teams and labelVerified of one map; games = {schedule index: last game given}"""
    idx, src, issues = resolve_match(rec, sched, prev_idx)
    if idx is None:
        no = rec['header'].get('match')
        guess = rec['banTeams'] or ([sched[no - 1]['team1'], sched[no - 1]['team2']] if no and 1 <= no <= len(sched) else None)
        panels = [t or f'panel{i + 1}' for i, t in enumerate(rec['panelTeams'])]
        return {'idx': None, 'matchNo': no, 'game': rec['header'].get('game'), 'pair': guess,
                'label': ' vs '.join(guess or panels), 'panels': panels,
                'labelVerified': False, 'labelIssues': issues + ['match unresolved']}
    pair = [sched[idx]['team1'], sched[idx]['team2']]
    panels, p_issues, p_ok = assign_panels(rec['panelTeams'], pair, rec['banTeams'])
    game, g_issues, g_ok = resolve_game(rec, src == 'header', games.get(idx, 0))
    return {'idx': idx, 'matchNo': idx + 1, 'game': game, 'pair': pair, 'label': f'{pair[0]} vs {pair[1]}',
            'panels': panels, 'labelVerified': p_ok and g_ok, 'labelIssues': issues + p_issues + g_issues}


def label_maps(recs: list, sched: list) -> list:
    """labels for the maps of a day in time order. rec = {'ts', 'header', 'ban' (dict|None), 'banTeams', 'panelTeams'}"""
    out, prev_idx, games = [], None, {}
    for rec in recs:
        lab = label_one(rec, sched, prev_idx, games)
        if lab['idx'] is not None:
            prev_idx = lab['idx']; games[prev_idx] = max(games.get(prev_idx, 0), lab['game'] or 0)
        out.append(lab)
    mark_duplicates(out)
    return out


def mark_duplicates(labels: list) -> None:
    """the same (match, game) twice on a day: neither can be trusted (10-23: two 'match 1 game 1')"""
    seen = Counter((x['matchNo'], x['game']) for x in labels if x['idx'] is not None)
    for x in labels:
        if x['idx'] is not None and seen[(x['matchNo'], x['game'])] > 1:
            x['labelVerified'] = False
            x['labelIssues'].append(f"duplicate match {x['matchNo']} game {x['game']}")


# ---- Player of the Match (pure) ----------------------------------------------------------------------------------

def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def potm_numbers(reads: list) -> dict | None:
    """the fully drawn POTM frame: elims, deaths and E/D all read and consistent; most elims wins (the numbers count
    up while the card animates in). None when no frame qualifies (10-23: intro frame 0/2/1 without E/D)."""
    good = [r for r in reads if _num(r.get('elims')) and _num(r.get('deaths')) and _num(r.get('ed'))
            and abs(r['elims'] / max(r['deaths'], 1) - r['ed']) < ED_TOL]
    return max(good, key=lambda r: r['elims']) if good else None


def card_name(reads: list) -> str:
    """the intro frames have no name yet and read as noise ('?51'): the most common clean name wins"""
    names = [r['name'] for r in reads if re.fullmatch(r'[A-Za-z0-9_]{2,}', r.get('name') or '')]
    return max(sorted(set(names)), key=names.count) if names else ''


def potm_card(reads: list) -> dict:
    return {'name': card_name(reads), 'numbers': potm_numbers(reads)}


def assign_cards(groups: list, cards: list) -> dict:
    """{label: (ts, card)}: a card belongs to a match when it comes after the match's last map, before the next
    match's first map and within POTM_WINDOW; each card is used once. groups = [(label, first_ts, last_ts)]"""
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

def set_winners(ms: list, potm: dict | None) -> None:
    """map winner = the side whose series score went up at the next ban screen; last map = the leader (tie: POTM team)"""
    for m, nxt in zip(ms, ms[1:]):
        if m.get('seriesBefore') and nxt.get('seriesBefore'):
            up = [t for t in m['seriesBefore'] if (nxt['seriesBefore'].get(t) or 0) > (m['seriesBefore'][t] or 0)]
            if len(up) == 1: m['winner'], m['winnerSource'] = up[0], 'series score'
    lm = ms[-1]
    if lm.get('seriesBefore') and 'winner' not in lm and len(lm['seriesBefore']) == 2:
        (ta, a_), (tb, b_) = list(lm['seriesBefore'].items())
        if a_ is not None and b_ is not None and a_ != b_:
            lm['winner'], lm['winnerSource'] = (ta if a_ > b_ else tb), 'match end (leader)'
        elif potm and potm.get('team') in lm['seriesBefore']:
            lm['winner'], lm['winnerSource'] = potm['team'], 'match end (POTM team)'


def match_results(out_maps: list, cards: list, ctx: dict) -> list:
    """per match, from the label-verified maps only: map winners, map wins and Player of the Match"""
    by_match = {}
    for m in out_maps:
        if m['labelVerified']: by_match.setdefault(m['match'], []).append(m)
    for ms in by_match.values(): ms.sort(key=lambda x: x['_ts'])
    owner = assign_cards([(lb, ms[0]['_ts'], ms[-1]['_ts']) for lb, ms in by_match.items()], cards)
    results = []
    for label, ms in by_match.items():
        potm, method = None, None
        if label in owner: potm, method = pick_potm(owner[label][1], ms, ms[0]['_pair'], ctx)
        set_winners(ms, potm)
        res = {'match': label, 'matchNo': ms[0]['matchNo'], 'mapWins': dict(Counter(m['winner'] for m in ms if m.get('winner'))),
               'potm': potm}
        if label in owner and potm is None:
            res['potmMethod'], res['potmScreenName'] = method, owner[label][1].get('name')
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
                uid = f'?{len(unknown) + 1}'
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
    import cv2
    import ocr_screens as SCR
    lists, ev = SCR.word_lists(), {}
    for f in sorted(glob.glob(os.path.join(frames_dir, 'ban_*_1.png'))):
        ev[int(os.path.basename(f).split('_')[1])] = SCR.read_ban(cv2.imread(f), lists)
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

def build_map(entry: dict, panels_rows: list, lab: dict, rec: dict, sched: list) -> dict:
    hd = entry.get('header') or {}
    m = sched[lab['idx']] if lab['idx'] is not None else None
    map_name = hd.get('map') if hd.get('map') not in (None, '?') else None
    if not map_name and m and lab['game'] and lab['game'] - 1 < len(m['maps']): map_name = m['maps'][lab['game'] - 1].get('map')
    known = sum(1 for rows in panels_rows for r in rows if r['name'])
    issues = lab['labelIssues'] + ([f'known names {known}/10'] if known < MIN_KNOWN * 10 else [])
    out = {'match': lab['label'], 'matchNo': lab['matchNo'], 'game': lab['game'], 'map': map_name or '?',
           'mapTime': entry.get('mapTime'), 'frame': entry['frame'],
           'teams': {t: rows for t, rows in zip(lab['panels'], panels_rows)},
           'totalsVerified': entry.get('totalsOK') is True, 'labelVerified': lab['labelVerified'], 'labelIssues': issues,
           'reading': 'ocr', '_ts': rec['ts'], '_known': known, '_pair': lab['pair']}
    out.update({k: entry[k] for k in COPY_FIELDS if k in entry})
    b = rec.get('ban')
    if b and len(out['teams']) == 2 and set(b.get('teams') or []) == set(out['teams']):
        out['bans'] = {'initial': b['initial'], 'followUp': b['followUp']}
        out['seriesBefore'] = {b['teams'][0]: b['score'][0], b['teams'][1]: b['score'][1]}
        if out['map'] == '?' and b.get('map'): out['map'] = b['map']
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
    """unknown/ holds the crops of the current mapstats only (ids are renumbered on every run)"""
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
        for k in ('_ts', '_known', '_pair'): m.pop(k, None)
    out = {'date': date, 'source': 'OBS capture of the SOOP broadcast (owesports), GAME DATA screens', **res,
           'note': 'reading=ocr: numbers, match/game/map read from the broadcast screen; totalsVerified = sums match the team-totals page; '
                   'labelVerified = match, game and panel teams agree with the schedule, ban screen and rosters (labelIssues say why not); '
                   'name None + unknownId = a player name not in the name library; mapTime = damage / damage-per-minute from the totals page.'}
    with open(os.path.join(day, 'mapstats.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


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
    with open(os.path.join(day, 'ocr.json'), encoding='utf-8') as f: ocr = json.load(f)
    frames_dir = os.path.join(day, 'frames')
    res = assemble(ocr, lambda e: cv2.imread(os.path.join(e['dir'], e['frame'])), read_bans(frames_dir),
                   read_cards(frames_dir), ctx, lib, prepare_unknown_dir(day))
    line = summary(date, res)
    write_result(date, day, res)
    print(line)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace'); sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # names like 'Esperança'
    if len(sys.argv) != 2 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', sys.argv[1]):
        print('usage: python -I tools/assemble_day.py YYYY-MM-DD', file=sys.stderr); sys.exit(2)
    sys.exit(main(sys.argv[1]))
