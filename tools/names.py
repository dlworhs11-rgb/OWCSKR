"""Name folding shared by the assembly step: player handles and team names as the broadcast, Liquipedia and the
community sheet (data/manual/players.json) spell them."""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# look-alike glyphs: the sheet writes 'iR0NY', the broadcast and Liquipedia 'Irony'
_CONFUSE = str.maketrans({'0': 'o', '1': 'l', 'i': 'l', '3': 'e', '5': 's'})


def norm(s: str) -> str:
    """lowercase a-z0-9 only"""
    return ''.join(ch for ch in (s or '').lower() if ch.isalnum())


def fold(s: str, handle_aliases: dict | None = None) -> str:
    """comparison key of a handle: normalised, Liquipedia -> sheet alias applied, confusable glyphs folded"""
    n = norm(s)
    n = (handle_aliases or {}).get(n, n)
    return n.translate(_CONFUSE)


def sheet_handle(name: str) -> str:
    """the Latin handle of a sheet name ('준빈 JunBin', 'SoLA 솔라')"""
    latin = [w for w in name.split() if any('a' <= ch.lower() <= 'z' for ch in w)]
    return latin[0] if latin else name


def load_json(rel: str, root: str = ROOT):
    with open(os.path.join(root, rel), encoding='utf-8') as f:
        return json.load(f)


def team_aliases(root: str = ROOT) -> dict:
    return {k: v for k, v in load_json('data/aliases.json', root).items() if not k.startswith('_')}


def handle_aliases(root: str = ROOT) -> dict:
    try:
        raw = load_json('data/manual/handle-aliases.json', root)
    except FileNotFoundError:
        return {}
    return {norm(k): norm(v) for k, v in raw.items() if not k.startswith('_')}


def canon_team(name: str | None, aliases: dict) -> str | None:
    if not name: return None
    return aliases.get(name.strip().lower(), name.strip())


def build_rosters(players: list, aliases: dict, h_aliases: dict, region: str = 'KR') -> dict:
    """{canonical team: {folded handle: sheet handle}}"""
    rosters = {}
    for p in players:
        if p.get('region') != region: continue
        h = sheet_handle(p['name'])
        rosters.setdefault(canon_team(p['team'], aliases), {})[fold(h, h_aliases)] = h
    return rosters


def team_of(name: str | None, rosters: dict, h_aliases: dict, among=None) -> str | None:
    """roster team of one handle (only teams in `among` when given); None when unknown or on two rosters"""
    if not name: return None
    k = fold(name, h_aliases)
    hits = [t for t, r in rosters.items() if k in r and (among is None or t in among)]
    return hits[0] if len(hits) == 1 else None
