"""Snatcher CD-ROMantic's image codec and display lists, from the resident code.

Stage 2 (track-relative sector 22, 15 sectors, loaded at $4000) owns a file
table of 8-byte records `{rec_hi, rec_lo, rec_mid, mode, bank, 0, sectors, 0}`
in five groups ($5505 six system files, $5535 33 code modules, $566D 64 scene
blocks, $563D six small ones; work/pce/filetable.json). Scene blocks load into
SCD RAM banks $3F80+bank and are addressed through the MPRs.

Pictures are drawn from display lists (interpreter $6F00): header byte, byte,
then 6-byte records `{bank, type, vram_lo, vram_hi, ptr_lo, ptr_hi}` until a
bank of $FF. `bank` maps at $8000 (`$43B1`: TAM MPR4..6 = $3F80+bank..+2), so
`ptr` is an address in $8000-$DFFF. Type 8 and 4 (`$6FC8`, `$7019`) point at
`{flags, rowlen, stream...}`; any other type (`$6F60`) at `{flags, remap[flags &
0x7F], stream...}` where the remap table recolours every pixel on the way out.

The stream (dispatcher $7061) is a byte-oriented RLE, control byte c:
   00 n b          n pairs of (b, literal)            (n=0 -> 256)
   01 lo hi b      b repeated lo|hi<<8 times
   02 n b1 b2      (b1 b2) repeated n times           (n=0 -> 256)
   03..3F b        b repeated c times
   40..7F          (c & 3F) zero bytes                 (0 -> 256)
   80 lo hi        lo|hi<<8 literal bytes follow
   81..BF          (c & 7F) literal bytes follow
   C0..FD          (c & 3F) pairs of (0, literal)
   FE n b1..b4     (b1 b2 b3 b4) repeated n times      (n=0 -> 256)
   FF              end
Every output byte goes to `$71B0`, which fills a 128-byte buffer and pushes it
to VRAM as four 8x8 planar tiles: the decoded stream IS VDC tile data, so
tilescan.decode renders it directly.
"""
import json, os, sys
import numpy as np
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import tilescan as T

BANK = 0x2000


def decode(s, pos, limit=0x10000):
    """Decode one stream at `pos`; returns (bytes, end_pos, clean_end)."""
    out = bytearray()
    n = len(s)
    while pos < n and len(out) < limit:
        c = s[pos]
        if c & 0x80:
            if c == 0xFF:
                return bytes(out), pos + 1, True
            if c == 0x80:
                if pos + 3 > n:
                    break
                k = s[pos + 1] | s[pos + 2] << 8
                out += s[pos + 3:pos + 3 + k]
                pos += 3 + k
            elif c == 0xFE:
                if pos + 6 > n:
                    break
                k = s[pos + 1] or 256
                out += bytes(s[pos + 2:pos + 6]) * k
                pos += 6
            else:
                k = c & 0x7F
                if k >= 0x40:
                    k &= 0x3F
                    k = k or 256
                    for i in range(1, k + 1):
                        if pos + i >= n:
                            break
                        out += b"\0" + bytes([s[pos + i]])
                else:
                    out += s[pos + 1:pos + 1 + k]
                pos += k + 1
        else:
            if c == 0:
                if pos + 3 > n:
                    break
                k = s[pos + 1] or 256
                b = s[pos + 2]
                pos += 3
                for i in range(k):
                    if pos + i >= n:
                        break
                    out += bytes([b, s[pos + i]])
                pos += k
            elif c == 1:
                if pos + 4 > n:
                    break
                out += bytes([s[pos + 3]]) * (s[pos + 1] | s[pos + 2] << 8)
                pos += 4
            elif c == 2:
                if pos + 4 > n:
                    break
                out += bytes(s[pos + 2:pos + 4]) * (s[pos + 1] or 256)
                pos += 4
            elif c < 0x40:
                if pos + 2 > n:
                    break
                out += bytes([s[pos + 1]]) * c
                pos += 2
            else:
                out += b"\0" * ((c & 0x3F) or 256)
                pos += 1
    return bytes(out), pos, False


def find_lists(block, bank0, nbanks):
    """Candidate display lists: runs of records whose bank/ptr fall inside the
    block, terminated by $FF. Yields (offset, [(bank, type, vram, ptr)])."""
    n = len(block)
    i = 0
    while i < n - 6:
        recs = []
        j = i
        while j + 6 <= n:
            b, t, vl, vh, pl, ph = block[j:j + 6]
            if b == 0xFF:
                break
            ptr = pl | ph << 8
            if not (bank0 <= b < bank0 + nbanks and 0x8000 <= ptr < 0xE000 and t < 0x20):
                recs = None
                break
            off = (b - bank0) * BANK + (ptr - 0x8000)
            if off >= n:
                recs = None
                break
            recs.append((b, t, vl | vh << 8, ptr, off))
            j += 6
        if recs:
            yield i, recs
            i = j + 1
        else:
            i += 1


def image_stream(block, off, typ):
    flags = block[off]
    if typ in (4, 8):
        return off + 2, flags, block[off + 1]
    return off + 1 + (flags & 0x7F), flags, None


def render(data, path, tiles_wide=32):
    from PIL import Image
    n = (len(data) // 32) * 32
    if n < 32 * tiles_wide:
        return None
    px = T.decode(np.frombuffer(data[:n], dtype=np.uint8).reshape(-1, 32))
    img = T.as_image(px, tiles_wide)
    im = Image.fromarray((img * 17).astype(np.uint8), "L")
    im.save(path)
    return im.size


if __name__ == "__main__":
    print(__doc__)
