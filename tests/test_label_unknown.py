"""Unknown names: name_lib loading, label_unknown, assembly stop on an empty library (P1-07)."""
import json, os, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
import assemble_day as AD
import label_unknown as LU
import ocr_header as H
import ocr_names as N
import platform_util as PU

DATE = '2026-10-23'
FX = json.load(open(os.path.join(HERE, 'fixtures', 'live-2026-10-23.json'), encoding='utf-8'))


def feat():
    f = np.zeros((18, 96), np.float32); f[3:15, 5:60] = 1.0
    return f


def make_root(tmp_path):
    for rel, data in (('data/aliases.json', FX['aliases']), ('data/manual/handle-aliases.json', FX['handleAliases']),
                      ('data/manual/players.json', FX['players'])):
        p = tmp_path / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data), encoding='utf-8')
    unk = tmp_path / 'data' / 'live' / DATE / 'unknown'; unk.mkdir(parents=True)
    H.imwrite_u(str(unk / '3_m04_r6.feat.png'), N.feat_png(feat()))
    H.imwrite_u(str(unk / '3_m04_r6.raw.png'), np.zeros((26, 175, 3), np.uint8))
    H.imwrite_u(str(unk / '4_m04_r7.raw.png'), np.zeros((26, 175, 3), np.uint8))   # empty crop: no feature
    return tmp_path


def test_load_lib_skips_wrong_shapes(tmp_path, capsys):
    H.imwrite_u(str(tmp_path / 'Irony__a.png'), N.feat_png(feat()))
    H.imwrite_u(str(tmp_path / 'Esperança__b.png'), N.feat_png(feat()))
    H.imwrite_u(str(tmp_path / 'Raw__c.png'), np.zeros((26, 175), np.uint8))     # a raw crop copied by hand
    H.imwrite_u(str(tmp_path / 'noseparator.png'), N.feat_png(feat()))
    lib = N.load_lib(str(tmp_path))
    assert sorted(n for n, _, _ in lib) == ['Esperança', 'Irony']
    assert lib[0][1].shape == (18, 96) and lib[0][1].max() == 1.0
    err = capsys.readouterr().err
    assert 'Raw__c.png' in err and 'noseparator.png' in err


def test_feature_roundtrip_matches_library_format():
    f = feat()
    assert N.feat_png(f).shape == N.FEAT_SHAPE and np.allclose(N.feat_png(f).astype(np.float32) / 255, f)


def test_add_label_copies_feature(tmp_path):
    root = make_root(tmp_path)
    path = LU.add_label(DATE, '?3', 'Irony', str(root))
    assert os.path.basename(path) == f'Irony__{DATE}_3.png'
    assert np.array_equal(H.imread_u(path), N.feat_png(feat()))
    again = LU.add_label(DATE, '3', 'Irony', str(root))                 # same id of a later assembly
    assert os.path.basename(again) == f'Irony__{DATE}_3_m04_r6.png'
    assert len(N.load_lib(str(root / 'data' / 'name_lib'))) == 2


def test_add_label_rejects_bad_input(tmp_path):
    root = make_root(tmp_path)
    for uid, name, msg in (('?4', 'Kilo', 'empty'), ('?9', 'Kilo', 'no such'), ('x', 'Kilo', 'not an unknown id'),
                           ('?3', 'a__b', "'__'"), ('?3', 'a/b', 'not allowed'), ('?3', ' ', 'empty')):
        try:
            LU.add_label(DATE, uid, name, str(root)); raise AssertionError('accepted ' + uid + name)
        except ValueError as e:
            assert msg in str(e)


def test_main_labels_then_reassembles(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    monkeypatch.setattr(LU, 'ROOT', str(root))
    calls = []
    monkeypatch.setattr(AD, 'main', lambda date: calls.append(date) or 0)
    assert LU.main([DATE, '?3', 'Irony', '?9', 'Kilo']) == 1             # one failed: still re-assembles, exit 1
    assert calls == [DATE]
    assert LU.main([DATE, '?9', 'Kilo']) == 1 and calls == [DATE]        # nothing added: no re-run
    assert LU.main([DATE, '?3']) == 2


def test_on_roster_uses_folding(tmp_path):
    root = make_root(tmp_path)
    assert LU.on_roster('Irony', str(root)) and not LU.on_roster('Nobody', str(root))


def test_assembly_stops_on_empty_name_library(tmp_path, monkeypatch):
    day = tmp_path / 'data' / 'live' / DATE; day.mkdir(parents=True)
    (day / 'ocr.json').write_text(json.dumps(FX['ocr']), encoding='utf-8')
    sent = []
    monkeypatch.setattr(PU, 'notify', lambda t, x: sent.append((t, x)))
    monkeypatch.setattr(AD, 'ROOT', str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert AD.main(DATE) == 2
    assert AD.main(DATE) == 2
    assert len(sent) == 1 and 'name_lib' in sent[0][1]                   # notified once per day
    assert not (day / 'mapstats.json').exists()


def test_digit_gap_text():
    assert AD.digit_lib_gaps({str(d): 3 for d in range(10)}, 3) == ''
    assert AD.digit_lib_gaps({**{str(d): 3 for d in range(10)}, '6': 0, '9': 1}, 3) == '6: 0, 9: 1'


def test_unknown_crops_saved_as_feature_and_raw(tmp_path):
    AD.save_unknown(str(tmp_path), '?7', '04', 6, feat(), np.zeros((26, 175, 3), np.uint8))
    assert sorted(os.listdir(tmp_path)) == ['7_m04_r6.feat.png', '7_m04_r6.raw.png']
    assert H.imread_u(str(tmp_path / '7_m04_r6.feat.png')).shape == N.FEAT_SHAPE
    AD.save_unknown(str(tmp_path), '?8', '04', 7, None, None)
    assert len(os.listdir(tmp_path)) == 2


def test_main_end_to_end_without_frames(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    (root / 'data' / 'site').mkdir(parents=True)
    (root / 'data' / 'site' / 'matches.json').write_text(json.dumps(FX['schedule']), encoding='utf-8')
    day = root / 'data' / 'live' / DATE
    (day / 'ocr.json').write_text(json.dumps(FX['ocr']), encoding='utf-8')
    lib = root / 'data' / 'name_lib'; lib.mkdir()
    H.imwrite_u(str(lib / 'Irony__x.png'), N.feat_png(feat()))
    sent = []
    monkeypatch.setattr(PU, 'notify', lambda t, x: sent.append(t))
    monkeypatch.setattr(AD, 'ROOT', str(root))
    monkeypatch.chdir(root)
    assert AD.main(DATE) == 0
    out = json.loads((day / 'mapstats.json').read_text(encoding='utf-8'))
    assert len(out['maps']) == 9 and len(out['unknownNames']) == 90       # no frames here: every name unknown
    m = out['maps'][0]
    assert {'labelVerified', 'labelIssues', 'totalsVerified', 'framesAgree'} <= set(m) and '_ts' not in m
    assert m['teams']['Cheeseburger'][0] == {'name': None, 'unknownId': '?10', 'e': 13, 'a': 5, 'd': 2, 'dmg': 9356, 'heal': 422, 'mit': 10648}
    assert not os.listdir(day / 'unknown')                                 # earlier crops cleared, none saved without frames
    assert 'OWCSKR digit library incomplete' in sent                       # no data/digit_lib on this machine
