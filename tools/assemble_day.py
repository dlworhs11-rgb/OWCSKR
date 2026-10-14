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
        'totalsVerified': bool(entry['totalsOK']), 'reading': 'ocr'})

res = {'date': date, 'source': 'OBS capture of the SOOP broadcast (owesports), GAME DATA screens', 'maps': out_maps,
       'unknownNames': unknown, 'unknownMaps': unknown_maps,
       'note': 'reading=ocr: numbers, match/game/map read from the broadcast screen; totalsVerified = sums match the team-totals page; '
               'mapTime = damage / damage-per-minute from the totals page.'}
json.dump(res, open(os.path.join(day, 'mapstats.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
verified = sum(1 for x in out_maps if x['totalsVerified'])
print(f'{date}: {len(out_maps)} maps, {verified} verified by totals, {len(unknown)} unknown names')
