"""Ban/POTM screen readings cached per frame in data/live/<date>/screens_cache.json (RA-18), without Tesseract:
read_ban / read_potm are replaced by counting fakes that return 10-23 readings."""
import json, os, sys

import cv2, numpy as np, pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
import assemble_day as AD
import ocr_screens as SCR
from test_assemble_labels import FX

LISTS = (['cassidy', 'mauga'], ['New Junk City', 'Samoa'], {'cheeseburger': 'Cheeseburger', 'o2 blast': 'O2 Blast'})
BAN = dict(FX['bans'][1][1], raw={'map': 'NEW JUNK CITY'})                     # m02's ban screen as read on 10-23
POTM = {'name': 'Someone', 'elims': 55, 'deaths': 12, 'ed': 4.58, 'dmgPerMin': 1021, 'raw': {}}


@pytest.fixture
def day(tmp_path, monkeypatch):
    """a day folder with two ban frames and one POTM card of two frames; calls counts the OCR calls"""
    frames = tmp_path / 'frames'; frames.mkdir()
    img = np.full((54, 96, 3), 40, np.uint8)
    for name in ('ban_1792743994_1.png', 'ban_1792745398_1.png', 'potm_1792747000_1.png', 'potm_1792747000_t2.png'):
        cv2.imwrite(str(frames / name), img)
    calls = []
    monkeypatch.setattr(SCR, 'word_lists', lambda: LISTS)
    monkeypatch.setattr(SCR, 'DIGIT_LIB', str(tmp_path / 'digit_lib'))
    monkeypatch.setattr(SCR, 'read_ban', lambda im, lists: calls.append('ban') or dict(BAN))
    monkeypatch.setattr(SCR, 'read_potm', lambda im: calls.append('potm') or dict(POTM))
    monkeypatch.delenv('OWCSKR_DIGIT_CUTOFF', raising=False)
    return tmp_path, frames, calls


def read(tmp_path):
    return AD.read_screens(str(tmp_path), str(tmp_path / 'frames'))


def test_second_assembly_reads_no_screen_again(day):
    tmp_path, _, calls = day
    first = read(tmp_path)
    assert calls == ['ban', 'ban', 'potm', 'potm']
    second = read(tmp_path)
    assert calls == ['ban', 'ban', 'potm', 'potm'] and second == first
    bans, cards = second
    assert [ts for ts, _ in bans] == [1792743994, 1792745398] and bans[0][1]['mapKnown'] is True
    assert cards == [(1792747000, {'name': 'Someone', 'numbers': POTM})]
    cache = json.loads((tmp_path / AD.SCREENS_CACHE).read_text(encoding='utf-8'))
    assert cache['version'] == AD.SCREENS_CACHE_VERSION and sorted(cache['frames']) == sorted(os.listdir(tmp_path / 'frames'))


def test_only_new_frames_are_read(day):
    tmp_path, frames, calls = day
    read(tmp_path); calls.clear()
    cv2.imwrite(str(frames / 'ban_1792747926_1.png'), np.zeros((54, 96, 3), np.uint8))   # next map's ban screen
    bans, _ = read(tmp_path)
    assert calls == ['ban'] and len(bans) == 3


def test_rewritten_frame_is_read_again(day):
    tmp_path, frames, calls = day
    read(tmp_path); calls.clear()
    f = frames / 'ban_1792743994_1.png'
    cv2.imwrite(str(f), np.full((60, 100, 3), 200, np.uint8))                  # same name, other size and mtime
    read(tmp_path)
    assert calls == ['ban']


def test_same_size_new_mtime_is_read_again(day):
    tmp_path, frames, calls = day
    read(tmp_path); calls.clear()
    f = frames / 'potm_1792747000_1.png'
    st = f.stat(); os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    read(tmp_path)
    assert calls == ['potm']


def test_version_bump_and_new_word_lists_invalidate(day, monkeypatch):
    tmp_path, _, calls = day
    read(tmp_path); calls.clear()
    monkeypatch.setattr(AD, 'SCREENS_CACHE_VERSION', AD.SCREENS_CACHE_VERSION + 1)
    read(tmp_path)
    assert len(calls) == 4
    calls.clear()
    monkeypatch.setattr(SCR, 'word_lists', lambda: (LISTS[0], LISTS[1] + ['Aatlis'], LISTS[2]))   # 09:00 build
    read(tmp_path)
    assert len(calls) == 4


def test_digit_library_change_invalidates(day):
    tmp_path, _, calls = day
    read(tmp_path); calls.clear()
    lib = tmp_path / 'digit_lib'; lib.mkdir()
    cv2.imwrite(str(lib / '6__1023_a.png'), np.zeros((36, 28), np.uint8))       # a new '6' sample
    read(tmp_path)
    assert len(calls) == 4


def test_corrupt_or_foreign_cache_is_rebuilt(day, capsys):
    tmp_path, _, calls = day
    (tmp_path / AD.SCREENS_CACHE).write_text('{"version": 1, "stamp": "x", "fra', encoding='utf-8')   # killed mid-write
    read(tmp_path)
    assert len(calls) == 4 and 'unreadable' in capsys.readouterr().err
    calls.clear()
    read(tmp_path)
    assert calls == []


def test_deleted_frames_leave_the_cache_and_no_temp_file_stays(day):
    tmp_path, frames, _ = day
    read(tmp_path)
    (frames / 'ban_1792745398_1.png').unlink()
    bans, _ = read(tmp_path)
    cache = json.loads((tmp_path / AD.SCREENS_CACHE).read_text(encoding='utf-8'))
    assert 'ban_1792745398_1.png' not in cache['frames'] and len(bans) == 1
    assert not [p for p in os.listdir(tmp_path) if p.endswith('.tmp')]


def test_undecodable_frame_is_skipped_and_not_cached(day, capsys):
    tmp_path, frames, _ = day
    (frames / 'ban_1792749271_1.png').write_bytes(b'\x89PNG half written')
    bans, _ = read(tmp_path)
    assert len(bans) == 2 and 'cannot be read' in capsys.readouterr().err
    cache = json.loads((tmp_path / AD.SCREENS_CACHE).read_text(encoding='utf-8'))
    assert 'ban_1792749271_1.png' not in cache['frames']


def test_unwritable_cache_does_not_stop_the_assembly(day, monkeypatch, capsys):
    tmp_path, _, _ = day
    def fail(src, dst): raise PermissionError('locked by an antivirus scan')
    monkeypatch.setattr(AD.os, 'replace', fail)
    bans, cards = read(tmp_path)
    assert len(bans) == 2 and len(cards) == 1 and 'not written' in capsys.readouterr().err
    assert not [p for p in os.listdir(tmp_path) if p.endswith('.tmp')]
