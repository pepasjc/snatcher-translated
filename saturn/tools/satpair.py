"""Pair glyphs for the Saturn's cells: two 7-px-pitch Latin letters.

The PS1 draws a pair as two 6-px MS Gothic letters in a 12x12 glyph
(ps1/tools/pairfont.render_pair). The Saturn's font sprite is 16x14 with the
12x12 Japanese glyph at (1, 1) (satfont.py), but the text renderers place
the sprites at a **14-px pitch** - the dialogue box, the list menus and the
nameplate alike (measured on work/saturn/build1/look_result_f026584.png:
cells at x = 24, 38, 52; the PS1 pair's column 0 is cell column 1) - so
columns 14 and 15 of a cell lie under the next cell's 0 and 1 and the
usable width is 14. The PS1 pair copied in (ink columns 1..11) left a 4-px
gap after every two letters (zoom_text.png). Here a pair fills the 14: the
first letter in columns 0..6, the second in 7..13, each up to 6 px of ink
plus a 1-px gap, so the gap between letters is 1 px inside a pair and
across cells alike; columns 14 and 15 stay blank. The baseline is cell row
10, where the game's own fullwidth Latin (Ａ..ｚ, caps rows 2..10) and the
kana sit, so a row that mixes a fallback fullwidth letter, a pair and a
kanji stays on one line.

Letter art (`STYLE`, env SATPAIR_STYLE; `sheet` draws every style side by
side into work/saturn/font/pair16_sheet.png at the real 14-px pitch):
  x11       X11 misc-fixed 7x13 regular (public domain, lib/fonts/7x13.bdf,
            loaded by lib/bdffont.py): each letter is the font's own 7-px cell
            (ink + gap column), BDF row y -> cell row y, so its baseline
            (FONT_ASCENT 11: the letters' bottom row is BDF row 10) lands on
            cell row 10; caps rows 2..10, descenders 11..12. The default
            since 2026-09-29 (Luiz; the PS1's dialogue face is X11 6x13).
  gothic14  MS Gothic at 14 px: its halfwidth cell IS 7 px (6 px of ink,
            1 gap), caps 11 rows (cell rows 0..10), descenders to row 12.
            The default until 2026-09-29.
  gothic12  the PS1's MS Gothic 12 px letters (5-px ink, 9-row caps at
            rows 2..10, the kana's height) at the 7-px pitch: 2-px gaps.
  old       the PS1 pair as build1 drew it (12 px at column 1) - for the
            sheet only.
(A first cut used the game's own 7-px-wide fullwidth Latin at an 8-px pitch,
before the 14-px cell pitch was measured: two 7-px letters do not fit 14.)

    render_pair16(a, b[, style]) -> 14 row ints, bit 15 = cell column 0
    pair_cell(pair)               -> the same for a 2-char pair string
    set_cell(font, index, rows14) -> write a 16x14 cell into a block array
    python saturn/tools/satpair.py sheet [out.png]     the comparison sheet
    python saturn/tools/satpair.py show <text>         ASCII dump of a string's cells
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]
import sysfont

import satfont

CELL_W, CELL_H = satfont.CELL_W, satfont.CELL_H     # the 16 x 14 sprite
CELL_PITCH = 14               # columns between consecutive cells on screen
PITCH = 7                     # columns per letter
INK_W = 6                     # ink columns per letter (the 7th is the gap)
BASELINE = 10                 # cell row the game's fullwidth Latin stands on
STYLES = ("x11", "gothic14", "gothic12", "old")
STYLE = os.environ.get("SATPAIR_STYLE", "x11")
X11_BDF = os.path.join(ROOT, "lib", "fonts", "7x13.bdf")
OUT = os.path.join(WORK, "saturn", "font")
# MS Gothic size -> (image row its caps start on, cell row they go to)
GOTHIC_TOP = {12: (2, 2), 14: (2, 0)}

_font = None
_tab = None
_gothic = {}


def _game_font():
    global _font, _tab
    if _font is None:
        _font = satfont.load_font()
        _tab = satfont.table()
    return _font, _tab


def _gothic_font(size):
    if size not in _gothic:
        from PIL import ImageFont
        _gothic[size] = sysfont.truetype("msgothic.ttc", size)
    return _gothic[size]


def _cols_of(rows, w):
    """(first, last) ink column of `rows` (bit w-1 = column 0), or None."""
    cols = [x for x in range(w) if any(r & (1 << (w - 1 - x)) for r in rows)]
    return (cols[0], cols[-1]) if cols else None


def _shift(rows, w, dx):
    """Move ink dx columns right (negative = left) inside a w-wide row (bit w-1 = column 0)."""
    out = []
    for r in rows:
        out.append(((r << -dx) if dx < 0 else (r >> dx)) & ((1 << w) - 1))
    return out


def _from_gothic(ch, size):
    """MS Gothic `size` px, ink centred in the 6 ink columns of the 7-px slot,
    the caps moved to their cell row (GOTHIC_TOP)."""
    from PIL import Image, ImageDraw
    f = _gothic_font(size)
    img = Image.new("L", (size, size + 4), 0)
    ImageDraw.Draw(img).text((0, 0), ch, fill=255, font=f)
    img_top, cap_top = GOTHIC_TOP[size]
    if ch == "~":
        cap_top += 5                               # MS Gothic parks the tilde at the cap top; mid-height reads as one
    rows = [0] * CELL_H
    for y in range(img.height):
        cy = y - img_top + cap_top
        if not 0 <= cy < CELL_H:
            continue
        v = 0
        for x in range(min(img.width, PITCH)):
            if img.getpixel((x, y)) > 96:
                v |= 0x40 >> x                      # bit 6 = column 0 of the 7-px slot
        rows[cy] = v
    c = _cols_of(rows, PITCH)
    if c:
        w = min(c[1] - c[0] + 1, INK_W)
        rows = _shift(rows, PITCH, (INK_W - w) // 2 - c[0])
        rows = [r & ~1 for r in rows]              # the 7th column is the gap (only `_` reaches it)
    return rows


_x11 = None


def _from_x11(ch):
    """7x13: the glyph's 7 columns = the slot, BDF row y = cell row y."""
    global _x11
    if _x11 is None:
        import bdffont
        _x11 = bdffont.BDF(X11_BDF)
        assert _x11.ascent == 11 and _x11.height == 13 and _x11.advance == PITCH
    g = _x11.glyph(ch)
    assert g.shape == (13, PITCH), (ch, g.shape)
    rows = [0] * CELL_H
    for y in range(g.shape[0]):
        rows[y + BASELINE + 1 - _x11.ascent] = sum(0x40 >> x for x in range(PITCH) if g[y, x])
    return rows


def letter(ch, style=STYLE):
    """One letter as 14 row ints, bit 6 = column 0 of its 7-px slot."""
    if ch == " ":
        return [0] * CELL_H
    if style == "x11":
        return _from_x11(ch)
    if style == "gothic14":
        return _from_gothic(ch, 14)
    if style == "gothic12":
        return _from_gothic(ch, 12)
    raise ValueError(style)


def render_pair16(a, b, style=STYLE):
    """Two letters -> 14 row ints of the 16x14 cell, bit 15 = column 0."""
    if style == "old":
        return old_pair_cell(a + b)
    L, R = letter(a, style), letter(b, style)
    return [(L[y] << 9) | (R[y] << 2) for y in range(CELL_H)]   # columns 0..6 and 7..13; 14, 15 blank


def pair_cell(pair, style=STYLE):
    assert len(pair) == 2, pair
    return render_pair16(pair[0], pair[1], style)


def old_pair_cell(pair):
    """The PS1 12x12 pair at (1, 1) of the cell - build1's look."""
    import pairfont
    g = pairfont.render_pair(pair)
    rows12 = []
    for i in range(6):
        w = (g[3 * i] << 16) | (g[3 * i + 1] << 8) | g[3 * i + 2]
        rows12 += [w >> 12, w & 0xFFF]
    return [0] + [r << 3 for r in rows12] + [0]


def set_cell(font, index, rows14):
    """Write a 16x14 cell (bit 15 = column 0) into plane `index & 3` of its block."""
    blk, plane = index >> 2, index & 3
    base = blk * satfont.BLOCK
    for y in range(CELL_H):
        r = rows14[y]
        for x in range(CELL_W):
            on = (r >> (CELL_W - 1 - x)) & 1
            i = base + y * 8 + x // 2
            shift = 4 if x % 2 == 0 else 0
            nib = (font[i] >> shift) & 15
            nib = (nib | (1 << plane)) if on else (nib & ~(1 << plane))
            font[i] = (font[i] & ~(15 << shift)) | (nib << shift)


# ---- the sheet -------------------------------------------------------------

def text_cells(s, style=STYLE):
    """A string -> [14-row cell] the way the game would draw it: ASCII runs as
    pairs, `{..}` as fullwidth fallback letters, other characters from the font."""
    font, tab = _game_font()
    cells, buf, i = [], "", 0

    def flush():
        nonlocal buf
        if len(buf) % 2:
            buf += " "
        for k in range(0, len(buf), 2):
            cells.append(pair_cell(buf[k:k + 2], style))
        buf = ""

    def fw_cell(ch):
        fw = chr(0xFEE0 + ord(ch)) if ord(ch) < 0x80 else ch
        sj = int.from_bytes(fw.encode("cp932", "replace"), "big")
        g = tab.get(sj, 0)
        return satfont.cell_rows(font, g)

    while i < len(s):
        ch = s[i]
        if ch == "{":
            flush()
            j = s.index("}", i)
            for c in s[i + 1:j]:
                cells.append(fw_cell(c))
            i = j + 1
            continue
        if ord(ch) < 0x80:
            buf += ch
        else:
            flush()
            cells.append(fw_cell(ch))
        i += 1
    flush()
    return cells


SAMPLES = [
    "ギリアン",
    "Quite an attractive lady.",
    "JUNKER HQ. What can I do for you?",
    "Gillian Seed, Runner. My wife Jamie's",
    "Look  Talk  Move  Investigate  0123456789",
    "hand{ke}rchief cros{sr}oad gro{wt}h ＪＵＮＫＥＲ本部",
    "MAXIMUM WARP ZONE QUIZ! 99% ~ 'yes' (no) _",
]


def sheet(out, styles=STYLES, samples=SAMPLES, scale=3):
    """Every style's samples at the game's 14-px cell pitch and 15-px row pitch, 1:1 above, `scale`x below."""
    from PIL import Image, ImageDraw
    rows = []
    for st in styles:
        rows.append(("label", st))
        for s in samples:
            rows.append(("text", text_cells(s, st)))
    w = max(len(c) for k, c in rows if k == "text") * CELL_PITCH + 2
    pitch = 15                                 # the box's row pitch (173, 188, 204)
    lab_h = 12
    h1 = sum(lab_h if k == "label" else pitch for k, _ in rows)
    im = Image.new("RGB", (w + 8, h1 + 4), (28, 28, 36))
    dr = ImageDraw.Draw(im)
    y = 2
    for k, v in rows:
        if k == "label":
            dr.text((4, y), v, fill=(120, 200, 255))
            y += lab_h
            continue
        for ci, cell in enumerate(v):
            for cy, r in enumerate(cell):
                for x in range(CELL_W):
                    if r & (0x8000 >> x):
                        im.putpixel((4 + ci * CELL_PITCH + x, y + cy), (255, 255, 255))
        y += pitch
    big = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    combo = Image.new("RGB", (max(im.width, big.width), im.height + big.height + 8), (28, 28, 36))
    combo.paste(im, (0, 0))
    combo.paste(big, (0, im.height + 8))
    combo.save(out)
    return out


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cmd = argv[0] if argv else "sheet"
    os.makedirs(OUT, exist_ok=True)
    if cmd == "sheet":
        print(sheet(argv[1] if len(argv) > 1 else os.path.join(OUT, "pair16_sheet.png")))
    elif cmd == "show":
        cells = text_cells(" ".join(argv[1:]), STYLE)
        for y in range(CELL_H):
            print("".join("".join("#" if c[y] & (0x8000 >> x) else "." for x in range(CELL_PITCH)) for c in cells))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
