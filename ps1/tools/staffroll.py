"""Redraw the intro credit roll in English.

`CXD_BX30.BIN` is the roll the game plays after New Game — the `2042.12 /
NEO KOBE CITY` caption, the cast, and the staff list, over the city. It is
*not* the FMV: `MX2_S000.STR` carries the same credits but never plays in
that sequence (the roll renders at 256x240, MDEC playback here is 320x240).
Translating the movie left the on-screen text Japanese, which is what gave
this away.

It uses the same data-driven blitter as the red disclaimer, one draw list
per screen:

    4 items x 128x128, 4bpp, stacked  ->  one 128x512 glyph atlas
    draw list right after the image data, 22 screens of
        u32  count << 24
        count * { u16 y, u16 x, u8 h, u8 w, u16 src }
    then a u32 per screen pointing at its records, section-relative

The game reaches a screen through that pointer table rather than by walking
the counts, so it has to be rewritten alongside the lists — otherwise every
screen after the first draws the wrong text.

`src` addresses the atlas in 8x8 blocks, `src = (v/8)*16 + (u/8)`, so a
16-pixel glyph row is 0x20 apart and the atlas is capped at 128 wide by the
4 bits available for `u`. Glyphs are a 1-pixel outline in index 11 around an
interior that fades from index 8 at the top of the cell to 2 at the bottom;
index 0 is transparent, so the city shows through.

Capacity is the whole problem. The atlas is 32 shelves of 128 pixels and
English needs more width than Japanese, so text goes in at 12px rather than
the Japanese 16px - X11 "fixed" 6x13 (lib/bdffont.py, ROLL), set
PROPORTIONALLY: each glyph cropped to its ink with one blank column after
it and a 3-px space, because the font's fixed 6-px advance needs ~4,500 px
of shelf against the atlas's 4,096 - runs of two or more spaces are laid out as separate
records (a gap then costs no atlas space), and identical strings share one
copy. The tool prints the usage; if it overflows, shorten a line in
ps1/translation/staff_roll.json.

The draw list is rewritten in place at its original size: every screen is
padded back to its original record count with invisible blits, so nothing
after the table moves.

Usage:
  python staffroll.py preview     # render every screen to work/gfx/bx30_en/
  python staffroll.py apply       # write patched/CXD_BX30.BIN + exec size
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

NAME = "CXD_BX30"
TEXT = os.path.join(ROOT, "ps1/translation", "staff_roll.json")
DST = os.path.join(ROOT, "patched", NAME + ".BIN")

AW, AH = 128, 512              # atlas, four 128x128 items stacked
CELL = 16                      # shelf height, and the vertical src step is 2 blocks
SCREEN_W = 256
OUTLINE = 11                   # ink index of the 1px outline
GLYPH_GAP, SPACE = 1, 3       # proportional Tamzen: blank columns after a glyph, a space
GLYPH_TOP = 1                  # Tamzen's cell top in the 16-row shelf: caps on
                               # rows 3-9, where Calibri 11 at (1, 1) had them
GAP = 24                       # space between columns on one line
BLANK_SRC = (AH - 8) // 8 * 16 + (AW - 8) // 8   # reserved all-zero block


def gradient(y):
    """Interior ink index for row y of a 16-pixel cell: 8 at the top, 2 at
    the bottom, measured off the original glyphs."""
    return max(2, min(8, round(8 - y * 6 / 15)))


def load():
    """(decompressed container, item offsets, atlas, screens, table extent)."""
    import numpy as np
    dec = bytearray(decompress(source_bytes(NAME + ".BIN"))[0])
    base, size = sections(dec)[1]
    lst = items(dec, base, size, 1)
    offs = [ip for ip, _, _ in lst]
    if len(lst) != AH // 128 or any(whw * 2 != AW // 2 or h != 128
                                    for _, whw, h in lst):
        raise SystemExit("unexpected atlas geometry")
    atlas = np.zeros((AH, AW), np.uint8)
    for i, ip in enumerate(offs):
        d = np.frombuffer(dec[ip:ip + (AW // 2) * 128], np.uint8).reshape(128, AW // 2)
        atlas[i * 128:(i + 1) * 128, 0::2] = d & 0xF
        atlas[i * 128:(i + 1) * 128, 1::2] = d >> 4
    tbl = offs[-1] + (AW // 2) * 128 + 4 * len(offs)
    screens, off = [], tbl
    while off + 4 <= len(dec):
        hdr = struct.unpack_from("<I", dec, off)[0]
        cnt = hdr >> 24
        if (hdr & 0xFFFFFF) or cnt == 0:
            break
        recs = [struct.unpack_from("<HHBBH", dec, off + 4 + 8 * i) for i in range(cnt)]
        screens.append(recs)
        off += 4 + 8 * cnt
    return dec, offs, atlas, screens, (tbl, off)


def render_run(text):
    """A run of text as (mask, width): 1 where the glyph body is."""
    import numpy as np
    import bdffont
    m = bdffont.load(bdffont.ROLL).render(text, proportional=True,
                                              gap=GLYPH_GAP, space=SPACE)
    # One blank column on the left for the outline, as the Calibri runs had.
    a = np.zeros((CELL, m.shape[1] + 3), bool)
    a[GLYPH_TOP:GLYPH_TOP + m.shape[0], 1:1 + m.shape[1]] = m
    xs = np.nonzero(a.any(0))[0]
    if not len(xs):
        return a[:, :0], 0
    return a[:, :xs.max() + 2], int(xs.max() + 2)


def colour(mask):
    """A run's mask as atlas indices: the glyph body with the fade, a
    1-px outline around it. Coloured whole before it is sliced into chunks,
    so a run that spills onto the next shelf keeps its outline at the cut."""
    import numpy as np
    h, w = mask.shape
    out = np.zeros((h, w), np.uint8)
    # The original outlines 8-way, but at this size that closes the counters
    # of e and a; orthogonal keeps them open and reads the same on screen.
    # (render_run leaves a blank border, so the rolls never wrap ink.)
    grow = mask.copy()
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        grow |= np.roll(np.roll(mask, dy, 0), dx, 1)
    out[grow & ~mask] = OUTLINE
    for y in range(h):
        out[y][mask[y]] = gradient(y)
    return out


def pieces(part, shared):
    """Split a run at the words other runs repeat, so each is packed once:
    [(piece, x offset in the run)]. The pieces drawn at their offsets put
    the same pixels on screen as the whole run."""
    import bdffont
    font = bdffont.load(bdffont.ROLL)
    words, out, cur = part.split(" "), [], []
    def flush(upto):
        if cur:
            text = " ".join(cur)
            out.append((text, upto - len(text)))
            cur.clear()
    pos = 0
    for i, w in enumerate(words):
        if w in shared:
            flush(pos - 1 if pos else 0)
            out.append((w, pos))
        else:
            cur.append(w)
        pos += len(w) + 1
    flush(pos - 1)
    return [(t, font.width(part[:k], proportional=True, gap=GLYPH_GAP, space=SPACE))
            for t, k in out]


def build():
    import numpy as np
    spec = json.load(open(TEXT, encoding="utf-8"))["screens"]
    dec, offs, atlas, screens, (tbl, tbl_end) = load()
    if len(spec) != len(screens):
        raise SystemExit(f"{len(spec)} screens of text, {len(screens)} in the file")

    atlas[:] = 0
    cache = {}
    # Words more than one distinct run carries (SEED, BENSON, SOUND...) are
    # packed once and drawn by their own records: the proportional Tamzen
    # runs need ~4,250 px of shelf whole, ~4,040 with these shared, of 4,088.
    import collections
    runs = {p.strip() for lines in spec for line in lines
            for p in line.split("  ") if p.strip()}
    seen = collections.Counter(w for r in runs for w in set(r.split(" ")))
    shared = {w for w, n in seen.items() if n > 1}
    cur = [0, 0]                  # shelf, x — the packing cursor

    def place(text):
        """Pack a run, returning [(src, width)] chunks left to right.

        Runs are laid down end to end across the shelves and spill into the
        next one when a shelf fills, so the only waste is the 8-pixel
        rounding at the end of each run. First-fit per whole run instead
        wasted a third of the atlas: most runs are 80-110px against a
        128px shelf, so each shelf held exactly one."""
        if text in cache:
            return cache[text]
        mask, w = render_run(text)
        ink = colour(mask)
        chunks, done = [], 0
        while done < w:
            if cur[1] >= AW:
                cur[0] += 1
                cur[1] = 0
            if cur[0] >= AH // CELL:
                raise SystemExit(
                    f"atlas full: {text!r} does not fit — "
                    "shorten a line in ps1/translation/staff_roll.json")
            take = min(w - done, AW - cur[1])
            atlas[cur[0] * CELL:(cur[0] + 1) * CELL,
                  cur[1]:cur[1] + take] = ink[:, done:done + take]
            chunks.append((cur[0] * (CELL // 8) * 16 + cur[1] // 8, take))
            cur[1] += (take + 7) & ~7
            done += take
        cache[text] = chunks
        return chunks

    out = []
    for si, (lines, recs) in enumerate(zip(spec, screens)):
        ys = sorted({r[0] for r in recs})
        if len(lines) != len(ys):
            raise SystemExit(f"screen {si}: {len(lines)} lines of text, "
                             f"{len(ys)} on screen")
        made = []
        for y, line in zip(ys, lines):
            parts = [p.strip() for p in line.split("  ") if p.strip()]
            widths = [render_run(p)[1] for p in parts]
            x = (SCREEN_W - (sum(widths) + GAP * (len(parts) - 1))) // 2
            for part, pw in zip(parts, widths):
                for piece, dx in pieces(part, shared):
                    cx = x + dx
                    for src, w in place(piece):
                        made.append((y, cx, CELL, (w + 7) & ~7, src))
                        cx += w
                x += pw + GAP
        out.append(made)

    # The table is rewritten at its original byte length so nothing after it
    # moves, but the records are free to move between screens: a screen that
    # needs more than the original drew borrows from one that needs fewer.
    room = sum(len(r) for r in screens)
    need = sum(len(m) for m in out)
    if need > room:
        raise SystemExit(f"{need} records needed, table holds {room} — "
                         "shorten a line in ps1/translation/staff_roll.json")
    for _ in range(room - need):
        out[-1].append((0, 0, 8, 8, BLANK_SRC))

    for i, ip in enumerate(offs):
        band = atlas[i * 128:(i + 1) * 128]
        packed = (band[:, 0::2] & 0xF) | (band[:, 1::2] << 4)
        dec[ip:ip + (AW // 2) * 128] = packed.astype(np.uint8).tobytes()
    off = tbl
    starts = []
    for made in out:
        starts.append(off)
        struct.pack_into("<I", dec, off, len(made) << 24)
        for i, r in enumerate(made):
            struct.pack_into("<HHBBH", dec, off + 4 + 8 * i, *r)
        off += 4 + 8 * len(made)
    assert off == tbl_end, (off, tbl_end)
    # Immediately after the draw list sits a u32 per screen pointing at that
    # screen's records, section-relative (the section starts at byte 8). The
    # game reads a screen through this table, not by walking the counts, so
    # rewriting the lists without it drew the wrong screen at each slot: the
    # caption was right and everything after it slid, MIKA SLAYTON turning up
    # where JAMIE SEED belonged and four screens vanishing entirely.
    for i, st in enumerate(starts):
        struct.pack_into("<I", dec, tbl_end + 4 * i, st - 8)
    if atlas[AH - 8:, AW - 8:].any():
        raise SystemExit("the padding block at the end of the atlas is in use — "
                         "shorten a line in ps1/translation/staff_roll.json")
    used = cur[0] * AW + cur[1]
    print(f"atlas: {used} of {AW * (AH // CELL)} px used "
          f"({used * 100 // (AW * (AH // CELL))}%), {len(cache)} unique runs, "
          f"{sum(len(m) for m in out)} records")
    return bytes(dec), out, atlas


def preview():
    import numpy as np
    from PIL import Image
    dec, out, atlas = build()
    d = os.path.join(ROOT, "work", "gfx", "bx30_en")
    os.makedirs(d, exist_ok=True)
    Image.fromarray((atlas * 20 % 256).astype(np.uint8)).save(
        os.path.join(d, "atlas.png"))
    for i, made in enumerate(out):
        scr = np.zeros((240, SCREEN_W), np.uint8)
        for y, x, h, w, src in made:
            v, u = (src // 16) * 8, (src % 16) * 8
            blk = atlas[v:v + h, u:u + w]
            ink = np.where(blk == OUTLINE, 110, np.where(blk > 0, 255, 0))
            scr[y:y + h, x:x + w] = np.maximum(scr[y:y + h, x:x + w], ink)
        rows = np.nonzero(scr.any(1))[0]
        if not len(rows):
            continue
        im = Image.fromarray(scr[rows.min():rows.max() + 1])
        im.resize((im.width * 2, im.height * 2), Image.NEAREST).save(
            os.path.join(d, f"s{i:02d}.png"))
    print(f"wrote {d}")


def apply():
    dec, _, _ = build()
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
