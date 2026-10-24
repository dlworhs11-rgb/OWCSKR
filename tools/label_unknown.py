"""Add names that assemble_day could not read to the name library, then assemble the day again.

usage: python -I tools/label_unknown.py YYYY-MM-DD ?3 Name [?5 Name2 ...]

- ids are the unknownId values of data/live/<date>/mapstats.json; look at unknown/<k>_m<map>_r<row>.raw.png to see
  who it is. An id is map * 10 + row (?46 = map 4, row 6) and stays the same when the day is assembled again.
- copies unknown/<k>_m<map>_r<row>.feat.png (the 96x18 feature, not the raw crop) to data/name_lib/<Name>__<date>_<k>.png
"""
import glob, os, re, sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import names as NM

ROOT = os.path.dirname(TOOLS)
NAME_LIB = os.path.join('data', 'name_lib')
BAD_CHARS = set('<>:"/\\|?*')


def check_name(name: str) -> str | None:
    """why `name` cannot be a library file name (None = fine)"""
    if not name.strip() or name != name.strip(): return 'empty or padded with spaces'
    if '__' in name: return "contains '__' (the name/tag separator)"
    if BAD_CHARS & set(name) or any(ord(ch) < 32 for ch in name): return 'contains a character not allowed in file names'
    return None


def find_feature(unknown_dir: str, uid: str) -> tuple:
    """-> (path of the .feat.png | None, error | None)"""
    k = uid.lstrip('?')
    if not k.isdigit(): return None, f'{uid}: not an unknown id like ?3'
    feats = glob.glob(os.path.join(unknown_dir, f'{k}_m*_r*.feat.png'))
    if len(feats) == 1: return feats[0], None
    if glob.glob(os.path.join(unknown_dir, f'{k}_m*_r*.raw.png')):
        return None, f'{uid}: the name crop was empty (no feature); it cannot be added'
    return None, f'{uid}: no such unknown name in {unknown_dir} (already labelled, or check mapstats.json)'


def target_path(lib_dir: str, name: str, date: str, feat_path: str) -> str:
    k = os.path.basename(feat_path).split('_', 1)[0]
    path = os.path.join(lib_dir, f'{name}__{date}_{k}.png')
    if os.path.exists(path):          # the same id of an earlier assembly: keep both samples
        where = re.sub(r'\.feat\.png$', '', os.path.basename(feat_path)).split('_', 1)[1]
        path = os.path.join(lib_dir, f'{name}__{date}_{k}_{where}.png')
    return path


def add_label(date: str, uid: str, name: str, root: str | None = None) -> str:
    """copy one unknown feature into the name library; returns the new file, raises ValueError on bad input"""
    import ocr_header as H
    import ocr_names as N
    root = root or ROOT
    why = check_name(name)
    if why: raise ValueError(f'{name!r}: {why}')
    feat, err = find_feature(os.path.join(root, 'data', 'live', date, 'unknown'), uid)
    if err: raise ValueError(err)
    im = H.imread_u(feat)
    if im is None or im.shape != N.FEAT_SHAPE:
        raise ValueError(f'{feat}: not a {N.FEAT_SHAPE[1]}x{N.FEAT_SHAPE[0]} name feature')
    lib_dir = os.path.join(root, NAME_LIB); os.makedirs(lib_dir, exist_ok=True)
    path = target_path(lib_dir, name, date, feat)
    if os.path.exists(path): raise ValueError(f'{path} already exists')
    H.imwrite_u(path, im)
    return path


def on_roster(name: str, root: str | None = None) -> bool:
    root = root or ROOT
    aliases, h = NM.team_aliases(root), NM.handle_aliases(root)
    rosters = NM.build_rosters(NM.load_json('data/manual/players.json', root), aliases, h)
    return any(NM.fold(name, h) in r for r in rosters.values())


def main(argv: list) -> int:
    if len(argv) < 3 or len(argv) % 2 == 0 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', argv[0]):
        print(__doc__.split('\n\n')[1], file=sys.stderr); return 2
    date, pairs = argv[0], list(zip(argv[1::2], argv[2::2]))
    failed = 0
    for uid, name in pairs:
        try:
            print('added', add_label(date, uid, name))
            if not on_roster(name): print(f'note: {name} is not on any roster in data/manual/players.json', file=sys.stderr)
        except ValueError as e:
            print('not added:', e, file=sys.stderr); failed += 1
    if failed == len(pairs): return 1
    import assemble_day
    code = assemble_day.main(date)
    return code or (1 if failed else 0)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace'); sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main(sys.argv[1:]))
