"""hypekit: read Hype: The Time Quest's game data (sounds, dialogue, textures) as plain Python data.

    import hypekit
    kit = hypekit.open()                       # finds the install ($HYPEKIT_GAME, Ubi.ini, Program Files, Wine)
    kit.sounds('rajoth', kind='voice')         # -> [dict]  (records: see hypekit.schema)
    kit.lines(level='brigand2')
    kit.get('Bnk_12:3')                        # one record + links (voice <-> dialogue line)
    open('a.wav', 'wb').write(kit.wav('Bnk_12:3'))
    open('t.png', 'wb').write(kit.png('Textures:120'))
    kit.sql('SELECT speaker, count(*) FROM lines GROUP BY speaker')

Everything is read-only. Records are JSON-ready dicts with stable ids; the same calls back the CLI (python -m
hypekit) and the HTTP API. The catalog (SQLite) lives in the per-user cache and is rebuilt when the install changes.
"""
import builtins
import hashlib
import json
import os
import sqlite3
import threading

from . import catalog as C
from . import game as G
from . import sounds as S
from . import textures as X

__version__ = '0.1.0'
__all__ = ['open', 'Kit', 'NotFound', 'NotAvailable', '__version__']

NotAvailable = S.NotAvailable


class NotFound(KeyError):
    """No record with that id."""


def open(game=None, cache=None, discs=None, vgmstream=None, progress=None):  # noqa: A001 - public API name
    """Open an install. game: folder (default: auto-detect). discs: extra folders with Sound/*.csb (names)."""
    folder = game or G.find_game()
    if not folder:
        raise FileNotFoundError('no Hype install found: pass game=<folder> or set $HYPEKIT_GAME')
    return Kit(G.Game(folder), cache, G.find_discs() if discs is None else discs, vgmstream, progress)


def _like(q):
    return '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


class Kit:
    def __init__(self, game, cache=None, discs=(), vgmstream=None, progress=None):
        self.game = game
        key = hashlib.sha1(os.path.normcase(game.root).encode('utf-8')).hexdigest()[:10]
        self.cache_dir = cache or os.path.join(G.cache_root(), key)
        self.discs = list(discs)
        self.vgmstream = vgmstream
        self.progress = progress
        self.db_path = os.path.join(self.cache_dir, 'catalog.sqlite')
        self._lib = None
        self._db = None
        self._archives = {}
        self._lock = threading.RLock()

    # ---- setup -----------------------------------------------------------------------------------------------
    @property
    def library(self):
        """The loaded sounds.Library (decoding needs it)."""
        with self._lock:
            if self._lib is None:
                self._lib = S.Library(self.game.sound, self.cache_dir, self.vgmstream, self.discs).load(self.progress)
                self._by_id = {C.sound_id(s): s for s in self._lib}
            return self._lib

    def build(self, force=False):
        """Make sure the catalog is current; -> meta dict."""
        with self._lock:
            st = C.stamp(self.game, self.discs)
            if force or not C.is_current(self.db_path, st):
                if self._db:
                    self._db.close()
                    self._db = None
                C.build(self.db_path, self.game, self.library, st, self.progress)
            return self.meta()

    @property
    def db(self):
        with self._lock:
            if self._db is None:
                self.build()
                self._db = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True, check_same_thread=False)
                self._db.row_factory = sqlite3.Row
            return self._db

    def meta(self):
        m = dict(self.db.execute('SELECT key, value FROM meta')) if self._db else dict(
            sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True).execute('SELECT key, value FROM meta'))
        m['errors'] = json.loads(m.get('errors') or '[]')
        return m

    # ---- queries (-> list of dicts) --------------------------------------------------------------------------
    def sql(self, query, params=()):
        """Read-only SQL on the catalog."""
        with self._lock:
            return [_rec(r) for r in self.db.execute(query, params)]

    def sounds(self, query='', kind=None, level=None, speaker=None, limit=None):
        w, p = [], []
        if query:
            w.append("(title LIKE ? ESCAPE '\\' OR file_name LIKE ? ESCAPE '\\' OR text LIKE ? ESCAPE '\\' "
                     "OR group_name LIKE ? ESCAPE '\\')")
            p += [_like(query)] * 4
        if kind:
            w.append('kind = ?')
            p.append(kind)
        else:
            w.append("kind != 'music part'")
        if level:
            w.append('levels LIKE ?')
            p.append(f'%"{level}"%')
        if speaker:
            w.append('speaker LIKE ?')
            p.append(speaker)
        return self.sql('SELECT * FROM sounds' + _where(w) + ' ORDER BY rowid' + _limit(limit), p)

    def lines(self, query='', level=None, speaker=None, common=False, limit=None):
        w, p = [], []
        if query:
            w.append("text LIKE ? ESCAPE '\\'")
            p.append(_like(query))
        if level:
            w.append('level = ?')
            p.append(level)
        if speaker:
            w.append('speaker LIKE ?')
            p.append(speaker)
        if not common:
            w.append('common = 0')
        return self.sql('SELECT * FROM lines' + _where(w) + ' ORDER BY rowid' + _limit(limit), p)

    def textures(self, query='', archive=None, limit=None):
        w, p = [], []
        if query:
            w.append("path LIKE ? ESCAPE '\\'")
            p.append(_like(query))
        if archive:
            w.append('archive = ?')
            p.append(archive)
        return self.sql('SELECT * FROM textures' + _where(w) + ' ORDER BY rowid' + _limit(limit), p)

    def levels(self):
        lv = self.sql('SELECT level, count(*) AS lines FROM lines WHERE common = 0 GROUP BY level ORDER BY level')
        from .soundnames import level_label, place_of
        for r in lv:
            r['place'] = place_of(r['level'])
            r['label'] = level_label(r['level'])
        return lv

    def find(self, query, limit=20):
        """Search everything: {'sounds': [...], 'lines': [...], 'textures': [...]}."""
        return dict(sounds=self.sounds(query, limit=limit), lines=self.lines(query, limit=limit),
                    textures=self.textures(query, limit=limit))

    def kind_of(self, rid):
        for t in ('sounds', 'textures', 'lines'):
            if self.db.execute(f'SELECT 1 FROM {t} WHERE id = ?', (rid,)).fetchone():
                return t[:-1]
        raise NotFound(rid)

    def get(self, rid):
        """One record with its links: sound -> 'lines', line -> 'sounds', track -> 'parts' expanded to titles."""
        k = self.kind_of(rid)
        r = self.sql(f'SELECT * FROM {k}s WHERE id = ?', (rid,))[0]
        r['type'] = k
        if k == 'sound':
            r['lines'] = self.sql('SELECT l.* FROM sound_lines j JOIN lines l ON l.id = j.line_id '
                                  'WHERE j.sound_id = ? ORDER BY l.rowid', (rid,))
        elif k == 'line':
            r['sounds'] = self.sql('SELECT s.id, s.title, s.seconds FROM sound_lines j JOIN sounds s '
                                   'ON s.id = j.sound_id WHERE j.line_id = ?', (rid,))
        return r

    # ---- payloads (bytes) ------------------------------------------------------------------------------------
    def sound(self, rid):
        """The sounds.Sound object (for decode())."""
        self.library
        s = self._by_id.get(rid)
        if s is None:
            raise NotFound(rid)
        return s

    def wav(self, rid):
        return self.library.wav_bytes(self.sound(rid), self.progress)

    def png(self, rid, level=0):
        arch, _, idx = rid.partition(':')
        with self._lock:
            if arch not in self._archives:
                p = self.game.archives().get(arch)
                if not p:
                    raise NotFound(rid)
                self._archives[arch] = X.Archive(p, arch)
            a = self._archives[arch]
        if not idx.isdigit() or int(idx) >= len(a.entries):
            raise NotFound(rid)
        return a.png(int(idx), level)

    def export(self, rid, dest='.'):
        """Write a sound as .wav or a texture as .png. dest: file path, or a folder (readable file name). -> path."""
        k = self.kind_of(rid)
        if k == 'sound':
            name, data = self.sound(rid).file_name(), self.wav(rid)
        elif k == 'texture':
            r = self.sql('SELECT path FROM textures WHERE id = ?', (rid,))[0]
            name, data = f"{r['path'].replace('/', '_').rsplit('.', 1)[0]}.png", self.png(rid)
        else:
            raise NotAvailable('lines have no payload: use get()')
        path = os.path.join(dest, name) if os.path.isdir(dest) else dest
        with builtins.open(path, 'wb') as f:
            f.write(data)
        return path

    def close(self):
        with self._lock:
            if self._db:
                self._db.close()
                self._db = None
            for a in self._archives.values():
                a.close()
            self._archives.clear()


def _rec(row):
    d = dict(row)
    for k in ('levels', 'parts'):
        if isinstance(d.get(k), str) and d[k].startswith('['):
            d[k] = json.loads(d[k])
    if 'common' in d:
        d['common'] = bool(d['common'])
    return d


def _where(w):
    return (' WHERE ' + ' AND '.join(w)) if w else ''


def _limit(n):
    return f' LIMIT {int(n)}' if n else ''
