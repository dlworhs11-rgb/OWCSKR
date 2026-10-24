"""Turn one capture day (data/live/<date>/ocr.json + frames) into a mapstats file.

usage: python -I tools/assemble_day.py YYYY-MM-DD

- player names: nearest crop in data/name_lib (unknown names -> '?k', crop saved to data/live/<date>/unknown/)
- team of each panel: roster overlap with data/manual/players.json (community sheet)
- match / game number / map name / map time: read from the broadcast itself (header + totals page);
  the day's schedule in data/site/matches.json is only a fallback and gives the 'Team A vs Team B' order
- writes data/live/<date>/mapstats.json (tools/publish_day.py uploads the verified maps)
"""
import cv2, json, os, sys, shutil
import sys as _sys; _sys.stdout.reconfigure(encoding='utf-8', errors='replace'); _sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # logs may contain names like 'Esperança'
sys.path.insert(0, os.path.dirname(__file__))
import ocr_names as N

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
date = sys.argv[1]
day = os.path.join('data', 'live', date)
if not os.path.exists(os.path.join(day, 'ocr.json')):
    print(f'{date}: no map read yet'); sys.exit(0)
ocr = json.load(open(os.path.join(day, 'ocr.json'), encoding='utf-8'))
lib = N.load_lib()

aliases = json.load(open('data/aliases.json', encoding='utf-8'))
canon = lambda t: aliases.get(t.lower(), t)
norm = lambda s: ''.join(ch for ch in s.lower() if ch.isalnum())
rosters = {}
for p in json.load(open('data/manual/players.json', encoding='utf-8')):
    if p['region'] != 'KR': continue
    latin = [w for w in p['name'].split() if any('a' <= ch.lower() <= 'z' for ch in w)]   # '준빈 JunBin', 'SoLA 솔라'
    handle = latin[0] if latin else p['name']
    rosters.setdefault(canon(p['team']), set()).add(norm(handle))

matches = [m for m in json.load(open('data/site/matches.json', encoding='utf-8'))
           if m['date'].startswith(date) and '/Korea' in m['competitionTitle']]
matches.sort(key=lambda m: m['date'])
K = ['e', 'a', 'd', 'dmg', 'heal', 'mit']

unknown_dir = os.path.join(day, 'unknown'); os.makedirs(unknown_dir, exist_ok=True)
unknown, unknown_maps, out_maps = [], [], []
mi, game = 0, 0
for entry in sorted(ocr, key=lambda e: e['map']):
    im = cv2.imread(os.path.join(entry['dir'], entry['frame']))
    panels = []
    for pi in (0, 1):
        names = []
        for r in range(pi * 5, pi * 5 + 5):
            f, crop = N.name_feat(im, r)
            nm, d = N.match(lib, f) if f is not None else (None, 1e9)
            if d > N.UNKNOWN_DIST:
                nm = f'?{len(unknown) + 1}'
                cv2.imwrite(os.path.join(unknown_dir, f"{nm[1:]}_m{entry['map']}_r{r}.png"), crop)
                unknown.append({'id': nm, 'map': entry['map'], 'row': r})
            names.append(nm)
        known = {norm(n) for n in names if not n.startswith('?')}
        team = max(rosters, key=lambda t: len(rosters[t] & known)) if known else None
        if team and not (rosters[team] & known): team = None
        panels.append((team, names))
    teams = {t for t, _ in panels if t}
    hd = entry.get('header') or {}
    # match / game: read from the broadcast header ("MATCH 2 GAME 3"); fall back to the day's schedule order
    if hd.get('match') and hd.get('game'):
        mi, game = hd['match'] - 1, hd['game']
    else:
        if mi < len(matches):
            cur = {matches[mi]['team1'], matches[mi]['team2']}
            nxt = {matches[mi + 1]['team1'], matches[mi + 1]['team2']} if mi + 1 < len(matches) else set()
            if teams and teams <= nxt and not teams <= cur: mi, game = mi + 1, 0
        game += 1
    m = matches[mi] if 0 <= mi < len(matches) else None
    if m and teams and not teams <= {m['team1'], m['team2']}:
        m = None                                   # schedule changed / not in Liquipedia yet: trust the screen
    # map name: header first ('?' = a map we have not seen yet), then Liquipedia
    map_name = hd.get('map') if hd.get('map') not in (None, '?') else None
    if not map_name and m and game - 1 < len(m['maps']): map_name = m['maps'][game - 1].get('map')
    if hd.get('map') == '?': unknown_maps.append({'map': entry['map'], 'frame': entry['frame']})
    # a panel whose team we could not tell gets the remaining team of the match
    pair = [m['team1'], m['team2']] if m else sorted(teams)
    for i, (t, nm) in enumerate(panels):
        if not t:
            other = panels[1 - i][0]
            rest = [x for x in pair if x != other]
            panels[i] = (rest[0] if rest else f'panel{i + 1}', nm)
    label = f"{pair[0]} vs {pair[1]}" if len(pair) == 2 else ' vs '.join(t for t, _ in panels)
    out_maps.append({
        'match': label, 'matchNo': hd.get('match') or (mi + 1), 'game': game, 'map': map_name or '?', 'mapTime': entry.get('mapTime'),
        'frame': entry['frame'],
        'teams': {t: [{'name': nm[i], **{k: entry['rows'][pi * 5 + i][k] for k in K}} for i in range(5)] for pi, (t, nm) in enumerate(panels)},
        'totalsVerified': bool(entry['totalsOK']), 'reading': 'ocr',
        '_ts': int(os.path.splitext(entry['frame'])[0].rsplit('_', 1)[1])})

# ---- hero bans, series score / map winners and Player of the Match from the broadcast screens ----------------
import glob as _glob
import ocr_screens as SCR
frames_dir = os.path.join(day, 'frames')
lists = SCR.word_lists()
def _events(prefix, reader):
    ev = {}
    for f in sorted(_glob.glob(os.path.join(frames_dir, prefix + '_*_1.png'))):
        ts = int(os.path.basename(f).split('_')[1])
        ev[ts] = reader(cv2.imread(f))
    return sorted(ev.items())
bans = _events('ban', lambda im: SCR.read_ban(im, lists))

import re as _re
def _potm_events():
    """one POTM card = up to 4 frames with the same first timestamp; take the name from any frame that shows it
    and the numbers from the frame where E/D agrees best with elims/deaths"""
    groups = {}
    for f in sorted(_glob.glob(os.path.join(frames_dir, 'potm_*.png'))):
        ts = int(os.path.basename(f).split('_')[1]); groups.setdefault(ts, []).append(SCR.read_potm(cv2.imread(f)))
    out = []
    for ts, reads in sorted(groups.items()):
        # the intro frames have no name yet and read as noise ('?51'): the most common clean name wins
        names = [r['name'] for r in reads if _re.fullmatch(r'[A-Za-z0-9_]{2,}', r.get('name') or '')]
        name = max(set(names), key=names.count) if names else ''
        good = [r for r in reads if r.get('elims') is not None and r.get('deaths')]
        best = min(good, key=lambda r: abs(r['elims'] / r['deaths'] - r.get('ed', 0))) if good else (reads[0] if reads else {})
        out.append((ts, {**best, 'name': name}))
    return out
potms = _potm_events()

def _team_set(m): return set(m['teams'])
used = set()
for m in out_maps:
    before = [(ts, b) for ts, b in bans if ts < m['_ts'] and m['_ts'] - ts < 3 * 3600 and ts not in used and set(b['teams']) == _team_set(m)]
    if not before: continue
    ts, b = before[-1]; used.add(ts)
    m['bans'] = {'initial': b['initial'], 'followUp': b['followUp']}
    m['seriesBefore'] = {b['teams'][0]: b['score'][0], b['teams'][1]: b['score'][1]}
    m['_banTs'] = ts
    if m['map'] in (None, '?') and b.get('map'): m['map'] = b['map']

# map winner = the side whose series score went up at the next ban screen of the same match
by_match = {}
for m in out_maps: by_match.setdefault(m['match'], []).append(m)
match_results = []
for label, ms in by_match.items():
    ms.sort(key=lambda x: x['_ts'])
    for i, m in enumerate(ms):
        nxt = ms[i + 1] if i + 1 < len(ms) else None
        if m.get('seriesBefore') and nxt and nxt.get('seriesBefore'):
            up = [t for t in m['seriesBefore'] if nxt['seriesBefore'].get(t, 0) > m['seriesBefore'][t]]
            if len(up) == 1: m['winner'], m['winnerSource'] = up[0], 'series score'
    # Player of the Match: the POTM screen shown after this match's last map
    last_ts = ms[-1]['_ts']
    cand = [(ts, p) for ts, p in potms if 0 < ts - last_ts < 1800]
    potm = None
    if cand:
        ts, p = cand[0]
        tot = {}
        for m in ms:
            for team, rows in m['teams'].items():
                for r in rows:
                    t = tot.setdefault((r['name'], team), {'e': 0, 'd': 0}); t['e'] += r['e'] or 0; t['d'] += r['d'] or 0
        exact = [k for k, v in tot.items() if v['e'] == p.get('elims') and v['d'] == p.get('deaths')]
        byname = [k for k in tot if p.get('name') and k[0].lower() == p['name'].lower()]
        if len(exact) == 1: pick, method = exact[0], 'elims+deaths match'
        elif byname: pick, method = byname[0], 'name'
        elif p.get('elims') is not None and p.get('deaths') is not None:
            near = sorted(tot, key=lambda k: abs(tot[k]['e'] - p['elims']) + abs(tot[k]['d'] - p['deaths']))
            pick, method = near[0], 'closest elims+deaths'
        else: pick, method = None, 'unresolved'
        # a table name not read yet ('?88') is no name: the card's own name ('Violet') is closer (the site matches it to the roster)
        nm = pick[0] if pick and not str(pick[0]).startswith('?') else (p.get('name') or (pick[0] if pick else None))
        potm = {'name': nm, 'team': pick[1] if pick else None,
                'elims': p.get('elims'), 'deaths': p.get('deaths'), 'dmgPerMin': p.get('dmgPerMin'), 'screenName': p.get('name'), 'method': method}
    # last map of the match: decided by the final score (the leader won), POTM team only breaks a tie
    # Only once the POTM card proves the match is over: mid-match the newest map is not the last one (10-24 CB-ZETA:
    # with map 3 not yet read, map 2 at 1-0 was handed to the leader CB, ZETA had won it 3-2)
    lm = ms[-1]
    if potm and lm.get('seriesBefore') and 'winner' not in lm:
        sb = lm['seriesBefore']; (ta, a_), (tb, b_) = list(sb.items())
        if a_ != b_: lm['winner'], lm['winnerSource'] = (ta if a_ > b_ else tb), 'match end (leader)'
        elif potm and potm.get('team') in sb: lm['winner'], lm['winnerSource'] = potm['team'], 'match end (POTM team)'
    wins = {}
    for m in ms:
        if m.get('winner'): wins[m['winner']] = wins.get(m['winner'], 0) + 1
    match_results.append({'match': label, 'matchNo': ms[0].get('matchNo'), 'mapWins': wins, 'potm': potm})
for m in out_maps:
    for k in ('_ts', '_banTs'): m.pop(k, None)

res = {'date': date, 'source': 'OBS capture of the SOOP broadcast (owesports), GAME DATA screens', 'maps': out_maps,
       'matches': match_results, 'unknownNames': unknown, 'unknownMaps': unknown_maps,
       'note': 'reading=ocr: numbers, match/game/map read from the broadcast screen; totalsVerified = sums match the team-totals page; '
               'mapTime = damage / damage-per-minute from the totals page.'}
json.dump(res, open(os.path.join(day, 'mapstats.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
verified = sum(1 for x in out_maps if x['totalsVerified'])
print(f'{date}: {len(out_maps)} maps, {verified} verified by totals, {len(unknown)} unknown names, '
      f'{sum(1 for m in out_maps if m.get("bans"))} with bans, {sum(1 for m in out_maps if m.get("winner"))} with winner, '
      f'POTM: {", ".join((r["potm"] or {}).get("name") or "-" for r in match_results)}')
