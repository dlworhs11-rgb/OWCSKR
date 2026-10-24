import json, os, sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import glyph_models as GM
import ocr_table as TB


def model(digits='0123456789'):
    m = TB.Model()
    for i, d in enumerate(digits):
        m.add(np.full((4, 3), i, np.float32), d)
    m.fit()
    return m


def stats():
    return {k: {'cells': 1, 'skipped': 0, 'classes': {}} for k in GM.KINDS}


@pytest.fixture
def root(tmp_path, monkeypatch):
    """tiny fake training set: ground truth + 2 table frames + 2 totals frames"""
    monkeypatch.setattr(GM, 'TABLE_TRAIN', {1: 'data/vod/t1.png', 2: 'data/vod/t2.png'})
    monkeypatch.setattr(GM, 'TOT_TRAIN', 'data/vod/p1a/frames/m{:02d}_totals_*.png')
    (tmp_path / 'data/manual/mapstats').mkdir(parents=True)
    (tmp_path / 'data/vod/p1a/frames').mkdir(parents=True)
    (tmp_path / GM.GT).write_text(json.dumps({'maps': [{'teams': {}}, {'teams': {}}]}), encoding='utf-8')
    for rel in ('data/vod/t1.png', 'data/vod/t2.png', 'data/vod/p1a/frames/m01_totals_1.png', 'data/vod/p1a/frames/m02_totals_2.png'):
        (tmp_path / rel).write_bytes(b'img')
    return tmp_path


@pytest.fixture
def trainer(monkeypatch):
    calls = []
    def fake_train(gt, tables, tots):
        calls.append((gt, tables, tots))
        return model(), model(), stats()
    monkeypatch.setattr(GM, 'train', fake_train)
    return calls


def test_build_then_load_from_cache(root, trainer):
    mt, mo = GM.get_models(root=str(root), log=lambda *x: None)
    assert len(trainer) == 1 and os.path.isfile(GM.model_path('table', str(root))) and os.path.isfile(GM.model_path('totals', str(root)))
    mt2, mo2 = GM.get_models(root=str(root), log=lambda *x: None)
    assert len(trainer) == 1
    assert np.array_equal(mt.Xa, mt2.Xa) and list(mt2.ya) == list(mt.ya)
    assert mt2.predict(np.full((4, 3), 3, np.float32))[0] == '3'


def test_changed_ground_truth_rebuilds(root, trainer):
    GM.get_models(root=str(root), log=lambda *x: None)
    (root / GM.GT).write_text(json.dumps({'maps': [{'teams': {}}, {'teams': {}}], 'x': 1}), encoding='utf-8')
    GM.get_models(root=str(root), log=lambda *x: None)
    assert len(trainer) == 2


def test_changed_training_frame_rebuilds(root, trainer):
    GM.get_models(root=str(root), log=lambda *x: None)
    (root / 'data/vod/t2.png').write_bytes(b'a different frame')
    GM.get_models(root=str(root), log=lambda *x: None)
    assert len(trainer) == 2


def test_cache_used_when_training_frames_absent(root, trainer):
    GM.get_models(root=str(root), log=lambda *x: None)
    for f in ('data/vod/t1.png', 'data/vod/t2.png', 'data/vod/p1a/frames/m01_totals_1.png'):
        os.remove(root / f)
    GM.get_models(root=str(root), log=lambda *x: None)
    assert len(trainer) == 1
    assert GM.status(str(root)) == (None, 'cached')


def test_neither_cache_nor_frames_is_a_clear_error(root, trainer):
    os.remove(root / 'data/vod/t1.png')
    with pytest.raises(GM.ModelError, match='copy data/models'):
        GM.get_models(root=str(root), log=lambda *x: None)
    assert trainer == [] and GM.status(str(root))[0] == 'fatal'


def test_missing_digit_fails_the_build(root, monkeypatch):
    monkeypatch.setattr(GM, 'train', lambda gt, t, o: (model('012345789'), model(), stats()))
    with pytest.raises(GM.ModelError, match='digit\\(s\\) 6'):
        GM.get_models(root=str(root), log=lambda *x: None)
    assert not os.path.isfile(GM.model_path('table', str(root)))


def test_status_before_first_build_is_a_warning(root):
    assert GM.status(str(root))[0] == 'warn'


def test_build_prints_training_stats(root, monkeypatch):
    s = stats(); s['table'] = {'cells': 420, 'skipped': 7, 'classes': {str(d): 5 for d in range(10)}}
    monkeypatch.setattr(GM, 'train', lambda gt, t, o: (model(), model(), s))
    lines = []
    GM.get_models(root=str(root), log=lambda *x: lines.append(' '.join(map(str, x))))
    assert any('420 cells, 7 skipped' in ln and '6:5' in ln for ln in lines)


def test_train_refuses_misaligned_ground_truth(root):
    (root / GM.GT).write_text(json.dumps({'maps': [{'teams': {}}]}), encoding='utf-8')
    gt, tables, tots = GM.training_inputs(str(root))
    with pytest.raises(GM.ModelError, match='1 hand-checked maps but 2'):
        GM.train(gt, tables, tots)


def test_corrupt_cache_is_ignored(root, trainer):
    os.makedirs(os.path.dirname(GM.model_path('table', str(root))), exist_ok=True)
    with open(GM.model_path('table', str(root)), 'wb') as fh: fh.write(b'not a zip')
    assert GM.load(GM.model_path('table', str(root))) is None
    GM.get_models(root=str(root), log=lambda *x: None)
    assert len(trainer) == 1


def _put(img, text, cx, cy, scale, th):
    import cv2
    (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, th)
    cv2.putText(img, text, (cx - w // 2, cy + h // 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), th, cv2.LINE_8)


def _synthetic_map(seed):
    """ground-truth map + its rendered table and totals frames (two-digit cells, team sums on the totals page)"""
    import ocr_totals as TT
    rng = np.random.default_rng(seed)
    teams = {t: [{'name': f'{t}{i}', **{k: int(rng.integers(10, 20 if k in ('e', 'd') else 100)) for k in GM.K}} for i in range(5)]
             for t in ('A', 'B')}
    table, tot = np.zeros((1080, 1920, 3), np.uint8), np.zeros((1080, 1920, 3), np.uint8)
    rows = [p for t in teams.values() for p in t]
    for r, p in enumerate(rows):
        for c, k in enumerate(GM.K):
            _put(table, str(p[k]), TB.X0 + TB.COLS[c], TB.Y0 + TB.ROWS[r], 0.42, 1)
    for pi, team in enumerate(teams.values()):
        for k in GM.TOT_KEYS:
            cx, cy, _, _ = TT.FIELDS[(pi, k)]
            big = k in ('dmg', 'heal', 'mit')
            _put(tot, str(sum(p[k] for p in team)), TT.X0 + cx, TT.Y0 + cy, 1.5 if big else 0.8, 3 if big else 2)
    return {'teams': teams, 'reading': 'manual'}, table, tot


def test_real_training_on_synthetic_frames_reads_back(tmp_path, monkeypatch):
    import cv2
    import ocr_run as R
    monkeypatch.setattr(GM, 'TABLE_TRAIN', {1: 'data/vod/t1.png', 2: 'data/vod/t2.png', 3: 'data/vod/t3.png'})
    (tmp_path / 'data/manual/mapstats').mkdir(parents=True); (tmp_path / 'data/vod/p1a/frames').mkdir(parents=True)
    maps = []
    for i in (1, 2, 3):
        m, table, tot = _synthetic_map(i)
        maps.append(m)
        cv2.imwrite(str(tmp_path / f'data/vod/t{i}.png'), table)
        cv2.imwrite(str(tmp_path / f'data/vod/p1a/frames/m{i:02d}_totals_{i}.png'), tot)
    (tmp_path / GM.GT).write_text(json.dumps({'maps': maps}), encoding='utf-8')
    lines = []
    mt, mo = GM.get_models(root=str(tmp_path), log=lambda *x: lines.append(' '.join(map(str, x))))
    assert any('glyph model table: 180 cells, 0 skipped' in ln for ln in lines)
    monkeypatch.setattr(R, '_MODELS', (mt, mo))
    m, table, tot = _synthetic_map(1)
    rows, _ = R.read_table(table)
    assert rows == [{k: p[k] for k in GM.K} for t in m['teams'].values() for p in t]
    assert R.sums_ok(rows, R.read_totals(tot))
