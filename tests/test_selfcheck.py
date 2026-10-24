import json, os, sys, types

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import glyph_models as GM
import selfcheck as SC


def no_tools(name): return None
def all_tools(name): return f'/usr/bin/{name}'
def has_module(name): return object()
def logged_in(cmd, **kw): return types.SimpleNamespace(returncode=0, stdout='gho_token\n', stderr='')
def logged_out(cmd, **kw): return types.SimpleNamespace(returncode=1, stdout='', stderr='no oauth token found for github.com')


def png(path, value=128):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cv2.imwrite(str(path), np.full((4, 4, 3), value, np.uint8))


def complete_root(root, digits='0123456789'):
    for rel, _ in SC.REFERENCE_IMAGES:
        png(root / rel)
    feat = root / 'data/name_lib/Faith__a.png'
    os.makedirs(feat.parent, exist_ok=True)
    cv2.imwrite(str(feat), np.zeros((18, 96, 3), np.uint8))
    for d in digits:
        png(root / f'data/header_lib/digit_{d}__x.png'); png(root / f'data/digit_lib/{d}__x.png')
    png(root / 'data/header_lib/map_Busan__x.png')
    for rel in ('data/manual/players.json', 'data/site/matches.json'):
        os.makedirs(root / os.path.dirname(rel), exist_ok=True)
        (root / rel).write_text(json.dumps([{'x': 1}]), encoding='utf-8')
    m = GM.TB.Model(); [m.add(np.zeros(2, np.float32), d) for d in '0123456789']; m.fit()
    for kind in GM.KINDS:
        GM.save(GM.model_path(kind, str(root)), m, 'h', {})


def items(problems, severity):
    return {p.item for p in problems if p.severity == severity}


def test_empty_root_reports_every_missing_file(tmp_path):
    probs = SC.check(str(tmp_path), env={}, which=no_tools, run=logged_out, find_spec=lambda n: None)
    fatal = items(probs, 'fatal')
    for rel, _ in SC.REFERENCE_IMAGES:
        assert rel in fatal
    for item in ('data/name_lib', 'data/header_lib', 'data/digit_lib', 'data/manual/players.json', 'data/site/matches.json',
                 'data/models', 'gh', 'tesseract', 'pytesseract'):
        assert item in fatal, item
    assert items(probs, 'warn') == {'ffmpeg', 'yt-dlp'}


def test_complete_root_passes(tmp_path):
    complete_root(tmp_path)
    probs = SC.check(str(tmp_path), env={'GH_TOKEN': 'x'}, which=all_tools, run=logged_out, find_spec=has_module)
    assert probs == []


def test_missing_digit_is_a_warning_not_fatal(tmp_path):
    complete_root(tmp_path, digits='012345789')
    probs = SC.check(str(tmp_path), env={'GH_TOKEN': 'x'}, which=all_tools, find_spec=has_module)
    assert SC.fatal(probs) == []
    assert {(p.item, 'digit(s) 6' in p.detail) for p in probs} == {('data/header_lib', True), ('data/digit_lib', True)}


def test_token_from_gh_auth_token(tmp_path):
    complete_root(tmp_path)
    assert SC.check(str(tmp_path), env={}, which=all_tools, run=logged_in, find_spec=has_module) == []
    probs = SC.check(str(tmp_path), env={}, which=all_tools, run=logged_out, find_spec=has_module)
    assert items(probs, 'fatal') == {'GitHub token'}


def test_publish_off_makes_gh_a_warning(tmp_path):
    """OWCSKR_PUBLISH=0 (shadow run): nothing is uploaded, so a server without gh or a token still captures"""
    complete_root(tmp_path)
    probs = SC.check(str(tmp_path), env={'OWCSKR_PUBLISH': '0'}, which=all_tools, run=logged_out, find_spec=has_module)
    assert SC.fatal(probs) == [] and items(probs, 'warn') == {'GitHub token'}
    assert 'publish off' in probs[0].detail
    no_gh = lambda name: None if name == 'gh' else all_tools(name)
    probs = SC.check(str(tmp_path), env={}, which=no_gh, find_spec=has_module, publish=False)
    assert SC.fatal(probs) == [] and items(probs, 'warn') == {'gh'}
    assert items(SC.check(str(tmp_path), env={}, which=no_gh, find_spec=has_module), 'fatal') == {'gh'}


def test_token_check_is_local_and_network_trouble_is_not_fatal(tmp_path):
    import subprocess
    complete_root(tmp_path)
    cmds = []
    def run(cmd, **kw):
        cmds.append(cmd[1:])
        return logged_in(cmd)
    assert SC.check(str(tmp_path), env={}, which=all_tools, run=run, find_spec=has_module) == []
    assert cmds == [['auth', 'token']]                                # no 'gh auth status': that one needs api.github.com
    def hangs(cmd, **kw): raise subprocess.TimeoutExpired(cmd, kw['timeout'])
    probs = SC.check(str(tmp_path), env={}, which=all_tools, run=hangs, find_spec=has_module)
    assert SC.fatal(probs) == [] and items(probs, 'warn') == {'GitHub token'}
    old_gh = lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout='', stderr='unknown command "token" for "gh auth"')
    assert SC.fatal(SC.check(str(tmp_path), env={}, which=all_tools, run=old_gh, find_spec=has_module)) == []


def test_name_lib_of_unusable_files_counts_as_empty(tmp_path):
    complete_root(tmp_path)
    os.remove(tmp_path / 'data/name_lib/Faith__a.png')
    png(tmp_path / 'data/name_lib/Faith__raw.png')                  # a raw crop, not a 96x18 feature
    png(tmp_path / 'data/name_lib/no_tag.png')
    probs = SC.check(str(tmp_path), env={'GH_TOKEN': 'x'}, which=all_tools, find_spec=has_module)
    assert items(probs, 'fatal') == {'data/name_lib'} and '2 skipped' in probs[0].detail
    cv2.imwrite(str(tmp_path / 'data/name_lib/Faith__ok.png'), np.zeros((18, 96, 3), np.uint8))
    probs = SC.check(str(tmp_path), env={'GH_TOKEN': 'x'}, which=all_tools, find_spec=has_module)
    assert SC.fatal(probs) == [] and items(probs, 'warn') == {'data/name_lib'}


def test_unreadable_reference_image_is_fatal(tmp_path):
    complete_root(tmp_path)
    (tmp_path / SC.REFERENCE_IMAGES[0][0]).write_bytes(b'not an image')
    probs = SC.check(str(tmp_path), env={'GH_TOKEN': 'x'}, which=all_tools, find_spec=has_module)
    assert items(probs, 'fatal') == {SC.REFERENCE_IMAGES[0][0]}


def test_tesseract_env_override(tmp_path):
    complete_root(tmp_path)
    tess = tmp_path / 'tesseract.bin'; tess.write_bytes(b'')
    which = lambda n: None if n == 'tesseract' else all_tools(n)
    probs = SC.check(str(tmp_path), env={'GH_TOKEN': 'x', 'TESSERACT_CMD': str(tess)}, which=which, find_spec=has_module)
    assert probs == []


def test_cli_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(SC, 'check', lambda **k: [SC.Problem('fatal', 'gh', 'missing')])
    sent = []
    monkeypatch.setattr(SC.PU, 'notify', lambda t, x: sent.append((t, x)))
    assert SC.main(['--notify']) == 2
    assert 'FATAL gh: missing' in capsys.readouterr().out and len(sent) == 1
    monkeypatch.setattr(SC, 'check', lambda **k: [SC.Problem('warn', 'ffmpeg', 'missing')])
    assert SC.main([]) == 0


def test_hls_source_needs_ffmpeg_and_ytdlp(tmp_path):
    complete_root(tmp_path)
    which = lambda n: None if n in ('ffmpeg', 'yt-dlp') else all_tools(n)
    probs = SC.check(str(tmp_path), env={'GH_TOKEN': 'x'}, which=which, find_spec=has_module, source='hls')
    assert items(probs, 'fatal') == {'ffmpeg', 'yt-dlp'} and 'FFMPEG_CMD' in str(probs[0])
    obs = SC.check(str(tmp_path), env={'GH_TOKEN': 'x'}, which=which, find_spec=has_module, source='obs')
    assert items(obs, 'fatal') == set() and items(obs, 'warn') == {'ffmpeg', 'yt-dlp'}
    assert 'only with --source hls' in str(obs[0])


def test_hls_tools_found_through_env_overrides(tmp_path):
    complete_root(tmp_path)
    ff, yt = tmp_path / 'ffmpeg.exe', tmp_path / 'yt.exe'
    ff.write_bytes(b''); yt.write_bytes(b'')
    which = lambda n: None if n in ('ffmpeg', 'yt-dlp') else all_tools(n)
    env = {'GH_TOKEN': 'x', 'FFMPEG_CMD': str(ff), 'YTDLP_CMD': str(yt)}
    assert SC.check(str(tmp_path), env=env, which=which, find_spec=has_module, source='hls') == []


def test_frame_source_from_env(tmp_path):
    assert SC.frame_source({}) == 'obs' and SC.frame_source({'OWCSKR_FRAME_SOURCE': ' HLS '}) == 'hls'
    complete_root(tmp_path)
    which = lambda n: None if n == 'ffmpeg' else all_tools(n)
    probs = SC.check(str(tmp_path), env={'GH_TOKEN': 'x', 'OWCSKR_FRAME_SOURCE': 'hls'}, which=which, find_spec=has_module)
    assert items(probs, 'fatal') == {'ffmpeg'}
    bad = SC.check(str(tmp_path), env={'GH_TOKEN': 'x', 'OWCSKR_FRAME_SOURCE': 'webcam'}, which=all_tools, find_spec=has_module)
    assert items(bad, 'fatal') == {'frame source'}


def test_cli_source_argument(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(SC, 'check', lambda **k: seen.update(k) or [])
    assert SC.main(['--source', 'hls']) == 0 and seen['source'] == 'hls'
    assert SC.main([]) == 0 and seen['source'] is None
