"""The opening's last caption, "Konami Omni Building / JUNKER HQ", in English.

The caption under the tower at the end of the credit roll is neither text
nor a stored bitmap of its own: it is sixteen sprite cells cut from the Neo
Kobe sign sheets in CXH_B000.BIN (loaded compressed into RAM at 0x8013D800
early in the opening, decompressed to the asset heap ~frame 25850):

    section 1 item 5   rows 48-63,  x 0-63    コナミオ   (four 16 px cells)
                       rows 64-79,  x 0-63    ムニビル   (the second half of line 1)
                       rows 96-111, x 80-127  JUN        (three 16 px serif caps)
                       rows 112-127,x 80-127  KER
    section 1 item 4   rows 80-95,  x 0-31    本部       (two 16 px cells)

Glyph pixels use index 237 (bright) and 170 (dim, Konami's shadow) on 0,
which is transparent; the caption's CLUT maps them to white (248) and
(64, 56, 64).

Geometry, measured with `cal` (0.9.2): every cell is drawn whole, all 16
texel columns and all 16 rows 1:1, at its own screen x, eight cells per
line at an irregular 11-13 px pitch - so each cell overlaps its neighbour
by 3-5 columns, where both cells' non-zero texels show. The starts, in the
280-px-wide Beetle capture (line 1 at y 166, line 2 at y 182):

    line 1  90 102 113 125 137 150 162 175
    line 2  89 100 113 125 137 149 162 175

Every column 89-190 is covered, so any 16-row line can be reproduced
exactly: the English is drawn at screen resolution and each column given
to one cell (the one whose centre is nearest), blank in the others. (Until
0.9.2 the tool assumed texels 0-11 at a 12 px pitch; that drew line 1's
letters unevenly spaced and kept Konami's JUNKER beside a serif "HQ".)

Line 1 "KONAMI OMNI BLDG" is X11 "fixed" 6x13 (16 characters = 96 px);
line 2 "JUNKER HQ" is redrawn whole in Tamzen 8x16 bold with 2 px between
letters, white with a 1-px dim shadow right, down and diagonal as
Konami's letters have. Both centred on x 138 (Luiz's approved mock-up,
work/capimg/hq_options.png option A). The caption reveals cell by cell, so
a letter split between cells appears in two steps.

The container is recompressed in place (21 sectors) and the executable's
file-table size updated, as gfxpages does.

    python ps1/tools/introcaption.py preview      # work/introcaption_preview.png
    python ps1/tools/introcaption.py apply        # patched/CXH_B000.BIN + exec size
    python ps1/tools/introcaption.py cal OUT.BIN  # calibration container (dev)
    python ps1/tools/introcaption.py fit FRAME.png  # cell starts from a capture of it
"""
import os, sys
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
import bdffont

NAME = "CXH_B000"
BRIGHT, DIM = 237, 170
LINE1 = "KONAMI OMNI BLDG"
LINE2 = "JUNKER HQ"
LINE2_SPACING = 2
CENTRE = 138                   # screen x both lines centre on
LINE1_TOP, LINE2_TOP = 1, 1    # font cell top within the line's 16 rows

# Every caption cell as (item, row0, col0): line 1's eight kana cells, then
# line 2's eight - JUN, KER, then the two HONBU cells.
LINE1_CELLS = [(5, 48, 16 * i) for i in range(4)] + [(5, 64, 16 * i) for i in range(4)]
LINE2_CELLS = ([(5, 96, 80 + 16 * i) for i in range(3)] + [(5, 112, 80 + 16 * i) for i in range(3)]
               + [(4, 80, 16 * i) for i in range(2)])
# Screen x of each cell's texel 0 (the `cal`/`fit` measurement above).
LINE1_STARTS = [90, 102, 113, 125, 137, 150, 162, 175]
LINE2_STARTS = [89, 100, 113, 125, 137, 149, 162, 175]
LINE1_Y, LINE2_Y = 166, 182    # screen rows (for the preview and `fit`)
SCREEN_W = 280


def load():
    raw = gfxpages.source_bytes(NAME + ".BIN")
    dec, _ = decompress(raw)
    dec = bytearray(dec)
    base, size = sections(dec)[1]
    its = items(dec, base, size, 1)
    return raw, dec, its


def tile(dec, its, k):
    ip, whw, h = its[k]
    W = whw * 2
    return np.frombuffer(bytes(dec[ip:ip + W * h]), dtype=np.uint8).reshape(h, W).copy(), ip, W


def shadowed(m):
    """Ink BRIGHT, with DIM on the right, lower and lower-right neighbours
    that are not ink themselves."""
    h, w = m.shape
    out = np.zeros((h + 1, w + 1), np.uint8)
    for dy, dx in ((1, 0), (0, 1), (1, 1)):
        out[dy:dy + h, dx:dx + w][m] = DIM
    out[:h, :w][m] = BRIGHT
    return out


def screen_lines():
    """The two caption lines as they should appear: 16 x SCREEN_W each, in
    texture indices."""
    lines = []
    l1 = bdffont.crop(bdffont.load(bdffont.DIALOGUE).render(LINE1))
    l1 = np.where(l1, BRIGHT, 0).astype(np.uint8)
    l2 = shadowed(bdffont.crop(bdffont.load(bdffont.CAPTION).render(
        LINE2, spacing=LINE2_SPACING)))
    # the shadow's extra column does not count for centring
    for img, top, w in ((l1, LINE1_TOP, l1.shape[1]), (l2, LINE2_TOP, l2.shape[1] - 1)):
        scr = np.zeros((16, SCREEN_W), np.uint8)
        x = CENTRE - w // 2
        h = min(img.shape[0], 16 - top)
        if img[h:].any():
            raise SystemExit("caption line taller than its 16-row cells")
        scr[top:top + h, x:x + img.shape[1]] = img[:h]
        lines.append(scr)
    return lines


def slice_cells(scr, starts):
    """16x16 texture cells that draw `scr` when placed at `starts`."""
    cols = np.nonzero(scr.any(0))[0]
    owner = {}
    for x in range(SCREEN_W):
        cover = [c for c, s in enumerate(starts) if s <= x < s + 16]
        if cover:
            owner[x] = min(cover, key=lambda c: abs(x - (starts[c] + 7.5)))
    if len(cols) and any(x not in owner for x in cols):
        raise SystemExit("caption text runs outside the columns its cells cover")
    out = []
    for c, s in enumerate(starts):
        cell = np.zeros((16, 16), np.uint8)
        for u in range(16):
            if owner.get(s + u) == c:
                cell[:, u] = scr[:, s + u]
        out.append(cell)
    return out


def build():
    raw, dec, its = load()
    l1, l2 = screen_lines()
    for cells_, starts, scr in ((LINE1_CELLS, LINE1_STARTS, l1), (LINE2_CELLS, LINE2_STARTS, l2)):
        for (k, r0, c0), pix in zip(cells_, slice_cells(scr, starts)):
            t, ip, W = tile(dec, its, k)
            t[r0:r0 + 16, c0:c0 + 16] = pix
            dec[ip:ip + W * t.shape[0]] = t.tobytes()
    return raw, bytes(dec), its


def composite(dec, its):
    """The caption as the cells draw it (later cells over earlier ones)."""
    view = np.zeros((32, SCREEN_W), np.uint8)
    for row, cells_, starts in ((0, LINE1_CELLS, LINE1_STARTS), (16, LINE2_CELLS, LINE2_STARTS)):
        for (k, r0, c0), s in zip(cells_, starts):
            t, _, _ = tile(dec, its, k)
            cell = t[r0:r0 + 16, c0:c0 + 16]
            dst = view[row:row + 16, s:s + 16]
            dst[cell > 0] = cell[cell > 0]
    return view


def preview():
    raw, dec, its = build()
    view = composite(bytearray(dec), its)
    rgb = np.zeros(view.shape + (3,), np.uint8)
    rgb[view == BRIGHT] = (248, 248, 248)
    rgb[view == DIM] = (64, 56, 64)
    Image.fromarray(rgb[:, 60:220]).resize((160 * 4, 32 * 4), Image.NEAREST).save(
        os.path.join(ROOT, "work", "introcaption_preview.png"))
    print("work/introcaption_preview.png")


def apply():
    raw, dec, its = build()
    packed = compress(dec)
    check, _ = decompress(packed)
    assert bytes(check) == dec, "roundtrip mismatch"
    print(f"{NAME}: {len(raw)} -> {len(packed)} bytes")
    out = os.path.join(gfxpages.DST_DIR, NAME + ".BIN")
    open(out, "wb").write(packed)
    pristine = open(os.path.join(ROOT, "discs/extracted_ps1", "SLPS_001.54"), "rb").read()
    exe_path = os.path.join(gfxpages.DST_DIR, "SLPS_001.54")
    exe = bytearray(open(exe_path, "rb").read())
    gfxpages.resize(exe, pristine, NAME, len(packed))
    open(exe_path, "wb").write(exe)
    print("wrote", out)


def calibration(dec, its):
    """Every cell's texel columns coded in its own pixels: rows 0 and 15 a
    marker, rows 1-14 seven bits two rows each - the texel column u (bits
    0-3) and the cell's index on its line (bits 4-6), bright = 1. A capture
    then says which texel of which cell lands on each screen column; where
    two cells overlap the column reads as the OR of both codes."""
    for cells_ in (LINE1_CELLS, LINE2_CELLS):
        for ci, (k, r0, c0) in enumerate(cells_):
            t, ip, W = tile(dec, its, k)
            for u in range(16):
                code = u | ci << 4
                col = np.zeros(16, np.uint8)
                col[0] = col[15] = BRIGHT
                for b in range(7):
                    if code >> b & 1:
                        col[1 + 2 * b:3 + 2 * b] = BRIGHT
                t[r0:r0 + 16, c0 + u] = col
            dec[ip:ip + W * t.shape[0]] = t.tobytes()


def cal(out):
    """Write the calibration container to `out`. Dev use: write it over
    CXH_B000 in a COPY of the built image (same LBA; pad to the exec's
    file-table size), capture the caption (~frame 28300 of a New Game boot)
    and run `fit` on the frame."""
    raw, dec, its = load()
    calibration(dec, its)
    packed = compress(bytes(dec))
    open(out, "wb").write(packed)
    print(f"{out}: {len(packed)} bytes")


def fit(frame):
    """Each cell's screen start from a capture of the calibration pattern,
    under the model 'every cell draws texels 0-15 1:1, overlaps OR'."""
    a = np.asarray(Image.open(frame).convert("RGB")).astype(int).mean(2) > 200
    for name, y0 in (("line 1", LINE1_Y), ("line 2", LINE2_Y)):
        def code(x):
            col = a[y0:y0 + 16, x]
            if not (col[0] and col[15]):
                return None
            return sum(1 << b for b in range(7) if col[1 + 2 * b])
        obs = {x: code(x) for x in range(a.shape[1])}
        starts, x = [], min(k for k, v in obs.items() if v is not None)
        for c in range(8):
            def score(s):
                trial = starts + [s]
                return sum(obs.get(xx) == _pred(trial, xx)
                           for xx in range(s, s + 16))
            s = max(range(x, x + 20), key=score)
            starts.append(s)
            x = s + 1
        bad = [xx for xx, v in obs.items() if v != (_pred(starts, xx) if any(
            st <= xx < st + 16 for st in starts) else None)]
        print(f"{name}: starts {starts}, {len(bad)} column(s) off the model")


def _pred(starts, x):
    v = 0
    for c, s in enumerate(starts):
        if s <= x < s + 16:
            v |= c << 4 | (x - s)
    return v


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if cmd == "cal":
        cal(sys.argv[2])
    elif cmd == "fit":
        fit(sys.argv[2])
    else:
        {"preview": preview, "apply": apply}[cmd]()
