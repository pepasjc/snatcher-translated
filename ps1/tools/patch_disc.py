"""Write patched ISZ_B010.BIN back into a copy of the PS1 disc image.

Mode 2 Form 1 sectors: data at +24, EDC at +2072 (over bytes 16..2071),
ECC P/Q at +2076/+2248 (header zeroed for mode 2). EDC/ECC regenerated
per Neill Corlett's ECM algorithm so the image stays consistent.
"""
import os, shutil, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

SRC_BIN = os.path.join(ROOT, "discs/iso_ps1_jp/Snatcher (Japan).bin")
SRC_CUE = os.path.join(ROOT, "discs/iso_ps1_jp/Snatcher (Japan).cue")
OUT_DIR = os.path.join(ROOT, r"patched")
# SNATCHER_IMAGE names the output image (default "Snatcher (Japan)"), so a
# scratch build can be written while an emulator holds the main one open.
_IMG = os.environ.get("SNATCHER_IMAGE", "Snatcher (Japan)")
OUT_BIN = os.path.join(OUT_DIR, _IMG + ".bin")
OUT_CUE = os.path.join(OUT_DIR, _IMG + ".cue")
import json, glob
_LBA = json.load(open(os.path.join(ROOT, "work/lba_map.json")))
_REL_PATH = os.path.join(os.path.dirname(OUT_DIR), "work", "relocations.json")
_REL = json.load(open(_REL_PATH)) if os.path.exists(_REL_PATH) else {}
# Files the original disc never had (the SUBS_*.BIN subtitle blobs) exist
# only through a relocation entry; everything else must be a disc file.
PATCHES = [(p, _REL.get(os.path.basename(p), _LBA.get(os.path.basename(p), [None])[0]))
           for p in glob.glob(os.path.join(OUT_DIR, "*.BIN")) + [os.path.join(OUT_DIR, "SLPS_001.54")]
           if os.path.basename(p) in _LBA or os.path.basename(p) in _REL]


def new_sector(lba):
    """Empty Mode 2 Form 1 sector with sync, BCD MSF header and subheader,
    for sectors appended past the original end of the image."""
    sec = bytearray(2352)
    sec[0] = 0
    sec[1:11] = bytes([0xFF] * 10)
    sec[11] = 0
    m, rem = divmod(lba + 150, 75 * 60)
    s, f = divmod(rem, 75)
    sec[12] = ((m // 10) << 4) | (m % 10)
    sec[13] = ((s // 10) << 4) | (s % 10)
    sec[14] = ((f // 10) << 4) | (f % 10)
    sec[15] = 0x02
    sec[16:20] = bytes([0, 0, 0x08, 0])
    sec[20:24] = bytes([0, 0, 0x08, 0])
    return sec


# The pristine image ends with 150 empty sectors after its last file - the
# 2-second post-gap of Sony's mastering rules, there because the drive reads
# ahead past the sector it was asked for. Appended files must keep it: v0.7
# relocated the exec to the very last sector, the BIOS's read of it ran off
# the image, and PS3 froze on the Sony logo (GitHub #13) while real
# hardware, MiSTer and the PC emulators, which have a lead-out or tolerate
# the overrun, booted. Pad sectors match the pristine ones: sync, header,
# zero subheader and body, no EDC/ECC.
POSTGAP = 150


def pad_sector(lba):
    sec = new_sector(lba)
    sec[16:24] = bytes(8)
    return sec


def pad_image(f, end_lba):
    f.seek(0, 2)
    have = f.tell() // 2352
    want = end_lba + POSTGAP
    for lba in range(have, want):
        f.write(pad_sector(lba))
    if want > have:
        print(f"post-gap: {want - have} empty sectors at LBA {have}..{want - 1}")

# --- EDC/ECC tables ---
edc_lut = []
for i in range(256):
    edc = i
    for _ in range(8):
        edc = (edc >> 1) ^ (0xD8018001 if edc & 1 else 0)
    edc_lut.append(edc)

ecc_f_lut = [0]*256
ecc_b_lut = [0]*256
for i in range(256):
    j = ((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF
    ecc_f_lut[i] = j
    ecc_b_lut[i ^ j] = i

def edc_compute(data):
    edc = 0
    for b in data:
        edc = (edc >> 8) ^ edc_lut[(edc ^ b) & 0xFF]
    return edc

def ecc_compute_block(src, major_count, minor_count, major_mult, minor_inc):
    size = major_count * minor_count
    dest = bytearray(major_count * 2)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        ecc_a = 0
        ecc_b = 0
        for _ in range(minor_count):
            temp = src[index]
            index += minor_inc
            if index >= size:
                index -= size
            ecc_a ^= temp
            ecc_b ^= temp
            ecc_a = ecc_f_lut[ecc_a]
        ecc_a = ecc_b_lut[ecc_f_lut[ecc_a] ^ ecc_b]
        dest[major] = ecc_a
        dest[major + major_count] = ecc_a ^ ecc_b
    return bytes(dest)

def fix_sector(sec):
    """Recompute EDC+ECC for a mode 2 form 1 raw sector (2352 bytes)."""
    sec = bytearray(sec)
    edc = edc_compute(sec[16:2072])
    sec[2072:2076] = struct.pack("<I", edc)
    zeroed = bytes(4) + bytes(sec[16:2076])   # header zeroed for mode 2 ECC
    p = ecc_compute_block(zeroed, 86, 24, 2, 86)
    sec[2076:2076+172] = p
    q_src = zeroed + p
    q = ecc_compute_block(q_src, 52, 43, 86, 88)
    sec[2248:2248+104] = q
    return bytes(sec)

def repoint_exec(f, lba, size):
    def sector(n):
        f.seek(n * 2352)
        return bytearray(f.read(2352))
    pvd = sector(16)
    root_lba = struct.unpack_from("<I", pvd, 24 + 156 + 2)[0]
    root_len = struct.unpack_from("<I", pvd, 24 + 156 + 10)[0]
    for n in range(root_lba, root_lba + (root_len + 2047) // 2048):
        sec = sector(n)
        i = 24
        while i < 24 + 2048 and sec[i]:
            rec_len = sec[i]
            name_len = sec[i + 32]
            if sec[i + 33:i + 33 + name_len] == b"SLPS_001.54;1":
                old = struct.unpack_from("<I", sec, i + 2)[0], struct.unpack_from("<I", sec, i + 10)[0]
                struct.pack_into("<I", sec, i + 2, lba)
                struct.pack_into(">I", sec, i + 6, lba)
                struct.pack_into("<I", sec, i + 10, size)
                struct.pack_into(">I", sec, i + 14, size)
                f.seek(n * 2352)
                f.write(fix_sector(sec))
                print(f"SLPS_001.54 directory record: LBA {old[0]} -> {lba}, size {old[1]} -> {size}")
                return
            i += rec_len
    sys.exit("SLPS_001.54 directory record not found")


if __name__ == "__main__":
    import sys
    from verify_build import check
    problems = check(verbose=False)
    if problems:
        for p in problems:
            print("FAIL " + p)
        sys.exit("patched/ is inconsistent with work/pair_table.json — "
                 "run ps1/tools/apply_translation.py, image NOT written")

    # An emulator holding the image open makes the copy below fail halfway
    # and leaves a 276 KB stump that boots to a crash after the intro FMV -
    # and because the stump exists, later runs skip the copy and patch it.
    # Probe the lock first, and treat a short image as absent.
    if os.path.exists(OUT_BIN) and os.path.getsize(OUT_BIN) < os.path.getsize(SRC_BIN):
        print(f"{OUT_BIN} is truncated ({os.path.getsize(OUT_BIN)} bytes) - recopying")
        os.remove(OUT_BIN)
    if os.path.exists(OUT_BIN):
        try:
            open(OUT_BIN, "r+b").close()
        except PermissionError:
            sys.exit("the image is open in an emulator - close it and rerun; image NOT touched")
    if not os.path.exists(OUT_BIN):
        print("copying disc image...")
        try:
            shutil.copyfile(SRC_BIN, OUT_BIN)
        except BaseException:
            if os.path.exists(OUT_BIN):
                os.remove(OUT_BIN)
            raise
    cue = open(SRC_CUE, encoding="utf-8").read().replace("Snatcher (Japan).bin", _IMG + ".bin")
    open(OUT_CUE, "w", encoding="utf-8").write(cue)
    with open(OUT_BIN, "r+b") as f:
        end_lba = os.path.getsize(SRC_BIN) // 2352 - POSTGAP
        for path, lba in PATCHES:
            if not os.path.exists(path):
                print(f"skip (missing): {path}")
                continue
            data = open(path, "rb").read()
            nsec = (len(data) + 2047) // 2048
            name = os.path.basename(path)
            if name in _LBA and name not in _REL:
                cap = (_LBA[name][1] + 2047) // 2048
                if nsec > cap:
                    # would overwrite the next file on the disc: an oversized
                    # CXD_B0B0 test build once clobbered CXD_B0C0's first sector
                    sys.exit(f"{name}: {nsec} sectors do not fit the {cap} the "
                             f"original occupies - relocate it (work/relocations.json)")
            for s in range(nsec):
                off = (lba + s) * 2352
                f.seek(0, 2)
                if off >= f.tell():
                    sec = new_sector(lba + s)
                else:
                    f.seek(off)
                    sec = bytearray(f.read(2352))
                    # A sector inside the file but never written - the gap
                    # left when an alphabetically earlier relocated file
                    # extended the image past a later one's slot - has no
                    # sync or header. Beetle reads it anyway; DuckStation
                    # never completes the read (v0.5: black screen after
                    # New Game, the opening's blob at such a sector).
                    if sec[1:11] != bytes([0xFF] * 10):
                        sec = new_sector(lba + s)
                    # A post-gap pad left by an earlier, shorter build has a
                    # sync but a zero subheader. Keeping it made the exec's
                    # last sector a pad-form data sector in the v0.8
                    # uncensored image (built over a stale image; the
                    # translation-only one was fresh), so the two variants
                    # were not built the same way. Stamp the Form 1 data
                    # subheader; original in-place sectors keep their own.
                    if sec[16:24] == bytes(8):
                        sec[16:24] = new_sector(lba + s)[16:24]
                chunk = data[s*2048:(s+1)*2048]
                sec[24:24+len(chunk)] = chunk
                sec = fix_sector(sec)
                f.seek(off)
                f.write(sec)
            print(f"wrote {nsec} sectors at LBA {lba} ({os.path.basename(path)})")
            end_lba = max(end_lba, lba + nsec)
        pad_image(f, end_lba)
        if "SLPS_001.54" in _REL:
            # The exec is the one relocated file the BIOS finds through
            # ISO9660 (bootcard.py grows it past its 242 sectors): repoint
            # its directory record - extent and size, both byte orders.
            repoint_exec(f, _REL["SLPS_001.54"],
                         os.path.getsize(os.path.join(OUT_DIR, "SLPS_001.54")))

