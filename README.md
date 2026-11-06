# hypekit

Read *Hype: The Time Quest* game data from your own install: sounds (with names, levels, speaker and line),
dialogue text, textures, 3D characters with their animations, and save games. It's pure Python with the standard library only, and it's read-only.

Three layers:

| Layer | What | Status |
|---|---|---|
| **core** (`hypekit/`) | decoders + SQLite catalog + Python API; characters → glTF | M1 ✓, M3 ✓ |
| **api** | CLI with `--json`, local HTTP API (`server.py`), MCP later | M1 CLI ✓, M2 HTTP ✓ |
| **app** | web UI (`hypekit/web/`: plain HTML/JS, three.js) in a native window | M2 ✓, M3 ✓ Models, M4 ✓ Saves |
| **build** | standalone Windows app (pywebview + PyInstaller, no Python needed) | M4 ✓ |

Next: M5 own MPEG decoder, macOS/Linux builds (GitHub Actions), MCP wrapper, write operations.

## App

```
python -m hypekit app          # window: pywebview if installed, else Edge/Chrome app mode, else the browser
python -m hypekit serve        # just the server: http://127.0.0.1:8765/
```
Deep links: `#/sounds?kind=voice&level=toras`, `#/models?id=fort:94c230c&state=5`, `#/script?level=toras&line=toras:5`, `?play=<sound id>` on any page.
Keys: space = play/pause, `/` = search, Esc = close the panel.

HTTP API (GET, JSON): `/api/info`, `/api/find?q=`, `/api/sounds|lines|textures?q=&...&limit=&offset=`,
`/api/levels`, `/api/script/<level>`, `/api/persos?q=&level=`, `/api/perso/<id>`, `/api/get/<id>`, `/api/schema`.
Payloads: `/api/wav/<id>`, `/api/png/<id>`, `/api/glb/<perso id>?state=N` (all support Range). The server binds 127.0.0.1 only.

## Windows build

```
powershell -File tools\fetch_wheels.ps1            # once: wheels via PowerShell (pip can't get through the TLS proxy)
python -m venv ..\work\hypekit\venv
..\work\hypekit\venv\Scripts\python -m pip install --no-index --find-links ..\work\hypekit\wheels pywebview pyinstaller
powershell -File tools\build_windows.ps1           # -> ..\work\hypekit\dist\HypeToolkit\HypeToolkit.exe + HypeToolkit-win64.zip
```
About 45 MB (20 MB zipped). It bundles vgmstream-cli (its COPYING is included) and no game files. On first start without a
detectable install it asks for the game folder and remembers it. `HypeToolkit.exe <command>` runs CLI commands.
Windowed build: errors go to `%LOCALAPPDATA%\hypekit\hypekit.log`; the cache is `%LOCALAPPDATA%\hypekit`.
Python 3.10 pins: pythonnet 3.0.5, clr_loader 0.2.9, pycparser 2.23 (newer ones need 3.11).

## Python

```python
import hypekit
kit = hypekit.open()                       # or hypekit.open(r'D:\Games\Hype')
kit.sounds('ragoth', kind='voice')         # list of dicts (see `hypekit schema`)
kit.lines(level='brigand2', speaker='GUSTUS')
kit.get('Bnk_116:0')                       # record + linked dialogue lines
open('a.wav', 'wb').write(kit.wav('Bnk_116:0'))
open('t.png', 'wb').write(kit.png('Vignette:0'))
kit.sql('SELECT speaker, count(*) FROM lines GROUP BY speaker')
kit.persos('granslak', wait=True)          # characters (first call scans every level, ~1 min, then cached)
kit.perso('fort:94c230c')['animations']   # Hype's states
open('hype.glb', 'wb').write(kit.glb('fort:94c230c', state=5))
kit.saves()                                # slots, newest first
kit.save('SaveGame3')                      # health, mana, gold, inventory, spells, armour, story flags
```

## CLI

```
python -m hypekit info | find <q> | sounds | lines | textures | levels | get <id> | export <id>... --out DIR
python -m hypekit persos [q] [--level L] [--all] | glb <perso id> [--state N] [--out FILE]
python -m hypekit saves | save <slot>
python -m hypekit sql "SELECT ..." | schema [sound|line|texture|perso|save] | build [--force]
  --game DIR  --disc DIR (repeatable, .csb sound names)  --cache DIR  --limit N (0 = all)  --json
```

## IDs (stable)
- **sound:** `Bnk_<n>:<node>` (bank entry or track) or `apm:<file>` (stream)
- **line:** `<level>:<n>`
- **texture:** `Textures:<i>` / `Vignette:<i>`
- **perso** (character placement): `<level>:<superobject hex>`, e.g. `fort:94c230c` = Hype in the Fortress

## Where things come from
- **Game:** `$HYPEKIT_GAME`, then `Ubi.ini` `Directory=`, Program Files, Wine/Proton prefixes. Lookups are case-insensitive.
- **Sound designer names (.csb):** only on the disc. Pass the disc folders with `--disc` or `$HYPEKIT_DISCS`.
- **Ubi MPEG (voices, music):** decoded with `vgmstream-cli`, from `$HYPEKIT_VGMSTREAM`, `vendor/vgmstream/`, the
  workspace `sources/tools/vgmstream` or `PATH`. MPEG lengths (`seconds`) stay `null` until a bank has been decoded once.
- **Cache:** catalog and decoded files live in `$HYPEKIT_CACHE`, else `work/hypekit` in the dev workspace, else
  `%LOCALAPPDATA%\hypekit`, `~/Library/Caches/hypekit` or `~/.cache/hypekit`. The catalog is rebuilt when the
  install changes, which takes about 2 s.

## Tests
`python -m unittest discover -s tests` uses the auto-detected install and skips everything without one.
