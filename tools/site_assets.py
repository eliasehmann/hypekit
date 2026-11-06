"""Website assets for the toolkit page: app screenshots + the exe.

    python tools/site_assets.py [--game DIR] [--site ..\\website]

Starts the toolkit's server on a free port against a game folder (default: the English copy in
work/hypekit/game-EN, see disc_to_game.py), shoots a few pages with headless Edge (dark theme), writes
<site>/assets/toolkit/*.jpg (needs Pillow) and copies work/hypekit/dist/HypeToolkit.exe to <site>/downloads/.
Prints a short summary.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WS = os.path.dirname(REPO)
sys.path.insert(0, REPO)

SHOTS = [   # name, hash route (bare=1: no page heading, the content sits under the app's top bar), window height
    ('models', '#/models?category=figure&id={hype}&bare=1', 800),
    ('dialogue', '#/dialogue?level=toras&play={voice}&bare=1', 800),
    ('sounds', '#/sounds?kind=music&play={music}&bare=1', 800),
    ('textures', '#/textures?archive=Vignette&bare=1', 800),
]
EDGE = [r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', r'C:\Program Files\Microsoft\Edge\Application\msedge.exe']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', default=os.path.join(WS, 'work', 'hypekit', 'game-EN'))
    ap.add_argument('--site', default=os.path.join(WS, 'website'))
    a = ap.parse_args()
    from PIL import Image
    import hypekit
    from hypekit import server
    kit = hypekit.open(a.game)
    kit.build()
    kit.persos(wait=True)                              # the models page needs the character scan
    hype = next(r['id'] for r in kit.scanner.records if r['name'] == 'Hype' and r['level'] == 'fort')
    voice = kit.sounds(kind='voice', level='toras', limit=1)[0]['id']
    music = kit.sounds(kind='music', level='manoir', limit=1)[0]['id']
    srv, url = server.serve(kit, 0)
    edge = next(p for p in EDGE if os.path.exists(p))
    out = os.path.join(a.site, 'assets', 'toolkit')
    os.makedirs(out, exist_ok=True)
    prof = tempfile.mkdtemp(prefix='hypekit-shots-')
    try:
        for name, route, h in SHOTS:
            png = os.path.join(prof, name + '.png')
            subprocess.run([edge, '--headless=new', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                            '--run-all-compositor-stages-before-draw', '--hide-scrollbars', '--force-device-scale-factor=1.5',
                            '--autoplay-policy=no-user-gesture-required', f'--user-data-dir={prof}', f'--window-size=1280,{h}',
                            '--virtual-time-budget=25000', f'--screenshot={png}', url + route.format(hype=hype, voice=voice, music=music)],
                           capture_output=True, timeout=180)
            im = Image.open(png).convert('RGB')
            im.save(os.path.join(out, name + '.jpg'), quality=86, optimize=True, progressive=True)
            print(f'{name}.jpg {im.width}x{im.height} {os.path.getsize(os.path.join(out, name + ".jpg")) // 1024} KB')
    finally:
        srv.shutdown()
        srv.server_close()
        kit.close()
        shutil.rmtree(prof, ignore_errors=True)
    exe = os.path.join(WS, 'work', 'hypekit', 'dist', 'HypeToolkit.exe')
    if os.path.exists(exe):
        os.makedirs(os.path.join(a.site, 'downloads'), exist_ok=True)
        shutil.copy2(exe, os.path.join(a.site, 'downloads', 'HypeToolkit.exe'))
        print(f'downloads/HypeToolkit.exe {os.path.getsize(exe) / 1048576:.1f} MB, version {hypekit.__version__}')
    else:
        print('no exe: run tools/build_windows.ps1 first')


if __name__ == '__main__':
    main()
