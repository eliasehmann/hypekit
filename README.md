# hypekit

Read *Hype: The Time Quest* game data from your own install: sounds (with names, levels, speaker and line),
dialogue text and textures. It's pure Python with the standard library only, and it's read-only.

Three layers:

| Layer | What | Status |
|---|---|---|
| **core** (`hypekit/`) | decoders + SQLite catalog + Python API | M1 ✓ |
| **api** | CLI with `--json` ✓, local HTTP server, MCP (later) | M1 CLI ✓, M2 HTTP |
| **app** | web UI (HTML/JS, three.js) in a pywebview window, PyInstaller builds per OS | M2+ |

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
```

## CLI

```
python -m hypekit info | find <q> | sounds | lines | textures | levels | get <id> | export <id>... --out DIR
python -m hypekit sql "SELECT ..." | schema [sound|line|texture] | build [--force]
  --game DIR  --disc DIR (repeatable, .csb sound names)  --cache DIR  --limit N (0 = all)  --json
```

## IDs (stable)
- **sound:** `Bnk_<n>:<node>` (bank entry or track) or `apm:<file>` (stream)
- **line:** `<level>:<n>`
- **texture:** `Textures:<i>` / `Vignette:<i>`

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
