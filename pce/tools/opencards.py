"""The opening's text cards in English: tile pictures redrawn from text.

The disclaimer, the dedication and the RSS notice at the start of the
opening are not strings but pictures: each is a display list in the first
opening block (rec 858) with one tile stream and one BAT stream (type 8,
flags 0x60: direct mode, 64-byte runs = columns of the 32x32 map). The
Japanese is drawn in the System Card's typeface; the English is set in the
same 12-px halfwidth face the dialogue uses (X11 6x13, as pcepair.halffont),
at the line tops of the original, inside the same box, and the two streams
are re-encoded in place - every tile picture keeps its VRAM base and the
new stream may not outgrow the old one.

  python pce/tools/opencards.py show      # the originals and the English as PNG
  python pce/tools/opencards.py apply     # into patched/pce/snatcher_pce.bin
"""
import os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import patch_pce as P
import pcecodec as C
import pcescene as S
import tilescan as T
import titlemenu as M

BLOCK = (858, 100)
BANK0 = 4
CARDS = [
    # list offset, the English rows, ink and paper indices, alignment
    {"list": 0x49, "fg": 1, "bg": 6, "align": "center",     # each line centred, as the PS1
     "text": ["This story is fiction. The", "groups, companies and persons",
              "appearing in it are fictitious,", "and any resemblance to real",
              "ones is purely coincidental."]},
    {"list": 0x66, "fg": 1, "bg": 0, "align": "center",
     "text": ["Dedicated to all the", "cyberpunks fighting in a", "world full of deceit.", ""]},
    {"list": 0x111, "fg": 7, "bg": 0, "align": "center", "ymin": 120,     # the logo above stays
     "text": ["This game uses the", "RSS (Roland Sound Space)", "system in places."]},
]
FONT = "6x13"                          # lib/fonts, top row trimmed = 12 rows (pcepair.FACE)
GLYPH_H = 12
# Sprite captions. The date and place cards ("1991年6月6日 / モスクワ", "50年後")
# are 32x32 sprites from two streams of rec 858 (VRAM $5000 and $5800, 32 and
# 16 cells): a band of n sprites is 32n x 32 pixels, cells row-major per
# sprite, glyphs light grey (7) with a blue two-step shadow (8, then 14). The
# second opening block (rec 758) captions the city with "2042.12" and
# ネオコウベシティ as four 32x16 sprites (cells 16-23 of the $4000 stream of
# list 0xae): a double dark outline (2 inside 1) round a light fill (11).
# A band lists its cells as (stream, cell, x, y) inside the band.


def sprites32(*firsts):
    """Cells of a row of 32x32 sprites: (stream, first cell) each."""
    out = []
    for k, (si, c) in enumerate(firsts):
        out += [(si, c, 32 * k, 0), (si, c + 1, 32 * k + 16, 0), (si, c + 2, 32 * k, 16), (si, c + 3, 32 * k + 16, 16)]
    return out


def row16(si, first, n):
    """Cells of n consecutive 16-px cells in one row."""
    return [(si, first + k, 16 * k, 0) for k in range(n)]


SPRITE_SETS = [
    {"block": (858, 100), "streams": [0x1e656, 0x1eede], "height": 32,
     "style": {"kind": "shadow", "hi": 7, "fill": 7, "shadow": (8, 14)},
     "cards": [{"label": "June 6, 1991", "cells": sprites32((0, 0), (0, 4), (0, 8), (0, 12), (0, 16), (0, 20)), "y": 10},
               {"label": "Moscow", "cells": sprites32((0, 24), (0, 28), (1, 0)), "y": 10},
               {"label": "50 years later", "cells": sprites32((1, 4), (1, 8), (1, 12)), "y": 10}]},
    # the katakana straddled the 32x32 sprites of the "2042.12" row above (their
    # lower cells 2 3 6 7 10 11 14 15 hold the digits' feet and the kana's tops),
    # so the band is 32 rows and only its lower part is cleared
    {"block": (758, 100), "streams": [0x10101], "height": 32,
     "style": {"kind": "outline", "fill": 11, "rings": (2, 1)},
     "cards": [{"label": "NEO KOBE CITY", "y": 12, "clear": 10,
                "cells": [(0, c, x, 0) for c, x in zip((2, 3, 6, 7, 10, 11, 14, 15), range(0, 128, 16))]
                         + [(0, c, x, 16) for c, x in zip(range(16, 24), range(0, 128, 16))]}]},
]
SPRITE_MASKS = os.path.join(ROOT, "pce", "translation", "opening_sprites.json")

# The caption over the building shot (コナミオムニビル / ＪＵＮＫＥＲ本部) is a
# ready-decoded message in the opening's code file (rec 126): control bytes
# and raw Shift-JIS, copied to the engine's message buffer ($3610) by the loop
# at $8B77 (LDA $8BDB,X) and drawn by the dialogue renderer. No decoder runs,
# so no English flag: the letters go in as the BIOS's fullwidth Latin, one
# cell each, and the longer message moves to the file's free tail.
CAPTION = {"rec": (126, 3), "buffer": 0x0BDB, "load": 0x0B78, "free": 0x15C2, "col": 2,
           "lines": ["KONAMI OMNI BLDG", "JUNKER HQ"]}


def caption():
    """(old file bytes, new file bytes) for the opening's code file."""
    import pcetext as T
    old = S.block(*CAPTION["rec"])
    b = CAPTION["buffer"]
    head = old[b:b + 9]                                    # fc 0c f9 81 fe 04 fb 06 02
    assert head[:2] == b"\xfc\x0c" and head[6:9] == b"\xfb\x06\x02", head.hex()
    msg = bytearray(head[:6])
    for k, line in enumerate(CAPTION["lines"]):
        msg += bytes([0xFB, CAPTION["col"], 0x02 + k])          # fb col row, as the original's fb 06 02
        msg += T.encode_raw(line)
    msg.append(0xFF)
    new = bytearray(old)
    free = CAPTION["free"]
    assert not any(old[free:]) and free + len(msg) <= len(old)
    new[free:free + len(msg)] = msg
    addr = 0x8000 + free
    load = CAPTION["load"]
    assert old[load - 1] == 0xBD and old[load:load + 2] == bytes([b & 0xFF, 0x80 | (b >> 8)])
    new[load:load + 2] = bytes([addr & 0xFF, addr >> 8])
    return bytes(old), bytes(new)


def paint_outline(mask, fill, rings):
    """Mask -> fill with concentric 1-px rings round it (inner ring first)."""
    n = len(rings)
    h, w = mask.shape
    m = np.zeros((h + 2 * n, w + 2 * n), np.uint8)
    m[n:n + h, n:n + w] = mask
    out = np.zeros_like(m)
    grown = m > 0
    layers = [grown]
    for _ in rings:
        g = layers[-1].copy()
        g[1:, :] |= layers[-1][:-1, :]
        g[:-1, :] |= layers[-1][1:, :]
        g[:, 1:] |= layers[-1][:, :-1]
        g[:, :-1] |= layers[-1][:, 1:]
        layers.append(g)
    for k in range(n, 0, -1):
        out[layers[k]] = rings[k - 1]
    out[grown] = fill
    return out


def card(blk, off):
    """(tile record, bat record) of a card's display list, decoded."""
    recs = dict(C.find_lists(blk, BANK0, 25))[off]
    out = []
    for b, t, va, ptr, o in recs:
        sp, flags, rowlen = C.image_stream(blk, o, t)
        data, end, clean = C.decode(blk, sp)
        assert clean
        out.append({"bank": b, "type": t, "vram": va, "off": o, "stream": sp, "end": end,
                    "flags": flags, "rowlen": rowlen, "data": data})
    tiles, bat = out
    assert tiles["type"] == 0 and bat["type"] == 8 and bat["flags"] & 0x60 == 0x60
    return tiles, bat


def grid_of(bat):
    """The BAT stream as a rows x cols array of words."""
    per = bat["rowlen"] // 2
    words = np.frombuffer(bat["data"][:len(bat["data"]) // bat["rowlen"] * bat["rowlen"]], dtype="<u2")
    return words.reshape(-1, per).T.copy()


def picture(tiles, bat):
    """The card as pixels (palette indices) and its grid."""
    grid = grid_of(bat)
    base = tiles["vram"] // 16
    tl = T.decode(np.frombuffer(tiles["data"][:len(tiles["data"]) // 32 * 32], np.uint8).reshape(-1, 32))
    h, w = grid.shape
    img = np.zeros((h * 8, w * 8), np.uint8)
    for y in range(h):
        for x in range(w):
            k = (int(grid[y, x]) & 0xFFF) - base
            if 0 <= k < len(tl):
                img[y * 8:y * 8 + 8, x * 8:x * 8 + 8] = tl[k]
    return img, grid


def text_rows(img, fg):
    """(top, bottom) of every line of ink in the picture."""
    ink = (img == fg).any(axis=1)
    rows, y = [], 0
    while y < len(ink):
        if ink[y]:
            y0 = y
            while y < len(ink) and ink[y]:
                y += 1
            rows.append((y0, y - 1))
        else:
            y += 1
    return rows


def render_line(text):
    """A 12-px halfwidth line as a 1-bit array."""
    import bdffont
    f = bdffont.load(FONT)
    assert f.height == GLYPH_H
    a = f.render(text).astype(np.uint8)
    xs = np.nonzero(a.any(axis=0))[0]
    return a[:, :xs.max() + 1] if len(xs) else a[:, :0]


def english(c, img, grid, tiles):
    """The card's pixels with the English in place of the Japanese."""
    fg, bg = c["fg"], c["bg"]
    base = tiles["vram"] // 16
    # the text box: every cell whose tile is ink-on-paper only
    tl = T.decode(np.frombuffer(tiles["data"][:len(tiles["data"]) // 32 * 32], np.uint8).reshape(-1, 32))
    textcell = np.zeros(grid.shape, bool)
    for y in range(c.get("ymin", 0) // 8, grid.shape[0]):
        for x in range(grid.shape[1]):
            k = (int(grid[y, x]) & 0xFFF) - base
            if 0 <= k < len(tl):
                t = tl[k]
                textcell[y, x] = (t == fg).any() and set(np.unique(t).tolist()) <= {fg, bg}
    ys, xs = np.nonzero(textcell)
    y0, y1, x0, x1 = ys.min() * 8, ys.max() * 8 + 8, xs.min() * 8, xs.max() * 8 + 8
    out = img.copy()
    box = out[y0:y1, x0:x1]
    lines = text_rows(box, fg)
    # glyph lines at the original line tops, one per original line; the line
    # pitch carries on for any extra row of English
    pitch = (lines[1][0] - lines[0][0]) if len(lines) > 1 else 16
    tops = [t for t, _ in lines]
    while len(tops) < len(c["text"]):
        tops.append(tops[-1] + pitch)
    box[box == fg] = bg
    # the left margin of the original text, for left-aligned cards
    ink_cols = np.nonzero((img[y0:y1, x0:x1] == fg).any(axis=0))[0]
    left = int(ink_cols.min()) if len(ink_cols) else 0
    width = x1 - x0
    for text, top in zip(c["text"], tops):
        if not text:
            continue
        g = render_line(text)
        # centred on the screen, not the box (the disclaimer's box sits 4 px left)
        x = left if c["align"] == "left" else (img.shape[1] - g.shape[1]) // 2 - x0
        if x < 0 or x + g.shape[1] > width or top + GLYPH_H > box.shape[0]:
            sys.exit(f"card {c['list']:#x}: {text!r} does not fit the box")
        win = box[top:top + GLYPH_H, x:x + g.shape[1]]
        win[g > 0] = fg
    return out, (y0, y1, x0, x1)


def retile(out, grid, tiles, bat, region):
    """New tile data and BAT words for the picture: unique tiles inside the
    region, in scan order, after the original's tiles the region does not
    use (the blank and the frame keep their ids)."""
    base = tiles["vram"] // 16
    y0, y1, x0, x1 = region
    tl = T.decode(np.frombuffer(tiles["data"][:len(tiles["data"]) // 32 * 32], np.uint8).reshape(-1, 32))
    used = set()
    for y in range(grid.shape[0]):
        for x in range(grid.shape[1]):
            if not (y0 // 8 <= y < y1 // 8 and x0 // 8 <= x < x1 // 8):
                used.add((int(grid[y, x]) & 0xFFF) - base)
    keep = sorted(k for k in used if 0 <= k < len(tl))
    newtiles = [tl[k] for k in keep]
    ids = {k: i for i, k in enumerate(keep)}          # old index -> new index
    seen = {tl[k].tobytes(): i for i, k in enumerate(keep)}
    newgrid = grid.copy()
    for y in range(grid.shape[0]):
        for x in range(grid.shape[1]):
            w = int(grid[y, x])
            if y0 // 8 <= y < y1 // 8 and x0 // 8 <= x < x1 // 8:
                t = out[y * 8:y * 8 + 8, x * 8:x * 8 + 8]
                key = t.tobytes()
                if key not in seen:
                    seen[key] = len(newtiles)
                    newtiles.append(t.copy())
                newgrid[y, x] = (w & 0xF000) | (base + seen[key])
            else:
                k = (w & 0xFFF) - base
                if k in ids:
                    newgrid[y, x] = (w & 0xF000) | (base + ids[k])
    return np.array(newtiles, np.uint8), newgrid


def streams(blk):
    """[(record, old bytes, new bytes)] for every card."""
    out = []
    for c in CARDS:
        tiles, bat = card(blk, c["list"])
        img, grid = picture(tiles, bat)
        pic, region = english(c, img, grid, tiles)
        newtiles, newgrid = retile(pic, grid, tiles, bat, region)
        room = len(tiles["data"]) // 32
        if len(newtiles) > room:
            sys.exit(f"card {c['list']:#x}: {len(newtiles)} tiles, the original has {room}")
        tdata = S.encode_tiles(newtiles)
        old_t = bytes(blk[tiles["stream"]:tiles["end"]])
        new_t = M.encode(tdata, limit=len(old_t))
        words = newgrid.T.astype("<u2").tobytes()
        old_b = bytes(blk[bat["stream"]:bat["end"]])
        new_b = M.encode(words + bat["data"][len(words):], limit=len(old_b))
        for old, new in ((old_t, new_t), (old_b, new_b)):
            back, _, ok = C.decode(new, 0)
            assert ok and len(new) == len(old)
        out.append((c, tiles, old_t, new_t, bat, old_b, new_b, len(newtiles)))
    return out


def sprite_cells(blk, sset):
    """A set's sprite streams decoded: [(stream start, end, cells)]."""
    out = []
    for off in sset["streams"]:
        sp, flags, _ = C.image_stream(blk, off, 0)
        data, end, clean = C.decode(blk, sp)
        assert clean and flags == 0
        out.append([sp, end, M.cells_of(data).copy()])
    return out


def band_of(streams, c, height):
    """A card's band assembled from its cells."""
    w = max(x for _, _, x, _ in c["cells"]) + 16
    band = np.zeros((height, w), np.uint8)
    for si, cell, x, y in c["cells"]:
        band[y:y + 16, x:x + 16] = streams[si][2][cell]
    return band


def sprite_english(blk, sset):
    """The set's streams with the English bands painted in."""
    import json
    masks = {k: np.array([[1 if ch == "#" else 0 for ch in row] for row in v], np.uint8)
             for k, v in json.load(open(SPRITE_MASKS, encoding="utf-8")).items()}
    streams = sprite_cells(blk, sset)
    st, h = sset["style"], sset["height"]
    for c in sset["cards"]:
        w = max(x for _, _, x, _ in c["cells"]) + 16
        band = band_of(streams, c, h)
        band[c.get("clear", 0):] = 0
        if st["kind"] == "shadow":
            art = M.paint(masks[c["label"]], st["hi"], st["fill"], st["shadow"])
        else:
            art = paint_outline(masks[c["label"]], st["fill"], st["rings"])
        if art.shape[1] > w or c["y"] + art.shape[0] > h:
            sys.exit(f"{c['label']!r}: {art.shape[1]}x{art.shape[0]} does not fit {w}x{h}")
        x = (w - art.shape[1]) // 2
        band[c["y"]:c["y"] + art.shape[0], x:x + art.shape[1]] = art
        for si, cell, cx, cy in c["cells"]:
            streams[si][2][cell] = band[cy:cy + 16, cx:cx + 16]
    return streams


def sprite_streams(blk, sset):
    """[(old bytes, new bytes)] for a set's sprite streams."""
    out = []
    for sp, end, cells in sprite_english(blk, sset):
        old = bytes(blk[sp:end])
        raw = M.bytes_of(cells)
        new = M.encode(raw, limit=len(old))
        back, _, ok = C.decode(new, 0)
        assert ok and back == raw
        out.append((old, new))
    return out


def replace(img, old, new, what):
    hits, i = [], img.data.find(old)
    while i >= 0:
        hits.append(i)
        img.write(i, new)
        i = img.data.find(old, i + 1)
    if len(hits) != 1:
        sys.exit(f"{what}: found {len(hits)} times")


def apply(out_path=P.OUT):
    blk = S.block(*BLOCK)
    img = P.Image(out_path, P.T3 + P.RESERVE)
    for c, tiles, old_t, new_t, bat, old_b, new_b, n in streams(blk):
        for rec, old, new in ((tiles, old_t, new_t), (bat, old_b, new_b)):
            replace(img, old, new, f"card {c['list']:#x}: stream at {rec['stream']:#x}")
        print(f"card {c['list']:#x}: {n} tiles, streams {len(old_t)} B and {len(old_b)} B rewritten")
    for sset in SPRITE_SETS:
        sblk = S.block(*sset["block"])
        for k, (old, new) in enumerate(sprite_streams(sblk, sset)):
            replace(img, old, new, f"rec {sset['block'][0]} sprite stream {sset['streams'][k]:#x}")
            print(f"rec {sset['block'][0]} sprite stream {sset['streams'][k]:#x}: {len(old)} B rewritten")
    old, new = caption()
    base = (S.T2 + CAPTION["rec"][0]) * P.DATA
    assert bytes(img.data[base:base + len(old)]) == old, "rec 126 is not pristine"
    img.write(base, new)
    print(f"rec {CAPTION['rec'][0]}: the caption moved to {0x8000 + CAPTION['free']:#06x}")
    print(f"{img.flush()} sectors written")


def render_masks():
    """The bold-font masks for the sprite cards -> opening_sprites.json."""
    import json
    d = {}
    for sset in SPRITE_SETS:
        for c in sset["cards"]:
            m = M.render_label(c["label"])
            d[c["label"]] = ["".join("#" if v else "." for v in row) for row in m]
            print(f"{c['label']}: {m.shape[1]}x{m.shape[0]}")
    json.dump(d, open(SPRITE_MASKS, "w", encoding="utf-8"), indent=1)


def show(path=os.path.join(WORK, "pce", "open_cards.png")):
    from PIL import Image
    blk = S.block(*BLOCK)
    rows = []
    for c in CARDS:
        tiles, bat = card(blk, c["list"])
        img, grid = picture(tiles, bat)
        pic, region = english(c, img, grid, tiles)
        newtiles, newgrid = retile(pic, grid, tiles, bat, region)
        print(f"card {c['list']:#x}: box rows {region[0]}-{region[1]} cols {region[2]}-{region[3]}, "
              f"{len(newtiles)} tiles (original {len(tiles['data']) // 32})")
        rows.append(np.hstack([img, np.full((img.shape[0], 8), 15, np.uint8), pic]))
    # the sprite bands, original and English side by side
    for sset in SPRITE_SETS:
        sblk = S.block(*sset["block"])
        orig, eng = sprite_cells(sblk, sset), sprite_english(sblk, sset)
        for c in sset["cards"]:
            pair = [np.pad(band_of(src, c, sset["height"]), ((0, 0), (0, 0))) for src in (orig, eng)]
            pair = [np.pad(b, ((0, 0), (0, 256 - b.shape[1]))) for b in pair]
            rows.append(np.hstack([pair[0], np.full((sset["height"], 8), 15, np.uint8), pair[1]]))
    sheet = np.vstack(rows) * 17
    Image.fromarray(sheet).save(path)
    print(path)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    {"show": show, "render": render_masks}.get(cmd, apply)()
