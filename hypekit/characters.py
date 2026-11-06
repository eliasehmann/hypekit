"""Characters ("persos": figures with states and animations) of every level, scanned once and cached as JSON.

A scan loads each level (pure-Python LZO, ~3 s per level, ~2 min for an install), so it runs in a background
thread; status() reports progress. Records: see schema.py 'perso'. The same figure (instance name) appears in
several levels; each placement is its own record.
"""
import glob
import json
import os
import threading
import time

from . import geo, level

VERSION = 1


def stamp(game):
    h = VERSION
    for f in sorted(glob.glob(os.path.join(game.levels, '*', '*.sna')) + glob.glob(os.path.join(game.levels, 'Fix.sna'))):
        st = os.stat(f)
        h = (h * 1000003 + st.st_size * 31 + int(st.st_mtime)) & 0xffffffffffff
    return f'{h:012x}'


def scan_level(w):
    out = []
    for so in geo.persos(w):
        try:
            p = geo.Perso(w, so)
            states = p.states()
            an = p.anim(p.state_initial)
        except (TypeError, KeyError, ValueError, IndexError):
            continue
        out.append(dict(id=f'{w.level}:{so:x}', level=w.level, so=f'{so:x}', name=p.name or '',
                        family=f'{p.family:x}', states=len(states), parts=len(p.parts),
                        frames=an['nframes'] if an else 0, fps=(an['speed'] or 30) if an else 0))
    return out


class Scanner:
    def __init__(self, game, cache_dir):
        self.game, self.cache_dir = game, cache_dir
        self.path = os.path.join(cache_dir, f'persos_{stamp(game)}.json')
        self.lock = threading.Lock()
        self.thread = None
        self.done = self.total = 0
        self.current = ''
        self.error = ''
        self.records = None
        if os.path.exists(self.path):
            try:
                self.records = json.load(open(self.path, encoding='utf-8'))
            except ValueError:
                self.records = None

    def status(self):
        state = 'ready' if self.records is not None else 'scanning' if self.thread and self.thread.is_alive() else \
            'error' if self.error else 'idle'
        return dict(state=state, done=self.done, total=self.total, level=self.current, error=self.error,
                    count=len(self.records) if self.records is not None else 0)

    def start(self):
        """Start the background scan if needed; -> status()."""
        with self.lock:
            if self.records is None and not (self.thread and self.thread.is_alive()):
                self.error = ''
                self.thread = threading.Thread(target=self._run, daemon=True, name='hypekit-persos')
                self.thread.start()
        return self.status()

    def run(self):
        """Scan in this thread (CLI); -> records."""
        if self.records is None:
            self._run()
        if self.error:
            raise RuntimeError(self.error)
        return self.records

    def _run(self):
        try:
            lvs = self.game.model_levels()
            self.total, self.done, recs, t0 = len(lvs), 0, [], time.time()
            for lv in lvs:
                self.current = lv
                try:
                    recs += scan_level(level.World(self.game, lv))
                except (OSError, ValueError, KeyError) as ex:
                    recs.append(dict(id=f'{lv}:error', level=lv, so='', name='', family='', states=0, parts=0,
                                     frames=0, fps=0, error=str(ex)))
                self.done += 1
            recs = [r for r in recs if not r.get('error')]
            os.makedirs(self.cache_dir, exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(recs, f, ensure_ascii=False)
            os.replace(tmp, self.path)
            self.records = recs
            self.current = f'{time.time() - t0:.0f} s'
        except Exception as ex:                       # noqa: BLE001 - reported through status()
            self.error = f'{type(ex).__name__}: {ex}'
