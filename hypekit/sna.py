"""SNA archives (.sna/.lng/...): blocks of (module, id, base address, data), LZO1X-decompressed."""
import struct, sys, os

def lzo1x_decompress(src, out_len):
    dst = bytearray(); ip = 0
    def getlen(t, mask):
        nonlocal ip
        if t == 0:
            t = 0
            while src[ip] == 0:
                t += 255; ip += 1
            t += mask + src[ip]; ip += 1
        return t
    def copy_match(dist, n):
        p = len(dst) - dist
        if p < 0: raise ValueError("bad dist")
        for i in range(n): dst.append(dst[p+i])
    t = src[ip]
    state = 0
    if t > 17:
        ip += 1; t -= 17
        dst += src[ip:ip+t]; ip += t
        state = 4 if t >= 4 else t
        t = src[ip]; ip += 1
        # fallthrough into match handling below
        first = True
    else:
        first = False
    while True:
        if not first:
            t = src[ip]; ip += 1
        first = False
        if t < 16:
            if state == 0:
                # literal run
                n = getlen(t, 15) + 3 if t == 0 else t + 3
                dst += src[ip:ip+n]; ip += n
                state = 4
                continue
            elif state < 4:
                # 2-byte match, dist <= 1024
                dist = 1 + (t >> 2) + (src[ip] << 2); ip += 1
                copy_match(dist, 2)
            else:
                dist = 1 + 0x0800 + (t >> 2) + (src[ip] << 2); ip += 1
                copy_match(dist, 3)
        elif t >= 64:
            dist = 1 + ((t >> 2) & 7) + (src[ip] << 3); ip += 1
            copy_match(dist, (t >> 5) - 1 + 2)
        elif t >= 32:
            n = getlen(t & 31, 31) + 2
            v = src[ip] | (src[ip+1] << 8); ip += 2
            dist = 1 + (v >> 2)
            copy_match(dist, n)
            t = v  # low 2 bits = state
        else:  # 16..31
            n = getlen(t & 7, 7) + 2
            v = src[ip] | (src[ip+1] << 8); ip += 2
            dist = ((t & 8) << 11) + (v >> 2)
            if dist == 0:
                break  # end of stream
            dist += 0x4000
            copy_match(dist, n)
            t = v
        state = t & 3
        dst += src[ip:ip+state]; ip += state
    return bytes(dst)

def read_sna(path):
    d = open(path, 'rb').read(); p = 0; blocks = []
    while p < len(d):
        mod, bid = d[p], d[p+1]; p += 2
        base = struct.unpack_from('<i', d, p)[0]; p += 4
        if base == -1:
            blocks.append((mod, bid, base, b'')); continue
        unk2, unk3, maxp, size = struct.unpack_from('<4I', d, p); p += 16
        data = b''
        if size > 0:
            comp, csize, cck, dsize, dck = struct.unpack_from('<5I', d, p); p += 20
            raw = d[p:p+csize]; p += csize
            data = lzo1x_decompress(raw, dsize) if comp else raw
            if len(data) != dsize: print("size mismatch", path, mod, bid, len(data), dsize, file=sys.stderr)
        blocks.append((mod, bid, base, data))
    return blocks
