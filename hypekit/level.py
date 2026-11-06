"""A loaded level: Fix.sna + <level>.sna blocks in one address space, plus the level's pointer relocations (.rtb).

Pure-Python LZO makes a load take a few seconds, so Fix's blocks are decoded once and shared, and the last few
levels stay in memory (see load()).
"""
import collections
import os
import re
import struct
import threading

from . import sna

_FIX = {}                     # (path, size, mtime) -> {(mod, id, 'fix'): (base, data)}
_LEVELS = collections.OrderedDict()
_LOCK = threading.Lock()
KEEP = 3                      # levels kept in memory


def read_rtb(path):
    """Relocation table: [(module, block, count, header offset, compressed size, [(addr, tmod, tblock, x, y)])]."""
    d = open(path, 'rb').read()
    p, out = 1, []
    for _ in range(d[0]):
        mod, bid, n = d[p], d[p + 1], struct.unpack_from('<I', d, p + 2)[0]
        p += 6
        hdr = p
        comp, cs, _, ds, _ = struct.unpack_from('<5I', d, p)
        p += 20
        raw = d[p:p + cs]
        p += cs
        data = sna.lzo1x_decompress(raw, ds) if comp else raw
        out.append((mod, bid, n, hdr, cs, [struct.unpack_from('<IBBBB', data, 8 * k) for k in range(n)]))
    return out


def _key(path):
    st = os.stat(path)
    return path, st.st_size, int(st.st_mtime)


class World:
    """Blocks of Fix + one level: find(addr) -> ((mod, id, src), offset); u32/u16/cstr readers."""

    def __init__(self, game, level):
        self.level = level
        fix = game.ci_level_file('Fix.sna')
        lv = game.ci_level_file(level, level + '.sna')
        rtb = game.ci_level_file(level, level + '.rtb')
        if not (fix and lv and rtb):
            raise FileNotFoundError(f'level {level}: Fix.sna / {level}.sna / {level}.rtb missing')
        k = _key(fix)
        if k not in _FIX:
            _FIX.clear()
            _FIX[k] = {(m, b, 'fix'): (base & 0xffffffff, data) for m, b, base, data in sna.read_sna(fix) if data}
        self.blocks = dict(_FIX[k])
        for m, b, base, data in sna.read_sna(lv):
            if data:
                self.blocks[(m, b, level)] = (base & 0xffffffff, data)
        self.lvlrtb = read_rtb(rtb)
        self.ptrs = {a: (tm, tb) for *_, ents in self.lvlrtb for a, tm, tb, _, _ in ents}
        self._ranges = sorted((base, base + len(data), key) for key, (base, data) in self.blocks.items())

    def find(self, addr):
        if addr is None:
            return None, None
        for lo, hi, key in self._ranges:
            if lo <= addr < hi:
                return key, addr - lo
        return None, None

    def u32(self, addr):
        k, o = self.find(addr)
        return struct.unpack_from('<I', self.blocks[k][1], o)[0] if k else None

    def u16(self, addr):
        k, o = self.find(addr)
        return struct.unpack_from('<H', self.blocks[k][1], o)[0] if k else None

    def cstr(self, addr):
        k, o = self.find(addr)
        return re.match(rb'[\x20-\x7e]*', self.blocks[k][1][o:o + 80]).group().decode() if k else None


def load(game, level):
    """Cached World of game's level (thread-safe; the last KEEP levels stay loaded)."""
    key = (game.root, level)
    with _LOCK:
        if key in _LEVELS:
            _LEVELS.move_to_end(key)
            return _LEVELS[key]
        w = World(game, level)
        _LEVELS[key] = w
        while len(_LEVELS) > KEEP:
            _LEVELS.popitem(last=False)
        return w
