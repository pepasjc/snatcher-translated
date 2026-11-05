"""The text layout's row accounting: a row that fills the box's width no longer
doubles up with the `￥` that follows it, and a line that runs past row 3
pages (a press, a clean box, the rest from the top - the PS1's continuation
card) instead of writing cells over the game context.

The wedge (2026-09-12, Gaudi's terminal, B030 offsets 8105 / 11102 / 16629 /
17201 - 'Witch hunts' first): the layout 0x060B45C4(col, row, sjis) keeps
the row in r10 and the column in r12 and advances the row in two places:

  0x060B46AA..46D0  after a cell lands at the last column (20, or 14 while
                    ctx+0x56A == 7) r10 += 1 and r11 = ctx + 0x3FA + 80*r10.
                    No row-count check: row 4 is ctx+0x53A, the bytes after
                    the cell array (ctx+0x54A is the scene index).
  0x060B4646..4678  a `￥` (0x818F): r10 += 1; if r10 == 4 the page scrolls
                    (0x060B4730: rows 1-3 -> 0-2, row 3 cleared) and r11 goes
                    to row 3 - but r10 STAYS 4, so the next `￥` makes 5 and
                    r11 = ctx+0x58A, which is where the cells then land.

A full row followed by `￥` therefore costs two rows (the Japanese shows a
blank row there - B040 5076 and 8368 are the only two JP cases, and the JP
never needs more than 4 rows counted that way, so the Japanese never
scrolls). The English terminal entries are pre-broken at 14 and two of
their rows are often exactly 14 wide: rows 0 and 1 full -> rows 0, 2 and
`￥` -> 4 (scroll, r10 = 4) -> the third `￥` -> row 5 -> 'southern
slums...' is written over ctx+0x58A.. and the bytecode pointer at
ctx+0x58C (the script PC, read by 0x060B8170) gets a pair code's bytes
for its top half: the interpreter runs into garbage and the vblank
counter stops. Shortening either full row to 13 or dropping the fourth
row avoids the fifth advance, which is exactly what probe_hang.py saw.

Two pool words are retargeted to stubs in the exec hole (satexec.alloc):

  0x060B4728  the layout's write-cell (0x060B45B0: {sjis, colour} into the
              cell)  -> `wrap`: writes the cell, and when it was the row's
              last cell (r12 + 1 == width) consumes a `￥` that follows
              (r8 += 2 - the PS1's render_text never leaves a blank row
              there either); then, if more text follows and the row was
              row 3, scrolls the page right away and leaves r10 = 2 so the
              caller's own advance lands on row 3 (until now a full row 3
              with text after it wrote row 4 = ctx+0x53A).
  0x060B4698  the `￥` path's scroll (0x060B4730) -> `scroll`: calls it and
              sets r10 = 3, so every further `￥` scrolls again.

Registers: the layout holds r8 = text pointer (already past the cell's
code), r10 = row, r12 = column, r13 = ctx in callee-saved registers, and
recomputes r4-r7 before every cell (r6 = colour from r9 in the delay slot at
0x060B4650), so the stubs may clobber r0-r7. 0x060B4730 saves r8-r14.
Only the layout reads these two pool words (sh2dis xref: the other
write-cell callers have their own words).

Build: after satsubs, before satpack (the ledger keys on the exec's sha1):
    python saturn/tools/satwrap.py [--dry]
RAM (the harness): `install(mem, addr)` writes the stubs at `addr` and
retargets the two words in the running core (work/saturn/play/probe_wrapfix.py).

Paging (Luiz, 2026-09-30: "in saturn the text scrolls so the top line gets
pushed up and can't be read anymore"): the English runs past 4 rows on ~125
lines, and the layout types on synchronously (a frame wait or two per cell,
0x060B46F0), so the scroll took the top row away mid-sentence. Both overflow
paths now call `page` instead of the engine's scroll: the end-of-card wait's
own moves (0x060B4E28) - 9 frames, the press cursor (object 11 through
0x060B5428 at (0x120, 0xCC) while object 0 is on the dialogue box list; it
sets ctx+0xB74, so the pilots press it like any card), the loop on
pad(0, 0, [0x060F24A4]) around the frame wait, ctx+0xB74 cleared, the
0x519 blip - then rows 3..start cleared (0x060B48DC) and the text goes on at
the layout's start row: row 1 under a speaker's name (row 0, the name, is
kept - the PS1's pageplate), row 0 otherwise. `more` skips `＠`+colour pairs:
a line whose text ends exactly on row 3 closes normally, no empty page.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import satexec, sh2asm

MAIN_BASE = 0x060B0000
OUT_MAIN = os.path.join(ROOT, "patched", "saturn", "MAIN_L.BIN")
BUILD = os.path.join(WORK, "saturn", "build")
CTX = 0x060F24B0
WINDOW_MODE = CTX + 0x56A          # u16, 7 = Gaudi's terminal: 14 cells per row
BREAK_WORD = 0x060E4DBC            # u16 0x818F, the `￥` the layout compares against
WRITE_CELL = 0x060B45B0
SCROLL = 0x060B4730
EMPTY_STR = 0x060B45C0             # the scroll's row-3 text: an empty string
LAYOUT_ENTER = 0x060B4A8C          # called first thing by the layout (pool 0x060B468C), r10 = the start row
CELLS = CTX + 0x3FA                # row r at CELLS + 80*r, 20 cells of {u16 sjis, u8 colour, pad}
COLOUR_WORD = 0x060E4DA8           # u16 `＠`, the colour escape (one code follows)
FRAME_WAIT = 0x060B55A0
PAD = 0x060B2228                   # pad(port, 0, mask) -> r0 != 0 on a press (the end-of-card wait's call)
CONFIRM_MASK = 0x060F24A4          # u16, the buttons that close a card
MAKE_OBJ = 0x060B5428              # (obj, 17, -1, 31; 1, 7, 7): the press cursor, as 0x060B4EAC calls it
OBJ0_LIST = CTX + 0x848            # object 0's sprite list; its first u16 is 88 on the dialogue box
CURSOR_X, CURSOR_Y = CTX + 0xB7C, CTX + 0xB80
BOX_WAIT = CTX + 0xB74             # object 11's type byte: 1 while the cursor waits
SOUND = 0x060BBA74                 # the press blip, 0x519
CLEAR_ROW = 0x060B48DC             # (row): 20 blank cells
# The name on a continuation page (Luiz, 2026-09-18: "the second page is not
# carrying the name / with 4 rows the name disappears"): the speaker op lays
# the name at row 0 and its text from row 1. `enter` records the layout's
# start row; `page` clears the rows from 3 down to it, so row 0 keeps the
# name when the text started at row 1.
# (pool word, original value, stub)
HOOKS = [
    (0x060B4728, WRITE_CELL, "wrap"),
    (0x060B4698, SCROLL, "scroll"),
    (0x060B468C, LAYOUT_ENTER, "enter"),
]


def stub_program():
    return [
        # wrap(r4 = cell, r5 = code, r6 = colour); r8 text, r10 row, r12 col (live)
        ("label", "wrap"),
        ("mov.w", "r5", "@r4"),
        ("add", "#2", "r4"),
        ("mov.b", "r6", "@r4"),                 # the original write-cell
        ("mov.l", f"=0x{WINDOW_MODE:08x}", "r1"),
        ("mov.w", "@r1", "r0"),
        ("mov", "#7", "r2"),
        ("mov", "#20", "r1"),
        ("cmp/eq", "r2", "r0"),
        ("bf", "width"),
        ("mov", "#14", "r1"),
        ("label", "width"),
        ("add", "#-1", "r1"),                   # r1 = last column
        ("mov", "r12", "r0"),
        ("cmp/eq", "r1", "r0"),
        ("bf", "done"),                         # not the row's last cell
        ("mov.w", "@r8", "r0"),
        ("extu.w", "r0", "r0"),                 # the code after this cell
        ("mov.l", f"=0x{BREAK_WORD:08x}", "r2"),
        ("mov.w", "@r2", "r2"),
        ("extu.w", "r2", "r2"),
        ("cmp/eq", "r2", "r0"),
        ("bf", "nobreak"),
        ("add", "#2", "r8"),                    # the `￥` rides on the advance the full row already made
        ("mov.w", "@r8", "r0"),
        ("extu.w", "r0", "r0"),
        ("label", "nobreak"),
        ("mov", "#3", "r1"),
        ("mov", "r10", "r0"),
        ("cmp/eq", "r1", "r0"),
        ("bf", "done"),                         # rows 0-2: the caller's advance is in range
        ("sts.l", "pr", "@-r15"),
        ("mov", "r8", "r4"),
        ("mov.l", "=more", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("tst", "r0", "r0"),
        ("bt", "wlast"),                        # end of text: nothing more lands
        ("mov.l", "=page", "r1"),               # row 3 full with text to come: a new page
        ("jsr", "@r1"),
        ("nop",),
        ("mov.l", "=startrow", "r1"),
        ("mov.l", "@r1", "r10"),
        ("add", "#-1", "r10"),                  # the caller's advance lands on the start row
        ("label", "wlast"),
        ("lds.l", "@r15+", "pr"),
        ("label", "done"),
        ("rts",),
        ("nop",),
        # scroll(r4 = text): the `￥` path's overflow (r10 = 4, r11 = row 3,
        # r8 on the `￥`): a new page when text follows, else stay on row 3
        ("label", "scroll"),
        ("sts.l", "pr", "@-r15"),
        ("mov", "r8", "r4"),
        ("add", "#2", "r4"),
        ("mov.l", "=more", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("tst", "r0", "r0"),
        ("bt", "slast"),
        ("mov.l", "=page", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("mov.l", "=startrow", "r1"),
        ("mov.l", "@r1", "r10"),
        ("mov.l", f"=0x{CELLS:08x}", "r11"),    # r11 = CELLS + 80 * r10
        ("mov", "r10", "r1"),
        ("tst", "r1", "r1"),
        ("bt", "sgo"),
        ("label", "srow"),
        ("add", "#80", "r11"),
        ("dt", "r1"),
        ("bf", "srow"),
        ("label", "sgo"),
        ("lds.l", "@r15+", "pr"),
        ("rts",),
        ("nop",),
        ("label", "slast"),
        ("mov", "#3", "r10"),
        ("lds.l", "@r15+", "pr"),
        ("rts",),
        ("nop",),
        # enter: the layout's first call, with r10 = the start row: remember it
        ("label", "enter"),
        ("mov.l", "=startrow", "r1"),
        ("mov.l", "r10", "@r1"),
        ("mov.l", f"=0x{LAYOUT_ENTER:08x}", "r1"),
        ("jmp", "@r1"),
        ("nop",),
        # more(r4 = next code) -> r0 != 0 when text follows (`＠`+colour skipped)
        ("label", "more"),
        ("mov.l", f"=0x{COLOUR_WORD:08x}", "r2"),
        ("mov.w", "@r2", "r2"),
        ("extu.w", "r2", "r2"),
        ("label", "mloop"),
        ("mov.w", "@r4", "r0"),
        ("extu.w", "r0", "r0"),
        ("cmp/eq", "r2", "r0"),
        ("bf", "mtest"),
        ("add", "#4", "r4"),
        ("bra", "mloop"),
        ("nop",),
        ("label", "mtest"),
        ("mov.l", "=0x0000ff00", "r1"),
        ("and", "r1", "r0"),
        ("rts",),
        ("nop",),
        # page: the end-of-card wait's lead-in, cursor, press and blip, then
        # rows 3..startrow cleared. Clobbers r0-r7.
        ("label", "page"),
        ("sts.l", "pr", "@-r15"),
        ("mov", "#9", "r0"),
        ("mov.l", "=pcount", "r1"),
        ("mov.l", "r0", "@r1"),
        ("label", "lead"),
        ("mov.l", f"=0x{FRAME_WAIT:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("mov.l", "=pcount", "r1"),
        ("mov.l", "@r1", "r0"),
        ("dt", "r0"),
        ("mov.l", "r0", "@r1"),
        ("bf", "lead"),
        ("mov.l", f"=0x{OBJ0_LIST:08x}", "r1"),
        ("mov.l", "@r1", "r1"),
        ("mov.w", "@r1", "r0"),
        ("mov", "#88", "r2"),
        ("cmp/eq", "r2", "r0"),
        ("bf", "pwait"),                        # not the dialogue box: no cursor
        ("mov", "#7", "r1"),
        ("mov.l", "r1", "@-r15"),
        ("mov.l", "r1", "@-r15"),
        ("mov", "#1", "r1"),
        ("mov.l", "r1", "@-r15"),
        ("mov", "#11", "r4"),
        ("mov", "#17", "r5"),
        ("mov", "#-1", "r6"),
        ("mov", "#31", "r7"),
        ("mov.l", f"=0x{MAKE_OBJ:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("add", "#12", "r15"),
        ("mov.l", f"=0x{CURSOR_X:08x}", "r1"),
        ("mov.l", "=0x00000120", "r2"),
        ("mov.w", "r2", "@r1"),
        ("mov.l", f"=0x{CURSOR_Y:08x}", "r1"),
        ("mov.l", "=0x000000cc", "r2"),
        ("mov.w", "r2", "@r1"),
        ("label", "pwait"),
        ("mov.l", f"=0x{CONFIRM_MASK:08x}", "r1"),
        ("mov.w", "@r1", "r6"),
        ("extu.w", "r6", "r6"),
        ("mov", "#0", "r5"),
        ("mov", "#0", "r4"),
        ("mov.l", f"=0x{PAD:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("tst", "r0", "r0"),
        ("bf", "pgo"),
        ("mov.l", f"=0x{FRAME_WAIT:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("bra", "pwait"),
        ("nop",),
        ("label", "pgo"),
        ("mov.l", f"=0x{BOX_WAIT:08x}", "r1"),
        ("mov", "#0", "r0"),
        ("mov.b", "r0", "@r1"),
        ("mov.l", "=0x00000519", "r4"),
        ("mov.l", f"=0x{SOUND:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("mov", "#3", "r0"),
        ("mov.l", "=pcount", "r1"),
        ("mov.l", "r0", "@r1"),
        ("label", "clr"),
        ("mov.l", "=pcount", "r1"),
        ("mov.l", "@r1", "r4"),
        ("mov.l", f"=0x{CLEAR_ROW:08x}", "r1"),
        ("jsr", "@r1"),
        ("nop",),
        ("mov.l", "=pcount", "r1"),
        ("mov.l", "@r1", "r0"),
        ("mov.l", "=startrow", "r2"),
        ("mov.l", "@r2", "r2"),
        ("cmp/hs", "r0", "r2"),                 # startrow >= this row: done
        ("bt", "cdone"),
        ("add", "#-1", "r0"),
        ("mov.l", "r0", "@r1"),
        ("bra", "clr"),
        ("nop",),
        ("label", "cdone"),
        ("lds.l", "@r15+", "pr"),
        ("rts",),
        ("nop",),
        ("pool",),
        ("label", "startrow"),
        (".long", 0),
        ("label", "pcount"),
        (".long", 0),
    ]


def assemble(addr):
    code, labels = sh2asm.asm(stub_program(), addr)
    return code, labels


def install(mem, addr):
    """Into a running core's RAM (satmem.SatMem): stubs at `addr`, the two pool
    words retargeted. Returns the labels."""
    code, labels = assemble(addr)
    assert not any(mem.read(addr, len(code))), f"RAM at {addr:#x} is not free"
    mem.write(addr, code)
    for site, want, name in HOOKS:
        have = mem.u32(site)
        assert have == want, f"pool word {site:#x} holds {have:#010x}, expected {want:#010x}"
        mem.write(site, struct.pack(">I", labels[name]))
    return labels


def main(argv):
    dry = "--dry" in argv
    if not os.path.exists(OUT_MAIN):
        sys.exit(f"{OUT_MAIN} missing: run satapply.py first")
    exe = bytearray(open(OUT_MAIN, "rb").read())
    led = satexec.load_ledger(bytes(exe))
    for site, want, _ in HOOKS:
        have = struct.unpack_from(">I", exe, site - MAIN_BASE)[0]
        if have != want:
            sys.exit(f"pool word {site:#x} holds {have:#010x}, expected {want:#010x} - double apply or another patch")
    probe, _ = assemble(satexec.HOLE_LO)
    addr = satexec.alloc(led, exe, "satwrap", len(probe), align=4)
    code, labels = assemble(addr)
    exe[addr - MAIN_BASE:addr - MAIN_BASE + len(code)] = code
    for site, want, name in HOOKS:
        struct.pack_into(">I", exe, site - MAIN_BASE, labels[name])
    print(f"satwrap: {len(code)} bytes at {addr:#x} (wrap {labels['wrap']:#x}, scroll {labels['scroll']:#x}); "
          f"{len(HOOKS)} pool words retargeted")
    os.makedirs(BUILD, exist_ok=True)
    with open(os.path.join(BUILD, "wrap_stubs.txt"), "w", encoding="utf-8") as f:
        f.write(sh2asm.check(code, addr) + "\n")
    if dry:
        print("dry run: nothing written")
        return
    open(OUT_MAIN, "wb").write(bytes(exe))
    satexec.save_ledger(led, bytes(exe))
    print(f"wrote {OUT_MAIN}")


if __name__ == "__main__":
    main(sys.argv[1:])
