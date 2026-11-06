"""The catalog: one SQLite file per install with every sound, dialogue line and texture, plus the links between them.

Tables (see schema.py for the JSON shapes, which use the same column names):
  meta(key, value)                       schema version, game folder, source stamp
  sounds(id, kind, title, ...)           id 'Bnk_<n>:<node>' (bank entry or track) or 'apm:<file>' (stream)
  lines(id, level, n, dialog, ...)       id '<level>:<n>'
  textures(id, archive, idx, path, ...)  id '<Textures|Vignette>:<index>'
  sound_lines(sound_id, line_id)         a voice sound and the dialogue line(s) it speaks
Other tools may read the file directly (read-only); it is rebuilt when the install changes.
"""
import glob
import json
import os
import sqlite3
import time

from . import text as T
from . import textures as X

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sounds (id TEXT PRIMARY KEY, kind TEXT, title TEXT, bank TEXT, node TEXT, file_name TEXT, format TEXT,
  seconds REAL, rate INTEGER, channels INTEGER, size INTEGER, volume INTEGER, loop INTEGER, loop_start REAL,
  levels TEXT, group_name TEXT, speaker TEXT, dialog TEXT, text TEXT, part TEXT, parts TEXT);
CREATE TABLE lines (id TEXT PRIMARY KEY, level TEXT, n INTEGER, dialog TEXT, speaker TEXT, text TEXT, common INTEGER);
CREATE TABLE textures (id TEXT PRIMARY KEY, archive TEXT, idx INTEGER, path TEXT, size INTEGER, width INTEGER,
  height INTEGER, format TEXT, mips INTEGER, error TEXT);
CREATE TABLE sound_lines (sound_id TEXT, line_id TEXT, PRIMARY KEY (sound_id, line_id));
CREATE INDEX lines_dialog ON lines (level, dialog);
CREATE INDEX sounds_kind ON sounds (kind);
"""


def sound_id(s):
    return f'apm:{s.name}' if s.codec == 'stream' else f'{s.bank}:{s.index}'


def sound_row(s):
    return dict(id=sound_id(s), kind=s.kind, title=s.title, bank=s.bank, node=str(s.index), file_name=s.name,
                format=s.format, seconds=None if s.seconds is None else round(s.seconds, 3), rate=s.rate,
                channels=s.channels, size=s.size, volume=s.volume, loop=int(bool(s.loop)),
                loop_start=s.loop_start() if s.codec == 'seq' else None, levels=json.dumps(s.levels),
                group_name=s.group or '', speaker=s.speaker or '', dialog=s.dialog or '', text=s.text or '',
                part=s.part or '', parts=json.dumps([sound_id(p) for p in s.parts]))


def stamp(game, extra=()):
    """Sizes + mtimes of every source file: changes when the install (or a disc copy) changes."""
    fs = glob.glob(os.path.join(game.sound, '*')) + glob.glob(os.path.join(game.levels, '*', '*.lng')) + \
        glob.glob(os.path.join(game.levels, '*', '*.snd')) + glob.glob(os.path.join(game.levels, 'Fix.*')) + \
        list(game.archives().values())
    for d in extra:
        fs += glob.glob(os.path.join(d, 'Sound', '*.csb')) + glob.glob(os.path.join(d, 'Sound', '*', '*.csb'))
    h = SCHEMA_VERSION
    for f in sorted(fs):
        st = os.stat(f)
        h = (h * 1000003 + st.st_size * 31 + int(st.st_mtime)) & 0xffffffffffff
    return f'{h:012x}'


def is_current(path, st):
    if not os.path.exists(path):
        return False
    try:
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
            m = dict(db.execute('SELECT key, value FROM meta'))
        return m.get('schema') == str(SCHEMA_VERSION) and m.get('stamp') == st
    except sqlite3.Error:
        return False


def build(path, game, library, st, progress=None):
    """Write the catalog for game (library = a loaded sounds.Library). Atomic: writes a temp file, then renames."""
    t0 = time.time()
    tmp = path + '.tmp'
    if os.path.exists(tmp):
        os.remove(tmp)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(DDL)
    rows = [sound_row(s) for s in library]
    cols = list(rows[0]) if rows else []
    db.executemany(f'INSERT OR REPLACE INTO sounds ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})',
                   [tuple(r[c] for c in cols) for r in rows])
    if progress:
        progress(f'{len(rows)} sounds')
    per = T.read_levels(game)
    lines = [x for v in per.values() for x in v]
    db.executemany('INSERT INTO lines VALUES (?,?,?,?,?,?,?)',
                   [(x.id, x.level, x.n, x.dialog, x.speaker, x.text, int(x.common)) for x in lines])
    if progress:
        progress(f'{len(lines)} dialogue lines')
    by = {}
    for x in lines:
        if x.dialog:
            by.setdefault((x.level, x.dialog), []).append(x.id)
    links = set()
    for s in library:
        if s.kind == 'voice' and s.dialog:
            for lv in s.levels:
                for lid in by.get((lv, s.dialog), ()):
                    links.add((sound_id(s), lid))
    db.executemany('INSERT INTO sound_lines VALUES (?,?)', sorted(links))
    ntex = 0
    for name, p in game.archives().items():
        a = X.Archive(p, name)
        try:
            ts = a.textures()
        finally:
            a.close()
        db.executemany('INSERT INTO textures VALUES (?,?,?,?,?,?,?,?,?,?)',
                       [(t.id, t.archive, t.index, t.path, t.size, t.width, t.height, t.format, t.mips, t.error)
                        for t in ts])
        ntex += len(ts)
    if progress:
        progress(f'{ntex} textures, {len(links)} voice/line links')
    meta = dict(schema=SCHEMA_VERSION, stamp=st, game=game.root, built=int(time.time()),
                seconds=round(time.time() - t0, 1), sounds=len(rows), lines=len(lines), textures=ntex,
                links=len(links), errors=json.dumps(library.errors[:20]))
    db.executemany('INSERT INTO meta VALUES (?,?)', [(k, str(v)) for k, v in meta.items()])
    db.commit()
    db.close()
    os.replace(tmp, path)
    return meta
