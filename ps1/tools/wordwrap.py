"""Word wrap in the engine's text rasterizer (GitHub #14).

render_text (0x800367D8) fills a row cell by cell and cuts it at `width`
(18 in the dialogue box, 14 on Gaudi's terminal and the videophone) or at a
`￥`. English pre-wrapped for 18 cells then breaks mid-word wherever the box
is narrower ("Euras / ian"), and a line one cell over 18 leaves its last
word or its period alone on a row.

This installs a pre-pass: `move s3, a0` at the top of render_text becomes
the delay slot of a jump into a resident stub in high RAM, which copies the
SJIS string into its own buffer and inserts `￥` (0x818F) wherever a row
would overflow, at the latest break it can find in that row, then resumes
render_text with s3 pointing at the copy. A break is allowed after a cell
whose RIGHT half is blank ("d ") or before one whose LEFT half is blank
(" r"); the stub decides by reading the glyph itself from the exec font
(0x80074B60 + 18 * slot through the engine's own SJIS range table at
0x80074AA8), so pairs, fullwidth spaces and punctuation like `。` all work
without a table. A row with no break keeps the engine's hard cut. Colour
codes (`＠x`) are copied through as zero-cell codes, exactly as the engine
counts them.

The stub lives at RESIDENT (0x801FE000, 4 KB): the 8 KB between the
subtitle scratch (0x801FC000..) and the stack page 0x801FF000 that nothing
allocates. Nothing file-backed can hold it (the exec tail is BSS the entry
code clears), so bootcard.py appends `resident()` to the exec and its boot
stub copies it there before the original entry runs; raminject.py puts it
into resumed states. The hook is unconditional: a RAM image without the
resident runs into zeros there, so keep the two in step.

  python ps1/tools/wordwrap.py apply        # hook in patched/SLPS_001.54
  python ps1/tools/wordwrap.py show B030    # every string as the engine will row it
  python ps1/tools/wordwrap.py lint         # rows that still cut mid-word at 18
"""
import json, os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

from mipsasm import Asm

EXE = os.path.join(ROOT, "patched", "SLPS_001.54")
EXEC_RAM, HDR = 0x80028000, 0x800
RENDER_TEXT = 0x800367D8
HOOK_AT = 0x800367E0                     # move s3, a0  (becomes j wrap + that
                                         # move in the delay slot)
RESUME = 0x800367E8                      # lw t2, 0xae8(sp): the width
WIDTH_OFF, DEST_OFF = 0xAE8, 0xAEC       # stack args after the prologue's
                                         # addiu sp, -0xad8
RESIDENT = 0x801FE000
RESIDENT_LEN = 0x1000
BUF_OFF, BUF_LEN = 0x800, 0x400          # the wrapped copy
CELLS_OFF, MAX_CELLS = 0xC00, 64         # u16 buffer offset per row cell
SAVE_RA, SAVE_ORIG, SAVE_T0, SAVE_T1 = 0xF00, 0xF04, 0xF08, 0xF0C
RANGE_TAB = 0x80074AA8                   # 46 x {sjis_start, slot_base} u16
RANGE_END = RANGE_TAB + 46 * 4
GLYPHS = 0x80074B60                      # slot 0 of that table (= pairfont
                                         # slot 112): 18 bytes each
NEWLINE, COLOUR = 0x818F, 0x8197
MAGIC = 0x50415257                       # 'WRAP' at RESIDENT+0
LIST_MENU_RA = 0x8004D9B8                # return address of the list menu's
                                         # render_text call (jal 0x8004D9B0)

# The R3000 load-delay slot: every load below is followed by an instruction
# that does not read the loaded register.


def code():
    a = Asm(RESIDENT)
    a.word(MAGIC)
    a.word(0)
    a.label("wrap")                                    # s3 = string, sp adjusted
    a.lui("$t9", RESIDENT >> 16)
    a.ori("$t9", "$t9", RESIDENT & 0xFFFF)
    a.sw("$ra", SAVE_RA, "$t9")
    a.sw("$s3", SAVE_ORIG, "$t9")
    # The list menu (verbs, Ask topics, Gaudi's topic lists) renders ONE
    # buffer of 18-cell rows packed back to back with no newline between
    # them - render_text's hard cut at `width` IS the row boundary. To
    # this stub such a row is "18 cells and still going", so it broke it
    # at the last space: 'Scanning warrant' became 'Scanning' with
    # 'warrant' at the head of the next row, in front of the left
    # column's label (Gaudi's JUNKER files, 2026-09-12). Labels are placed
    # by the grid, never wrapped: that caller keeps the engine's cut.
    a.lui("$v1", LIST_MENU_RA >> 16)
    a.ori("$v1", "$v1", LIST_MENU_RA & 0xFFFF)
    a.beq("$ra", "$v1", "bail")
    a.lw("$t2", WIDTH_OFF, "$sp")                      # width in cells
    a.addiu("$t3", "$s3", 0)                           # src
    a.beq("$t2", "$zero", "bail")
    a.sltiu("$at", "$t2", MAX_CELLS)
    a.beq("$at", "$zero", "bail")
    a.addiu("$t7", "$t9", BUF_OFF)                     # buf
    a.addiu("$t4", "$t9", BUF_OFF)                     # out
    a.addiu("$t6", "$t9", CELLS_OFF)                   # cells
    a.addiu("$t5", "$zero", 0)                         # n = cells in this row
    a.label("loop")
    a.lbu("$t0", 0, "$t3")
    a.lbu("$t1", 1, "$t3")
    a.addiu("$t3", "$t3", 2)
    a.beq("$t0", "$zero", "finish")                    # high byte 0 ends it
    a.sll("$v0", "$t0", 8)
    a.or_("$v0", "$v0", "$t1")
    a.ori("$v1", "$zero", NEWLINE)
    a.beq("$v0", "$v1", "newline")
    a.ori("$v1", "$zero", COLOUR)
    a.beq("$v0", "$v1", "colour")
    a.nop()
    a.bne("$t5", "$t2", "place")                       # row not full yet
    a.nop()
    # --- row full: the latest break in cells[0..W-1] ---------------------
    a.addiu("$t0", "$t2", -1)                          # j = W-1
    a.addiu("$t1", "$zero", -1)                        # p = none
    a.label("search")
    a.bltz("$t0", "searched")
    a.sll("$v1", "$t0", 1)
    a.addu("$v1", "$v1", "$t6")
    a.lhu("$a0", 0, "$v1")
    a.nop()
    a.jal("halves")
    a.addu("$a0", "$a0", "$t7")
    a.andi("$v1", "$v0", 2)
    a.bne("$v1", "$zero", "after")                     # right half blank: after j
    a.andi("$v1", "$v0", 1)
    a.beq("$v1", "$zero", "nextj")
    a.nop()
    a.beq("$t0", "$zero", "nextj")                     # before cell 0 is no break
    a.nop()
    a.b("searched")
    a.addiu("$t1", "$t0", -1)                          # left half blank: before j
    a.label("after")
    a.b("searched")
    a.addiu("$t1", "$t0", 0)
    a.label("nextj")
    a.b("search")
    a.addiu("$t0", "$t0", -1)
    a.label("searched")
    a.bltz("$t1", "reset")                             # no break: hard cut
    a.addiu("$v1", "$t2", -1)
    a.beq("$t1", "$v1", "reset")                       # break after the last cell
    a.sll("$v1", "$t1", 1)                             # = the cut itself
    # insert 0x818F after cell p: shift buf[ins..out) up by 2
    a.addu("$v1", "$v1", "$t6")
    a.lhu("$a0", 0, "$v1")
    a.nop()
    a.addu("$a0", "$a0", "$t7")
    a.addiu("$a0", "$a0", 2)                           # ins
    a.addiu("$v0", "$t4", -1)
    a.label("move")
    a.sltu("$v1", "$v0", "$a0")
    a.bne("$v1", "$zero", "moved")
    a.nop()
    a.lbu("$v1", 0, "$v0")
    a.nop()
    a.sb("$v1", 2, "$v0")
    a.b("move")
    a.addiu("$v0", "$v0", -1)
    a.label("moved")
    a.ori("$v1", "$zero", NEWLINE >> 8)
    a.sb("$v1", 0, "$a0")
    a.ori("$v1", "$zero", NEWLINE & 0xFF)
    a.sb("$v1", 1, "$a0")
    a.addiu("$t4", "$t4", 2)
    # the new row is cells p+1..W-1, each 2 bytes further on
    a.addiu("$v0", "$t1", 1)                           # source index
    a.addiu("$v1", "$zero", 0)                         # destination index
    a.label("shift")
    a.sltu("$at", "$v0", "$t2")
    a.beq("$at", "$zero", "shifted")
    a.sll("$a0", "$v0", 1)
    a.addu("$a0", "$a0", "$t6")
    a.lhu("$a0", 0, "$a0")
    a.sll("$at", "$v1", 1)
    a.addiu("$a0", "$a0", 2)
    a.addu("$at", "$at", "$t6")
    a.sh("$a0", 0, "$at")
    a.addiu("$v0", "$v0", 1)
    a.b("shift")
    a.addiu("$v1", "$v1", 1)
    a.label("shifted")
    a.b("place")
    a.addiu("$t5", "$v1", 0)
    a.label("reset")
    a.addiu("$t5", "$zero", 0)
    a.label("place")                                   # cells[n++] = out - buf
    a.subu("$v0", "$t4", "$t7")
    a.sll("$v1", "$t5", 1)
    a.addu("$v1", "$v1", "$t6")
    a.sh("$v0", 0, "$v1")
    a.b("emit")
    a.addiu("$t5", "$t5", 1)
    a.label("newline")
    a.addiu("$t5", "$zero", 0)
    a.label("emit")                                    # the 2 bytes at src-2
    a.lbu("$t0", -2, "$t3")
    a.lbu("$t1", -1, "$t3")
    a.addiu("$t4", "$t4", 2)
    a.sb("$t0", -2, "$t4")
    a.b("guard")
    a.sb("$t1", -1, "$t4")
    a.label("colour")                                  # ＠ + its argument: 0 cells
    a.lbu("$t0", -2, "$t3")
    a.lbu("$t1", -1, "$t3")
    a.lbu("$v0", 0, "$t3")
    a.lbu("$v1", 1, "$t3")
    a.sb("$t0", 0, "$t4")
    a.sb("$t1", 1, "$t4")
    a.sb("$v0", 2, "$t4")
    a.sb("$v1", 3, "$t4")
    a.addiu("$t3", "$t3", 2)
    a.addiu("$t4", "$t4", 4)
    a.label("guard")
    a.addiu("$v0", "$t7", BUF_LEN - 8)
    a.sltu("$v1", "$v0", "$t4")
    a.beq("$v1", "$zero", "loop")
    a.nop()
    a.label("bail")                                    # too long / odd width:
    a.lw("$s3", SAVE_ORIG, "$t9")                      # render the original
    a.b("done")
    a.nop()
    a.label("finish")
    a.sb("$zero", 0, "$t4")
    a.addiu("$s3", "$t7", 0)
    a.label("done")
    a.lw("$ra", SAVE_RA, "$t9")
    a.lw("$a0", DEST_OFF, "$sp")
    a.j(RESUME)
    a.nop()
    # --- halves(a0 = &sjis) -> v0: bit0 left half blank, bit1 right half ----
    a.label("halves")
    a.sw("$t0", SAVE_T0, "$t9")
    a.sw("$t1", SAVE_T1, "$t9")
    a.lbu("$v0", 0, "$a0")
    a.lbu("$v1", 1, "$a0")
    a.sll("$v0", "$v0", 8)
    a.or_("$v0", "$v0", "$v1")
    a.addiu("$v1", "$v0", 0x7EC0)                      # code - 0x8140 mod 2^16
    a.andi("$v1", "$v1", 0xFFFF)                       # (the engine's own test)
    a.sltiu("$v1", "$v1", 0x1734)                      # outside the font: the
    a.beq("$v1", "$zero", "blank")                     # engine draws a blank
    a.lui("$at", RANGE_TAB >> 16)
    a.ori("$at", "$at", RANGE_TAB & 0xFFFF)
    a.addiu("$a0", "$at", 4)                           # &entry[1]
    a.addiu("$t0", "$at", RANGE_END - RANGE_TAB)
    a.label("walk")                                    # first start > code
    a.lhu("$v1", 0, "$a0")
    a.nop()
    a.sltu("$v1", "$v0", "$v1")
    a.bne("$v1", "$zero", "walked")
    a.nop()
    a.addiu("$a0", "$a0", 4)
    a.bne("$a0", "$t0", "walk")
    a.nop()
    a.label("walked")                                  # entry i-1 = a0 - 4
    a.lhu("$v1", -2, "$a0")                            # base[i-1]
    a.lhu("$at", -4, "$a0")                            # start[i-1]
    a.addu("$v0", "$v0", "$v1")
    a.subu("$v0", "$v0", "$at")                        # slot
    a.sll("$v1", "$v0", 3)
    a.addu("$v1", "$v1", "$v0")
    a.sll("$v1", "$v1", 1)                             # * 18
    a.lui("$at", GLYPHS >> 16)
    a.ori("$at", "$at", GLYPHS & 0xFFFF)
    a.addu("$a0", "$v1", "$at")                        # glyph
    a.addiu("$v0", "$zero", 0)                         # left ink
    a.addiu("$v1", "$zero", 0)                         # right ink
    a.addiu("$t1", "$a0", 18)
    # 3 bytes = 2 rows of 12 bits, MSB first: b0 = row0[11..4], b1 =
    # row0[3..0] row1[11..8], b2 = row1[7..0]; left = bits 11..6
    a.label("group")
    a.lbu("$t8", 0, "$a0")
    a.lbu("$t0", 1, "$a0")
    a.andi("$at", "$t8", 0xFC)
    a.or_("$v0", "$v0", "$at")
    a.andi("$at", "$t8", 0x03)
    a.or_("$v1", "$v1", "$at")
    a.andi("$at", "$t0", 0x0F)
    a.or_("$v0", "$v0", "$at")
    a.andi("$at", "$t0", 0xF0)
    a.or_("$v1", "$v1", "$at")
    a.lbu("$t8", 2, "$a0")
    a.addiu("$a0", "$a0", 3)
    a.andi("$at", "$t8", 0xC0)
    a.or_("$v0", "$v0", "$at")
    a.andi("$at", "$t8", 0x3F)
    a.bne("$a0", "$t1", "group")
    a.or_("$v1", "$v1", "$at")
    a.sltiu("$v0", "$v0", 1)
    a.sltiu("$v1", "$v1", 1)
    a.sll("$v1", "$v1", 1)
    a.b("halved")
    a.or_("$v0", "$v0", "$v1")
    a.label("blank")
    a.ori("$v0", "$zero", 3)
    a.label("halved")
    a.lw("$t0", SAVE_T0, "$t9")
    a.lw("$t1", SAVE_T1, "$t9")
    a.jr("$ra")
    a.nop()
    return a


def resident():
    """The RESIDENT image: code, zero-filled to the buffers."""
    a = code()
    img = a.assemble()
    assert len(img) <= BUF_OFF, f"wrap stub is {len(img)} B, over {BUF_OFF:#x}"
    return img + b"\0" * (RESIDENT_LEN - len(img))


def apply():
    exe = bytearray(open(EXE, "rb").read())
    fo = HOOK_AT - EXEC_RAM + HDR
    cur = struct.unpack_from("<II", exe, fo)
    want_move = 0x00809821                             # move s3, a0
    labels = code().labels()
    j = 0x08000000 | (labels["wrap"] >> 2) & 0x3FFFFFF
    if cur == (j, want_move):
        print("wordwrap: hook already in place")
        return
    assert cur == (want_move, 0x8FA40AEC), f"unexpected code at {HOOK_AT:#x}: {cur[0]:#x} {cur[1]:#x}"
    # the lw a0, 0xaec(sp) moves into the stub; the move stays as the delay slot
    struct.pack_into("<II", exe, fo, j, want_move)
    open(EXE, "wb").write(exe)
    print(f"wordwrap: j {labels['wrap']:#x} at {HOOK_AT:#x}; resident {len(code().assemble())} B "
          f"(copied by bootcard.py)")


# --- the same algorithm in Python, for lint and for the validators --------

def _cells(text, pf):
    """The engine's row units for an English line: [(cell_text, left_blank,
    right_blank)] per row unit, with '\n' entries for ￥ and colour codes
    dropped (zero cells)."""
    from textcodec import char_to_code
    out = []
    buf = ""

    def flush():
        nonlocal buf
        if not buf:
            return
        if len(buf) % 2:
            buf += " "
        for k in range(0, len(buf), 2):
            pair = buf[k:k + 2]
            if pair in pf.table:
                out.append((pair, pair[0] == " ", pair[1] == " "))
            else:                                      # fallback: two fullwidth
                for ch in pair:
                    out.append((ch, ch == " ", ch == " "))
        buf = ""

    i = 0
    while i < len(text):
        ch = text[i]
        if ord(ch) < 0x80:
            buf += ch
        else:
            flush()
            if ch == "￥":
                out.append(("\n", False, False))
            elif ch == "＠":
                i += 1                                 # colour / Ｃ: no cell
            elif ch == "　":
                out.append((ch, True, True))
            else:
                out.append((ch, ch in "。、，．", ch in "。、，．"))
        i += 1
    flush()
    return out


def wrap_rows(text, width, pf=None):
    """Rows as the patched engine draws them: list of strings (a fallback
    fullwidth letter counts as one cell like the pair)."""
    if pf is None:
        from pairfont import PairFont
        pf = PairFont()
    rows, row = [], []
    for unit in _cells(text, pf):
        if unit[0] == "\n":
            rows.append(row)
            row = []
            continue
        if len(row) == width:
            p = -1
            for j in range(width - 1, -1, -1):
                if row[j][2]:
                    p = j
                    break
                if row[j][1] and j > 0:
                    p = j - 1
                    break
            if p < 0 or p == width - 1:
                rows.append(row)
                row = []
            else:
                rows.append(row[:p + 1])
                row = row[p + 1:]
        row.append(unit)
    rows.append(row)
    return ["".join(u[0] for u in r) for r in rows if r]


def show(scene, width=18):
    from pairfont import PairFont
    pf = PairFont()
    for rec in json.load(open(os.path.join(ROOT, "ps1/translation", f"ISZ_{scene}.json"), encoding="utf-8"))["strings"]:
        if rec.get("lock") or not rec.get("en"):
            continue
        print(f"--- {rec['off']}")
        for r in wrap_rows(rec["en"], width, pf):
            print(f"  |{r}|")


def lint(width=18):
    """Strings whose ￥-rows exceed `width` cells (the engine cuts them; the
    wrap now breaks at a word, but the ragged result is worth a look)."""
    from pairfont import PairFont
    pf = PairFont()
    n = 0
    for f in sorted(os.listdir(os.path.join(ROOT, "ps1/translation"))):
        if not f.startswith("ISZ_"):
            continue
        for rec in json.load(open(os.path.join(ROOT, "ps1/translation", f), encoding="utf-8"))["strings"]:
            if rec.get("lock") or not rec.get("en"):
                continue
            units = _cells(rec["en"], pf)
            row = 0
            for u in units:
                row = 0 if u[0] == "\n" else row + 1
                if row > width:
                    print(f"{f} {rec['off']}: {rec['en']}")
                    n += 1
                    break
    print(f"{n} strings over {width} cells")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "apply":
        apply()
    elif cmd == "show":
        show(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 18)
    elif cmd == "lint":
        lint(int(sys.argv[2]) if len(sys.argv) > 2 else 18)
    elif cmd == "size":
        print(len(code().assemble()))
