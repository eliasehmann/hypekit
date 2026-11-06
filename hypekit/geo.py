"""Hype's 3D data (Montreal engine) from a loaded level (level.World): superobjects, characters (Perso), their
states/animations, physical objects, geometric objects, materials and texture names. Layouts follow Raymap
(byvar/raymap, OpenSpace readers, EngineVersion.Montreal branches). 

Everything here stays in game axes (z-up); models.py converts to glTF.
"""
import math
import re
import struct
import sys

SO_WORLD, SO_PERSO, SO_SECTOR, SO_IPO, SO_IPO2 = 0x0, 0x4, 0x8, 0xD, 0x15


class Geo:
    def __init__(s, w, addr):
        s.w, s.addr = w, addr
        nv, pv, pn, pmat, _, ne, pet, pel = struct.unpack('<IIIIIIII', s.rd(addr, 32))
        s.radius, cx, cy, cz = struct.unpack('<4f', s.rd(addr + 48, 16))
        s.center = (cx, cy, cz)
        if not (0 < nv < 20000 and 0 < ne < 500):
            raise ValueError(f'geo {addr:#x}: nv={nv} ne={ne}')
        s.verts = [struct.unpack_from('<3f', s.rd(pv, nv * 12), i * 12) for i in range(nv)]
        s.normals = [struct.unpack_from('<3f', s.rd(pn, nv * 12), i * 12) for i in range(nv)] if pn else None
        types = struct.unpack(f'<{ne}H', s.rd(pet, ne * 2))
        ptrs = struct.unpack(f'<{ne}I', s.rd(pel, ne * 4))
        s.elements, s.sprites = [], []
        for t, p in zip(types, ptrs):
            if t == 1:
                s.elements.append(s.tris(p))
            elif t == 3:
                s.sprites += s.sprite_list(p)

    def rd(s, addr, n):
        k, o = s.w.find(addr)
        if k is None:
            raise ValueError(f'unmapped {addr:#x}')
        d = s.w.blocks[k][1]
        if o + n > len(d):
            raise ValueError(f'short read {addr:#x}+{n}')
        return d[o:o + n]

    def tris(s, p):
        pmat, ntri, nuv, ptri, pmap, pnrm, puv = struct.unpack('<IHHIIII', s.rd(p, 24))
        tri = struct.unpack(f'<{ntri * 3}h', s.rd(ptri, ntri * 6)) if ntri else ()
        uvmap = struct.unpack(f'<{ntri * 3}h', s.rd(pmap, ntri * 6)) if ntri and pmap else None
        uvs = [struct.unpack_from('<2f', s.rd(puv, nuv * 8), i * 8) for i in range(nuv)] if nuv and puv else []
        mat = s.material(pmat)
        return dict(addr=p, tri=tri, uvmap=uvmap, uvs=uvs, **mat)

    def sprite_list(s, p):
        """Camera-facing sprites (e.g. the Playmobil faces): centre vertex, size, material."""
        n, ps = struct.unpack('<II', s.rd(p, 8))
        out = []
        for i in range(n if n < 64 else 0):
            _, info, sx, sy, cv = struct.unpack('<IIffH', s.rd(ps + 24 * i, 18))
            mp = s.w.u32(info + 20) if info else None
            gm = s.w.u32(mp) if mp else None
            psc = s.w.u32(info + 12) if info else None          # info scale: half-extents = size * scale
            k = struct.unpack('<2f', s.rd(psc, 8)) if psc else (1.0, 1.0)
            out.append(dict(center=cv, size=(sx * k[0], sy * k[1]), **s.material(gm)))
        return out

    def material(s, gm):
        out = dict(texture=None, flags=0, tex_flags=0, color=(1, 1, 1, 1), diffuse=(1, 1, 1, 1), ambient=(0, 0, 0, 1),
                   tex_addr=None)
        if not gm:
            return out
        vm = s.w.u32(gm)
        if not vm:
            return out
        out['flags'] = s.w.u32(vm)
        f = struct.unpack('<16f', s.rd(vm + 4, 64))
        out['ambient'], out['diffuse'], out['color'] = f[0:4], f[4:8], f[12:16]
        tex = s.w.u32(vm + 0x48)
        if tex:
            out['tex_addr'] = tex
            out['tex_flags'] = s.w.u32(tex + 8) or 0     # 0x2: black is transparent (chroma key), 0x20: additive light
            out['texture'] = texture_name(s.w, tex)
        return out


def texture_name(w, tex):
    k, o = w.find(tex)
    if k is None:
        return None
    d = w.blocks[k][1][o:o + 0x200]
    m = re.search(rb'[A-Za-z0-9_\\\-. ]{3,80}\.(?:tga|bmp|gf)', d, re.I)
    return m.group().decode('latin-1') if m else None


def matrix(w, addr):
    """4x4 row-major (game axes) from a Montreal transform: type, pos, rot 3x3 (columns), scale 3x3."""
    k, o = w.find(addr)
    d = w.blocks[k][1]
    f = struct.unpack_from('<21f', d, o + 4)
    pos, rot, scl = f[0:3], f[3:12], f[12:21]
    R = [[rot[c * 3 + r] for c in range(3)] for r in range(3)]   # columns -> rows
    S = [[scl[c * 3 + r] for c in range(3)] for r in range(3)]
    M = [[sum(R[i][k] * S[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return [M[0] + [pos[0]], M[1] + [pos[1]], M[2] + [pos[2]], [0, 0, 0, 1]]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


IDENT = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def superobjects(w, code):
    """All superobjects with the given type code in the level blocks (relocated data pointer)."""
    out = []
    for (mod, bid, src), (base, data) in w.blocks.items():
        if src == 'fix':
            continue
        for o in range(0, len(data) - 0x38, 4):
            if struct.unpack_from('<I', data, o)[0] != code:
                continue
            a = base + o
            if (a + 4) in w.ptrs and (a + 0x1c) in w.ptrs:
                out.append(a)
    return out


def global_matrix(w, so):
    chain = []
    seen = set()
    while so and so not in seen:
        seen.add(so)
        m = w.u32(so + 0x20)
        chain.append(matrix(w, m) if m else IDENT)
        so = w.u32(so + 0x1c)
    g = IDENT
    for m in reversed(chain):
        g = mul(g, m)
    return g


def po_geos(w, po):
    """Geometric objects of a physical object's visual set (LOD 0 only)."""
    vs = w.u32(po)
    if not vs:
        return []
    nlod, vstype = w.u16(vs + 4), w.u16(vs + 6)
    if vstype != 0 or nlod == 0:
        return []
    datas = w.u32(vs + 12)
    try:
        return [Geo(w, w.u32(datas))]
    except ValueError:          # degenerate placeholder geometry (e.g. 2 vertices, no elements) in some NPC parts
        return []


def sector_of(w, so):
    seen = set()
    while so and so not in seen:
        seen.add(so)
        if w.u32(so) == SO_SECTOR:
            sd = w.u32(so + 4)
            return w.cstr(w.u32(sd + 156)) or hex(so)
        so = w.u32(so + 0x1c)
    return None


def ipos(w):
    """[(so, sector name, global matrix, [Geo])] for every IPO superobject in the level."""
    out = []
    for so in superobjects(w, SO_IPO) + superobjects(w, SO_IPO2):
        try:
            ipo = w.u32(so + 4)
            po = w.u32(ipo)
            geos = po_geos(w, po)
            out.append((so, sector_of(w, so), global_matrix(w, so), geos))
        except (ValueError, TypeError, KeyError) as e:
            print(f'skip IPO SO {so:#x}: {e}', file=sys.stderr)
    return out


def quat_matrix(w_, x, y, z):
    """Raymap AnimQuaternion.ToMatrix (note: transposed vs. the textbook form), row-major 3x3."""
    n = 1 / math.sqrt(x * x + y * y + z * z + w_ * w_)
    x, y, z, w_ = x * n, y * n, z * n, w_ * n
    tx, ty, tz = 2 * x, 2 * y, 2 * z
    xw, yw, zw, xx, yx, zx, yy, zy, zz = tx * w_, ty * w_, tz * w_, tx * x, ty * x, tz * x, ty * y, tz * y, tz * z
    return [[1 - (zz + yy), yx + zw, zx - yw],
            [yx - zw, 1 - (zz + xx), zy + xw],
            [zx + yw, zy - xw, 1 - (yy + xx)]]


def compressed_matrix(w, addr):
    """Montreal animation channel transform (Raymap Matrix.ReadCompressed) -> 4x4 row-major."""
    k, o = w.find(addr)
    d = w.blocks[k][1]
    typ = struct.unpack_from('<H', d, o)[0]
    o += 2
    t = typ & 0xF if typ < 128 else 128
    pos, R, S = (0.0, 0.0, 0.0), [[1, 0, 0], [0, 1, 0], [0, 0, 1]], (1.0, 1.0, 1.0)
    if t in (1, 3, 7, 11, 15):
        pos = tuple(v / 512 for v in struct.unpack_from('<3h', d, o))
        o += 6
    if t in (2, 3, 7, 11, 15):
        qw, qx, qy, qz = (v / 32767 for v in struct.unpack_from('<4h', d, o))
        o += 8
        R = quat_matrix(qw, qx, qy, qz)
    if t == 7:
        s = struct.unpack_from('<h', d, o)[0] / 256
        S = (s, s, s)
    elif t == 11:
        S = tuple(v / 256 for v in struct.unpack_from('<3h', d, o))
    elif t == 15:
        m = [v / 256 for v in struct.unpack_from('<6h', d, o)]
        S = (m[0], m[3], m[5])
    return [[R[i][0] * S[0], R[i][1] * S[1], R[i][2] * S[2], pos[i]] for i in range(3)] + [[0, 0, 0, 1]]


class Perso:
    """A character: 3D data -> state -> Montreal animation; object list -> body-part POs."""

    def __init__(s, w, so):
        s.w, s.so = w, so
        s.perso = w.u32(so + 4)
        s.d3 = w.u32(s.perso)
        s.state_initial, s.state_current, _, s.objlist, _, s.family = (w.u32(s.d3 + 4 * i) for i in range(6))
        sg = w.u32(s.perso + 4)                      # standard game block; +0x48 points at the instance name
        np_ = w.u32(sg + 0x48) if sg else None
        s.name = w.cstr(np_) if np_ and w.find(np_)[0] else None
        n = w.u16(s.objlist + 20)
        start = w.u32(s.objlist + 12)
        s.parts = []        # (scale vec or None, po)
        for i in range(n):
            e = start + i * 20
            sc, po = w.u32(e), w.u32(e + 4)
            scale = struct.unpack('<3f', bytes(b for j in range(3) for b in struct.pack('<I', w.u32(sc + 4 * j)))) if sc else None
            s.parts.append((scale, po))

    def states(s):
        """All states of the family, in list order (family+0x10 head, +0x18 count); falls back to following
        'next' from the initial state. Indexes match aidump's state numbering."""
        out, seen = [], set()
        head, cnt = s.w.u32(s.family + 0x10), s.w.u32(s.family + 0x18)
        st = head if head and s.w.find(head)[0] and 0 < cnt < 2000 else s.state_initial
        limit = cnt if st == head else 2000
        while st and st not in seen and len(out) < limit:
            seen.add(st)
            out.append(st)
            st = s.w.u32(st)
        return out

    def anim(s, state):
        a = s.w.u32(state + 12)
        if not a:
            return None
        frames = s.w.u32(a)
        k, o = s.w.find(a + 4)
        nf, speed, nch = s.w.blocks[k][1][o:o + 3]
        return dict(addr=a, frames=frames, nframes=nf, speed=speed, nchannels=nch)

    def pose(s, state=None, frame=0):
        """[(4x4 global matrix, Geo)] for one animation frame, in the character's local space."""
        w = s.w
        an = s.anim(state or s.state_initial)
        if not an or not an['nframes']:
            return []
        fr = an['frames'] + 16 * (frame % an['nframes'])
        pch, _, _, phier = (w.u32(fr + 4 * i) for i in range(4))
        local, objidx = [], []
        for c in range(an['nchannels']):
            ch = w.u32(pch + 4 * c)
            mp = w.u32(ch)
            objidx.append(w.u16(ch + 4))          # 16-bit object index (0xffff = hidden); the high byte matters for sprite FX
            local.append(compressed_matrix(w, mp) if mp not in (0, 1) else IDENT)
        parent = {}
        if phier:
            nh, ph = w.u32(phier), w.u32(phier + 4)
            for i in range(nh or 0):
                k, o = w.find(ph + 4 * i)
                cid, pid = struct.unpack_from('<hh', w.blocks[k][1], o)
                parent[cid] = pid
        glob = {}

        def g(c, depth=0):
            if c not in glob:
                p = parent.get(c)
                glob[c] = mul(g(p, depth + 1), local[c]) if p is not None and p != c and depth < 64 else local[c]
            return glob[c]
        out = []
        for c in range(an['nchannels']):
            oi = objidx[c]
            if oi == 0xffff or oi >= len(s.parts):
                continue
            scale, po = s.parts[oi]
            if not po:
                continue
            m = g(c)
            if scale:
                m = mul(m, [[scale[0], 0, 0, 0], [0, scale[1], 0, 0], [0, 0, scale[2], 0], [0, 0, 0, 1]])
            for geo in po_geos(w, po):
                out.append((m, geo))
        return out


def persos(w):
    """Superobjects of type Perso (0x4) whose 3D data has a state, object list and family."""
    out = []
    for (mod, bid, src), (base, data) in w.blocks.items():
        for o in range(0, len(data) - 0x38, 4):
            if struct.unpack_from('<I', data, o)[0] != SO_PERSO:
                continue
            a = base + o
            try:
                p = w.u32(a + 4)
                d3 = w.u32(p) if p and w.find(p)[0] else None
                vals = [w.u32(d3 + 4 * i) for i in range(6)] if d3 and w.find(d3)[0] else None
            except (TypeError, KeyError):
                continue
            if not vals or any(v is None or (v and w.find(v)[0] is None) for v in vals):
                continue
            if vals[0] and vals[3] and vals[5]:
                out.append(a)
    return out
