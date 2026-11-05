"""Gaudi's name search with Latin names: the row scan compares whole names.

The search is two-step (rec 110, the resident system file, base $6000). The
script keeps fifteen kana row records in module 254 (ア, イウエオ, カキクケコ...)
and files the names under them in its bytecode; on 決定 the engine walks
the row records ($3540 table, entries copied to $D4/$D5, records fetched
through $5341) and, with $34BA = 1, takes the FIRST row whose record
contains the typed name's first character - a scan of consecutive byte
pairs against $363E/$363F at $BA41 - then compares the typed name with
that row's names. Names filed by their Japanese kana carry Latin initials
the kana rows cannot index (CATHERINE and CHIEF under カ, CHIN under タ),
and the rows must stay as they are (the keyboard is built on them), so
the block at $BA41 jumps to a stub in the file's free tail ($BE56) that
answers "does this row hold the typed name": pcescript writes a table into
module 254 - `{row, name}` offset pairs from the bytecode's filing, 0xFFFF
after the last, at the offset in SEARCH_PTR (0x7FF9) - and the stub
compares the typed name with every name filed under the row at ($D4).
The same scan serves the videophone (modules 174 and 190 file the numbers
under single-digit rows), so a module whose SEARCH_PTR is 0 or FFFF gets
the engine's own scan back - until 2026-09-13 every number dialled came
back "not in service".

The typed length is clamped to 8 or more as well (CLAMP below), and the
input's kind (keyboard or pad) no longer hangs on the catch-all record's
lead byte (MODE below: the hospital-list search opened as a hidden number
pad once ＱＵＥＥＮ以外 replaced クイーン以外).

  python pce/tools/pcesearch.py apply     # into patched/pce/snatcher_pce.bin
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

from asm6280 import assemble
import patch_pce as P
import pcescene as S

SYSTEM = (110, 12)
BASE = 0x6000                 # the file's load address
SCAN = 0xBA41                 # the first-character row scan (mode 1)
STUB = 0xBE56                 # free zeros to $BFFF
FETCH = 0x5341                # A = module byte at ($90/$91 + $92), maps MPR6
SEARCH_PTR = 0x7FF9           # module-relative: the table, {row u16, name u16}.., FFFF

SOURCE = f"""
TYPED = 0x363E
FETCH = {FETCH}
SEARCH_PTR = {SEARCH_PTR}
; the row scan: ($D4) is the row record's module offset, X the caller's
; record index (kept); found = carry clear. The variables come first: the
; assembler sizes a reference to a label it has not met as zero page.
  JMP scan
tbl:  .word 0
row:  .word 0
name: .word 0
scan:
  ; tbl = [SEARCH_PTR] (FETCH keeps X and Y)
  LDA #lo(SEARCH_PTR)
  STA 0x90
  LDA #hi(SEARCH_PTR)
  STA 0x91
  STZ 0x92
  JSR FETCH
  STA tbl
  LDA #lo(SEARCH_PTR)
  STA 0x90
  LDA #hi(SEARCH_PTR)
  STA 0x91
  LDA #1
  STA 0x92
  JSR FETCH
  STA tbl+1
  ; a module with no table (0 or FFFF there: the videophone's dial lists in 174 and 190
  ; file the numbers under their first digit the same way) keeps the engine's own scan
  LDA tbl
  ORA tbl+1
  BEQ orig
  LDA tbl
  AND tbl+1
  CMP #0xFF
  BEQ orig
  PHX
  PHY
  BRA entry
orig:                 ; the three bytes the jump replaced, then the scan as it was
  INY
  STZ 0x92
  JMP {SCAN + 3}
entry:
  LDY #0
  JSR tfetch          ; row lo
  STA row
  LDY #1
  JSR tfetch
  STA row+1
  CMP #0xFF
  BNE have
  LDA row
  CMP #0xFF
  BEQ fail            ; FFFF: the table's end
have:
  LDA row
  CMP 0xD4
  BNE skip
  LDA row+1
  CMP 0xD5
  BNE skip
  LDY #2
  JSR tfetch          ; name lo
  STA name
  LDY #3
  JSR tfetch
  STA name+1
  LDY #0
cmp:
  LDA name
  STA 0x90
  LDA name+1
  STA 0x91
  STY 0x92
  JSR FETCH           ; A = name[Y]
  CMP TYPED,Y
  BNE skip
  CMP #0xFF
  BEQ found           ; both ended together
  INY
  BRA cmp
skip:
  CLC
  LDA tbl
  ADC #4
  STA tbl
  LDA tbl+1
  ADC #0
  STA tbl+1
  BRA entry
found:
  PLY
  PLX
  CLC
  RTS
fail:
  PLY
  PLX
  SEC
  RTS
tfetch:               ; A = table byte Y
  LDA tbl
  STA 0x90
  LDA tbl+1
  STA 0x91
  STY 0x92
  JMP FETCH
"""


# The typed length. The keyboard's opener keeps the script's maximum in $34B9 (0 = its own
# default: 10 or 12 for the name search) and the typing routine ($B98E) refuses letters past
# it: the videophone's code words are 4 kana, so 4 - and REIGN, BENSON, QUEEN cannot be typed.
# Both sites (`LDA $34B9 / BNE $B793`, $B754 and $B784) go through a clamp that keeps a set
# length at 8 or more and reproduces each site's default when it is 0.
CLAMP = 0xBF40
CLAMP_SOURCE = """
LIMIT = 0x34B9
COL = 0x36B6
clampa:
  LDA LIMIT
  BNE cl
  LDA #6
  STA COL
  LDA #0x0A
  STA LIMIT
  RTS
clampb:
  LDA LIMIT
  BNE cl
  LDA #3
  STA COL
  LDA #0x0C
  STA LIMIT
  RTS
cl:
  CMP #8
  BCS ok
  LDA #8
  STA LIMIT
ok:
  RTS
"""
CLAMP_SITES = [(0xB754, bytes.fromhex("adb934d03a"), "clampa", 0x3A), (0xB784, bytes.fromhex("adb934d00a"), "clampb", 0x0A)]

# The input's kind comes from the catch-all matcher record the search opcode names: its
# first character's lead byte & 3 - katakana 0x83 = 3, the keyboard; 0x82 = 2, the phone's
# pad (the dial lists' digit rows). The English catch-alls are fullwidth Latin (ＱＵＥＥＮ以外,
# lead 0x82), which opened the hospital-list search as a hidden number pad: a Latin
# record (second byte 0x60 up: letters) counts as the keyboard, a digit one as the pad.
MODE = 0xBF70
MODE_SOURCE = f"""
FETCH = {FETCH}
mode:
  JSR FETCH              ; the record's first byte, at ($90/$91 + $92) = ($FE/$FF), mapped
  CMP #0x82
  BNE mask
  LDA 0xFE               ; the pointer again (FETCH turns $91 into the mapped page): + 1
  CLC
  ADC #1
  STA 0x90
  LDA 0xFF
  ADC #0
  STA 0x91
  STZ 0x92
  JSR FETCH              ; the second byte: a digit (0x4F-0x58) or a letter (0x60 up)
  CMP #0x60
  BCC pad
  LDA #3
  RTS
pad:
  LDA #2
  RTS
mask:
  AND #3
  RTS
"""
MODE_SITE = (0xB72B, bytes.fromhex("2041532903"))     # JSR FETCH; AND #3 -> JSR mode; NOP; NOP


def patches():
    """[(file offset, old bytes, new bytes)] for rec 110."""
    old = bytes(S.block(*SYSTEM))
    code, labels = assemble(SOURCE, STUB)
    at = STUB - BASE
    assert old[at:at + len(code)] == bytes(len(code)), "the stub's space is not free"
    assert STUB + len(code) <= CLAMP
    entry = old[SCAN - BASE:SCAN - BASE + 3]
    assert entry == bytes([0xC8, 0x64, 0x92]), f"the row scan moved: {entry.hex()}"
    jump = bytes([0x4C, STUB & 0xFF, STUB >> 8])
    out = [(at, old[at:at + len(code)], code), (SCAN - BASE, entry, jump)]
    ccode, cl = assemble(CLAMP_SOURCE, CLAMP)
    assert old[CLAMP - BASE:CLAMP - BASE + len(ccode)] == bytes(len(ccode)), "the clamp's space is not free"
    out.append((CLAMP - BASE, old[CLAMP - BASE:CLAMP - BASE + len(ccode)], ccode))
    for site, expect, entry_name, bra in CLAMP_SITES:
        assert old[site - BASE:site - BASE + 5] == expect, f"the keyboard opener moved at {site:#x}"
        target = cl[entry_name]
        out.append((site - BASE, expect, bytes([0x20, target & 0xFF, target >> 8, 0x80, bra])))
    mcode, ml = assemble(MODE_SOURCE, MODE)
    assert CLAMP + len(ccode) <= MODE and MODE + len(mcode) <= 0xC000
    assert old[MODE - BASE:MODE - BASE + len(mcode)] == bytes(len(mcode)), "the mode stub's space is not free"
    out.append((MODE - BASE, old[MODE - BASE:MODE - BASE + len(mcode)], mcode))
    site, expect = MODE_SITE
    assert old[site - BASE:site - BASE + 5] == expect, f"the input's mode fetch moved at {site:#x}"
    out.append((site - BASE, expect, bytes([0x20, MODE & 0xFF, MODE >> 8, 0xEA, 0xEA])))
    return out


def apply(out_path=P.OUT):
    img = P.Image(out_path, P.T3 + P.RESERVE)
    base = (S.T2 + SYSTEM[0]) * P.DATA
    for at, old, new in patches():
        assert bytes(img.data[base + at:base + at + len(old)]) == old, f"rec 110 at {at:#x} is not pristine"
        img.write(base + at, new)
    print(f"rec 110: the name search's row scan reads the module's table; {img.flush()} sectors written")


if __name__ == "__main__":
    apply()
