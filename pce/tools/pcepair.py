"""Two Latin characters per cell for the PCE: pair codes, the module pair tables, the font.

The PCE font is the System Card's (EX_GETFNT), so no glyph can be added to
it. Instead the glyph fetch in stage 2 ($6473) is hooked (pceengine.py): a
SJIS code in rows 0x88-0x98 met while the English flag is up is not a kanji
but a PAIR of characters, composed on the fly from a 6x12 halfwidth font
the module carries (FONT_OFF: every printable ASCII character, X11 6x13
with its blank top row trimmed).

Codes to slots (unchanged since 2026-09-11):
  slots 0..2759   rows 0x89-0x97, 184 codes each
  slots 2760..    row 0x98 with a trail byte under 0x9F, then row 0x88 with
                  one from 0x9F up - the two halves the codec's n=8 case
                  splits (see pcetext), 94 codes each; 2948 codes in all

Slots to characters (2026-09-30): each module carries its own PAIR TABLE -
`[n u16]` then n entries `{glyph a, glyph b}` (glyph = ASCII - 0x20), its
address in the module's PAIRS_PTR word - and a slot is an index into it.
Every pair the module's text uses gets the next free slot as the build
encodes it (`PairTable.slot`), so ANY two characters share a cell: no
letter is left alone in a half-blank cell ("V ideophone", "HQ ." - until
then slot = a*54 + b over a 54-letter alphabet, and Q, V, X, Z, the digits
and most punctuation were drawn alone, 1,867 holes). A module needs 330-940
pairs (1,500 across the game), 0.7-1.9 KB of table.

The encoders run inside `using(table_for(rec))`; decoders load a module's
table back from its bytes (`PairTable.from_module`). A module with no table
(PAIRS_PTR 0 - a savestate from an older build) decodes by the old
arithmetic (`legacy_pair_of`). ALPHA/EXTRA/halffont() stay for the opening's
own stub (pceopening), which draws single glyphs in that order.
"""
import contextlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

# the old 54-letter alphabet and its singles: the opening stub's glyph order, and the
# arithmetic an older build's module (no pair table) still decodes by
ALPHA = " abcdefghijklmnopqrstuvwxyz.,'?!ABCDEFGHIJKLMNOPRSTUWY"
assert len(ALPHA) == 54
EXTRA = "QVXZ0123456789-()%&*+:;=>_"
INDEX = {c: i for i, c in enumerate(ALPHA)}

ROW_HI = [0x89 + i for i in range(7)] + [0x90 + i for i in range(8)]
PER_ROW = 184
FULL = len(ROW_HI) * PER_ROW          # 2760 codes in the whole rows
TAIL = 94                             # and 94 more in each half row
SLOTS = FULL + 2 * TAIL               # 2948
FONT_OFF = 0x7FD0 - 95 * 12  # module-relative (0x7B5C): the font, 95 glyphs x 12 rows, 6-bit rows, ending
                          # where the module's pointer words begin - 0x7A00 until 2026-10-15 left 348 B
                          # unused behind it, and 478's longs blob outgrew the room it may take
PAIRS_PTR = 0x7FF0        # module-relative: u16 offset of the pair table's first entry
MARK = (0x84, 0x40)       # "English follows" code at the head of a string
GLYPHS = "".join(chr(c) for c in range(0x20, 0x7F))     # the module font's order
FACE = "6x13"             # X11 misc-fixed 6x13 (public domain, lib/fonts/), as the PS1
REGISTRY = os.path.join(WORK, "pce", "pair_tables.json")  # the build's tables, rec -> [pairs]


def code_of_slot(slot):
    """The SJIS code for a slot."""
    if slot < FULL:
        row, col = divmod(slot, PER_ROW)
        return ROW_HI[row], 0x40 + col + (1 if col >= 0x3F else 0)
    if slot < FULL + TAIL:                 # row 0x98, trail bytes under 0x9F
        col = slot - FULL
        return 0x98, 0x40 + col + (1 if col >= 0x3F else 0)
    col = slot - FULL - TAIL               # row 0x88, trail bytes from 0x9F
    assert slot < SLOTS, slot
    return 0x88, 0x9F + col


def slot_of_code(hi, lo):
    if hi == 0x98:
        return FULL + lo - 0x40 - (1 if lo > 0x7F else 0)
    if hi == 0x88:
        return FULL + TAIL + lo - 0x9F
    col = lo - 0x40 - (1 if lo > 0x7F else 0)
    return ROW_HI.index(hi) * PER_ROW + col


def is_pair(hi, lo):
    return hi in ROW_HI or hi == 0x98 or hi == 0x88


def printable(ch):
    return " " <= ch <= "~"


# ---------------------------------------------------------------- the pair tables

BLANK = (" ", " ")                    # slot 0 of every table


class PairTable:
    """One module's slots: [(a, b)], a slot per distinct pair, in order of first use."""

    def __init__(self, pairs=(), frozen=False):
        # slot 0 (code 89 40) is always two spaces: the subtitle stub pads its rows with that
        # code (pcesubs tpad), as the old arithmetic's slot 0 was
        self.pairs = [tuple(p) for p in pairs] or [BLANK]
        self.index = {p: i for i, p in enumerate(self.pairs)}
        self.frozen = frozen

    def slot(self, a, b):
        p = (a, b)
        if p not in self.index:
            if self.frozen:
                raise KeyError(f"pair {a + b!r} is not in the module's table")
            if len(self.pairs) >= SLOTS:
                raise OverflowError(f"more than {SLOTS} pairs in one module")
            self.index[p] = len(self.pairs)
            self.pairs.append(p)
        return self.index[p]

    def pair(self, slot):
        return self.pairs[slot] if slot < len(self.pairs) else None

    def blob(self):
        """[n u16][glyph a, glyph b]... - PAIRS_PTR names the first entry (the n before it)."""
        out = bytearray(len(self.pairs).to_bytes(2, "little"))
        for a, b in self.pairs:
            out += bytes([ord(a) - 0x20, ord(b) - 0x20])
        return bytes(out)

    @classmethod
    def from_module(cls, mod, base=0):
        """The table a built module carries (None if it has none): `mod` is the module's
        bytes, or any buffer with the module at `base`."""
        ptr = int.from_bytes(mod[base + PAIRS_PTR:base + PAIRS_PTR + 2], "little")
        if not ptr or ptr < 2:
            return None
        n = int.from_bytes(mod[base + ptr - 2:base + ptr], "little")
        if n > SLOTS:
            return None
        raw = mod[base + ptr:base + ptr + 2 * n]
        return cls([(chr(raw[2 * i] + 0x20), chr(raw[2 * i + 1] + 0x20)) for i in range(n)], frozen=True)


_tables = {}          # rec -> PairTable, while a build runs
_current = [None]


def table_for(rec):
    """The build's table for module `rec` (created empty on first use)."""
    rec = int(rec)
    if rec not in _tables:
        _tables[rec] = PairTable()
    return _tables[rec]


@contextlib.contextmanager
def using(table):
    """Encode (or decode) with `table` as the module's."""
    old = _current[0]
    _current[0] = table
    try:
        yield table
    finally:
        _current[0] = old


def use(table):
    _current[0] = table


def current():
    if _current[0] is None:
        raise RuntimeError("pair codes need a module's table: wrap the encoding in pcepair.using(...)")
    return _current[0]


def save_registry():
    os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
    json.dump({str(r): ["".join(p) for p in t.pairs] for r, t in sorted(_tables.items()) if t.pairs},
              open(REGISTRY, "w", encoding="utf-8"), indent=0)


def load_registry(frozen=True):
    """The tables pcescript built (the later tools encode into the same modules)."""
    for r, pairs in json.load(open(REGISTRY, encoding="utf-8")).items():
        _tables[int(r)] = PairTable([(p[0], p[1]) for p in pairs], frozen=frozen)


# ---------------------------------------------------------------- encoding

def split(text):
    """ASCII text -> [(a, b)] cells, left to right: every two printable characters share a
    cell, an odd last one takes a space. A character outside printable ASCII (a Japanese
    one left in a label) is yielded alone and ends the run of pairs before it."""
    out, i = [], 0
    while i < len(text):
        if printable(text[i]):
            if i + 1 < len(text) and printable(text[i + 1]):
                out.append((text[i], text[i + 1]))
                i += 2
            else:
                out.append((text[i], " "))
                i += 1
        else:
            out.append(text[i])
            i += 1
    return out


def cells(text):
    return len(split(text))


def pair_code(a, b):
    return code_of_slot(current().slot(a, b))


def code_of(cell):
    """Code for a cell: an (a, b) tuple."""
    return pair_code(*cell)


def pair_of(hi, lo):
    """(a, b) for a pair code under the current table (the old arithmetic when the module
    has none); None for a slot the table does not hold."""
    t = _current[0]
    if t is None:
        return legacy_pair_of(hi, lo)
    return t.pair(slot_of_code(hi, lo))


def legacy_pair_of(hi, lo):
    """The pre-table arithmetic: slot = a*54 + b, then the singles."""
    slot = slot_of_code(hi, lo)
    if slot >= len(ALPHA) ** 2:
        k = slot - len(ALPHA) ** 2
        return (EXTRA[k], " ") if k < len(EXTRA) else None
    return ALPHA[slot // len(ALPHA)], ALPHA[slot % len(ALPHA)]


# ---------------------------------------------------------------- the fonts

_fonts = {}


def _glyphs(chars):
    import bdffont
    f = bdffont.load(FACE)
    assert f.height == 12 and f.advance == 6, (f.height, f.advance)
    out = bytearray()
    for ch in chars:
        g = f.glyph(ch)
        assert g.shape == (12, 6), (ch, g.shape)
        for y in range(12):
            v = 0
            for x in range(6):
                v = (v << 1) | int(g[y, x])
            out.append(v)
    return bytes(out)


def modfont():
    """The module font: one 6x12 glyph per printable ASCII character (GLYPHS order),
    12 bytes each, 6-bit rows. X11 6x13 with its blank top row trimmed
    (lib/bdffont.TRIM_TOP): letters stand on row 9, descenders on 10-11."""
    if "mod" not in _fonts:
        _fonts["mod"] = _glyphs(GLYPHS)
    return _fonts["mod"]


def halffont():
    """The opening stub's font: ALPHA then EXTRA, 12 bytes each (pceopening)."""
    if "half" not in _fonts:
        _fonts["half"] = _glyphs(ALPHA + EXTRA)
    return _fonts["half"]


def compose(hi, lo):
    """The 12x12 bitmap (rows as 12-bit ints) the engine stub produces."""
    a, b = pair_of(hi, lo)
    font = modfont()
    ia, ib = GLYPHS.index(a) * 12, GLYPHS.index(b) * 12
    return [(font[ia + r] << 6) | font[ib + r] for r in range(12)]


def preview(path):
    from PIL import Image
    img = Image.new("L", (len(GLYPHS) * 6, 12), 0)
    font = modfont()
    for i in range(len(GLYPHS)):
        for r in range(12):
            for x in range(6):
                if font[i * 12 + r] & (0x20 >> x):
                    img.putpixel((i * 6 + x, r), 255)
    img.resize((len(GLYPHS) * 6 * 4, 48), Image.NEAREST).save(path)


if __name__ == "__main__":
    preview(os.path.join(WORK, "pce", "modfont.png"))
    print(len(modfont()), "bytes;", split("Hello, JUNKER HQ. Videophone 3"))
