"""Prove a variant image carries the art its name promises.

  python ps1/tools/check_variant.py censored    ["Snatcher (Japan) [censored]"]
  python ps1/tools/check_variant.py uncensored  ["Snatcher (Japan)"]

The two release images come out of one build and differ only in what
ps1/tools/uncensor.py touches: the two pictures it rewrites and the exec's
file-table record for the maggot-skull swap. This compares those three
places in the built image against the pristine disc, so a censored build
that quietly shipped the uncensored art (a leftover patched/*.BIN, a
build script edited out of order) fails here rather than in a player's
hands.
"""
import json, os, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

PRISTINE = os.path.join(ROOT, "discs/iso_ps1_jp", "Snatcher (Japan).bin")
LBA = json.load(open(os.path.join(ROOT, "work", "lba_map.json")))
_REL_PATH = os.path.join(ROOT, "work", "relocations.json")
REL = json.load(open(_REL_PATH)) if os.path.exists(_REL_PATH) else {}

PICTURES = ["CXK_B062.BIN", "CXF_B080.BIN"]
# uncensor.py's MAGGOT record: {lba, size, pad} at exec file offset 0x4c3f0.
MAGGOT_REC = 0x4C3F0
MAGGOT_DONOR = "CXQ_B0A0.BIN"


def extent_at(path, lba, size):
    """The bytes at an LBA as they lie in the image (data at +24 of a sector)."""
    out = bytearray()
    with open(path, "rb") as f:
        f.seek(lba * 2352)
        for _ in range((size + 2047) // 2048):
            out += f.read(2352)[24:24 + 2048]
    return bytes(out[:size])


def extent(path, name):
    """A picture as the GAME finds it: through the exec's file table ({lba,
    size} records, the record found by the pristine pair in the pristine exec),
    read out of this image's own exec (located by its ISO directory record) -
    a relocated file moves in the exec's table, not in the ISO directory."""
    import struct
    lba0, size0 = LBA[name][:2]
    if os.path.abspath(path) == os.path.abspath(PRISTINE):
        return extent_at(path, lba0, size0)
    orig = open(os.path.join(ROOT, "discs/extracted_ps1", "SLPS_001.54"), "rb").read()
    rec = orig.find(struct.pack("<II", lba0, size0))
    assert rec >= 0, f"no file-table record for {name}"
    elba, esize = find(path, "SLPS_001.54")
    lba, size = struct.unpack_from("<II", extent_at(path, elba, esize), rec)
    return extent_at(path, lba, size)


def find(img, name):
    """(lba, size) of a file, from the image's own ISO 9660 directory tree.
    The two variants of one build no longer share a layout (1.0: the
    uncensored image relocates the Saturn's larger CXF_B080 picture, 8
    sectors, in front of the exec), so neither lba_map.json nor
    work/relocations.json - the LAST build's layout - can say where the other
    variant keeps a file."""
    import struct
    def walk(lba, size):
        d = extent_at(img, lba, size)
        for base in range(0, len(d), 2048):
            i = base
            while i < base + 2048 and d[i]:
                e_lba, e_sz = struct.unpack_from("<I", d, i + 2)[0], struct.unpack_from("<I", d, i + 10)[0]
                n = d[i + 32]
                nm = d[i + 33:i + 33 + n].decode("ascii", "replace").split(";")[0]
                if nm == name:
                    return e_lba, e_sz
                if d[i + 25] & 2 and nm not in ("\x00", "\x01"):
                    hit = walk(e_lba, e_sz)
                    if hit:
                        return hit
                i += d[i]
        return None
    pvd = extent_at(img, 16, 2048)
    hit = walk(struct.unpack_from("<I", pvd, 158)[0], struct.unpack_from("<I", pvd, 166)[0])
    if not hit:
        raise SystemExit(f"{name} not found in {img}")
    return hit


def maggot_record(img):
    """The exec's file-table record 321, read out of the IMAGE and out of the
    shipped exec.

    Out of the image, not patched/SLPS_001.54: that file is rebuilt by every
    build, so checking it would report the LAST variant built rather than the
    one in this image. The exec is relocated past the image end, so its
    sectors are wherever work/relocations.json put it (it is the same layout
    for both variants of one build)."""
    lba = find(img, "SLPS_001.54")[0]
    size = LBA["SLPS_001.54"][1]
    built = extent_at(img, lba, max(size, MAGGOT_REC + 12))
    orig = open(os.path.join(ROOT, "discs/extracted_ps1", "SLPS_001.54"), "rb").read()
    return built[MAGGOT_REC:MAGGOT_REC + 12], orig[MAGGOT_REC:MAGGOT_REC + 12]


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else "censored"
    if want not in ("censored", "uncensored"):
        sys.exit(__doc__)
    default = "Snatcher (Japan) [censored]" if want == "censored" else "Snatcher (Japan)"
    img = os.path.join(ROOT, "patched", (sys.argv[2] if len(sys.argv) > 2 else default) + ".bin")
    if not os.path.exists(img):
        sys.exit(f"missing image: {img}")

    bad = []
    for name in PICTURES:
        same = extent(img, name) == extent(PRISTINE, name)
        print(f"{name:<14} {'pristine' if same else 'replaced'}")
        if same != (want == "censored"):
            bad.append(f"{name} is {'pristine' if same else 'replaced'} in the {want} image")
    built, orig = maggot_record(img)
    repointed = built != orig
    print(f"{'exec rec 321':<14} {'repointed -> ' + MAGGOT_DONOR if repointed else 'pristine'}")
    if repointed != (want == "uncensored"):
        bad.append(f"the maggot record is {'repointed' if repointed else 'pristine'} "
                   f"in the {want} image")
    for b in bad:
        print("FAIL " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
