# -*- coding: utf-8 -*-
"""The opening's full-screen Snatcher diagram, with its narration card baked in.

The last newsreel card ("Because they take people's bodies and replace
them, they came to be called... Snatchers.") plays over a still that is not
drawn through the OT: CXD_B0B0.BIN's section 1 items 3-6 (four 128x128 8bpp
tiles, 2x2, top-left first) are uploaded to VRAM and displayed as is, and
nothing the subtitle payload draws can appear over it. So the card's three
rows are painted into the tiles where the payload's sprites would put them
(x 14, rows 173/189/205, the game's own 12 px glyphs) in white on the
runtime band's rectangle baked dark (white -> black, the blueprint lines ->
dark blue; #19 - until 0.8.2 the rows were black ink with a white halo on
the bare blueprint), and the subtitle sprite hands over to the picture
without moving.

The recompressed container outgrows its 18 sectors (5 bytes of slack), so
it is relocated past the image end like a bank: work/relocations.json gets
the entry and the executable's file-table record takes the new LBA and
size. Runs after repoint.py (which rebuilds the relocation table) and
before subs_cue.py; patch_disc.py writes it out there.

    python ps1/tools/introdiagram.py preview      # work/introdiagram_preview.png
    python ps1/tools/introdiagram.py apply
    python ps1/tools/introdiagram.py cal          # calibration tiles, dev use
"""
import json, os, struct, sys
import numpy as np
from PIL import Image
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

from lzss import decompress, compress
from gfx import sections, items
import gfxpages

NAME = "CXD_B0B0"
TILES = {(0, 0): 3, (1, 0): 4, (0, 1): 5, (1, 1): 6}   # (col, row) -> item
CARD = "INTRO_news_16"
ROWS_Y = (173, 189, 205)
TEXT_X = 14
INK, HALO = 0xF9, 0x00                                  # measured: 0 black, f9 white
BAND = (168, 240, 8, 248)                               # y0, y1, x0, x1: the runtime
                                                        # band's rectangle (#19)
DARK = {0xF9: 0x00, 0xFA: 0xF1, 0xFB: 0xF1}             # white -> black, blue and
                                                        # light blue -> dark blue
                                                        # (f1; measured against a
                                                        # capture: f2-f8 read white
                                                        # too, fa 88/120/216, fb
                                                        # 184/184/216, f1 0/0/120)
for _i in range(0xF2, 0xF9):
    DARK[_i] = 0x00
RELOC = os.path.join(ROOT, "work", "relocations.json")
LBA_MAP = os.path.join(ROOT, "work", "lba_map.json")
SRC_IMG = os.path.join(ROOT, "discs/iso_ps1_jp", "Snatcher (Japan).bin")


def load():
    raw = gfxpages.source_bytes(NAME + ".BIN")
    dec, _ = decompress(raw)
    dec = bytearray(dec)
    base, size = sections(dec)[1]
    return raw, dec, items(dec, base, size, 1)


def canvas(dec, its):
    """The 256x256 still assembled from its tiles, and the tile slots."""
    img = np.zeros((256, 256), np.uint8)
    for (c, r), k in TILES.items():
        ip, whw, h = its[k]
        W = whw * 2
        img[r * 128:r * 128 + h, c * 128:c * 128 + W] = np.frombuffer(bytes(dec[ip:ip + W * h]), np.uint8).reshape(h, W)
    return img


def store(dec, its, img):
    for (c, r), k in TILES.items():
        ip, whw, h = its[k]
        W = whw * 2
        dec[ip:ip + W * h] = img[r * 128:r * 128 + h, c * 128:c * 128 + W].tobytes()


def card_rows():
    from subs_cue import wrap_only
    from subs_validate import row_mask
    spec = json.load(open(os.path.join(ROOT, "ps1/translation", "subs_INTRO.json"), encoding="utf-8"))
    cue = next(c for c in spec["cues"] if c["id"] == CARD)
    cols = cue.get("cols", spec.get("options", {}).get("cols", 18))
    return [row_mask(r) for r in wrap_only(cue["en"], 3, cols).splitlines()]


def paint(img):
    # The band first (GitHub #19): the runtime band darkens the other
    # boards to a quarter, and black ink on the blueprint's dense lines was
    # the one card left hard to read - so the same rectangle is baked dark
    # here, the lines kept as dark blue, and the rows go in white.
    y0, y1, x0, x1 = BAND
    sub = img[y0:y1, x0:x1]
    for src, dst in DARK.items():
        sub[sub == src] = dst
    for y, mask in zip(ROWS_Y, card_rows()):
        h, w = mask.shape
        R = 1                                   # halo radius: a black rim
        halo = np.zeros((h + 2 * R, w + 2 * R), bool)   # where a line touches
        for dy in range(2 * R + 1):
            for dx in range(2 * R + 1):
                halo[dy:dy + h, dx:dx + w] |= mask
        sub = img[y - R:y + h + R, TEXT_X - R:TEXT_X + w + R]
        sub[halo] = HALO
        sub[R:R + h, R:R + w][mask] = INK
    return img


def calibration(img):
    IDX = [0x00, 0x10, 0x1b, 0x20, 0x40, 0x41, 0x80, 0xa0, 0xc0, 0xe0, 0xf1, 0xf3, 0xf5, 0xf9, 0xfd, 0xff]
    for (c, r), k in TILES.items():           # tile id: a black bar, 4 px per index
        img[r * 128 + 4:r * 128 + 4 + 4 * (k - 2), c * 128:c * 128 + 128] = 0
    for i, idx in enumerate(IDX):             # index blocks in the bottom-left tile
        img[168:184, i * 8:(i + 1) * 8] = idx
    return img


def build(mode):
    raw, dec, its = load()
    img = canvas(dec, its)
    img = calibration(img) if mode == "cal" else paint(img)
    store(dec, its, img)
    return raw, bytes(dec), img


def preview():
    _, _, img = build("apply")
    view = np.where(img == 0xF9, 248, np.where(img == 0x00, 0, np.where(img == 0xF1, 40, 128))).astype(np.uint8)
    Image.fromarray(view[:240]).resize((512, 480), Image.NEAREST).save(
        os.path.join(ROOT, "work", "introdiagram_preview.png"))
    print("work/introdiagram_preview.png")


def relocate(exe, pristine, packed_len):
    """A slot past the image end (reusing this file's, if it still fits) and
    the file-table record pointed at it."""
    lba0, size0 = json.load(open(LBA_MAP))[NAME + ".BIN"]
    rec = pristine.find(struct.pack("<II", lba0, size0))
    assert rec >= 0, "file-table record not found"
    rel = json.load(open(RELOC)) if os.path.exists(RELOC) else {}
    need = (packed_len + 2047) // 2048
    lba = rel.get(NAME + ".BIN")
    taken = [(at, (os.path.getsize(os.path.join(gfxpages.DST_DIR, f)) + 2047) // 2048)
             for f, at in rel.items() if f != NAME + ".BIN" and os.path.exists(os.path.join(gfxpages.DST_DIR, f))]
    if lba is None or any(at < lba + need and lba < at + n for at, n in taken):
        lba = os.path.getsize(SRC_IMG) // 2352
        for at, n in taken:
            lba = max(lba, at + n)
    rel[NAME + ".BIN"] = lba
    json.dump(rel, open(RELOC, "w"))
    exe[rec:rec + 8] = struct.pack("<II", lba, packed_len)
    return lba, need


def apply(mode="apply"):
    raw, dec, _ = build(mode)
    packed = compress(dec)
    check, _ = decompress(packed)
    assert bytes(check) == dec, "roundtrip mismatch"
    out = os.path.join(gfxpages.DST_DIR, NAME + ".BIN")
    open(out, "wb").write(packed)
    pristine = open(os.path.join(ROOT, "discs/extracted_ps1", "SLPS_001.54"), "rb").read()
    exe_path = os.path.join(gfxpages.DST_DIR, "SLPS_001.54")
    exe = bytearray(open(exe_path, "rb").read())
    cap = ((len(raw) + 2047) // 2048) * 2048
    if len(packed) <= cap:
        gfxpages.resize(exe, pristine, NAME, len(packed))
        print(f"{NAME}: {len(raw)} -> {len(packed)} bytes, in place")
    else:
        lba, need = relocate(exe, pristine, len(packed))
        print(f"{NAME}: {len(raw)} -> {len(packed)} bytes, relocated to LBA {lba} ({need} sectors)")
    open(exe_path, "wb").write(exe)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if cmd == "preview":
        preview()
    elif cmd == "cal":
        apply("cal")
    else:
        apply()
