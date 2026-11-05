"""Redraw the baked full-page memo images in English.

`CPC_*.BIN` carries one page each for the Act 1 scene banks B000..B0C0, and
the thirteen pages read as one document. Unlike the keyboard faces there is
no cell grid and no indirection: each page is a plain full-page bitmap, two
items side by side (128 + 64 = 192 x 128), text on a flat background.

Measured layout, identical across the pages: lines sit on a 12-pixel pitch
with the glyph band 9 rows tall, the first at y = 25, and the text column
runs x = 17..183. Two pages carry a photograph on the right (`CPC_B060` and
`CPC_B070`), so their text is kept clear of it.

English text lives in `ps1/translation/gfx_pages.json`, one list of lines per
page, and is rendered in X11 "fixed" 6x13 (lib/bdffont.py, DIALOGUE) — the same face `pairfont.py` uses for the in-game pair
glyphs, so the pages match the dialogue.

Usage:
  python gfxpages.py preview     # render before/after PNGs to work/gfx/
  python gfxpages.py apply       # write patched/CPC_*.BIN
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

TEXT = os.path.join(ROOT, "ps1/translation", "gfx_pages.json")
SRC_DIR = os.path.join(ROOT, "work", "gfx", "all")
DST_DIR = os.path.join(ROOT, "patched")
DISC = os.path.join(ROOT, "discs/iso_ps1_jp", "Snatcher (Japan).bin")
LBA_MAP = os.path.join(ROOT, "work", "lba_map.json")

LEFT, RIGHT = 17, 183
TOP, PITCH, BAND = 25, 12, 9
MAX_LINES = 7
CLEAR_TOP, CLEAR_BOTTOM = 10, 118    # wipe the whole column, not just the lines

# Pages carrying a photograph, as the 48x48 rectangle to preserve:
# (x0, x1, y0, y1), measured as the pixels that are neither ink nor
# background. The original runs text down the left of the picture and past
# its bottom edge, so everything outside this rectangle has to be wiped —
# and the rectangle has to be tight, or Japanese glyph bottoms survive
# inside its top rows.
PHOTOS = {"CPC_B060": (122, 169, 48, 95), "CPC_B070": (120, 167, 64, 111)}


def source_bytes(name):
    path = os.path.join(SRC_DIR, name)
    if os.path.exists(path):
        return open(path, "rb").read()
    lba, size = json.load(open(LBA_MAP))[name]
    out = bytearray()
    with open(DISC, "rb") as f:
        for s in range((size + 2047) // 2048):
            f.seek((lba + s) * 2352)
            out += f.read(2352)[24:24 + 2048]
    return bytes(out[:size])


class Page:
    """One memo page: the two halves addressed as a single 192x128 image."""

    def __init__(self, name, dec):
        self.name = name
        self.dec = bytearray(dec)
        base, size = sections(dec)[0]
        self.halves = [(ip, whw * 2, h) for ip, whw, h in items(dec, base, size, 0)]
        self.width = sum(w for _, w, _ in self.halves)
        self.height = self.halves[0][2]
        self.bg, self.ink = self._colours()

    def _at(self, x, y):
        for ip, w, h in self.halves:
            if x < w:
                return ip + y * w + x
            x -= w
        raise IndexError(x)

    def get(self, x, y):
        return self.dec[self._at(x, y)]

    def set(self, x, y, v):
        self.dec[self._at(x, y)] = v

    def _colours(self):
        """Background is the commonest pixel of the text column, ink the next.

        Measured over the whole column rather than one line, so the two pages
        carrying a photograph do not pick a colour out of the picture.
        """
        counts = {}
        for y in range(CLEAR_TOP, CLEAR_BOTTOM + 1):
            for x in range(LEFT, self.width):
                if self.in_photo(x, y):
                    continue
                v = self.get(x, y)
                counts[v] = counts.get(v, 0) + 1
        order = sorted(counts, key=counts.get, reverse=True)
        return order[0], order[1]

    def right_edge(self, y, band=1):
        """Rightmost usable column over `band` rows, keeping clear of a photo."""
        photo = PHOTOS.get(self.name)
        if photo and photo[2] <= y + band - 1 and y <= photo[3]:
            return photo[0] - 2
        return RIGHT

    def in_photo(self, x, y):
        photo = PHOTOS.get(self.name)
        return bool(photo) and photo[0] <= x <= photo[1] and photo[2] <= y <= photo[3]

    def erase(self):
        """Blank the text column, keeping any photograph.

        The original lines do not all start at `TOP` - `CPC_B070` sits a row
        higher, and both illustrated pages run text down the side of the
        picture - so clearing only the new lines' bands leaves Japanese behind.
        """
        for y in range(CLEAR_TOP, CLEAR_BOTTOM + 1):
            for x in range(LEFT - 1, self.width):
                if not self.in_photo(x, y):
                    self.set(x, y, self.bg)

    def draw(self, lines):
        import numpy as np
        import bdffont
        font = bdffont.load(bdffont.DIALOGUE)
        over = []
        for i, text in enumerate(lines):
            if not text:
                continue
            y0 = TOP + PITCH * i
            # Top row 1: the letters stand on row 9 of the line, as MS Gothic
            # drawn at y=-1 had them; descenders reach row 11, the last row
            # before the next line's blank top row (PITCH 12).
            img = np.zeros((PITCH, self.width), bool)
            m = font.render(text)[:, :self.width]
            img[1:1 + m.shape[0], :m.shape[1]] = m[:PITCH - 1]
            xs = np.nonzero(img.any(0))[0]
            wide = int(xs.max()) if len(xs) else 0
            limit = self.right_edge(y0, PITCH) - LEFT
            if wide > limit:
                over.append((i, wide - limit, text))
            for y in range(PITCH):
                for x in range(min(wide + 1, limit + 1)):
                    if img[y, x] and y0 + y < self.height:
                        self.set(LEFT + x, y0 + y, self.ink)
        return over


def pages():
    data = json.load(open(TEXT, encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def build(name, lines):
    dec, _ = decompress(source_bytes(name + ".BIN"))
    page = Page(name, dec)
    if len(lines) > MAX_LINES:
        raise SystemExit(f"{name}: {len(lines)} lines, {MAX_LINES} fit")
    page.erase()
    for i, over, text in page.draw(lines):
        print(f"  {name} line {i}: {over}px too wide — {text!r}")
    return page


def preview():
    from PIL import Image
    import numpy as np

    def shot(page, tag):
        rows = [np.frombuffer(bytes(page.dec[ip:ip + w * h]), np.uint8).reshape(h, w)
                for ip, w, h in page.halves]
        a = np.hstack(rows)
        im = Image.fromarray((a * 23 % 256).astype(np.uint8))
        im.resize((a.shape[1] * 3, a.shape[0] * 3), Image.NEAREST).save(
            os.path.join(ROOT, "work", "gfx", f"page_{page.name}_{tag}.png"))

    for name, lines in pages().items():
        dec, _ = decompress(source_bytes(name + ".BIN"))
        shot(Page(name, dec), "before")
        shot(build(name, lines), "after")
    print(f"wrote work/gfx/page_*_{{before,after}}.png")


def resize(exe, pristine, name, size):
    """Point the executable's file table at the new packed length.

    Graphics files are loaded from a table of 12-byte {lba, size, pad}
    records (the first is at 0x4b4e4), not through ISO9660, so a file that
    grows is truncated on load unless its record is updated. Growth is still
    bounded by the sectors the file already occupies.
    """
    lba, old = json.load(open(LBA_MAP))[name + ".BIN"]
    rec = pristine.find(struct.pack("<II", lba, old))
    if rec < 0:
        raise SystemExit(f"{name}: no file-table record for lba {lba}")
    cap = ((old + 2047) // 2048) * 2048
    if size > cap:
        raise SystemExit(f"{name}: {size} bytes overruns its {cap}-byte sectors")
    exe[rec + 4:rec + 8] = struct.pack("<I", size)
    return rec


def apply():
    os.makedirs(DST_DIR, exist_ok=True)
    pristine = open(os.path.join(ROOT, "discs/extracted_ps1", "SLPS_001.54"), "rb").read()
    exe_path = os.path.join(DST_DIR, "SLPS_001.54")
    exe = bytearray(open(exe_path, "rb").read())
    for name, lines in pages().items():
        page = build(name, lines)
        packed = compress(bytes(page.dec))
        original = len(source_bytes(name + ".BIN"))
        check, _ = decompress(packed)
        assert check == bytes(page.dec), f"{name}: roundtrip mismatch"
        resize(exe, pristine, name, len(packed))
        print(f"{name}: {len(packed)} bytes (original {original}, "
              f"{len(packed) - original:+d})")
        open(os.path.join(DST_DIR, name + ".BIN"), "wb").write(packed)
    open(exe_path, "wb").write(bytes(exe))
    print(f"file-table sizes updated in {os.path.basename(exe_path)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    {"preview": preview, "apply": apply}[cmd]()
