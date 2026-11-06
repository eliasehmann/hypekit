"""Characters as binary glTF (.glb) with the game's own textures (from the install's Textures.cnt).

One node per animation channel with TRS keyframes (Montreal animations: compressed per-channel transforms + a
parent hierarchy per frame); rest pose = frame 0. Sprites (Playmobil faces) are quads with extras.sprite=True that a
viewer turns to the camera; additive light textures carry extras.additive=True on the material.
Game axes are z-up right-handed; glTF is y-up: (x, y, z) -> (x, z, -y).
"""
import array
import json
import math
import struct

from .geo import IDENT, Perso, compressed_matrix, po_geos
from .textures import png_bytes

# Per-character fixes, by instance name: animation channels to leave out. Frame 0 shows every weapon copy:
# Hype ch14 = crossbow in the hand, ch18 = sword at the hip (keeps ch15 sword in the hand, ch19 crossbow on the back).
SKIP_CHANNELS = {'Hype': (14, 18)}
FIXED_FPS = False             # True: every clip at a flat 30 fps (old website exports); default: the game's speed


def conv(v):
    return (v[0], v[2], -v[1])


def conv_m3(m):
    """3x3 game-space linear map -> glTF space: C m C^-1, C = [[1,0,0],[0,0,1],[0,-1,0]]."""
    C = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]
    Ci = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
    mm = lambda a, b: [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return mm(mm(C, m), Ci)


def trs(m4):
    """Game 4x4 -> glTF (translation, rotation quaternion xyzw, scale)."""
    t = conv([m4[0][3], m4[1][3], m4[2][3]])
    M = conv_m3([row[:3] for row in m4[:3]])
    s = [math.sqrt(sum(M[r][c] ** 2 for r in range(3))) or 1 for c in range(3)]
    R = [[M[r][c] / s[c] for c in range(3)] for r in range(3)]
    det = (R[0][0] * (R[1][1] * R[2][2] - R[1][2] * R[2][1]) - R[0][1] * (R[1][0] * R[2][2] - R[1][2] * R[2][0])
           + R[0][2] * (R[1][0] * R[2][1] - R[1][1] * R[2][0]))
    if det < 0:
        s[0] = -s[0]
        for r in range(3):
            R[r][0] = -R[r][0]
    tr = R[0][0] + R[1][1] + R[2][2]
    if tr > 0:
        S = math.sqrt(tr + 1) * 2
        q = ((R[2][1] - R[1][2]) / S, (R[0][2] - R[2][0]) / S, (R[1][0] - R[0][1]) / S, S / 4)
    elif R[0][0] > R[1][1] and R[0][0] > R[2][2]:
        S = math.sqrt(1 + R[0][0] - R[1][1] - R[2][2]) * 2
        q = (S / 4, (R[0][1] + R[1][0]) / S, (R[0][2] + R[2][0]) / S, (R[2][1] - R[1][2]) / S)
    elif R[1][1] > R[2][2]:
        S = math.sqrt(1 + R[1][1] - R[0][0] - R[2][2]) * 2
        q = ((R[0][1] + R[1][0]) / S, S / 4, (R[1][2] + R[2][1]) / S, (R[0][2] - R[2][0]) / S)
    else:
        S = math.sqrt(1 + R[2][2] - R[0][0] - R[1][1]) * 2
        q = ((R[0][2] + R[2][0]) / S, (R[1][2] + R[2][1]) / S, S / 4, (R[1][0] - R[0][1]) / S)
    n = math.sqrt(sum(x * x for x in q)) or 1
    return list(t), [x / n for x in q], s


def gltf_matrix(m4):
    """Game 4x4 -> glTF column-major 16 floats."""
    M = conv_m3([row[:3] for row in m4[:3]])
    t = conv([m4[0][3], m4[1][3], m4[2][3]])
    return [M[0][0], M[1][0], M[2][0], 0, M[0][1], M[1][1], M[2][1], 0, M[0][2], M[1][2], M[2][2], 0, t[0], t[1], t[2], 1]


class Glb:
    def __init__(s, textures):
        s.textures = textures      # name -> (w, h, RGBA bytes) or None
        s.png = png_bytes          # (w, h, RGBA bytes) -> PNG bytes (exporters may plug in a smaller encoder)
        s.bin = bytearray()
        s.g = dict(asset=dict(version='2.0', generator='hypekit'), scene=0,
                   scenes=[dict(nodes=[])], nodes=[], meshes=[], materials=[], textures=[], images=[],
                   samplers=[dict(magFilter=9729, minFilter=9987, wrapS=10497, wrapT=10497)],
                   accessors=[], bufferViews=[], buffers=[])
        s.mat_cache, s.mesh_cache = {}, {}
        s.additive_flags = 0x20       # texture flags drawn as additive light; FX exports also use 0x8 (flashes, rings)
        s.gallery = None

    def view(s, data, target=None):
        while len(s.bin) % 4:
            s.bin.append(0)
        bv = dict(buffer=0, byteOffset=len(s.bin), byteLength=len(data))
        if target:
            bv['target'] = target
        s.bin += data
        s.g['bufferViews'].append(bv)
        return len(s.g['bufferViews']) - 1

    def acc(s, fmt, rows, typ, ctype=5126, target=34962, minmax=False):
        data = b''.join(struct.pack(fmt, *r) if isinstance(r, (tuple, list)) else struct.pack(fmt, r) for r in rows)
        a = dict(bufferView=s.view(data, target), componentType=ctype, count=len(rows), type=typ)
        if minmax:
            a['min'] = [min(r[i] for r in rows) for i in range(len(rows[0]))]
            a['max'] = [max(r[i] for r in rows) for i in range(len(rows[0]))]
        s.g['accessors'].append(a)
        return len(s.g['accessors']) - 1

    def material(s, e):
        key = (e['texture'], e['tex_flags'] & ~0x8 | (e['tex_flags'] & s.additive_flags), bool(e['flags'] & 0x400),
               tuple(round(x, 3) for x in e['diffuse']))
        if key in s.mat_cache:
            return s.mat_cache[key]
        m = dict(name=e['texture'] or 'color', doubleSided=not e['flags'] & 0x400,   # bit 10: cull back faces
                 pbrMetallicRoughness=dict(metallicFactor=0, roughnessFactor=1))
        img = s.textures(e['texture']) if e['texture'] else None
        if img:
            w, h, px = img
            if e['tex_flags'] & 0x10a and not e['tex_flags'] & 0x20:      # chroma key: pure black -> transparent
                a = array.array('I', px)
                for k, v in enumerate(a):
                    if v == 0xff000000:
                        a[k] = 0
                px = a.tobytes()
            alpha = any(px[k] != 255 for k in range(3, len(px), 4))
            data = s.png(w, h, px)
            s.g['images'].append(dict(bufferView=s.view(data), mimeType='image/png', name=e['texture']))
            s.g['textures'].append(dict(sampler=0, source=len(s.g['images']) - 1))
            m['pbrMetallicRoughness']['baseColorTexture'] = dict(index=len(s.g['textures']) - 1)
            if e['tex_flags'] & s.additive_flags:
                m['extras'] = dict(additive=True)                    # light / glow effects
            elif alpha:
                m['alphaMode'] = 'MASK'
                m['alphaCutoff'] = 0.5
        else:
            d = e['diffuse']
            m['pbrMetallicRoughness']['baseColorFactor'] = [max(0, min(1, x)) for x in d[:3]] + [1]
        s.g['materials'].append(m)
        s.mat_cache[key] = len(s.g['materials']) - 1
        return s.mat_cache[key]

    def mesh(s, geo):
        if geo.addr in s.mesh_cache:
            return s.mesh_cache[geo.addr]
        prims = []
        for e in geo.elements:
            if not e['tri']:
                continue
            idx, pos, nrm, uv, remap = [], [], [], [], {}
            for c in range(len(e['tri'])):
                vi = e['tri'][c]
                ui = e['uvmap'][c] if e['uvmap'] and e['uvs'] else -1
                k = (vi, ui)
                if k not in remap:
                    remap[k] = len(pos)
                    pos.append(conv(geo.verts[vi]))
                    nrm.append(conv(geo.normals[vi]) if geo.normals else (0, 1, 0))
                    uv.append(e['uvs'][ui] if 0 <= ui < len(e['uvs']) else (0, 0))
                idx.append(remap[k])
            # (x, y, z) -> (x, z, -y) is a rotation, so the game's winding is kept as is
            attrs = dict(POSITION=s.acc('<3f', pos, 'VEC3', minmax=True),
                         NORMAL=s.acc('<3f', [n if any(n) else (0, 1, 0) for n in nrm], 'VEC3'),
                         TEXCOORD_0=s.acc('<2f', [(u, 1 - v) for u, v in uv], 'VEC2'))
            prims.append(dict(attributes=attrs, indices=s.acc('<H' if len(pos) < 65536 else '<I', idx, 'SCALAR',
                                                              5123 if len(pos) < 65536 else 5125, 34963),
                              material=s.material(e)))
        if not prims:
            s.mesh_cache[geo.addr] = None
            return None
        s.g['meshes'].append(dict(name=f'geo_{geo.addr:x}', primitives=prims))
        s.mesh_cache[geo.addr] = len(s.g['meshes']) - 1
        return s.mesh_cache[geo.addr]

    def sprite_mesh(s, sp):
        """A quad in the glTF XY plane facing +Z, centred on the origin; the viewer turns it to the camera."""
        key = ('sprite', sp['texture'], sp['size'])
        if key not in s.mesh_cache:
            w, h = sp['size']
            pos = [(-w, -h, 0), (w, -h, 0), (w, h, 0), (-w, h, 0)]
            uv = [(0, 1), (1, 1), (1, 0), (0, 0)]
            prim = dict(attributes=dict(POSITION=s.acc('<3f', pos, 'VEC3', minmax=True),
                                        NORMAL=s.acc('<3f', [(0, 0, 1)] * 4, 'VEC3'),
                                        TEXCOORD_0=s.acc('<2f', uv, 'VEC2')),
                        indices=s.acc('<H', [0, 1, 2, 0, 2, 3], 'SCALAR', 5123, 34963), material=s.material(sp))
            s.g['meshes'].append(dict(name='sprite', primitives=[prim]))
            s.mesh_cache[key] = len(s.g['meshes']) - 1
        return s.mesh_cache[key]

    def add_geo(s, parent, geo, name, **kw):
        """Mesh node for a geometric object plus one billboard child node per sprite."""
        mi = s.mesh(geo)
        if mi is None and not geo.sprites:
            return None
        n = s.node(parent, name=name, **({'mesh': mi} if mi is not None else {}), **kw)
        for sp in geo.sprites:
            s.node(n, name=name + '_sprite', mesh=s.sprite_mesh(sp), translation=list(conv(geo.verts[sp['center']])),
                   extras=dict(sprite=True))
        return n

    def node(s, parent=None, **kw):
        s.g['nodes'].append(kw)
        i = len(s.g['nodes']) - 1
        if parent is None:
            s.g['scenes'][0]['nodes'].append(i)
        else:
            s.g['nodes'][parent].setdefault('children', []).append(i)
        return i

    def bytes(s):
        g = {k: v for k, v in s.g.items() if v != []}
        b = bytes(s.bin) + b'\0' * (-len(s.bin) % 4)
        g['buffers'] = [dict(byteLength=len(b))]
        js = json.dumps(g, separators=(',', ':')).encode()
        js += b' ' * (-len(js) % 4)
        return (struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(b)) +
                struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(b), 0x004E4942) + b)


def frame_data(w, p, an, f):
    """(local matrices per channel, part index per channel, parent per channel) for frame f."""
    fr = an['frames'] + 16 * f
    pch, phier = w.u32(fr), w.u32(fr + 12)
    local, obj = [], []
    for c in range(an['nchannels']):
        ch = w.u32(pch + 4 * c)
        mp = w.u32(ch)
        obj.append(w.u16(ch + 4))                 # 16-bit object index, 0xffff = hidden
        local.append(compressed_matrix(w, mp) if mp not in (0, 1) else IDENT)
    parent = {}
    if phier:
        nh, ph = w.u32(phier), w.u32(phier + 4)
        for i in range(nh or 0):
            k, o = w.find(ph + 4 * i)
            cid, pid = struct.unpack_from('<hh', w.blocks[k][1], o)
            if cid != pid:
                parent[cid] = pid
    return local, obj, parent


def add_perso(g, w, so, root, samplers, channels, state_index=None, max_frames=None, skip=(), skip_channels=(), swap=None):
    """Channels, parts and keyframes of one superobject under node `root`; appends to samplers/channels."""
    p = Perso(w, so)
    state = p.states()[state_index] if state_index is not None else p.state_initial
    an = p.anim(state)
    nf = min(an['nframes'], max_frames or an['nframes'])
    frames = [frame_data(w, p, an, f) for f in range(nf)]
    _, obj0, parent0 = frames[0]
    chan = {}

    def make(c):
        if c in chan:
            return chan[c]
        par = parent0.get(c)
        pn = make(par) if par is not None and par < an['nchannels'] else root
        chan[c] = g.node(pn, name=f'channel{c}')
        return chan[c]
    for c in range(an['nchannels']):
        make(c)
    for c in range(an['nchannels']):
        oi = obj0[c]
        if oi == 0xffff or oi >= len(p.parts) or oi in skip or c in skip_channels:
            continue
        oi = (swap or {}).get(oi, oi)            # costume variants: another part from the same object list
        scale, po = p.parts[oi]
        if not po:
            continue
        for geo in po_geos(w, po):
            if geo.elements and all(e['tex_flags'] & 0x20 for e in geo.elements) and not geo.sprites:
                continue                                    # pure light/trail effect planes (additive textures)
            kw = dict(scale=[abs(x) for x in conv(scale)]) if scale else {}
            g.add_geo(chan[c], geo, f'part{oi}', **kw)
    # keyframes (also sets the rest pose = frame 0)
    fps = 30 if FIXED_FPS else (an['speed'] or 30)  # the animation's own frame rate (see FIXED_FPS)
    times = [f / fps for f in range(nf)]
    tacc = g.acc('<f', times, 'SCALAR', target=None)
    g.g['accessors'][tacc]['min'], g.g['accessors'][tacc]['max'] = [0], [times[-1]]
    # Root motion: animations like the dragon's flight move the whole figure along a path. Keep the figure in
    # place by removing the drift of the first root channel from every root channel.
    roots = [c for c in range(an['nchannels']) if c not in parent0]
    ref = [trs(fd[0][roots[0]])[0] for fd in frames] if roots else None
    for c in range(an['nchannels']):
        T, R, S = zip(*[trs(fd[0][c]) for fd in frames])
        if ref and c in roots:
            T = [[t[i] - (ref[f][i] - ref[0][i]) for i in range(3)] for f, t in enumerate(T)]
        n = g.g['nodes'][chan[c]]
        n['translation'], n['rotation'], n['scale'] = list(T[0]), list(R[0]), list(S[0])
        if nf > 1:
            R = list(R)
            for i in range(1, len(R)):                 # keep quaternions on one hemisphere
                if sum(a * b for a, b in zip(R[i], R[i - 1])) < 0:
                    R[i] = [-x for x in R[i]]
            for path, vals, typ in (('translation', T, 'VEC3'), ('rotation', R, 'VEC4'), ('scale', S, 'VEC3')):
                samplers.append(dict(input=tacc, output=g.acc('<4f' if typ == 'VEC4' else '<3f', vals, typ, target=None),
                                     interpolation='LINEAR'))
                channels.append(dict(sampler=len(samplers) - 1, target=dict(node=chan[c], path=path)))


def perso_glb(world, so, textures, state_index=None, max_frames=None):
    """-> GLB bytes of one character: parts, rest pose, animation 'anim' of state_index (default: initial state)."""
    p = Perso(world, so)
    g = Glb(textures)
    root = g.node(name=p.name or f'perso_{so:x}')
    samplers, channels = [], []
    add_perso(g, world, so, root, samplers, channels, state_index, max_frames,
              skip_channels=SKIP_CHANNELS.get(p.name, ()))
    if channels:
        g.g['animations'] = [dict(name='anim', samplers=samplers, channels=channels)]
    return g.bytes()
