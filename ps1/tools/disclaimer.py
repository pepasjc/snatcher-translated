"""Redraw the red New Game disclaimer in English.

The screen is drawn by a data-driven blitter: `CXD_B000.BIN` carries a
128x128 8bpp glyph atlas (ink index 1 on background 15) followed by a draw
list the overlay `SXX_B020` merely executes. The list sits right after the
image data:

    u32   0x208                      # unknown, preserved
    u32   count << 24
    count * { u16 y, u16 x, u8 h, u8 w, u16 src }

Each record blits a w x h strip out of the atlas to screen (x, y), and the
rewrite centres each line horizontally and the block vertically (8-aligned
in x, matching the 16-aligned x/w every original record uses). `src`
addresses the atlas in 8x8-pixel blocks: src = (v/8)*16 + (u/8). Records
cover *runs* of adjacent glyphs, which is why no per-character table was
ever findable. Decoding this table and rendering it reproduces the
Japanese screen exactly (34 records, 5 lines).

Thirty-four containers on the disc carry such a table; every other one
already draws English (the intro dedication, OPTION MENU, SPECIAL MENU,
NO DATA, NO CARD). This was the only Japanese user of the mechanism.

The rewrite renders English lines in X11 "fixed" 6x13 (lib/bdffont.py,
DIALOGUE), shelf-packs them into
the atlas as 8px-aligned chunks on 16px rows, and emits one record per
chunk. Unused record slots keep valid but invisible blits (a blank
background block), in case the engine ignores the count byte.

Usage:
  python disclaimer.py preview     # render before/after PNGs to work/gfx/
  python disclaimer.py apply       # write patched/CXD_B000.BIN + exec size
"""
import json, os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from lzss import decompress, compress
from gfx import sections, items
from gfxpages import source_bytes, resize

NAME = "CXD_B000"
TEXT = os.path.join(ROOT, "ps1/translation", "disclaimer.json")
DST = os.path.join(ROOT, "patched", NAME + ".BIN")

INK, BG = 1, 15
AW = AH = 128                 # atlas size
ROW_H = 16                    # shelf height; v stays 8-aligned
CHUNK = 64                    # max chunk width; keeps records small and packable
# The display is 256 wide, not 320: the Japanese records span x 16..240,
# i.e. equal 16px margins. Centring against 320 puts every line ~32px right.
SCREEN_W, SCREEN_H, PITCH = 256, 240, 20

# Every original record puts x and w on a 16-pixel boundary, so keep the
# centring 8-aligned rather than exact: at most 4px off centre, and well
# inside what the blitter is known to handle.
ALIGN = 8


def locate(dec):
    """(image offset, table offset, record capacity) of the container."""
    base, size = sections(dec)[1]
    ip, whw, h = items(dec, base, size, 1)[-1]
    assert (whw * 2, h) == (AW, AH), "unexpected atlas geometry"
    end = ip + AW * AH
    a, hdr = struct.unpack_from("<II", dec, end)
    assert a == 0x208 and (hdr & 0xFFFFFF) == 0, "unexpected table header"
    return ip, end, hdr >> 24


def render_lines(lines):
    """Each line as a 1bpp numpy array, tightly cropped to its ink."""
    import numpy as np
    import bdffont
    font = bdffont.load(bdffont.DIALOGUE)
    out = []
    for text in lines:
        # Top row 3: the letters stand on row 11 of the 16-row strip, where
        # MS Gothic drawn at y=1 had them (descenders 12-13).
        a = np.zeros((ROW_H, SCREEN_W + 64), bool)
        m = font.render(text)
        a[3:3 + m.shape[0], :m.shape[1]] = m
        xs = np.nonzero(a.any(0))[0]
        if not len(xs):
            out.append(a[:, :0])
            continue
        if xs.max() + 1 > SCREEN_W - 16:
            raise SystemExit(f"line too wide ({xs.max()+1}px): {text!r}")
        out.append(a[:, :xs.max() + 1])
    return out


def build():
    import numpy as np
    lines = json.load(open(TEXT, encoding="utf-8"))["lines"]
    dec = bytearray(decompress(source_bytes(NAME + ".BIN"))[0])
    ip, tbl, cap = locate(dec)

    atlas = np.full((AH, AW), BG, np.uint8)
    recs = []
    shelf_v, shelf_u = 0, 0
    strips = render_lines(lines)
    block_h = (len(strips) - 1) * PITCH + ROW_H
    top = ((SCREEN_H - block_h) // 2) & ~1
    for li, strip in enumerate(strips):
        y = top + PITCH * li
        left = ((SCREEN_W - strip.shape[1]) // 2) & ~(ALIGN - 1)
        for cx in range(0, strip.shape[1], CHUNK):
            chunk = strip[:, cx:cx + CHUNK]
            w = (chunk.shape[1] + 7) & ~7          # 8px-aligned footprint
            if shelf_u + w > AW:
                shelf_v += ROW_H
                shelf_u = 0
            if shelf_v + ROW_H > AH:
                raise SystemExit("atlas full — shorten the text")
            atlas[shelf_v:shelf_v + chunk.shape[0],
                  shelf_u:shelf_u + chunk.shape[1]][chunk] = INK
            src = (shelf_v // 8) * 16 + (shelf_u // 8)
            recs.append((y, left + cx, ROW_H, w, src))
            shelf_u += w

    if len(recs) > cap:
        raise SystemExit(f"{len(recs)} records, capacity {cap}")
    # Blank block for the unused slots: bottom-right corner stays background.
    blank_src = ((AH - 8) // 8) * 16 + ((AW - 8) // 8)
    while len(recs) < cap:
        recs.append((0, 0, 8, 8, blank_src))

    dec[ip:ip + AW * AH] = atlas.tobytes()
    struct.pack_into("<II", dec, tbl, 0x208, len(recs) << 24)
    for i, (y, x, h, w, src) in enumerate(recs):
        struct.pack_into("<HHBBH", dec, tbl + 8 + 8 * i, y, x, h, w, src)
    return bytes(dec), recs


def preview():
    import numpy as np
    from PIL import Image
    dec, recs = build()
    _, _, _ = locate(dec)
    ip, tbl, cap = locate(dec)
    atlas = np.frombuffer(dec[ip:ip + AW * AH], np.uint8).reshape(AH, AW)
    Image.fromarray((atlas * 23 % 256).astype(np.uint8)).resize(
        (AW * 3, AH * 3), Image.NEAREST).save(
        os.path.join(ROOT, "work", "gfx", "disclaimer_atlas_after.png"))
    screen = np.zeros((240, 336), np.uint8)
    for y, x, h, w, src in recs:
        v, u = (src // 16) * 8, (src % 16) * 8
        blk = atlas[v:v + h, u:u + w]
        screen[y:y + h, x:x + w] = np.maximum(screen[y:y + h, x:x + w],
                                              (blk == INK) * 255)
    im = Image.fromarray(screen)
    im.resize((672, 480), Image.NEAREST).save(
        os.path.join(ROOT, "work", "gfx", "disclaimer_after.png"))
    print("wrote work/gfx/disclaimer_{atlas_,}after.png")


def apply():
    dec, _ = build()
    packed = compress(dec)
    original = len(source_bytes(NAME + ".BIN"))
    check, _ = decompress(packed)
    assert check == dec, "roundtrip mismatch"
    exe_path = os.path.join(ROOT, "patched", "SLPS_001.54")
    exe = bytearray(open(exe_path, "rb").read())
    pristine = open(os.path.join(ROOT, "discs/extracted_ps1", "SLPS_001.54"), "rb").read()
    resize(exe, pristine, NAME, len(packed))
    open(exe_path, "wb").write(bytes(exe))
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    open(DST, "wb").write(packed)
    print(f"{NAME}: {len(packed)} bytes (original {original}, "
          f"{len(packed) - original:+d}); file-table size updated")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    {"preview": preview, "apply": apply}[cmd]()
