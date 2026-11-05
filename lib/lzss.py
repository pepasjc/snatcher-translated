"""Codec for the compressed graphics files (CC3/CED/CH3/CM*/CP*/CX* etc).

The in-game decompressor sits at 0x8003B924 (found with a PCSX-Redux Lua
write-breakpoint on the asset heap 0x801A6800, then disassembled). It is a
bit-level LZSS over a 4096-byte ring buffer at 0x800A0D48:

  - the bit reader is MSB-first within each byte (mask 0x80 means "fetch the
    next source byte, then test its 0x80 bit")
  - flag bit 1: literal — the next 8 bits are one output byte
  - flag bit 0: match — 12 bits of ABSOLUTE ring position, then 4 bits of
    (length - 2); copies length bytes from ring[pos..], each also appended
    to the ring
  - the ring write index starts at 1 and wraps at 0xFFF; position 0 is never
    written, and a match position of 0 terminates the stream
  - every output byte (literal or copied) is appended to the ring

Files carry a 4-byte header `01 00 00 00` before the bitstream; the game's
loader passes file+4 to the decompressor.

compress() is a greedy encoder producing the same format; roundtrips are
verified byte-exact and the output stays within the original file's size for
all shipped files tested. Positions may reference the current write window
only (the game never zero-initialises the ring between files, so a match
must never point at unwritten ring cells).
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RING = 0x1000


def decompress(d, off=4):
    """Decode `d` starting at `off`. Returns (output, end_offset)."""
    src = off
    mask = 0x80
    data = 0
    ring = bytearray(RING)
    s1 = 1
    out = bytearray()

    def bit():
        nonlocal mask, data, src
        old = mask
        if mask == 0x80:
            data = d[src]; src += 1
        mask >>= 1
        if mask == 0:
            mask = 0x80
        return data & old

    def nbits(n):
        acc = 0
        for i in range(n - 1, -1, -1):
            if bit():
                acc |= 1 << i
        return acc

    while src < len(d):
        if bit():
            v = nbits(8)
            out.append(v); ring[s1] = v; s1 = (s1 + 1) & 0xFFF
        else:
            pos = nbits(12)
            if pos == 0:
                break
            ln = nbits(4) + 2
            for i in range(ln):
                v = ring[(pos + i) & 0xFFF]
                out.append(v); ring[s1] = v; s1 = (s1 + 1) & 0xFFF
    return bytes(out), src


class _BitWriter:
    def __init__(self):
        self.bytes = bytearray()
        self.cur = 0
        self.n = 0

    def bit(self, b):
        self.cur = (self.cur << 1) | (1 if b else 0)
        self.n += 1
        if self.n == 8:
            self.bytes.append(self.cur)
            self.cur = 0; self.n = 0

    def bits(self, v, n):
        for i in range(n - 1, -1, -1):
            self.bit((v >> i) & 1)

    def flush(self):
        while self.n:
            self.bit(0)
        return bytes(self.bytes)


def compress(data, header=b"\x01\x00\x00\x00"):
    """Greedy LZSS encoder for the format above."""
    w = _BitWriter()
    n = len(data)
    # ring position each output byte lands at: byte k -> (1 + k) & 0xFFF
    # map from 3-byte prefix to recent output indices, for match search
    from collections import deque
    heads = {}
    i = 0
    while i < n:
        best_len = 0
        best_pos = 0
        if i + 2 <= n:
            key = bytes(data[i:i+3]) if i + 3 <= n else None
            cands = heads.get(key, ()) if key else ()
            for j in reversed(cands):
                # candidate output index j; its ring cell may have been
                # overwritten if more than RING-1 bytes were emitted since
                if i - j > 0xFFF - 17:
                    continue
                L = 0
                while L < 17 and i + L < n and data[j + L] == data[i + L]:
                    L += 1
                if L > best_len:
                    best_len = L; best_pos = (1 + j) & 0xFFF
                    if L == 17:
                        break
            # a match may not cover ring cell 0 and must not alias the
            # write head; pos+len stays within written history by design
            if best_len >= 2 and best_pos == 0:
                best_len = 0
        if best_len >= 3 or (best_len == 2 and False):
            w.bit(0)
            w.bits(best_pos, 12)
            w.bits(best_len - 2, 4)
            end = i + best_len
        else:
            w.bit(1)
            w.bits(data[i], 8)
            end = i + 1
        while i < end:
            if i + 3 <= n:
                k = bytes(data[i:i+3])
                dq = heads.setdefault(k, deque(maxlen=64))
                dq.append(i)
            i += 1
    # terminator: flag 0 + position 0
    w.bit(0)
    w.bits(0, 12)
    return header + w.flush()


if __name__ == "__main__":
    import glob, os
    args = sys.argv[1:]
    if args:
        for a in args:
            d = open(a, "rb").read()
            out, end = decompress(d)
            dst = a + ".dec"
            open(dst, "wb").write(out)
            print(f"{a}: {len(d)} -> {len(out)} bytes ({end} consumed)")
    else:
        # roundtrip self-test over extracted files
        ok = bad = 0
        for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work", "gfx", "*.BIN"))):
            d = open(f, "rb").read()
            if d[:4] != b"\x01\x00\x00\x00":
                continue
            plain, _ = decompress(d)
            enc = compress(plain)
            back, _ = decompress(enc)
            tag = os.path.basename(f)
            if back != plain:
                print(f"FAIL roundtrip {tag}")
                bad += 1
            else:
                ratio = len(enc) / len(d)
                print(f"ok {tag}: orig {len(d)}, ours {len(enc)} ({ratio:.2f}x)")
                ok += 1
        print(f"\n{ok} ok, {bad} failed")
