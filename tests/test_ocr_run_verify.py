import copy, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import ocr_run as R


def rows(a=3):
    return [{'e': 10 + i, 'a': a, 'd': 5, 'dmg': 1000 * (i + 1), 'heal': 100, 'mit': 0} for i in range(10)]


def totals_for(rs):
    out = []
    for pi in (0, 1):
        part = rs[pi * 5:(pi + 1) * 5]
        out.append({k: sum(p[k] for p in part) for k in R.VERIFIED_FIELDS} | {'dpm': 1, 'hpm': 1})
    return out


def test_import_does_not_train():
    assert R._MODELS is None


def test_no_totals_frame_is_none_even_when_frames_agree():
    v = R.assess([rows(), rows(), rows()], [])
    assert v['totalsOK'] is None and v['framesAgree'] is True
    assert v['verifyFailed'] is True and v['verifyReason'] == 'no totals frame'


def test_totals_present_and_matching():
    rs = rows()
    v = R.assess([rs, rs], [totals_for(rs)])
    assert v['totalsOK'] is True and v['verifyFailed'] is False and v['verifyReason'] is None


def test_totals_present_but_mismatch_is_false():
    rs = rows(); bad = totals_for(rs); bad[0]['dmg'] += 1
    v = R.assess([rs], [bad])
    assert v['totalsOK'] is False and v['verifyFailed'] is True


def test_any_table_totals_combination_passes():
    good = rows()
    misread = copy.deepcopy(good); misread[2]['dmg'] = 9999
    bad_tot = totals_for(good); bad_tot[1]['heal'] = 1
    ti, oi, ok = R.verify([misread, good], [bad_tot, totals_for(good)])
    assert (ti, oi, ok) == (1, 1, True)
    v = R.assess([misread, good], [bad_tot, totals_for(good)])
    assert v['rows'][2]['dmg'] == good[2]['dmg'] and v['framesAgree'] is False


def test_none_cell_never_matches():
    rs = rows(); tot = totals_for(rs); rs[0]['e'] = None
    assert R.sums_ok(rs, tot) is False


def test_assists_need_two_agreeing_frames():
    f1, f2, f3 = rows(a=3), rows(a=3), rows(a=3)
    f2[4]['a'] = 7; f3[4]['a'] = 1           # three different values on row 4
    f3[6]['a'] = 9                           # row 6: two of three agree on 3
    out, ok = R.agreed_assists([f1, f2, f3], f1)
    assert out[4]['a'] is None and out[6]['a'] == 3 and out[0]['a'] == 3
    assert ok is False


def test_assists_single_frame_unverified():
    v = R.assess([rows()], [])
    assert all(r['a'] is None for r in v['rows']) and v['aVerified'] is False


def test_assists_majority_overrides_picked_frame():
    f1, f2, f3 = rows(a=3), rows(a=8), rows(a=8)
    out, ok = R.agreed_assists([f1, f2, f3], f1)
    assert all(r['a'] == 8 for r in out) and ok is True
    assert all(r['e'] == f1[i]['e'] for i, r in enumerate(out))


def test_main_fails_cleanly_without_models(monkeypatch, tmp_path, capsys):
    import glyph_models as GM
    monkeypatch.setattr(R, '_MODELS', None)
    monkeypatch.setattr(GM, 'get_models', lambda **k: (_ for _ in ()).throw(GM.ModelError('no glyph models')))
    out = tmp_path / 'ocr.json'
    assert R.main(str(out), [str(tmp_path)]) == 2
    assert not out.exists() and 'no glyph models' in capsys.readouterr().err


def test_main_writes_entries_with_new_fields(monkeypatch, tmp_path):
    import json
    import cv2, numpy as np
    import ocr_header as HD
    good = rows(); misread = copy.deepcopy(good); misread[0]['e'] = 99
    by_pixel = {1: misread, 2: good, 3: good}
    for name, px in (('m01_table1_100.png', 1), ('m01_table2_105.png', 2), ('m01_table3_110.png', 3),
                     ('m01_totals_120.png', 50), ('m01_totals_125.png', 60), ('m02_table1_900.png', 1)):
        cv2.imwrite(str(tmp_path / name), np.full((8, 8, 3), px, np.uint8))
    bad_tot = totals_for(good); bad_tot[0]['mit'] = 5
    monkeypatch.setattr(R, '_MODELS', ('mt', 'mo'))
    monkeypatch.setattr(R, 'read_table', lambda im: (copy.deepcopy(by_pixel[int(im[0, 0, 0])]), []))
    monkeypatch.setattr(R, 'read_totals', lambda im: copy.deepcopy(bad_tot if int(im[0, 0, 0]) == 50 else totals_for(good)))
    monkeypatch.setattr(HD, 'load_header_lib', lambda: ([], []))
    monkeypatch.setattr(HD, 'read_header', lambda im, lib: {'match': 1, 'game': 1, 'map': 'Busan'})
    out = tmp_path / 'ocr.json'
    assert R.main(str(out), [str(tmp_path)]) == 0
    m1, m2 = json.loads(out.read_text(encoding='utf-8'))
    assert m1['totalsOK'] is True and m1['frame'] == 'm01_table2_105.png' and m1['totalsFrame'] == 'm01_totals_125.png'
    assert m1['verifiedFields'] == ['e', 'd', 'dmg', 'heal', 'mit'] and m1['framesAgree'] is False
    assert m1['aVerified'] is True and m1['verifyFailed'] is False
    assert m2['totalsOK'] is None and m2['verifyFailed'] is True and m2['aVerified'] is False and m2['totals'] is None
    for k in ('dir', 'map', 'frame', 'framesAgree', 'totalsOK', 'rows', 'totals', 'header', 'durationSec', 'mapTime'):
        assert k in m1
