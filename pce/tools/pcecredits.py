"""The opening's credits in English: 23 sprite strips and their sprite tables.

The credits over the city are sprite text: one RLE stream per credit in the
second opening block (rec 758, the 23 single-record display lists at 0x075b
+ 0x1c*k) decoded to VRAM $7000 as 16x16 cells (12-15 a strip), placed by a
sprite table - `{02 00 N}` then N x `{cgx, dy, dx, pattern lo, attr}`, dx/dy
from (64, 56), pattern lo = 0x80 + 2*cell, attr 0xB5 - reached through the
credit's 28-byte record (`02 0f 02 40 00 58 00 lo hi` at record + 7). The
tables share one 688-byte region (bank 0x1c, ptr 0x96ff..0x99af, a word
table follows) which is rewritten whole: every credit gets a type-02 table
sized for its English, credits with the same sprite layout share one, and
each record's pointer moves with its table. The staff credits' own tables
are types 04/06/08 with a longer header (`04 00 05 00 00 N`, `06 00 07 00
08 00 00 00 N`, `08 00 09 00 0a 00 33 00 00 00 N`) whose meaning is not
worked out; their entries are the same five bytes, and a type-02 table
shows the cast the same way, so every credit is written as type 02. The
strips sit back to back (a flags byte then the stream) and are repacked as
one run, each list's bank/pointer following its strip.

Each credit is two rows in the strip's cells: the role (small, above, dy 0)
and the name (below, dy 0x20) - the Japanese order - or one row for the
CAST / STAFF titles. Rows are runs of 32x16 sprites (two cells each, a
16x16 for a trailing cell), centred on the screen. Glyphs are the strip's
own style: fill 11 rimmed with 1 (12 px names in X11 6x13, 10 px roles in MS Gothic).

  python pce/tools/pcecredits.py show     # every strip before/after as PNG
  python pce/tools/pcecredits.py apply    # into patched/pce/snatcher_pce.bin
"""
import os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
import sysfont

import patch_pce as P
import pcecodec as C
import pcescene as S
import titlemenu as M
import pcepair

BLOCK = (758, 100)
TABLES = (0x96FF, 0x99AF)      # the sprite tables' region, as bank-0x1c pointers
TABLE_BANK = 0x1C
FILL, RIM = 11, 1
BASE_X = 128                   # every credit command's x; dx is a signed byte from it
CAST_CLASS = bytes([0xAE, 0x9B])
# a table drawing nothing: frame 0 at +2, N = 1, one sprite at dy -128 (the walker draws before
# it counts N down - N = 0 would draw 256 entries of whatever follows)
HIDDEN = bytes([0x02, 0x00, 0x01, 0x00, 0x80, 0x00, 0x80, 0xB5])      # the field after the table pointer in the cast's records
NAME_PX, ROLE_PX = 12, 10
# (role, name) per credit in strip order; a title has no name
CREDITS = [
    ("CAST", None),
    ("GILLIAN SEED", "Yusaku Yara"),
    ("METAL GEAR Mk.II", "Mami Koyama"),
    ("JAMIE SEED", "Kikuko Inoue"),
    ("RANDAM HAJILE", "Kaneto Shiozawa"),
    ("MIKA SLAYTON", "Mina Tominaga"),
    ("HARRY BENSON", "Ryuji Saikachi"),
    ("JEAN JACK GIBSON", "Isao Inokuchi"),
    ("BENSON CUNNINGHAM", "Goro Naya"),
    ("STAFF", None),
    ("EXECUTIVE PRODUCER", "Akihiko Nagata"),
    ("PLANNER & DIRECTOR", "Hideo Kojima"),          # 企画脚本監督: planning, script, direction
    ("PLANNER & DIRECTOR", "Hideo Kojima"),          # (the longer roles only fit at 8-9 px)
    ("CHARACTERS & ART", "Tomiharu Kinoshita"),      # キャラクターデザイン・原画
    ("MECHA DESIGN, GRAPHICS", "Yoshihiko Ota"),
    ("GRAPHICS", "Satoshi Yoshioka"),
    ("MAIN PROGRAM", "Yoshikazu Matsuhana"),
    ("PROGRAM", "Kenji Shinohara"),
    ("ASSISTANT DIRECTOR", "Shinya Inoue"),
    ("SCENARIO SYSTEM DESIGN", "Toshiya Adachi"),    # シナリオコンパイラ設計
    ("MUSIC", "Motoaki Furukawa (Kukeiha Club)"),
    ("SOUND EFFECTS", "Kazuki Muraoka"),
    ("PRODUCED BY", "KONAMI CO., LTD."),             # 制作著作 コナミ株式会社
]


def table_off(ptr):
    return (TABLE_BANK - 4) * 0x2000 + ptr - 0x8000


def strips(blk):
    """One entry per credit, in order: the display list (a single record to
    VRAM $7000, which loads the strip), the stream, and every sprite-table
    pointer in the command(s) that FOLLOW the list - `02 f x xx 00 yy 00 lo
    hi`, base (0x40, 0x58) for a credit, (0x60, 0x60) for CAST; credit 14
    has two of them."""
    import re
    lists = [off for off, recs in C.find_lists(blk, 4, 25)
             if len(recs) == 1 and recs[0][1] == 0 and recs[0][2] == 0x7000]
    lists = sorted(o for o in lists if 0x700 <= o < 0xA00)
    assert len(lists) == len(CREDITS), f"{len(lists)} credit lists"
    out = []
    cmd = re.compile(rb"\x02[\x00-\x7f].[\x00-\xff]\x00[\x00-\xff]\x00", re.S)
    cmd3 = re.compile(rb"\x03[\x00-\xff]\x00[\x00-\xff]\x00", re.S)
    for k, lst in enumerate(lists):
        nxt = lists[k + 1] if k + 1 < len(lists) else lst + 0x30
        after = blk[lst + 7:nxt]
        ptr_at = [lst + 7 + m.start() + 7 for m in cmd.finditer(after)]
        assert ptr_at, f"credit {k}: no sprite command after its list"
        # a type-03 command (`03 x x y y lo hi`: credit 14's second, the Japanese role's right
        # half at x 0xC0) names a table in the region rewritten below: it gets the hidden one
        extra = [a for a in (lst + 7 + m.start() + 5 for m in cmd3.finditer(after))
                 if TABLES[0] <= (blk[a] | blk[a + 1] << 8) < TABLES[1]]
        b, t, vl, vh, pl, ph = blk[lst:lst + 6]
        o = (b - 4) * 0x2000 + (pl | ph << 8) - 0x8000
        sp, flags, _ = C.image_stream(blk, o, 0)
        data, end, clean = C.decode(blk, sp)
        assert clean
        out.append({"ptr_at": ptr_at, "empty_at": extra, "list": lst, "stream": sp, "end": end,
                    "cells": M.cells_of(data[:len(data) // 128 * 128]).copy()})
    return out


def render(text, px):
    """A 1-bit mask of `text` at `px`: the names' 12 px in X11 6x13 (the dialogue's
    face, pcepair.FACE, top row trimmed), the smaller sizes in MS Gothic halfwidth."""
    if px == 12:
        import bdffont
        a = bdffont.load(pcepair.FACE).render(text).astype(np.uint8)
        xs = np.nonzero(a.any(axis=0))[0]
        ys = np.nonzero(a.any(axis=1))[0]
        return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    from PIL import Image, ImageDraw, ImageFont
    f = sysfont.truetype("msgothic.ttc", px)
    im = Image.new("L", (px * len(text) + 8, px + 4), 0)
    ImageDraw.Draw(im).text((1, 0), text, fill=255, font=f)
    a = (np.array(im) > 127).astype(np.uint8)
    xs = np.nonzero(a.any(axis=0))[0]
    ys = np.nonzero(a.any(axis=1))[0]
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def paint(mask):
    """Fill with a 1-px rim around it, in the strip's indices."""
    return M.paint_outline(mask, FILL, (RIM,)) if hasattr(M, "paint_outline") else None


# (role px, name px) tried in order until a credit's rows fit its strip
SIZES = [(ROLE_PX, NAME_PX), (10, 10), (9, 10), (9, 9), (8, 9), (8, 8)]


def rows_of(k, role_px, name_px):
    role, name = CREDITS[k]
    if name is None:
        return [(role, name_px, 0x10)]
    return [(role, role_px, 0x00), (name, name_px, 0x20)]


def widths_of(w, cell):
    """Sprite widths for a row `w` px wide starting at strip cell `cell`: a
    32x16 sprite's pattern must start on an even cell (the VDC clears bit 0
    of a CGX=1 pattern address - an odd start showed the previous cell), so
    a row starting odd leads with a 16-wide sprite."""
    n = (w + 15) // 16
    out = []
    if cell % 2 and n:
        out.append(16)
        n -= 1
    out += [32] * (n // 2) + [16] * (n % 2)
    return out


def layout(k, ncells):
    """[(row art, dy, [(cell, width, x)...])] and the sprite entries; rows
    take cells from 0 up. Sizes step down SIZES until both rows fit the
    strip. dx is a SIGNED byte from BASE_X (the command's x, rewritten
    from 64 to 128: a tail at dx 136 vanished, at 120 it showed)."""
    import opencards as O
    for role_px, name_px in SIZES:
        rows, entries, cell = [], [], 0
        for text, px, dy in rows_of(k, role_px, name_px):
            art = O.paint_outline(render(text, px), FILL, (RIM,))
            widths = widths_of(art.shape[1], cell)
            used = sum(wd // 16 for wd in widths)
            if cell + used > ncells:
                break
            x0 = (256 - sum(widths)) // 2
            assert -128 <= x0 - BASE_X and x0 + sum(widths) - BASE_X <= 128, (k, text, x0)
            sprites, x = [], x0
            for wd in widths:
                sprites.append((cell, wd, x))
                entries.append(bytes([1 if wd == 32 else 0, dy, (x - BASE_X) & 0xFF, 0x80 + 2 * cell, 0xB5]))
                cell += wd // 16
                x += wd
            rows.append((art, dy, sprites))
        else:
            return rows, entries
    sys.exit(f"credit {k} {CREDITS[k]}: {cell} cells used, the strip has {ncells}")


def compose(k, strip):
    """The strip's cells with the English rows drawn in; the sprite table bytes."""
    cells = strip["cells"]
    cells[:] = 0
    rows, entries = layout(k, len(cells))
    for art, dy, sprites in rows:
        band_w = sum(wd for _, wd, _ in sprites)
        band = np.zeros((16, band_w), np.uint8)
        y = (16 - art.shape[0]) // 2
        x = (band_w - art.shape[1]) // 2
        band[y:y + art.shape[0], x:x + art.shape[1]] = art
        bx = 0
        for cell, wd, _ in sprites:
            for j in range(wd // 16):
                cells[cell + j] = band[:, bx + 16 * j:bx + 16 * j + 16]
            bx += wd
    return cells, bytes([0x02, 0x00, len(entries)]) + b"".join(entries)


def build(blk):
    """(stream patches, table region bytes, byte patches). Strips that sit
    back to back (a flags byte, then the stream, then the next strip's flags
    byte) are repacked as one run from its start, and each list's bank and
    pointer move with its strip; a strip on its own is re-encoded in place.
    Every credit's command gets x = BASE_X, its table's pointer, and the
    cast's class field; a second command on the same credit (credit 14's
    type 03, `empty_at`) gets HIDDEN, the region's first table: one sprite at
    dy -128 (off the top). Left alone it drew bytes of the rewritten region as
    sprites at x 0xC0 (the flicker round Yoshihiko Ota, 2026-09-29); a table
    with N = 0 is no fix: the walker ($63CB) draws an entry before it counts
    N down, so 0 draws until the sprite table is full."""
    st = strips(blk)
    tables, patches = HIDDEN, []
    encoded, placed = {}, {}
    for k, s in enumerate(st):
        if s["stream"] not in encoded:
            cells, table = compose(k, s)
            encoded[s["stream"]] = (M.encode(M.bytes_of(cells)), table, s)
        table = encoded[s["stream"]][1]
        if table not in placed:            # the same sprite layout shares one
            placed[table] = TABLES[0] + len(tables)
            tables += table
        for i, at in enumerate(s["ptr_at"]):
            ptr = placed[table] if i == 0 else TABLES[0]
            patches.append((at, bytes([ptr & 0xFF, ptr >> 8])))
            patches.append((at - 4, bytes([BASE_X])))
            if CREDITS[k][1] is not None:
                patches.append((at + 2, CAST_CLASS))
        for at in s["empty_at"]:                # the hidden table, read as the cast's type 02 (the
            patches.append((at, bytes([TABLES[0] & 0xFF, TABLES[0] >> 8])))    # class field
            patches.append((at + 2, CAST_CLASS))     # names the table's type: de 9b read it as 08)
    room = TABLES[1] - TABLES[0]
    if len(tables) > room:
        sys.exit(f"the sprite tables need {len(tables)} B, the region holds {room}")
    tables += bytes(room - len(tables))
    # runs of back-to-back strips
    order = sorted(encoded)
    runs, run = [], [order[0]]
    for sp in order[1:]:
        if encoded[run[-1]][2]["end"] + 1 == sp:
            run.append(sp)
        else:
            runs.append(run)
            run = [sp]
    runs.append(run)
    streams = []
    for run in runs:
        start = run[0] - 1
        stop = encoded[run[-1]][2]["end"]
        old = bytes(blk[start:stop])
        new, at = b"", start
        for sp in run:
            data, _, s = encoded[sp]
            for lst in lists_of(st, sp):
                ptr = 0x8000 + at % 0x2000
                patches.append((lst, bytes([at // 0x2000 + 4])))
                patches.append((lst + 4, bytes([ptr & 0xFF, ptr >> 8])))
            new += bytes(1) + data
            at = start + len(new)
        if len(new) > len(old):
            sys.exit(f"the strips at {start:#x} need {len(new)} B, the run holds {len(old)}")
        streams.append((start, old, new + bytes(len(old) - len(new))))
    return streams, tables, patches


def lists_of(st, sp):
    return [s["list"] for s in st if s["stream"] == sp]


def apply(out_path=P.OUT):
    blk = S.block(*BLOCK)
    img = P.Image(out_path, P.T3 + P.RESERVE)
    base = (S.T2 + BLOCK[0]) * P.DATA
    streams, tables, patches = build(blk)
    for sp, old, new in streams:
        assert bytes(img.data[base + sp:base + sp + len(old)]) == old, f"stream at {sp:#x} is not pristine"
        img.write(base + sp, new)
    img.write(base + table_off(TABLES[0]), tables)
    for at, data in patches:
        img.write(base + at, data)
    print(f"{len(streams)} strip runs, {len(tables.rstrip(bytes(1)))} B of tables, {len(patches)} record patches; {img.flush()} sectors written")


def show(path=os.path.join(WORK, "pce", "credits.png")):
    from PIL import Image
    blk = S.block(*BLOCK)
    st = strips(blk)
    rows = []
    for k, s in enumerate(st):
        before = np.hstack(list(s["cells"]))
        cells, table = compose(k, {"cells": s["cells"].copy()})
        after = np.hstack(list(cells))
        w = max(before.shape[1], after.shape[1])
        rows.append(np.pad(before, ((0, 0), (0, w - before.shape[1]))))
        rows.append(np.pad(after, ((0, 0), (0, w - after.shape[1]))))
        rows.append(np.full((2, w), 15, np.uint8))
        print(f"{k:2d}: {len(s['cells'])} cells, {table[2]} sprites, table {len(table)} B")
    w = max(r.shape[1] for r in rows)
    sheet = np.vstack([np.pad(r, ((0, 0), (0, w - r.shape[1]))) for r in rows]) * 17
    Image.fromarray(sheet).resize((sheet.shape[1] * 2, sheet.shape[0] * 2), Image.NEAREST).save(path)
    print(path)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    show() if cmd == "show" else apply()
