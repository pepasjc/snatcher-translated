"""Locate the RAM variable holding the current scene index.

Takes two DuckStation savestates from different scenes. The index of the
first state must be known (index = ISZ number / 0x10; JUNKER HQ = ISZ_B010
= 1). The second state's scene is worked out by trying every candidate.

Usage:
  python find_scene_var.py stateA.sav 1 stateB.sav            # guess B
  python find_scene_var.py stateA.sav 1 stateB.sav 17         # B known
"""
import sys, struct, zstandard as zstd

TABLE_RAM = 0x80071E8C          # verified against the PS-EXE header, not assumed
FIRST_LBA = 166904          # ISZ_B000, anchors the table in a RAM dump

def load_ram(path):
    d = open(path, "rb").read()
    magic = bytes.fromhex("28b52ffd")
    pos, i = [], 0
    while True:
        i = d.find(magic, i)
        if i < 0:
            break
        pos.append(i)
        i += 4
    dec = zstd.ZstdDecompressor()
    blob = b"".join(
        dec.decompress(d[p:(pos[n+1] if n+1 < len(pos) else len(d))],
                       max_output_size=16*1024*1024)
        for n, p in enumerate(pos))
    at = blob.find(struct.pack("<I", FIRST_LBA))
    if at < 0:
        raise SystemExit(f"{path}: scene table not found")
    ram0 = at - (TABLE_RAM - 0x80000000)
    return blob[ram0:ram0+0x200000]

def candidates(ra, rb, va, vb):
    out = []
    for width, fmt in ((1, "B"), (2, "<H"), (4, "<I")):
        for k in range(0, len(ra) - 4):
            if struct.unpack_from(fmt, ra, k)[0] == va and \
               struct.unpack_from(fmt, rb, k)[0] == vb:
                out.append((width, 0x80000000 + k))
    return out

if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    ra = load_ram(sys.argv[1])
    ia = int(sys.argv[2])
    rb = load_ram(sys.argv[3])

    if len(sys.argv) >= 5:
        ib = int(sys.argv[4])
        for w, a in candidates(ra, rb, ia, ib):
            print(f"{w}-byte  {a:#010x}")
    else:
        print(f"state A index {ia}; testing candidate indices for state B\n")
        for ib in range(0, 39):
            if ib == ia:
                continue
            hits = candidates(ra, rb, ia, ib)
            if hits:
                print(f"  index {ib:2d} (ISZ_B{ib*16:03X}): {len(hits):4d} matches"
                      f"  {[hex(a) for _, a in hits[:6]]}")
