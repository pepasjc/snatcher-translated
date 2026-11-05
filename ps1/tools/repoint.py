"""Give strings more room than their slots allow, without touching bytecode.

Strings are referenced from bytecode as word indices, but those references
take several forms (dialogue words, menu items with flag bits in the top two
bits, counted menu lists), and the bytecode grammar is variable-length with
length-prefixed blocks. Scanning for references corrupted a scene once —
missed the flagged menu forms, and patched false positives inside operands.

So the bytecode is never modified. Instead every reference is redirected at
runtime. All string display funnels through exactly three places that compute
`address = string_base + offset` (string_base is the global 0x800AB5A4, and
these are the only reads of it in the executable):

    0x80043790  dialogue resolver          (offset in $s0, base+off in $a0)
    0x8003DF5C  display-string variant A   (base in $v0,   base+off in $a0)
    0x8003E000  display-string variant B   (offset in $a1, base+off in $a0)

Each site's `jal` to the shared measure/copy helper is retargeted to a small
stub (0x8009E330) that looks up (bank, offset) in a remap group and, on a hit,
swaps in the address of the relocated string before tail-calling the original
helper. The bank key is the bank's header halfword (read at [0x800ABFF0] - 4),
and offsets are compared bank-absolute (B040 runs two string bases). One
instruction changes per site; everything else is data.

A bank's group is entries [old u16][pad u16][new u32] - `new` an absolute
pointer - and the group and the bank's long texts are written to
work/longs/<S>.bin, which subs_cue.py ships as LONGS_<S>.BIN: a second CD read
after the subtitle payload puts it in high RAM (lib/hiram.LONGS,
0x801E1000..0x801EC000), so a long costs the bank nothing. B050 (resident) and
a bank with no cue file keep their group and longs in the bank tail. The
executable keeps the stub and a directory [bank key][group pointer]... in the
zero region at 0x8009F628 (file 0x77E28). The larger zero region at
0x800A009C is runtime-written - do not use it.

Long text goes in a `"long"` field beside `"en"` in ps1/translation/*.json. `en`
stays the short form so apply_translation.py and verify_build.py are
unchanged. This runs after apply_translation.py (which rebuilds patched files
from pristine sources, discarding previous runs of this script):

    python repoint.py            # apply
    python repoint.py --dry      # report only
"""
import glob, json, os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from pairfont import PairFont

OUT = os.path.join(ROOT, "patched")
EXE = os.path.join(OUT, "SLPS_001.54")

EXE_BASE = 0x80028000          # ram = file - 0x800 + EXE_BASE (PS-EXE header t_addr)
SCENE_TABLE = 0x4A68C          # 39 x {LBA, size, pad}; index = ISZ number / 0x10

STUB_RAM = 0x8009E330          # zero region for the stub code (514 bytes)
STUB_LEN = 0x200
TABLE_RAM = 0x8009F628         # zero region for the bank directory (1016 bytes)
BANK_RAM = 0x8010D000          # every scene bank loads here (B050 is resident higher)
RESIDENT_RAM = {"ISZ_B050": 0x80118000}
# Long strings leave the bank (longs-poc, 2026-09-18): each bank's remap
# group and encoded longs are written to work/longs/<S>.bin, laid out for
# hiram.LONGS; subs_cue.py on <S> ships it as LONGS_<S>.BIN, which the loader
# hook reads right after the subtitle payload. The bank is untouched: the
# exec directory points at the group in LONGS. Banks with no cue file, and
# the resident B050, keep their longs in the bank as before. LONGS_IN_BANK=1
# builds the old way.
from hiram import LONGS, LONGS_MAX      # lib/hiram.py: the longs blob's home
LONGS_DIR = os.path.join(ROOT, "work", "longs")
LONGS_MAP = os.path.join(ROOT, "work", "longs.json")
LONGS_IN_BANK = bool(os.environ.get("LONGS_IN_BANK"))
TABLE_LEN = 0x3F8
MEASURE = 0x80058624           # helper tail-called by the dialogue resolver
COPYSTR = 0x8004582C           # helper tail-called by the display variants

# --- keyboard max-length clamp ---
# The typed-input field length is a per-puzzle nibble from the scene script
# (config word 0x80011B28 bits 4-7), sized for the kana answers: Napoleon's
# password gives 4 cells, which no English answer fits. The single writer of
# the max-length byte 0x80011D9D is the sb in the delay slot at 0x8004E77C;
# its jal is retargeted to a mini-stub that raises the stored value to at
# least KEYLEN_MIN. The name search (11) and the dial pad pass unchanged.
KEYLEN_RAM = 0x8009E204        # zero region, 176 bytes, zero in savestates
KEYLEN_LEN = 0xB0
KEYLEN_HOOK = 0x8004E778       # jal 0x800585E4 with the sb in its delay slot
KEYLEN_HELPER = 0x800585E4
KEYLEN_BYTE = 0x80011D9D       # keyboard struct +0x19: max input length
KEYLEN_MIN = 8                 # longest fullwidth answer (MEMORIAL, TOGETHER)
# The field's place on screen (GitHub #35). The reposition pass at
# 0x8004E864 keys a base x on the SAME nibble: 2-4 -> 0x34, 5 -> 0x38,
# anything else -> 0; the field sprite (ctx+0x29F0) goes to base+0x1C, the
# cell sprites (ctx+0x2A30.., created 14 px wide at boot, 0x800466C0) to
# base+0x20+16*i, the letter row sprites (ctx+0x2CF0..) to base+0x22+16*i,
# and the field is sized to maxlen*16+8 later (0x8004EA5C). So the 4-kana
# videophone field sat centred on the TV picture (x 80..152 over a picture
# at 56..176) and the clamped 8-cell one ran from 80 to 216, over the
# keypad. Three stubs, each on a jal in that code and tail-calling its
# callee, apply only while the clamp has added cells (max length m >
# nibble n):
#   KEYPOS  (0x8004E8F0, the first call after the switch; $v1 = n, $s2 =
#           the base) moves the base left by 8(m-n) - m, so the field keeps
#           the centre the designers chose at the tighter pitch below;
#   KEYCELL (0x8004E944 the cell, 0x8004E964 the letter; $s1 = i, $s6 =
#           ctx+0x1AC0) closes the pitch to 14 (12-px cells, 2-px gaps: the
#           cell is resized after it is placed, and the letter - drawn 2 px
#           into a 14-px cell - goes to the cell's x); unclamped, the cell
#           is set back to 14 wide - the width is a boot-time constant the
#           keyboard code never touches;
#   KEYWIDTH (0x8004EA60; $s1 = ctx) sizes the field to 14m + 8.
# 8 cells: 56..176 on the videophone (nibble 4), exactly the picture;
# 68..188 on the hospital list and the BENSON cipher (nibble 5). Base-0
# layouts (the 11-letter name search, never clamped) pass untouched.
# There are TWO input structs - 0x1D84 (max len at 0x1D9D) and a second at
# 0x1DA4 (max len at 0x1DB1, filled by the variant at 0x8004FC54,
# unclamped) - and an earlier try that rewrote the switch itself broke the
# phone screen (typed letters at the dial number display, the TV bezel
# gone); the stubs touch only the registers named. They live in dead font
# slots (pairfont.RESERVED; a slot address is 0x80074380 + 18*slot, and an
# even slot is word-aligned).
KEYPOS_HOOK = 0x8004E8F0       # jal 0x80032D9C (show the field frame)
KEYPOS_HELPER = 0x80032D9C
KEYCELL_HOOKS = (0x8004E944, 0x8004E964)   # jal 0x80033560 (place the cell / the letter)
KEYCELL_HELPER = 0x80033560
KEYCELL_RESIZE = 0x80033A18    # absolute size(obj, w, h, 1)
KEYWIDTH_HOOK = 0x8004EA60     # jal 0x80033A18 (size the field)
KEYWIDTH_HELPER = 0x80033A18
KEYPOS_SLOTS = (1550, 1554)    # KEYPOS + KEYWIDTH, 90 bytes
KEYCELL_SLOTS = (1564, 1570)   # KEYCELL, 126 bytes
KEYPOS_RAM = 0x80074380 + 18 * KEYPOS_SLOTS[0]
KEYPOS_LEN = 18 * (KEYPOS_SLOTS[1] - KEYPOS_SLOTS[0] + 1)
KEYCELL_RAM = 0x80074380 + 18 * KEYCELL_SLOTS[0]
KEYCELL_LEN = 18 * (KEYCELL_SLOTS[1] - KEYCELL_SLOTS[0] + 1)

# (site of the jal to retarget, expected original word, stub entry name)
HOOKS = [
    (0x800437A8, 0x0C000000 | ((MEASURE >> 2) & 0x03FFFFFF), "A"),
    (0x8003DF7C, 0x0C000000 | ((COPYSTR >> 2) & 0x03FFFFFF), "B"),
    (0x8003E024, 0x0C000000 | ((COPYSTR >> 2) & 0x03FFFFFF), "C"),
]

BYTECODE_BASE_GLOBAL = (0x800B, -0x4010)      # lui/lw pair for [0x800ABFF0]


def fo(ram):
    return ram - EXE_BASE + 0x800


def scene_index(scene):
    return int(scene[len("ISZ_B"):], 16) // 0x10


# --- a tiny MIPS assembler, just enough for the stubs ---

REG = {f"$t{i}": 8 + i for i in range(8)}
REG.update({"$zero": 0, "$at": 1, "$v0": 2, "$v1": 3, "$a0": 4, "$a1": 5,
            "$a2": 6, "$a3": 7, "$s0": 16, "$s1": 17, "$s2": 18, "$s6": 22,
            "$sp": 29, "$ra": 31})


def asm(prog, org):
    """Two-pass assembly of [(op, args...)] tuples. Branch targets are labels."""
    labels, pc = {}, org
    for ins in prog:
        if ins[0] == "label":
            labels[ins[1]] = pc
        else:
            pc += 4
    out, pc = bytearray(), org
    for ins in prog:
        op = ins[0]
        if op == "label":
            continue
        if op == "lui":
            w = 0x3C000000 | REG[ins[1]] << 16 | (ins[2] & 0xFFFF)
        elif op == "ori":
            w = 0x34000000 | REG[ins[2]] << 21 | REG[ins[1]] << 16 | (ins[3] & 0xFFFF)
        elif op == "addiu":
            w = 0x24000000 | REG[ins[2]] << 21 | REG[ins[1]] << 16 | (ins[3] & 0xFFFF)
        elif op == "lw":
            w = 0x8C000000 | REG[ins[3]] << 21 | REG[ins[1]] << 16 | (ins[2] & 0xFFFF)
        elif op == "lhu":
            w = 0x94000000 | REG[ins[3]] << 21 | REG[ins[1]] << 16 | (ins[2] & 0xFFFF)
        elif op == "lbu":
            w = 0x90000000 | REG[ins[3]] << 21 | REG[ins[1]] << 16 | (ins[2] & 0xFFFF)
        elif op == "sb":
            w = 0xA0000000 | REG[ins[3]] << 21 | REG[ins[1]] << 16 | (ins[2] & 0xFFFF)
        elif op == "sw":
            w = 0xAC000000 | REG[ins[3]] << 21 | REG[ins[1]] << 16 | (ins[2] & 0xFFFF)
        elif op == "andi":
            w = 0x30000000 | REG[ins[2]] << 21 | REG[ins[1]] << 16 | (ins[3] & 0xFFFF)
        elif op == "sltu":
            w = 0x2B | REG[ins[2]] << 21 | REG[ins[3]] << 16 | REG[ins[1]] << 11
        elif op == "move":
            w = 0x21 | REG[ins[2]] << 21 | REG[ins[1]] << 11          # addu rd, rs, $zero
        elif op == "mult":
            w = 0x18 | REG[ins[1]] << 21 | REG[ins[2]] << 16   # lo = rs * rt
        elif op == "mflo":
            w = 0x12 | REG[ins[1]] << 11
        elif op == "jal":
            w = 0x0C000000 | ((ins[1] >> 2) & 0x03FFFFFF)
        elif op == "jr":
            w = 0x08 | REG[ins[1]] << 21
        elif op == "slti":
            w = 0x28000000 | REG[ins[2]] << 21 | REG[ins[1]] << 16 | (ins[3] & 0xFFFF)
        elif op == "subu":
            w = 0x23 | REG[ins[2]] << 21 | REG[ins[3]] << 16 | REG[ins[1]] << 11
        elif op == "addu":
            w = 0x21 | REG[ins[2]] << 21 | REG[ins[3]] << 16 | REG[ins[1]] << 11
        elif op in ("beq", "bne"):
            rel = (labels[ins[3]] - (pc + 4)) >> 2
            w = (0x10000000 if op == "beq" else 0x14000000) \
                | REG[ins[1]] << 21 | REG[ins[2]] << 16 | (rel & 0xFFFF)
        elif op == "b":
            rel = (labels[ins[1]] - (pc + 4)) >> 2
            w = 0x10000000 | (rel & 0xFFFF)
        elif op == "j":
            w = 0x08000000 | ((ins[1] >> 2) & 0x03FFFFFF)
        elif op == "sll":
            w = REG[ins[2]] << 16 | REG[ins[1]] << 11 | (ins[3] & 0x1F) << 6
        elif op == "srl":
            w = 2 | REG[ins[2]] << 16 | REG[ins[1]] << 11 | (ins[3] & 0x1F) << 6
        elif op == "nop":
            w = 0
        else:
            raise ValueError(op)
        out += struct.pack("<I", w)
        pc += 4
    return bytes(out)


def stub_program(table_ram):
    """One shared lookup body with three entry points.

    Entry A (dialogue resolver): $s0 = offset, $a0 = base+offset. On a hit the
    offset in $s0 is swapped and $a0 rebuilt; tail-calls MEASURE.
    Entries B and C (display variants): recover base and offset from the
    registers each site guarantees; on a hit $a0 is rebuilt; tail-call COPYSTR.

    The directory in the exec is [key][group offset] pairs terminated by key
    0xFFFF, where key is the bank's first two bytes (its BE16 string-region
    offset, read as a little-endian halfword) and the group offset is a file
    offset in the bank; the group is [count] then count x [old][new] with
    BANK-ABSOLUTE offsets. The request is turned absolute too
    ($t0 + $t1 - bank), so a bank that runs with more than one string base
    (B040: its header base for the key table and 0x1585 for dialogue -
    which is also B030's sbase) resolves against its own group only; keying
    on the current string base sent B040's dialogue lookups to "B030's"
    group at an address past B040's end, and once the first search had
    filled that memory the garbage count ran the scan into false hits.
    Bank base in $t2, string base in $t0, mode flag in $t7. R3000 load-delay
    slots are respected throughout.
    """
    g_hi, g_lo = BYTECODE_BASE_GLOBAL
    t_hi = ((table_ram >> 16) + (1 if table_ram & 0x8000 else 0)) & 0xFFFF
    t_lo = table_ram & 0xFFFF
    return [
        ("label", "entry_A"),
        ("subu", "$t0", "$a0", "$s0"),          # $t0 = string base
        ("addu", "$t1", "$s0", "$zero"),        # $t1 = offset
        ("b", "body"),
        ("ori", "$t7", "$zero", 1),             # delay: mode A
        ("label", "entry_B"),
        ("subu", "$t1", "$a0", "$v0"),
        ("addu", "$t0", "$v0", "$zero"),
        ("b", "body"),
        ("ori", "$t7", "$zero", 2),             # delay: mode B/C
        ("label", "entry_C"),
        ("subu", "$t0", "$a0", "$a1"),
        ("addu", "$t1", "$a1", "$zero"),
        ("ori", "$t7", "$zero", 2),

        ("label", "body"),
        ("lui", "$t2", g_hi),
        ("lw", "$t2", g_lo, "$t2"),             # bytecode base = bank + 4
        ("lui", "$t3", t_hi),
        ("addiu", "$t3", "$t3", t_lo),          # directory
        ("srl", "$t4", "$t2", 24),
        ("addiu", "$t4", "$t4", -0x80),         # not a RAM pointer: no bank loaded
        ("bne", "$t4", "$zero", "finish"),
        ("addiu", "$t2", "$t2", -4),            # delay: $t2 = bank base
        ("lhu", "$t4", 0, "$t2"),               # bank key: header halfword
        ("addu", "$t1", "$t0", "$t1"),          # (fills the load delay)
        ("subu", "$t1", "$t1", "$t2"),          # $t1 = request, bank-absolute

        ("label", "bankloop"),
        ("lhu", "$t5", 0, "$t3"),               # directory: bank key
        ("ori", "$t6", "$zero", 0xFFFF),
        ("beq", "$t5", "$t6", "finish"),
        ("lw", "$t6", 4, "$t3"),                # delay: the group's POINTER (any RAM)
        ("beq", "$t5", "$t4", "found"),
        ("addiu", "$t3", "$t3", 8),             # delay: next directory entry
        ("b", "bankloop"),
        ("nop",),

        ("label", "found"),
        ("addu", "$t3", "$t6", "$zero"),        # the group ($t6 settled)
        ("lhu", "$t5", 0, "$t3"),               # entry count
        ("nop",),                               # load delay
        ("beq", "$t5", "$zero", "finish"),
        ("addiu", "$t3", "$t3", 4),             # delay: past the count word
        ("label", "scanloop"),
        ("lhu", "$t4", 0, "$t3"),               # old offset (bank-absolute)
        ("addiu", "$t5", "$t5", -1),
        ("bne", "$t4", "$t1", "scannext"),
        ("lw", "$t6", 4, "$t3"),                # delay: the target POINTER (any RAM)
        ("ori", "$t4", "$zero", 1),             # (fills the load delay)
        ("bne", "$t7", "$t4", "hit_bc"),
        ("nop",),
        ("b", "finish"),
        ("subu", "$s0", "$t6", "$t0"),          # delay: mode A: base + $s0 = target
        ("label", "hit_bc"),
        ("b", "finish"),
        ("addu", "$a0", "$t6", "$zero"),        # delay: the pointer itself
        ("label", "scannext"),
        ("bne", "$t5", "$zero", "scanloop"),
        ("addiu", "$t3", "$t3", 8),

        ("label", "finish"),
        ("ori", "$t4", "$zero", 1),
        ("bne", "$t7", "$t4", "fin_bc"),
        ("nop",),
        ("addu", "$a0", "$t0", "$s0"),          # A: rebuild (no-op on miss)
        ("j", MEASURE),
        ("nop",),
        ("label", "fin_bc"),
        ("j", COPYSTR),
        ("nop",),
    ]


def keylen_program():
    """Raise the keyboard max-length byte to KEYLEN_MIN after the hooked
    site's delay-slot sb has stored the script's value, then continue into
    the original helper. R3000 load delay respected."""
    hi = ((KEYLEN_BYTE >> 16) + (1 if KEYLEN_BYTE & 0x8000 else 0)) & 0xFFFF
    lo = KEYLEN_BYTE & 0xFFFF
    return [
        ("lui", "$t0", hi),
        ("lbu", "$t1", lo, "$t0"),
        ("ori", "$t3", "$zero", KEYLEN_MIN),    # fills the load delay
        ("slti", "$t2", "$t1", KEYLEN_MIN),
        ("beq", "$t2", "$zero", "keep"),
        ("nop",),
        ("sb", "$t3", lo, "$t0"),
        ("label", "keep"),
        ("j", KEYLEN_HELPER),
        ("nop",),
    ]


def keypos_program():
    """KEYPOS then KEYWIDTH, back to back (see the notes above KEYPOS_HOOK).
    Returns (code list, {label: offset}). R3000 load delays respected; every
    branch delay slot is harmless on both paths."""
    return [
        # KEYPOS: $s0 = ctx, $v1 = n, $s2 = base
        ("label", "keypos"),
        ("lbu", "$t0", KEYLEN_BYTE & 0xFFFF, "$s0"),   # m, the clamped max length
        ("beq", "$s2", "$zero", "pos_done"),           # base-0 layout: untouched
        ("nop",),                                      # (also the load delay)
        ("subu", "$t1", "$t0", "$v1"),                 # m - n
        ("beq", "$t1", "$zero", "pos_done"),
        ("sll", "$t1", "$t1", 3),                      # 8(m - n)
        ("subu", "$t1", "$t1", "$t0"),                 # (16n+8)/2 - (14m+8)/2
        ("subu", "$s2", "$s2", "$t1"),                 # base -= 8(m-n) - m
        ("label", "pos_done"),
        ("j", KEYPOS_HELPER),
        ("nop",),
        # KEYWIDTH: $s1 = ctx, $a1 = 16m + 8
        ("label", "keywidth"),
        ("lw", "$t1", 0x1B28, "$s1"),                  # the config word
        ("lbu", "$t0", KEYLEN_BYTE & 0xFFFF, "$s1"),   # m
        ("srl", "$t1", "$t1", 4),
        ("andi", "$t1", "$t1", 0xF),                   # n
        ("subu", "$t1", "$t0", "$t1"),
        ("beq", "$t1", "$zero", "width_done"),
        ("sll", "$t2", "$t0", 1),                      # 2m
        ("subu", "$a1", "$a1", "$t2"),                 # 14m + 8
        ("label", "width_done"),
        ("j", KEYWIDTH_HELPER),
        ("nop",),
    ]


def keycell_program():
    """KEYCELL, both loop sites. $s1 = i, $s6 = ctx+0x1AC0, $a0 = the
    sprite, $a1 = its x. The cell site (ra = KEYCELL_HOOKS[0] + 8) places
    the cell and then sets its width, 12 clamped / 14 not - a real frame:
    this runs in the keyboard task's own step, not a callback."""
    cell_ra = KEYCELL_HOOKS[0] + 8
    return [
        ("lw", "$t1", 0x1B28 - 0x1AC0, "$s6"),         # the config word
        ("lbu", "$t0", (KEYLEN_BYTE & 0xFFFF) - 0x1AC0, "$s6"),   # m
        ("srl", "$t1", "$t1", 4),
        ("andi", "$t1", "$t1", 0xF),                   # n
        ("subu", "$t0", "$t0", "$t1"),                 # m - n
        ("sltu", "$t4", "$zero", "$t0"),               # clamped: 1 / 0
        ("sll", "$t4", "$t4", 1),                      # 2 or 0
        ("mult", "$t4", "$s1"),
        ("mflo", "$t2"),                               # 2i or 0
        ("lui", "$t3", cell_ra >> 16),
        ("ori", "$t3", "$t3", cell_ra & 0xFFFF),
        ("bne", "$ra", "$t3", "letter"),
        ("subu", "$a1", "$a1", "$t2"),                 # x at the tighter pitch
        # the cell: place it, then size it
        ("addiu", "$sp", "$sp", -0x18),
        ("sw", "$ra", 0x14, "$sp"),
        ("sw", "$a0", 0x10, "$sp"),
        ("jal", KEYCELL_HELPER),
        ("sw", "$t4", 0x0C, "$sp"),
        ("lw", "$a0", 0x10, "$sp"),
        ("lw", "$t4", 0x0C, "$sp"),
        ("ori", "$a1", "$zero", 14),
        ("subu", "$a1", "$a1", "$t4"),                 # 14 wide, or 12
        ("move", "$a2", "$zero"),
        ("jal", KEYCELL_RESIZE),
        ("ori", "$a3", "$zero", 1),
        ("lw", "$ra", 0x14, "$sp"),
        ("nop",),
        ("jr", "$ra"),
        ("addiu", "$sp", "$sp", 0x18),
        # the letter: drawn 2 px into the cell in the game's layout
        ("label", "letter"),
        ("j", KEYCELL_HELPER),
        ("subu", "$a1", "$a1", "$t4"),
    ]


def labels_of(prog, org):
    out, pc = {}, org
    for ins in prog:
        if ins[0] == "label":
            out[ins[1]] = pc
        else:
            pc += 4
    return out


def keyfield_patches():
    """[(ram, bytes)] for the three field stubs and their four hook words."""
    kp = keypos_program(); kl = labels_of(kp, KEYPOS_RAM)
    pcode = asm(kp, KEYPOS_RAM); ccode = asm(keycell_program(), KEYCELL_RAM)
    assert len(pcode) <= KEYPOS_LEN, (len(pcode), KEYPOS_LEN)
    assert len(ccode) <= KEYCELL_LEN, (len(ccode), KEYCELL_LEN)
    jal = lambda t: struct.pack("<I", 0x0C000000 | ((t >> 2) & 0x03FFFFFF))
    return [(KEYPOS_RAM, pcode), (KEYCELL_RAM, ccode),
            (KEYPOS_HOOK, jal(kl["keypos"])), (KEYWIDTH_HOOK, jal(kl["keywidth"])),
            (KEYCELL_HOOKS[0], jal(KEYCELL_RAM)), (KEYCELL_HOOKS[1], jal(KEYCELL_RAM))]


def build_group(pairs):
    """A bank's remap group: [count u16][pad] + count x [old u16][pad][new
    u32]. `old` is the bank-absolute file offset of the referenced string,
    `new` the RAM address of the text that replaces it - in the bank
    (BANK_RAM + offset) or anywhere else the loader put it (the SUBS blob in
    HIRAM, see LONGS_TOP). The group starts on a 4-byte boundary."""
    g = struct.pack("<HH", len(pairs), 0)
    for old, new in pairs:
        g += struct.pack("<HHI", old, 0, new)
    return g


def build_directory(groups):
    """The exec-side directory: [bank key u16][pad][group pointer u32] per
    bank, 0xFFFF end. The key is the bank's first halfword read
    little-endian; the pointer is the group's RAM address - in the bank, or
    in HIRAM in front of the bank's longs."""
    d = bytearray()
    for key, ptr in sorted(groups.items()):
        d += struct.pack("<HHI", key, 0, ptr)
    d += struct.pack("<H", 0xFFFF)
    return bytes(d)


def build_patch(groups, count, dry=False):
    """groups: {bank key: file offset of the group}; count for the report."""
    exe = bytearray(open(EXE, "rb").read())

    for ram, ln, what in ((STUB_RAM, STUB_LEN, "stub"), (TABLE_RAM, TABLE_LEN, "table"),
                          (KEYLEN_RAM, KEYLEN_LEN, "keylen stub")):
        if any(exe[fo(ram):fo(ram) + ln]) and not dry:
            raise SystemExit(f"{what} region {ram:#x} is not zero — "
                             "wrong exec or double apply")
    # (the field stubs live in dead font slots, which hold a glyph, not
    # zeros: the guard there is the RESERVED list)
    from pairfont import RESERVED
    for slots in (KEYPOS_SLOTS, KEYCELL_SLOTS):
        if not any(a <= slots[0] and slots[1] <= b for a, b in RESERVED):
            raise SystemExit(f"field stub slots {slots} are not in pairfont.RESERVED")
    jal_of = lambda t: 0x0C000000 | ((t >> 2) & 0x03FFFFFF)
    for site, want, _ in HOOKS + [(KEYLEN_HOOK, jal_of(KEYLEN_HELPER), "keylen"),
                                  (KEYPOS_HOOK, jal_of(KEYPOS_HELPER), "keypos"),
                                  (KEYWIDTH_HOOK, jal_of(KEYWIDTH_HELPER), "keywidth"),
                                  (KEYCELL_HOOKS[0], jal_of(KEYCELL_HELPER), "keycell"),
                                  (KEYCELL_HOOKS[1], jal_of(KEYCELL_HELPER), "keycell")]:
        have = struct.unpack_from("<I", exe, fo(site))[0]
        if have != want:
            raise SystemExit(f"hook site {site:#x} holds {have:#010x}, "
                             f"expected {want:#010x} — exec layout changed?")

    prog = stub_program(TABLE_RAM)
    code = asm(prog, STUB_RAM)
    labels, pc = {}, STUB_RAM
    for ins in prog:
        if ins[0] == "label":
            labels[ins[1]] = pc
        else:
            pc += 4
    t1 = build_directory(groups)
    if len(code) > STUB_LEN:
        raise SystemExit(f"stub is {len(code)} bytes, region holds {STUB_LEN}")
    if len(t1) > TABLE_LEN:
        raise SystemExit(f"directory is {len(t1)} bytes, region holds {TABLE_LEN}")

    if dry:
        print(f"  exec: {count} remap entries in {len(groups)} banks, "
              f"stub {len(code)}B, directory {len(t1)}B")
        return

    exe[fo(STUB_RAM):fo(STUB_RAM) + len(code)] = code
    exe[fo(TABLE_RAM):fo(TABLE_RAM) + len(t1)] = t1
    for site, _, name in HOOKS:
        entry = labels[f"entry_{name}"]
        struct.pack_into("<I", exe, fo(site),
                         0x0C000000 | ((entry >> 2) & 0x03FFFFFF))
    kcode = asm(keylen_program(), KEYLEN_RAM)
    assert len(kcode) <= KEYLEN_LEN
    exe[fo(KEYLEN_RAM):fo(KEYLEN_RAM) + len(kcode)] = kcode
    struct.pack_into("<I", exe, fo(KEYLEN_HOOK),
                     0x0C000000 | ((KEYLEN_RAM >> 2) & 0x03FFFFFF))
    for ram, data in keyfield_patches():
        exe[fo(ram):fo(ram) + len(data)] = data
    open(EXE, "wb").write(exe)
    print(f"  exec: {count} remap entries in {len(groups)} banks, stub {len(code)}B, "
          f"directory {len(t1)}B at {TABLE_RAM:#x}, "
          f"keylen clamp {len(kcode)}B at {KEYLEN_RAM:#x} (min {KEYLEN_MIN}), "
          f"field layout stubs at {KEYPOS_RAM:#x} and {KEYCELL_RAM:#x}")


def collect(extra, dry=False):
    """Append every bank's long strings and its remap group. `extra` holds
    remaps that come from elsewhere ({scene: [(old, new)]} as bank file
    offsets - keytable's evicted dialogue). Returns ({bank key: group file
    offset}, count, overflow)."""
    pf = PairFont()
    known = set(pf.table)                        # a long may not mint a pair: its glyph
    groups, total = {}, 0                        # would never reach the exec (see below)
    overflow = []
    relp = os.path.join(ROOT, "work", "relocations.json")
    already = set(json.load(open(relp))) if os.path.exists(relp) else set()
    for path in sorted(glob.glob(os.path.join(ROOT, "ps1/translation", "ISZ_*.json"))):
        scene = os.path.basename(path)[:-5]
        spec = json.load(open(path, encoding="utf-8"))
        jobs = [(i, e) for i, e in enumerate(spec["strings"])
                if e.get("long") and not e.get("lock")]
        pairs = list(extra.get(scene, []))
        if not jobs and not pairs:
            continue
        bank_path = os.path.join(OUT, scene + ".BIN")
        d = bytearray(open(bank_path, "rb").read())
        sbase = struct.unpack_from(">H", d, 0)[0]
        key = struct.unpack_from("<H", d, 0)[0]     # what the stub's lhu reads
        orig_len = len(d)
        capacity = ((orig_len + 2047) // 2048) * 2048
        bank_ram = RESIDENT_RAM.get(scene, BANK_RAM)
        pairs = [(old, bank_ram + new) for old, new in pairs]   # keytable's: in-bank
        out_of_bank = (not LONGS_IN_BANK and scene not in RESIDENT_RAM
                       and os.path.exists(os.path.join(ROOT, "ps1/translation", f"subs_{scene[4:]}.json")))
        print(f"{scene}: sbase {sbase:#06x}" + ("  (longs -> HIRAM)" if out_of_bank else ""))
        if out_of_bank:
            text = bytearray()
            offs = []
            for i, e in jobs:
                offs.append(len(text))
                text += pf.encode(e["long"]) + b"\x00"
            gsize = 4 + 8 * (len(jobs) + len(pairs))       # the group, then the text
            gsize += -gsize % 4
            base = LONGS
            if gsize + len(text) > LONGS_MAX:
                raise SystemExit(f"{scene}: {gsize + len(text)} B of group + longs exceed LONGS_MAX "
                                 f"{LONGS_MAX} by {gsize + len(text) - LONGS_MAX} B")
            for (i, e), o in zip(jobs, offs):
                if not 0 <= e["off"] <= 0xFFFF:
                    raise SystemExit(f"{scene} idx {i}: offset out of 16-bit range")
                pairs.append((e["off"], base + gsize + o))
                print(f"  idx {i:4d} {e['long']!r:24s} file {e['off']:#06x} -> "
                      f"{base + gsize + o:#010x}")
            g = build_group(pairs)
            blob = g + b"\x00" * (gsize - len(g)) + text
            groups[key] = base
            os.makedirs(LONGS_DIR, exist_ok=True)
            longs_map = json.load(open(LONGS_MAP)) if os.path.exists(LONGS_MAP) else {}
            if not dry:
                open(os.path.join(LONGS_DIR, scene[4:] + ".bin"), "wb").write(blob)
                longs_map[scene[4:]] = {"addr": base, "size": len(blob)}
                json.dump(longs_map, open(LONGS_MAP, "w"), indent=1)
            print(f"  group of {len(pairs)} + {len(text)} B of longs at {base:#010x}..{base + gsize + len(text):#010x} "
                  f"(work/longs/{scene[4:]}.bin); bank untouched")
            total += len(pairs)
            continue
        else:
            for i, e in jobs:
                enc = pf.encode(e["long"]) + b"\x00"
                d.append(0)
                off = len(d)
                d += enc
                if not (0 <= e["off"] <= 0xFFFF and 0 <= off <= 0xFFFF):
                    raise SystemExit(f"{scene} idx {i}: offset out of 16-bit range")
                pairs.append((e["off"], bank_ram + off))
                print(f"  idx {i:4d} {e['long']!r:24s} file {e['off']:#06x} -> "
                      f"{off:#06x}")
        # the group: words, so it starts on a 4-aligned file offset (the bank
        # loads 4-aligned; a stray zero after the last string is harmless)
        d.append(0)
        while len(d) % 4:
            d.append(0)
        goff = len(d)
        if goff > 0xFFFF:
            raise SystemExit(f"{scene}: group offset out of 16-bit range")
        d += build_group(pairs)
        groups[key] = bank_ram + goff
        print(f"  group: {len(pairs)} entries at file {goff:#06x}")
        if len(d) > capacity and scene + ".BIN" not in already:
            overflow.append(scene)
            print(f"  {scene}: grew to {len(d)}, past {capacity} — relocating")
        total += len(pairs)
        if not dry:
            open(bank_path, "wb").write(d)
            exe = bytearray(open(EXE, "rb").read())
            rec = SCENE_TABLE + scene_index(scene) * 12
            struct.pack_into("<I", exe, rec + 4, len(d))
            open(EXE, "wb").write(exe)
            print(f"  {scene}: {orig_len} -> {len(d)} bytes "
                  f"(slack left {capacity - len(d)})")
    minted = [k for k in pf.table if k not in known]
    if minted:
        raise SystemExit(f"{len(minted)} letter pair(s) with no glyph slot in the longs "
                         f"({', '.join(repr(m) for m in minted[:12])}...): the code would draw the "
                         f"slot's kanji. Run rebuild_pairs.py, then the build again.")
    return groups, total, overflow


def relocate(overflow, dry=False):
    """Move overflowing banks to sectors appended past the image end.

    All relocated banks — keytable.py's ISZ_B040 plus anything collect()
    overflowed — get their LBAs reassigned sequentially from the end of the
    source image, using each patched file's final size, and the scene table
    records are rewritten to match. patch_disc.py reads the result from
    work/relocations.json and builds fresh Mode 2 Form 1 sectors past the
    original image end."""
    relp = os.path.join(ROOT, "work", "relocations.json")
    rel = json.load(open(relp)) if os.path.exists(relp) else {}
    for scene in overflow:
        rel.setdefault(scene + ".BIN", None)
    if not rel:
        return
    img = os.path.join(ROOT, "discs/iso_ps1_jp", "Snatcher (Japan).bin")
    lba = os.path.getsize(img) // 2352
    exe = bytearray(open(EXE, "rb").read())
    out = {}
    for fname in rel:
        size = os.path.getsize(os.path.join(OUT, fname))
        rec = SCENE_TABLE + scene_index(fname[:-4]) * 12
        struct.pack_into("<II", exe, rec, lba, size)
        out[fname] = lba
        print(f"  {fname}: relocated to LBA {lba} "
              f"({(size + 2047) // 2048} sectors, {size} bytes)")
        lba += (size + 2047) // 2048
    if not dry:
        open(EXE, "wb").write(exe)
        json.dump(out, open(relp, "w"))


def keytable_entries():
    """Evicted-dialogue remaps from keytable.py (ISZ_B040), if it has run."""
    p = os.path.join(ROOT, "work", "keytable_remaps.json")
    if not os.path.exists(p):
        return {}
    kt = json.load(open(p))
    print(f"  + {len(kt['entries'])} evicted-dialogue remaps from keytable")
    base = kt["sbase"] + 4                      # keytable's offsets are base-relative
    return {"ISZ_B040": [(old + base, new + base) for old, new in kt["entries"]]}


def main(dry=False):
    if not dry and os.path.exists(LONGS_MAP):
        os.remove(LONGS_MAP)                    # every build places the longs afresh
    groups, total, overflow = collect(keytable_entries(), dry)
    relocate(overflow, dry)
    if groups:
        build_patch(groups, total, dry)
    print(f"{total} string(s) repointed" + (" (dry run)" if dry else ""))


if __name__ == "__main__":
    main("--dry" in sys.argv)
