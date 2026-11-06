"""Save slots (Gamedata/SaveGame/<slot>/): decode and summarize (read-only). Ported from modding/tools/save.

.sav codec (reverse engineered from FUN_00550860, the 'cmp::pc' mode-2 writer):
  byte0 = (sum of stream values) ^ 0x53; bytes1-4 = u32 length ^ 0x54555657;
  stream byte = bitrev8(counter) ^ 0xB9 ^ value, counter from 0x57; content = 8-byte blocks against a 256-entry
  dictionary (index, mask, changed bytes; full blocks replace the entry; a short last block ends with its length).
Level000.sav records (FUN_004c6e30): u16 block | u32 offset | u32 flags | payload; flags top byte = type
  (01/02/04/08 = 1/2/4/8 bytes, 10 = u32 length + buffer, 11 = pointer: u16 block + u32 offset).
  Block id = (module << 8) | block index, offset relative to that SNA block's base in Fix.sna + <level>.sna.
General000.sav: text lines: level, checkpoint, playtime (ms).
Meanings of the fixed offsets: docs/savegame.md in the modding repo.
"""
import os
import struct

from . import geo, level as L, sna

SIZES = {0x01: 1, 0x02: 2, 0x04: 4, 0x08: 8, 0x11: 6}
MANA, MANAMAX, GOLD, GOLDMAX, DEBUG = (0x0500, 0x4c1564), (0x0500, 0x4c1566), (0x0a00, 0x169e), (0x0a00, 0x16c4), (0x1100, 0x48b04)
HEALTH = 0x5eac                              # (0x0500) hp, hp max, hp max max (u8 each)
MAPDEST = range(0x4c15ec, 0x4c1614, 4)       # 10 map destination words, -2 = none
EPOCHS = range(0x4c1618, 0x4c1628, 4)        # 4 era-available words: 0 = the map skips that era
ARMOUR_NODES = [(0x4c1144, 7), (0x4c12d8, 5), (0x4c140c, 5)]
ARMOUR_PIECES = [[0x4c1214 + 0x1c * i for i in range(7)], [0x4c1380 + 0x1c * i for i in range(5)],
                 [0x4c14b4 + 0x1c * i for i in range(5)]]
FIXNAMES = {0x2210334: 'Global', 0x262c2a4: 'StdCamer', 0x26357f4: 'iDummy_PourCercles', 0x2636288: 'iDummy_PourBarils'}
INV_TYPES = {'Weapon', 'RestoreMP', 'RestoreHP', 'RestoreHPMP', 'MagicIce', 'MagicFire', 'MagicLightning', 'Object',
             'NotFound'}
# Global DsgVar meanings known from the cheat scripts and experiments (modding/docs/savegame-flags.md has more)
KNOWN_FLAGS = {0x3d: 'brave almanac', 0x43: 'number of standards', 0x26: 'jewel flag', 0x28: 'jewel flag',
               0x49: 'jewel flag', 0xc: 'camera focal cheat', 28: 'set in Torras TS1', 145: 'cleared in Torras TS1',
               191: 'dagger thief steal event', 219: 'got the map from Gogoud (brigand)', 233: 'map input enabled',
               0x79: 'first flight with Zatila', 147: 'statue breaks (manor)'}


def _bitrev(b):
    return int(f'{b:08b}'[::-1], 2)


_REV = [_bitrev(c) ^ 0xB9 for c in range(256)]


def decode(data):
    """.sav bytes -> plain bytes."""
    length = int.from_bytes(data[1:5], 'little') ^ 0x54555657
    s = bytes(x ^ _REV[(0x57 + i) & 0xff] for i, x in enumerate(data[5:]))
    dic = [bytearray([k] * 8) for k in range(256)]
    out, p = bytearray(), 0
    while len(out) < length:
        idx, mask = s[p], s[p + 1]
        p += 2
        blk = bytearray(dic[idx])
        for i in range(8):
            if mask >> i & 1:
                blk[i] = s[p]
                p += 1
        if length - len(out) >= 8:
            out += blk
            dic[idx] = blk
        else:
            out += blk[:s[p]]
            p += 1
    return bytes(out)


def records(raw):
    """[(block, offset, flags, payload bytes)]"""
    out, p = [], 0
    while p < len(raw):
        blk, off, flags = struct.unpack_from('<HII', raw, p)
        p += 10
        t = flags >> 24
        if t == 0x10:
            n = struct.unpack_from('<I', raw, p)[0]
            p += 4
        elif t in SIZES:
            n = SIZES[t]
        else:
            raise ValueError(f'unknown record type {t:#x} at {p - 10}')
        out.append((blk, off, flags, bytes(raw[p:p + n])))
        p += n
    return out


def _val(recs, key):
    r = recs.get(key)
    if not r:
        return None
    t = r[2] >> 24
    return int.from_bytes(r[3], 'little') if t in (1, 2, 4, 8) or (t == 0x10 and len(r[3]) <= 4) else r[3]


def slots(game):
    """Save slot folders that hold General000.sav + Level000.sav: [(slot name, folder, mtime)], newest first."""
    bases = [game.save_dir()]
    va = os.environ.get('LOCALAPPDATA')
    if va and os.name == 'nt' and bases[0]:          # a non-elevated game under Program Files saves to VirtualStore
        bases.append(os.path.join(va, 'VirtualStore', os.path.splitdrive(bases[0])[1].lstrip('\\/')))
    best = {}
    for base in filter(None, bases):
        if not os.path.isdir(base):
            continue
        for d in os.listdir(base):
            f = os.path.join(base, d)
            g = os.path.join(f, 'General000.sav')
            if os.path.isfile(g) and os.path.isfile(os.path.join(f, 'Level000.sav')):
                t = os.path.getmtime(g)
                if d not in best or t > best[d][2]:
                    best[d] = (d, f, t)
    return sorted(best.values(), key=lambda x: -x[2])


def header(folder):
    lines = decode(open(os.path.join(folder, 'General000.sav'), 'rb').read()).decode('latin-1').split('\r\n')
    return dict(level=lines[0], checkpoint=lines[1] if len(lines) > 1 else '',
                playtime=int(lines[2]) // 1000 if len(lines) > 2 and lines[2].isdigit() else None)


class _PersoInfo:
    """Name, stdGame and DsgVar layout of one perso (also invisible actors without 3D data)."""

    def __init__(self, w, so):
        self.perso = w.u32(so + 4)
        self.sg = w.u32(self.perso + 4)
        self.name = FIXNAMES.get(self.perso)
        if not self.name:
            try:
                self.name = geo.Perso(w, so).name
            except Exception:                         # noqa: BLE001 - persos without 3D data
                self.name = None
        self.dsg, self.buf = [], None
        brain = w.u32(self.perso + 0x10)
        mind = w.u32(brain) if brain and w.find(brain)[0] else None
        dsgmem = w.u32(mind + 0xc) if mind and w.find(mind)[0] else None
        if dsgmem and w.find(dsgmem)[0]:
            pp = w.u32(dsgmem)
            dv = w.u32(pp) if pp and w.find(pp)[0] else None
            self.buf = w.u32(dsgmem + 8)
            if dv and w.find(dv)[0]:
                info, n = w.u32(dv + 4), w.u32(dv + 0xc)
                for i in range(min(n or 0, 1024)):
                    self.dsg.append(tuple(w.u32(info + 16 * i + k) for k in (0, 4, 8)))


def _persos_with_names(w, names):
    """_PersoInfo for the superobjects whose perso is named in `names` (Global is a fix perso without 3D data)."""
    out = {}
    for (m, b, src), (base, data) in w.blocks.items():
        for off in range(0, len(data) - 4, 4):
            if struct.unpack_from('<I', data, off)[0] != 4:
                continue
            so = base + off
            p = w.u32(so + 4)
            if not p or not w.find(p)[0]:
                continue
            if FIXNAMES.get(p) in names and FIXNAMES[p] not in out:
                out[FIXNAMES[p]] = _PersoInfo(w, so)
    for so in geo.persos(w):
        try:
            n = geo.Perso(w, so).name
        except Exception:                             # noqa: BLE001
            continue
        if n in names and n not in out:
            out[n] = _PersoInfo(w, so)
    return out


def _inv_items(w):
    """Inventory item structs (INV module 0x0a): base -> (type name, offset of the max field)."""
    out = {}
    for (m, b, src), (base, data) in w.blocks.items():
        if m != 0x0a:
            continue
        end = 0
        for off in range(0, len(data) - 0x54, 4):
            if off < end:
                continue
            for poff, maxoff, size, kind in ((0x20, 0x28, 0x50, 9), (0x38, 0x40, 0xb0, 6)):
                sp = struct.unpack_from('<I', data, off + poff)[0]
                if struct.unpack_from('<I', data, off + 0x10)[0] == kind and sp == base + off + poff + 0x18 \
                        and w.cstr(sp) in INV_TYPES:
                    out[base + off] = (w.cstr(sp), maxoff)
                    end = off + size
                    break
    return out


def _inv_names(w, items, fix_lng):
    """Item base -> display name (install language) via Fix.lng's INV strings and the char* array in block 0x0a/0."""
    try:
        lb, ld = next((base & 0xffffffff, data) for m, b, base, data in sna.read_sna(fix_lng) if (m, b) == (0x0a, 1))
    except (OSError, StopIteration, TypeError):
        return {}
    _, d = next(((base, data) for (m, b, src), (base, data) in w.blocks.items() if (m, b) == (0x0a, 0)), (0, b''))
    ptrs = [o for o in range(0, len(d) - 4, 4) if lb <= struct.unpack_from('<I', d, o)[0] < lb + len(ld)]
    if not ptrs:
        return {}
    arr, out = ptrs[0], {}
    for b in items:
        it = w.u32(b - 8)
        ti = w.u16(it + 0x1c) if it and w.find(it)[0] else None
        if ti is None or arr + 4 * ti + 4 > len(d):
            continue
        v = struct.unpack_from('<I', d, arr + 4 * ti)[0]
        if lb <= v < lb + len(ld):
            out[b] = ld[v - lb:ld.index(b'\0', v - lb)].decode('cp1252')
    return out


def summary(game, folder):
    """Readable state of one slot (record shape: schema 'save'). Loads the slot's level (a few seconds once)."""
    h = header(folder)
    recs = {(r[0], r[1]): r for r in records(decode(open(os.path.join(folder, 'Level000.sav'), 'rb').read()))}
    w = L.load(game, h['level'])
    bases = {(m, b): base for (m, b, src), (base, data) in w.blocks.items()}
    hp = [_val(recs, (0x0500, HEALTH + i)) for i in range(3)]
    dest = [_val(recs, (0x0500, o)) for o in MAPDEST]
    out = dict(id=os.path.basename(folder), level=h['level'], checkpoint=h['checkpoint'], playtime=h['playtime'],
               modified=int(os.path.getmtime(os.path.join(folder, 'General000.sav'))),
               debug=_val(recs, DEBUG) == 1, health=hp[0], health_max=hp[1], health_maxmax=hp[2],
               mana=_val(recs, MANA), mana_max=_val(recs, MANAMAX), gold=_val(recs, GOLD), gold_max=_val(recs, GOLDMAX),
               eras=[i + 1 for i, o in enumerate(EPOCHS) if _val(recs, (0x0500, o))],
               map_destinations=[d for d in dest if d not in (None, 0xfffffffe)], records=len(recs))
    # inventory: carried slot pointers (HIE fix block 0x0601) -> item superobject -> INV object -> item base
    items = _inv_items(w)
    names = _inv_names(w, items, game.lng('Fix'))
    fix0a, fix06 = bases.get((0x0a, 0)), bases.get((6, 1))
    carried = set()
    for (b, o), r in recs.items():
        if b == 0x0601 and r[2] >> 24 == 0x11:
            tb, to = struct.unpack('<HI', r[3])
            if tb == 0x0601 and fix06 is not None:
                obj = w.u32(fix06 + to + 4)
                if obj and obj + 8 in items:
                    carried.add(obj + 8)
    inv, spells = [], []
    for b in sorted(items):
        typ, name = items[b][0], names.get(b, '')
        o = b - fix0a
        sel, cnt, mx = _val(recs, (0x0a00, o)), _val(recs, (0x0a00, o + 2)), _val(recs, (0x0a00, o + items[b][1]))
        if typ.startswith('Magic'):
            if b in carried:
                spells.append(dict(name=name or typ, element=typ[5:], selected=bool(sel)))
            continue
        if b not in carried and cnt in (None, 0, 65535):
            continue
        inv.append(dict(name=name or typ, type=typ, count=None if cnt in (None, 65535) else cnt, max=mx or None,
                        selected=bool(sel), carried=b in carried))
    out['inventory'], out['spells'] = inv, spells
    out['armour'] = []
    for n, ((node, npieces), pieces) in enumerate(zip(ARMOUR_NODES, ARMOUR_PIECES)):
        out['armour'].append(dict(n=n + 1, resistance=_val(recs, (0x0500, node + 0x1f)),
                                  damaged=bool(_val(recs, (0x0500, node + 0x1e))), pieces=npieces,
                                  pieces_damaged=[i + 1 for i, p in enumerate(pieces) if _val(recs, (0x0500, p + 0x14))]))
    # story flags: Global DsgVars that are set
    fix11 = bases.get((0x11, 0))
    g = _persos_with_names(w, {'Global'}).get('Global')
    flags = []
    if g and g.buf and fix11 is not None:
        for i, (off, ty, sv) in enumerate(g.dsg):
            v = _val(recs, (0x1100, g.buf - fix11 + off))
            if v and ty in (0, 2, 5) and not isinstance(v, bytes):
                flags.append(dict(index=i, value=v, note=KNOWN_FLAGS.get(i, '')))
    out['flags'] = flags
    return out
