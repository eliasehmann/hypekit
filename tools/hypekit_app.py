"""Entry point of the packaged app (PyInstaller): `HypeToolkit.exe` = `python -m hypekit app`, and
`HypeToolkit.exe <command> ...` runs any CLI command. A windowed build has no console, so errors go to
<cache>/hypekit.log (%LOCALAPPDATA%\\hypekit\\hypekit.log)."""
import os
import sys
import traceback

from hypekit import cli, game

if __name__ == '__main__':
    if sys.stderr is None or sys.stdout is None:           # windowed build
        os.makedirs(game.cache_root(), exist_ok=True)
        log = open(os.path.join(game.cache_root(), 'hypekit.log'), 'a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    args = sys.argv[1:] or ['app']
    try:
        code = cli.main(args)
    except Exception:                                       # noqa: BLE001 - logged for the windowed build
        traceback.print_exc()
        code = 1
    sys.exit(code)
