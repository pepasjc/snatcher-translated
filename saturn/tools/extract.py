"""Extract files from Saturn Snatcher track 1 (2352-byte raw sectors, Mode 1).

Reads the disc in discs/iso_saturn_jp/ and writes every root-directory
file to discs/extracted_saturn/ (both gitignored). Usage:
    python saturn/tools/extract.py [NAME...]
"""
import struct
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

BIN = os.path.join(ROOT, "discs/iso_saturn_jp/Snatcher (Japan) (Track 1).bin")
BIN2 = os.path.join(ROOT, "discs/iso_saturn_jp/Snatcher (Japan) (Track 2).bin")
OUT = os.path.join(ROOT, "discs/extracted_saturn")
T1_SECTORS = 203720  # track 1 length; track 2 file begins at this disc LBA (incl. 225-sector pregap)

def read_file(f, lba, size):
    out = bytearray()
    nsec = (size + 2047) // 2048
    if lba >= T1_SECTORS:
        # mode 2 form 1: data at offset 24
        with open(BIN2, "rb") as f2:
            f2.seek((lba - T1_SECTORS) * 2352)
            for _ in range(nsec):
                sec = f2.read(2352)
                out += sec[24:24+2048]
    else:
        f.seek(lba * 2352)
        for _ in range(nsec):
            sec = f.read(2352)
            out += sec[16:16+2048]
    return bytes(out[:size])

def list_root(f):
    entries = []
    for si in range(6):
        f.seek((20 + si) * 2352)
        sec = f.read(2352)[16:16+2048]
        i = 0
        while i < 2048:
            l = sec[i]
            if l == 0:
                break
            lba = struct.unpack("<I", sec[i+2:i+6])[0]
            size = struct.unpack("<I", sec[i+10:i+14])[0]
            flags = sec[i+25]
            nlen = sec[i+32]
            name = sec[i+33:i+33+nlen].decode("ascii", "replace").split(";")[0]
            if name and not flags & 2:
                entries.append((name, lba, size))
            i += l
    return entries

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    wanted = sys.argv[1:]
    with open(BIN, "rb") as f:
        for name, lba, size in list_root(f):
            if wanted and name not in wanted:
                continue
            data = read_file(f, lba, size)
            with open(os.path.join(OUT, name), "wb") as o:
                o.write(data)
            print(f"extracted {name} ({size} bytes)")
