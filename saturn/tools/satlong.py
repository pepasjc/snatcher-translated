"""The `long` labels on the Saturn: full text appended to the bank, redirected at runtime.

The PS1's repoint.py for DATA.BIN. A saturn/translation record whose short
`en` fits its slot and whose `long` is the label the player should read
(`Dr` / `Door`, `Bldg` / `Building`, 462 of them) keeps the short text in
place (satapply.py) and gets the long one appended to its bank; the engine
is then redirected from the old string to the new one without touching a
byte of bytecode.

**Over budget = long** (2026-09-12). A record whose `en` does not fit its
slot (pair-encoded with the build's table, null included: satapply keeps
the Japanese there and lists it in work/saturn/build/over_budget.txt) is a
long job too, with the full `en` as its text: nothing in the data moves
(the `en` stays the translation, no `long` field is written), the fit is
decided here at build time with the same encoder satapply used (and
checked against satapply's list), and the remap shows the English where
the Japanese sits. A record with a `long` of its own keeps that as the
text whether or not its short `en` fits. The 39 strings of the first
builds (35 of Gaudi's terminal, the rest dialogue a few bytes over) read
English this way; long_report.txt marks them `over budget`. satglyphs'
plan ranks their pairs with the in-place text's and keeps their Japanese
counted as drawn (the bank still holds it).

The bank in the file: {u16 w0, u16 w1} + bytecode (w0 bytes, loaded at
0x202F8000) + the string region (w1 bytes, loaded at 0x202E8000 =
[0x060FD164]) + a u32 the loader keeps at 0x060FD150 (+ a pad byte).
The scene loader 0x060B915E reads the two sizes from the header and the
chunk table entry {u16 sector, u16 size/2} at 0x060E62F4 bounds the read
(0x060B22EC sets the byte budget 0x060EF488 = size*2), so a grown region
means: w1 up, the table's size up, and the chunk in a slot that holds it -
in place when the sector slot has the slack (33 of 39 banks), else a slot
another grown bank vacated or fresh sectors at DATA.BIN's end (satdisc.py
shifts the files after it; 75 sectors of track slack, 20 already taken by
the font chunk). The region's window is 64 KB (0x202E8000..0x202F8000);
long dialogue is kept outside that window in a separate LNGS payload.

Bytecode references a string by BE16 word index; the reader 0x060C08B0
turns it into a region offset (2*word, minus one when the byte before is
not a null - strings start at odd offsets too), and every consumer adds
[0x060FD164] and hands the pointer on. Four consumers, one pool word each:
    0x060B82A8  show dialogue text            pool 0x060B835C = the converter 0x060C4D24
    0x060B8390  show text with a speaker      pool 0x060B84A0 = the converter
    0x060B904C  (from op 0x060C4B1A)          pool 0x060B907C = the converter
    0x060C31A0  add a list-menu item          pool 0x060C320C = strlen 0x060DBEF8, then
                                              strcpy into the 64-byte label table 0x060FAC60
The pool words are retargeted to stubs that run LOOKUP on r4 (the pointer)
and jump on to the original routine; the menu stub also rewrites r8 (the
site's copy of the offset, which it adds the base to after the call). The
converter's other callers (list-menu draws from the label table) keep
their own pool words and are never redirected. No flag bits ride in the
offset (the PS1 masked 0x3FFF; here the item's flags are a byte before the
word).

LOOKUP finds the bank's remap group without a directory in the exec: a
fifth stub on the loader's pool word 0x060B93AC (= 0x060B9144, the
read-into-RAM helper the loader calls for the bytecode and then for the
strings) records the region length when the destination is the string
base; the region's last four bytes are then {0xFFFF, group offset}
(0xFFFF cannot occur in text: codes are 0x55..0x7F bytes and nulls) and
the group is {count u16, pad u16, (old u16, pad u16, new u32) x count}.
Long text follows the bank's native u32 as {'LNGS', length u32, bytes}.
A sixth loader hook reads that payload into one buffer owned by the game's
allocator and reused for the session. On-disc long
pointers use LONGS_BASE as a bias; LOOKUP subtracts that bias and adds the
current allocation. Region-local keyboard keys retain their pointers.
The old fixed destination overlaps the game's malloc arena and is unsafe.
A bank
without longs has no tail and misses; a pointer outside the region
(offset >= 0x10000 unsigned) misses; before any bank loads the length is
zero and misses. The group and the tail sit on even offsets (mov.w).

Order: after satapply.py (fresh banks and exec, the pair table) and
satnames.py (which allocates the exec hole first - satexec.py), before
satdisc.py. The longs' pairs join the glyph ranking through
satglyphs.extra_pairs() (pairs_used() below).

    python saturn/tools/satlong.py [--dry]
"""
import glob, json, os, re, struct, sys
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
PAIR_TABLE = os.path.join(WORK, "saturn", "pair_table_sat.json")
SECTOR = 2048
TABLE_N = 639
TABLE_ADDR = 0x060E62F4
STRING_BASE_VAR = 0x060FD164
CONVERTER = 0x060C4D24
STRLEN = 0x060DBEF8
LOAD_HELPER = 0x060B9144
U32_READER = 0x060B9108   # the loader's "u32 after the strings" read (two u16 reads)
U16_READER = 0x060B90CC   # one u16 off the chunk stream (r4 handle, r5 name)
MAGIC = 0xFFFF
WINDOW = 0x10000
STR_MIRROR = 0x202E8000   # the string base as the game addresses it (cached mirror)
# Long strings out of the bank (2026-09-18, the PS1's longs-poc on the Saturn):
# the remap group stays in the region ({0xFFFF, goff} tail) but its entries
# are {old u16, pad, new u32} - an absolute pointer - and the texts ride
# behind the bank's u32 as {'LNGS' u32, len u32, bytes}. LONGS_BASE is now
# an on-disc pointer bias only: the loader allocates the actual buffer with
# the game's allocator and LOOKUP rebases those pointers. The old fixed
# destination overlapped the malloc arena (0x00200000..0x00248000), despite
# appearing untouched in short scene-save runs. Long play overwrote text
# allocations and the pool's own contents (issue #88, October 6 diagnostic).
# Key records (satkeys' search keys) keep their text in the region: KEYSEL's
# directory is region-relative. LONGS_IN_BANK=1 builds the old in-region way.
LONGS_BASE = 0x20201000
LONGS_MAX = 0x2F000       # up to 0x20230000
LONGS_CAPACITY = 0x8000  # Build rejects any bank that exceeds this reusable allocation.
XMALLOC = 0x060C4DA0
XFREE = 0x060C4E38
LNGS_MAGIC = 0x4C4E4753   # 'LNGS'
LONGS_IN_BANK = bool(os.environ.get("LONGS_IN_BANK"))
LABEL_MAX = 63            # the list-menu label table has 64-byte entries (strcpy)
# (pool word, original value, stub name)
HOOKS = [
    (0x060B835C, CONVERTER, "convf"),     # the two show-text sites free the line before (release_program)
    (0x060B84A0, CONVERTER, "convf"),
    (0x060B907C, CONVERTER, "conv"),      # this caller frees its own buffer (0x060B9068)
    (0x060C320C, STRLEN, "menu"),
    (0x060B93AC, LOAD_HELPER, "load"),
    (0x060B93B8, U32_READER, "u32"),
]


FREE_WRAP = 0x060C4F78   # free(p - 4): the converter's buffers come from the 0x060C4F3C wrapper; null is a no-op


def release_program(conv, prev):
    """The two show-text sites (0x060B82A8, 0x060B8390) convert each line into a fresh
    allocation and never free it - the Japanese game leaks one block per card shown
    (~66 bytes; ~78 with the English pair codes). The 0x48000-byte arena runs out after
    a few thousand cards of one session and the next conversions draw garbage, then the
    machine hangs (issue #88: garbled text deep into Act 2/3, cured by reset + load).
    The buffer is dead once its show-text call returns (the cells hold the text and the
    engine is synchronous), so this stub frees the previous line's buffer, converts the
    new one through `conv` (LOOKUP, then the converter) and keeps its pointer in `prev`
    (a word in the exec hole: MAIN_L reloads with it zero, and nothing else frees it)."""
    return [
        ("sts.l", "pr", "@-r15"),
        ("mov.l", "r4", "@-r15"),
        ("mov.l", f"=0x{prev:08x}", "r1"),
        ("mov.l", "@r1", "r4"),
        ("mov.l", f"=0x{FREE_WRAP:08x}", "r0"),
        ("jsr", "@r0"),
        ("nop",),
        ("mov.l", "@r15+", "r4"),
        ("mov.l", f"=0x{conv:08x}", "r0"),
        ("jsr", "@r0"),
        ("nop",),
        ("mov.l", f"=0x{prev:08x}", "r1"),
        ("mov.l", "r0", "@r1"),
        ("lds.l", "@r15+", "pr"),
        ("rts",),
        ("nop",),
        ("pool",),
    ]


def replacing_buffer_program():
    """Release the previous scene's pool, allocate len bytes, return its base."""
    return [
        ("sts.l", "pr", "@-r15"),
        ("mov.l", "r8", "@-r15"),
        ("mov", "r4", "r8"),
        ("mov.l", "=buffer", "r1"),
        ("mov.l", "@r1", "r4"),
        ("tst", "r4", "r4"),
        ("bt", "no_release"),                  # the game's free routine requires non-null
        ("mov.l", f"=0x{XFREE:08x}", "r0"),
        ("jsr", "@r0"),
        ("nop",),
        ("label", "no_release"),
        ("mov.l", f"=0x{XMALLOC:08x}", "r0"),
        ("jsr", "@r0"),
        ("mov", "r8", "r4"),
        ("mov.l", "=buffer", "r1"),
        ("mov.l", "r0", "@r1"),
        ("mov.l", "@r15+", "r8"),
        ("lds.l", "@r15+", "pr"),
        ("rts",),
        ("nop",),
        ("nop",),                              # 4-align the writable pointer
        ("label", "buffer"),
        (".long", 0),
        ("pool",),
    ]


def buffer_program():
    """Allocate once before heap fragmentation, then reuse the owned pool."""
    return [
        ("sts.l", "pr", "@-r15"),
        ("mov.l", "=buffer", "r1"),
        ("mov.l", "@r1", "r0"),
        ("tst", "r0", "r0"),
        ("bf", "done"),
        ("mov.l", f"=0x{LONGS_CAPACITY:08x}", "r4"),
        ("mov.l", f"=0x{XMALLOC:08x}", "r0"),
        ("jsr", "@r0"),
        ("nop",),
        ("mov.l", "=buffer", "r1"),
        ("mov.l", "r0", "@r1"),
        ("label", "done"),
        ("lds.l", "@r15+", "pr"),
        ("rts",),
        ("nop",),
        ("label", "buffer"),
        (".long", 0),
        ("pool",),
    ]


def stub_program(buffer_helper, buffer_var):
    return [
        # LOOKUP(r4 = pointer) -> r4 remapped on a hit; clobbers r0-r3, r5-r7
        ("label", "lookup"),
        ("mov.l", f"=0x{STRING_BASE_VAR:08x}", "r1"),
        ("mov.l", "@r1", "r1"),                 # r1 = region base
        ("mov", "r4", "r5"),
        ("sub", "r1", "r5"),                    # r5 = offset
        ("mov.l", f"=0x{WINDOW:08x}", "r0"),
        ("cmp/hs", "r0", "r5"),                 # T = offset >= 0x10000 (unsigned)
        ("bt", "miss"),
        ("mov.l", "=lenvar", "r2"),
        ("mov.l", "@r2", "r2"),                 # r2 = region length (the loader stub's record)
        ("mov", "#4", "r0"),
        ("cmp/hs", "r0", "r2"),                 # T = len >= 4
        ("bf", "miss"),
        ("mov", "r1", "r3"),
        ("add", "r2", "r3"),
        ("add", "#-4", "r3"),                   # r3 = base + len - 4 -> {magic, goff}
        ("mov.w", "@r3", "r0"),
        ("extu.w", "r0", "r0"),
        ("mov.l", f"=0x{MAGIC:08x}", "r6"),
        ("cmp/eq", "r6", "r0"),
        ("bf", "miss"),
        ("mov.w", "@(2,r3)", "r0"),
        ("extu.w", "r0", "r0"),                 # group offset
        ("mov", "r1", "r3"),
        ("add", "r0", "r3"),                    # r3 = group
        ("mov.w", "@r3+", "r7"),
        ("extu.w", "r7", "r7"),                 # count
        ("add", "#2", "r3"),                    # its pad: entries are 4-aligned
        ("label", "loop"),
        ("tst", "r7", "r7"),
        ("bt", "miss"),
        ("mov.w", "@r3+", "r0"),
        ("extu.w", "r0", "r0"),                 # old (region offset)
        ("add", "#2", "r3"),                    # pad
        ("mov.l", "@r3+", "r6"),                # new: the text's POINTER (any RAM)
        ("cmp/eq", "r5", "r0"),
        ("bt", "hit"),
        ("add", "#-1", "r7"),
        ("bra", "loop"),
        ("nop",),
        ("label", "hit"),
        ("cmp/hs", "r1", "r6"),                 # region-local keys keep their pointer
        ("bt", "hit_in_region"),
        ("mov.l", f"=0x{LONGS_BASE:08x}", "r0"),
        ("sub", "r0", "r6"),
        ("mov.l", f"=0x{buffer_var:08x}", "r0"),
        ("mov.l", "@r0", "r0"),
        ("add", "r0", "r6"),                   # pool offset -> allocator-owned pointer
        ("label", "hit_in_region"),
        ("mov", "r6", "r4"),                    # r4 = the pointer
        ("label", "miss"),
        ("rts",),
        ("nop",),
        # CONV: the three dialogue sites (r4 = base + off) -> the converter
        ("label", "conv"),
        ("sts.l", "pr", "@-r15"),
        ("mov.l", "=lookup", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("lds.l", "@r15+", "pr"),
        ("mov.l", f"=0x{CONVERTER:08x}", "r0"),
        ("jmp", "@r0"),
        ("nop",),
        # MENU: the list-menu item site (r4 = base + off, r8 = off) -> strlen
        ("label", "menu"),
        ("sts.l", "pr", "@-r15"),
        ("mov.l", "=lookup", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("lds.l", "@r15+", "pr"),
        ("mov.l", f"=0x{STRING_BASE_VAR:08x}", "r1"),
        ("mov.l", "@r1", "r1"),
        ("mov", "r4", "r8"),
        ("sub", "r1", "r8"),                    # r8 = new offset; the site adds the base after the call
        ("mov.l", f"=0x{STRLEN:08x}", "r0"),
        ("jmp", "@r0"),
        ("nop",),
        # LOAD: the scene loader's read helper (r4 handle, r5 dest, r6 size, r7 name)
        ("label", "load"),
        ("mov.l", f"=0x{STRING_BASE_VAR:08x}", "r1"),
        ("mov.l", "@r1", "r1"),
        ("cmp/eq", "r1", "r5"),
        ("bf", "skip"),
        ("mov.l", "=lenvar", "r2"),
        ("mov.l", "r6", "@r2"),                 # the string region's length
        ("label", "skip"),
        ("mov.l", f"=0x{LOAD_HELPER:08x}", "r0"),
        ("jmp", "@r0"),
        ("nop",),
        # U32: the loader's last read (r4 handle, r5 name) -> the u32, then the
        # bank's longs: {'LNGS', len, bytes} streamed into an owned allocation
        ("label", "u32"),
        ("sts.l", "pr", "@-r15"),
        ("mov.l", "r8", "@-r15"),
        ("mov.l", "r9", "@-r15"),
        ("mov.l", "r10", "@-r15"),
        ("mov.l", "r11", "@-r15"),
        ("mov", "r4", "r8"),                    # handle
        ("mov", "r5", "r9"),                    # name
        ("mov.l", f"=0x{U32_READER:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("mov", "r0", "r10"),                   # the game's u32
        # the marker {magic, len} as four u16 reads (bytes off the sector buffer;
        # the build keeps the 12-byte block inside the sector the strings read
        # fetched - a byte read cannot refill past the last sector, and the
        # block reader wedges the boot on a short read)
        ("mov", "r8", "r4"),
        ("mov", "r9", "r5"),
        ("mov.l", f"=0x{U16_READER:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("extu.w", "r0", "r0"),
        ("mov.l", f"=0x{LNGS_MAGIC >> 16:08x}", "r2"),
        ("cmp/eq", "r2", "r0"),
        ("bf", "u32done"),                      # no marker: an old bank, or none
        ("mov", "r8", "r4"),
        ("mov", "r9", "r5"),
        ("mov.l", f"=0x{U16_READER:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("extu.w", "r0", "r0"),
        ("mov.l", f"=0x{LNGS_MAGIC & 0xFFFF:08x}", "r2"),
        ("cmp/eq", "r2", "r0"),
        ("bf", "u32done"),
        ("mov", "r8", "r4"),
        ("mov", "r9", "r5"),
        ("mov.l", f"=0x{U16_READER:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("extu.w", "r0", "r11"),
        ("shll16", "r11"),                      # len, high half
        ("mov", "r8", "r4"),
        ("mov", "r9", "r5"),
        ("mov.l", f"=0x{U16_READER:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("extu.w", "r0", "r0"),
        ("or", "r0", "r11"),                    # len
        ("tst", "r11", "r11"),
        ("bt", "u32done"),                      # a marker with no text
        ("mov.l", f"=0x{buffer_helper:08x}", "r1"),
        ("jsr", "@r1"),
        ("mov", "r11", "r4"),
        ("mov", "r0", "r5"),
        ("mov", "r8", "r4"),
        ("mov", "r11", "r6"),
        ("mov", "r9", "r7"),
        ("mov.l", f"=0x{LOAD_HELPER:08x}", "r1"),
        ("jsr", "@r1"),                         # read(handle, allocated pool, len, name)
        ("nop",),
        ("label", "u32done"),
        ("mov", "r10", "r0"),
        ("mov.l", "@r15+", "r11"),
        ("mov.l", "@r15+", "r10"),
        ("mov.l", "@r15+", "r9"),
        ("mov.l", "@r15+", "r8"),
        ("lds.l", "@r15+", "pr"),
        ("rts",),
        ("nop",),
        ("label", "lenvar"),
        (".long", 0),
        ("pool",),
    ]


def read_table(exe):
    """All 639 chunk-table entries {(sector, bytes)} out of an exec image."""
    o = TABLE_ADDR - MAIN_BASE
    return [(s, w * 2) for s, w in struct.iter_unpack(">HH", exe[o:o + 4 * TABLE_N])]


def buffer_var_from_exec(exe):
    """Recognize this build's helper and writable pointer; old builds return None."""
    probe_base, helper_marker, var_marker = 0x06000000, 0x11223344, 0x55667788
    probe, labels = sh2asm.asm(stub_program(helper_marker, var_marker), probe_base)
    site = next(h[0] for h in HOOKS if h[2] == "conv")      # (the show-text sites go through convf first)
    conv = struct.unpack_from(">I", exe, site - MAIN_BASE)[0]
    start = conv - (labels["conv"] - probe_base)
    pos = start - MAIN_BASE + probe.index(struct.pack(">I", helper_marker))
    if not 0 <= pos <= len(exe) - 4:
        return None
    helper = struct.unpack_from(">I", exe, pos)[0]
    if not MAIN_BASE <= helper < MAIN_BASE + len(exe):
        return None
    off = helper - MAIN_BASE
    for program in (buffer_program(), replacing_buffer_program()):
        code, helper_labels = sh2asm.asm(program, helper)
        if exe[off:off + len(code)] == code:
            return helper_labels["buffer"]
    return None


def over_budget(rec, pf):
    """True when the record's `en` does not fit its slot through `pf` (satapply's test)."""
    return bool(rec.get("en")) and not rec.get("lock") and len(pf.encode(rec["en"])) + 1 > rec["budget"]


def long_jobs(pf=None):
    """{entry: [record]} for every unlocked record that gets a tail copy: one
    with a `long`, and (given the pair font) one whose `en` is over budget.
    Each record carries `text` = what the tail copy says and `why`."""
    jobs = {}
    for path in sorted(glob.glob(os.path.join(TR, "SAT_*.json"))):
        spec = json.load(open(path, encoding="utf-8"))
        L = []
        for r in spec["strings"]:
            if r.get("lock"):
                continue
            if r.get("long"):
                L.append(dict(r, text=r["long"], why="long"))
            elif pf is not None and over_budget(r, pf):
                L.append(dict(r, text=r["en"], why="over budget"))
        if L:
            jobs[spec["entry"]] = L
    return jobs


def pairs_used():
    """Every letter pair the `long` labels draw (satglyphs' ranking hook; the
    over-budget strings' pairs are ranked by the plan itself)."""
    import satglyphs
    out = []
    for L in long_jobs().values():
        for r in L:
            out += satglyphs.pairs_of(r["text"])
    return out


MARKER_BLOCK = 12         # {u32, 'LNGS', len}: byte reads cannot refill past the strings' last sector


def region_pad(w0, rlen):
    """Zero bytes to append to a region of `rlen` behind bytecode `w0` so the
    marker block behind the u32 stays inside one 2048-byte sector."""
    end = 4 + w0 + rlen
    if (end % SECTOR) + MARKER_BLOCK <= SECTOR:
        return 0
    return (SECTOR - end % SECTOR + 3) & ~3     # the block starts in the next sector


def grow_bank(bank, jobs, pf, log):
    """A bank's bytes with the remap group appended to its string region and
    the long texts behind the u32 as {'LNGS', len, bytes} (key records stay in
    the region). Returns (new bank bytes, [(old, pointer)], region length,
    longs bytes)."""
    w0, w1 = struct.unpack_from(">HH", bank, 0)
    region = bytearray(bank[4 + w0:4 + w0 + w1])
    tail = bank[4 + w0 + w1:]                   # the u32 the loader keeps (+ pad)
    assert len(tail) >= 4, "bank tail"
    if len(region) % 2:
        region.append(0)
    pairs = []
    longs = bytearray()
    for r in jobs:
        old = r["off"] - w0 - 4
        assert 0 <= old < w1, (r["off"], w0, w1)
        enc = pf.encode(r["text"]) + b"\0"
        if len(enc) - 1 > LABEL_MAX and len(r["text"]) <= 20:
            log(f"    WARNING: {r['text']!r} is {len(enc) - 1} bytes, over the 63-byte label copy")
        typed = all(ord(c) > 0xFF for c in r["text"])   # a typed target (puzzle answer): satkeys checks it in the region
        if LONGS_IN_BANK or r.get("key") or typed:
            new = len(region)
            region += enc
            ptr = STR_MIRROR + new
            where = f"{new:#06x}"
        else:
            ptr = LONGS_BASE + len(longs)
            longs += enc
            where = f"{ptr:#010x}"
        pairs.append((old, ptr))
        log(f"    off {r['off']:5d} (region {old:#06x}) -> {where}  {r['text']!r}"
            + ("" if r["why"] == "long" else f"  ({r['why']}: {len(enc)} > {r['budget']})"))
    if pairs:
        while len(region) % 4:
            region.append(0)
        gsize = 4 + 8 * len(pairs) + 4
        region += bytes(region_pad(w0, len(region) + gsize))
        goff = len(region)
        region += struct.pack(">HH", len(pairs), 0)
        for old, ptr in pairs:
            region += struct.pack(">HHI", old, 0, ptr)
        region += struct.pack(">HH", MAGIC, goff)
    else:
        region += bytes(region_pad(w0, len(region)))
    assert len(region) % 2 == 0 and len(region) < WINDOW - 0x1000, len(region)
    assert all(0 <= old < 0x10000 for old, _ in pairs)
    assert len(longs) <= LONGS_MAX, f"{len(longs)} B of longs exceed LONGS_MAX {LONGS_MAX}"
    out = (struct.pack(">HH", w0, len(region)) + bank[4:4 + w0] + bytes(region)
           + tail[:4] + struct.pack(">II", LNGS_MAGIC, len(longs)) + bytes(longs)
           + b"\0" * 4)       # slack: the chunk reader refuses a read that ends exactly at
    if len(out) % 2:          # the byte budget (B050/B0D0 streamed nothing, B000/B010 did)
        out += b"\0"
    return out, pairs, len(region), bytes(longs)


def place(entries, pristine, grown, data, log):
    """Put the grown banks into DATA.BIN: in place when the pristine sector
    slot holds them, else a slot another grown bank vacated (smallest that
    fits), else appended. Returns (data, {entry: (sector, size)}, appended sectors)."""
    slots = {}                                   # entry -> (sector, sectors) pristine
    for i, (off, size) in enumerate(pristine):
        nxt = pristine[i + 1][0] if i + 1 < len(pristine) else len(data)
        slots[i] = (off // SECTOR, (nxt - off) // SECTOR)
    need = {e: (len(b) + SECTOR - 1) // SECTOR for e, b in grown.items()}
    fits = {e for e in grown if need[e] <= slots[e][1]}
    moving = sorted((e for e in grown if e not in fits), key=lambda e: -need[e])
    free = sorted((slots[e] for e in moving), key=lambda s: s[1])   # vacated slots
    placed = {}
    for e in fits:
        placed[e] = slots[e][0]
    appended = 0
    end = len(data) // SECTOR
    for e in moving:
        pick = next((s for s in free if s[1] >= need[e]), None)
        if pick:
            free.remove(pick)
            placed[e] = pick[0]
            rest = (pick[0] + need[e], pick[1] - need[e])
            if rest[1] > 0:
                free.append(rest)
                free.sort(key=lambda s: s[1])
            log(f"  {e} {satdata.BANK_NAMES[e]}: {need[e]} sectors into the slot at {pick[0]} ({pick[1]} sectors)")
        else:
            placed[e] = end
            end += need[e]
            appended += need[e]
            log(f"  {e} {satdata.BANK_NAMES[e]}: {need[e]} sectors appended at {placed[e]}")
    data = bytearray(data)
    data += bytes(appended * SECTOR)
    for e, b in grown.items():
        sec = placed[e]
        room = need[e] * SECTOR
        data[sec * SECTOR:sec * SECTOR + room] = b + bytes(room - len(b))
    table = {e: (placed[e], len(b)) for e, b in grown.items()}
    return bytes(data), table, appended


def main(argv):
    dry = "--dry" in argv
    for p in (OUT_DATA, OUT_MAIN):
        if not os.path.exists(p):
            sys.exit(f"{p} missing: run satapply.py first")
    import satapply
    table = json.load(open(PAIR_TABLE))
    pf = satapply.SatPairFont(table)
    lines = []

    def log(m=""):
        print(m, flush=True)
        lines.append(m)

    data = open(OUT_DATA, "rb").read()
    exe = bytearray(open(OUT_MAIN, "rb").read())
    led = satexec.load_ledger(bytes(exe))       # before any edit: the ledger keys on the input's sha1
    entries = read_table(bytes(exe))
    pristine = satdata.read_table()             # the pristine layout: sector slots
    assert len(pristine) == TABLE_N
    for site, want, _ in HOOKS:
        have = struct.unpack_from(">I", exe, site - MAIN_BASE)[0]
        if have != want:
            sys.exit(f"pool word {site:#x} holds {have:#010x}, expected {want:#010x} - double apply or another patch")
    jobs = long_jobs(pf)
    n_over = sum(1 for L in jobs.values() for r in L if r["why"] == "over budget")
    ob = os.path.join(BUILD, "over_budget.txt")
    if os.path.exists(ob):                       # satapply's list of the same strings, from the same encoder
        listed = {(int(m.group(1)), int(m.group(2))) for m in
                  (re.match(r"(\d+) \S* ?off=(\d+) ", ln) for ln in open(ob, encoding="utf-8")) if m}
        ours = {(e, r["off"]) for e, L in jobs.items() for r in L if r["why"] == "over budget"}
        alljobs = {(e, r["off"]) for e, L in jobs.items() for r in L}
        # every over-budget string is a job (its own `long` or the en carried whole), and vice versa
        assert ours <= listed <= alljobs, f"over-budget set differs from satapply's: {sorted(ours ^ listed)[:10]}"
    grown, groups = {}, {}
    total = 0
    fb = 0
    longs_total = 0
    for e in range(21, 60):                      # the 39 banks
        jobs.setdefault(e, [])                   # every bank carries the marker
        sec, size = entries[e]
        bank = data[sec * SECTOR:sec * SECTOR + size]
        assert struct.unpack_from(">H", bank, 0)[0] == struct.unpack_from(">H", data, pristine[e][0])[0]
        no = sum(1 for r in jobs[e] if r["why"] == "over budget")
        log(f"{e} {satdata.BANK_NAMES[e]}: {len(jobs[e])} longs" + (f" ({no} over budget)" if no else ""))
        nb, pairs, rlen, lbytes = grow_bank(bank, jobs[e], pf, log)
        if len(lbytes) > LONGS_CAPACITY:
            raise ValueError(f"{satdata.BANK_NAMES[e]} needs {len(lbytes)} long-text bytes; "
                             f"increase LONGS_CAPACITY above {LONGS_CAPACITY}")
        longs_total += len(lbytes)
        if lbytes:
            log(f"  {len(lbytes)} B of longs at {LONGS_BASE:#x} (behind the u32)")
        grown[e] = nb
        groups[e] = pairs
        total += len(pairs)
        import satglyphs
        fb += sum(1 for r in jobs[e] for p in satglyphs.pairs_of(r["text"]) if p not in table)
        slot = pristine[e]
        nxt = pristine[e + 1][0] if e + 1 < TABLE_N else len(data)
        log(f"  {len(bank)} -> {len(nb)} bytes (region {rlen:#x}), slot {(nxt - slot[0]) // SECTOR} sectors"
            + ("" if len(nb) <= nxt - slot[0] else " - RELOCATES"))
    log()
    data, placed, appended = place(entries, pristine, grown, data, log)
    # the exec: chunk table entries, the stubs, the hooks
    for e, (sec, size) in placed.items():
        assert size % 2 == 0 and size // 2 < 0x10000 and sec < 0x10000
        struct.pack_into(">HH", exe, TABLE_ADDR - MAIN_BASE + 4 * e, sec, size // 2)
    # Keep the helper outside the crowded main exec hole. This uses the
    # same validated invalid-SJIS runs as the option-menu extension.
    import satoptmenu
    probe, _ = sh2asm.asm(buffer_program(), satoptmenu.SPARE_RUNS[0][0])
    buffer_addr = satoptmenu.alloc_spare(exe, len(probe))
    buffer_code, buffer_labels = sh2asm.asm(buffer_program(), buffer_addr)
    exe[buffer_addr - MAIN_BASE:buffer_addr - MAIN_BASE + len(buffer_code)] = buffer_code
    led["allocations"].append(dict(who="satlong-buffer (invalid-SJIS table entries)",
                                   start=buffer_addr, end=buffer_addr + len(buffer_code)))
    prog = stub_program(buffer_addr, buffer_labels["buffer"])
    probe, _ = sh2asm.asm(prog, satexec.HOLE_LO)   # size only
    addr = satexec.alloc(led, exe, "satlong", len(probe), align=4)
    code, labels = sh2asm.asm(prog, addr)
    exe[addr - MAIN_BASE:addr - MAIN_BASE + len(code)] = code
    # the show-text release stub: its word in the hole (the integrity checks skip the hole),
    # its code in a spare invalid-SJIS run like the buffer helper
    prev = satexec.alloc(led, exe, "satlong-prev", 4, align=4)
    probe, _ = sh2asm.asm(release_program(labels["conv"], prev), satoptmenu.SPARE_RUNS[0][0])
    rel_addr = satoptmenu.alloc_spare(exe, len(probe))
    rel_code, _ = sh2asm.asm(release_program(labels["conv"], prev), rel_addr)
    exe[rel_addr - MAIN_BASE:rel_addr - MAIN_BASE + len(rel_code)] = rel_code
    led["allocations"].append(dict(who="satlong-release (invalid-SJIS table entries)",
                                   start=rel_addr, end=rel_addr + len(rel_code)))
    labels = dict(labels, convf=rel_addr)
    for site, want, name in HOOKS:
        struct.pack_into(">I", exe, site - MAIN_BASE, labels[name])
    log(f"stubs: {len(code)} bytes at {addr:#x} (lookup {labels['lookup']:#x}, conv {labels['conv']:#x}, "
        f"menu {labels['menu']:#x}, load {labels['load']:#x}, lenvar {labels['lenvar']:#x}); "
        f"{len(HOOKS)} pool words retargeted")
    log(f"{total} longs in {len(grown)} banks ({n_over} of them over-budget `en` carried whole), "
        f"{fb} pair uses without a glyph slot; DATA.BIN {len(data)} bytes ({appended} sectors appended)")
    # read back: every group from the written data
    for e, pairs in groups.items():
        sec, size = placed[e]
        b = data[sec * SECTOR:sec * SECTOR + size]
        w0, w1 = struct.unpack_from(">HH", b, 0)
        region = b[4 + w0:4 + w0 + w1]
        if not pairs:
            continue                              # the marker alone: no group, no tail
        magic, goff = struct.unpack_from(">HH", region, w1 - 4)
        assert magic == MAGIC
        n = struct.unpack_from(">H", region, goff)[0]
        got = [(old, ptr) for old, _pad, ptr in struct.iter_unpack(">HHI", region[goff + 4:goff + 4 + 8 * n])]
        assert got == pairs, e
        tail = b[4 + w0 + w1:]
        lm, ll = struct.unpack_from(">II", tail, 4)
        assert lm == LNGS_MAGIC and 12 + ll <= len(tail), (e, lm, ll, len(tail))
        lbytes = tail[12:12 + ll]
        for old, ptr in pairs:
            if LONGS_BASE <= ptr < LONGS_BASE + LONGS_MAX:
                o = ptr - LONGS_BASE
                if b"\0" not in lbytes[o:]:
                    raise AssertionError(f"read back {e}: tail {len(tail)} B, marker {lm:#x} len {ll}, "
                                         f"pair {old:#x} -> +{o:#x}, lbytes {len(lbytes)}: {lbytes[o:o+16].hex()}")
                s = lbytes[o:lbytes.index(b"\0", o)]
            else:
                o = ptr - STR_MIRROR
                s = region[o:region.index(b"\0", o)]
            assert pf.encode(next(r["text"] for r in jobs[e] if r["off"] - w0 - 4 == old)) == s
    log("read back: every group and every long string decode from the written banks")
    os.makedirs(BUILD, exist_ok=True)
    if dry:
        log("dry run: nothing written")
    else:
        open(OUT_DATA, "wb").write(data)
        open(OUT_MAIN, "wb").write(bytes(exe))
        satexec.save_ledger(led, bytes(exe))
        json.dump({str(e): {"sector": s, "size": z} for e, (s, z) in placed.items()},
                  open(os.path.join(BUILD, "long_placement.json"), "w"), indent=1)
        log(f"wrote {OUT_DATA}, {OUT_MAIN}")
    with open(os.path.join(BUILD, "long_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(BUILD, "long_stubs.txt"), "w", encoding="utf-8") as f:
        f.write(sh2asm.check(code, addr) + "\n")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1:])
