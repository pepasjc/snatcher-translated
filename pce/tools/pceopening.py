"""Subtitles for the opening's narration: the newsreel (CD-DA track 17) and Gillian's profile
(the end of track 19), carded from the PS1's INTRO reel (pce/translation/cdda_opening.json).

The opening runs before rec 110 (the resident stub) and the voice bank (the CD-DA clock) are
in: its two blocks, rec 858 (the disclaimer, the newsreel) and rec 758 (the city, the credits,
Gillian in the car, the building), load 100 sectors each over banks $6C-$84, and nothing else
of ours is resident. Both leave bank $6C's 0x1000-0x1FFF free (0xFF) and never write it, so
each carries there, at the same offsets, a stub of its own; the trampoline (pcesubs) tries
$6C at MPR4 after the module's fourth bank, with the same entry ($9000) and signature address.

The game's renderer is not used: it draws in the opening's main loop, and every page it drew
held the opening's pictures back ~6 frames (three seconds behind the narration by the
newsreel's end). The stub draws each page itself, from the vblank pass: the pages are wrapped,
centred and timed here, a row is 1-bit glyphs (pcepair's 6x12 font, beside the stub) ORed into
a 16 x 256 buffer and written as tiles (plane 0 the ink, plane 1 set everywhere: colour 3 on
colour 2, never the see-through 0 - the backdrop the pictures set, red or lavender, showed
through) to VRAM 0x7800-0x7FFF (unused by the opening's pictures and sprites while a cue can be
up), the BAT's rows 43-50 at columns 32-63 map them in palette 14 (the pictures use 0-3 and 15;
entry 2 = PAPER, black, and 3 = white set every pass), and two raster sections of its own show
them from line 192: slot 14 (line 0, the picture's scroll - the game's lowest enabled slot's,
else 0,0) and slot 15 (line 192, the band; its enable byte SPR_OFF, which stage 2's rewritten
raster path - rcr_patch - reads to turn the VDC's sprites off from the band to the frame's end,
so no picture sprite draws over the text), with
$27 = 1 so the vblank handler enables the RCR interrupt; all put back every pass (the opening's
scene changes clear them). The clock: the game's CD service pulses $2638 for one frame when a
play is confirmed and keeps the track's number (BCD) in $263B until the next play (0x17 at
frame 5451 of a fresh boot, 0x19 at 14696); the stub counts the vblank handler's frames ($1B)
from the pulse while $263B still names the track, and shows the page whose span holds the
count.

  $6C offset  what
  ..0x0FFF    the block's pages (as low as its free run allows)
  0x1000      the stub (entry $9000 at MPR4), its variables, the row buffer; "SB3" where the
              module stub's signature sits
  0x1A40      the font (80 glyphs x 12 rows, pcepair.halffont)
  0x1FFE      the pages' address (at MPR4)

A page: [track BCD][start u16][end u16][size][row: x0, n, n glyph indices] x 2 (frames from the
track's start; 0 ends the table).

  python pce/tools/pceopening.py show     # the pages
  python pce/tools/pceopening.py apply    # into patched/pce/snatcher_pce.bin
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

from asm6280 import assemble
import patch_pce as P
import pcepair
import pcescene as S
import pcesubs as U

BLOCKS = {858: (17,), 758: (19,)}      # the tracks each block's pages cover
FREE = {858: 0x08D7, 758: 0x0AB0}      # their free run in $6C starts here (0xFF to the bank's end)
STUB = U.MODULE_STUB - 0x8000          # 0x1000
FONT = 0x1A40
PAGES_PTR = 0x1FFE
FPS = U.CDDA_FPS
ROW = 40                               # glyphs a row (6 px each, centred in 256)
ROWS = 2
BRIDGE = 0.6                           # a gap between two cues shorter than this keeps the band
GLYPHS = pcepair.ALPHA + pcepair.EXTRA
PAPER = 0x000                          # the band's colour (VCE GRB 3-3-3): black, the letterbox's
BX = 0x100                             # slot 15's scroll: column 32 at the screen's left edge
CUES = os.path.join(ROOT, "pce", "translation", "cdda_opening.json")

SOURCE = """
VDC_SEL = 0x0000
VDC_LO = 0x0002
VDC_HI = 0x0003
VDC_SHADOW = 0xF7
PAGES = {PAGES}
FONTA = {FONTA}
start:
  JMP stat
; ---- variables (before the code: a label used before its definition would be zero page) ----
was:    .byte 0                  ; $2638 last pass
live:   .byte 0                  ; a track's frames are being counted
track:  .byte 0
pos:    .word 0                  ; frames since the track's play was confirmed
lastvb: .byte 0                  ; $1B at the last pass
cur:    .word 0                  ; the page up, 0 none
want:   .word 0                  ; the page for now
shown:  .byte 0
o27:    .byte 0                  ; $27 before the band
s90:    .byte 0                  ; $90-$93 and $F7 as the pass found them
s91:    .byte 0
s92:    .byte 0
s93:    .byte 0
sf7:    .byte 0
g30:    .byte 0
rowi:   .byte 0
xpos:   .byte 0
cnt:    .byte 0
gidx:   .byte 0
shf:    .byte 0
vlo:    .byte 0
vhi:    .byte 0
tmp:    .byte 0
tmp2:   .byte 0
gbuf:   .res 12
buf:    .res 512                 ; a text row: 16 lines x 32 bytes, 1 bit a pixel
; ---- every pass, from the trampoline (bank $6C at MPR4) ----
stat:
  PHA
  PHX
  PHY
  LDA 0x90
  STA s90
  LDA 0x91
  STA s91
  LDA 0x92
  STA s92
  LDA 0x93
  STA s93
  LDA VDC_SHADOW
  STA sf7
  LDA 0x1B               ; the frames since the last pass
  SEC
  SBC lastvb
  TAY
  LDA 0x1B
  STA lastvb
  LDA 0x2638             ; the play confirmed: frame 0 of the track in $263B
  BEQ cnop
  LDA was
  BNE ccount
  LDA #1
  STA was
  STA live
  LDA 0x263B
  STA track
  STZ pos
  STZ pos+1
  BRA cscan
cnop:
  STZ was
  LDA live
  BEQ cnone
  LDA 0x263B             ; (a pulse in the opening: the track plays on while $263B names it)
  CMP track
  BNE cstop
ccount:
  TYA
  CLC
  ADC pos
  STA pos
  BCC cscan
  INC pos+1
cscan:
  JSR find
  BRA act
cstop:
  STZ live
cnone:
  STZ want
  STZ want+1
act:
  LDA want
  CMP cur
  BNE change
  LDA want+1
  CMP cur+1
  BEQ keep
change:
  LDA want
  STA cur
  LDA want+1
  STA cur+1
  ORA cur
  BEQ off
  JSR draw
  LDA shown
  BNE keep
  LDA 0x27
  STA o27
  LDA #1
  STA shown
keep:
  LDA shown
  BEQ done
  JSR secon
  BRA done
off:
  LDA shown
  BEQ done
  STZ shown
  JSR secoff
done:
  LDA s90
  STA 0x90
  LDA s91
  STA 0x91
  LDA s92
  STA 0x92
  LDA s93
  STA 0x93
  LDA sf7
  STA VDC_SHADOW
  STA a:VDC_SEL
  PLY
  PLX
  PLA
  RTS
; ---- want = the page of this track whose span holds pos, else 0 ----
find:
  LDA PAGES
  STA 0x90
  LDA PAGES+1
  STA 0x91
floop:
  LDY #0
  LDA (0x90),Y
  BEQ fnone
  CMP track
  BNE fnext
  LDY #1                 ; pos >= start
  LDA (0x90),Y
  STA vlo
  INY
  LDA (0x90),Y
  STA vhi
  LDA pos
  CMP vlo
  LDA pos+1
  SBC vhi
  BCC fnext
  LDY #3                 ; pos < end
  LDA (0x90),Y
  STA vlo
  INY
  LDA (0x90),Y
  STA vhi
  LDA pos
  CMP vlo
  LDA pos+1
  SBC vhi
  BCS fnext
  LDA 0x90
  STA want
  LDA 0x91
  STA want+1
  RTS
fnext:
  LDY #5
  LDA (0x90),Y
  CLC
  ADC 0x90
  STA 0x90
  BCC floop
  INC 0x91
  BRA floop
fnone:
  STZ want
  STZ want+1
  RTS
; ---- the page's two rows into the tiles, then the BAT (the game's guard round the VDC
; writes: $30 = 2, interrupts on - the raster sections keep their lines) ----
draw:
  LDA 0x30
  STA g30
  LDA #2
  STA 0x30
  JSR 0x4776             ; the VDC's increment to 1
  LDA cur
  STA 0x92
  LDA cur+1
  STA 0x93
  LDA #6
  JSR qadd
  STZ rowi
drow:
  JSR render
  JSR upload
  INC rowi
  LDA rowi
  CMP #2
  BNE drow
  LDA #0xE7              ; tiles 0x780 on, palette 14
  JSR bat
  LDA g30
  STA 0x30
  RTS
qadd:
  CLC
  ADC 0x92
  STA 0x92
  BCC qadd1
  INC 0x93
qadd1:
  RTS
; ---- the row at ($92) into buf, ($92) past it ----
render:
  LDA #lo(buf)
  STA 0x90
  LDA #hi(buf)
  STA 0x91
  LDX #2
  LDY #0
  CLA
rclr:
  STA (0x90),Y
  INY
  BNE rclr
  INC 0x91
  DEX
  BNE rclr
  LDY #0
  LDA (0x92),Y
  STA xpos
  INY
  LDA (0x92),Y
  STA cnt
  LDA #2
  JSR qadd
  LDA cnt
  BEQ rdone
rlet:
  LDY #0
  LDA (0x92),Y
  STA gidx
  LDA #1
  JSR qadd
  LDA gidx
  BEQ rnext              ; a space
  JSR glyph
rnext:
  LDA xpos
  CLC
  ADC #6
  STA xpos
  DEC cnt
  BNE rlet
rdone:
  RTS
; ---- glyph gidx ORed into buf at xpos, lines 2-13 ----
glyph:
  LDA gidx               ; ($90) = FONTA + gidx * 12
  STA vlo
  STZ vhi
  ASL vlo
  ROL vhi
  ASL vlo
  ROL vhi
  LDA vlo
  STA tmp
  LDA vhi
  STA tmp2
  ASL vlo
  ROL vhi
  LDA vlo
  CLC
  ADC tmp
  STA vlo
  LDA vhi
  ADC tmp2
  STA vhi
  LDA vlo
  CLC
  ADC #lo(FONTA)
  STA 0x90
  LDA vhi
  ADC #hi(FONTA)
  STA 0x91
  LDY #11
gcopy:
  LDA (0x90),Y
  STA gbuf,Y
  DEY
  BPL gcopy
  LDA xpos
  AND #7
  STA shf
  LDA xpos
  LSR
  LSR
  LSR
  CLC
  ADC #lo(buf + 64)
  STA 0x90
  LDA #hi(buf + 64)
  ADC #0
  STA 0x91
  LDX #0
gline:
  LDA gbuf,X             ; 6 bits, the leftmost pixel in bit 5
  ASL
  ASL
  STA vhi
  STZ vlo
  LDY shf
  BEQ gput
gshift:
  LSR vhi
  ROR vlo
  DEY
  BNE gshift
gput:
  LDY #0
  LDA (0x90),Y
  ORA vhi
  STA (0x90),Y
  INY
  LDA (0x90),Y
  ORA vlo
  STA (0x90),Y
  LDA 0x90
  CLC
  ADC #32
  STA 0x90
  BCC gnext
  INC 0x91
gnext:
  INX
  CPX #12
  BNE gline
  RTS
; ---- buf as the tiles of text row rowi: 0x7800 + rowi * 0x400 (the top 32 tiles, then the
; bottom 32 from + 0x200), a tile 8 words of plane 0/1 then 8 of planes 2/3 ----
upload:
  LDA #lo(buf)
  STA 0x90
  LDA #hi(buf)
  STA 0x91
  STZ tmp
uhalf:
  LDA rowi
  ASL
  ASL
  STA vhi
  LDA tmp
  ASL
  CLC
  ADC vhi
  CLC
  ADC #0x78
  STA vhi
  LDA #0
  STA VDC_SHADOW
  STA a:VDC_SEL
  STZ a:VDC_LO
  LDA vhi
  STA a:VDC_HI
  LDA #2
  STA VDC_SHADOW
  STA a:VDC_SEL
  LDX #0
ucol:
  TXA
  TAY
  LDA #8
  STA cnt
urow:
  LDA (0x90),Y
  STA a:VDC_LO
  LDA #0xFF              ; plane 1 set everywhere: paper colour 2, ink 3 (never 0 = see-through)
  STA a:VDC_HI
  TYA
  CLC
  ADC #32
  TAY
  DEC cnt
  BNE urow
  LDA #8
  STA cnt
uzero:
  STZ a:VDC_LO
  STZ a:VDC_HI
  DEC cnt
  BNE uzero
  INX
  CPX #32
  BNE ucol
  INC 0x91
  INC tmp
  LDA tmp
  CMP #2
  BNE uhalf
  RTS
; ---- the BAT's rows 43-50, columns 32-63: A = 0xE7 ours (rows 43-46 tiles 0x780 + row * 0x20
; + column, palette 14; 47-50 tile 0x780, always empty - the text starts at x 8 - where the
; game's blank cell is the picture's tile 0x110 and drew under the band), 0xF1 blank (0xF110,
; the game's closed window) ----
bat:
  STA tmp2
  STZ tmp
  LDA #lo(43 * 64 + 32)
  STA vlo
  LDA #hi(43 * 64 + 32)
  STA vhi
brow:
  LDA #0
  STA VDC_SHADOW
  STA a:VDC_SEL
  LDA vlo
  STA a:VDC_LO
  LDA vhi
  STA a:VDC_HI
  LDA #2
  STA VDC_SHADOW
  STA a:VDC_SEL
  LDA tmp
  ASL
  ASL
  ASL
  ASL
  ASL
  CLC
  ADC #0x80
  TAY
  LDX #32
bcol:
  LDA tmp2
  CMP #0xE7
  BEQ bours
  LDA #0x10
  STA a:VDC_LO
  BRA bhi
bours:
  LDA tmp
  CMP #4
  BCC btext
  LDA #0x80
  STA a:VDC_LO
  BRA bhi
btext:
  STY a:VDC_LO
bhi:
  LDA tmp2
  STA a:VDC_HI
  INY
  DEX
  BNE bcol
  LDA vlo
  CLC
  ADC #64
  STA vlo
  BCC bnext
  INC vhi
bnext:
  INC tmp
  LDA tmp
  CMP #8
  BNE brow
  RTS
; ---- every pass while a page is up: the sections, the RCR on, the text colour ----
secon:
  LDA #1
  STA 0x27               ; the vblank handler enables the RCR interrupt for the sections
  STA 0x390E
  LDA #{SPR_OFF}            ; slot 15 on, marked: stage 2's raster path turns sprites off under it
  STA 0x390F
  LDA #0x40              ; slot 14: rcr 0x40, line 0
  STA 0x392E
  STZ 0x393E
  LDA #0xF8              ; slot 15: rcr 0xF8, line 192
  STA 0x392F
  STZ 0x393F
  LDA #lo({BX})          ; the band: BAT row 43 (by 0x158), column 32 at the left edge
  STA 0x398F
  LDA #hi({BX})
  STA 0x399F
  LDA #0x58
  STA 0x39BF
  LDA #1
  STA 0x39CF
  STZ 0x398E             ; line 0: the picture's scroll - the game's lowest enabled slot's
  STZ 0x399E
  STZ 0x39BE
  STZ 0x39CE
  LDX #0
sslot:
  LDA 0x3900,X
  BNE scopy
  INX
  CPX #14
  BNE sslot
  BRA spal
scopy:
  LDA 0x3980,X
  STA 0x398E
  LDA 0x3990,X
  STA 0x399E
  LDA 0x39B0,X
  STA 0x39BE
  LDA 0x39C0,X
  STA 0x39CE
spal:
  LDA #0xE2              ; palette 14: entry 2 the band's paper, 3 the ink (white)
  STA a:0x0402
  STZ a:0x0403
  LDA #lo({PAPER})
  STA a:0x0404
  LDA #hi({PAPER})
  STA a:0x0405
  LDA #0xFF
  STA a:0x0404
  LDA #1
  STA a:0x0405
  LDA #1                 ; the BAT still ours? (the opening writes its BAT over at a scene
  STA VDC_SHADOW         ; change: the band went blank under the corridor, the skull...) -
  STA a:VDC_SEL          ; its first cell read back: MARR a word early (the buffer lags)
  LDA #lo(43 * 64 + 31)
  STA a:VDC_LO
  LDA #hi(43 * 64 + 31)
  STA a:VDC_HI
  LDA #2
  STA VDC_SHADOW
  STA a:VDC_SEL
  LDA a:VDC_HI           ; the dummy read
  LDA a:VDC_LO
  CMP #0x80
  BNE sbat
  LDA a:VDC_HI
  CMP #0xE7
  BNE sbat
  RTS
sbat:
  LDA 0x30
  STA g30
  LDA #2
  STA 0x30
  JSR 0x4776
  LDA #0xE7
  JSR bat
  LDA g30
  STA 0x30
  RTS
secoff:
  STZ 0x390E
  STZ 0x390F
  LDA o27
  STA 0x27
  LDA 0x30
  STA g30
  LDA #2
  STA 0x30
  JSR 0x4776
  LDA #0xF1
  JSR bat
  LDA g30
  STA 0x30
  RTS
{PAD}
sig:
  .byte 0x53, 0x42, 0x33         ; "SB3", where the module stub's is (the trampoline checks one address)
"""


# The band hides the picture's sprites: stage 2's raster interrupt path ($42F9, after the VD/RCR
# test at $40BF) and its next-section routine ($4318, also called from the vblank's $439E) are
# rewritten in the same 60 bytes (the old next-section routine loaded $3E80,Y twice, and $4310
# was dead) so that, while slot 15's enable byte reads SPR_OFF (only this stub writes it: the game
# and pcesubs write 1), every section also writes CR from the vblank's value ($3F26) - with the
# sprite bit (0x40) cleared at the LAST section (ours, the band's line 192), set again at any
# earlier one (slot 14, line 0) in case a nested vblank skipped its own CR write. The
# handler saved the VDC's register select ($F7) and puts it back at $42D0, so ST0 is free.
SPR_OFF = 0xA5
RCR_AT, RCR_END = 0x42F9, 0x4335
RCR_OLD = bytes.fromhex("ac253fd0034cd042a5673010a66720ef4320184"
                        "34cd042a20120ef434cd042e667a467b9803e1ad006a9ff8567800cb9803e48b9a03eaa6820a8e060")
RCR_CALL = (0x439E, bytes.fromhex("201843"))          # the vblank's first-section call
RCR_SOURCE = """
rcr:
  LDY 0x3F25             ; sections on?
  BEQ 0x42D0
  LDX 0x67
  BMI 0x42D0
  JSR 0x43EF             ; this section's BXR/BYR
  JSR rnext
  LDA 0x390F             ; the opening's band up?
  CMP #{SPR_OFF}
  BNE 0x42D0
  LDA 0x3F26             ; CR as the vblank wrote it
  LDY 0x67
  BPL rcr1               ; not the last section: sprites as they were
  AND #0xBF              ; the last (the band): sprites off to the frame's end
rcr1:
  .byte 0x03, 0x05       ; ST0 #5 (CR; $F7 restored by the handler's exit)
  STA a:0x0002
  BRA 0x42D0
rnext:
  INC 0x67
  LDY 0x67
  LDA 0x3E80,Y
  CMP #0xFF
  BNE rnext1
  STA 0x67               ; the end: $67 = $FF
  RTS
rnext1:
  .byte 0xBE, 0xA0, 0x3E ; LDX $3EA0,Y
  JMP 0xE0A8             ; the RCR from A/X
"""


def rcr_patch():
    """[(stage-2 address, old bytes, new bytes)]: the raster path and the vblank's call."""
    code, labels = assemble(RCR_SOURCE.format(SPR_OFF=SPR_OFF), RCR_AT)
    assert len(RCR_OLD) == RCR_END - RCR_AT and len(code) <= len(RCR_OLD), len(code)
    code += bytes([0xEA]) * (len(RCR_OLD) - len(code))
    nxt = labels["rnext"]
    return [(RCR_AT, RCR_OLD, code), (RCR_CALL[0], RCR_CALL[1], bytes([0x20, nxt & 0xFF, nxt >> 8]))]


def glyph_index(ch):
    if ch not in GLYPHS:
        raise SystemExit(f"{ch!r}: no glyph in pcepair's font")
    return GLYPHS.index(ch)


def wrap(text, width=ROW):
    """Rows of at most `width` letters, each row filled before the next starts."""
    rows, row = [], ""
    for word in text.split():
        cand = f"{row} {word}" if row else word
        if len(cand) <= width:
            row = cand
        else:
            if len(word) > width:
                raise SystemExit(f"{word!r} is wider than a row")
            rows.append(row)
            row = word
    return rows + ([row] if row else [])


def split(text):
    """A cue's text as pages of at most ROWS rows, broken where lib/cardplan.py says
    (whole sentences a page, then clause, phrase, word; no widow) - the rule of every
    subtitle card in the three ports."""
    import cardplan
    words = text.split()
    cards = cardplan.plan(words, lambda a, b: len(wrap(" ".join(words[a:b]))) <= ROWS)
    return [wrap(" ".join(words[a:b])) for a, b in cards]


def pages(cues):
    """[(track, start frame, end frame, [row, row])]: each cue's pages (split), its time
    shared by the pages' letters; a short gap to the next cue bridged."""
    out = []
    cues = sorted(cues, key=lambda c: (c["track"], c["start"]))
    for k, c in enumerate(cues):
        end = c["end"]
        if k + 1 < len(cues) and cues[k + 1]["track"] == c["track"] and 0 <= cues[k + 1]["start"] - end < BRIDGE:
            end = cues[k + 1]["start"]
        pg = split(c["en"])
        weights = [sum(len(r) for r in p) for p in pg]
        t, total = c["start"], sum(weights)
        for p, w in zip(pg, weights):
            t1 = t + (end - c["start"]) * w / total
            out.append((c["track"], round(t * FPS), round(t1 * FPS), p))
            t = t1
    return out


def table(cues):
    """The pages as the stub reads them."""
    out = bytearray()
    for track, s, e, rows in pages(cues):
        body = bytearray()
        for r in rows + [""] * (ROWS - len(rows)):
            x0 = (256 - 6 * len(r)) // 2
            body += bytes([x0, len(r)]) + bytes(glyph_index(ch) for ch in r)
        assert 0 <= s < e <= 0xFFFF and 6 + len(body) < 256
        out += bytes([int(f"{track:02d}", 16)]) + s.to_bytes(2, "little") + e.to_bytes(2, "little") + bytes([6 + len(body)]) + body
    return bytes(out) + bytes([0])


def stub():
    """The stub's bytes at $9000, its signature where the module stub's is."""
    _, ml = U.stub(U.MODULE_STUB)
    env = dict(PAGES=0x8000 + PAGES_PTR, FONTA=0x8000 + FONT, BX=BX, SPR_OFF=SPR_OFF, PAPER=PAPER)
    code, labels = assemble(SOURCE.format(PAD="", **env), U.MODULE_STUB)
    pad = ml["sig"] - labels["sig"]
    if pad < 0:
        raise SystemExit(f"the opening's stub is {len(code)} B, {-pad} past the module stub's signature")
    code, labels = assemble(SOURCE.format(PAD=f"  .res {pad}", **env), U.MODULE_STUB)
    assert labels["sig"] == ml["sig"] and code[-3:] == U.SIGNATURE and STUB + len(code) <= FONT
    return code, labels


def cues(block):
    return [c for c in json.load(open(CUES, encoding="utf-8")) if c["track"] in BLOCKS[block]]


def blob(block):
    """{$6C offset: bytes} for a block."""
    code, _ = stub()
    font = pcepair.halffont()
    assert FONT + len(font) <= PAGES_PTR
    t = table(cues(block))
    at = STUB - len(t)
    if at < FREE[block]:
        raise SystemExit(f"rec {block}: its pages are {len(t)} B, {FREE[block] - at} more than the free run holds")
    ptr = 0x8000 + at
    return {at: t, STUB: code, FONT: font, PAGES_PTR: bytes([ptr & 0xFF, ptr >> 8])}


def apply(out_path=P.OUT):
    img = P.Image(out_path, P.T3 + P.RESERVE)
    for block in BLOCKS:
        base = (S.T2 + block) * P.DATA
        assert bytes(S.block(block, 100)[FREE[block]:0x2000]) == bytes([0xFF]) * (0x2000 - FREE[block])
        img.write(base + FREE[block], bytes([0xFF]) * (0x2000 - FREE[block]))     # (a re-run)
        parts = blob(block)
        for off, data in sorted(parts.items()):
            img.write(base + off, data)
        n = len(pages(cues(block)))
        print(f"rec {block}: {n} pages ({len(parts[min(parts)])} B at $6C:{min(parts):#06x}), the stub and the font in $6C")
    s2 = (P.T2 + P.STAGE2) * P.DATA - P.STAGE2_BASE
    for at, old, new in rcr_patch():
        now = bytes(img.data[s2 + at:s2 + at + len(old)])
        if now not in (old, new):
            raise SystemExit(f"stage 2 at ${at:04X}: neither the game's bytes nor ours")
        img.write(s2 + at, new)
    print(f"stage 2: the raster path at ${RCR_AT:04X} turns sprites off under the band; {img.flush()} sectors written")


def show():
    for block in BLOCKS:
        for track, s, e, rows in pages(cues(block)):
            print(f"track {track} {s / FPS:6.2f}-{e / FPS:6.2f}  " + " / ".join(rows))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    show() if cmd == "show" else apply()
