"""Extract files from PS1 Snatcher disc (MODE2/2352)."""
import struct, sys, os
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

BIN = os.path.join(ROOT, "discs/iso_ps1_jp/Snatcher (Japan).bin")
OUT = os.path.join(ROOT, r"discs/extracted_ps1")

f = open(BIN, "rb")

def rsec(lba):
    f.seek(lba * 2352)
    return f.read(2352)[24:24+2048]

def read_file(lba, size):
    out = bytearray()
    for s in range((size + 2047) // 2048):
        out += rsec(lba + s)
    return bytes(out[:size])

def listdir(lba, ln=2048):
    out = []
    for si in range((ln + 2047) // 2048):
        sec = rsec(lba + si)
        i = 0
        while i < 2048:
            l = sec[i]
            if l == 0:
                break
            e_lba = struct.unpack("<I", sec[i+2:i+6])[0]
            e_sz = struct.unpack("<I", sec[i+10:i+14])[0]
            fl = sec[i+25]
            nl = sec[i+32]
            nm = sec[i+33:i+33+nl].decode("ascii", "replace").split(";")[0]
            if nm not in ("\x00", "\x01"):
                out.append((nm, e_lba, e_sz, fl))
            i += l
    return out

def walk(lba, ln, path=""):
    for nm, e_lba, e_sz, fl in listdir(lba, ln):
        full = f"{path}/{nm}" if path else nm
        if fl & 2:
            yield from walk(e_lba, e_sz, full)
        else:
            yield full, e_lba, e_sz

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    pvd = rsec(16)
    rec = pvd[156:156+34]
    root_lba = struct.unpack("<I", rec[2:6])[0]
    root_len = struct.unpack("<I", rec[10:14])[0]
    pats = sys.argv[1:]
    lba_map = {}
    for full, lba, sz in walk(root_lba, root_len):
        # work/lba_map.json: basename -> [lba, size], what every
        # patcher reads to find a file's sectors (patch_disc, gfxpages,
        # uncensor...). Written on a full extraction only; the names are
        # unique across the disc's directories.
        base = full.rsplit("/", 1)[-1]
        assert base not in lba_map, f"duplicate basename {base}"
        lba_map[base] = [lba, sz]
        if pats and not any(p.lower() in full.lower() for p in pats):
            continue
        dst = os.path.join(OUT, full.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst) or OUT, exist_ok=True)
        with open(dst, "wb") as o:
            o.write(read_file(lba, sz))
        print(f"extracted {full} ({sz})")
    if not pats:
        import json
        os.makedirs(WORK, exist_ok=True)
        json.dump(lba_map, open(os.path.join(WORK, "lba_map.json"), "w"), indent=0)
        print(f"wrote work/lba_map.json ({len(lba_map)} files)")
