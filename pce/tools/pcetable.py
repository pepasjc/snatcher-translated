"""The stage-2 file table -> work/pce/filetable.json (what every PCE tool reads).

Stage 2 (track sector 22, 15 sectors, loaded at $4000) keeps 8-byte records
`{rec_hi, rec_lo, rec_mid, mode, bank, bh, sectors, 0}` in four groups:
$5505 the six system files (rec 110 = the resident file at $6000...),
$5535 the 33 code modules (the scenes' bytecode and text), $563D the six
per-act voice tables (recs 86..106, three sectors each), $566D the scene
blocks (pictures and their display lists) - that run continues past the
group pointers: cutting it at 64 hid Acts 2-3, so it is read until the
records stop looking like records. `rec` is track-relative: the file's
first sector is `T2 + rec`.

The JSON maps the group ("0" system, "1" modules, "2" scene blocks, "3"
voice tables) to `[{rec, mode, bank, bh, n}]` in table order; pcescene
indexes group 2 by position (block 0 = the first record), pcescript reads
group 1 and every group's (rec, n), pcevoice group 3's recs.

  python pce/tools/pcetable.py           # from work/pce/snatcher_pce.bin, into work/pce/filetable.json
  python pce/tools/pcetable.py show      # print the groups
  python pce/tools/pcetable.py dump      # stage 2, its banks and rec 110 as raw files for huc6280.py
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

BIN = os.path.join(WORK, "pce", "snatcher_pce.bin")
OUT = os.path.join(WORK, "pce", "filetable.json")
T2 = 4174                      # track 2's first sector in the chdman image
STAGE2 = 22                    # track-relative
BASE = 0x4000
GROUPS = [("0", 0x5505, 6), ("1", 0x5535, 33), ("3", 0x563D, 6), ("2", 0x566D, None)]
SECTOR = 2352


def stage2():
    with open(BIN, "rb") as f:
        out = bytearray()
        for i in range(15):
            f.seek((T2 + STAGE2 + i) * SECTOR)
            out += f.read(SECTOR)[16:16 + 2048]
    return bytes(out)


def record(s, off):
    r = s[off:off + 8]
    rec = r[0] << 16 | r[2] << 8 | r[1]
    return {"rec": rec, "mode": r[3], "bank": r[4], "bh": r[5], "n": r[6]}, r[7]


def looks(entry, pad):
    return pad == 0 and 0 < entry["n"] <= 120 and entry["rec"] < 40000 and entry["mode"] < 16


def table():
    s = stage2()
    out = {}
    for key, addr, count in GROUPS:
        off = addr - BASE
        entries = []
        while count is None or len(entries) < count:
            e, pad = record(s, off)
            if not looks(e, pad):
                if count is not None:
                    raise SystemExit(f"group {key}: record {len(entries)} at ${addr + 8 * len(entries):04x} is not a record")
                break
            entries.append(e)
            off += 8
        out[key] = entries
    return out


def main():
    t = table()
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        for key in ("0", "1", "2", "3"):
            print(f"group {key}: {len(t[key])} records")
            print("  " + ", ".join(f"{e['rec']}x{e['n']}" for e in t[key]))
        return
    json.dump(t, open(OUT, "w"), indent=1)
    print(f"{OUT}: " + ", ".join(f"group {k} {len(t[k])}" for k in ("0", "1", "2", "3")))


def dump():
    """Stage 2 and its banks, and the resident file rec 110, as raw files for
    huc6280.py: work/pce/stage2_pristine.bin (base $4000), bank69_pristine.bin
    (file 0x2000-0x3FFF, base $6000), textbank_pristine.bin (file
    0x4000-0x5FFF, the text engine, base $6000), rec110_pristine.bin (base $6000)."""
    s = stage2()
    d = os.path.join(WORK, "pce")
    open(os.path.join(d, "stage2_pristine.bin"), "wb").write(s)
    open(os.path.join(d, "bank69_pristine.bin"), "wb").write(s[0x2000:0x4000])
    open(os.path.join(d, "textbank_pristine.bin"), "wb").write(s[0x4000:0x6000])
    with open(BIN, "rb") as f:
        out = bytearray()
        for i in range(12):
            f.seek((T2 + 110 + i) * SECTOR)
            out += f.read(SECTOR)[16:16 + 2048]
    open(os.path.join(d, "rec110_pristine.bin"), "wb").write(out)
    print("stage2/bank69/textbank/rec110 _pristine.bin written to", d)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "dump":
        dump()
    else:
        main()
