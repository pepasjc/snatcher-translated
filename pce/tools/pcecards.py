"""Text cards drawn as tile pictures, redrawn in English: Gibson's memo, the
ending's epilogue and the videophone's "not in service" card.

Gibson's thirteen memo pages (PS1: CPC_B000..B0C0, `gfx_pages.json`) are
display lists in block 37 (rec 2802, lists 0xa872..0xab60) - a tile stream
to VRAM $2000 or $4000, a second one for the two pages with a photo inset,
and a BAT stream of 32-byte column runs (16 rows x 24 columns = 192x128
px) at BAT (4, 0/16/32/48); block 14 (rec 1586) carries pages 7 and 8 again
for the scene that shows them. The epilogue over the sunset ("疑い、それは
いつも闘争を生んできた。") is one more such picture in block 102 (rec 7218,
list 0x5fc, a full 32x32 BAT). All are Konami's font rendered to tiles, so
the English is set the way opencards.py sets the opening's cards
(opencards.render_line: X11 "fixed" 6x13, the dialogue's face), one line per original line
top, ink on paper, only in cells that held nothing but ink and paper (the
photo insets keep their tiles), and both streams are re-encoded in place.
The PS1 page texts are reused as they are (`ps1/translation/gfx_pages.json`,
already broken to clear the insets); the epilogue's lines are here. The
videophone's card (現在、使われておりません over the mascot) is list 0x651 of
the videophone block (rec 3506, the only block with the phone's screens):
the card's tiles at VRAM $2000 and a 24-byte-column BAT at $C5 - white (3)
on the box's blue (4); the list's other streams (the phone) stay. The "no
video signal" card a shop's answer shows (映像信号が送信されておりません, the
Joy Division and Konami numbers) is the same layout in block 49 (rec 3570,
list 0x5f4; found by searching every block's $2000 tile streams for the
tiles a savestate's BAT pointed at).

  python pce/tools/pcecards.py show      # every card before/after as PNG
  python pce/tools/pcecards.py apply     # into patched/pce/snatcher_pce.bin
"""
import json, os, sys
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
import opencards as O

PAGES = os.path.join(ROOT, "ps1", "translation", "gfx_pages.json")
MEMO = (2802, 22, 5)                   # block 37: rec, sectors, first bank
MEMO_LISTS = [0xA872, 0xA888, 0xA8CE, 0xA914, 0xA954, 0xA99A, 0xA9DA,
              0xAA1A, 0xAA60, 0xAAA0, 0xAAE0, 0xAB20, 0xAB60]
MEMO_KEYS = [f"CPC_B0{k:X}0" for k in range(13)]
AGAIN = (1586, 45, 5)                  # block 14 shows pages 7 and 8 too
AGAIN_LISTS = {0x11EA2: "CPC_B060", 0x11EB2: "CPC_B070"}
ENDING = (7218, 81, 4)                 # block 102
EPILOGUE = {"list": 0x5FC, "text": ["Doubt. It has always", "bred conflict.",
                                     "The true struggle may lie", "in the human heart.",
                                     "Now, the struggle has", "only just begun."]}
FG, BG = 1, 0
INK = {1, 2}                           # 2 = the paragraph marks
PHONE = {"block": (3506, 20, 5), "list": 0x651, "name": "not in service",
         "text": ["This number is", "not in service."], "tops": [10, 25], "fg": 3, "bg": 4, "ink": {2, 3},
         "wipe_mixed": True, "tiles_vram": 0x2000, "bat_vram": 0xC5}   # (the kana ran into the box's border cells)
SIGNAL = {"block": (3570, 22, 5), "list": 0x5F4, "name": "no video signal",       # a shop answers with no picture
          "text": ["No video", "signal is", "being sent."], "fg": 3, "bg": 4, "ink": {2, 3},
          "wipe_mixed": True, "tiles_vram": 0x2000, "bat_vram": 0xC5}           # (映像信号が送信されておりません: block 49)


def cards():
    pages = json.load(open(PAGES, encoding="utf-8"))
    out = [dict(block=MEMO, list=off, text=pages[key], name=key)
           for off, key in zip(MEMO_LISTS, MEMO_KEYS)]
    out += [dict(block=AGAIN, list=off, text=pages[key], name=key + " (again)")
            for off, key in AGAIN_LISTS.items()]
    out.append(dict(block=ENDING, list=EPILOGUE["list"], text=EPILOGUE["text"], name="epilogue"))
    out.append(dict(PHONE))
    out.append(dict(SIGNAL))
    return out


_blocks = {}


def block_of(spec):
    rec, n, bank = spec
    if rec not in _blocks:
        blk = S.block(rec, n)
        nb = (len(blk) + C.BANK - 1) // C.BANK
        _blocks[rec] = (blk, dict(C.find_lists(blk, bank, nb)))
    return _blocks[rec]


def records(blk, recs):
    out = []
    for b, t, va, ptr, o in recs:
        sp, flags, rowlen = C.image_stream(blk, o, t)
        data, end, clean = C.decode(blk, sp)
        assert clean
        out.append({"bank": b, "type": t, "vram": va, "off": o, "stream": sp, "end": end,
                    "flags": flags, "rowlen": rowlen, "data": data})
    return out


def card(c):
    """(tile records in VRAM order, bat record, grid, picture, tiles by id).
    A page's tiles run past one 8 KB bank into a second stream at the next
    VRAM base; the two are one tile array here."""
    blk, lists = block_of(c["block"])
    recs = records(blk, lists[c["list"]])
    tiles = sorted([r for r in recs if r["type"] == 0 and r["vram"] == c.get("tiles_vram", r["vram"])], key=lambda r: r["vram"])
    bat = [r for r in recs if r["type"] == 8 and r["vram"] == c.get("bat_vram", r["vram"])][0]
    assert bat["flags"] & 0x60 == 0x60
    grid = O.grid_of(bat)
    tl = {}
    nxt = tiles[0]["vram"] // 16
    for r in tiles:
        base = r["vram"] // 16
        assert base == nxt, f"{c['name']}: tile streams are not contiguous"
        r["n"] = len(r["data"]) // 32
        for i, t in enumerate(T.decode(np.frombuffer(r["data"][:r["n"] * 32], np.uint8).reshape(-1, 32))):
            tl[base + i] = t
        nxt = base + r["n"]
    h, w = grid.shape
    img = np.zeros((h * 8, w * 8), np.uint8)
    for y in range(h):
        for x in range(w):
            t = tl.get(int(grid[y, x]) & 0xFFF)
            if t is not None:
                img[y * 8:y * 8 + 8, x * 8:x * 8 + 8] = t
    return tiles, bat, grid, img, tl


def span(tiles):
    """(first tile id, tile count) of a card's tile array."""
    return tiles[0]["vram"] // 16, sum(r["n"] for r in tiles)


def english(c, tiles, grid, img, tl):
    """The picture with the English in place of the Japanese, and the mask
    of cells that may change (ink-on-paper cells of the tile array)."""
    base, n = span(tiles)
    fg, bg, inks = c.get("fg", FG), c.get("bg", BG), c.get("ink", INK)
    h, w = grid.shape
    textcell = np.zeros((h, w), bool)
    mixed = np.zeros((h, w), bool)         # ink over something else (a border): wiped, not written
    for y in range(h):
        for x in range(w):
            k = (int(grid[y, x]) & 0xFFF)
            if base <= k < base + n:
                vals = set(np.unique(tl[k]).tolist())
                textcell[y, x] = vals <= inks | {bg}
                mixed[y, x] = bool(vals & inks) and not textcell[y, x] and c.get("wipe_mixed", False)
    ink = np.zeros((h, w), bool)
    for y in range(h):
        for x in range(w):
            ink[y, x] = textcell[y, x] and (img[y * 8:y * 8 + 8, x * 8:x * 8 + 8] == fg).any()
    ys, xs = np.nonzero(ink)
    y0, y1, x0, x1 = ys.min() * 8, ys.max() * 8 + 8, xs.min() * 8, xs.max() * 8 + 8
    lines = O.text_rows(img[y0:y1, x0:x1], fg)
    pitch = (lines[1][0] - lines[0][0]) if len(lines) > 1 else 16
    tops = c.get("tops") or [y0 + t for t, _ in lines]         # "tops": set by hand (the phone card's box is 4 rows)
    while len(tops) < len(c["text"]):
        tops.append(tops[-1] + pitch)
    cols = np.nonzero((img[y0:y1, x0:x1] == fg).any(axis=0))[0]
    left = x0 + int(cols.min())
    out = img.copy()
    cellmask = np.repeat(np.repeat(textcell, 8, axis=0), 8, axis=1)
    out[cellmask & np.isin(out, list(inks))] = bg
    mixmask = np.repeat(np.repeat(mixed, 8, axis=0), 8, axis=1)
    out[mixmask & np.isin(out, list(inks))] = bg
    for text, top in zip(c["text"], tops):
        if not text.strip():
            continue
        g = O.render_line(text)
        x = left
        if top + O.GLYPH_H > h * 8 or x + g.shape[1] > w * 8:
            sys.exit(f"{c['name']}: {text!r} runs off the page")
        win = out[top:top + O.GLYPH_H, x:x + g.shape[1]]
        touched = cellmask[top:top + O.GLYPH_H, x:x + g.shape[1]]
        if ((g > 0) & ~touched).any():
            sys.exit(f"{c['name']}: {text!r} runs into a cell that is not text")
        win[g > 0] = fg
    return out, textcell | mixed


def retile(c, out, textcell, tiles, grid, tl):
    """New tiles for the tile array and the new grid: the tiles the picture
    still uses keep their order, new cells' tiles follow."""
    base, n = span(tiles)
    h, w = grid.shape
    used = sorted({int(grid[y, x]) & 0xFFF for y in range(h) for x in range(w)
                   if not textcell[y, x] and base <= (int(grid[y, x]) & 0xFFF) < base + n})
    newtiles = [tl[k] for k in used]
    ids = {k: i for i, k in enumerate(used)}
    seen = {tl[k].tobytes(): i for i, k in enumerate(used)}
    newgrid = grid.copy()
    for y in range(h):
        for x in range(w):
            word = int(grid[y, x])
            k = word & 0xFFF
            if textcell[y, x]:
                t = out[y * 8:y * 8 + 8, x * 8:x * 8 + 8]
                key = t.tobytes()
                if key not in seen:
                    seen[key] = len(newtiles)
                    newtiles.append(t.copy())
                newgrid[y, x] = (word & 0xF000) | (base + seen[key])
            elif k in ids:
                newgrid[y, x] = (word & 0xF000) | (base + ids[k])
    return np.array(newtiles, np.uint8), newgrid


def build():
    """[(card, [(record, old bytes, new bytes)...], tile count, english picture, original)]."""
    out = []
    for c in cards():
        blk, _ = block_of(c["block"])
        tiles, bat, grid, img, tl = card(c)
        pic, textcell = english(c, tiles, grid, img, tl)
        newtiles, newgrid = retile(c, pic, textcell, tiles, grid, tl)
        base, room = span(tiles)
        if len(newtiles) > room:
            sys.exit(f"{c['name']}: {len(newtiles)} tiles, the original has {room}")
        # the tile array back into its streams, each decoding to its old length
        blank = np.zeros((8, 8), np.uint8)
        padded = list(newtiles) + [blank] * (room - len(newtiles))
        patches, at = [], 0
        for r in tiles:
            part = S.encode_tiles(np.array(padded[at:at + r["n"]], np.uint8))
            at += r["n"]
            old = bytes(blk[r["stream"]:r["end"]])
            patches.append((r, old, M.encode(part, limit=len(old))))
        words = newgrid.T.astype("<u2").tobytes()
        old_b = bytes(blk[bat["stream"]:bat["end"]])
        patches.append((bat, old_b, M.encode(words + bat["data"][len(words):], limit=len(old_b))))
        # the streams read back: the picture they describe is the English one
        tl2 = {}
        for r, old, new in patches:
            back, _, ok = C.decode(new, 0)
            assert ok and len(new) == len(old) and len(back) >= len(r["data"]) // 32 * 32
            if r["type"] == 0:
                for i, t in enumerate(T.decode(np.frombuffer(back[:r["n"] * 32], np.uint8).reshape(-1, 32))):
                    tl2[r["vram"] // 16 + i] = t
        h, w = newgrid.shape
        check = np.zeros_like(pic)
        for y in range(h):
            for x in range(w):
                t = tl2.get(int(newgrid[y, x]) & 0xFFF, tl.get(int(newgrid[y, x]) & 0xFFF))
                if t is not None:
                    check[y * 8:y * 8 + 8, x * 8:x * 8 + 8] = t
        assert (check == pic).all(), f"{c['name']}: the rebuilt picture differs"
        out.append((c, patches, len(newtiles), pic, img))
    return out


def apply(out_path=P.OUT):
    img = P.Image(out_path, P.T3 + P.RESERVE)
    n = 0
    for c, patches, ntiles, _, _ in build():
        base = (S.T2 + c["block"][0]) * P.DATA
        for rec, old, new in patches:
            at = base + rec["stream"]
            assert bytes(img.data[at:at + len(old)]) == old, f"{c['name']}: stream {rec['stream']:#x} is not pristine"
            img.write(at, new)
        n += 1
        print(f"{c['name']}: {ntiles} tiles, {len(patches)} streams rewritten")
    print(f"{n} cards; {img.flush()} sectors written")


def show(path=os.path.join(WORK, "pce", "cards.png")):
    from PIL import Image
    rows = []
    for c, _, _, pic, img in build():
        w = max(pic.shape[1], img.shape[1])
        pair = np.hstack([np.pad(img, ((0, 0), (0, w - img.shape[1]))), np.full((img.shape[0], 4), 15, np.uint8),
                          np.pad(pic, ((0, 0), (0, w - pic.shape[1])))])
        rows.append(pair)
        rows.append(np.full((4, pair.shape[1]), 15, np.uint8))
    w = max(r.shape[1] for r in rows)
    sheet = np.vstack([np.pad(r, ((0, 0), (0, w - r.shape[1]))) for r in rows]) * 17
    Image.fromarray(sheet.astype(np.uint8)).save(path)
    print(path)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    show() if cmd == "show" else apply()
