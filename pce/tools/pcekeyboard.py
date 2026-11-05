"""Gaudi's name-search keyboard in Latin: the key picture redrawn.

The kana keyboard is a picture: a 129-tile stream at VRAM $2000 in the
computer-room scene block of each act (recs 1266, 2482, 3186, 3506; list
type 0), laid on the message canvas by code as BAT rows 32-39 x cols 1-30.
Each key is one 8-px cell whose glyph straddles two tile rows; four groups
of five keys sit 48 px apart on three key rows. The engine takes the typed
character from the word-list record behind the key (pce_words.KEYS puts
fullwidth Latin there), so only the picture has to change: the letters go
where the kana were, in the picture's own ink (0) on its paper (13), from a
bold 6x8 pixel font (2-px stems).

  python pce/tools/pcekeyboard.py show     # the keyboard picture before and after
  python pce/tools/pcekeyboard.py apply    # every block on the image
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

BLOCKS = [(1266, 32, 0x5bbe), (2482, 37, 0x56be), (3186, 22, 0x6210), (3506, 20, 0x3a78)]   # rec, sectors, the record's data (flags byte)
VRAM = 0x2000
INK, PAPER = 0, 13
# the picture's BAT, as the code lays it (rows 32-39, cols 1-30 of the map): tile ids
LAYOUT = [
    [0x201] + [0x202] * 28 + [0x24f],
    [0x203, 0x204, 0x205, 0x206, 0x207, 0x208, 0x209, 0x20a, 0x205, 0x20b, 0x20c, 0x20d, 0x20e, 0x20f, 0x205,
     0x250, 0x251, 0x252, 0x253, 0x254, 0x205, 0x255, 0x256, 0x257, 0x258, 0x259, 0x205, 0x205, 0x25a, 0x25b],
    [0x203, 0x210, 0x211, 0x212, 0x213, 0x214, 0x215, 0x216, 0x211, 0x217, 0x218, 0x219, 0x21a, 0x21b, 0x211,
     0x25c, 0x25d, 0x25e, 0x25f, 0x27e, 0x211, 0x260, 0x261, 0x262, 0x226, 0x263, 0x211, 0x211, 0x264, 0x25b],
    [0x203, 0x210, 0x211, 0x21c, 0x21d, 0x21e, 0x21f, 0x220, 0x211, 0x221, 0x222, 0x223, 0x224, 0x225, 0x211,
     0x223, 0x265, 0x266, 0x267, 0x268, 0x211, 0x269, 0x26a, 0x26b, 0x26c, 0x26d, 0x211, 0x211, 0x264, 0x25b],
    [0x203, 0x210, 0x211, 0x27f, 0x227, 0x228, 0x229, 0x22a, 0x211, 0x22b, 0x22c, 0x22d, 0x22e, 0x22f, 0x211,
     0x26e, 0x26f, 0x270, 0x271, 0x272, 0x211, 0x273, 0x274, 0x275, 0x276, 0x277, 0x211, 0x211, 0x264, 0x25b],
    [0x203, 0x210, 0x211, 0x230, 0x231, 0x232, 0x233, 0x234, 0x211, 0x211, 0x235, 0x236, 0x237, 0x211, 0x211,
     0x278, 0x279, 0x211, 0x211, 0x211, 0x211, 0x211, 0x211, 0x211, 0x211, 0x211, 0x211, 0x211, 0x264, 0x25b],
    [0x203, 0x238, 0x239, 0x23a, 0x23b, 0x23c, 0x23d, 0x23e, 0x239, 0x23f, 0x240, 0x239, 0x239, 0x239, 0x239,
     0x27a, 0x27b, 0x239, 0x239, 0x239, 0x239, 0x239, 0x239, 0x239, 0x239, 0x239, 0x239, 0x239, 0x27c, 0x25b],
    [0x241] + [0x242] * 28 + [0x27d],
]
# the keys: (glyph top row, x of the first key of each group); a key is an 8-px
# cell. The kana straddled two tile rows (13-19, 29-35, 43-49) and a few of
# their lower halves share a tile (0x219, 0x226), so the letters sit in the
# upper tile row alone (rows 8-15, the kana's top a row lower) and every lower half is
# blank. The font is bold - 6x8 with 2-px stems (M, W 7 wide) - since the 5x7
# one-pixel face was hard to read on a TV (Luiz, 2026-09-15)
ROWS = [12, 28, 44]
CLEAR = [(12, 20), (28, 36), (43, 53)]      # the kana's rows, wiped
ENTER = (120, 43, "OK")                     # 決定, two cells wide; its wide highlight sits a row above the marks' (rows 43-50)
# the marks row: ー ◆ ゛ ゜ at cells 9-12. Latin input has no use for the long vowel
# and the two dakuten, so those three keys go (picture and key table); the
# backspace arrow stays and rises 4 px to the highlight box (rows 40-47 now)
MARKS_CLEAR = [(43, 53, 72, 80), (43, 53, 88, 104)]   # y0, y1, x0, x1 of ー and ゛゜
ARROW = (43, 53, 80, 88, 0)                          # the ◆ cell, rows up (0: it stays)
MARK_KEYS = {7: 0x1B, 9: 0x0B, 10: 0x0A}              # row 2 cells -> the key byte to drop
GROUPS = [24, 72, 120, 168]
# the lower halves of O (row 2 col 19) and U (row 4 col 3) shared a tile with H's
# and S's (0x219, 0x226): the BAT record (BAT below) points them at two spare
# tiles of the stream instead, which start as copies of the tiles they replace
SPARE = {0x27e: 0x219, 0x27f: 0x226}
# the keyboard's BAT record per block: (list offset, record index); 8 rows x 30
# columns at VRAM 0x801, 16-byte column runs (flags 0x60), palette 14 throughout
BAT = {1266: (0x193, 6), 2482: (0x7a, 9), 3186: (0x1b, 6), 3506: (0x1ad, 5)}
# what each group reads, row by row: pce_words.KEYS' rows in the picture's order
KEYS = [["ABCDE", "FGHIJ", "KLMNO", "PQRST"],
        ["UVWXY", "Z    ", "     ", "     "],
        ["     "]]                                # ー ◆ ゛ ゜ stay as drawn, 決定 reads OK
# What a key types is the system file's business (rec 110, resident): a map of
# the box, 30 bytes a row from TABLE, one byte per cell - 01 no key, 06/07 the
# row's ends, 08 決定, 09-0B/1B the marks, else the trail byte of the katakana
# (lead $83). The routine at file 0x5BE7 builds the Shift-JIS of the typed
# string: a value under $40 takes lead $82 and +$1F, so the letters go in as
# $41-$5A and the kana threshold (CMP #$40 at 0x5BF1) rises to $5B: the same
# +$1F lands on Ａ-Ｚ ($8260-$8279).
SYSTEM = (110, 12)
TABLE = [0x5AC1, 0x5AF1, 0x5B21]
THRESHOLD = 0x5BF1
# The cursor: $BD56 puts the highlight object at (col * 8 + base x, row * 8 + base y)
# from a per-mode table at file 0x5B9D (mode 2 the phone pad, mode 3 the keyboard:
# pointer, first cell, cells a row, base x, base y). It stays at Konami's 184: the
# box then covers picture rows 12-19, the kana's, and the letters sit there. Raising
# it to 180 (0.3 dev, 2026-09-15) put the cursor sprite's 16 lines into the band
# where the hospital-list scene parks sixteen 32-wide picture sprites (lines
# 144-159), and the VDC's per-line sprite budget dropped the cursor there: the
# box lit only the lower half of M..S and OK (not A..L, which lie left of them)
CURSOR_Y = (0x5BA8, 0xB8)                        # (offset, the byte it must read)
FONT = {                                          # 6x8 (M, W 7 wide), 2-px stems: '#' = ink
    "A": ".####.|##..##|##..##|######|##..##|##..##|##..##|##..##",
    "B": "#####.|##..##|##..##|#####.|##..##|##..##|##..##|#####.",
    "C": ".####.|##..##|##....|##....|##....|##....|##..##|.####.",
    "D": "#####.|##..##|##..##|##..##|##..##|##..##|##..##|#####.",
    "E": "######|##....|##....|#####.|##....|##....|##....|######",
    "F": "######|##....|##....|#####.|##....|##....|##....|##....",
    "G": ".####.|##..##|##....|##....|##.###|##..##|##..##|.####.",
    "H": "##..##|##..##|##..##|######|##..##|##..##|##..##|##..##",
    "I": "######|..##..|..##..|..##..|..##..|..##..|..##..|######",
    "J": "..####|...##.|...##.|...##.|...##.|...##.|##.##.|.###..",
    "K": "##..##|##.##.|####..|###...|####..|##.##.|##..##|##..##",
    "L": "##....|##....|##....|##....|##....|##....|##....|######",
    "M": "##...##|###.###|#######|##.#.##|##...##|##...##|##...##|##...##",
    "N": "##..##|###.##|###.##|##.###|##.###|##..##|##..##|##..##",
    "O": ".####.|##..##|##..##|##..##|##..##|##..##|##..##|.####.",
    "P": "#####.|##..##|##..##|#####.|##....|##....|##....|##....",
    "Q": ".####.|##..##|##..##|##..##|##..##|##.##.|.####.|....##",
    "R": "#####.|##..##|##..##|#####.|##.##.|##..##|##..##|##..##",
    "S": ".#####|##....|##....|.####.|....##|....##|....##|#####.",
    "T": "######|..##..|..##..|..##..|..##..|..##..|..##..|..##..",
    "U": "##..##|##..##|##..##|##..##|##..##|##..##|##..##|.####.",
    "V": "##..##|##..##|##..##|##..##|.####.|.####.|..##..|..##..",
    "W": "##...##|##...##|##...##|##.#.##|##.#.##|#######|###.###|##...##",
    "X": "##..##|##..##|.####.|..##..|..##..|.####.|##..##|##..##",
    "Y": "##..##|##..##|##..##|.####.|..##..|..##..|..##..|..##..",
    "Z": "######|....##|...##.|..##..|.##...|##....|##....|######",
}


def stream_of(blk, off):
    sp, flags, _ = C.image_stream(blk, off, 0)
    data, end, clean = C.decode(blk, sp)
    assert clean and flags & 0x7F == 0 and len(data) // 32 >= 0x7e
    return sp, end, data


def picture(tiles):
    """The keyboard box as pixels from the tiles and LAYOUT."""
    img = np.zeros((8 * len(LAYOUT), 8 * len(LAYOUT[0])), np.uint8)
    for y, row in enumerate(LAYOUT):
        for x, t in enumerate(row):
            img[y * 8:y * 8 + 8, x * 8:x * 8 + 8] = tiles[SPARE.get(t, t) - 0x200]
    return img


def english(img):
    out = img.copy()
    for r, top in enumerate(ROWS):
        groups = KEYS[r] if r < len(KEYS) else []
        for g, x0 in enumerate(GROUPS):
            if g >= len(groups):
                continue
            for k, ch in enumerate(groups[g]):
                x = x0 + 8 * k
                out[CLEAR[r][0]:CLEAR[r][1], x:x + 8] = PAPER    # the kana
                out[top:top + 8, x:x + 8] = PAPER
                if ch == " ":
                    continue
                glyph(out, ch, x, top)
    for y0, y1, x0, x1 in MARKS_CLEAR:
        out[y0:y1, x0:x1] = PAPER
    y0, y1, x0, x1, up = ARROW
    cell = out[y0:y1, x0:x1].copy()
    out[y0:y1, x0:x1] = PAPER
    out[y0 - up:y1 - up, x0:x1] = cell
    x, top, text = ENTER
    out[top - 1:top + 12, x:x + 16] = PAPER
    for k, ch in enumerate(text):
        glyph(out, ch, x + 1 + 7 * k, top)
    return out


def glyph(out, ch, x, top):
    """The glyph in the 8-px cell at x: 6-wide glyphs one pixel in, 7-wide at the edge."""
    rows = FONT[ch].split("|")
    x += 1 if len(rows[0]) <= 6 else 0
    for dy, line in enumerate(rows):
        for dx, c in enumerate(line):
            if c == "#":
                out[top + dy, x + dx] = INK


def retile(tiles, img):
    """Tiles with the picture's cells written back; a shared tile must get
    one content only."""
    new = tiles.copy()
    want = {}
    for y, row in enumerate(LAYOUT):
        for x, t in enumerate(row):
            cell = img[y * 8:y * 8 + 8, x * 8:x * 8 + 8]
            if t in want and not np.array_equal(want[t], cell):
                sys.exit(f"tile {t:#x} is shared by cells that now differ (row {y}, col {x})")
            want[t] = cell
            new[t - 0x200] = cell
    return new


def system_patch():
    """(old bytes, new bytes) of the system file: the key table and threshold."""
    old = S.block(*SYSTEM)
    new = bytearray(old)
    assert old[THRESHOLD - 1:THRESHOLD + 3] == bytes([0xC9, 0x40, 0xB0, 0x11]), "the kana threshold moved"
    new[THRESHOLD] = 0x5B
    off, was = CURSOR_Y
    assert old[off - 1:off + 1] == bytes([0x18, was]), "the keyboard cursor table moved"
    for r, base in enumerate(TABLE):
        row = bytearray(old[base:base + 30])
        assert row[0] == 0x06 and 0x07 in row, f"row {r} is not a key row"
        groups = KEYS[r] if r < len(KEYS) else []
        pos = 1
        for g, text in enumerate(groups):
            for k, ch in enumerate(text):
                assert row[pos] >= 0x40, f"row {r} group {g} key {k}: not a kana key"
                row[pos] = 0x01 if ch == " " else 0x41 + ord(ch) - ord("A")
                pos += 1
            pos += 1                                  # the gap between groups
        if r == 2:
            for pos, was in MARK_KEYS.items():
                assert row[pos] == was, f"row 2 cell {pos}: {row[pos]:#x}, not {was:#x}"
                row[pos] = 0x01
        new[base:base + 30] = row
    return bytes(old), bytes(new)


def apply(out_path=P.OUT):
    img = P.Image(out_path, P.T3 + P.RESERVE)
    old, new = system_patch()
    base = (S.T2 + SYSTEM[0]) * P.DATA
    assert bytes(img.data[base:base + len(old)]) == old, "the system file is not pristine"
    img.write(base, new)
    print(f"rec {SYSTEM[0]}: key table and threshold patched")
    for rec, n, off in BLOCKS:
        blk = S.block(rec, n)
        sp, end, data = stream_of(blk, off)
        tiles = T.decode(np.frombuffer(data[:len(data) // 32 * 32], np.uint8).reshape(-1, 32))
        pic = english(picture(tiles))
        newtiles = retile(tiles, pic)
        raw = S.encode_tiles(newtiles) + data[len(newtiles) * 32:]
        old = bytes(blk[sp:end])
        new = M.encode(raw, limit=len(old))
        back, _, ok = C.decode(new, 0)
        assert ok and back == raw
        base = (S.T2 + rec) * P.DATA + sp
        assert bytes(img.data[base:base + len(old)]) == old, f"rec {rec}: the stream is not pristine"
        img.write(base, new)
        print(f"rec {rec}: keyboard stream {len(old)} B rewritten")
        bat_patch(img, rec, n)
    print(f"{img.flush()} sectors written")


def bat_record(rec, n):
    """The keyboard's BAT record of a block, as pcecards reads records."""
    import pcecards as K
    blk, lists = K.block_of((rec, n, 5))
    li, ri = BAT[rec]
    r = K.records(blk, lists[li])[ri]
    assert r["type"] == 8 and r["vram"] == 0x801 and r["flags"] & 0x60 == 0x60 and r["rowlen"] == 16
    return blk, r


def bat_words(r):
    """The record's words as rows x cols (column runs of 8), and the palette bits."""
    words = np.frombuffer(r["data"][:len(r["data"]) // r["rowlen"] * r["rowlen"]], dtype="<u2").reshape(-1, 8).T
    return words.copy()


def bat_patch(img, rec, n):
    """The BAT record rewritten with LAYOUT's tile ids (the two spare tiles), the
    palette bits kept; re-encoded to its slot."""
    blk, r = bat_record(rec, n)
    grid = bat_words(r)
    assert grid.shape == (len(LAYOUT), len(LAYOUT[0])), grid.shape
    pal = grid & 0xF000
    old_ids = grid & 0xFFF
    want = np.array(LAYOUT, dtype="<u2")
    changed = int((old_ids != want).sum())
    assert changed == len(SPARE), f"rec {rec}: {changed} BAT cells differ from LAYOUT, expected {len(SPARE)}"
    new_grid = (pal | want).astype("<u2")
    raw = new_grid.T.copy().tobytes() + r["data"][len(new_grid.tobytes()):]
    assert len(raw) == len(r["data"])
    old = bytes(blk[r["stream"]:r["end"]])
    new = M.encode(raw, limit=len(old))
    back, _, ok = C.decode(new, 0)
    assert ok and back == raw
    base = (S.T2 + rec) * P.DATA + r["stream"]
    assert bytes(img.data[base:base + len(old)]) == old, f"rec {rec}: the BAT stream is not pristine"
    img.write(base, new)
    print(f"rec {rec}: keyboard BAT {len(old)} B rewritten ({changed} cells repointed)")


def show(path=os.path.join(WORK, "pce", "keyboard.png")):
    from PIL import Image
    rec, n, off = BLOCKS[0]
    blk = S.block(rec, n)
    sp, end, data = stream_of(blk, off)
    tiles = T.decode(np.frombuffer(data[:len(data) // 32 * 32], np.uint8).reshape(-1, 32))
    before = picture(tiles)
    after = english(before)
    retile(tiles, after)
    sheet = np.vstack([before, np.full((4, before.shape[1]), 15, np.uint8), after]) * 17
    Image.fromarray(sheet).resize((sheet.shape[1] * 3, sheet.shape[0] * 3), Image.NEAREST).save(path)
    print(path)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    show() if cmd == "show" else apply()
