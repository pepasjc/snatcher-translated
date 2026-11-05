"""Redraw the on-screen keyboard key faces in Latin.

`patch_keyboard.py` rewrites what each key *emits* (the Shift-JIS table at
0x49DB8); the faces the player reads are pixels, baked into `CPS_B0A0.BIN` —
one shared container, loaded by the typing UI at 0x80046efc, decompressed to
the asset heap at 0x801A6800. It holds the keyboard twice:

  section 0, items 0+1   128x80 + 120x80, joined into one 248x80 panel:
                         the resting keyboard, 4 rows of 15 keys. Glyph ink
                         is index 3 on a flat index-4 cell interior; the
                         7x8 face box of key (r, c) sits at (COL_X[c], 11+14r).

  section 1, item 0      128x128, the pressed-key sprites: an 8x8 grid of
                         16x16 cells. Rows 0-3 carry keys 0-7 of panel rows
                         0-3, rows 4-7 the remaining keys 8-14. Ink is index
                         1 over a 1-pixel index-2 halo on an index-3 interior,
                         which `_halo` reproduces (see `verify`: 53 of 60
                         cells byte-exact, three kana carrying a hand-tweaked
                         pixel and the four cells of the wide OK button, which
                         is never redrawn).

Face order follows the emit table, so the layouts stay in step: panel key
(row, col) is cell col%5 of layout group (col//5)*4 + row, which is
`patch_keyboard.ROWS` read the same way. Blank cells are erased; the kept
function keys (/ . ! ? - and the two kana marks and the arrows) keep their
original faces, because they still emit their original characters.

Usage:
  python kbdfaces.py verify      # check the halo model against the original
  python kbdfaces.py preview     # render before/after PNGs to work/gfx/
  python kbdfaces.py apply       # write patched/CPS_B0A0.BIN
"""
import os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from lzss import decompress, compress
from gfx import sections, items
from patch_keyboard import ROWS

NAME = "CPS_B0A0.BIN"
SRC = os.path.join(ROOT, "work", "gfx", "all", NAME)
DST = os.path.join(ROOT, "patched", NAME)
DISC = os.path.join(ROOT, "discs/iso_ps1_jp", "Snatcher (Japan).bin")
LBA_MAP = os.path.join(ROOT, "work", "lba_map.json")

NCOL, NROW = 15, 4
COL_X = [34 + 12 * c + 4 * (c // 5) for c in range(NCOL)]   # 34..88, 98..152, 162..216
ROW_Y = [11 + 14 * r for r in range(NROW)]
FACE_W, FACE_H = 7, 8

PANEL_INK, PANEL_BG = 3, 4
SPR_INK, SPR_HALO, SPR_BG, SPR_EDGE = 1, 2, 3, 4
SPR_PITCH = 16
SPR_FACE = (2, 3)            # face box origin inside a 16x16 sprite cell
SPR_PAINT = (1, 2, 9, 11)    # x0, y0, x1, y1 of the repaintable interior

# 5x7 uppercase font, drawn centred in the 7x8 face box.
FONT = {
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "####.", "#...#", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "####.", "#....", "#....", "#....", "#####"),
    "F": ("#####", "#....", "####.", "#....", "#....", "#....", "#...."),
    "G": (".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".###."),
    "H": ("#...#", "#...#", "#####", "#...#", "#...#", "#...#", "#...#"),
    "I": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "J": ("..###", "...#.", "...#.", "...#.", "#..#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#...#", "#.#.#", "##.##", "#...#"),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
}


def face_char(row, col):
    """Latin face for a panel key, or None to keep the original."""
    group = (col // 5) * 4 + row
    if group >= len(ROWS):
        return None
    return ROWS[group][col % 5]


def glyph_pixels(ch):
    """Set of (x, y) inside the 7x8 face box, centred."""
    rows = FONT[ch]
    ox = (FACE_W - len(rows[0])) // 2
    oy = (FACE_H - len(rows)) // 2
    return {(ox + x, oy + y)
            for y, r in enumerate(rows) for x, c in enumerate(r) if c == "#"}


def _halo(ink, x0, y0, x1, y1):
    """Pixels orthogonally adjacent to `ink`, inside the paint box.

    Orthogonal, not 8-way: the original art leaves a diagonal neighbour on
    the plain interior colour, which is what `verify` pins down.
    """
    out = set()
    for (x, y) in ink:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p = (x + dx, y + dy)
            if x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
                out.add(p)
    return out - ink


class Keyboard:
    """The two keyboard images inside a decompressed CPS_B0A0."""

    def __init__(self, dec):
        self.dec = bytearray(dec)
        base, size = sections(dec)[0]
        self.panel = []           # (data offset, width, height) per half
        for ip, whw, h in items(dec, base, size, 0):
            self.panel.append((ip, whw * 2, h))
        base, size = sections(dec)[1]
        ip, whw, h = items(dec, base, size, 1)[0]
        self.sprites = (ip, whw * 2, h)

    # --- the panel is two side-by-side halves; address it as one image ---

    def _panel_at(self, x, y):
        for ip, w, h in self.panel:
            if x < w:
                return ip + y * w + x
            x -= w
        raise IndexError(x)

    def panel_get(self, x, y):
        return self.dec[self._panel_at(x, y)]

    def panel_set(self, x, y, v):
        self.dec[self._panel_at(x, y)] = v

    def spr_get(self, x, y):
        ip, w, _ = self.sprites
        return self.dec[ip + y * w + x]

    def spr_set(self, x, y, v):
        ip, w, _ = self.sprites
        self.dec[ip + y * w + x] = v

    def spr_origin(self, row, col):
        """Top-left of the sprite cell holding panel key (row, col)."""
        r, c = (row, col) if col < 8 else (row + 4, col - 8)
        return c * SPR_PITCH, r * SPR_PITCH

    # --- drawing ---

    def draw_panel(self, row, col, ink):
        x0, y0 = COL_X[col], ROW_Y[row]
        for y in range(FACE_H):
            for x in range(FACE_W):
                self.panel_set(x0 + x, y0 + y,
                               PANEL_INK if (x, y) in ink else PANEL_BG)

    def draw_sprite(self, row, col, ink):
        cx, cy = self.spr_origin(row, col)
        px0, py0, px1, py1 = SPR_PAINT
        fx, fy = SPR_FACE
        abs_ink = {(cx + fx + x, cy + fy + y) for (x, y) in ink}
        box = (cx + px0, cy + py0, cx + px1, cy + py1)
        halo = _halo(abs_ink, *box)
        for y in range(box[1], box[3] + 1):
            for x in range(box[0], box[2] + 1):
                corner = (x in (box[0], box[2])) and (y in (box[1], box[3]))
                v = (SPR_EDGE if corner else
                     SPR_INK if (x, y) in abs_ink else
                     SPR_HALO if (x, y) in halo else
                     SPR_BG)
                self.spr_set(x, y, v)

    def read_sprite_ink(self, row, col):
        """Face-box ink of the original sprite, in face-box coordinates."""
        cx, cy = self.spr_origin(row, col)
        fx, fy = SPR_FACE
        return {(x, y) for y in range(FACE_H) for x in range(FACE_W)
                if self.spr_get(cx + fx + x, cy + fy + y) == SPR_INK}

    def sprite_cell(self, row, col):
        cx, cy = self.spr_origin(row, col)
        px0, py0, px1, py1 = SPR_PAINT
        return [[self.spr_get(cx + x, cy + y) for x in range(px0, px1 + 1)]
                for y in range(py0, py1 + 1)]


def source_bytes(path=SRC):
    """The pristine container, from a local extract or straight off the disc."""
    if os.path.exists(path):
        return open(path, "rb").read()
    import json
    lba, size = json.load(open(LBA_MAP))[NAME]
    out = bytearray()
    with open(DISC, "rb") as f:
        for s in range((size + 2047) // 2048):
            f.seek((lba + s) * 2352)
            out += f.read(2352)[24:24 + 2048]
    return bytes(out[:size])


def load(path=SRC):
    dec, _ = decompress(source_bytes(path))
    return Keyboard(dec)


def verify(path=SRC):
    """Redraw every original sprite from its own ink; nothing may change."""
    kb = load(path)
    bad = []
    for row in range(NROW):
        for col in range(NCOL):
            before = kb.sprite_cell(row, col)
            kb.draw_sprite(row, col, kb.read_sprite_ink(row, col))
            if kb.sprite_cell(row, col) != before:
                bad.append((row, col))
    print(f"sprite halo model: {NROW * NCOL - len(bad)}/{NROW * NCOL} cells "
          f"reproduced exactly" + (f", mismatches {bad}" if bad else ""))
    return not bad


def retitle(kb):
    """Draw the Latin faces. Returns (drawn, blanked, kept)."""
    drawn = blanked = kept = 0
    for row in range(NROW):
        for col in range(NCOL):
            ch = face_char(row, col)
            if ch is None:
                kept += 1
                continue
            if ch == " ":
                ink = set()
                blanked += 1
            else:
                ink = glyph_pixels(ch)
                drawn += 1
            kb.draw_panel(row, col, ink)
            kb.draw_sprite(row, col, ink)
    return drawn, blanked, kept


def preview(path=SRC):
    from PIL import Image
    import numpy as np

    def shot(kb, tag):
        halves = [np.frombuffer(bytes(kb.dec[ip:ip + w * h]), np.uint8).reshape(h, w)
                  for ip, w, h in kb.panel]
        ip, w, h = kb.sprites
        spr = np.frombuffer(bytes(kb.dec[ip:ip + w * h]), np.uint8).reshape(h, w)
        for name, a in (("panel", np.hstack(halves)), ("sprites", spr)):
            im = Image.fromarray((a * 23 % 256).astype(np.uint8))
            im = im.resize((a.shape[1] * 3, a.shape[0] * 3), Image.NEAREST)
            im.save(os.path.join(ROOT, "work", "gfx", f"kbd_{name}_{tag}.png"))

    kb = load(path)
    shot(kb, "before")
    print("faces drawn/blanked/kept:", retitle(kb))
    shot(kb, "after")
    print("wrote work/gfx/kbd_{panel,sprites}_{before,after}.png")


def apply(path=SRC, dst=DST):
    kb = load(path)
    print("faces drawn/blanked/kept:", retitle(kb))
    packed = compress(bytes(kb.dec))
    original = len(source_bytes(path))
    print(f"{os.path.basename(dst)}: {len(packed)} bytes "
          f"(original {original}, {len(packed) - original:+d})")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "wb").write(packed)
    check, _ = decompress(packed)
    assert check == bytes(kb.dec), "roundtrip mismatch"
    print("roundtrip verified")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    {"verify": verify, "preview": preview, "apply": apply}[cmd]()
