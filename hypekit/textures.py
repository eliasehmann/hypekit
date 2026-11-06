"""Textures.cnt / Vignette.cnt (read-only): file table, GF texture header and decoding to PNG. Pure stdlib.

CNT: u32 dir count, u32 file count, xor flag, checksum flag, xor key; dir names; files (dir index, name, 4-byte
XOR key, checksum, offset, size). Each file is XORed with its key (per 4-byte word).
GF: u8 version, u32 w, u32 h, u8 channels, u8 RLE escape, u16 palette colors, u8 palette bpp, 3 bytes, u32 flags,
u32 pixel total (all mips), u8 type (5 pal8, 10 rgb565, 11 argb1555, 12 argb4444); palette; RLE planes.
Textures.cnt is stored bottom-up, Vignette.cnt top-down: images here are always upright.
Writing archives (texture mods) is not part of the toolkit yet.
"""
import mmap
import re
import os
import struct
import zlib
from dataclasses import dataclass, asdict

TYPE_PAL8, TYPE_565, TYPE_1555, TYPE_4444 = 5, 10, 11, 12
# Vignette screens stored with red and blue swapped (the era screens epoque1-4, also under map/)
SWAPPED_RB = re.compile(r'epoque\d\.gf$', re.I)
TYPE_NAMES = {TYPE_PAL8: 'pal8', TYPE_565: 'rgb565', TYPE_1555: 'argb1555', TYPE_4444: 'argb4444'}


def _xor(data, key):
    n = len(data) - len(data) % 4
    if n == 0:
        return bytes(data)
    k = (bytes(key) * (n // 4 + 1))[:n]
    body = (int.from_bytes(data[:n], 'little') ^ int.from_bytes(k, 'little')).to_bytes(n, 'little')
    return body + bytes(data[n:])


@dataclass
class Texture:
    """One file of an archive. id = '<archive>:<index>'; path uses '/' (e.g. 'Hype/hype_corps.gf')."""
    id: str
    archive: str
    index: int
    path: str
    size: int
    width: int = 0
    height: int = 0
    format: str = ''
    mips: int = 0
    error: str = ''

    def to_dict(self):
        return asdict(self)


class Archive:
    def __init__(self, path, name=None):
        self.path = path
        self.name = name or os.path.splitext(os.path.basename(path))[0]
        self._f = open(path, 'rb')
        self.buf = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        b = self.buf
        nd, nf = struct.unpack_from('<ii', b, 0)
        self.is_xor, self.xor_key = b[8], b[10]
        o = 11
        dirs = []
        for _ in range(nd):
            n, = struct.unpack_from('<i', b, o)
            dirs.append(self._name(b[o + 4:o + 4 + n]))
            o += 4 + n
        o += 1
        self.entries = []                    # (path, key, offset, size)
        for _ in range(nf):
            di, n = struct.unpack_from('<ii', b, o)
            name = self._name(b[o + 8:o + 8 + n])
            o += 8 + n
            key = b[o:o + 4]
            _, off, size = struct.unpack_from('<Iii', b, o + 4)
            o += 16
            d = dirs[di] if di >= 0 else ''
            self.entries.append((((d + '/' + name) if d else name).replace('\\', '/'), key, off, size))
        self.bottom_up = not self.name.lower().startswith('vignette')

    def _name(self, raw):
        if self.is_xor:
            raw = bytes(c ^ self.xor_key for c in raw)
        return raw.decode('latin-1')

    def close(self):
        self.buf.close()
        self._f.close()

    def read(self, index, limit=None):
        _, key, off, size = self.entries[index]
        n = size if limit is None else min(size, (limit + 3) // 4 * 4)
        return _xor(self.buf[off:off + n], key)

    def texture(self, index):
        """Texture record from the GF header only (fast)."""
        path, _, _, size = self.entries[index]
        t = Texture(f'{self.name}:{index}', self.name, index, path, size)
        try:
            h = header(self.read(index, 28))
            t.width, t.height, t.format, t.mips = h['width'], h['height'], TYPE_NAMES[h['type']], h['mips']
        except Exception as ex:                       # noqa: BLE001 - keep listing other files
            t.error = str(ex)
        return t

    def textures(self):
        return [self.texture(i) for i in range(len(self.entries))]

    def rgba(self, index, level=0):
        """-> (width, height, RGBA bytes, upright)."""
        w, h, px = decode_gf(self.read(index), level)
        if self.bottom_up:
            row = w * 4
            px = b''.join(px[y * row:(y + 1) * row] for y in range(h - 1, -1, -1))
        if not self.bottom_up and SWAPPED_RB.match(self.entries[index][0].rsplit('/', 1)[-1]):
            b = bytearray(px)                          # stored with red and blue swapped: swap back
            b[0::4], b[2::4] = px[2::4], px[0::4]
            px = bytes(b)
        return w, h, px

    def png(self, index, level=0):
        return png_bytes(*self.rgba(index, level))


def header(data):
    ver, w, h, ch, esc, pc, pb = struct.unpack_from('<BIIBBHB', data, 0)
    flags, total, typ = struct.unpack_from('<IIB', data, 17)
    if typ not in TYPE_NAMES:
        raise ValueError(f'unknown GF type {typ}')
    return dict(width=w, height=h, channels=ch, esc=esc, pal_colors=pc, pal_bpp=pb, total=total, type=typ,
                mips=len(mip_sizes(w, h, total)))


def mip_sizes(w, h, total):
    sizes, acc = [], 0
    while acc < total:
        sizes.append((w, h))
        acc += w * h
        if w == 1 and h == 1:
            break
        w, h = max(1, w >> 1), max(1, h >> 1)
    if acc != total:
        raise ValueError(f'pixel count {total} is not a mip chain of {sizes[0]}')
    return sizes


def _rle_planes(b, o, channels, total, esc):
    planes = []
    esc_b = bytes((esc,))
    for _ in range(channels):
        p = bytearray()
        while len(p) < total:
            need = total - len(p)
            j = b.find(esc_b, o, o + need)
            if j < 0:
                p += b[o:o + need]
                o += need
                break
            p += b[o:j]
            p += bytes((b[j + 1],)) * b[j + 2]
            o = j + 3
        if len(p) != total:
            raise ValueError('RLE run overflows plane')
        planes.append(bytes(p))
    return planes


_UNPACK = {}


def _unpack_table(typ):
    if typ not in _UNPACK:
        x5 = [(v * 255 + 15) // 31 for v in range(32)]
        x6 = [(v * 255 + 31) // 63 for v in range(64)]
        tab = []
        for w in range(65536):
            if typ == TYPE_565:
                px = (x5[w >> 11], x6[(w >> 5) & 63], x5[w & 31], 255)
            elif typ == TYPE_1555:
                px = (x5[(w >> 10) & 31], x5[(w >> 5) & 31], x5[w & 31], 255 if w >> 15 else 0)
            else:
                px = (((w >> 8) & 15) * 17, ((w >> 4) & 15) * 17, (w & 15) * 17, (w >> 12) * 17)
            tab.append(bytes(px))
        _UNPACK[typ] = tab
    return _UNPACK[typ]


def decode_gf(data, level=0):
    """GF bytes -> (w, h, RGBA bytes) of one mip level, in stored row order."""
    h = header(data)
    pal = data[26:26 + h['pal_colors'] * h['pal_bpp']]
    planes = _rle_planes(data, 26 + len(pal), h['channels'], h['total'], h['esc'])
    levels = mip_sizes(h['width'], h['height'], h['total'])
    start = sum(w * hh for w, hh in levels[:level])
    w, hh = levels[level]
    n = w * hh
    if h['type'] == TYPE_PAL8:
        bpp = h['pal_bpp']
        lut = [bytes((pal[i * bpp + 2], pal[i * bpp + 1], pal[i * bpp], 255)) if i < h['pal_colors'] else b'\0\0\0\xff'
               for i in range(256)]
        px = b''.join(lut[v] for v in planes[0][start:start + n])
    else:
        tab = _unpack_table(h['type'])
        lo, hi = planes[0][start:start + n], planes[1][start:start + n]
        px = b''.join(tab[a | b << 8] for a, b in zip(lo, hi))
    return w, hh, px


def png_bytes(w, h, rgba):
    """Minimal RGBA PNG encoder."""
    row = w * 4
    raw = b''.join(b'\0' + rgba[y * row:(y + 1) * row] for y in range(h))

    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))
