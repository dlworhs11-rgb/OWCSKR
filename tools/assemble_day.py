"""Turn one capture day (data/live/<date>/ocr.json + frames) into a mapstats file.

usage: python -I tools/assemble_day.py YYYY-MM-DD

- player names: nearest crop in data/name_lib (unknown names -> '?k', crop saved to data/live/<date>/unknown/)
- team of each panel: roster overlap with data/manual/players.json (community sheet)
- match / game number / map name: that day's Korean-league matches from data/site/matches.json (run collector/build.mjs first)
- writes data/live/<date>/mapstats.json (tools/publish_day.py uploads the verified maps)
"""
import cv2, json, os, sys, shutil
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
unknown, out_maps = [], []
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
    # advance through the day's matches
    if mi < len(matches):
        cur = {matches[mi]['team1'], matches[mi]['team2']}
        nxt = {matches[mi + 1]['team1'], matches[mi + 1]['team2']} if mi + 1 < len(matches) else set()
        if teams and teams <= nxt and not teams <= cur: mi, game = mi + 1, 0
        elif not teams and game >= max(1, sum(1 for x in matches[mi]['maps'] if x.get('winner'))): mi, game = mi + 1, 0
    game += 1
    m = matches[mi] if mi < len(matches) else None
    lp_map = (m['maps'][game - 1]['map'] if m and game - 1 < len(m['maps']) else None)
    # a panel whose team we could not tell gets the remaining team of the match
    if m:
        pair = [m['team1'], m['team2']]
        for i, (t, nm) in enumerate(panels):
            if not t:
                other = panels[1 - i][0]
                panels[i] = ([x for x in pair if x != other][0] if other in pair else f'panel{i + 1}', nm)
    out_maps.append({
        'match': f"{m['team1']} vs {m['team2']}" if m else None, 'game': game, 'map': lp_map, 'mapTime': None,
        'frame': entry['frame'],
        'teams': {t: [{'name': nm[i], **{k: entry['rows'][pi * 5 + i][k] for k in K}} for i in range(5)] for pi, (t, nm) in enumerate(panels)},
        'totalsVerified': bool(entry['totalsOK']), 'reading': 'ocr'})

res = {'date': date, 'source': 'OBS capture of the SOOP broadcast (owesports), GAME DATA screens', 'maps': out_maps,
       'unknownNames': unknown,
       'note': 'reading=ocr: digits read by tools/ocr_run.py; totalsVerified = sums match the team-totals page. mapTime not read yet.'}
json.dump(res, open(os.path.join(day, 'mapstats.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
verified = sum(1 for x in out_maps if x['totalsVerified'])
print(f'{date}: {len(out_maps)} maps, {verified} verified by totals, {len(unknown)} unknown names')
