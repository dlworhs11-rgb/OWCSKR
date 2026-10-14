"""(dev) Grab 1080p ban / POTM screens from a SOOP VOD through OBS (normal embed playback, nothing downloaded).
usage: python -I tools/grab_vod.py VOD_ID OUT_DIR SECONDS[:part]...
For each second: load the embed at that time, poll the OBS source until the expected screen appears, save it."""
import asyncio, os, sys, time
import sys as _sys; _sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import obs_setup, ocr_screens as S
from obs_client import OBS

vod, out, items = sys.argv[1], sys.argv[2], sys.argv[3:]
os.makedirs(out, exist_ok=True)
url = lambda sec: f'https://vod.sooplive.com/player/{vod}/embed?autoPlay=true&mutePlay=true&change_second={sec}'
obs_setup.start(url(0))


async def main():
    obs = await OBS().connect()
    for it in items:
        sec = int(it.split(':')[0])
        await obs.call('SetInputSettings', {'inputName': obs_setup.SOURCE, 'inputSettings': {'url': url(max(0, sec - 6))}, 'overlay': True})
        await obs.call('PressInputPropertiesButton', {'inputName': obs_setup.SOURCE, 'propertyName': 'refreshnocache'})
        t0, saved = time.time(), None
        while time.time() - t0 < 50:
            await asyncio.sleep(1.5)
            img = cv2.imdecode(np.frombuffer(await obs.screenshot(obs_setup.SOURCE), np.uint8), cv2.IMREAD_COLOR)
            k = S.screen_kind(img)
            if k:
                saved = os.path.join(out, f'{it.replace(":", "_")}_{k}.png'); cv2.imwrite(saved, img); break
        print(it, '->', saved or 'not found within 50 s', flush=True)
    await obs.close()

asyncio.run(main())
