"""The engine patch for English text: stubs in stage 2 (pcepair, dictionary).

Stage 2 (track sectors 22-36) is resident in SysCard RAM banks $68-$6A; the
text engine's bank 2 (file offset 0x4000-0x5FFF) is mapped at $6000-$7FFF
whenever the decoder or the glyph fetch runs. The stubs live in the old
speaker-name list's bytes ($6D47-$6FBB, 629 B; the names move into the
modules), all reads of module data go through the engine's own linear
fetch ($5341: $90/$91 = offset from the module base, $92 = 0, maps MPR6).

Hooks (file offset = address - 0x2000):
  $648C  JSR $69C2 -> JSR compose   glyph fetch: with the English flag up (or,
                                    outside a message - menus, verb lists -
                                    with the module's ALL_EN byte set), a
                                    code in rows 0x88-0x98 is a letter pair,
                                    drawn from the module's font at FONT_OFF
                                    into the 32-byte glyph buffer (12-bit
                                    rows, high byte then low nibble << 4)
  $733F  AND #$0C; ASL -> JMP dhook decoder: rows 0x81-0x84 branch; row
                                    0x84 lo 0x40 raises the English flag and
                                    the other row-0x84 codes are dictionary
                                    entries (slot = lo - 0x41, table at
                                    DICT_PTR, an entry is a plain string)
  $7290  JMP $7357 -> JMP dend      decoder end-of-string, byte boundary
  $7357  LDA #1;STA $3607 -> dend   decoder end-of-string, n=0 code
  $7204  message init -> minit      clears the flag (new message)
  $7521  row-loop exit -> mend       message end: the flag drops once the last
  $66F5 STZ $3470 -> rdone, $689B -> rclr   row drawn / the window rebuilt (gwin, #43)
  $70A7  name lookup -> ncopy       the speaker name comes from the module:
                                    a pointer at NAMES_PTR to a table of 74
                                    u16 offsets, each entry {attr, SJIS.., FF}
                                    as the old stage-2 list, mapped through
                                    MPR6 and handed to $71AA in place (an
                                    entry must not cross an 8 KB bank)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

from asm6280 import assemble
import patch_pce as P
import pcepair

STAGE2_BASE = 0x2000          # file offset + this = address in the text bank
AREA = 0x6D47                 # the old name list
AREA_END = 0x6FBC
AREA2 = 0x7F50                # 176 bytes of 0xFF filler at the bank's end
AREA2_END = 0x8000
FETCH = 0x5341
DECODE = 0x7272
NAMES_PTR = 0x7FFE            # module-relative: u16 offset of the name table
DICT_PTR = 0x7FFC             # module-relative: u16 offset of the dictionary slot table
ALL_EN = 0x7FFB               # module-relative: 1 = every string is English (no markers)
PAIRS_PTR = pcepair.PAIRS_PTR # module-relative: u16 offset of the pair table (slot -> glyphs)

SOURCE = f"""
AL   = 0xF8
AH   = 0xF9
BL   = 0xFA
BH   = 0xFB
P90  = 0x90
E0   = 0xE0
E1   = 0xE1
PHASE = 0x360C
FETCH = {FETCH}
DECODE = {DECODE}
FONT = {pcepair.FONT_OFF}
NAMES_PTR = {NAMES_PTR}
DICT_PTR = {DICT_PTR}
ALL_EN = {ALL_EN}
PAIRS_PTR = {PAIRS_PTR}

; ---- variables (SysCard RAM is writable) ----
eng:     .byte 0          ; English flag
indict:  .byte 0          ; inside a dictionary entry
la:      .word 0          ; font row pointers
ra:      .word 0
mpr6:    .byte 0
sv_e0:   .word 0          ; the outer string pointer while in a dictionary entry
sv_ph:   .byte 0
pclr:    .byte 0          ; drop the English flag once the pending row is drawn
tmp:     .word 0
acc:     .word 0

; ---- glyph fetch hook: replaces JSR $69C2 ----
compose:
  LDA eng
  BNE on
  ; menus and verb lists draw outside any message, where minit never ran:
  ; ask the module whether all of its text is English (one fetch, and only
  ; while the flag is down) and latch it
  TMA #0x40
  PHA
  STZ P90+2
  LDA #lo(ALL_EN)
  STA P90
  LDA #hi(ALL_EN)
  STA P90+1
  JSR FETCH
  STA eng
  PLA
  TAM #0x40
  LDA eng
  BEQ to_orig
on:
  LDA AH
  CMP #0x88
  BEQ go             ; the two half rows the codec's n=8 case splits
  CMP #0x98
  BEQ row98
  CMP #0x89
  BCC to_orig
  CMP #0x98
  BCC go
to_orig:
  JMP 0x69C2
row98:
  LDA AL             ; row 0x98 is a pair only under 0x9F: from 0x9F up it is
  CMP #0x9F          ; JIS level 2, which the ending's credit roll draws as
  BCC go             ; its own tiles (a logo) with the English flag up
  BRA to_orig
go:
  TMA #0x40
  STA mpr6
  STZ P90+2
  JSR slot           ; la = first glyph, ra = second (the module's pair table)
  ; la = FONT + a*12, ra = FONT + b*12
  LDA la
  JSR mul12
  STA la
  STX la+1
  LDA ra
  JSR mul12
  STA ra
  STX ra+1
  CLY
row:
  LDA la
  STA P90
  LDA la+1
  STA P90+1
  JSR FETCH
  ASL A
  ASL A
  STA tmp            ; L << 2
  LDA ra
  STA P90
  LDA ra+1
  STA P90+1
  JSR FETCH
  PHA
  LSR A
  LSR A
  LSR A
  LSR A
  ORA tmp
  STA (BL),Y         ; row bits 11..4
  INY
  PLA
  ASL A
  ASL A
  ASL A
  ASL A
  STA (BL),Y         ; row bits 3..0 << 4
  INY
  INC la
  BNE nc1
  INC la+1
nc1:
  INC ra
  BNE nc2
  INC ra+1
nc2:
  CPY #24
  BNE row
  CLA
pad:
  STA (BL),Y
  INY
  CPY #0x80          ; rows 12-15 and the overflow/second-layer buffers
  BNE pad
  LDA mpr6
  TAM #0x40
  CLA                ; 0 = glyph supplied, skip the BIOS
  RTS

mul12:               ; A = glyph (< 95) -> A (lo), X (hi) = FONT + index*12
  STA tmp
  STZ acc+1
  ASL A              ; 2x (x < 128: no carry)
  CLC
  ADC tmp            ; 3x, the ninth bit in carry
  ROL acc+1
  ASL A
  ROL acc+1
  ASL A
  ROL acc+1          ; 12x, 16-bit
  CLC
  ADC #lo(FONT)
  STA acc
  LDA acc+1
  ADC #hi(FONT)
  TAX
  LDA acc
  RTS

; ---- decoder hooks ----
dhook:               ; A = n, from $733F (rows 0x81-0x84 branch)
  PHA
  AND #3
  CMP #3
  BEQ row84
  PLA
  AND #0x0C
  ASL A
  JMP 0x7342
row84:
  PLA
  JSR lo_of          ; lo = ((n & 0xC) << 4) | b
  CMP #0x40
  BNE dentry
  LDA #1
  STA eng
  JMP DECODE         ; marker consumed: produce the next character
dentry:
  SEC
  SBC #0x41          ; entry index
  CLC                ; (the SBC leaves carry set: no ninth bit here)
dslot:
  STA tmp
  CLA
  ROL A              ; (carry from the ADC/SBC) -> slot high bit
  STA tmp+1
  ASL tmp
  ROL tmp+1          ; tmp = slot*2
  LDA #lo(DICT_PTR)
  STA acc
  LDA #hi(DICT_PTR)
  STA acc+1
  JSR rd_acc         ; table offset lo
  PHA
  JSR inc_acc
  JSR rd_acc         ; table offset hi
  TAX
  PLA
  CLC
  ADC tmp
  STA acc
  TXA
  ADC tmp+1
  STA acc+1          ; acc = &table[slot]
  JSR rd_acc         ; entry offset lo
  PHA
  JSR inc_acc
  JSR rd_acc         ; entry offset hi
  TAX
  LDA E0
  STA sv_e0
  LDA E1
  STA sv_e0+1
  LDA PHASE
  STA sv_ph
  PLA
  STA E0
  STX E1
  STZ PHASE
  LDA #1
  STA indict
  JMP DECODE

dend:
  LDA indict
  BEQ realend
  STZ indict
  LDA sv_e0
  STA E0
  LDA sv_e0+1
  STA E1
  LDA sv_ph
  STA PHASE
  JMP DECODE
realend:
  LDA #1
  STA 0x3607
  RTS

; ---- speaker name from the module ----
ncopy:               ; Y = index*2, replaces the table read + JSR $71AA at $70A7
  STY tmp
  LDA #lo(NAMES_PTR)
  STA acc
  LDA #hi(NAMES_PTR)
  STA acc+1
  JSR rd_acc
  PHA
  JSR inc_acc
  JSR rd_acc
  STA acc+1
  PLA
  STA acc            ; acc = table offset
  CLC
  LDA acc
  ADC tmp
  STA acc
  LDA acc+1
  ADC #0
  STA acc+1          ; acc = &table[index]
  JSR rd_acc
  STA tmp
  JSR inc_acc
  JSR rd_acc
  STA acc+1
  LDA tmp
  STA acc            ; acc = entry offset
  JSR rd_acc         ; maps MPR6 to the entry's bank; $90/$91 = its address
  LDA P90
  STA 0xFE
  LDA P90+1
  STA 0xFF
  JMP 0x71AA         ; copies from (_dl) as it did from the stage-2 list
lo_of:               ; A = n -> A = ((n & 0xC) << 4) | b   (b in $360E)
  AND #0x0C
  ASL A
  ASL A
  ASL A
  ASL A
  ORA 0x360E
  RTS
rd_acc:              ; A = module byte at acc
  LDA acc
  STA P90
  LDA acc+1
  STA P90+1
  STZ P90+2
  JMP FETCH
inc_acc:
  INC acc
  BNE ia_out
  INC acc+1
ia_out:
  RTS

mend:                ; replaces the row-loop exit test at $7521: the English
                     ; flag drops when the MESSAGE ends (not on a full page),
                     ; so the raw-SJIS menus that follow keep their kanji
  LDA 0x3607
  BNE mdone
  LDA 0x3608
  CMP #3
  BEQ mdone
  INC 0x3601
  LDA 0x3601
  CMP #4
  BCS mpage
  CLC
  RTS
mdone:
  LDA 0x3470         ; a row still to be drawn? then drop the flag after it
  BEQ mnow
  LDA #1
  STA pclr
  BRA mpage
mnow:
  STZ eng
mpage:
  SEC
  RTS

rdone:               ; replaces STZ $3470 where the renderer finishes a row
  STZ 0x3470
  LDA pclr
  BEQ rd_out
  STZ pclr
  STZ eng
rd_out:
  RTS
rclr:                ; replaces the STZ $3470 at $689B: the game rebuilds its window (a list or a
  LDA #1             ; message opening) - any draw in progress is aborted and the text area
  STA gwin           ; cleared at the base in $3F32. The stub reads gwin each pass: the window
  JMP rdone          ; is the game's now (#43). The base is the game's: the stub no longer moves
                     ; it, and the ending clears 0x4000-0x7FFF through here at bases of its own
                     ; (forcing 0x7000 left the credits' bitmap edges dirty - #89)
gwin: .byte 0

minit:               ; replaces LDA $E0; STA $3609 at $7204
  STZ indict
  STZ pclr
  TMA #0x40
  PHA
  LDA #lo(ALL_EN)
  STA acc
  LDA #hi(ALL_EN)
  STA acc+1
  JSR rd_acc         ; 1 when every string in the module is English
  STA eng
  PLA
  TAM #0x40
  LDA E0
  STA 0x3609
  RTS
"""

SOURCE2 = f"""
AH   = 0xF9
PAIRS_PTR = {PAIRS_PTR}
AL   = 0xF8

; slot: hi/lo of a pair code -> la = first glyph, ra = second.
; Lead bytes 0x89-0x97 are contiguous, so row = hi - 0x89 and
; slot = row*184 + col; rows 0x98 and 0x88 carry the last 188 slots (the
; two halves of the codec's n=8 case). The glyphs are the module's pair
; table entry for the slot (PAIRS_PTR; see pcepair).
slot:
  LDA AH
  CMP #0x98
  BEQ half98
  CMP #0x88
  BEQ half88
  SEC
  SBC #0x89          ; rows 0x89..0x97 are contiguous
  STA rowc
  STZ acc
  STZ acc+1
mulrow:
  LDX rowc
  BEQ muldone
  CLC
  LDA acc
  ADC #184
  STA acc
  LDA acc+1
  ADC #0
  STA acc+1
  DEC rowc
  BRA mulrow
muldone:
  JSR column
  CLC
  ADC acc
  STA acc
  LDA acc+1
  ADC #0
  STA acc+1          ; acc = slot
  BRA divide

half88:              ; slots 2854.. : row 0x88, trail byte from 0x9F
  LDA AL
  SEC
  SBC #0x9F - 94     ; 94 slots past row 0x98's
  BRA halftail
half98:              ; slots 2760.. : row 0x98, trail byte under 0x9F
  JSR column
halftail:
  CLC
  ADC #lo(2760)
  STA acc
  CLA
  ADC #hi(2760)
  STA acc+1

divide:              ; acc = slot -> la, ra = the glyphs of the module's table entry
  ASL acc
  ROL acc+1          ; slot*2
  LDA acc
  STA tmp
  LDA acc+1
  STA tmp+1
  LDA #lo(PAIRS_PTR)
  STA acc
  LDA #hi(PAIRS_PTR)
  STA acc+1
  JSR rd_acc         ; the table's offset, lo
  PHA
  JSR inc_acc
  JSR rd_acc         ; hi
  TAX
  PLA
  CLC
  ADC tmp
  STA acc
  TXA
  ADC tmp+1
  STA acc+1          ; acc = &table[slot]
  JSR rd_acc
  STA la
  JSR inc_acc
  JSR rd_acc
  STA ra
  RTS
column:              ; A = the trail byte's column (0x7F is not a trail byte)
  LDA AL
  SEC
  SBC #0x40
  CMP #0x40
  BCC colok
  DEC A
colok:
  RTS
rowc: .byte 0
"""

PATCHES = {   # address: (expected bytes, replacement built from labels)
    0x648C: ("20 c2 69", lambda e: bytes([0x20]) + e["compose"].to_bytes(2, "little")),
    0x733F: ("29 0c 0a", lambda e: bytes([0x4C]) + e["dhook"].to_bytes(2, "little")),
    0x7290: ("4c 57 73", lambda e: bytes([0x4C]) + e["dend"].to_bytes(2, "little")),
    0x7357: ("a9 01 8d 07 36 60", lambda e: bytes([0x4C]) + e["dend"].to_bytes(2, "little") + b"\xea\xea\xea"),
    0x7204: ("a5 e0 8d 09 36", lambda e: bytes([0x20]) + e["minit"].to_bytes(2, "little") + bytes([0xEA] * 2)),
    0x66F5: ("9c 70 34", lambda e: bytes([0x20]) + e["rdone"].to_bytes(2, "little")),
    0x689B: ("9c 70 34", lambda e: bytes([0x20]) + e["rclr"].to_bytes(2, "little")),
    0x7521: ("ad 07 36 d0 13", lambda e: bytes([0x4C]) + e["mend"].to_bytes(2, "little") + bytes([0xEA] * 2)),
    0x70A7: ("b9 28 6f 85 fe b9 29 6f 85 ff 20 aa 71",
             lambda e: bytes([0x20]) + e["ncopy"].to_bytes(2, "little") + bytes([0xEA] * 10)),
}


def build():
    """((bytes at AREA, bytes at AREA2), label env)."""
    seed = {k: 0x8000 for k in ("acc", "la", "ra", "tmp", "rd_acc", "inc_acc")}
    code2, env2 = assemble(SOURCE2, AREA2, seed)          # for its labels
    code, env = assemble(SOURCE, AREA, env2)
    code2, env2 = assemble(SOURCE2, AREA2, env)           # now with the real variables
    if AREA + len(code) > AREA_END:
        raise SystemExit(f"stubs {len(code)}B exceed the {AREA_END - AREA}B area")
    if AREA2 + len(code2) > AREA2_END:
        raise SystemExit(f"helpers {len(code2)}B exceed the {AREA2_END - AREA2}B area")
    env.update({k: v for k, v in env2.items() if k not in env})
    return (code, code2), env


def install(img):
    """Write the stubs and hooks into stage 2 on `img` (patch_pce.Image)."""
    (code, code2), env = build()
    base = (P.T2 + P.STAGE2) * P.DATA - STAGE2_BASE     # image offset of address 0
    img.write(base + AREA, code)
    img.write(base + AREA2, code2)
    for addr, (expect, make) in PATCHES.items():
        have = bytes(img.data[base + addr:base + addr + len(bytes.fromhex(expect))])
        if have != bytes.fromhex(expect):
            raise SystemExit(f"stage 2 at {addr:#06x}: {have.hex(' ')}, expected {expect}")
        img.write(base + addr, make(env))
    return len(code) + len(code2)


if __name__ == "__main__":
    (code, code2), env = build()
    print(f"{len(code)}B at {AREA:#06x} (of {AREA_END - AREA}), "
          f"{len(code2)}B at {AREA2:#06x} (of {AREA2_END - AREA2}); "
          f"compose {env['compose']:#06x} slot {env['slot']:#06x}")
