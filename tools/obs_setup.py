"""Prepare OBS for OWCSKR capture.
usage:
  python -I tools/obs_setup.py config          # (OBS closed) enable obs-websocket on 127.0.0.1:4455 with a random local password
  python -I tools/obs_setup.py start [URL]     # launch OBS in the tray and create scene 'OWCSKR' with a hidden browser source
The browser source plays the SOOP page like a normal viewer (ads included); custom CSS stretches the <video> to 1920x1080.
"""
import asyncio, json, os, secrets, subprocess, sys, time
import sys as _sys; _sys.stdout.reconfigure(encoding='utf-8', errors='replace'); _sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # logs may contain names like 'Esperança'
sys.path.insert(0, os.path.dirname(__file__))
from obs_client import OBS, CONFIG
import platform_util as PU

SCENE, SOURCE, COLLECTION = 'OWCSKR', 'SOOP', 'OWCSKR'
LIVE_URL = 'https://play.sooplive.com/owesports/embed?autoPlay=true&mutePlay=true'   # official embed player: video only, full frame
CSS = ('body{background:#000!important;overflow:hidden!important}'
       'video{position:fixed!important;left:0!important;top:0!important;width:100vw!important;height:100vh!important;'
       'z-index:2147483647!important;object-fit:contain!important;background:#000!important}')


def config():
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    cur = {}
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding='utf-8') as f: cur = json.load(f)
    cur.update({'server_enabled': True, 'server_port': 4455, 'auth_required': True, 'alerts_enabled': False, 'first_load': False})
    if not cur.get('server_password'):
        cur['server_password'] = secrets.token_urlsafe(24)       # local-only key, never printed or committed
    with open(CONFIG, 'w', encoding='utf-8') as f: json.dump(cur, f, indent=2)
    print('obs-websocket enabled on 127.0.0.1:4455 (password stored only in OBS config)')


SCENES_DIR = os.path.join(PU.obs_config_dir(), 'basic', 'scenes')


def write_collection(url):
    """A separate scene collection file, so the user's own scenes are never touched."""
    import uuid
    path = os.path.join(SCENES_DIR, COLLECTION + '.json')
    if os.path.exists(path): return
    u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())
    item = {'name': SOURCE, 'source_uuid': u2, 'visible': True, 'locked': False, 'rot': 0.0, 'pos': {'x': 0.0, 'y': 0.0},
            'scale': {'x': 1.0, 'y': 1.0}, 'align': 5, 'bounds_type': 0, 'bounds_align': 0, 'bounds': {'x': 0.0, 'y': 0.0},
            'crop_left': 0, 'crop_top': 0, 'crop_right': 0, 'crop_bottom': 0, 'id': 1, 'group_item_backup': False}
    col = {'name': COLLECTION, 'current_scene': SCENE, 'current_program_scene': SCENE, 'scene_order': [{'name': SCENE}],
           'sources': [
               {'name': SCENE, 'uuid': u1, 'id': 'scene', 'versioned_id': 'scene', 'settings': {'id_counter': 1, 'custom_size': False, 'items': [item]},
                'enabled': True, 'muted': False, 'volume': 1.0, 'mixers': 0},
               {'name': SOURCE, 'uuid': u2, 'id': 'browser_source', 'versioned_id': 'browser_source',
                'settings': {'url': url, 'width': 1920, 'height': 1080, 'css': CSS, 'reroute_audio': True},
                'enabled': True, 'muted': True, 'volume': 1.0, 'mixers': 255}],
           'groups': [], 'quick_transitions': [], 'transitions': [], 'transition_duration': 300, 'current_transition': 'Fade'}
    os.makedirs(SCENES_DIR, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f: json.dump(col, f, ensure_ascii=False, indent=1)


def running():
    return PU.process_running(PU.OBS_PROC)


async def ensure_scene(url):
    obs = await OBS().connect()
    scenes = [s['sceneName'] for s in (await obs.call('GetSceneList'))['scenes']]
    if SCENE not in scenes:
        await obs.call('CreateScene', {'sceneName': SCENE})
    settings = {'url': url, 'width': 1920, 'height': 1080, 'css': CSS, 'reroute_audio': True, 'fps_custom': False, 'shutdown': False, 'restart_when_active': False}
    inputs = [i['inputName'] for i in (await obs.call('GetInputList'))['inputs']]
    if SOURCE in inputs:
        await obs.call('SetInputSettings', {'inputName': SOURCE, 'inputSettings': settings, 'overlay': True})
        await obs.call('PressInputPropertiesButton', {'inputName': SOURCE, 'propertyName': 'refreshnocache'})
    else:
        await obs.call('CreateInput', {'sceneName': SCENE, 'inputName': SOURCE, 'inputKind': 'browser_source', 'inputSettings': settings, 'sceneItemEnabled': True})
    await obs.call('SetInputMute', {'inputName': SOURCE, 'inputMuted': True})
    await obs.call('SetCurrentProgramScene', {'sceneName': SCENE})
    await obs.close()
    print('scene ready:', SCENE, '/', SOURCE, '->', url)


def clear_crash_marks():
    """live_capture force-closes OBS (tray mode turns a normal close into 'hide'), which leaves run markers in
    obs-studio/.sentinel; newer OBS then opens an 'unclean shutdown' dialog at the next start (ignoring
    --disable-shutdown-check) and the websocket never comes up. Only called while OBS is not running."""
    d = os.path.join(PU.obs_config_dir(), '.sentinel')
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.startswith('run_'):
                try: os.remove(os.path.join(d, f))
                except OSError: pass


def start(url):
    write_collection(url)
    if not running():
        clear_crash_marks()
        exe, cwd = PU.obs_command()
        flags = ['--collection', COLLECTION, '--scene', SCENE, '--minimize-to-tray', '--disable-shutdown-check']
        if PU.IS_WIN: flags.append('--disable-updater')          # the Linux build has no updater
        subprocess.Popen(exe + flags, cwd=cwd)
    for _ in range(60):                       # wait for the websocket server
        try:
            asyncio.run(ensure_scene(url)); return
        except Exception as e:
            last = e; print('waiting for OBS:', type(e).__name__, str(e)[:80], flush=True); time.sleep(2)
    raise SystemExit(f'could not reach OBS websocket: {last}')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'start'
    if cmd == 'config': config()
    elif cmd == 'start': start(sys.argv[2] if len(sys.argv) > 2 else LIVE_URL)
