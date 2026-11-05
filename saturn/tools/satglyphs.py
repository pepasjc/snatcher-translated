"""The Saturn font side of the English build: pair glyphs, the SJIS table, the exec.

The PS1 packs two Latin letters per kanji glyph slot (ps1/tools/pairfont.py,
work/pair_table.json: pair -> [slot, code]); the bank text is the same
2-byte code stream on both machines (the Saturn negates each byte into
Shift-JIS, satfont.py), so the PS1 pair CODES can stay in the text. What
differs is the glyph supply: the Saturn font (DATA.BIN chunk 0, 470 blocks
of four 4-bpp planes = 1,880 slots, VDP1 0x8000..0x15000) holds only the
1,871 characters the Japanese game draws, and the residual Japanese of a
build (strings with no `en`, locked ones, over-budget ones) still draws
~1,000 of its 1,610 kanji. That leaves ~560 free slots for ~1,480 pairs,
and the fit spirals: pairs without a slot fall back to two fullwidth
letters (4 bytes), which pushes strings over budget, which keeps more
kanji drawn, which frees fewer slots (the first simulation ended with
1,395 of 10,839 strings applied).

So the font grows downward (`EXT`): VDP1 VRAM 0x4000..0x8000 is never
written in any saved state (the game's two command lists end at 0x4000,
no exec constant points inside, the BIOS logo and the movies leave it
alone), and 146 more blocks fit at 0x4020..0x8000 contiguous with the
original blocks at 0x8000 - 584 slots. The exec then needs:
  * the loader's destination 0x25C08000 -> 0x25C04020 and budget 0xD000 ->
    0x10FE0 (0x060B4590 / 0x060B458C, load_chunk copies exactly that many
    bytes from the decode buffer);
  * the two renderers' CMDSRCA base 0x1000 -> 0x0804 (= 0x4020 / 8, the
    `mov.w` pool halfwords at 0x060B4A58 and 0x060B9DD4; block b then sits
    at 0x4020 + 112 b, and every ORIGINAL glyph index shifts by 584);
  * the SJIS -> glyph table at 0x060E6CF0 rewritten (shifted, freed kanji
    -> 0 = blank, each pair code -> its slot); the second renderer's
    "ASCII table" 0x060E70F0 is that same table from ア (0x8340) on - a
    katakana keyboard - so it shifts with it.
The direct `CMDSRCA = 0x1000` stores (0x060B9B10, 0x060B9F04: block 0, the
blank glyph, for cursor/blank sprites) stay right because the original
blocks do not move. Glyph 0 stays blank: every table code the game does
not use maps to 0. `--no-ext` builds the conservative layout instead
(0xD000, no exec code constants touched, only the slots the residual frees
plus the seven spare and the 20 the 475-block budget allows).

A pair keeps its PS1 code unless that code's SJIS is a kanji the Saturn
build still draws (the residual differs from the PS1's); then it takes a
fresh code from the table range the game never uses - never one whose
entry lies in the exec hole satexec.py allocates (SJIS 0x83C0..0x889E). Slots go to the most
frequent pairs of the wanted text (in place or, over budget, as satlong's
tail copy); the rest fall back. `plan()` iterates applied set <-> drawn
set <-> free slots to a fixed point; a string that does not fit keeps its
Japanese counted as drawn (the bank still holds it) and its English's
codes too.

Used by satapply.py; nothing here writes a file by itself except `main`
(a dry report). The pair art is satpair.py's (two 7-px-pitch letters in the 14-px cell pitch).
"""
import os, sys, json, struct, collections
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import satfont, lz3, satdata, satpair
from textcodec import char_to_code
import pairfont

MAIN_BASE = 0x060B0000
BLOCK = satfont.BLOCK
ORIG_BLOCKS = 470                 # blocks in the shipped chunk 0
BUDGET_BLOCKS = satfont.VDP1_BUDGET // BLOCK   # 475: the loader's 0xD000
NEW_BLOCKS = 146                  # 0x8000 - 146*112 = 0x4020
EXT_BASE = satfont.VDP1_FONT - NEW_BLOCKS * BLOCK   # 0x4020
EXT_SHIFT = NEW_BLOCKS * 4        # original glyph index g -> g + 584
EXT_BUDGET = satfont.VDP1_BUDGET + NEW_BLOCKS * BLOCK   # 0x10FE0
LOADER_BUDGET = 0x060B458C        # u32 0x0000D000
LOADER_DEST = 0x060B4590          # u32 0x25C08000
RENDER_BASES = (0x060B4A58, 0x060B9DD4)   # u16 0x1000 = CMDSRCA of block 0
ASCII_TAB = 0x060E70F0            # = TABLE_ADDR + 2*(0x8340-0x8140): the second renderer's katakana
NAME_PTRS = 0x060C1F1C            # u32 pointers into the speaker-name strings
NAME_LO, NAME_HI = 0x060C17F4, 0x060C1F1C
CTRL_TAB = 0x060E4DA8             # ＠青赤紫緑水黄白Ｃ
CHUNK_TAB = lz3.TABLE_ADDR
KANJI_LO = 0x889F                 # SJIS: JIS level-1 kanji start
CODE_LO, CODE_HI = satfont.TABLE_LO, satfont.TABLE_LO + satfont.TABLE_N
PS1_TABLE = pairfont.TABLE
SAT_TABLE = os.path.join(WORK, "saturn", "pair_table_sat.json")


def is_kanji(sjis):
    return sjis >= KANJI_LO


def raw_codes(raw):
    """SJIS codes of a raw bank string (2-byte codes, first byte 0x55..0x7F)."""
    out = []
    i = 0
    while i + 1 < len(raw):
        b = raw[i]
        if 0x55 <= b <= 0x7F:
            out.append(satfont.code_to_sjis((b << 8) | raw[i + 1]))
            i += 2
        else:
            i += 1
    return out


def text_codes(s):
    """SJIS codes of the non-ASCII characters of an English line (colour codes, ￥, ▽ ...)."""
    out = []
    for ch in s:
        if ord(ch) >= 0x80:
            c = char_to_code(ch)
            if c is None:
                raise ValueError(f"cannot encode {ch!r}")
            out.append(satfont.code_to_sjis(c))
    return out


def fallback_codes(pair):
    """The two fullwidth codes a pair without a slot becomes (pairfont's rule)."""
    out = []
    for ch in pair:
        fw = "　" if ch == " " else chr(0xFEE0 + ord(ch))
        c = char_to_code(fw)
        if c is None:
            c = char_to_code("？")
        out.append(satfont.code_to_sjis(c))
    return out


def pairs_of(s):
    """The letter pairs pairfont.encode would emit for s (ASCII runs, padded per run)."""
    out = []
    buf = ""
    for ch in s + "\0":
        if ch != "\0" and ord(ch) < 0x80:
            buf += ch
        else:
            if len(buf) % 2:
                buf += " "
            out += [buf[k:k + 2] for k in range(0, len(buf), 2)]
            buf = ""
    return out


def exec_codes(exe):
    """SJIS codes the exec itself draws: the speaker names and the control table."""
    out = set()
    o = NAME_PTRS - MAIN_BASE
    while True:
        p = struct.unpack_from(">I", exe, o)[0]
        if not NAME_LO <= p < NAME_HI:
            break
        q = p - MAIN_BASE
        while exe[q]:
            out.add((exe[q] << 8) | exe[q + 1])
            q += 2
        o += 4
    q = CTRL_TAB - MAIN_BASE
    for i in range(9):
        out.add((exe[q + 2 * i] << 8) | exe[q + 2 * i + 1])
    return out


def extra_pairs():
    """Hook point (2026-09-12): letter pairs drawn outside the bank text -
    the English speaker names (satnames.pairs_used), the `long` labels
    (satlong.pairs_used) and the subtitle cards (satsubs.pairs_used, since
    2026-09-16) - join the slot ranking at one count per use, so
    they get glyph slots like the bank text's. A module that is missing or
    fails is skipped; nothing else in the plan changes."""
    out = []
    sys.path.insert(0, os.path.join(ROOT, "saturn", "subs"))
    for mod in ("satnames", "satlong", "satsubs"):
        try:
            out += __import__(mod).pairs_used()
        except Exception as e:
            print(f"extra pairs from {mod} skipped: {e}")
    return out


class Item:
    """One bank string as the planner sees it."""
    __slots__ = ("bank", "off", "budget", "en", "lock", "long", "raw", "pairs", "fixed", "want", "applied", "note")

    def __init__(self, bank, rec, raw):
        self.bank, self.off, self.budget = bank, rec["off"], rec["budget"]
        self.en = rec.get("en") or ""
        self.lock = bool(rec.get("lock"))
        self.long = rec.get("long")
        self.raw = raw
        self.want = bool(self.en) and not self.lock
        self.pairs = pairs_of(self.en) if self.want else []
        self.fixed = text_codes(self.en) if self.want else []
        self.applied = False
        self.note = ""

    def enc_len(self, slotted):
        """Bytes incl. the null with pairs outside `slotted` falling back."""
        return 2 * len(self.pairs) + 2 * len(self.fixed) + 2 * sum(1 for p in self.pairs if p not in slotted) + 1


def load_items(translations, data=None, ents=None):
    """[Item] for every string of every saturn/translation JSON."""
    data = data if data is not None else open(satdata.DATA, "rb").read()
    ents = ents or satdata.read_table()
    items = []
    for path in translations:
        spec = json.load(open(path, encoding="utf-8"))
        bank = satdata.entry(data, ents, spec["entry"])
        for rec in spec["strings"]:
            raw = bank[rec["off"]:rec["off"] + rec["budget"] - 1]
            items.append(Item(spec["entry"], rec, raw))
    return items


def plan(items, exe, ext=True, ps1_table=None, log=print):
    """Decide the applied strings, the pair -> [slot, code] table and the freed kanji.

    Returns dict(applied, table {pair: [slot, code]}, drawn, freed, shift,
    stats). Slots are in the BUILT font's index space (ext: new 1..583, the
    original glyphs at +584)."""
    ps1_table = ps1_table or json.load(open(PS1_TABLE))
    orig = satfont.table(exe)                      # sjis -> glyph (original indices)
    shift = EXT_SHIFT if ext else 0
    base_drawn = set(exec_codes(exe))
    always = {s for s in orig if not is_kanji(s)}  # every kana/symbol stays
    spare = sorted(set(range(1, BUDGET_BLOCKS * 4)) - set(orig.values()))  # unused indices in the budget
    new_slots = list(range(1, NEW_BLOCKS * 4)) if ext else []   # slot 0 stays blank
    for it in items:
        it.applied = it.want
    slotted = set()
    for rnd in range(12):
        drawn = set(base_drawn) | always
        for it in items:
            if it.want:                    # applied in place or carried as a long: its codes draw either way
                drawn.update(it.fixed)
                for p in it.pairs:
                    if p not in slotted:
                        drawn.update(fallback_codes(p))
            if not it.applied:             # the Japanese stays in the bank (a long's original too: kept drawable)
                drawn.update(raw_codes(it.raw))
        freed = sorted(s for s in orig if is_kanji(s) and s not in drawn)
        pool = new_slots + [g + shift for g in spare] + [orig[s] + shift for s in freed]
        counts = collections.Counter()
        for it in items:
            if it.want:                    # over-budget ones too: satlong appends them as longs
                counts.update(it.pairs)
        counts.update(extra_pairs())
        ranked = [p for p, _ in counts.most_common()]
        slotted = set(ranked[:len(pool)])
        changed = 0
        for it in items:
            if not it.want:
                continue
            ok = it.enc_len(slotted) <= it.budget
            if ok != it.applied:
                changed += 1
            it.applied = ok
        log(f"plan round {rnd}: {sum(it.applied for it in items)} applied, "
            f"{len(freed)} kanji freed, {len(pool)} slots for {len(counts)} pairs "
            f"({max(0, len(counts) - len(pool))} without), {changed} changed")
        if not changed:
            break
    # slots: new area first (fresh glyphs), then spare, then freed kanji
    table = {}
    taken_codes = set()
    fresh = [s for s in range(KANJI_LO, CODE_HI) if s not in drawn and s not in orig] + \
            [s for s in range(0x8540, KANJI_LO) if s not in drawn and s not in orig] + \
            [s for s in range(KANJI_LO, CODE_HI) if s not in drawn]
    import satexec
    hole_lo, hole_hi = satexec.sjis_range()        # the exec hole's codes (0x83C0..0x889E) stay out of the text
    fresh = [s for s in fresh if (s & 0xFF) not in (0x00, 0x80) and (s >> 8) != 0 and not hole_lo <= s < hole_hi]
    recoded = 0
    fi = 0
    for pair, slot in zip(ranked[:len(pool)], pool):
        code = ps1_table.get(pair, [None, None])[1]
        sjis = satfont.code_to_sjis(code) if code is not None else None
        if sjis is None or sjis in drawn or sjis in taken_codes or not CODE_LO <= sjis < CODE_HI:
            while fresh[fi] in taken_codes:
                fi += 1
            sjis = fresh[fi]
            fi += 1
            recoded += 1
        taken_codes.add(sjis)
        table[pair] = [slot, satfont.sjis_to_code(sjis)]
    stats = dict(applied=sum(it.applied for it in items), wanted=sum(it.want for it in items),
                 pairs=len(counts), slots=len(pool), slotted=len(table),
                 unslotted=sorted(set(counts) - set(table)), freed=len(freed),
                 kanji_drawn=sum(1 for s in drawn if is_kanji(s) and s in orig),
                 recoded=recoded, new_slots=len(new_slots), spare=len(spare),
                 fallback_uses=sum(1 for it in items if it.applied for p in it.pairs if p not in table),
                 rounds=rnd + 1)
    return dict(applied=[it for it in items if it.applied], table=table, drawn=drawn,
                freed=freed, shift=shift, orig=orig, stats=stats, ext=ext)


def pair_cell(pair):
    """The 16x14 cell of a pair: two 8-px-pitch letters filling the Saturn
    cell (satpair.render_pair16), 14 row ints, bit 15 = column 0. Until
    2026-09-12 this was the PS1's 12-px pairfont.render_pair at (1, 1), which
    left a 4-px gap after every pair in the 16-px cell."""
    return satpair.pair_cell(pair)


def build_font(font, plan_):
    """The block array of the built font: [new blocks] + original + growth, pairs drawn in."""
    nblocks = (NEW_BLOCKS if plan_["ext"] else 0) + BUDGET_BLOCKS
    out = bytearray(nblocks * BLOCK)
    off = NEW_BLOCKS * BLOCK if plan_["ext"] else 0
    out[off:off + len(font)] = font
    for pair, (slot, code) in plan_["table"].items():
        satpair.set_cell(out, slot, pair_cell(pair))
    return bytes(out)


def sjis_table_bytes(plan_):
    """The rewritten 0x1734-entry SJIS -> glyph table."""
    t = [0] * satfont.TABLE_N
    freed = set(plan_["freed"])
    for sjis, g in plan_["orig"].items():
        if sjis not in freed:
            t[sjis - CODE_LO] = g + plan_["shift"]
    for pair, (slot, code) in plan_["table"].items():
        sjis = satfont.code_to_sjis(code)
        assert t[sjis - CODE_LO] == 0 or sjis in freed, (pair, hex(sjis))
        t[sjis - CODE_LO] = slot
    return struct.pack(f">{satfont.TABLE_N}H", *t)


def patch_exec(exe, plan_, chunk0=None):
    """MAIN_L.BIN bytes with the table, the EXT constants and
    (if given) chunk 0's table entry {sector, size//2}."""
    exe = bytearray(exe)
    o = satfont.TABLE_ADDR - MAIN_BASE
    exe[o:o + 2 * satfont.TABLE_N] = sjis_table_bytes(plan_)
    if plan_["shift"]:
        assert struct.unpack_from(">I", exe, LOADER_BUDGET - MAIN_BASE)[0] == satfont.VDP1_BUDGET
        assert struct.unpack_from(">I", exe, LOADER_DEST - MAIN_BASE)[0] == 0x25C00000 + satfont.VDP1_FONT
        struct.pack_into(">I", exe, LOADER_BUDGET - MAIN_BASE, EXT_BUDGET)
        struct.pack_into(">I", exe, LOADER_DEST - MAIN_BASE, 0x25C00000 + EXT_BASE)
        for a in RENDER_BASES:
            assert struct.unpack_from(">H", exe, a - MAIN_BASE)[0] == satfont.CMDSRCA_BASE
            struct.pack_into(">H", exe, a - MAIN_BASE, EXT_BASE // 8)
    if chunk0:
        sector, size = chunk0
        assert size % 2 == 0 and size // 2 < 0x10000 and sector < 0x10000
        struct.pack_into(">HH", exe, CHUNK_TAB - MAIN_BASE, sector, size // 2)
    return bytes(exe)


def literal_pack(data):
    """A valid LZ3 chunk with every byte a literal (bit 0 + the byte), for
    when lz3.encode is unavailable: 9/8 the size, decodes on the SH-2."""
    n = len(data)
    bits = n + 2                       # n literal flags, then `1,0` = token, token 0 ends
    nwords = (bits + 31) // 32
    words = bytearray(4 * nwords)
    # literal bits are 0; the terminator `1` sits at bit n, the `0` at n+1
    words[4 * (n // 32) + 3 - ((n % 32) // 8)] |= 1 << (n % 8)
    return struct.pack(">IHH", n, nwords, 1) + bytes(words) + b"\0\0" + bytes(data)


def pack_chunk(data):
    """lz3.encode if it exists and round-trips, else the literal packer. Returns (raw, how)."""
    enc = getattr(lz3, "encode", None)
    if enc is not None:
        try:
            raw = enc(data)
            if lz3.decode(raw) == data:
                return raw, "lz3.encode"
        except Exception as e:                # an encoder under construction
            print(f"lz3.encode failed ({e}); literal fallback")
    raw = literal_pack(data)
    assert lz3.decode(raw) == data
    return raw, "literal"


def main(argv):
    import glob
    ext = "--no-ext" not in argv
    exe = open(satdata.MAIN, "rb").read()
    items = load_items(sorted(glob.glob(os.path.join(ROOT, "saturn", "translation", "SAT_*.json"))))
    p = plan(items, exe, ext=ext)
    print(json.dumps(p["stats"], indent=1))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1:])
