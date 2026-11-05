"""The Saturn's hidden wall paper sets, reachable and kept (Luiz, 2026-09-30:
"add the special options menu like we did on PS1").

The Saturn has no SPECIAL MENU; its one secret option is the wall paper set
(0 = JUNKER metal, 1 and 2 = Konami's alternates), cycled by the Konami code
(U U D D L R L R B A, halfword table at file 0x72C) on the title's PUSH
BUTTON screen: the index at 0x060E4B50 reaching 10 (`cmp/eq #10` at
0x060B08DC) steps u16 [0x060E4B54]+4 (0x26007104, warm-reset RAM) 0 -> 1 -> 2
-> 0 with a jingle. Only the CONTINUE loader (0x060C5EAC -> chunk 60's
0x864..0x90C) reads it; every room's own op 0x0F loads the default chunk, so
a New Game or an act change dropped the set. (work/saturn/special/: the
probes and wallpaper_matrix.png, the three sets per act.)

The picture is chosen in OPTIONS > WALLPAPERS (satoptmenu.py, run right after
this tool): ONE picture for the whole game, stored as `MAGIC << 8 | row` in
that word (row 0..8 = PICTURES, 9 = BLACK). The Konami code's step (+1, then
0 unless it reads 1 or 2) and the power-on garbage (0x060A) never carry the
0xA5 high byte, so any other value = never chosen = Konami's own behaviour,
each act's default plate. This tool keeps it in play:
  op 0x0F  the room script's load op (table word 0x060E4E2C -> 0x060B6424)
           -> `wp`, a copy of the handler: when the word is marked and the
           row is 0..8, any of the nine wall paper chunks asked for is
           swapped for PICTURES[row] before the loader 0x060B2624(chunk,
           dest, 0) - so every room and every act show it. Row 9 (BLACK)
           loads what is asked; satoptmenu's op 0x1D front blanks its
           palette. A chunk argument with bit 15 set is loaded as given (bit
           cleared, no swap): the menu's previews ask for 0x812D etc.
  CONTINUE the loader 0x060C5EAC sets scene-0 flag `set*3 + act` for chunk
           60's per-set blocks (0x864..0x90C); the set term is dropped
           (`mov.w @r1,r2` at 0x060C5EB0 -> `mov #0,r2`), so it always loads
           the act's default and `wp` swaps it - a marked word never makes a
           flag index past 3 (a BLACK set used to raise 0x0B/0x0C).
(The first cut also made START on the title's PUSH BUTTON screen the whole
Konami code - the table entry at 0x060B072C and the `cmp/eq #10` at
0x060B08DC; the menu replaced it, both stay pristine.)

Build: after satwrap, before satpack (the exec hole ledger keys on the
exec's sha1). `python saturn/tools/satspecial.py [--dry]`.
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
RAW = 0x8000                            # chunk argument flag: load as given (the menu's previews)
OP0F_WORD, OP0F = 0x060E4E2C, 0x060B6424
LOADER = 0x060B2624                     # (r4 chunk, r5 dest, r6 0) -> r0 != 0: not ready, the op repeats
SET_PTR = 0x060E4B54                    # -> the warm-reset block; +4 = u16 the chosen picture
MAGIC = 0xA5                            # the word's high byte once the menu stored a row
PICTURES = [0x12D, 0x12E, 0x12F,        # rows 0-2 ACT 1/2/3 (Konami's per-act defaults)
            0x13D, 0x13B, 0x13C,        # rows 3-5 TWINBEE / KONAMI / TOKIMEKI
            0x139, 0x13A, 0x13E]        # rows 6-8 ENDING / GRADIUS / TURBOCAR; row 9 = BLACK
BLACK_ROW = len(PICTURES)
CONT_AT, CONT_OLD, CONT_NEW = 0x060C5EB0, 0x6211, 0xE200   # CONTINUE: mov.w @r1,r2 -> mov #0,r2


def stub_program():
    return [
        # wp(r4 = the op's argument words {u16 chunk, u16 dest}) -> r0 = the next PC
        ("label", "wp"),
        ("mov.l", "r8", "@-r15"),
        ("sts.l", "pr", "@-r15"),
        ("mov", "r4", "r8"),
        ("mov.w", "@r8", "r4"),
        ("extu.w", "r4", "r4"),                 # the chunk the room asks for
        ("mov", "r4", "r2"),
        ("mov.l", f"=0x{RAW - 1:08x}", "r1"),
        ("and", "r1", "r4"),                    # the RAW flag off
        ("cmp/eq", "r4", "r2"),
        ("bf", "go"),                           # it was set: no swap
        ("mov.l", f"=0x{SET_PTR:08x}", "r1"),
        ("mov.l", "@r1", "r1"),
        ("mov.w", "@(4,r1)", "r0"),
        ("mov", "r0", "r3"),
        ("shlr8", "r3"),
        ("extu.b", "r3", "r3"),
        ("mov", f"#{MAGIC - 256}", "r1"),
        ("extu.b", "r1", "r1"),
        ("cmp/eq", "r1", "r3"),
        ("bf", "go"),                           # never chosen: Konami's own
        ("extu.b", "r0", "r3"),                 # the row
        ("mov", f"#{BLACK_ROW}", "r1"),
        ("cmp/hs", "r1", "r3"),
        ("bt", "go"),                           # BLACK (or past it): load as asked
        ("mov.l", "=wptab", "r5"),
        ("mov", f"#{len(PICTURES)}", "r6"),
        ("label", "scan"),
        ("mov.w", "@r5+", "r1"),
        ("extu.w", "r1", "r1"),
        ("cmp/eq", "r1", "r4"),
        ("bt", "hit"),
        ("dt", "r6"),
        ("bf", "scan"),
        ("bra", "go"),                          # not a wall paper
        ("nop",),
        ("label", "hit"),
        ("mov.l", "=wptab", "r5"),
        ("add", "r3", "r5"),
        ("add", "r3", "r5"),
        ("mov.w", "@r5", "r4"),
        ("extu.w", "r4", "r4"),                 # PICTURES[row]
        ("label", "go"),
        ("mov", "r8", "r1"),                    # the original handler from here (0x060B6432..)
        ("add", "#2", "r1"),
        ("mov.w", "@r1", "r5"),
        ("mov", "#0", "r6"),
        ("mov.l", f"=0x{LOADER:08x}", "r0"),
        ("jsr", "@r0"),
        ("nop",),
        ("tst", "r0", "r0"),
        ("bt", "ok"),
        ("mov.l", f"=0x{CTX + 0x556:08x}", "r1"),   # not ready: the flag, and the op runs again
        ("mov", "#1", "r2"),
        ("mov.w", "r2", "@r1"),
        ("add", "#-2", "r8"),
        ("bra", "out"),
        ("nop",),
        ("label", "ok"),
        ("add", "#4", "r8"),
        ("label", "out"),
        ("mov", "r8", "r0"),
        ("lds.l", "@r15+", "pr"),
        ("mov.l", "@r15+", "r8"),
        ("rts",),
        ("nop",),
        ("pool",),
        ("label", "wptab"),
    ] + [(".word", c) for c in PICTURES]


def assemble(addr):
    return sh2asm.asm(stub_program(), addr)


def main(argv):
    dry = "--dry" in argv
    exe = bytearray(open(OUT_MAIN, "rb").read())
    have = struct.unpack_from(">I", exe, OP0F_WORD - MAIN_BASE)[0]
    if have != OP0F:
        sys.exit(f"op 0x0F word {OP0F_WORD:#x} holds {have:#010x}, expected {OP0F:#010x}")
    have = struct.unpack_from(">H", exe, CONT_AT - MAIN_BASE)[0]
    if have != CONT_OLD:
        sys.exit(f"CONTINUE {CONT_AT:#x} holds {have:#06x}, expected {CONT_OLD:#06x}")
    led = satexec.load_ledger(bytes(exe))       # keyed on the exec as satwrap left it: before any edit
    struct.pack_into(">H", exe, CONT_AT - MAIN_BASE, CONT_NEW)
    probe, _ = assemble(satexec.HOLE_LO)
    addr = satexec.alloc(led, exe, "satspecial", len(probe), align=4)
    code, labels = assemble(addr)
    exe[addr - MAIN_BASE:addr - MAIN_BASE + len(code)] = code
    struct.pack_into(">I", exe, OP0F_WORD - MAIN_BASE, labels["wp"])
    print(f"satspecial: op 0x0F -> {labels['wp']:#x} (the chosen wall paper in every room; CONTINUE's set term off) "
          f"({len(code)} bytes in the hole)")
    os.makedirs(BUILD, exist_ok=True)
    with open(os.path.join(BUILD, "special_stub.txt"), "w", encoding="utf-8") as f:
        f.write(sh2asm.check(code, addr) + "\n")
    if dry:
        print("dry run: nothing written")
        return
    open(OUT_MAIN, "wb").write(bytes(exe))
    satexec.save_ledger(led, bytes(exe))
    print(f"wrote {OUT_MAIN}")


if __name__ == "__main__":
    main(sys.argv[1:])
