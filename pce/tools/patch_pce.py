"""Patch Shift-JIS strings into the PCE disc image (MODE1/2352, data at +16).

Snatcher CD-ROMantic keeps its menu/verb/name lists as RAW Shift-JIS in the
code-module files on track 2, one token per record with 0xFF between them, so a
label is replaced in place exactly like a PS1 ISZ string: the English must fit
the Japanese byte footprint (`fit` below), and every copy of the token on the
disc is rewritten (the same list ships inside many scene modules).

The data track is packed to its last sector, so a module that outgrows its
record (English dialogue does) has nowhere to go: `fresh_copy` extends track 2
by RESERVE sectors (blank MODE1 sectors inserted before track 3's pregap, the
cue's later INDEX times shifted - the game plays music by track number, so
they may move) and `Image.alloc` hands out sectors from the old post-gap on.
`Image.retable` rewrites a file-table record in stage 2 (track sector 22,
loaded at $4000; 8-byte records {hi, lo, mid, mode, bank, 0, sectors, 0},
rec = hi<<16 | mid<<8 | lo).

Sectors are MODE1/2352, not the PS1's Mode 2 Form 1: user data at +16 (2048),
EDC at +2064 over bytes 0..2063, ECC P/Q at +2076/+2248 over bytes 12..2075
with the header INCLUDED (mode 2 zeroes it). `fix_sector` regenerates both.

  python pce/tools/patch_pce.py pce/translation/strings_test.json
"""
import json, os, re, shutil, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

RAW = 2352
DATA = 2048
HDR = 16
T2 = 4174                   # track 2's first sector (cue: 00:55:49)
T3 = 38294                  # track 3's pregap start (08:30:44) in the pristine image
LAST_USED = 33969           # last non-zero data sector, relative to T2
RESERVE = 600
STAGE2 = 22                 # stage 2: track-relative sector, 15 sectors, at $4000
STAGE2_BASE = 0x4000
SRC = os.path.join(WORK, "pce", "snatcher_pce.bin")
OUT = os.path.join(ROOT, "patched", "pce", "snatcher_pce.bin")
CUE = os.path.join(WORK, "pce", "snatcher_pce.cue")

# --- EDC/ECC (same polynomials as the PS1 side, mode 1 geometry) ---
edc_lut = []
for i in range(256):
    e = i
    for _ in range(8):
        e = (e >> 1) ^ (0xD8018001 if e & 1 else 0)
    edc_lut.append(e)

ecc_f_lut = [0] * 256
ecc_b_lut = [0] * 256
for i in range(256):
    j = ((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF
    ecc_f_lut[i] = j
    ecc_b_lut[i ^ j] = i


def edc_compute(data):
    edc = 0
    for b in data:
        edc = (edc >> 8) ^ edc_lut[(edc ^ b) & 0xFF]
    return edc


def ecc_block(src, major_count, minor_count, major_mult, minor_inc):
    size = major_count * minor_count
    dest = bytearray(major_count * 2)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = src[index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = ecc_f_lut[a]
        a = ecc_b_lut[ecc_f_lut[a] ^ b]
        dest[major] = a
        dest[major + major_count] = a ^ b
    return bytes(dest)


def fix_sector(sec):
    """Recompute EDC + ECC P/Q for one raw MODE1/2352 sector."""
    sec = bytearray(sec)
    sec[2064:2068] = struct.pack("<I", edc_compute(sec[0:2064]))
    sec[2068:2076] = bytes(8)
    src = bytes(sec[12:2076])              # header included for mode 1
    p = ecc_block(src, 86, 24, 2, 86)
    sec[2076:2248] = p
    q = ecc_block(src + p, 52, 43, 86, 88)
    sec[2248:2352] = q
    return bytes(sec)


def msf(sector):
    a = sector + 150
    m, s, f = a // 4500, a // 75 % 60, a % 75
    return bytes(int(str(v), 16) for v in (m, s, f))


def blank_sector(sector):
    """A MODE1 sector with the right header and no data."""
    sec = bytearray(RAW)
    sec[0:12] = bytes([0]) + bytes([0xFF]) * 10 + bytes([0])
    sec[12:15] = msf(sector)
    sec[15] = 1
    return fix_sector(sec)


def fresh_copy(src=SRC, out=OUT, cue=CUE, reserve=RESERVE):
    """Copy the image with track 2 extended by `reserve` blank sectors."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(src, "rb") as f, open(out, "wb") as g:
        left = T3 * RAW
        while left:
            chunk = f.read(min(left, 1 << 24))
            g.write(chunk)
            left -= len(chunk)
        for i in range(reserve):
            g.write(blank_sector(T3 + i))
        shutil.copyfileobj(f, g, 1 << 24)
    lines = []
    for line in open(cue, encoding="utf-8"):
        m = re.match(r"(\s*INDEX \d\d )(\d\d):(\d\d):(\d\d)", line)
        if m:
            fr = int(m.group(2)) * 4500 + int(m.group(3)) * 75 + int(m.group(4))
            if fr >= T3:
                fr += reserve
                line = f"{m.group(1)}{fr // 4500:02}:{fr // 75 % 60:02}:{fr % 75:02}" + chr(10)
        lines.append(line)
    open(os.path.splitext(out)[0] + ".cue", "w", encoding="utf-8").writelines(lines)
    return out


class Image:
    """The data track's user bytes, addressed linearly; writes track sectors."""

    def __init__(self, path, sectors):
        self.path = path
        self.n = sectors
        with open(path, "rb") as f:
            self.data = bytearray()
            for i in range(sectors):
                f.seek(i * RAW)
                self.data += f.read(RAW)[HDR:HDR + DATA]
        self.dirty = set()
        self.next_free = T2 + LAST_USED + 1

    def alloc(self, count):
        """Track-relative record number for `count` fresh sectors."""
        rec = self.next_free - T2
        self.next_free += count
        if self.next_free > self.n:
            sys.exit(f"out of reserved sectors ({self.next_free - self.n} short)")
        return rec

    def retable(self, rec, n, new_rec, new_n):
        """Point the stage-2 file-table record (rec, n) at (new_rec, new_n)."""
        base = (T2 + STAGE2) * DATA
        table = self.data[base:base + 15 * DATA]
        old = bytes([rec >> 16, rec & 0xFF, (rec >> 8) & 0xFF])
        hits = [i for i in range(0, len(table) - 8) if table[i:i + 3] == old
                and table[i + 3] == 4 and table[i + 6] == n and table[i + 7] == 0]
        if len(hits) != 1:
            sys.exit(f"file-table record for rec {rec} x{n}: {len(hits)} matches")
        i = hits[0]
        self.write(base + i, bytes([new_rec >> 16, new_rec & 0xFF, (new_rec >> 8) & 0xFF]))
        self.write(base + i + 6, bytes([new_n]))
        return STAGE2_BASE + i

    def write(self, off, blob):
        self.data[off:off + len(blob)] = blob
        for s in range(off // DATA, (off + len(blob) - 1) // DATA + 1):
            self.dirty.add(s)

    def flush(self):
        with open(self.path, "r+b") as f:
            for s in sorted(self.dirty):
                f.seek(s * RAW)
                sec = bytearray(f.read(RAW))
                if sec[15] != 1:
                    sys.exit(f"sector {s}: mode {sec[15]}, not MODE1")
                sec[HDR:HDR + DATA] = self.data[s * DATA:(s + 1) * DATA]
                f.seek(s * RAW)
                f.write(fix_sector(sec))
        return len(self.dirty)


def fit(en, jp):
    a, b = en.encode("cp932"), jp.encode("cp932")
    if len(a) > len(b):
        sys.exit(f"{en!r} is {len(a)}B, {jp!r} allows {len(b)}B")
    return a + b"\x81\x40" * ((len(b) - len(a)) // 2) + b"\x20" * ((len(b) - len(a)) % 2)


def replace_tokens(img, jp, en):
    """Rewrite every 0xFF-delimited record equal to `jp`. Returns the offsets."""
    pat = b"\xff" + jp.encode("cp932") + b"\xff"
    new = b"\xff" + fit(en, jp) + b"\xff"
    hits, i = [], img.data.find(pat)
    while i >= 0:
        hits.append(i + 1)
        img.write(i, new)
        i = img.data.find(pat, i + 1)
    return hits


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    sectors = spec.get("sectors", 38000)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if not os.path.exists(OUT) or spec.get("fresh", True):
        print(f"copying {SRC} -> {OUT} (+{RESERVE} sectors)")
        fresh_copy()
    img = Image(OUT, sectors)
    for s in spec["strings"]:
        hits = replace_tokens(img, s["jp"], s["en"])
        print(f"{s['jp']} -> {s['en']}: {len(hits)} copies")
        if not hits:
            sys.exit(f"{s['jp']!r} not found as an 0xFF-delimited record")
    print(f"{img.flush()} sectors rewritten in {OUT}")


if __name__ == "__main__":
    main()
