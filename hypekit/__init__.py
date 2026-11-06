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
from . import characters as P
from . import game as G
from . import sounds as S
from . import textures as X

__version__ = '1.0.0'
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
        self._persos = None
        self._texmap = None
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

    def sounds(self, query='', kind=None, level=None, speaker=None, limit=None, offset=0):
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
        return self.sql('SELECT * FROM sounds' + _where(w) + ' ORDER BY rowid' + _limit(limit, offset), p)

    def lines(self, query='', level=None, speaker=None, common=False, limit=None, offset=0):
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
        return self.sql('SELECT * FROM lines' + _where(w) + ' ORDER BY rowid' + _limit(limit, offset), p)

    def textures(self, query='', archive=None, limit=None, offset=0):
        w, p = [], []
        if query:
            w.append("path LIKE ? ESCAPE '\\'")
            p.append(_like(query))
        if archive:
            w.append('archive = ?')
            p.append(archive)
        return self.sql('SELECT * FROM textures' + _where(w) + ' ORDER BY rowid' + _limit(limit, offset), p)

    def levels(self):
        """Levels in game order (place by place; 'Fix' = shared text first), with line counts and place names."""
        from .soundnames import PLACES, level_label, place_of
        order = {lv: i for i, lv in enumerate(x for _, lvs in PLACES for x in lvs.split())}
        lv = self.sql('SELECT level, count(*) AS lines FROM lines WHERE common = 0 GROUP BY level')
        lv.sort(key=lambda r: (r['level'] != 'Fix', order.get(r['level'], 999), r['level']))
        for r in lv:
            r['place'] = place_of(r['level'])
            r['label'] = level_label(r['level'])
        return lv

    def script(self, level):
        """All lines of one level in order, each with 'sounds': [voice sound ids] (for a script view)."""
        rows = self.sql('SELECT l.*, group_concat(j.sound_id) AS sound_ids FROM lines l LEFT JOIN sound_lines j '
                        'ON j.line_id = l.id WHERE l.level = ? GROUP BY l.id ORDER BY l.n', (level,))
        for r in rows:
            ids = r.pop('sound_ids', None)
            r['sounds'] = sorted(ids.split(',')) if ids else []
        return rows

    def count(self, table):
        return self.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]

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

    # ---- characters (3D) -------------------------------------------------------------------------------------
    @property
    def scanner(self):
        with self._lock:
            if self._persos is None:
                self._persos = P.Scanner(self.game, self.cache_dir)
            return self._persos

    def persos_status(self, start=True):
        """Character scan: {'state': ready|scanning|idle|error, done, total, level, count}; start=True starts it."""
        return self.scanner.start() if start else self.scanner.status()

    def persos(self, query='', level=None, named=True, wait=False):
        """Character records (see schema 'perso'); None while the background scan runs (wait=True: scan here)."""
        recs = self.scanner.run() if wait else self.scanner.records
        if recs is None:
            self.scanner.start()
            return None
        q = (query or '').lower()
        return [r for r in recs if (not named or r['name']) and (not level or r['level'] == level)
                and (not q or q in r['name'].lower() or q in r['level'].lower())]

    def perso(self, rid):
        """One character record + 'animations': [{index (state), frames, fps, initial}] (loads the level: a few seconds)."""
        from . import geo, level as L
        lv, _, so = rid.partition(':')
        recs = [r for r in (self.scanner.records or []) if r['id'] == rid]
        try:
            w = L.load(self.game, lv)
            p = geo.Perso(w, int(so, 16))
        except (FileNotFoundError, ValueError, TypeError, KeyError) as ex:
            raise NotFound(rid) from ex
        r = dict(recs[0]) if recs else dict(id=rid, level=lv, so=so, name=p.name or '')
        r['type'] = 'perso'
        r['animations'] = []
        for i, st in enumerate(p.states()):
            an = p.anim(st)
            if an and an['nframes']:
                r['animations'].append(dict(index=i, frames=an['nframes'], fps=an['speed'] or 30,
                                        initial=st == p.state_initial))
        return r

    def _texture_rgba(self, name):
        """Texture by the name a material uses ('Hype/hype_corps.tga', any slash or case) -> (w, h, RGBA) or None."""
        with self._lock:
            if self._texmap is None:
                self._texmap = {}
                p = self.game.archives().get('Textures')
                if p:
                    self._archives.setdefault('Textures', X.Archive(p, 'Textures'))
                    for i, (path, *_r) in enumerate(self._archives['Textures'].entries):
                        self._texmap.setdefault(path.lower().rsplit('.', 1)[0], i)
            a = self._archives.get('Textures')
        key = name.replace('\\', '/').lower().rsplit('.', 1)[0]
        i = self._texmap.get(key)
        if i is None:
            return None
        try:
            return a.rgba(i)
        except ValueError:
            return None

    def glb(self, rid, state=None):
        """GLB bytes of a character (state index or its initial state); cached on disk."""
        from . import level as L
        from . import models as M
        lv, _, so = rid.partition(':')
        d = os.path.join(self.cache_dir, 'glb', self.scanner.path.rsplit('_', 1)[-1].split('.')[0])
        f = os.path.join(d, f'{lv}_{so}_{"i" if state is None else int(state)}.glb')
        if os.path.exists(f):
            with builtins.open(f, 'rb') as fh:
                return fh.read()
        try:
            data = M.perso_glb(L.load(self.game, lv), int(so, 16), self._texture_rgba, state)
        except (FileNotFoundError, ValueError, TypeError, KeyError) as ex:
            raise NotFound(rid) from ex
        except IndexError as ex:
            raise NotAvailable(f'{rid}: no state {state}') from ex
        os.makedirs(d, exist_ok=True)
        with builtins.open(f + '.tmp', 'wb') as fh:
            fh.write(data)
        os.replace(f + '.tmp', f)
        return data

    # ---- save slots ------------------------------------------------------------------------------------------
    def saves(self):
        """Save slots, newest first: [{id, level, place, checkpoint, playtime (s), modified (unix time)}] (fast)."""
        from . import saves as V
        from .soundnames import place_of
        out = []
        for slot, folder, mtime in V.slots(self.game):
            try:
                h = V.header(folder)
            except (OSError, ValueError, IndexError):
                continue
            out.append(dict(id=slot, level=h['level'], place=place_of(h['level']), checkpoint=h['checkpoint'],
                            playtime=h['playtime'], modified=int(mtime)))
        return out

    def save(self, slot):
        """One slot in full (schema 'save'): stats, inventory, spells, armour, story flags. Loads its level once."""
        from . import saves as V
        from .soundnames import place_of
        folder = next((f for s, f, _ in V.slots(self.game) if s == slot), None)
        if not folder:
            raise NotFound(slot)
        r = V.summary(self.game, folder)
        r['place'] = place_of(r['level'])
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


def _limit(n, offset=0):
    return f' LIMIT {int(n)} OFFSET {int(offset or 0)}' if n else ''
