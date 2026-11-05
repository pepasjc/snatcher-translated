"""OPTIONS > WALLPAPERS: one picture behind the whole game, picked on the title.

The Saturn keeps one secret option, the wall paper set (u16 [0x060E4B54]+4 =
0x26007104), reachable in the pristine game only through the Konami code, as
three per-act families. The menu replaces the families with TEN rows, each
one fixed picture for the whole game (Luiz, 2026-09-30):

  OPTION MENU    5 rows at a 12-px pitch: MESSAGE SPEED / CONTROL PAD /
                 SOUND MODE / WALLPAPERS / EXIT.
  WALLPAPER      two columns of five: ACT 1 / ACT 2 / ACT 3 / TWINBEE /
                 KONAMI | TOKIMEKI / ENDING / GRADIUS / TURBOCAR / BLACK (rows
                 0..9; 0..8 = satspecial.PICTURES, 9 = no picture). Up/down
                 walk 0..9 (the left column, then the right). The cursor starts
                 on the stored row (ACT 1 when none), the highlighted picture
                 is previewed behind the panel (loaded when the cursor moves),
                 confirm stores `0xA5 << 8 | row` and returns to the OPTION
                 MENU with the title's city back. An unmarked word (never
                 chosen, power-on garbage, the Konami code's steps) = Konami's
                 own per-act plates (satspecial).
  BLACK (row 9)  rooms load what they ask for (satspecial swaps nothing), and
                 `black` - the op 0x1D handler's new front - zeroes the wall
                 paper's palette (CRAM work ptr 0x13, 0x202BF600, 256 colours)
                 whenever fade record 6 (NBG1 = CRAM palette 7) is pointed at
                 it. Only op 0x14/0x15 fill ptr 0x13 (chunk 60's CONTINUE
                 blocks and four room scripts: chunks 61, 80, 81, 96), and each
                 is followed by `1d 0006 0013`, so the palette is black again
                 before a frame shows it.

Three parts, all from pristine data (work/saturn/optmenu/chunk60_options.txt
and chunk331.txt hold the reverse engineering; saturn/tools/satroom.py
disassembles the room scripts):

  exec (patched/saturn/MAIN_L.BIN, byte-guarded):
       - the title state machine's OPTION state (0x060B0BE2): row count 4 ->
         5 (0x060B0C1A); the row-flag writes (0x060B0C26..0x060B0C43) ->
         `rows`: flags 0x0B..0x0E for rows 0-3 and 0x1C (ctx+0x5F6, free on
         the title) for row 4, since 0x0B+4 is the confirm flag; the confirm
         (0x060B0C4E) -> `conf`: row 4 -> state 9 (EXIT), rows 0-2 -> 6+row
         as before, row 3 runs WALLPAPER inline - state 6's loop over 10 rows
         (flags 0x10..0x19 = rows, 0x1A = confirm, 0x1B = "the cursor moved",
         set by the loop so the script loads a preview only then) whose
         setting is the marked word, then state 5. The state table
         (0x060B07C8) has no room for a state 10, so WALLPAPER never leaves
         the OPTION state. `rows`/`conf` sit in the exec hole (satexec's
         ledger).
       - `black` in the dead original op 0x0F handler (0x060B6424..0x060B6467,
         68 bytes: satspecial repointed op 0x0F's table word), reached from
         op 0x1D's table word (0x060E4E64) and the one direct caller's pool
         word (0x060B6F50): `1d xx 0013 a2` zeroes ptr 0x13 when a2 == 2 (the
         menu's BLACK preview) or when a2 != 3 (3 = the menu's picture
         previews) and the word is 0xA509; then the original handler
         (0x060B6924).
  chunk 60 (raw, the scene-0 room script; override patched/saturn/chunks/
       060.bin): new blocks appended at the pristine end (0x323C): five
       option bars + ten WALLPAPER bars (two columns), the option loop with
       flag 0x1C (0x0214 jumps there), the dispatch (0x0284 jumps there: 0x0E
       -> WALLPAPER, 0x1C -> EXIT), the WALLPAPER screen (preview = the row's
       chunk | 0x8000 into container slot 1 -> NBG1 VDP2 0x22000, palette ->
       CRAM work ptr 0x13 -> fade record 6; BLACK = `1d 0006 0013 0002`; the
       city, chunk 0x148, comes back on confirm).
  chunk 331 (LZ, the option graphics; override 331.bin, decoded): two word
       images composed from Konami's own 6x7 lettering (satoptlabels.py, plus
       its hand-drawn B, K, 1, 2, 3) and appended to the sprite section - the
       128x60 OPTION rows (list 0's rows record repointed) and the 248x80
       WALLPAPER screen (list/anim 14).

Build: after satspecial.py (whose op 0x0F stub does the swap, lets the
previews load their chunk | 0x8000 unswapped, and frees the old handler),
before satpack.py. `python saturn/tools/satoptmenu.py [--dry]`. Re-running on
an exec that already carries the patch checks it and rewrites the two chunk
overrides.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import lz3, satdata, satexec, satgfx, satoptlabels, satspecial, sh2asm

MAIN_BASE = 0x060B0000
PRISTINE_MAIN = os.path.join(ROOT, "discs", "extracted_saturn", "MAIN_L.BIN")
OUT_MAIN = os.path.join(ROOT, "patched", "saturn", "MAIN_L.BIN")
CHUNK_DIR = os.path.join(ROOT, "patched", "saturn", "chunks")
BUILD = os.path.join(WORK, "saturn", "build")
CTX = 0x060F24B0
WARM = 0x060E4B54                        # -> 0x26007100; +4 = u16 the wall paper set
SET_STATE = 0x060B1014                   # (r4 state)
FRAME_WAIT = 0x060B55A0
PAD = 0x060B2228                         # (0, 0, mask) -> non-zero on a new press
WRAP = 0x060B06D0                        # (cursor, count) -> cursor moved by up/down
F = lambda n: 0x5DA + n                  # signal flag n = byte ctx+0x5DA+n

ROWS_AT, ROWS_END = 0x060B0C26, 0x060B0C44
CONF_AT = 0x060B0C4E
COUNT_AT = 0x060B0C1A

SCRIPT_CHUNK, GFX_CHUNK = 60, 331
SCRIPT_END = 0x323C                      # pristine chunk 60 length
SCRIPT_CAP = 0x3F00                      # the title reads chunk 60 as 1 x 0x3F00 (0x060B09DE)
CITY = 0x148                             # the title's NBG1 picture
PREVIEW = [c | satspecial.RAW for c in satspecial.PICTURES] + [None]   # rows 0..8 unswapped; 9 = black
ROW_NAMES = ["ACT 1", "ACT 2", "ACT 3", "TWINBEE", "KONAMI", "TOKIMEKI", "ENDING", "GRADIUS", "TURBOCAR", "BLACK"]
NROWS = len(ROW_NAMES)
assert NROWS == len(PREVIEW) == satspecial.BLACK_ROW + 1
MARK = satspecial.MAGIC << 8
MENU_ROWS = ["MESSAGE SPEED", "CONTROL PAD", "SOUND MODE", "WALLPAPERS", "EXIT"]
SUB_TITLE = "WALLPAPER"
PITCH = 12                               # option rows
ROW0_Y = 0x5C                            # first option row on screen (y 92)
SUB_Y = 0x60                             # first WALLPAPER row on screen (y 96), same pitch, 5 per column
SUB_COLS = [(0x25, 0xA1), (0xA2, 0x11E)] # the two columns' bar spans (the option bar 0x25..0x11E split)
SUB_X, SUB_W, SUB_H = 38, 248, 80        # the WALLPAPER words image: screen x 38.., top y 76 (list y 80, object y -4)
SUB_FLAG, SUB_CONFIRM, SUB_MOVED = 0x10, 0x1A, 0x1B   # rows 0x10..0x19 (MESSAGE SPEED's / SOUND's / CONTROL PAD's, each re-set by its own screen)
BLACK_AT, BLACK_END = 0x060B6424, 0x060B6468    # the dead original op 0x0F handler
OP1D_WORD, OP1D = 0x060E4E64, 0x060B6924
OP1D_POOL = 0x060B6F50                   # 0x060B6F20's direct call of the handler
OP0F_WORD = 0x060E4E2C
PAL13 = 0x202BF600                       # CRAM work ptr 0x13 (0x060E4C78[0x13]): the wall paper's palette


# ---------------------------------------------------------------- exec

def stub_program(special):
    """`rows` + `conf` (outside the hole: alloc_spare); `special` = special_program()'s address."""
    ctx_flag = lambda n: f"=0x{F(n):08x}"
    return [
        # rows(r4 = ctx): clear the five row flags, set the cursor's
        ("label", "rows"),
        ("mov.l", ctx_flag(0x0B), "r1"),
        ("add", "r4", "r1"),
        ("mov", "#0", "r2"),
        ("mov", "r1", "r3"),
        ("mov.b", "r2", "@r3"), ("add", "#1", "r3"),
        ("mov.b", "r2", "@r3"), ("add", "#1", "r3"),
        ("mov.b", "r2", "@r3"), ("add", "#1", "r3"),
        ("mov.b", "r2", "@r3"),
        ("add", f"#{0x1C - 0x0E}", "r3"),
        ("mov.b", "r2", "@r3"),                 # flag 0x1C
        ("mov.l", f"=0x{0x3F8:08x}", "r0"),
        ("add", "r4", "r0"),
        ("mov.w", "@r0", "r0"),
        ("extu.w", "r0", "r0"),
        ("mov", "#4", "r2"),
        ("cmp/eq", "r2", "r0"),
        ("bf", "rows_set"),
        ("mov", f"#{0x1C - 0x0B}", "r0"),       # row 4 -> flag 0x1C
        ("label", "rows_set"),
        ("add", "r0", "r1"),
        ("mov", "#1", "r2"),
        ("rts",),
        ("mov.b", "r2", "@r1"),
        # conf(r4 = ctx): the OPTION MENU confirmed
        ("label", "conf"),
        ("mov.l", ctx_flag(0x0F), "r1"),
        ("add", "r4", "r1"),
        ("mov", "#1", "r2"),
        ("mov.b", "r2", "@r1"),
        ("mov.l", f"=0x{0x3F8:08x}", "r0"),
        ("add", "r4", "r0"),
        ("mov.w", "@r0", "r0"),
        ("extu.w", "r0", "r0"),
        ("mov", "#3", "r1"),
        ("cmp/eq", "r1", "r0"),
        ("bf", "conf_ns"),
        ("mov.l", f"=0x{special:08x}", "r1"),   # WALLPAPER (in the exec hole): pr still returns to the site
        ("jmp", "@r1"),
        ("nop",),
        ("label", "conf_ns"),
        ("mov", "#4", "r1"),
        ("cmp/eq", "r1", "r0"),
        ("bf", "conf_go"),
        ("mov", "#3", "r0"),                    # EXIT: state 9
        ("label", "conf_go"),
        ("add", "#6", "r0"),
        ("mov.l", f"=0x{SET_STATE:08x}", "r1"),
        ("jmp", "@r1"),                         # tail call; returns to the OPTION state's epilogue
        ("mov", "r0", "r4"),
        ("pool",),
    ]


def special_program():
    ctx_flag = lambda n: f"=0x{F(n):08x}"
    return [
        # WALLPAPER (r4 = ctx): state 6's loop over the ten rows
        ("label", "special"),
        ("mov.l", "r8", "@-r15"),
        ("mov.l", "r9", "@-r15"),
        ("mov.l", "r10", "@-r15"),
        ("sts.l", "pr", "@-r15"),
        ("mov", "r4", "r10"),
        ("label", "sp_wait"),                   # until the script has cleared flag 0x0F
        ("mov.l", f"=0x{FRAME_WAIT:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("mov.l", ctx_flag(0x0F), "r0"),
        ("add", "r10", "r0"),
        ("mov.b", "@r0", "r0"),
        ("tst", "r0", "r0"),
        ("bf", "sp_wait"),
        ("mov.l", f"=0x{WARM:08x}", "r1"),
        ("mov.l", "@r1", "r1"),
        ("mov.w", "@(4,r1)", "r0"),
        ("mov", "r0", "r3"),
        ("shlr8", "r3"),
        ("extu.b", "r3", "r3"),
        ("mov", f"#{satspecial.MAGIC - 256}", "r1"),
        ("extu.b", "r1", "r1"),
        ("cmp/eq", "r1", "r3"),
        ("bf", "sp_zero"),                      # never chosen: ACT 1
        ("extu.b", "r0", "r0"),
        ("mov", f"#{NROWS}", "r1"),
        ("cmp/hs", "r1", "r0"),
        ("bf", "sp_cur"),
        ("label", "sp_zero"),
        ("mov", "#0", "r0"),
        ("label", "sp_cur"),
        ("mov.l", f"=0x{0x3F8:08x}", "r8"),
        ("add", "r10", "r8"),                   # r8 = &cursor
        ("mov.w", "r0", "@r8"),
        ("mov.l", ctx_flag(SUB_FLAG), "r9"),
        ("add", "r10", "r9"),                   # r9 = &row flag 0
        ("mov", "#1", "r2"),
        ("mov", "r9", "r3"),
        ("add", f"#{SUB_MOVED - SUB_FLAG}", "r3"),
        ("mov.b", "r2", "@r3"),                 # the preview is due
        ("label", "sp_loop"),
        ("mov.l", "=0x00000600", "r6"),
        ("mov", "#0", "r5"),
        ("mov.l", f"=0x{PAD:08x}", "r1"),
        ("jsr", "@r1"),
        ("mov", "#0", "r4"),
        ("tst", "r0", "r0"),
        ("bf", "sp_ok"),
        ("mov", f"#{NROWS}", "r5"),
        ("mov.l", f"=0x{WRAP:08x}", "r1"),
        ("jsr", "@r1"),
        ("mov.w", "@r8", "r4"),
        ("mov.w", "@r8", "r1"),
        ("mov.w", "r0", "@r8"),
        ("cmp/eq", "r0", "r1"),
        ("bt", "sp_flags"),
        ("mov", "#1", "r2"),                    # moved: the preview is due
        ("mov", "r9", "r3"),
        ("add", f"#{SUB_MOVED - SUB_FLAG}", "r3"),
        ("mov.b", "r2", "@r3"),
        ("label", "sp_flags"),
        ("mov", "r9", "r3"),
        ("mov", f"#{NROWS}", "r1"),
        ("mov", "#0", "r2"),
        ("label", "sp_clr"),
        ("mov.b", "r2", "@r3"),
        ("dt", "r1"),
        ("bf/s", "sp_clr"),
        ("add", "#1", "r3"),
        ("mov.w", "@r8", "r0"),
        ("extu.w", "r0", "r0"),
        ("mov", "r9", "r1"),
        ("add", "r0", "r1"),
        ("mov", "#1", "r2"),
        ("mov.b", "r2", "@r1"),
        ("mov.l", f"=0x{FRAME_WAIT:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("bra", "sp_loop"),
        ("nop",),
        ("label", "sp_ok"),
        ("mov.w", "@r8", "r0"),
        ("extu.w", "r0", "r0"),
        ("mov.l", f"=0x{MARK:08x}", "r1"),
        ("or", "r1", "r0"),                     # MAGIC << 8 | row
        ("mov.l", f"=0x{WARM:08x}", "r1"),
        ("mov.l", "@r1", "r1"),
        ("add", "#4", "r1"),
        ("mov.w", "r0", "@r1"),
        ("mov", "#1", "r2"),
        ("mov", "r9", "r1"),
        ("add", f"#{SUB_CONFIRM - SUB_FLAG}", "r1"),
        ("mov.b", "r2", "@r1"),                 # the script's confirm
        ("mov.l", ctx_flag(0x0A), "r1"),
        ("add", "r10", "r1"),
        ("mov", "#0", "r2"),
        ("mov.b", "r2", "@r1"),                 # OPTION MENU not ready until the script says so
        ("mov.l", f"=0x{SET_STATE:08x}", "r1"),
        ("jsr", "@r1"),
        ("mov", "#5", "r4"),
        ("lds.l", "@r15+", "pr"),
        ("mov.l", "@r15+", "r10"),
        ("mov.l", "@r15+", "r9"),
        ("rts",),
        ("mov.l", "@r15+", "r8"),
        ("pool",),
    ]


def black_program():
    """The op 0x1D front, 68 bytes at the dead op 0x0F handler (r4 = the op's arguments)."""
    return [
        ("label", "black"),
        ("mov.w", "@(2,r4)", "r0"),
        ("cmp/eq", "#19", "r0"),
        ("bf", "bk_orig"),                      # not the wall paper's palette (ptr 0x13)
        ("mov.w", "@(4,r4)", "r0"),
        ("cmp/eq", "#3", "r0"),
        ("bt", "bk_orig"),                      # a2 3: the menu's picture previews
        ("cmp/eq", "#2", "r0"),
        ("bt", "bk_zero"),                      # a2 2: the menu's BLACK preview
        ("mov.l", f"=0x{WARM:08x}", "r2"),
        ("mov.l", "@r2", "r2"),
        ("mov.w", "@(4,r2)", "r0"),
        ("extu.w", "r0", "r0"),
        ("mov.l", f"=0x{MARK | satspecial.BLACK_ROW:08x}", "r1"),
        ("cmp/eq", "r1", "r0"),
        ("bf", "bk_orig"),                      # not BLACK
        ("label", "bk_zero"),
        ("mov.l", f"=0x{PAL13 + 512:08x}", "r2"),
        ("mov", "#64", "r3"),
        ("mov", "#0", "r0"),
        ("label", "bk_loop"),
        ("mov.l", "r0", "@-r2"),
        ("mov.l", "r0", "@-r2"),
        ("dt", "r3"),
        ("bf", "bk_loop"),
        ("label", "bk_orig"),
        ("mov.l", f"=0x{OP1D:08x}", "r0"),
        ("jmp", "@r0"),
        ("nop",),
        ("pool",),
    ]


def site_code(rows, conf):
    """The bytes at ROWS_AT..ROWS_END and CONF_AT..+4 (branch offsets worked out by hand, checked)."""
    w = [
        0xD102,             # 0c26 mov.l @(0x0C30),r1   = rows
        0x410B,             # 0c28 jsr @r1
        0x64A3,             # 0c2a mov r10,r4
        0xA00A,             # 0c2c bra 0x0C44          (the frame wait, then back to the pad loop)
        0x0009,             # 0c2e nop
        rows >> 16, rows & 0xFFFF,          # 0c30
        0xD102,             # 0c34 mov.l @(0x0C40),r1   = conf
        0x410B,             # 0c36 jsr @r1
        0x64A3,             # 0c38 mov r10,r4
        0xA10C,             # 0c3a bra 0x0E56          (the state function's epilogue)
        0x0009,             # 0c3c nop
        0x0009,             # 0c3e
        conf >> 16, conf & 0xFFFF,          # 0c40
    ]
    assert len(w) * 2 == ROWS_END - ROWS_AT
    return b"".join(struct.pack(">H", x) for x in w), bytes.fromhex("aff1" "0009")   # 0c4e bra 0x0C34; nop


def check_sites():
    """The branch/pool arithmetic of site_code, recomputed."""
    def bra(at, to):
        d = (to - (at + 4)) // 2
        assert -2048 <= d < 2048
        return 0xA000 | (d & 0xFFF)
    def movl(at, lit, n):
        d = (lit - ((at & ~3) + 4)) // 4
        assert 0 <= d < 256
        return 0xD000 | n << 8 | d
    assert movl(0x060B0C26, 0x060B0C30, 1) == 0xD102
    assert bra(0x060B0C2C, 0x060B0C44) == 0xA00A
    assert movl(0x060B0C34, 0x060B0C40, 1) == 0xD102
    assert bra(0x060B0C3A, 0x060B0E56) == 0xA10C
    assert bra(0x060B0C4E, 0x060B0C34) == 0xAFF1


# Spare exec space outside satexec's hole: the SJIS->glyph table's entries for
# codes whose second byte is 0xFD..0xFF / 0x00..0x3F - not Shift-JIS at all, so
# no text draws them (alloc_spare still checks them against used_codes() and
# that the bytes are zero). Each run is 134 bytes; the first that fits is used.
SPARE_RUNS = [(0x060E806A + 0x200 * k, 0x060E80F0 + 0x200 * k) for k in range(8)]


def alloc_spare(exe, size):
    o = lambda a: a - MAIN_BASE
    used = satexec.used_codes()
    for lo, hi in SPARE_RUNS:
        start = (lo + 3) & ~3
        end = start + size
        if end > hi:
            continue
        first = satexec.TABLE_LO + (start - satexec.TABLE_ADDR) // 2
        last = satexec.TABLE_LO + (end - 1 - satexec.TABLE_ADDR) // 2
        if any(first <= c <= last for c in used) or any(exe[o(start):o(end)]):
            continue
        assert all(((c & 0xFF) >= 0xFD or (c & 0xFF) < 0x40) for c in range(first, last + 1)), hex(first)
        return start
    raise SystemExit(f"satoptmenu: no spare run holds {size} bytes")


def patch_exec(exe, pristine):
    """-> (exe, stub address, 'applied'|'present')."""
    check_sites()
    o = lambda a: a - MAIN_BASE
    led = satexec.load_ledger(bytes(exe))
    if exe[o(COUNT_AT):o(COUNT_AT) + 2] == b"\xe5\x05":
        # already applied (a re-run, or after satpack): the stub address is the site's literal
        addr = struct.unpack_from(">I", exe, o(ROWS_AT) + 10)[0]
        conf = struct.unpack_from(">I", exe, o(ROWS_AT) + 26)[0]
        rows_b, conf_b = site_code(addr, conf)
        assert exe[o(ROWS_AT):o(ROWS_END)] == rows_b and exe[o(CONF_AT):o(CONF_AT) + 4] == conf_b
        bk, _ = sh2asm.asm(black_program(), BLACK_AT)
        assert exe[o(BLACK_AT):o(BLACK_AT) + len(bk)] == bk
        assert struct.unpack_from(">I", exe, o(OP1D_WORD))[0] == BLACK_AT == struct.unpack_from(">I", exe, o(OP1D_POOL))[0]
        return exe, addr, "present"
    for a, n in ((COUNT_AT, 2), (ROWS_AT, ROWS_END - ROWS_AT), (CONF_AT, 4)):
        if exe[o(a):o(a) + n] != pristine[o(a):o(a) + n]:
            sys.exit(f"satoptmenu: {a:#x} holds {exe[o(a):o(a) + n].hex()}, expected the pristine "
                     f"{pristine[o(a):o(a) + n].hex()} - another patch")
    assert exe[o(COUNT_AT):o(COUNT_AT) + 2] == b"\xe5\x04"
    for a, n in ((BLACK_AT, BLACK_END - BLACK_AT), (OP1D_WORD, 4), (OP1D_POOL, 4)):
        if exe[o(a):o(a) + n] != pristine[o(a):o(a) + n]:
            sys.exit(f"satoptmenu: {a:#x} is not pristine - another patch")
    if struct.unpack_from(">I", exe, o(OP0F_WORD))[0] == BLACK_AT:
        sys.exit("satoptmenu: op 0x0F still points at its original handler - run satspecial.py first")
    assert struct.unpack_from(">I", exe, o(OP1D_WORD))[0] == OP1D == struct.unpack_from(">I", exe, o(OP1D_POOL))[0]
    bk, _ = sh2asm.asm(black_program(), BLACK_AT)
    assert len(bk) <= BLACK_END - BLACK_AT, len(bk)
    exe[o(BLACK_AT):o(BLACK_END)] = bk + bytes(BLACK_END - BLACK_AT - len(bk))
    struct.pack_into(">I", exe, o(OP1D_WORD), BLACK_AT)
    struct.pack_into(">I", exe, o(OP1D_POOL), BLACK_AT)
    probe, _ = sh2asm.asm(special_program(), satexec.HOLE_LO)
    sp_addr = satexec.alloc(led, exe, "satoptmenu", len(probe), align=4)
    sp_code, _ = sh2asm.asm(special_program(), sp_addr)
    exe[o(sp_addr):o(sp_addr) + len(sp_code)] = sp_code
    probe, _ = sh2asm.asm(stub_program(sp_addr), SPARE_RUNS[0][0])
    addr = alloc_spare(exe, len(probe))
    led["allocations"].append({"who": "satoptmenu-rows (outside the hole: invalid-SJIS table entries)",
                               "start": addr, "end": addr + len(probe)})
    code, labels = sh2asm.asm(stub_program(sp_addr), addr)
    exe[o(addr):o(addr) + len(code)] = code
    rows_b, conf_b = site_code(labels["rows"], labels["conf"])
    exe[o(ROWS_AT):o(ROWS_END)] = rows_b
    exe[o(CONF_AT):o(CONF_AT) + 4] = conf_b
    exe[o(COUNT_AT):o(COUNT_AT) + 2] = b"\xe5\x05"
    os.makedirs(BUILD, exist_ok=True)
    with open(os.path.join(BUILD, "optmenu_stub.txt"), "w", encoding="utf-8") as f:
        f.write(sh2asm.check(code, addr) + "\n")
        f.write(sh2asm.check(sp_code, sp_addr) + "\n")
        f.write(sh2asm.check(bk, BLACK_AT) + "\n")
    exe_b = bytes(exe)
    return exe, addr, ("applied", led, exe_b)


# ---------------------------------------------------------------- chunk 60

class Script:
    """A tiny room-script assembler: ops are (op, *args); a str arg is a label -> 0x002A, offset."""
    def __init__(self, org):
        self.org, self.items = org, []

    def label(self, name):
        self.items.append(("label", name))

    def op(self, op, *args):
        self.items.append(("op", op, args))

    def build(self, known=None):
        labels = dict(known or {})
        for rnd in range(2):
            pc, out = self.org, bytearray()
            for it in self.items:
                if it[0] == "label":
                    labels[it[1]] = pc
                    continue
                _, op, args = it
                words = [op]
                for a in args:
                    if isinstance(a, str):
                        words += [0x002A, labels.get(a, 0)]
                    else:
                        words.append(a & 0xFFFF)
                out += b"".join(struct.pack(">H", w) for w in words)
                pc += 2 * len(words)
        return bytes(out), labels


def bar(s, y0, y1, x0=0x25, x1=0x11E):
    s.op(0x1B, 0x0002, 0x801F, x0, y0, x1, y0, x1, y1, x0, y1, 0x4210, 0x4210, 0x4210, 0x4210)
    s.op(0x29)


def script_blocks():
    s = Script(SCRIPT_END)
    for i in range(5):
        s.label(f"B{i}")
        bar(s, ROW0_Y + PITCH * i, ROW0_Y + PITCH * (i + 1))
    # the OPTION MENU loop (0x0214 jumps here)
    s.label("L0")
    s.op(0x50, 0x1C)
    s.label("L")
    s.op(0x09, 1)
    for i, fl in enumerate((0x0B, 0x0C, 0x0D, 0x0E, 0x1C)):
        s.op(0x55, fl, f"B{i}")
    s.op(0x54, 0x0F, "L")
    s.op(0x0D, "T240")                      # the pristine tail: sound, slide out, dispatch
    # the dispatch's last test (0x0284 jumps here)
    s.label("D")
    s.op(0x53, 0x0E, "S")
    s.op(0x53, 0x1C, "T28")
    s.op(0x0D, "T28")
    # WALLPAPER: ten rows in two columns of five at the option pitch
    for i in range(NROWS):
        x0, x1 = SUB_COLS[i // 5]
        s.label(f"Q{i}")
        bar(s, SUB_Y + PITCH * (i % 5), SUB_Y + PITCH * (i % 5 + 1), x0, x1)
    s.label("S")
    s.op(0x05, 0, 14, 3, 0x1F, 1, 0, 0)      # obj 12 = anim 14 (the WALLPAPER words)
    s.op(0x05, 1, 4, 2, 0, 1, 0, 0)          # obj 13 = the panel
    s.op(0x1C, 0, 0, 0xFEFC)
    s.op(0x1C, 1, 0, 0xFEFC)
    s.op(0x33, 0, 0x10, 0, 0, 0x10, 0)
    s.op(0x33, 1, 0x10, 0, 0, 0x10, 0)
    s.op(0x09, 0x10)
    for fl in list(range(SUB_FLAG, SUB_MOVED + 1)) + [0x0F]:   # 0x0F last: the exec's loop waits on it
        s.op(0x50, fl)
    s.label("SL")
    s.op(0x09, 1)
    for i in range(NROWS):
        s.op(0x55, SUB_FLAG + i, f"Q{i}")
    s.op(0x54, SUB_MOVED, "SC")             # the cursor has not moved: no load
    s.op(0x50, SUB_MOVED)
    for i in range(NROWS):
        s.op(0x53, SUB_FLAG + i, f"P{i}")
    s.label("SC")
    s.op(0x54, SUB_CONFIRM, "SL")
    s.op(0x3C, 0, "T85a")                   # the confirm sound + 16 frames
    s.op(0x0F, CITY, 1)                     # the title's city back on NBG1; its palette is still CRAM work ptr 4
    s.op(0x10)
    s.op(0x16, 1, 0, 8)
    s.op(0x1D, 6, 4, 1)
    s.op(0x13, 2)
    s.op(0x33, 0, 0x10, 0, 0, 0xFFF0, 0)
    s.op(0x33, 1, 0x10, 0, 0, 0xFFF0, 0)
    s.op(0x09, 0x10)
    s.op(0x0D, "T170")                      # the OPTION MENU again
    for i in range(NROWS):
        s.label(f"P{i}")
        if PREVIEW[i] is None:              # BLACK: the palette zeroed (op 0x1D's front, a2 2)
            s.op(0x1D, 6, 0x13, 2)
        else:
            s.op(0x0F, PREVIEW[i], 1)       # chunk | 0x8000 (no swap) into container slot 1: slot 0 holds chunk 331
            s.op(0x10)
            s.op(0x16, 1, 0, 8)             # background -> VDP2 0x22000 (NBG1)
            s.op(0x15, 1, 0, 0x13, 0, 0x100)    # palette -> CRAM work ptr 0x13
            s.op(0x1D, 6, 0x13, 3)          # fade record 6 (CRAM palette 7) from it; a2 3 = never black
        s.op(0x0D, "SC")
    known = {f"T{a:x}": a for a in (0x240, 0x28, 0x85A, 0x170)}
    return s.build(known)


def build_script(pristine):
    import satroom
    d = bytearray(pristine)
    assert len(d) == SCRIPT_END, len(d)
    guards = {0x0214: "0009 0001 0055 000b", 0x0284: "0053 000e 002a 0028"}
    for at, hx in guards.items():
        assert d[at:at + 8].hex(" ", 2) == hx, (hex(at), d[at:at + 8].hex(" ", 2))
    blocks, labels = script_blocks()
    d += blocks
    d[0x0214:0x021A] = struct.pack(">HHH", 0x0D, 0x002A, labels["L0"])
    d[0x0284:0x028C] = struct.pack(">HHHH", 0x0D, 0x002A, labels["D"], 0x0009)   # 0x28A..: dead
    assert len(d) <= SCRIPT_CAP, f"chunk 60 grew to {len(d)} bytes (> {SCRIPT_CAP:#x})"
    seen, probs = satroom.flow(bytes(d))
    assert not probs, probs
    for k in ["S", "L0", "D", "SC", "SL"] + [f"P{i}" for i in range(NROWS)] + [f"Q{i}" for i in range(NROWS)]:
        assert labels[k] in seen, k
    return bytes(d), labels


# ---------------------------------------------------------------- chunk 331

def atlas(d):
    """{char: 7 rows of pixel values} - Konami's words (the first sighting) + satoptlabels' hand-drawn letters."""
    found = {}
    for off, w, h, lines in satoptlabels.TEXTS:
        for y0, txt in lines:
            cols = [x for x in range(w) if any(d[off + y * w + x] for y in range(y0, y0 + 7))]
            segs, s, prev = [], None, None
            for x in cols:
                if s is None:
                    s = x
                elif x != prev + 1:
                    segs.append((s, prev)); s = x
                prev = x
            segs.append((s, prev))
            letters = txt.replace(" ", "")
            assert len(segs) == len(letters), (txt, segs)
            for (a, b), ch in zip(segs, letters):
                if ch not in found:
                    found[ch] = [bytes(d[off + (y0 + y) * w + x] for x in range(a, b + 1)) for y in range(7)]
    for ch, rows in satoptlabels.EXTRA_GLYPHS.items():
        assert ch not in found and len(rows) == 7 and all(len(r) == 6 for r in rows), ch
        found[ch] = [bytes(9 if c == "#" else 0 for c in r) for r in rows]
    return found


def draw_text(img, W, gl, text, y, x=0, w=None):
    """Konami's placement: 10-px cells, a 6-px glyph at the cell's left (I at +2), centred in
    the span [x, x + w) of the image (the whole width by default)."""
    n = len(text)
    w = W if w is None else w
    x0 = x + (w - 10 * n + 4) // 2 - 1
    assert x0 >= 0, (text, W)
    for k, ch in enumerate(text):
        if ch == " ":
            continue
        g = gl[ch]
        cx = x0 + 10 * k + (2 if len(g[0]) == 2 else 0)
        assert 0 <= cx and cx + len(g[0]) <= W, (text, cx)
        for yy in range(7):
            for xx, v in enumerate(g[yy]):
                if v:
                    img[(y + yy) * W + cx + xx] = v


def build_gfx(dec):
    secs = satgfx.parse(dec)
    (t3, o3, s3), (t1, o1, s1), (t2, o2, s2) = secs
    assert (t3, t1, t2) == (3, 1, 2) and s3 == 0xE680
    gl = atlas(dec)
    for word in MENU_ROWS + ROW_NAMES + [SUB_TITLE]:
        missing = set(word.replace(" ", "")) - set(gl)
        assert not missing, (word, missing)
    RW, RH = 128, 12 * len(MENU_ROWS)
    rows = bytearray(RW * RH)
    for i, t in enumerate(MENU_ROWS):
        draw_text(rows, RW, gl, t, 12 * i + 2)
    SW, SH = SUB_W, SUB_H                    # title ink at 1 (screen y 77); rows on the bars from y 96
    sub = bytearray(SW * SH)
    draw_text(sub, SW, gl, SUB_TITLE, 1)
    top = 80 - 4                            # the image's screen top: list y 80, object y -4
    for i, t in enumerate(ROW_NAMES):
        x0, x1 = SUB_COLS[i // 5]
        draw_text(sub, SW, gl, t, SUB_Y - top + PITCH * (i % 5) + 2, x0 - SUB_X, x1 - x0 + 1)
    spr = bytearray(dec[o3:o3 + s3])
    rows_srca = len(spr) // 8
    spr += rows
    sub_srca = len(spr) // 8
    spr += sub
    assert 0x19000 + len(spr) <= 0x30000, "VDP1: past 0x30000 (the title's sprites)"
    idx = bytearray(dec[o2:o2 + s2])
    nA, nB = struct.unpack_from(">HH", idx, 0)
    assert (nA, nB) == (14, 14)
    tA, tB = 16, 16 + 4 * ((nA + 3) & ~3)
    # list 0 record 2: the rows image
    l0 = struct.unpack_from(">I", idx, tB)[0]
    rec = l0 + 8 + 12 * 2
    assert struct.unpack_from(">6H", idx, rec) == (0x2000, 0x8040, 0x0100, 0x0180, 99, 96)
    struct.pack_into(">6H", idx, rec, 0x2000, RW << 8 | RH, 0x0100, rows_srca, 99 - (RW - 128) // 2, 96)
    # list 14 + anim 14 appended; the padded tables have their slot 14 free
    assert struct.unpack_from(">I", idx, tA + 4 * 14)[0] == 0 and struct.unpack_from(">I", idx, tB + 4 * 14)[0] == 0
    while len(idx) & 3:
        idx.append(0)
    lst = len(idx)
    idx += struct.pack(">H6x", 1) + struct.pack(">6H", 0x2000, SW << 8 | SH, 0x0100, sub_srca, SUB_X, 80)
    anim = len(idx)
    idx += struct.pack(">HHH", 1, 14, 1)
    struct.pack_into(">HH", idx, 0, nA + 1, nB + 1)
    struct.pack_into(">I", idx, tA + 4 * 14, anim)
    struct.pack_into(">I", idx, tB + 4 * 14, lst)
    out = satgfx.build([(3, bytes(spr)), (1, dec[o1:o1 + s1]), (2, bytes(idx))], satgfx.terminator(dec))
    return out, rows, sub, (RW, RH, SW, SH)


def pristine_chunks():
    main = open(PRISTINE_MAIN, "rb").read()
    rows = lz3.table()
    with open(lz3.DATA_BIN, "rb") as f:
        script = lz3.read_chunk(f, SCRIPT_CHUNK, rows)
        gfx = lz3.decode(lz3.read_chunk(f, GFX_CHUNK, rows))
    return main, script, gfx


def preview_png(rows, sub, dims, path):
    from PIL import Image
    RW, RH, SW, SH = dims
    im = Image.new("RGB", (max(RW, SW), RH + SH + 4), (40, 0, 40))
    for (buf, w, h, y) in ((rows, RW, RH, 0), (sub, SW, SH, RH + 4)):
        for yy in range(h):
            for xx in range(w):
                im.putpixel((xx, y + yy), (0, 255, 64) if buf[yy * w + xx] else (0, 0, 0))
    im.resize((im.width * 3, im.height * 3), Image.NEAREST).save(path)


def main(argv):
    dry = "--dry" in argv
    main_p, script_p, gfx_p = pristine_chunks()
    script, labels = build_script(script_p)
    gfx, rows, sub, dims = build_gfx(gfx_p)
    os.makedirs(BUILD, exist_ok=True)
    preview_png(rows, sub, dims, os.path.join(BUILD, "optmenu_words.png"))
    exe = bytearray(open(OUT_MAIN, "rb").read())
    exe, addr, how = patch_exec(exe, main_p)
    print(f"satoptmenu: chunk 60 {len(script_p)} -> {len(script)} bytes (blocks at {SCRIPT_END:#x}: "
          + ", ".join(f"{k} {labels[k]:#x}" for k in ("L0", "D", "S", "P0")) + f"); chunk 331 decoded "
          f"{len(gfx_p)} -> {len(gfx)}; exec stub {addr:#x} ({'already in' if how == 'present' else 'new'})")
    if dry:
        print("dry run: nothing written")
        return
    os.makedirs(CHUNK_DIR, exist_ok=True)
    open(os.path.join(CHUNK_DIR, f"{SCRIPT_CHUNK:03d}.bin"), "wb").write(script)
    open(os.path.join(CHUNK_DIR, f"{GFX_CHUNK:03d}.bin"), "wb").write(gfx)
    if how != "present":
        _, led, exe_b = how
        open(OUT_MAIN, "wb").write(exe_b)
        satexec.save_ledger(led, exe_b)
        print(f"wrote {OUT_MAIN}")
    print(f"wrote {CHUNK_DIR}/{SCRIPT_CHUNK:03d}.bin, {GFX_CHUNK:03d}.bin")


if __name__ == "__main__":
    main(sys.argv[1:])
