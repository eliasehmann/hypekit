"""The desktop app: the local server + a native window.

    python -m hypekit app [--game DIR] [--browser]

Window: pywebview if installed (WebView2 / WebKit / GTK-Qt, also what the packaged app uses), else an Edge or
Chrome/Chromium window in app mode (no tabs), else the default browser. The app ends when the window closes
(pywebview, Edge/Chrome); with the default browser it runs until Ctrl+C.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser

from . import server

TITLE = 'Hype Toolkit'


def _chromium():
    names = ['msedge', 'chrome', 'chromium', 'chromium-browser', 'google-chrome', 'brave']
    cands = [shutil.which(n) for n in names]
    if sys.platform == 'win32':
        for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), os.environ.get('LOCALAPPDATA')):
            if base:
                cands += [os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
                          os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe')]
    elif sys.platform == 'darwin':
        cands += ['/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
                  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
    return next((c for c in cands if c and os.path.isfile(c)), None)


def run(kit, browser=False, port=0):
    kit.build()
    srv, url = server.serve(kit, port)
    print(f'{TITLE}: {url}', flush=True)
    try:
        if not browser:
            try:
                import webview                        # pywebview
            except ImportError:
                webview = None
            if webview:
                webview.create_window(TITLE, url, width=1280, height=820, min_size=(900, 600))
                webview.start()
                return 0
            exe = _chromium()
            if exe:
                prof = os.path.join(tempfile.gettempdir(), 'hypekit-window')   # own profile: own window + process
                p = subprocess.Popen([exe, f'--app={url}', f'--user-data-dir={prof}', '--window-size=1280,820',
                                      '--no-first-run', '--no-default-browser-check'])
                p.wait()
                return 0
        webbrowser.open(url)
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0
    finally:
        srv.shutdown()
        srv.server_close()
        kit.close()
