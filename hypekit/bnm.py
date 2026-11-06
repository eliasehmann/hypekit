"""Hype sound banks (Gamedata/World/Sound/Bnk_<n>.bnm) and .apm streams -> WAV. Pure Python, -I compatible.

Bank layout (vgmstream ubi_sb.c "BNM v0", Rayman 2 / Tonic Trouble family), all little endian:
  header 0x2c bytes: u32 version 0, section1 off/count (0x20-byte bank header entries), section2 off/count
  (entries), section3/4/X offsets, then data region starts: +0x1c PCM, +0x20 APM, +0x24 MPD, +0x28 end.
  Section2 entries start with u32 id (lo16 index, hi16 bank tag) and u32 type; type 1 = audio, 0x5c bytes:
    +0x0c size  +0x10 offset (relative to the codec's region)  +0x14 volume (0-100)  +0x18 loop flag
    +0x38 loop point?  +0x3c sample rate  +0x40 u16 bits, u16 channels  +0x44 stream type  +0x48 name[20]
  Stream types: 1 = PCM16LE, 4 = complete embedded .apm file (Ubi IMA ADPCM), 2 = Ubi MPEG (.mpd/.mpu; not
  decoded here). Some type-2 entries are named Bnk_<m>.bnm: their data lives in another bank.
APM (ffmpeg apm.c): 0x64-byte header, u16 0x2000, u16 channels, u32 rate, ..., 'vs12' at 0x14, initial
  predictor/step index per channel at 0x2c/0x30 (right) and 0x38/0x3c (left), 'DATA' at 0x60. Each byte holds
  two samples of one channel (high nibble first); channels interleave per byte.
"""
import os
import struct
import sys
import wave

CODEC = {1: 'pcm', 2: 'mpd', 4: 'apm'}

STEPS = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80,
         88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598,
         658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
         3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289,
         16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767]
INDEX = [-1, -1, -1, -1, 2, 4, 6, 8]


def _ima_table():
    """(step_index, nibble) -> (delta, next index): IMA expansion precomputed, keeps the decode loop small."""
    tab = []
    for si, step in enumerate(STEPS):
        row = []
        for n in range(16):
            d = step >> 3
            if n & 4: d += step
            if n & 2: d += step >> 1
            if n & 1: d += step >> 2
            row.append((-d if n & 8 else d, min(88, max(0, si + INDEX[n & 7]))))
        tab.append(row)
    return tab


TAB = _ima_table()


def decode_apm(b):
    """Complete .apm file bytes -> (channels, rate, interleaved int16 sample bytes)."""
    tag, ch, rate = struct.unpack_from('<HHI', b, 0)
    if tag != 0x2000 or b[0x14:0x18] != b'vs12' or ch not in (1, 2):
        raise ValueError('not an APM file')
    start = 0x64 if b[0x60:0x64] == b'DATA' else 0x60
    data = b[start:]
    # initial predictor/step per channel: stereo = left (0x38), right (0x2c); mono = 0x2c (bit-exact vs ffmpeg)
    if ch == 2:
        st = [list(struct.unpack_from('<ii', b, 0x38)), list(struct.unpack_from('<ii', b, 0x2c))]
    else:
        st = [list(struct.unpack_from('<ii', b, 0x2c))]
    outs = []
    for c in range(ch):
        pred, si = st[c]
        si = min(88, max(0, si))
        pred = min(32767, max(-32768, pred))
        o = []
        ap = o.append
        for v in data[c::ch]:
            d, si2 = TAB[si][v >> 4]
            pred += d
            pred = 32767 if pred > 32767 else -32768 if pred < -32768 else pred
            ap(pred)
            d, si = TAB[si2][v & 15]
            pred += d
            pred = 32767 if pred > 32767 else -32768 if pred < -32768 else pred
            ap(pred)
        outs.append(o)
    n = min(len(o) for o in outs)
    if ch == 1:
        pcm = struct.pack(f'<{n}h', *outs[0][:n])
    else:
        inter = [0] * (2 * n)
        inter[0::2], inter[1::2] = outs[0][:n], outs[1][:n]
        pcm = struct.pack(f'<{2 * n}h', *inter)
    return ch, rate, pcm


def write_wav(path, ch, rate, pcm):
    with wave.open(path, 'wb') as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def entries(path):
    """Audio entries of a bank (dicts) + the data region starts."""
    b = open(path, 'rb').read()
    return b, parse(b, path)


def read_table(path):
    """Audio entries without reading the sample data: only the header + section tables (fast for browsing)."""
    with open(path, 'rb') as f:
        h = struct.unpack('<11I', f.read(0x2c))
        f.seek(0)
        b = f.read(max(h[5], h[3]) + 0x5c)
    return parse(b, path)


def parse(b, path):
    """Entry table of bank bytes b (the data region may be cut off; offsets are kept, not read)."""
    h = struct.unpack_from('<11I', b, 0)
    if h[0] != 0 or h[1] != 0x2c:
        raise ValueError(f'{path}: not a BNM v0 bank')
    s2, s3 = h[3], h[5]
    regions = {1: (h[7], h[8]), 4: (h[8], h[9]), 2: (h[9], h[10])}
    tag = struct.unpack_from('<I', b, s2)[0] >> 16 if h[4] else None
    out = []
    o = s2
    while o + 0x5c <= s3:
        w = struct.unpack_from('<18I', b, o)
        bits, ch = struct.unpack_from('<HH', b, o + 0x40)
        if (w[1] == 1 and 4000 <= w[15] <= 48000 and bits in (4, 8, 16) and ch in (1, 2)
                and w[17] in CODEC):
            name = b[o + 0x48:o + 0x5c].split(b'\0')[0].decode('latin-1')
            own = os.path.basename(path).lower()
            if w[17] == 2 and not name.lower().endswith('.bnm'):
                lo, hi = h[5], h[6]                 # .mpu/.mpd sources: region after section2, relative offsets
                data = lo + w[4]
            elif w[17] == 2:
                lo, hi = regions[2]                 # named after the bank: absolute file offsets
                data = w[4]
            else:
                lo, hi = regions[w[17]]             # PCM/APM: relative to their region
                data = lo + w[4]
            ext = (name.lower().endswith('.bnm') and name.lower() != own) or not (lo <= data and data + w[3] <= hi)
            out.append(dict(id=w[0] & 0xffff, entry=o, index=(o - s2) // 0x5c, codec=CODEC[w[17]], size=w[3], offset=w[4],
                            volume=w[5], loop=w[6], rate=w[15], bits=bits, channels=ch, name=name,
                            data=None if ext else data, external=ext))
            o += 0x5c
        else:
            o += 4
    return out
