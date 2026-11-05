# -*- coding: utf-8 -*-
"""The Saturn's typing keyboard in Latin, the B040 name-search keys in English,
and the typed-puzzle targets checked - the PS1's patch_keyboard.py,
kbdfaces.py, keytable.py and the PUZZLE_TARGETS half of lock_data_strings.py
for MAIN_L.BIN / DATA.BIN.

THE KEYBOARD (found 2026-09-12 from the SH-2; every address is MAIN_L.BIN at
0x060B0000):

  * One routine drives every typing screen: 0x060B9A74(list, keydata, maxlen,
    mode). mode 2 is the 15 x 4 katakana keyboard (the name search and the
    typed puzzles); modes 0/1/3 are the videophone's numeric pad, untouched.
    The pad handler 0x060B97F0 moves a cursor {u16 col, u16 row} at
    0x060F2C00 over the cell map KEYDATA 0x060E5254 = {cols 15, rows 4} + 60
    bytes of key index per cell (row-major; the wide OK button is key 56 on
    row 3, cols 11-14) and returns the key index under it.
  * LAYOUT 0x060E5294: 60 x {u8 code, u8 kind}. A key's code is what the
    typed buffer 0x060EF6B4 (14 bytes, null-terminated) receives; its glyph
    is looked up as SJIS-table[0x8340 + code] through the pool word
    0x060B9DE8 (= TABLE + 2*(0x8340-0x8140): the katakana row), or
    SJIS-table[0x8140 + code - 0x80] when bit 7 is set (the symbols row:
    space 0x80, / 0x9E, . 0x84, ! 0x89, ? 0x88, - 0x9B). Codes 86-89 are
    the dakuten, handakuten, cursor-left and cursor-right keys (handled
    before the lookup; the marks act only on a previous key whose `kind`
    is 1 or 3), code 0 is the OK key that ends the entry. `maxlen` bounds
    the typed length: 10 on the name search (0x060BA4AE), 4 on the puzzle
    keyboard (0x060BA34C - four kana; the English answers run to eight).
  * The matcher never sees text: 0x060B9748 converts every live list-menu
    label (the label table 0x060FAC60, 64 bytes each, count [0x060FD0C0])
    to one byte per character = (SJIS low byte - 0x40) into
    0x060EF554 + 14*i, and the typed buffer is compared with those by
    strcmp (the puzzle wrapper 0x060BA2C8 and the search's second phase
    0x060BA538, lowest matching item wins, -1 = none) or by strchr of the
    first typed code in each label (the search's first phase 0x060BA4A4:
    the section whose initials contain the typed first character). So a
    key string must be one glyph code per typed character, and a Latin
    key `A` needs a code whose glyph is Ａ: with the table view moved from
    0x8340 to 0x8240 (one pool word), code = SJIS low byte - 0x40 gives
    Ａ..Ｚ = 0x20..0x39 and ０..９ = 0x0F..0x18, exactly what a fullwidth
    key string converts to. Pair-encoded ASCII can never match (the PS1's
    lesson), so keys and puzzle answers are FULLWIDTH in the JSON.
  * The key faces are a bitmap (the four VDP1 sprites of the list at
    0x060E57C8: 128x80 at (4,152), 56x48 and 56x32 at x=260, 128x80 at
    (132,152), 8bpp at VDP1 VRAM 0x43C00), the PS1's CPS_B0A0 - see
    `faces` below.

THE NAME SEARCH (B040 = DATA.BIN entry 25). The search is a list menu of 17
section items (bytecode 0x30..0x67E, one per kana row: ア, イウエオ, カキクケ,
コ, ガ.., サ.., ザ.., タ, チツテト, ダ.., ナ.., ハ.., バ.., パ.. (empty),
マ.., ラ.., ヤユヨワン) plus `Stop search`; an item is {expression ending in
the label's string word, flags, len, body}, a section's body is again items:
first the `NO SUCH PERSON` fallback, then its keys (flags 0x09, a 3-byte
`e0 xx xx` action or the 6-byte correction line; some carry a condition
prefix). The first typed character picks the section by strchr over the
section labels (first hit wins), the whole entry then strcmp's against
that section's keys. The English initials do not follow the kana rows
(KOJIMA sits in コ, KIYOHARA in カ; CHIN in チ, CHIEF in カ), so the pick
is replaced: the strchr pool word 0x060BA528 goes to KEYSEL in the exec
hole, which on the first candidate compares the typed buffer with every
key of a directory {u16 nsec; per section u16 n, n x u16 region offset}
and answers "this section" for the one holding the match - every key is
reachable whatever its row. With no match it falls back to strchr on the
initials (the sections' new labels: each letter claimed by the section
with most keys starting with it, the rest to the empty パ section), so an
unknown name reaches a `NO SUCH PERSON` reply as before.

DATA: the keys ride the ordinary machinery - `fit` writes every key record
of saturn/translation/SAT_025_B040.json with `key: true` and its English
(the PS1 keytable.ENGLISH through `src`, the Saturn-only ones' own `en`) as
FULLWIDTH text: in `en` where it fits the slot, else in `long` (satlong.py
appends it and the menu-item stub remaps the label). Section headers get
`initials: true` and their letters the same way. `apply` (after satlong.py,
before satdisc.py) patches the exec and reads the final offsets back from
the built bank (satlong's group) for the directory. Puzzle targets (B060,
B070, B1A0, B1D0) are already fullwidth `en`/`long` from the carry; `check`
holds them to lock_data_strings.PUZZLE_TARGETS.

    python saturn/tools/satkeys.py parse           the section table of the pristine bank
    python saturn/tools/satkeys.py fit             write the key records (JSON; one-off)
    python saturn/tools/satkeys.py apply [--dry]   patch patched/saturn/MAIN_L.BIN (after satlong)
    python saturn/tools/satkeys.py check           verify JSON + built files
    python saturn/tools/satkeys.py faces           the Latin key faces -> patched/saturn/chunks/310.bin (satpack's override)
"""
import glob, json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import satdata, satexec, sh2asm

MAIN_BASE = 0x060B0000
TR = os.path.join(ROOT, "saturn", "translation")
OUT = os.path.join(ROOT, "patched", "saturn")
OUT_DATA = os.path.join(OUT, "DATA.BIN")
OUT_MAIN = os.path.join(OUT, "MAIN_L.BIN")
BUILD = os.path.join(WORK, "saturn", "build")
B040 = 25
B040_JSON = os.path.join(TR, "SAT_025_B040.json")
B040_CARRY = os.path.join(WORK, "saturn", "carry", "SAT_025_B040.json")
PS1_REF = os.path.join(WORK, "ref", "ISZ_B040.json")
SECTOR = 2048

# --- the exec ---------------------------------------------------------------
KEYDATA = 0x060E5254          # {cols, rows} + 60 cell -> key index
LAYOUT = 0x060E5294           # 60 x {code, kind}
NKEYS = 60
GLYPH_VIEW_POOL = 0x060B9DE8  # u32: table view the typed cells draw from
GLYPH_VIEW_KANA = 0x060E70F0  # = TABLE + 2*(0x8340 - 0x8140)
GLYPH_VIEW_LATIN = 0x060E6EF0 # = TABLE + 2*(0x8240 - 0x8140): code n -> SJIS 0x8240+n
PUZZLE_MAXLEN = 0x060BA34C    # mov #4,r6  (0xE604)
PUZZLE_MAXLEN_NEW = 10
PUZZLE_COUNT = 0x060BA338     # mov #8,r0  (0xE008): the sprite list's count = 4 panel pieces + 4 cells
SEARCH_MAXLEN = 0x060BA4AE    # mov #10,r6 (0xE60A)
SEARCH_BUILD_N = 0x060BA45A   # mov #10,r5 (0xE50A): the wrapper rebuilds cells 0..10
SEARCH_COUNT = 0x060BA49A     # mov #15,r0 (0xE00F): 4 pieces + 11 cells (10 letters + the cursor)
MAXLEN = 13                   # the search field: the typed buffer holds 13 + null
# The field's x: each wrapper builds its cell records at x = base + 16*i
# (`mov #base,r3`), 64 on the search (11 cells: 64..240) and 112 on the
# puzzle (5 cells: 112..192). Blank cells are opaque black 16x14 sprites,
# and with 14 / 11 cells the last ones reached x 288 - past the terminal
# screen's black area, a black square on the blue bezel (Luiz, 2026-09-16).
# The longer fields keep the original centre: search 40..264, puzzle 64..240.
SEARCH_X = 0x060BA460         # mov #64,r3  (0xE340)
SEARCH_X_NEW = 40
PUZZLE_X = 0x060BA2FE         # mov #112,r3 (0xE370)
PUZZLE_X_NEW = 64
# The typed cells are records 4..14 of the keyboard panel's sprite list at
# 0x060E57C8 ({u16 count, 6 pad} + 12-byte records {ctrl, size, clut, srca,
# x, y}: 4 panel pieces, then 11 cells at 0x060E5800, x = 64 + 16*i on the
# search, 112 + 16*i on the puzzle), and the next list follows at once. For
# 13 letters the list is copied to the exec hole with 15 cell records and
# the three words that name it repointed.
LIST_PTR = 0x060E5344         # u32 -> the list (read by both wrappers)
LIST_ORIG = 0x060E57C8
CELLS_POOL = (0x060BA3E8, 0x060BA50C)   # u32 0x060E5800: the cell records (builder + the keyboard's arg)
CELLS_ORIG = 0x060E5800
NPIECES, NCELLS_ORIG, NCELLS = 4, 11, MAXLEN + 1
KEYSEL_POOL = 0x060BA528      # u32 = STRCHR, the section pick's compare
STRCHR = 0x060DBEC8
CAND_BASE = 0x060EF554
CAND_STRIDE = 14
TYPED = 0x060EF6B4
STRING_BASE_VAR = 0x060FD164
CURSOR = 0x060F2C00
OK_KEY = 56

# --- the layout, the PS1's patch_keyboard.ROWS read the same way -------------
# Screen cell (row r, col c) is layout group g = (c // 5) * 4 + r, cell c % 5.
# None keeps the Saturn key (/ . ! ? - the two marks, the arrows, the space
# and OK); ' ' is a typed space.
ROWS = [
    ["A", "B", "C", "D", "E"],          # row 0 cols 0-4   (アイウエオ)
    ["P", "Q", "R", "S", "T"],          # row 1 cols 0-4   (カキクケコ)
    ["0", "1", "2", "3", "4"],          # row 2 cols 0-4   (サシスセソ)
    [" ", " ", " ", " ", " "],          # row 3 cols 0-4   (タチツテト)
    ["F", "G", "H", "I", "J"],          # row 0 cols 5-9   (ナニヌネノ)
    ["U", "V", "W", "X", "Y"],          # row 1 cols 5-9   (ハヒフヘホ)
    ["5", "6", "7", "8", "9"],          # row 2 cols 5-9   (マミムメモ)
    [" ", None, " ", None, " "],        # row 3 cols 5-9   (ヤ ／ ユ ． ヨ)
    ["K", "L", "M", "N", "O"],          # row 0 cols 10-14 (ラリルレロ)
    ["Z", " ", " ", None, None],        # row 1 cols 10-14 (ワ ヲ ン ！ ？)
    [None, None, None, None, None],     # row 2 cols 10-14 (ー ゛ ゜ ← →)
    [None, None, None, None, None],     # row 3 cols 10-14 (␣ and the OK button)
]
GRID_ROWS, GRID_COLS = 4, 15
SPACE_CODE = 0x80


def code_of(ch):
    """The layout code a Latin key emits = (SJIS low byte of the fullwidth glyph) - 0x40."""
    if ch == " ":
        return SPACE_CODE
    if "A" <= ch <= "Z":
        return 0x20 + ord(ch) - 65
    if "0" <= ch <= "9":
        return 0x0F + int(ch)
    raise ValueError(ch)


def fullwidth(t):
    return "".join(chr(0xFF00 + ord(c) - 0x20) if 33 <= ord(c) <= 126 else c for c in t)


def halfwidth(t):
    return "".join(chr(ord(c) - 0xFF00 + 0x20) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in t)


def cell_map(exe):
    """{(row, col): key index} from KEYDATA."""
    o = KEYDATA - MAIN_BASE
    cols, rows = exe[o], exe[o + 1]
    assert (cols, rows) == (GRID_COLS, GRID_ROWS), (cols, rows)
    return {(r, c): exe[o + 2 + r * cols + c] for r in range(rows) for c in range(cols)}


def latin_cells():
    """{(row, col): char} the Latin layout puts on the grid (None = kept)."""
    out = {}
    for g, cells in enumerate(ROWS):
        r, c0 = g % 4, (g // 4) * 5
        for i, ch in enumerate(cells):
            out[(r, c0 + i)] = ch
    return out


def grid_cells(layout="latin"):
    """char -> (row, col) for the harness: Latin letters/digits and 'OK'."""
    out = {"OK": (3, 12)}
    if layout == "latin":
        for rc, ch in latin_cells().items():
            if ch and ch != " ":
                out[ch] = rc
        out[" "] = (3, 0)
    else:
        exe = open(satdata.MAIN, "rb").read()
        cm = cell_map(exe)
        for rc, k in cm.items():
            code = exe[LAYOUT - MAIN_BASE + 2 * k]
            if 0 < code < 0x56:
                out[(0x8340 + code).to_bytes(2, "big").decode("cp932")] = rc
    return out


# --- the bank ------------------------------------------------------------------
TABLE_START = 0x30


def word_offset(d, w0, pos):
    """The reader 0x060C08B0: word at bytecode `pos` -> region offset."""
    w = struct.unpack_from(">H", d, pos)[0]
    off = 2 * w
    if d[4 + w0 + off - 1] != 0:
        off -= 1
    return off


def parse_items(d, w0, start, end, region_offs, depth=0):
    """Items {expr, word_pos, off, flags, len, body_start, body_end} of a menu
    body d[start:end]: an item is <expression ending in a string word> <flags>
    <len> <len bytes>. The expression length is found by backtracking: the
    smallest prefix after which a known string word, a flags byte 0x08/0x09
    and a length that leaves a parseable remainder follow."""
    items = []
    pos = start
    while pos < end:
        found = None
        for k in range(2, 40, 1):
            wp = pos + k - 2
            if wp + 4 > end:
                break
            flags, ln = d[wp + 2], d[wp + 3]
            if flags not in (0x08, 0x09, 0x28):
                continue
            w = struct.unpack_from(">H", d, wp)[0]
            if w & 0x8000:
                continue
            off = word_offset(d, w0, wp)
            if off not in region_offs:
                continue
            if wp + 4 + ln > end:
                continue
            # the remainder must parse too (cheap: only check the next item's shape)
            found = (k, wp, off, flags, ln)
            break
        if found is None:
            raise ValueError(f"no item at {pos:#x} (depth {depth}): {d[pos:pos + 16].hex(' ')}")
        k, wp, off, flags, ln = found
        items.append({"pos": pos, "word_pos": wp, "off": off, "flags": flags, "len": ln,
                      "body": (wp + 4, wp + 4 + ln), "expr": bytes(d[pos:wp])})
        pos = wp + 4 + ln
    assert pos == end, (hex(pos), hex(end))
    return items


def parse_table(bank, strings):
    """The name-search menu: sections (items with flags 0x08) and their key
    items. `strings` = the JSON records (off, budget) of the bank."""
    w0 = struct.unpack_from(">H", bank, 0)[0]
    offs = {r["off"] - w0 - 4: i for i, r in enumerate(strings)}
    # the menu block: sections from TABLE_START until an item that is not a section
    sections = []
    pos = TABLE_START
    while True:
        w = struct.unpack_from(">H", bank, pos)[0]
        flags, ln = bank[pos + 2], bank[pos + 3]
        if flags != 0x08 or (w & 0x8000):
            break
        off = word_offset(bank, w0, pos)
        assert off in offs, hex(pos)
        body = (pos + 4, pos + 4 + ln)
        keys = parse_items(bank, w0, body[0], body[1], offs, 1)
        sections.append({"pos": pos, "word_pos": pos, "off": off, "idx": offs[off], "len": ln,
                         "body": body, "items": keys})
        pos = body[1]
    end = pos
    # every key: its item; the first item of a body is the fallback
    for s in sections:
        for it in s["items"]:
            it["idx"] = offs[it["off"]]
        s["fallback"] = s["items"][0]
        s["keys"] = s["items"][1:]
    return sections, end


def key_english(rec, carry_rec, ps1_by_off, ps1_english):
    """The English of a key record: the PS1 keytable's through `src`, else the
    record's own ASCII `en`/`long` (the Saturn-only keys), else None."""
    src = rec.get("src", "")
    if src.startswith("B040:"):
        pi = ps1_by_off.get(int(src[5:]))
        if pi is not None and pi in ps1_english:
            return ps1_english[pi]
    for f in ("long", "en"):
        t = rec.get(f) or ""
        if t and all(("A" <= c <= "Z") or ("0" <= c <= "9") for c in halfwidth(t)):
            return halfwidth(t)
    return None


# Saturn-only keys whose section does not own their English initial in the
# strchr fallback get a name their section can route (KEYSEL finds every key
# regardless; this keeps the "no such person" path sane and reads well):
RENAME = {
    "ITSACT1": "ACT1",            # 『ＡＣＴ１だから』 in the ア section
    "NOTMYBUG": "ITSNOTMYBUG",    # 『俺のバグじゃない』 in イウエオ
    "NICEPICTURE": "COOLPICTURE", # 『かわりにおいしい絵を』 in カキクケ
    "GOINGHOME": "CALLITADAY",    # 『今日は帰って・・・』 in カキクケ
    "BYDESIGN": "SPEC",           # 『それは仕様です』 in サシスセソ
}
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
EMPTY_SECTION = 13                # パピプペポ: no keys; takes the unclaimed letters
ONE_LETTER = {"マ": "M"}          # the lone 'マ' key of the マ section


def load_b040():
    spec = json.load(open(B040_JSON, encoding="utf-8"))
    carry = json.load(open(B040_CARRY, encoding="utf-8"))["strings"]
    assert len(carry) == len(spec["strings"])
    ref = json.load(open(PS1_REF, encoding="utf-8"))["strings"]
    ps1_by_off = {e["off"]: i for i, e in enumerate(ref)}
    from keytable import ENGLISH
    return spec, carry, ps1_by_off, ENGLISH


def pristine_bank():
    data = open(satdata.DATA, "rb").read()
    return satdata.entry(data, satdata.read_table(), B040)


def plan_keys():
    """(sections, {idx: english}, {section i: initials}) for the B040 table."""
    spec, carry, ps1_by_off, english = load_b040()
    strings = spec["strings"]
    bank = pristine_bank()
    sections, end = parse_table(bank, strings)
    names = {}
    for s in sections:
        for k in s["keys"]:
            r, c = strings[k["idx"]], carry[k["idx"]]
            en = key_english(r, c, ps1_by_off, english)
            if en is None:
                en = ONE_LETTER.get(c["jp"])
            assert en, (k["idx"], c["jp"])
            names[k["idx"]] = RENAME.get(en, en)
    # initials: each letter to the section with most keys starting with it
    import collections
    votes = collections.defaultdict(collections.Counter)
    for i, s in enumerate(sections):
        for k in s["keys"]:
            votes[names[k["idx"]][0]][i] += 1
    claimed = {}
    for ch in ALPHABET:
        if ch in votes:
            claimed[ch] = max(votes[ch].items(), key=lambda t: (t[1], -t[0]))[0]
        else:
            claimed[ch] = EMPTY_SECTION
    initials = {i: "".join(ch for ch in ALPHABET if claimed[ch] == i) for i in range(len(sections))}
    unreachable = [(names[k["idx"]], i) for i, s in enumerate(sections) for k in s["keys"]
                   if claimed[names[k["idx"]][0]] != i]
    return sections, names, initials, unreachable, spec, carry


def cmd_parse():
    sections, names, initials, unreachable, spec, carry = plan_keys()
    print(f"{len(sections)} sections, {sum(len(s['keys']) for s in sections)} keys, "
          f"table {TABLE_START:#x}..{sections[-1]['body'][1]:#x}")
    for i, s in enumerate(sections):
        print(f"  {i:2d} {s['pos']:#05x} {carry[s['idx']]['jp']:6s} len {s['len']:3d} keys {len(s['keys']):2d} "
              f"initials {initials[i]!r}")
        for k in s["keys"]:
            r = spec["strings"][k["idx"]]
            print(f"       {k['idx']:3d} {carry[k['idx']]['jp']:12s} b{r['budget']:2d} -> {names[k['idx']]}"
                  + (f"  [expr {k['expr'].hex(' ')}]" if k["expr"] else ""))
    print(f"strchr-fallback unreachable (KEYSEL finds them): {unreachable}")
    long_ = [n for n in names.values() if len(n) > MAXLEN]
    print(f"{len(long_)} keys longer than the {MAXLEN}-character field (single names find the same dossiers): {long_}")


def cmd_fit(write=True):
    """Write the key and header records into the JSON."""
    sections, names, initials, unreachable, spec, carry = plan_keys()
    strings = spec["strings"]
    n_en = n_long = 0
    for i, s in enumerate(sections):
        for k in s["keys"]:
            r = strings[k["idx"]]
            fw = fullwidth(names[k["idx"]])
            r["key"] = True
            r.pop("initials", None)
            if 2 * len(fw) + 1 <= r["budget"]:
                r["en"] = fw; r.pop("long", None); n_en += 1
            else:
                r["en"] = ""; r["long"] = fw; n_long += 1
            r["note"] = f"name-search key: {halfwidth(fw)}"
        r = strings[s["idx"]]
        fw = fullwidth(initials[i])
        r["initials"] = True
        r.pop("key", None)
        if 2 * len(fw) + 1 <= r["budget"]:
            r["en"] = fw; r.pop("long", None)
        else:
            r["en"] = ""; r["long"] = fw
        r["note"] = f"name-search section: the typed first letters routed here ({initials[i]})"
    if write:
        with open(B040_JSON, "w", encoding="utf-8", newline="\n") as f:
            json.dump(spec, f, ensure_ascii=False, indent=1)
            f.write("\n")
    print(f"{sum(len(s['keys']) for s in sections)} keys ({n_en} in place, {n_long} as longs), "
          f"{len(sections)} section headers written to {B040_JSON}")


# --- the built bank ------------------------------------------------------------
def built_bank(data, exe):
    o = satdata.TABLE_OFF + 4 * B040
    sec, words = struct.unpack_from(">HH", exe, o)
    return data[sec * SECTOR:sec * SECTOR + words * 2]


def region_of(bank):
    w0, w1 = struct.unpack_from(">HH", bank, 0)
    return w0, bank[4 + w0:4 + w0 + w1]


STR_MIRROR = 0x202E8000


def long_group(region):
    """satlong's {old: new} from the region's tail, {} when there is none."""
    if len(region) < 4:
        return {}
    magic, goff = struct.unpack_from(">HH", region, len(region) - 4)
    if magic != 0xFFFF:
        return {}
    n = struct.unpack_from(">H", region, goff)[0]
    # entries {old u16, pad, new u32}: a pointer; region-relative when it points
    # into the region (the keys), else out of the bank (dialogue longs, skipped)
    out = {}
    for old, _pad, ptr in struct.iter_unpack(">HHI", region[goff + 4:goff + 4 + 8 * n]):
        if STR_MIRROR <= ptr < STR_MIRROR + 0x10000:
            out[old] = ptr - STR_MIRROR
    return out


def region_string(region, off):
    end = region.index(b"\0", off)
    return bytes(region[off:end])


def fw_bytes(text):
    """A fullwidth string as the bank stores it (the PS1 codec = negated SJIS)."""
    from textcodec import encode_string
    return encode_string(text)


def key_codes(raw):
    """The bytes the engine's label conversion makes of a bank string: -lo - 0x40 per char."""
    return bytes(((0xC0 - raw[i + 1]) & 0xFF) for i in range(0, len(raw) - 1, 2))


def effective(rec):
    return rec.get("long") or rec.get("en") or ""


def directory(sections, strings, region, group):
    """[[final region offset]] per section, verified against the JSON text."""
    w0 = None
    out = []
    problems = []
    for s in sections:
        offs = []
        for k in s["keys"]:
            r = strings[k["idx"]]
            old = k["off"]
            new = group.get(old, old)
            want = fw_bytes(effective(r))
            got = region_string(region, new)
            if got != want:
                problems.append(f"key {k['idx']} at region {new:#x}: {got.hex()} != {effective(r)!r}")
            offs.append(new)
        out.append(offs)
    return out, problems


def keysel_program(dir_words):
    P = [
        ("label", "keysel"),
        ("sts.l", "pr", "@-r15"),
        ("mov.l", "r8", "@-r15"), ("mov.l", "r9", "@-r15"),
        ("mov.l", "r10", "@-r15"), ("mov.l", "r11", "@-r15"),
        # r3 = i = (r4 - CAND_BASE) / 14
        ("mov.l", f"=0x{CAND_BASE:08x}", "r1"),
        ("mov", "r4", "r2"), ("sub", "r1", "r2"),
        ("mov", "#0", "r3"), ("mov", "#14", "r0"),
        ("label", "div"),
        ("cmp/hs", "r0", "r2"), ("bf", "div_done"),
        ("sub", "r0", "r2"), ("add", "#1", "r3"),
        ("bra", "div"), ("nop",),
        ("label", "div_done"),
        ("mov.l", "=target", "r8"),
        ("tst", "r3", "r3"), ("bf", "have"),
        # first candidate: scan the directory for the typed name
        ("mov", "#-1", "r0"), ("mov.l", "r0", "@r8"),
        ("mov.l", f"=0x{STRING_BASE_VAR:08x}", "r1"), ("mov.l", "@r1", "r1"),
        ("mov.l", "=dir", "r2"),
        ("mov.w", "@r2+", "r9"), ("extu.w", "r9", "r9"),       # nsec
        ("mov", "#0", "r10"),                                    # s
        ("label", "sec_loop"),
        ("cmp/eq", "r9", "r10"), ("bt", "have"),
        ("mov.w", "@r2+", "r11"), ("extu.w", "r11", "r11"),     # n keys
        ("label", "ent_loop"),
        ("tst", "r11", "r11"), ("bt", "sec_next"),
        ("mov.w", "@r2+", "r0"), ("extu.w", "r0", "r0"),
        ("mov", "r1", "r6"), ("add", "r0", "r6"),                # r6 = the key string
        ("mov.l", f"=0x{TYPED:08x}", "r7"),
        ("label", "cmp_loop"),
        ("mov.b", "@r6+", "r0"), ("tst", "r0", "r0"), ("bt", "key_end"),
        ("mov.b", "@r6+", "r0"),
        (".word", 0x600B),                                       # neg r0,r0
        ("add", "#-64", "r0"), ("extu.b", "r0", "r0"),
        ("mov.b", "@r7+", "r5"), ("extu.b", "r5", "r5"),
        ("cmp/eq", "r5", "r0"), ("bf", "ent_next"),
        ("bra", "cmp_loop"), ("nop",),
        ("label", "key_end"),
        ("mov.b", "@r7", "r0"), ("tst", "r0", "r0"), ("bf", "ent_next"),
        ("mov.l", "r10", "@r8"),                                 # target = s
        ("bra", "have"), ("nop",),
        ("label", "ent_next"),
        ("add", "#-1", "r11"), ("bra", "ent_loop"), ("nop",),
        ("label", "sec_next"),
        ("add", "#1", "r10"), ("bra", "sec_loop"), ("nop",),
        ("label", "have"),
        ("mov.l", "@r8", "r0"),
        (".word", 0x4011),                                       # cmp/pz r0
        ("bf", "fallback"),
        ("cmp/eq", "r3", "r0"),
        (".word", 0x0029),                                       # movt r0
        ("bra", "done"), ("nop",),
        ("label", "fallback"),
        ("mov.l", f"=0x{TYPED:08x}", "r7"), ("mov.b", "@r7", "r5"),
        ("mov.l", f"=0x{STRCHR:08x}", "r0"),
        ("jsr", "@r0"), ("nop",),
        ("label", "done"),
        ("mov.l", "@r15+", "r11"), ("mov.l", "@r15+", "r10"),
        ("mov.l", "@r15+", "r9"), ("mov.l", "@r15+", "r8"),
        ("lds.l", "@r15+", "pr"),
        ("rts",), ("nop",),
        ("label", "target"), (".long", 0xFFFFFFFF),
        ("pool",),
        ("label", "dir"),
    ]
    P += [(".word", w) for w in dir_words]
    return P


def dir_words(dir_offs):
    words = [len(dir_offs)]
    for offs in dir_offs:
        words.append(len(offs))
        words += offs
    assert all(0 <= w < 0x10000 for w in words)
    return words


def patch_layout(exe):
    """The Latin codes into LAYOUT; returns the number of keys changed."""
    cm = cell_map(exe)
    changed = 0
    for rc, ch in latin_cells().items():
        if ch is None:
            continue
        k = cm[rc]
        assert k != OK_KEY, rc
        o = LAYOUT - MAIN_BASE + 2 * k
        code, kind = code_of(ch), 0
        if exe[o] != code or exe[o + 1] != kind:
            exe[o], exe[o + 1] = code, kind
            changed += 1
    return changed


def u32(b, addr):
    return struct.unpack_from(">I", b, addr - MAIN_BASE)[0]


def u16(b, addr):
    return struct.unpack_from(">H", b, addr - MAIN_BASE)[0]


def cmd_apply(dry=False):
    for p in (OUT_DATA, OUT_MAIN):
        if not os.path.exists(p):
            sys.exit(f"{p} missing: run satapply.py, satnames.py and satlong.py first")
    data = open(OUT_DATA, "rb").read()
    exe = bytearray(open(OUT_MAIN, "rb").read())
    led = satexec.load_ledger(bytes(exe))
    lines = []

    def log(m=""):
        print(m, flush=True); lines.append(m)

    if u32(exe, GLYPH_VIEW_POOL) != GLYPH_VIEW_KANA:
        sys.exit(f"pool word {GLYPH_VIEW_POOL:#x} holds {u32(exe, GLYPH_VIEW_POOL):#010x}, "
                 f"expected {GLYPH_VIEW_KANA:#010x} - double apply?")
    if u32(exe, KEYSEL_POOL) != STRCHR:
        sys.exit(f"pool word {KEYSEL_POOL:#x} holds {u32(exe, KEYSEL_POOL):#010x}, expected strchr - double apply?")
    assert u16(exe, PUZZLE_MAXLEN) == 0xE604, hex(u16(exe, PUZZLE_MAXLEN))
    assert u16(exe, SEARCH_MAXLEN) == 0xE60A, hex(u16(exe, SEARCH_MAXLEN))

    assert u32(exe, LIST_PTR) == LIST_ORIG and all(u32(exe, p) == CELLS_ORIG for p in CELLS_POOL)
    for a, v in ((PUZZLE_COUNT, 0xE008), (SEARCH_BUILD_N, 0xE50A), (SEARCH_COUNT, 0xE00F),
                 (SEARCH_X, 0xE340), (PUZZLE_X, 0xE370)):
        assert u16(exe, a) == v, (hex(a), hex(u16(exe, a)))

    # the keyboard
    n = patch_layout(exe)
    struct.pack_into(">I", exe, GLYPH_VIEW_POOL - MAIN_BASE, GLYPH_VIEW_LATIN)
    struct.pack_into(">H", exe, PUZZLE_MAXLEN - MAIN_BASE, 0xE600 | PUZZLE_MAXLEN_NEW)
    struct.pack_into(">H", exe, PUZZLE_COUNT - MAIN_BASE, 0xE000 | (NPIECES + PUZZLE_MAXLEN_NEW + 1))
    # the sprite list with room for MAXLEN letters and the cursor
    lst = bytes(exe[LIST_ORIG - MAIN_BASE:LIST_ORIG - MAIN_BASE + 8 + 12 * (NPIECES + NCELLS_ORIG)])
    cells = [lst[8 + 12 * (NPIECES + i):8 + 12 * (NPIECES + i + 1)] for i in range(NCELLS_ORIG)]
    for i in range(NCELLS_ORIG, NCELLS):
        cells.append(bytes(cells[-1]))
    for i, c in enumerate(cells):                   # the wrappers rewrite x at open; the copy agrees
        c = bytearray(c)
        struct.pack_into(">H", c, 8, SEARCH_X_NEW + 16 * i)
        cells[i] = bytes(c)
    lst = lst[:8 + 12 * NPIECES] + b"".join(cells)
    struct.pack_into(">H", exe, SEARCH_X - MAIN_BASE, 0xE300 | SEARCH_X_NEW)
    struct.pack_into(">H", exe, PUZZLE_X - MAIN_BASE, 0xE300 | PUZZLE_X_NEW)
    laddr = satexec.alloc(led, exe, "satkeys-list", len(lst), align=4)
    exe[laddr - MAIN_BASE:laddr - MAIN_BASE + len(lst)] = lst
    struct.pack_into(">I", exe, LIST_PTR - MAIN_BASE, laddr)
    for p in CELLS_POOL:
        struct.pack_into(">I", exe, p - MAIN_BASE, laddr + 8 + 12 * NPIECES)
    struct.pack_into(">H", exe, SEARCH_MAXLEN - MAIN_BASE, 0xE600 | MAXLEN)
    struct.pack_into(">H", exe, SEARCH_BUILD_N - MAIN_BASE, 0xE500 | (NCELLS - 1))
    struct.pack_into(">H", exe, SEARCH_COUNT - MAIN_BASE, 0xE000 | (NPIECES + NCELLS))
    log(f"keyboard: {n} keys re-coded Latin (A-Z 0x20.., 0-9 0x0F.., space 0x80), "
        f"typed-cell glyph view {GLYPH_VIEW_KANA:#x} -> {GLYPH_VIEW_LATIN:#x} (SJIS 0x8240 + code); "
        f"puzzle field 4 -> {PUZZLE_MAXLEN_NEW} characters; search field 10 -> {MAXLEN} "
        f"(the sprite list copied to {laddr:#x}, {len(lst)} bytes, {NCELLS} cells)")

    # the directory from the built bank
    sections, names, initials, unreachable, spec, carry = plan_keys()
    strings = spec["strings"]
    bank = built_bank(data, exe)
    w0, region = region_of(bank)
    group = long_group(region)
    dir_offs, problems = directory(sections, strings, region, group)
    for p in problems:
        log("  " + p)
    if problems:
        sys.exit(f"{len(problems)} keys do not read back from the built bank - run satkeys.py fit, then the build")
    words = dir_words(dir_offs)
    prog = keysel_program(words)
    probe, _ = sh2asm.asm(prog, satexec.HOLE_LO)
    addr = satexec.alloc(led, exe, "satkeys", len(probe), align=4)
    code, labels = sh2asm.asm(prog, addr)
    exe[addr - MAIN_BASE:addr - MAIN_BASE + len(code)] = code
    struct.pack_into(">I", exe, KEYSEL_POOL - MAIN_BASE, labels["keysel"])
    log(f"KEYSEL: {len(code)} bytes at {addr:#x} (directory {labels['dir']:#x}: {len(sections)} sections, "
        f"{sum(len(o) for o in dir_offs)} keys, {len(group)} longs in the bank); pool word {KEYSEL_POOL:#x} retargeted")
    log(f"section initials: " + " ".join(f"{i}:{initials[i] or '-'}" for i in range(len(sections))))
    os.makedirs(BUILD, exist_ok=True)
    if dry:
        log("dry run: nothing written")
    else:
        open(OUT_MAIN, "wb").write(bytes(exe))
        satexec.save_ledger(led, bytes(exe))
        log(f"wrote {OUT_MAIN}")
    with open(os.path.join(BUILD, "keys_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(BUILD, "keys_stub.txt"), "w", encoding="utf-8") as f:
        f.write(sh2asm.check(code[:labels["dir"] - addr], addr) + "\n")
    cmd_check(exe=bytes(exe), data=data)


# --- the key faces --------------------------------------------------------------
# The keyboard panel is DATA.BIN chunk 310 (LZ, 43,456 bytes decoded): four
# 8bpp pieces drawn as the VDP1 sprites of the list at 0x060E57C8 - 128x80 at
# screen (4,152) from decoded offset 0x3C20, 56x48 at (260,152) from 0x6420,
# 56x32 at (260,200) from 0x6EA0, 128x80 at (132,152) from 0x75A0 (found by
# matching VDP1 VRAM 0x43C00 of a keyboard state against every decoded
# chunk). A key face is a 10x10 interior of index 0x38 (x 46..55, y 162..171
# for the first key) inside a bevel (0x34 left, 0x32/0x33 right, rounded
# corners) with the kana in 0x3F over the WHOLE 10x10 (x 46..55, y 162..171,
# the four corners being bevel; 0x35/0x3C/0x2F shade a few strokes): the
# whole interior is cleared and the 5x7 glyph drawn on it (until 2026-09-16
# only the inner 8x8 was cleared, and the kana's outermost columns stayed as
# a pink strip on either side of every letter - Luiz's "artifacts"). The key
# boxes start at screen x 46, 61, 76, 91, 106 | 126 .. 186 | 206 .. 266
# (pitch 15, a 5-px gap between the blocks) and y 162, 176, 190, 204 (pitch
# 14). The SELECTED key is not the panel: the pad handler 0x060B97F0 sets
# sprite object 11 to animation `key index` of the chunk's sprite index
# (0x060B5428(11, key, ...); anim k -> list k+2 -> one 16x16 8bpp tile at
# section offset 256*k, the panel piece at (44 + 15*col + 5*block,
# 160 + 14*row) - VDP1 command srca 0x40000 + 0x100*key in play), a blue
# key with the kana in the pale 0x17 over the 0x0F interior (tile cols/rows
# 2..11; tile 55, the space key, is the blank), so those 56 tiles carry the
# Latin glyph too (the OK button's two highlight pieces at 0x3800/0x3A80 are
# already Latin). The override goes to patched/saturn/chunks/310.bin,
# satpack.py's contract (decoded bytes; it packs and lays the chunk out).
FACES_CHUNK = 310
FACES_PIECES = [(0x3C20, 128, 80, 4, 152), (0x6420, 56, 48, 260, 152),
                (0x6EA0, 56, 32, 260, 200), (0x75A0, 128, 80, 132, 152)]
FACE_X = [47, 62, 77, 92, 107, 127, 142, 157, 172, 187, 207, 222, 237, 252, 267]
FACE_Y = [163, 177, 191, 205]
FACE_W, FACE_H = 8, 8
FACE_BG, FACE_INK = 0x38, 0x3F
# the highlight tiles: 16x16 8bpp at section offset 256*key (section 0 starts
# at decoded 0x20); the interior is tile (2..11, 2..11) minus the corners
TILE_BASE, TILE_SIZE, NTILES, BLANK_TILE = 0x20, 256, 56, 55
TILE_INK = 0x17
CHUNKS_DIR = os.path.join(OUT, "chunks")


def interior(x0, y0):
    """The (x, y) of a key's 10x10 interior with origin (x0, y0) = its top-left
    interior pixel: the rounded corners stay bevel."""
    return [(x0 + x, y0 + y) for y in range(10) for x in range(10)
            if not ((x in (0, 9)) and (y in (0, 9)))]


def glyph(ch, x0, y0):
    """(x, y) pixels of the 5x7 glyph placed in a 10x10 interior at (x0, y0)."""
    from kbdfaces import FONT
    rows = FONT[ch]
    gx, gy = x0 + 2, y0 + 1
    return [(gx + x, gy + y) for y, row in enumerate(rows) for x, px in enumerate(row) if px == "#"]


def panel_offset(x, y):
    """Decoded-chunk offset of screen pixel (x, y), or None outside the pieces."""
    for off, w, h, px, py in FACES_PIECES:
        if px <= x < px + w and py <= y < py + h:
            return off + (y - py) * w + (x - px)
    return None


def paint_faces(dec, exe=None):
    """The Latin faces into a decoded chunk 310 (bytearray): the panel's key
    faces and the 56 highlight tiles; returns the cells painted."""
    exe = exe or open(satdata.MAIN, "rb").read()
    cm = cell_map(exe)
    blank = bytes(dec[TILE_BASE + TILE_SIZE * BLANK_TILE:TILE_BASE + TILE_SIZE * (BLANK_TILE + 1)])
    assert TILE_INK not in blank and blank[16 * 5 + 5] == 0x0F, "tile 55 is not the blank key"
    n = 0
    for (r, c), ch in latin_cells().items():
        if ch is None:
            continue
        # the panel: interior origin = the face box - 1 (FACE_X/Y are the inner 8x8)
        x0, y0 = FACE_X[c] - 1, FACE_Y[r] - 1
        for x, y in interior(x0, y0):
            o = panel_offset(x, y)
            assert o is not None, (r, c)
            dec[o] = FACE_BG
        if ch != " ":
            for x, y in glyph(ch, x0, y0):
                dec[panel_offset(x, y)] = FACE_INK
        # the highlight tile of the key under that cell
        k = cm[(r, c)]
        assert k < NTILES, (r, c, k)
        t = TILE_BASE + TILE_SIZE * k
        dec[t:t + TILE_SIZE] = blank
        if ch != " ":
            for x, y in glyph(ch, 2, 2):
                dec[t + 16 * y + x] = TILE_INK
        n += 1
    return n


def cmd_faces(preview=True):
    import lz3
    data = open(satdata.DATA, "rb").read()
    ents = satdata.read_table()
    raw = satdata.entry(data, ents, FACES_CHUNK)
    dec = bytearray(lz3.decode(raw))
    assert len(dec) == 43456, len(dec)
    # the pristine geometry: every face interior really is index 0x38 with the kana in ink
    for (r, c), ch in latin_cells().items():
        if ch is None:
            continue
        o = panel_offset(FACE_X[c], FACE_Y[r])
        assert dec[o] in (FACE_BG, FACE_INK, 0x35, 0x3C, 0x2F) and dec[panel_offset(FACE_X[c] - 2, FACE_Y[r] + 1)] == 0x34, (r, c, hex(dec[o]))
    n = paint_faces(dec)
    os.makedirs(CHUNKS_DIR, exist_ok=True)
    out = os.path.join(CHUNKS_DIR, f"{FACES_CHUNK:03d}.bin")
    open(out, "wb").write(bytes(dec))
    print(f"faces: {n} key cells painted Latin in chunk {FACES_CHUNK}; override {out} ({len(dec)} bytes, decoded)")
    if preview:
        try:
            from PIL import Image
            img = Image.new("L", (320, 88 + 16 * 4), 0)
            shade = {FACE_BG: 200, FACE_INK: 0}
            for off, w, h, px, py in FACES_PIECES:
                piece = Image.frombytes("L", (w, h), bytes(shade.get(b, 40 + (b & 0x3F) * 2) for b in dec[off:off + w * h]))
                img.paste(piece, (px - 4, py - 152))
            for k in range(NTILES):                  # the highlight tiles, 14 per row
                t = TILE_BASE + TILE_SIZE * k
                tile = Image.frombytes("L", (16, 16), bytes(255 if b == TILE_INK else 40 + b * 6 for b in dec[t:t + TILE_SIZE]))
                img.paste(tile, (16 * (k % 14), 88 + 16 * (k // 14)))
            os.makedirs(BUILD, exist_ok=True)
            img.resize((640, 2 * (88 + 64))).save(os.path.join(BUILD, "keys_faces.png"))
            print(f"preview {os.path.join(BUILD, 'keys_faces.png')}")
        except ImportError:
            pass


# --- verification ---------------------------------------------------------------
PS1_FILES = {"ISZ_B060.json": "SAT_027_B060", "ISZ_B070.json": "SAT_028_B070",
             "ISZ_B1A0.json": "SAT_047_B1A0", "ISZ_B1D0.json": "SAT_050_B1D0"}


def puzzle_records():
    """(sat json name, record, wanted fullwidth text) for every PUZZLE_TARGETS entry with a Saturn twin."""
    from lock_data_strings import PUZZLE_TARGETS
    out = []
    for ps1f, satf in PS1_FILES.items():
        ref = json.load(open(os.path.join(WORK, "ref", ps1f), encoding="utf-8"))["strings"]
        sat = json.load(open(os.path.join(TR, satf + ".json"), encoding="utf-8"))
        bysrc = {}
        for r in sat["strings"]:
            if r.get("src"):
                bysrc.setdefault(r["src"], []).append(r)
        bank = ps1f[4:8]
        for idx, text in PUZZLE_TARGETS[ps1f].items():
            for r in bysrc.get(f"{bank}:{ref[idx]['off']}", []):
                out.append((satf, sat["entry"], r, text))
    return out


def cmd_check(exe=None, data=None):
    errors = []
    sections, names, initials, unreachable, spec, carry = plan_keys()
    strings = spec["strings"]
    # the JSON: every key fullwidth Latin, unique in its section, within the field
    for i, s in enumerate(sections):
        seen = set()
        for k in s["keys"]:
            r = strings[k["idx"]]
            t = effective(r)
            if not r.get("key"):
                errors.append(f"key {k['idx']} ({carry[k['idx']]['jp']}) lacks key: true - run satkeys.py fit")
            hw = halfwidth(t)
            if not t or t != fullwidth(hw) or not all(c in ALPHABET for c in hw):
                errors.append(f"key {k['idx']}: {t!r} is not fullwidth A-Z/0-9")
            if hw in seen:
                errors.append(f"key {k['idx']}: {hw} twice in section {i}")
            seen.add(hw)
            if r.get("lock"):
                errors.append(f"key {k['idx']} is locked")
        h = strings[s["idx"]]
        t = effective(h)
        if halfwidth(t) != initials[i] or not h.get("initials"):
            errors.append(f"section {i} header: {t!r}, wanted {fullwidth(initials[i])!r} with initials: true")
    # puzzle targets
    for satf, entry, r, text in puzzle_records():
        t = effective(r)
        if t != text:
            errors.append(f"{satf} off {r['off']}: {t!r}, PUZZLE_TARGETS wants {text!r}")
        if len(text.replace("以外", "")) > PUZZLE_MAXLEN_NEW:
            errors.append(f"{satf} off {r['off']}: {text!r} is longer than the {PUZZLE_MAXLEN_NEW}-character field")
    # the built files
    if exe is None and os.path.exists(OUT_MAIN):
        exe = open(OUT_MAIN, "rb").read()
        data = open(OUT_DATA, "rb").read()
    if exe is not None:
        if u32(exe, GLYPH_VIEW_POOL) != GLYPH_VIEW_LATIN:
            errors.append("exec: the typed-cell glyph view is not the Latin one")
        if u16(exe, PUZZLE_MAXLEN) != (0xE600 | PUZZLE_MAXLEN_NEW):
            errors.append("exec: the puzzle field length is not patched")
        if u16(exe, SEARCH_MAXLEN) != (0xE600 | MAXLEN) or u16(exe, SEARCH_COUNT) != (0xE000 | NPIECES + NCELLS)                 or u16(exe, SEARCH_BUILD_N) != (0xE500 | NCELLS - 1)                 or u16(exe, PUZZLE_COUNT) != (0xE000 | NPIECES + PUZZLE_MAXLEN_NEW + 1):
            errors.append("exec: the field lengths / sprite counts are not patched")
        laddr = u32(exe, LIST_PTR)
        if not (satexec.HOLE_LO <= laddr < satexec.HOLE_HI) or any(u32(exe, p) != laddr + 8 + 12 * NPIECES for p in CELLS_POOL):
            errors.append("exec: the keyboard sprite list is not relocated")
        else:
            o = laddr - MAIN_BASE
            if exe[o:o + 8 + 12 * NPIECES] != exe[LIST_ORIG - MAIN_BASE:LIST_ORIG - MAIN_BASE + 8 + 12 * NPIECES]:
                errors.append("exec: the relocated list's panel pieces differ")
            xs = [struct.unpack_from(">H", exe, o + 8 + 12 * (NPIECES + i) + 8)[0] for i in range(NCELLS)]
            if xs != [xs[0] + 16 * i for i in range(NCELLS)]:
                errors.append(f"exec: the relocated cells are not 16 px apart: {xs}")
        cm = cell_map(exe)
        for rc, ch in latin_cells().items():
            if ch is None:
                continue
            o = LAYOUT - MAIN_BASE + 2 * cm[rc]
            if exe[o] != code_of(ch) or exe[o + 1] != 0:
                errors.append(f"exec: key {rc} {ch!r} emits {exe[o]:#x}/{exe[o + 1]}")
        stub = u32(exe, KEYSEL_POOL)
        if not (satexec.HOLE_LO <= stub < satexec.HOLE_HI):
            errors.append(f"exec: the section pick still calls {stub:#x}")
        else:
            # the directory as the stub reads it, against the built bank
            bank = built_bank(data, exe)
            w0, region = region_of(bank)
            group = long_group(region)
            dir_offs, problems = directory(sections, strings, region, group)
            errors += problems
            # find the directory: the stub's pool ends with the words; re-assemble to locate
            words = dir_words(dir_offs)
            prog = keysel_program(words)
            code, labels = sh2asm.asm(prog, stub)
            got = exe[stub - MAIN_BASE:stub - MAIN_BASE + len(code)]
            if bytes(got) != code:
                errors.append("exec: the KEYSEL stub/directory differ from what the built bank implies")
            # every key's converted form is what the Latin keyboard can type
            for s, offs in zip(sections, dir_offs):
                for k, off in zip(s["keys"], offs):
                    codes = key_codes(region_string(region, off))
                    want = bytes(code_of(c) for c in halfwidth(effective(strings[k["idx"]])))
                    if codes != want:
                        errors.append(f"key {k['idx']}: converts to {codes.hex()} not {want.hex()}")
            # puzzle targets in the built banks: the effective string decodes to the target
            ents = {}
            for satf, entry, r, text in puzzle_records():
                if entry not in ents:
                    o = satdata.TABLE_OFF + 4 * entry
                    sec, words_ = struct.unpack_from(">HH", exe, o)
                    b = data[sec * SECTOR:sec * SECTOR + words_ * 2]
                    ents[entry] = region_of(b) + (long_group(region_of(b)[1]),)
                w0_, reg, grp = ents[entry]
                old = r["off"] - w0_ - 4
                new = grp.get(old, old)
                got = region_string(reg, new)
                if got != fw_bytes(text):
                    errors.append(f"{satf} off {r['off']}: built bank holds {got.hex()} at {new:#x}, not {text!r}"
                                  + ("" if old in grp or not r.get("long") else " (no long remap in the bank - satlong not run?)"))
    print(f"check: {len(errors)} problems" + (":" if errors else ""))
    for e in errors:
        print("  " + e)
    if errors:
        sys.exit(1)


def main(argv):
    cmd = argv[0] if argv else "parse"
    if cmd == "parse":
        cmd_parse()
    elif cmd == "fit":
        cmd_fit(write="--dry" not in argv)
    elif cmd == "apply":
        cmd_apply(dry="--dry" in argv)
    elif cmd == "check":
        cmd_check()
    elif cmd == "faces":
        cmd_faces()
    else:
        print(__doc__)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1:])
