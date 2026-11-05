"""Voice-line subtitles on the Saturn: the payload, its blob and the exec hook.

How the engine draws text (found for this, 2026-09-12; see the Saturn port
notes in CLAUDE.md): the 4 x 20 cells at ctx+0x3FA are turned into 80
12-byte sprite records at 0x060E5358 by the cell renderer 0x060B4970 every
frame, but what VDP1 draws is decided by sprite OBJECT 0 (ctx+0x830 =
0x060F2CE0, 76 bytes: +0 active, +8 x, +12 y = the box slide 0..128, +24 the
sprite LIST it draws). A list is {u16 count, 6 pad} + count x {u16 ctrl, u16
size, u16 clut, u16 srca, u16 x, u16 y}. The dialogue box is the list at
0x060E5350 (88 = the 80 cells + 8 box pieces); the voice band (the speaking
face at the left, 0x060F2A08 == 2) switches object 0 to the list at
0x060E5778 (6 gold-line pieces, NO cells) - which is why a voiced line shows
no text and why poking the cells during one drew nothing. Cells are opaque
16 x 14 sprites, so a list of all 80 would paint the face over. Those two
are the only lists object 0 ever shows (the array at 0x060E533C; the four
list-menu sites put the box list back after 0x060B57CC).

The payload therefore keeps a list of its own in the blob: the 42 cell
records of rows 1-3, columns 6-19 (beside the face, one row down so the
block is centred on the portrait like the PS1's) copied from 0x060E5358
after the renderer runs, plus the 6 band pieces, and points object 0 at it while a
card is up; the band list comes back when the card ends. Cells are written
directly (u16 SJIS + colour), no engine text call: the engine's layout and
type-on are synchronous loops around the frame wait, so nothing of the
engine's text path can be called from a per-frame hook.

Hook: the frame wait 0x060B55A0 calls the renderer through the pool word at
0x060B563C (its only reference). That word is pointed at a 40-byte stub that
the exec-hole ledger places (work/saturn/build/exec_alloc.json: every patch's
code is allocated there, never at a fixed address); the stub
jumps into the blob when its magic
is in RAM and otherwise into the renderer. The payload runs INSTEAD of the
renderer, calls it itself and copies the records after it - so a card is
drawn the frame it is decided. It runs in the frame wait's own call
context (not an interrupt), from wherever the game waits a frame: the
type-on loop, the box slides, the script's own waits.

Blob: at the END of the loaded bank's string region (since 2026-09-16; a fixed
0x002F2000 until then cost 0xA000 of padding per bank, and 39 banks would not
have fit the disc). The scene loader (0x060B915E) reads the bank as {u16
code_len, u16 str_len, code, strings, u32 trailer}, exactly str_len bytes of
strings, so the region carries: strings (+ satlong's longs and group) | pad to
4 | blob | pad | footer {'SUBF', blob offset} | satlong's tail {0xFFFF, group}
(LOOKUP reads the region's last four bytes, so it stays last). The renderer
stub finds the blob through the footer at L-12 (L-8 with no tail), L being the
region length satlong's loader stub records in `lenvar`, checks the blob's
'SUBS', caches the address in `blobptr` (the exec hole; 0 when no blob is
live) for the op 0x21 stub, and jumps to blob+0x20. The payload is assembled
per bank at its own address (`payload_asm(BLOB)`); `work/saturn/build/
subs_layout.json` records every scene's blob address and `blobptr` for the
harness. Region + blob must stay under the 64 KB window (0x2F8000 is the
bytecode): one text per cue (the band's 14-cell rows; the plain box and the
plain-in-band card draw the same rows under a nameplate string, cue+20), so
B250 with the folded B260 (536 cards) is 53 KB. Layout: +0 magic 'SUBS', +4
u16 scene (ctx+0x54A), +6 u16 ncues, +8 cues ptr, +12 the 42-cell band list
(the 80-cell plain-in-band list follows it at +BP_OFF), +16 cur (cue ptr or
0), +20 the plain list, +24 LAYOUT (1 band, 2 plain), +28 PSTATE, +0x20 code,
then the cue table (32 B: u16 sector - 0xFFFF for a reel -, u16 reel flag (1
= a speaker with a known face: laid out by the face words), u32 key =
offset<<16 | act<<8 or the SDAIF stream number, u32 b0, u32 b1, u32 band
text, u32 nameplate text or 0, u32 face buffer, u32 CMDSRCA base << 16 |
palette), the interned SJIS texts (u16 codes, 0x818F = row break, 0x8101..
0x8107 = colour for the cells that follow, 0 = end), the two band list
buffers and the plain list buffer. The payload's own words (`menuhold`,
`facecue`, `flmiss`, `qhold`, `rlast`/`rsame`, `curlist`, `bplain`,
`cellcodes`, `job`) are data after the code.

Gate (per frame): the blob's scene == ctx+0x54A and ctx+0xB74 == 0, then
one of two layouts, decided from the engine's state (0.8.2-wip, the second
pass):

  BAND (the face at the left): 0x060F2A08 == 2 AND ctx+0x558 == 2 (the
  band's own state word, which the band close 0x060B4AE0 zeroes - the flag
  alone outlives the band) AND box y == 0 AND object 0 shows the band list
  or ours. The live line (sector 0x060EA2C2, key 0x060EA2C4, decoded bytes
  0x060EA2BC) picks the cue with b0 <= decoded < b1. A change shows (clear
  the 42 cells, write the text from row 1 column 6, menu-live byte 0x060F28A7 :=
  0 so the stale highlight cannot paint a row, object 0 -> our band list)
  or hides (cells cleared, band list back - only if object 0 still holds
  ours). If the engine took object 0 back while a card was up (band
  closing), the card is dropped without touching the cells.

  PLAIN (no band: Metal Gear in most rooms, narration): ctx+0x558 == 0, no
  menu live, and the box CLOSED and idle - y == 128 with object 0 on the
  engine's box list 0x060E5350 - or already ours - AND the line has started
  decoding (position > 0): the engine loads a line a frame or more before
  its band-open op runs, and in that window the state reads idle-plain
  (the wedge after Ask -> Snatchers, 2026-09-15: a b0 = 0 cue matched at
  decoded 0, the plain path called 0x060B6F20 - whose callee leaves r6 on
  its stack job - and plain_write read the cue through r6: address error,
  the BIOS's masked-interrupt loop, the vblank counter stopped). The
  payload keeps r6 across that call now. The payload then does
  what the engine's pre-text 0x060B4BA4 does: 0x060B6F20(10, 20) picks the
  box frame on its VDP2 layer, the cells are cleared and written at once
  (no type-on: a POC simplification, the engine's type-on is a synchronous
  loop we cannot run from here), the nameplate in row 0 in the speaker's
  colour and the text from row 1 (18 cells x 3 rows; from row 0 without a
  speaker), object 0 -> our plain list (all 80 cell records + the 8 box
  pieces), and the box y slides 128 -> 0 by 8 a frame (the engine's own
  slide). The frame pick is inlined on a job word in the blob: 0x060B6F20
  keeps its job on its own stack and 0x060B30A0 queues it by pointer for
  the next frame wait's 0x060B3108, which from this hook would read reused
  stack. A cue change on the same open box rewrites the cells; a cue end
  slides it back up (8 a frame to 128), parks it (x 0, y 128), puts the box
  list back and clears the cells - the engine's 0x060B57CC in short. The
  state word PSTATE (blob+28: 0 idle, 1 opening, 2 open, 3 closing, 4 lost)
  drives it; the two cell codes we wrote at (0,0) and (1,0) are kept in
  the `cellcodes` word and checked every frame: the engine's own text path clears
  the cells first (0x060B4920), so a mismatch means the engine took the box
  - the card is dropped without touching anything (LOST) until the box is
  closed and on the box list again. A box in motion that is not ours (y
  changed under an open card) is the same. The engine never lays out text
  while the band list is up (every text path runs 0x060B4BA4 first, which
  finishes the band close), so a voiced line with engine text is only ever
  a PLAIN situation, and there the y == 128 / list == box gate keeps us
  out of the engine's card; a card of ours the engine's text lands on is
  detected by the cell check within the frame.

    python saturn/subs/satsubs.py [B010 ...]     after satapply, satnames, satlong; before satpack/satdisc
"""
import os, sys, json, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]

import satdata, satfont
from sh2s import Asm
from satapply import SatPairFont
from gen_subs import SAT_TABLE

OUT = os.path.join(ROOT, "patched", "saturn")
DATA_OUT = os.path.join(OUT, "DATA.BIN")
MAIN_OUT = os.path.join(OUT, "MAIN_L.BIN")
BUILD = os.path.join(WORK, "saturn", "build")
MAIN_BASE = 0x060B0000
SECTOR = 2048

STR_BASE = 0x002E8000             # the string region's load address; the bank window ends at the
WINDOW_END = 0x002F8000           # bytecode (0x2F8000): region + blob must stay under 64 KB
MAGIC = 0x53554253                # 'SUBS' - the blob's first word
FOOT_MAGIC = 0x53554246           # 'SUBF' - the footer {magic, blob offset} before the region's tail
LENVAR_DEFAULT = None             # satlong's `lenvar` (the region length the loader stub records): read from its stub at build time
STUB_ROOM = 256                   # the stub is allocated in the exec hole through satexec's ledger
                                  # (after satnames and satlong): its address is decided at build time
LAYOUT_JSON = os.path.join(WORK, "saturn", "build", "subs_layout.json")   # per scene: the blob's address; the blobptr word
HOOK_POOL = 0x060B563C            # the frame wait's pool word = the renderer
RENDER = 0x060B4970
CTX = 0x060F24B0
CELLS = CTX + 0x3FA
RECS = 0x060E5358
BOX_LIST = 0x060E5350
BAND_LIST = 0x060E5778
OBJ0_LIST = 0x060F2CF8            # object 0 + 24
OBJ0_PRIO = 0x060F2CE1            # object 0 + 1: its draw priority (0..31; the VDP1 list builder 0x060B3838
                                  #   draws the buckets from 0 up, a bucket's first object last - object 0 at 31 tops all)
BAND_FLAG = 0x060F2A08
BOX_Y = 0x060F2CEC
BOX_WAIT = CTX + 0xB74
MENU_LIVE = 0x060F28A7
SCENE_VAR = CTX + 0x54A
VOICE_SEC, VOICE_KEY, VOICE_DEC = 0x060EA2C2, 0x060EA2C4, 0x060EA2BC
VOICE_TABLE, VOICE_TABLE_N = 0x060EB5A8, 1040   # the exec's voice table (satcat.py): 12 B per line
REEL_NO, REEL_PLAYING, REEL_POS = 0x060EFE6A, 0x060EFE64, 0x060EFF0C   # the SDAIF stream player (gen_subs.py)
REEL_TAG = 0xFFFF                 # a cue's sector field: a reel cue, its key = the stream number
ROWBREAK = 0x818F
COLOUR_CODE = 0x8100              # 0x8101..0x8107 in a text: the colour of the cells that follow
BLANK = 0x889E
COL0, COLS, ROWS = 6, 14, 3
ROW0 = 1                          # band text in cell rows 1-3: the PS1's block sits one row below the band's top, centred on the portrait (rows 0-2 left the face's bottom quarter bare, 2026-09-15)
assert ROW0 + ROWS <= 4
BAND_CELL0 = CELLS + 80 * ROW0 + 4 * COL0
PLAIN_COLS, PLAIN_ROWS = 18, 4    # the plain box: the writer's row limit is the whole grid
NREC = ROWS * COLS                # cell records in our band list
BP_OFF = 8 + 12 * NREC + 6 * 12   # the 80-cell band list (plain-in-band) follows the 42-cell one in the blob
NREC_PLAIN = 80
CUE_SIZE = 32
VDP1_VRAM = 0x25C00000            # cache-through; a column's slot = CMDSRCA base (obj+28) * 8 from here
SIG_OFF = 0x800                   # facechunks.SIG_OFF: the 16 signature bytes into a portrait slot
BAND_STATE = CTX + 0x558          # 2 while the band is up (0x060B4AE0 zeroes it at the close)
BOX_X = 0x060F2CE8
FRAME_PICK = 0x060B6F20           # (layer 10, picture 20 = the box frame, 21 = the band): builds the job on its stack
FRAME_JOB = 0x060B6924            # its body on a job {u16 layer, u16 picture, u16 1, u16 0} - the payload's is in the blob
PIECES = RECS + 12 * 80           # the 8 box pieces after the 80 cell records in the box list
VOICE_ID = CTX + 0x560            # the live voice id (0x700 + line), what the room script's op 0x59 keys on
OBJ_BASE0 = CTX + 0x830 + 76       # face column c: base cel 1+3c, eyes 2+3c, mouth 3+3c (76 B objects)
OBJ_MOUTH0 = CTX + 0x830 + 76 * 3  # the mouth cel carries the column's voice-id list at +60..+76
FACE_X, FACE_AWAY = 24, 400        # the band's clean window is at x=24; the others go off screen
HIDE_DX = 512                      # extras: a column hidden under its own replacement sprite sits at x + HIDE_DX for the frame
EX_LAST = 0x28                     # extras: the last object it tracks (op 0x05 sprites = handle + 12; the band ones seen: 15..32)
FACE_COL_PITCH = 96                # a column's native x = FACE_X + 96 * col (op 0x21, 0x060B6CF4..6D00)
FACE_SLOT0 = 0x25C60000            # VDP1 face slots 4-7 (0x060E4C24[4..7]: 0x25C60000/65000/6A000/70000, 0x5000 each)
FL_MISSES = 30                     # frames face_left finds no column for the voice id before it restores the native layout
QHOLD_MAX = 15                     # frames a band card waits for its speaker's column to carry the voice id (the PS1's QHOLD)
LINGER = 60                        # (#50) frames the open plain box waits for the next line
MIN_HOLD, MAX_HOLD = 60, 180       # frames a card stays up from the frame it went up, its line over or not (a following cue replaces it):
READ_CPS = 20                      #   its reading time at READ_CPS characters a second, within MIN_HOLD..MAX_HOLD (hold_frames)
REEL_PARK = 8                      # frames the reel's file position stays put before the reel counts as over (the PS1's PARK_FRAMES)
FACE_POOL = 0x060B6D60             # op 0x21's pool word for the call right after its x write (0x060B6D14):
FACE_TARGET = 0x060DBBF8           #   retargeted to FACE_STUB_ASM, which parks a cued line's column at FACE_AWAY
FACE_SLOTS = [0x25C19000, 0x25C30000, 0x25C40000, 0x25C50000, 0x25C60000,
              0x25C65000, 0x25C6A000, 0x25C70000, 0x25C80000]      # exec table 0x060E4C24: VDP1 sprite slots
FACE_BUFS = [0x202C8000 + 0x4000 * i for i in range(9)]            # exec table 0x060E4C00: structure buffers
SLOT_TAB, BUF_TAB = 0x060E4C24, 0x060E4C00
SCENES = {f"B{i:02X}0": (21 + i, i) for i in range(39)}   # name -> (chunk, ctx+0x54A value)
# The opening (subs_INTRO.json, gen_intro.py) has no bank of its own: B000 (chunk 21, scene 0) is
# in RAM from the title to B010's load, the frame wait (and so the renderer hook) runs every frame
# and object 0 sits parked on the box list - the plain box's gate. Its blob rides in B000's region.
SCENES["INTRO"] = (21, 0)

FACE_STUB_TPL = f"""
    ; op 0x21 (show a face column) just wrote the cel's native x = 24 + 96*col at @r13 and
    ; calls 0x{FACE_TARGET:08X}(r4, r5, r6) through the pool word 0x{FACE_POOL:08X}, once per cel.
    ; While the blob is live for this scene and the LIVE voice id (ctx+0x560, 0x700 + line,
    ; set by the sound op and 0 once the line is over) names a line with a mono cue, the cel
    ; goes to x = {FACE_AWAY} instead: the payload's face_left puts the speaker's column in the
    ; band's window when its voice id is on a mouth list, and every column back at native x
    ; when none is - so no column ever draws at the wrong place for the frames between the
    ; show and the id (the flash). The line is looked up in the exec's voice table
    ; (0x{VOICE_TABLE:08X}, 12 B per line: u8 act, u16 sector at +2, u16 offset at +8) and
    ; matched on the cue's sector and key (offset<<16 | act<<8) - NOT on the live-line
    ; registers (sector 0x{VOICE_SEC:08X}, key 0x{VOICE_KEY:08X}): the sound driver fills those a
    ; frame after the id, and op 0x21 runs in that frame, so the first build's stub declined
    ; the first frame of every line and the column flashed at its native x (B0D0's Teller,
    ; #48). Reels (no id) and uncued lines match nothing: the engine's own x stands.
    ; Touches r0-r3 and r7 (caller-saved; r4-r6 are the memset's arguments), r6 saved around
    ; the scan.
    mov.l   =0x{{BLOBPTR:08X}}, r3      ; the renderer stub's cache: 0 = no blob live
    mov.l   @r3, r3
    tst     r3, r3
    bt      go
    mov.l   =0x{{VOICE_ID:08X}}, r1
    mov.w   @r1, r1
    extu.w  r1, r1
    tst     r1, r1
    bt      go
    mov.l   =0x{SCENE_VAR:08X}, r2
    mov.w   @r2, r2
    mov.w   @(4, r3), r0
    cmp/eq  r2, r0
    bf      go
    mov.l   =0x{VOICE_TABLE:08X}, r2
    mov.l   =0x{(-0x700) & 0xFFFFFFFF:08X}, r0
    add     r0, r1                      ; r1 = the line index (id - 0x700)
    mov.l   =0x{VOICE_TABLE_N:08X}, r0
    cmp/hs  r0, r1
    bt      go                          ; not a line (a stray id)
    mov     r1, r0
    shll    r0
    add     r1, r0
    shll2   r0                          ; 12 * line = (2n + n) * 4
    add     r0, r2                      ; r2 = the line's record
    mov.w   @(2, r2), r0
    extu.w  r0, r0
    mov     r0, r1                      ; r1 = the line's sector
    mov.w   @(8, r2), r0
    extu.w  r0, r0
    shll16  r0
    mov     r0, r7
    mov.b   @r2, r0
    extu.b  r0, r0
    shll8   r0
    or      r0, r7                      ; r7 = the line's key (offset<<16 | act<<8)
    mov.w   @(6, r3), r0
    extu.w  r0, r0
    tst     r0, r0
    bt      go
    mov.l   @(8, r3), r3
    mov.l   r6, @-r15
scan:
    mov.w   @r3, r6
    extu.w  r6, r6
    cmp/eq  r1, r6
    bf      scan_next
    mov.l   @(4, r3), r6
    cmp/eq  r7, r6
    bt      found
scan_next:
    add     #{CUE_SIZE}, r3
    dt      r0
    bf      scan
    bra     go
    mov.l   @r15+, r6
found:
    mov.l   @r15+, r6
    mov.l   =0x{FACE_AWAY:08X}, r0
    mov.w   r0, @r13
go:
    mov.l   =0x{FACE_TARGET:08X}, r0
    jmp     @r0
    nop
.pool
"""

def stub_asm(lenvar):
    """The renderer hook. The blob sits at the END of the loaded bank's string region
    (behind the strings and satlong's longs, before satlong's 4-byte tail): the region
    length the loader stub records in satlong's `lenvar` names the footer {'SUBF', blob
    offset} at L-12 (L-8 when the bank has no tail), the offset names the blob, whose
    first word is 'SUBS'. The result is cached in `blobptr` for the op 0x21 stub (0 when
    no blob is live), and the payload runs instead of the renderer. A region length
    that is not a multiple of 4 is a bank without a blob (grow_bank pads to 4): the
    footer load there would be an address error - B0B0 (12,654 B) wedged the machine
    on its load until 2026-09-16."""
    return f"""
    mov.l   =0x{lenvar:08X}, r1
    mov.l   @r1, r1                     ; L = the string region's length
    mov.l   =0x00000010, r0
    cmp/hs  r0, r1
    bf      none
    mov     r1, r0
    tst     #3, r0                      ; a bank with a blob is padded to 4 (grow_bank); a 2-aligned
    bf      none                        ;   length means no blob - and mov.l there is an address error (B0B0)
    mov.l   =0x{STR_BASE:08X}, r2
    add     r1, r2
    add     #-12, r2                    ; the footer before the tail
    mov.l   =0x{FOOT_MAGIC:08X}, r3
    mov.l   @r2, r0
    cmp/eq  r3, r0
    bt      foot
    add     #4, r2                      ; or last, when the bank has no tail
    mov.l   @r2, r0
    cmp/eq  r3, r0
    bf      none
foot:
    mov.l   @(4, r2), r0                ; the blob's region-relative offset
    cmp/hs  r1, r0
    bt      none
    mov.l   =0x{STR_BASE:08X}, r3
    add     r0, r3
    mov.l   @r3, r0
    mov.l   =0x{MAGIC:08X}, r1
    cmp/eq  r1, r0
    bf      none
    mov.l   =blobptr, r1
    mov.l   @r1, r0
    cmp/eq  r3, r0
    bt      same                        ; another blob than last frame's: a new bank
    sts.l   pr, @-r15
    bsr     unstale
    nop
    lds.l   @r15+, pr
    mov.l   =blobptr, r1
same:
    mov.l   r3, @r1
    add     #32, r3                     ; the entry at +0x20
    jmp     @r3
    nop
none:
    sts.l   pr, @-r15
    bsr     unstale
    nop
    lds.l   @r15+, pr
    mov.l   =blobptr, r1
    mov     #0, r0
    mov.l   r0, @r1
    mov.l   =0x{RENDER:08X}, r0
    jmp     @r0
    nop
unstale:                                ; object 0 still at the opening card's priority (the intro blob's
    mov.l   =0x{OBJ0_PRIO:08X}, r1      ;   `oprio` 31, the engine's is 28 from its init 0x060B44B4 on):
    mov.b   @r1, r0                     ;   back, whatever bank the skip or the load brought in
    cmp/eq  #31, r0
    bf      u_list
    mov     #28, r0
    mov.b   r0, @r1
u_list:                                 ; object 0 still on one of our lists, whose blob a scene
    mov.l   =0x{OBJ0_LIST:08X}, r1      ;   change has loaded over (#62: the engine drew the new
    mov.l   @r1, r0                     ;   bank's bytes as a sprite list): the engine's list back
    mov.l   =0x{STR_BASE:08X}, r2
    cmp/hs  r2, r0
    bf      u_ret
    mov.l   =0x{WINDOW_END:08X}, r2
    cmp/hs  r2, r0
    bt      u_ret
    mov.l   =0x{BAND_FLAG:08X}, r2
    mov.w   @r2, r0
    cmp/eq  #2, r0
    bt      u_band
    mov.l   =0x{BOX_LIST:08X}, r2       ; no band: the box list, parked as p_closed parks it
    mov.l   r2, @r1
    mov.l   =0x{BOX_Y:08X}, r1
    mov     #64, r0
    add     r0, r0
    mov.w   r0, @r1
    mov.l   =0x{BOX_X:08X}, r1
    mov     #0, r0
    rts
    mov.w   r0, @r1
u_band:
    mov.l   =0x{BAND_LIST:08X}, r2
    rts
    mov.l   r2, @r1
u_ret:
    rts
    nop
    .align  4
blobptr:
    .long   0
.pool
"""


def hold_frames(text):
    """The frames a card of `text` stays up at least (the payload's holdtab byte)."""
    return max(MIN_HOLD, min(MAX_HOLD, -(-len(text) * 60 // READ_CPS)))


def payload_asm(BLOB):
    return f"""
entry:
    sts.l   pr, @-r15
    mov.l   r8, @-r15
    mov.l   r9, @-r15
    mov.l   r10, @-r15
    mov.l   r11, @-r15
    mov.l   r12, @-r15
    mov.l   r13, @-r15
    mov.l   r14, @-r15
    bsr     unhide                      ; the cels extras hid last frame back at their x
    nop
    mov.l   =0x{BLOB:08X}, r9
    ; ---- which layout the engine's state allows: r7 = 0 none, 1 band, 2 plain
    mov     #0, r7
    mov.l   =0x{SCENE_VAR:08X}, r1
    mov.w   @r1, r1
    extu.w  r1, r1
    mov.w   @(4, r9), r0
    extu.w  r0, r0
    cmp/eq  r1, r0
    bf      mode_done
    mov.l   =0x{BOX_WAIT:08X}, r1
    mov.b   @r1, r1
    tst     r1, r1
    bf      mode_done
    mov.l   =0x{BAND_FLAG:08X}, r1
    mov.w   @r1, r1
    mov     #2, r2
    cmp/eq  r2, r1
    bf      try_plain
    mov.l   =0x{BAND_STATE:08X}, r1
    mov.w   @r1, r1
    cmp/eq  r2, r1
    bf      try_plain
    mov.l   =0x{BOX_Y:08X}, r1
    mov.w   @r1, r1
    tst     r1, r1
    bf      band_moving
    mov.l   =0x{OBJ0_LIST:08X}, r1
    mov.l   @r1, r1
    mov.l   =0x{BAND_LIST:08X}, r2
    cmp/eq  r2, r1
    bt      band_ok
    mov.l   =curlist, r2                ; our 42-cell list, or the 80-cell plain-in-band one
    mov.l   @r2, r2
    cmp/eq  r2, r1
    bf      mode_done
band_ok:
    bra     mode_done
    mov     #1, r7
band_moving:
    ; the band sliding in (or out): no card yet, but the line is live and its cue known, so
    ; the speaker's face is placed now and rides in with the band (mode 3: face_left only)
    bra     mode_done
    mov     #3, r7
.pool                                   ; the entry's literals (the pool after `done` is out of their reach)
try_plain:
    mov.l   =0x{BAND_STATE:08X}, r1
    mov.w   @r1, r1
    tst     r1, r1
    bf      mode_done
    mov.l   =0x{MENU_LIVE:08X}, r1
    mov.b   @r1, r1
    tst     r1, r1
    bt      plain_lists
    ; the menu-live byte is STALE after a pick (0x060B4A76 sets it at the list open, the
    ; clear 0x060B4A8C runs on the next text or menu path, not on the pick): Mika's 'Mr.
    ; Seed.' (B010_002, line 200) plays right after `Go inside` with no band and no box,
    ; the byte still 1, and never drew (2026-09-15). A parked box (y 128 on the engine's
    ; box list) with the byte set is such a stale menu - unless a list is opening THIS
    ; frame (the open sets the byte before its first slide tick): so the state must hold
    ; two frames running (`menuhold`); a real open slides y to 120 on the second.
    mov.l   =0x{OBJ0_LIST:08X}, r1
    mov.l   @r1, r1
    mov.l   =0x{BOX_LIST:08X}, r2
    cmp/eq  r2, r1
    bf      hold_clear
    mov.l   =0x{BOX_Y:08X}, r1
    mov.w   @r1, r1
    extu.w  r1, r1
    mov.l   =0x00000080, r2
    cmp/eq  r2, r1
    bf      hold_clear
    mov.l   =menuhold, r1
    mov.l   @r1, r2
    tst     r2, r2
    bf      plain_ok                    ; the second frame parked: stale
    mov     #1, r2
    bra     mode_done
    mov.l   r2, @r1
hold_clear:
    mov.l   =menuhold, r1
    mov     #0, r2
    bra     mode_done
    mov.l   r2, @r1
plain_lists:
    mov.l   =menuhold, r1
    mov     #0, r2
    mov.l   r2, @r1
    mov.l   =0x{OBJ0_LIST:08X}, r1
    mov.l   @r1, r1
    mov.l   @(20, r9), r2
    cmp/eq  r2, r1
    bt      plain_ok
    mov.l   =0x{BOX_LIST:08X}, r2
    cmp/eq  r2, r1
    bf      mode_done
    mov.l   =0x{BOX_Y:08X}, r1
    mov.w   @r1, r1
    extu.w  r1, r1
    mov.l   =0x00000080, r2
    cmp/eq  r2, r1
    bf      mode_done
plain_ok:
    mov     #2, r7
mode_done:
    ; ---- the live line -> r6 = the cue that covers it, or 0
    mov     #0, r6
    tst     r7, r7
    bt      decide
    mov.l   =0x{VOICE_SEC:08X}, r1
    mov.w   @r1, r10
    extu.w  r10, r10
    mov.l   =0x{VOICE_KEY:08X}, r1
    mov.l   @r1, r11
    mov.l   =0xFFFFFF00, r2
    and     r2, r11
    mov.l   =0x{VOICE_DEC:08X}, r1
    mov.l   @r1, r12
    mov.l   =0x{REEL_NO:08X}, r1        ; the SDAIF reel: number, position; only while playing
    mov.w   @r1, r8
    extu.w  r8, r8
    mov.l   =0x{REEL_PLAYING:08X}, r1
    mov.l   @r1, r1
    mov     #1, r0
    cmp/eq  r0, r1
    bt      reel_ok
    mov     #-1, r8                     ; no stream number matches
reel_ok:
    mov.l   =0x{REEL_POS:08X}, r1
    mov.l   @r1, r5
    mov.l   =rlast, r1                  ; the position unchanged REEL_PARK frames running: the reel is
    mov.l   @r1, r2                     ; over (the counter parks at or just short of the size, and the
    mov.l   r5, @r1                     ; last cue's window would hold its card for ever)
    mov.l   =rsame, r1
    mov.l   @r1, r3
    cmp/eq  r2, r5
    bt      reel_same
    mov     #0, r3
    bra     reel_cnt
    mov.l   r3, @r1
reel_same:
    add     #1, r3
    mov.l   r3, @r1
    mov     #{REEL_PARK}, r0
    cmp/ge  r0, r3
    bf      reel_cnt
    mov     #-1, r8
reel_cnt:
    mov.l   @(8, r9), r13
    mov.w   @(6, r9), r0
    extu.w  r0, r14
loop:
    tst     r14, r14
    bt      decide
    mov.w   @r13, r1
    extu.w  r1, r1
    mov.l   =0x0000{REEL_TAG:04X}, r2
    cmp/eq  r2, r1
    bt      reel_cue
    cmp/eq  r10, r1
    bf      next
    mov.l   @(4, r13), r1
    cmp/eq  r11, r1
    bf      next
    bra     range
    mov     r12, r3                     ; position = the line's decoded bytes
reel_cue:
    mov.l   @(4, r13), r1
    cmp/eq  r8, r1
    bf      next
    mov     r5, r3                      ; position = the reel's file bytes played
range:
    mov.l   @(8, r13), r1
    cmp/hs  r1, r3
    bf      next
    mov.l   @(12, r13), r1
    cmp/hi  r3, r1
    bf      next
    bra     decide
    mov     r13, r6
next:
    add     #{CUE_SIZE}, r13
    bra     loop
    add     #-1, r14
    ; ---- dispatch on the card that is up
decide:
    ; A PLAIN card only for a line that is playing: the engine loads a line (sector and key
    ; set, decoded bytes 0) a frame or more BEFORE its band-open op runs, and in that window
    ; the state reads idle-plain (band flag 0, ctx+0x558 0 once the previous card was
    ; unvoiced, box parked on the box list) - Ask -> Snatchers in the Chief's room took
    ; the plain path there (2026-09-15). The position that matched (r3, from `range`) is
    ; 0 for the whole load, so such a match is no cue yet; the band path keeps b0 = 0.
    tst     r6, r6
    bt      decide2
    mov     r7, r0
    cmp/eq  #2, r0
    bf      decide2
    tst     r3, r3
    bf      decide2
    mov     #0, r6
decide2:
    mov.l   @(16, r9), r10              ; cur
    ; the minimum hold: a card stays up its reading time (holdtab: one byte per cue, frames,
    ; MIN_HOLD..MAX_HOLD) from the frame it went up, though its line is over, unless another
    ; cue matches (it replaces it at once) or the state is no card's (a menu, the engine's
    ; box: r7 = 0). B020's 0.4 s reels 'What?!' / 'What was that?' and B240's 'Snow?' were up
    ; 8-19 frames and nobody could read them.
    mov.l   =hcue, r1
    mov.l   @r1, r2
    cmp/eq  r2, r10
    bt      h_same
    mov.l   r10, @r1                    ; a new card (or none): count from 0
    mov     #0, r0
    bra     h_cnt
    mov.l   r0, @(4, r1)
h_same:
    mov.l   @(4, r1), r0
    add     #1, r0
    mov.l   r0, @(4, r1)
h_cnt:
    tst     r6, r6
    bf      h_done
    tst     r7, r7
    bt      h_done
    tst     r10, r10
    bt      h_done
    mov     r0, r3                      ; r3 = frames up
    mov.l   @(8, r9), r1                ; the cue's index = (cur - cues) / 32
    mov     r10, r0
    sub     r1, r0
    shlr2   r0
    shlr2   r0
    shlr    r0
    mov.l   =holdtab, r1
    mov.l   @r1, r1
    mov.b   @(r0, r1), r2
    extu.b  r2, r2
    cmp/ge  r2, r3
    bt      h_done
    mov     r10, r6                     ; nothing else wants the box: the card stays
h_done:
    mov.l   @(24, r9), r11              ; its layout
    tst     r10, r10
    bf      card_up
    bra     no_card                     ; past a conditional branch's reach
    nop
card_up:
    mov     r11, r0
    cmp/eq  #1, r0
    bf      plain_up
    bra     band_up                     ; past a conditional branch's reach
    nop
plain_up:
    ; ---- a plain card is up: the state machine
    mov.l   @(28, r9), r0
    cmp/eq  #1, r0
    bt      p_opening
    cmp/eq  #2, r0
    bt      p_open
    cmp/eq  #3, r0
    bt      p_closing
to_render1:
    bra     render
    nop
.pool
p_opening:
    bsr     own_check
    nop
    tst     r0, r0
    bt      p_lost
    mov     r10, r4
    bsr     ytarget                     ; r0 = the open box's y: 0, or the opening's per-cue y
    nop
    mov     r0, r3
    mov.l   =0x{BOX_Y:08X}, r1
    mov.w   @r1, r2
    extu.w  r2, r2
    cmp/hi  r3, r2
    bf      p_at                        ; at (or past) the target: open
    mov.l   =pslide, r0                 ; 8 a frame (the engine's slide), or 128 = no slide (the opening)
    mov.l   @r0, r0
    sub     r0, r2
    cmp/gt  r2, r3
    bf      p_step
    mov     r3, r2                      ; never past the target
p_step:
    mov.w   r2, @r1
    bra     render
    nop
p_at:
    mov.w   r3, @r1
p_opened:
    mov     #2, r0
    mov.l   r0, @(28, r9)
p_open:
    bsr     own_check
    nop
    tst     r0, r0
    bt      p_lost
    mov     r10, r4
    bsr     ytarget
    nop
    mov.l   =0x{BOX_Y:08X}, r1
    mov.w   @r1, r2
    extu.w  r2, r2
    cmp/eq  r0, r2
    bf      p_lost                      ; the box moved under us: the engine's
    cmp/eq  r6, r10
    bt      to_render1                  ; same cue, nothing to do
    tst     r6, r6
    bf      p_have
    ; (#50) the line is over but the state is still plain (no band, no menu): hold the
    ; open box LINGER frames - the next voice line of a plain exchange starts ~46 frames
    ; after the last one ended (B110, Ivan after the shot) and the box closed (16 frames),
    ; sat parked (30) and re-opened (18) between every two lines
    mov     r7, r0
    cmp/eq  #2, r0
    bf      p_close_start
    mov.l   =linger, r1
    mov.l   @r1, r0
    add     #1, r0
    mov.l   r0, @r1
    mov.l   =plinger, r2                ; LINGER, or the blob's own (the opening: its pauses run to 1.6 s)
    mov.l   @r2, r2
    cmp/ge  r2, r0
    bt      p_close_start
    bra     render
    nop
p_have:
    mov.l   =linger, r1
    mov     #0, r0
    mov.l   r0, @r1
    mov     r7, r0
    cmp/eq  #2, r0
    bf      p_close_start
    bsr     plain_write                 ; the next cue on the open box
    nop
    mov     r6, r4
    bsr     ytarget                     ; ... at its own y (the opening's cues each sit on their picture's
    nop                                 ;   black where it has one)
    mov.l   =0x{BOX_Y:08X}, r1
    mov.w   r0, @r1
    bra     render
    mov.l   r6, @(16, r9)
p_close_start:
    mov.l   =linger, r1
    mov     #0, r0
    mov.l   r0, @r1
    mov     #3, r0
    mov.l   r0, @(28, r9)
p_closing:
    ; the close is ours only while object 0 still shows our plain list and no list menu
    ; has gone live: the navigator reel's last card ended the frame the Mechanic room's
    ; verb menu opened, our +8 slide and the engine's -8 slide cancelled, the box stuck
    ; half-way and the engine waited for y == 0 for ever (Luiz on the MiSTer, 2026-09-15).
    ; Yield: the box list back on object 0 (the engine's menu draws through it), y left
    ; where it is (the engine's own slide finishes), our state idle, the cells untouched.
    mov.l   =0x{OBJ0_LIST:08X}, r1
    mov.l   @r1, r2
    mov.l   @(20, r9), r3
    cmp/eq  r3, r2
    bf      p_yield_gone
    mov.l   =0x{MENU_LIVE:08X}, r3
    mov.b   @r3, r3
    tst     r3, r3
    bf      p_yield
    ; ... and while our cells are still there: the engine writes the next card's nameplate
    ; before it slides the box up, never touching object 0. Jamie's answering machine
    ; (B070): with a fast picture reload (SAROO) Gillian's card opened during our close,
    ; our +8 and its -8 cancelled and the game froze with the box half-way (#98, 2026-10-20).
    bsr     own_check
    nop
    tst     r0, r0
    bt      p_lost
    mov.l   =0x{BOX_Y:08X}, r1
    mov.w   @r1, r2
    extu.w  r2, r2
    mov.l   =0x00000080, r3
    cmp/hs  r3, r2
    bt      p_closed
    mov.l   =pslide, r0
    mov.l   @r0, r0
    add     r0, r2
    mov.w   r2, @r1
    bra     render
    nop
p_closed:
    bsr     prio_back
    nop
    mov.l   =0x{BOX_Y:08X}, r1
    mov.l   =0x00000080, r3
    mov.w   r3, @r1                     ; y = 128 exactly, x = 0: the engine's park
    mov.l   =0x{BOX_X:08X}, r1
    mov     #0, r0
    mov.w   r0, @r1
    mov.l   =0x{OBJ0_LIST:08X}, r1
    mov.l   =0x{BOX_LIST:08X}, r2
    mov.l   r2, @r1
    mov.l   =0x{CELLS:08X}, r1
    mov     #20, r3
    mov     #4, r4
    bsr     clear_cells
    nop
    mov     #0, r0
    mov.l   r0, @(28, r9)
    mov.l   r0, @(24, r9)
    bra     render
    mov.l   r0, @(16, r9)
p_lost:
    ; object 0 still on our plain list: the box list back. The engine wrote its own cells
    ; (a menu or a card) into the box we hold open - it opens the verb menu straight onto
    ; an open box without touching object 0 - and our list draws its own glyphs, so the
    ; screen froze on our card while the game ran underneath (the navigator reel's last
    ; card lingering into the Mechanic room's menu, Luiz on the MiSTer, 2026-10-01).
    mov.l   =0x{OBJ0_LIST:08X}, r1
    mov.l   @r1, r2
    mov.l   @(20, r9), r3
    cmp/eq  r3, r2
    bf      p_lost2
    mov.l   =0x{BOX_LIST:08X}, r2
    mov.l   r2, @r1
p_lost2:
    bsr     prio_back
    nop
    mov     #4, r0
    mov.l   r0, @(28, r9)
    mov     #0, r0
    mov.l   r0, @(24, r9)
    bra     render
    mov.l   r0, @(16, r9)
p_yield:
    mov.l   =0x{BOX_LIST:08X}, r2       ; r1 = &object 0's list, still ours: the box list back
    mov.l   r2, @r1
p_yield_gone:
    bsr     prio_back
    nop
    mov     #0, r0
    mov.l   r0, @(28, r9)
    mov.l   r0, @(24, r9)
    bra     render
    mov.l   r0, @(16, r9)
    ; ---- a band card is up
band_up:
    cmp/eq  r6, r10
    bf      b_change
    mov     r7, r0
    cmp/eq  #1, r0
    bf      b_change
    mov.l   =0x{OBJ0_LIST:08X}, r1     ; still ours? the script's band re-open for a new line under an
    mov.l   @r1, r2                     ; open band puts the band list back: re-take it (the cells are
    mov.l   =curlist, r3                ; ours - no text path ran); anything else took object 0: drop
    mov.l   @r3, r3
    cmp/eq  r3, r2
    bt      bu_same
    mov.l   =0x{BAND_LIST:08X}, r0
    cmp/eq  r0, r2
    bf      drop
    mov.l   r3, @r1
bu_same:
    mov.l   =bplain, r1                 ; a plain-in-band card whose speaker's portrait lands LATE (the
    mov.l   @r1, r0                     ; Chief's office: the band opened while his chunk was still
    tst     r0, r0                      ; loading into slot 6, the wait ran out, the nameplate card
    bt      to_render2                  ; stayed - 2026-09-16) upgrades to the face layout the frame
    mov.l   =facecue, r1                ; a column carries the speaker (face_ready = 1)
    mov.l   r6, @r1
    bsr     face_ready
    nop
    cmp/eq  #1, r0
    bf      to_render2
    bra     sb_face
    nop
to_render2:
    bra     render
    nop
b_change:
    mov.l   =0x{OBJ0_LIST:08X}, r1
    mov.l   @r1, r2
    mov.l   =curlist, r3
    mov.l   @r3, r3
    cmp/eq  r3, r2
    bf      drop                        ; not ours any more: leave the cells alone
    mov.l   =0x{BAND_LIST:08X}, r2
    mov.l   r2, @r1
    bsr     clear_band
    nop
drop:
    mov     #0, r0
    mov.l   r0, @(24, r9)
    bra     render                      ; a new cue (r6) is taken up next frame from a clean state
    mov.l   r0, @(16, r9)
    ; ---- no card up
no_card:
    mov.l   @(28, r9), r0
    cmp/eq  #4, r0
    bf      no_card2
    mov     r7, r0                      ; LOST, and the BAND has the box (mode 1, or 3 while it slides):
    cmp/eq  #1, r0                      ; the engine took our plain card for a voiced line's band - the
    bt      lost_band                   ; HQ arrival reel: 'We've returned to JUNKER HQ' plain outside,
    cmp/eq  #3, r0                      ; then Mika's band at the front desk and NO card until the band
    bt      lost_band                   ; closed at the Chief's office (Luiz, 2026-09-16). Over: band cards
    mov.l   =0x{BOX_Y:08X}, r1          ; LOST: wait for the engine to close the box and put its list back
    mov.w   @r1, r1
    extu.w  r1, r1
    mov.l   =0x00000080, r2
    cmp/eq  r2, r1
    bf      to_render3
    mov.l   =0x{OBJ0_LIST:08X}, r1
    mov.l   @r1, r1
    mov.l   =0x{BOX_LIST:08X}, r2
    cmp/eq  r2, r1
    bf      to_render3
    mov     #0, r0
    bra     render
    mov.l   r0, @(28, r9)
to_render3:
    bra     render
    nop
lost_band:
    mov     #0, r0
    mov.l   r0, @(28, r9)
no_card2:
    tst     r6, r6
    bt      nc_idle
    mov     r7, r0
    cmp/eq  #1, r0
    bt      show_band
    cmp/eq  #3, r0
    bt      pre_face
    cmp/eq  #2, r0
    bf      to_render3
    mov.l   @(28, r9), r0
    tst     r0, r0
    bf      to_render3                  ; a plain card only from the idle state
    ; the box frame on its VDP2 layer = the pre-text's 0x060B6F20(10, 20), inlined: that
    ; function builds the job {{layer, picture, 1, 0}} on ITS STACK and 0x060B6924 ->
    ; 0x060B30A0 queues it by POINTER (ctx+0x36C: +8 = &job, +12 = &job + 8) for the next
    ; frame wait's 0x060B3108 - from this hook (inside the frame wait) that stack is long
    ; reused by then, so the job lives in the blob. 0x060B6924 also leaves r6 on the job
    ; (r6 = r15 - 2 in the first wedged state): the cue is kept across the call.
    mov.l   =job, r1
    mov     #10, r0
    mov.w   r0, @r1
    add     #2, r1
    mov     #20, r0
    mov.w   r0, @r1
    add     #2, r1
    mov     #1, r0
    mov.w   r0, @r1
    add     #2, r1
    mov     #0, r0
    mov.w   r0, @r1
    mov.l   =0x{FRAME_JOB:08X}, r1
    mov.l   =job, r4
    mov.l   r6, @-r15
    jsr     @r1
    nop
    mov.l   @r15+, r6
    mov.l   =0x{MENU_LIVE:08X}, r1
    mov     #0, r0
    mov.b   r0, @r1
    bsr     plain_write
    nop
    mov.l   @(20, r9), r2
    mov.l   =0x{OBJ0_LIST:08X}, r1
    mov.l   r2, @r1
    mov.l   =oprio, r1                  ; the opening: object 0 drawn LAST (its boards' sprites run at
    mov.l   @r1, r2                     ;   priorities 30/31, over the box's 28), the engine's byte kept
    tst     r2, r2
    bt      po_keep
    mov.l   =0x{OBJ0_PRIO:08X}, r3
    mov.b   @r3, r0
    extu.b  r0, r0
    mov.l   r0, @(4, r1)                ; oprio_save
    mov.b   r2, @r3
po_keep:
    mov.l   =0x{BOX_X:08X}, r1
    mov     #0, r0
    mov.w   r0, @r1
    mov.l   =linger, r1                 ; (#50) a fresh card starts a fresh linger (a LOST
    mov.l   r0, @r1                     ;   or yielded card leaves the counter where it was)
    mov     #1, r0
    mov.l   r0, @(28, r9)
    mov     #2, r0
    mov.l   r0, @(24, r9)
    bra     render
    mov.l   r6, @(16, r9)
nc_idle:
    ; (#72) the band is up (or sliding) with NO voice line yet - the script's pre-roll:
    ; it shows every column at its native x (24 + 96 col) and sets the voice id 20-40 frames
    ; later (the op 0x21 stub cannot tell the line: id 0). The column at the window stays,
    ; the others park, so the first speaker never rides in from 120/216 beside another face
    ; (B250 c10f33: Gillian at 24 + Metal Gear at 216 for 42 frames; the B230 arrival reel 26)
    mov     r7, r0
    cmp/eq  #1, r0
    bt      nc_band
    cmp/eq  #3, r0
    bf      to_render3
nc_band:
    mov.l   =0x{VOICE_ID:08X}, r1
    mov.w   @r1, r1
    extu.w  r1, r1
    tst     r1, r1
    bf      nc_voice
    bsr     park_off
    nop
    bra     render
    nop
nc_voice:
    ; a live voice line with no card under the band (#59: Napoleon's sneeze, line 391, has no
    ; cue - the script re-showed all three columns at their native x and the sneeze sprite at
    ; 216). The column whose mouth list carries the id to the window, the others away, no text.
    ; A CUED line's columns were parked by the op 0x21 stub (x = FACE_AWAY) until its card:
    ; left alone, the card's own path lays them out.
    mov     r7, r0
    cmp/eq  #1, r0
    bf      to_render3
    bsr     scan_cols                   ; r2 = the column carrying the id, or 3
    nop
    mov     r2, r0
    cmp/eq  #3, r0
    bt      to_render3
    bsr     col_act                     ; r3 = its base cel
    nop
    cmp/eq  #1, r0
    bf      to_render3
    mov.w   @(8, r3), r0
    mov.l   =0x{FACE_AWAY:08X}, r1
    cmp/eq  r1, r0
    bt      to_render3
    bsr     lay_col
    nop
    bra     render
    nop
pre_face:
    mov.l   =facecue, r1
    mov.l   r6, @r1
    bsr     face_left
    nop
    bra     render
    nop
show_band:
    ; the wait for the face (the PS1's QHOLD, #40): the script appends the voice id to the
    ; speaker's column (op 0x36) some frames after the line starts - 7-8 in the Chief's
    ; room - and a card typed before that sits beside the PREVIOUS speaker's face. So the
    ; card waits, every column parked off screen, until a mouth list carries the id or
    ; QHOLD_MAX frames have passed; a reel cue or no live id shows at once.
    mov.l   =facecue, r1
    mov.l   r6, @r1
    bsr     face_ready                  ; r0: 1 a column carries the speaker, 0 none, 2 not ours to place
    nop                                 ;   3 the speaker has no portrait on screen: plain now
    cmp/eq  #1, r0
    bt      sb_face
    cmp/eq  #3, r0
    bt      sb_plain
    cmp/eq  #2, r0
    bt      sb_engine
    mov.l   =qhold, r1                  ; none: wait QHOLD_MAX frames for the script (the id on a mouth
    mov.l   @r1, r2                     ; list for a mono line, the column shown for a reel: f5_4 went
    add     #1, r2                      ; plain-in-band when Gillian's column came a frame late)
    mov.l   r2, @r1
    mov     #{QHOLD_MAX}, r0
    cmp/ge  r0, r2
    bt      sb_plain
    bsr     park_all
    nop
    bra     render
    nop
sb_plain:
    ; the PS1's plain card inside the band (Metal Gear in the Mechanic room, a reel speaker
    ; with no column): every column parked, the nameplate at (0,0), the rows below from
    ; column 0, object 0 on the 80-cell band list
    bsr     park_all
    nop
    bsr     plain_write
    nop
    mov.l   =bplain, r1
    mov     #1, r0
    mov.l   r0, @r1
    mov.l   @(12, r9), r2
    mov.l   =0x{BP_OFF:08X}, r0
    add     r0, r2
    bra     sb_show
    nop
sb_engine:
sb_face:
    bsr     clear_band
    nop
    mov.l   =bplain, r1
    mov     #0, r0
    mov.l   r0, @r1
    mov.l   @(16, r6), r1               ; the band text beside the face
    mov.l   =0x{BAND_CELL0:08X}, r2
    mov     #{COLS}, r3
    mov.l   =0x{BAND_CELL0 + 80 * ROWS:08X}, r8
    bsr     write_text
    nop
    mov.l   @(12, r9), r2
sb_show:
    mov.l   =curlist, r1
    mov.l   r2, @r1
    mov.l   =qhold, r1
    mov     #0, r0
    mov.l   r0, @r1
    mov.l   =0x{MENU_LIVE:08X}, r1
    mov.b   r0, @r1
    mov.l   =0x{OBJ0_LIST:08X}, r1
    mov.l   r2, @r1
    mov     #1, r0
    mov.l   r0, @(24, r9)
    bra     render
    mov.l   r6, @(16, r9)
.pool
    ; ---- the renderer, then our list gets the records it built
render:
    mov.l   =0x{RENDER:08X}, r0
    jsr     @r0
    nop
    mov.l   @(16, r9), r7
    tst     r7, r7
    bt      done
    mov.l   @(24, r9), r0
    cmp/eq  #2, r0
    bt      copy_plain
    mov.l   =bplain, r1
    mov.l   @r1, r1
    tst     r1, r1
    bt      copy_face
    bsr     park_all                    ; plain-in-band: no portrait, all 80 cells
    nop
    mov.l   =0x{RECS:08X}, r1
    mov.l   @(12, r9), r2
    mov.l   =0x{BP_OFF:08X}, r0
    add     r0, r2
    add     #8, r2
    bra     plp_go
    nop
copy_face:
    mov.l   =facecue, r1
    mov.l   r7, @r1
    bsr     face_left                   ; the speaking column to the band's window, the others away
    nop
    mov.l   =0x{RECS + 12 * (20 * ROW0 + COL0):08X}, r1
    mov.l   @(12, r9), r2
    add     #8, r2
    mov     #{ROWS}, r3
rowloop:
    mov     #{COLS * 3}, r4
reclp:
    mov.l   @r1+, r0
    mov.l   r0, @r2
    add     #4, r2
    dt      r4
    bf      reclp
    add     #{(20 - COLS) * 12}, r1
    dt      r3
    bf      rowloop
    bra     done
    nop
copy_plain:
    mov.l   =0x{RECS:08X}, r1
    mov.l   @(20, r9), r2
    add     #8, r2
plp_go:
    mov.l   =0x000000F0, r4             ; 80 records x 3 words
plp:
    mov.l   @r1+, r0
    mov.l   r0, @r2
    add     #4, r2
    dt      r4
    bf      plp
done:
    bsr     extras                      ; once a frame, after the layout: sprites follow their column (#48/#55/#57/#59/#45)
    nop
    mov.l   @r15+, r14
    mov.l   @r15+, r13
    mov.l   @r15+, r12
    mov.l   @r15+, r11
    mov.l   @r15+, r10
    mov.l   @r15+, r9
    mov.l   @r15+, r8
    lds.l   @r15+, pr
    rts
    nop
.pool
    ; ---- subroutines ----
own_check:
    ; r0 = 1 while object 0 shows our plain list and cells (0,0) and (1,0) still hold what we wrote
    mov.l   =0x{OBJ0_LIST:08X}, r1
    mov.l   @r1, r1
    mov.l   @(20, r9), r2
    cmp/eq  r2, r1
    bf      own_no
    mov.l   =cellcodes, r3              ; (code at (0,0)) << 16 | code at (1,0)
    mov.l   @r3, r3
    mov.l   =0x{CELLS:08X}, r1
    mov.w   @r1, r2
    extu.w  r2, r2
    mov     r3, r0
    shlr16  r0
    cmp/eq  r2, r0
    bf      own_no
    add     #80, r1
    mov.w   @r1, r2
    extu.w  r2, r2
    extu.w  r3, r0
    cmp/eq  r2, r0
    bf      own_no
    rts
    mov     #1, r0
own_no:
    rts
    mov     #0, r0
ytarget:
    ; r4 = a cue (or 0) -> r0 = the open box's y: 0, or with `pcuey` set (the opening) the cue's
    ; own y at +28 (gen_intro.py: the rows just under the picture where it leaves black)
    mov.l   =pcuey, r0
    mov.l   @r0, r0
    tst     r0, r0
    bt      yt_ret
    tst     r4, r4
    bt      yt_zero
    mov.l   @(28, r4), r0
    rts
    nop
yt_zero:
    mov     #0, r0
yt_ret:
    rts
    nop
prio_back:
    ; object 0's priority byte back to what the plain card found (oprio_save; 0 = nothing saved)
    mov.l   =oprio_save, r1
    mov.l   @r1, r0
    tst     r0, r0
    bt      pb_ret
    mov.l   =0x{OBJ0_PRIO:08X}, r2
    mov.b   r0, @r2
    mov     #0, r0
    mov.l   r0, @r1
pb_ret:
    rts
    nop
plain_write:
    ; r6 = cue: clear the 80 cells, the nameplate (cue+20, 0 = none) at (0,0), the card's rows
    ; (the wide text at 20 cells when the cue has one, else the band text's 14-cell rows) from the
    ; row below it at column 0, remember the two codes
    sts.l   pr, @-r15
    mov.l   =0x{CELLS:08X}, r1
    mov     #20, r3
    mov     #4, r4
    bsr     clear_cells
    nop
    mov.l   =ptext0, r2                 ; the text's first cell with no nameplate (build_blob: row 0,
    mov.l   @r2, r2                     ;   or row 1 for the opening's three rows)
    mov.l   @(20, r6), r1
    tst     r1, r1
    bt      pw_text
    mov     #20, r3
    mov.l   =0x{CELLS + 80:08X}, r8
    bsr     write_text
    nop
    mov.l   =0x{CELLS + 80:08X}, r2
pw_text:
    mov.l   @(16, r6), r1
    mov.l   =pcols, r3                  ; cells per row: the band text's 14, the opening's 20
    mov.l   @r3, r3
    mov     r1, r5                      ; the wide text (20 cells, no portrait) follows the band
pw_end:                                 ;   text's end word; an empty one = draw the band rows
    mov.w   @r5+, r0
    tst     r0, r0
    bf      pw_end
    mov.w   @r5, r0
    tst     r0, r0
    bt      pw_go
    mov     r5, r1
    mov     #{WIDE_COLS}, r3
pw_go:
    mov.l   =0x{CELLS + 80 * 4:08X}, r8
    bsr     write_text
    nop
    mov.l   =0x{CELLS:08X}, r1
    mov.w   @r1, r0
    extu.w  r0, r0
    shll16  r0
    add     #80, r1
    mov.w   @r1, r2
    extu.w  r2, r2
    or      r2, r0
    mov.l   =cellcodes, r1
    mov.l   r0, @r1
    lds.l   @r15+, pr
    rts
    nop
write_text:
    ; r1 = text (u16 codes: 0x818F row break, 0x810c colour c, 0 end), r2 = first cell of the
    ; first row, r3 = cells per row, r8 = the first cell past the last row. Clobbers r0, r4, r5, r11-r14.
    mov     #7, r12                     ; colour
    mov     #0, r11                     ; column
    mov.l   =0x{ROWBREAK:08X}, r13
    mov.l   =0x00000810, r4
wt_loop:
    mov.w   @r1+, r0
    extu.w  r0, r0
    tst     r0, r0
    bt      wt_done
    cmp/eq  r13, r0
    bt      wt_break
    mov     r0, r14
    shlr2   r0
    shlr2   r0
    cmp/eq  r4, r0
    bf      wt_char
    mov     r14, r0
    and     #15, r0
    bra     wt_loop
    mov     r0, r12
wt_char:
    mov.w   r14, @r2
    add     #2, r2
    mov.b   r12, @r2
    add     #2, r2
    add     #1, r11
    cmp/eq  r11, r3
    bf      wt_loop
wt_break:
    tst     r11, r11                    ; a break right after a full row: the row already turned
    bt      wt_loop
    mov     r11, r0
    shll2   r0
    sub     r0, r2
    add     #80, r2
    mov     #0, r11
    cmp/hs  r8, r2
    bt      wt_done
    bra     wt_loop
    nop
wt_done:
    rts
    nop
face_left:
    ; The PS1's face-left layout (GitHub #23). The room script shows a column per
    ; speaker (op 0x21, x = 24 + 96*col) and never takes the previous one down, and the
    ; band's VDP2 frame has ONE clean window at x = 24 - columns at 120/216 show as
    ; strips through its grille. So: the column whose mouth cel carries the live voice
    ; id (ctx+0x560, what the script's own dispatch keys on) goes to x = 24 and every
    ; other column off screen. Only x is touched: the band close keys on act and y and
    ; resets both, and the next line's op 0x21 rewrites x - nothing to restore.
    ; A speaker whose column is hidden (act != 1) is left to the engine. Clobbers r0-r5,
    ; no nested bsr (pr belongs to the caller).
    sts.l   pr, @-r15
    mov.l   =facecue, r1                ; the cue (the card up, or the live line's during the band's slide)
    mov.l   @r1, r1
    tst     r1, r1
    bt      fl_done
    mov.w   @r1, r0                     ; a REEL card names no voice line (ctx+0x560 is stale): its
    extu.w  r0, r0                      ; speaker's column is found by the cue's face words instead
    mov.l   =0x0000{REEL_TAG:04X}, r2   ; (fl_reel); a reel with no speaker leaves the engine's layout
    cmp/eq  r2, r0
    bt      fl_reel
    mov.l   =0x{VOICE_ID:08X}, r1
    mov.w   @r1, r1
    extu.w  r1, r1
    tst     r1, r1
    bt      fl_done
    bsr     scan_cols                   ; r2 = the column whose mouth list holds the id, or 3
    nop
    mov     r2, r0
    cmp/eq  #3, r0
    bf      fl_verify
    ; no column carries the id: a known character is placed by CONTENT (#64, 2026-09-17:
    ; eight of Metal Gear's reconstruction lines are attached to no column while his
    ; portrait is up; the ending's 'Gillian!' of Randam's drew Jamie's column, the
    ; engine's layout, beside the plain card) - the column whose slot holds the speaker's
    ; picture goes to the window, and with none every column parks (the plain card in
    ; the band, as face_ready decided). A speaker with no portrait chunk keeps the old
    ; way: the miss counter, then the engine's layout.
    mov.l   =facecue, r1
    mov.l   @r1, r1
    bsr     cue_char                    ; r3 = the cue's character (0 = none known)
    nop
    tst     r3, r3
    bt      fl_native
    bsr     reel_col                    ; r2 = the speaker's column by content, or 3 (all away)
    nop
    bra     fl_move
    nop                                 ;   (never fl_reel - it once fell through into it with
fl_reel:                                ;   r1 = the ID, and `mov.w @(2, r1)` on an odd id was an
                                        ;   address error: B0E0's stall after 'Eat Kobe-yaki' (2026-09-17)
    mov.w   @(2, r1), r0                ; the reel flag (build_blob): 0 = no face known
    tst     r0, r0
    bt      fl_keep0
    bsr     reel_col                    ; r2 = the column carrying the cue's face, or 3 (all away)
    nop
    bra     fl_move
    nop
fl_keep0:
    ; no face known for this reel line (B080's debrief: the Chief, Harry, Mika have no
    ; witness in the room script): keep whatever column the engine put in the window and
    ; park the ones at 120/216 - never the pile-up, never text over a portrait; at worst
    ; a listener's face, the PS1's look before its face-left layout (= park_off)
    bsr     park_off
    nop
    bra     fl_done
    nop
fl_native:
    ; no column carries the voice id (or the speaker's is hidden and has no face here):
    ; the engine's own layout - every column back at its native x = 24 + 96 * col, which
    ; the exec stub on op 0x21 (FACE_STUB_ASM) replaced with FACE_AWAY for a cued line.
    ; Not at once: the script appends the voice id a frame or two AFTER op 0x21 (op 0x36),
    ; and a card can be up by then - a restore on the first miss would draw the flash the
    ; stub removes. Six misses running (100 ms) mean the script really names no column.
    mov.l   =flmiss, r1
    mov.l   @r1, r0
    add     #1, r0
    mov.l   r0, @r1
    cmp/eq  #{FL_MISSES}, r0
    bf      fl_done
    mov     #0, r0
    mov.l   r0, @r1
    mov.l   =0x{OBJ_BASE0:08X}, r3
    mov     #0, r5
    mov     #{FACE_X}, r2
fl_nat:
    mov.b   @r3, r0                     ; a SHOWN column only (act 1): one the script hid (op 0x3E/0x4B,
    cmp/eq  #1, r0                      ;   x 0x7000, y 16) and a park turned into FACE_AWAY came back
    bf      fl_nskip                    ;   at its native x with the hidden y - Madnar and Gillian over
    mov     r3, r4                      ;   the picture's top left in the ending (Luiz, 2026-09-30)
    mov     #3, r1
fl_ncel:
    add     #8, r4
    mov.w   r2, @r4
    add     #68, r4
    dt      r1
    bf      fl_ncel
fl_nskip:
    add     #{FACE_COL_PITCH}, r2
    add     #114, r3
    add     #114, r3
    add     #1, r5
    mov     r5, r0
    cmp/eq  #3, r0
    bf      fl_nat
fl_done:
    lds.l   @r15+, pr
    rts
    nop
fl_verify:
    ; a mono cue with a known character (flag 2 at +2: the speaker has a portrait chunk
    ; and the cue no face words; +24 = the character): the script's mouth list can name
    ; the wrong column - B190, Gillian's mouth flaps for two of Napoleon's lines and her
    ; face rode into the window (Luiz, 2026-09-16). A column whose slot holds someone
    ; ELSE's known portrait is not the speaker's: the speaker's column by content
    ; (reel_col), or every column away (the plain card in the band). An unlabelled
    ; portrait on the column keeps the mouth list's word.
    ; Since 2026-09-17 (#68) the check runs for every mono cue whose speaker has a portrait
    ; chunk, face words or not (the ending's script animates Gillian for four of Madnar's
    ; lines and Madnar for one of Gillian's, and those cues carry their own op 0x21 words):
    ; the character rides in the high byte of the flag word at +2, and only a SHOWN column
    ; is judged - a hidden one is the dress path's (its slot says nothing about the dress).
    mov.l   =facecue, r1
    mov.l   @r1, r1
    bsr     cue_char                    ; r3 = the cue's character (0 = none known)
    nop
    tst     r3, r3
    bt      fl_found
    bsr     col_act                     ; r0 = act of column r2
    nop
    cmp/eq  #1, r0
    bf      fl_found
    bsr     col_char                    ; r0 = the known character on column r2's slot, or 0
    nop
    tst     r0, r0
    bt      fl_found
    bsr     cue_char                    ; r3 again (col_char clobbers it)
    nop
    cmp/eq  r3, r0
    bt      fl_found
    bsr     reel_col                    ; r2 = the speaker's column by content, or 3
    nop
    bra     fl_move
    nop
fl_found:
    mov.l   =0x{OBJ_BASE0:08X}, r3      ; the speaking column's base cel
    mov     r2, r0
    tst     r0, r0
    bt      fl_shown
fl_mul:
    add     #114, r3
    add     #114, r3
    dt      r0
    bf      fl_mul
fl_shown:
    mov.b   @r3, r0
    extu.b  r0, r0
    cmp/eq  #1, r0
    bt      fl_move
    mov.l   r2, @-r15                   ; hidden (op 0x3E/0x4B, x = 0x7000): dress it from the cue's face
    bsr     dress
    nop
    mov.l   @r15+, r2
    tst     r0, r0
    bt      fl_native                   ; no resident face for this line: the engine's layout, nameplate
fl_move:
    mov.l   =flmiss, r3
    mov     #0, r0
    mov.l   r0, @r3
    bsr     lay_col                     ; r2 to the window, the others away
    nop
    bra     fl_done
    nop
extras:
    ; Sprites the room script builds beside the columns (op 0x05 obj anim ... buf slot, placed
    ; by op 0x1C at a column's native x, y 160; 0x0C waits, 0x13 deletes): the Teller's trance
    ; (B0D0, #48/#55), Metal Gear looking left (B1A0, #57: out of the ROOM's sprite slot 3,
    ; not a face slot), Napoleon's sneeze (B1D0, #59), the Cook's bowl (B0E0). Once a frame from
    ; `done`, after the layout. A live object 10..{EX_LAST:#x} on a shown column's row (same y as
    ; its cels) belongs to that column if it sits within 48 of where the column WAS at the
    ; entry (`exhx`, before this frame's layout; only the owner `exown` remembers) or else
    ; within 48 of a column's NATIVE x (`natx`: just placed by op 0x1C) - by position, not
    ; slot or buffer - and follows it: x = the column's x now + that offset. A sprite that
    ; REPLACES its column's picture (one record at 0,0 the size of the base cel's one record:
    ; the trance, the sneeze) hides the three cels for the frame (x + HIDE_DX) - the still
    ; portrait's hair showed through (#55). A sprite no column owns on the band row (y 160) in
    ; the text area (x 90..399) under a band card is hidden for the frame the same way (#45: the
    ; ruins' Metal Gear is a room sprite at 210, not a column; Gillian's push). `unhide` at the
    ; entry takes every HIDE_DX back. Clobbers r0-r8, r10-r14 (`done` restores); r9 = the blob.
    mov.l   =0x{SCENE_VAR:08X}, r1
    mov.w   @r1, r1
    mov.w   @(4, r9), r0
    cmp/eq  r1, r0
    bt      ex_go
    rts
    nop
ex_go:
    mov.l   =0x{OBJ_BASE0:08X}, r12
    mov.l   =0x{OBJ_BASE0 + 76 * 9:08X}, r3    ; object 10
    mov.l   =exown, r14
    mov     #{EX_LAST - 9}, r7
ex_obj:
    mov.b   @r14, r0
    mov     r0, r2
    add     #-1, r2                     ; r2 = the owner column, or -1
    mov     #0, r0
    mov.b   r0, @r14
    mov.b   @r3, r0
    cmp/eq  #1, r0
    bf      ex_next
    mov.w   @(8, r3), r0
    mov     r0, r6                      ; r6 = its x
    mov.w   @(12, r3), r0
    mov     r0, r8                      ; r8 = its y
    mov.l   =exhx, r10                  ; pass 1: the owner's x at the entry; pass 2: natx
ex_pass:
    mov     r12, r4
    mov     #0, r11
ex_ac:
    mov.b   @r4, r0
    cmp/eq  #1, r0
    bf      ex_acn
    mov.w   @(12, r4), r0
    cmp/eq  r8, r0
    bf      ex_acn
    mov.l   =natx, r0
    cmp/hs  r0, r10
    bt      ex_try                      ; pass 2: any column
    cmp/eq  r11, r2
    bf      ex_acn
ex_try:
    mov.w   @r10, r0
    mov     r6, r5
    sub     r0, r5                      ; r5 = the offset
    mov     r5, r0
    add     #48, r0
    mov     #96, r1
    cmp/hs  r1, r0
    bf      ex_own                      ; -48 <= offset < 48
ex_acn:
    add     #114, r4
    add     #114, r4
    add     #2, r10
    add     #1, r11
    mov     r11, r0
    cmp/eq  #3, r0
    bf      ex_ac
    mov.l   =natx, r0
    cmp/eq  r0, r10
    bt      ex_pass
    mov.l   =0x000000A0, r1             ; nobody's: hide it for the frame if it sits on the band
    cmp/eq  r1, r8                      ;   row in the text area under a band card
    bf      ex_next
    mov     #90, r1
    cmp/ge  r1, r6
    bf      ex_next
    mov.l   =0x{FACE_AWAY:08X}, r1
    cmp/ge  r1, r6
    bt      ex_next
    mov.l   @(16, r9), r0
    tst     r0, r0
    bt      ex_next
    mov.l   @(24, r9), r0
    cmp/eq  #1, r0
    bf      ex_next
    mov     #{HIDE_DX >> 8}, r0
    shll8   r0
    add     r6, r0
    bra     ex_next
    mov.w   r0, @(8, r3)
ex_own:
    mov     r11, r0
    add     #1, r0
    mov.b   r0, @r14
    mov.w   @(8, r4), r0                ; the column's x now (the window, away, or native)
    add     r5, r0
    mov.w   r0, @(8, r3)
    mov.l   @(24, r3), r1               ; a replacement? one record at 0,0, the size of the base cel's
    tst     r1, r1
    bt      ex_next
    mov.l   @(24, r4), r2           ; (the base cels' record 0 sits at 0,0)
    tst     r2, r2
    bt      ex_next
    mov.w   @r1, r0
    cmp/eq  #1, r0
    bf      ex_next
    mov.l   @(16, r1), r0               ; record 0's x << 16 | y
    tst     r0, r0
    bf      ex_next
    mov.w   @(10, r1), r0               ; record 0's size word
    mov     r0, r5
    mov.w   @(10, r2), r0
    cmp/eq  r5, r0
    bf      ex_next
    mov     #{HIDE_DX >> 8}, r1         ; hide the column's three cels (once)
    shll8   r1
    add     #8, r4
    mov.w   @r4, r0
    cmp/ge  r1, r0
    bt      ex_next
    mov     #3, r5
ex_hc:
    mov.w   @r4, r0
    add     r1, r0
    mov.w   r0, @r4
    dt      r5
    bf/s    ex_hc
    add     #76, r4
ex_next:
    add     #76, r3
    add     #1, r14
    dt      r7
    bt      ex_ret
    bra     ex_obj
    nop
ex_ret:
    rts
    nop
unhide:
    ; at the entry: every cel and object 1..{EX_LAST:#x} `extras` hid last frame (HIDE_DX <= x <
    ; 2 HIDE_DX; op 0x3E's hidden columns sit at 0x7000, above) back at its x; then the
    ; columns' x (as the layout will find them) into `exhx`. Leaf; clobbers r0-r4.
    mov.l   =0x{OBJ_BASE0 + 8:08X}, r1
    mov     #{EX_LAST}, r2
    mov     #{HIDE_DX >> 8}, r3
    shll8   r3
    mov     r3, r4
    shll    r4
uh_obj:
    mov.w   @r1, r0
    cmp/ge  r3, r0
    bf      uh_next
    cmp/ge  r4, r0
    bt      uh_next
    sub     r3, r0
    mov.w   r0, @r1
uh_next:
    dt      r2
    bf/s    uh_obj
    add     #76, r1
    mov.l   =0x{OBJ_BASE0 + 8:08X}, r1
    mov.l   =exhx, r2
    mov     #3, r3
uh_col:
    mov.w   @r1, r0
    mov.w   r0, @r2
    add     #2, r2
    add     #114, r1
    dt      r3
    bf/s    uh_col
    add     #114, r1
    rts
    nop
.pool
scan_cols:
    ; r1 = a voice id -> r2 = the column (0-2) whose mouth cel's list of up to 8 ids holds
    ; it, or 3. Leaf; clobbers r0, r3-r5.
    mov     #0, r2
    mov.l   =0x{OBJ_MOUTH0:08X}, r3
sc_col:
    mov     r3, r4
    add     #60, r4
    mov     #8, r5
sc_id:
    mov.w   @r4, r0
    extu.w  r0, r0
    cmp/eq  r1, r0
    bt      sc_found
    add     #2, r4
    dt      r5
    bf      sc_id
    add     #114, r3                    ; the next column: 3 objects of 76 bytes
    add     #114, r3
    add     #1, r2
    mov     r2, r0
    cmp/eq  #3, r0
    bf      sc_col
sc_found:
    rts
    nop
face_ready:
    ; the card at facecue: r0 = 1 a column carries its speaker (the voice id on a mouth
    ; list for a mono line; the cue's face words on a shown column for a reel), 0 none,
    ; 2 not ours to place (a reel with no face known, no live voice id): the engine's
    ; layout stands. Clobbers r0-r5 (r6/r7 kept: the callers' cue).
    sts.l   pr, @-r15
    mov.l   =facecue, r1
    mov.l   @r1, r1
    tst     r1, r1
    bt      fr_engine
    mov.w   @r1, r0
    extu.w  r0, r0
    mov.l   =0x0000{REEL_TAG:04X}, r2
    cmp/eq  r2, r0
    bf      fr_mono
    mov.w   @(2, r1), r0                ; the reel flag: 0 = no face known
    tst     r0, r0
    bt      fr_engine
    mov.l   r6, @-r15                   ; reel_col clobbers r6/r7: show_band's cue lives in r6 (a wedge
    mov.l   r7, @-r15                   ; on the navigator reel, the first reel with a face, 2026-09-16)
    bsr     reel_col
    nop
    mov.l   @r15+, r7
    mov.l   @r15+, r6
    bra     fr_col
    nop
fr_mono:
    mov.l   =0x{VOICE_ID:08X}, r1
    mov.w   @r1, r1
    extu.w  r1, r1
    tst     r1, r1
    bt      fr_engine
    bsr     scan_cols
    nop
    mov     r2, r0                      ; (see fl_verify): a SHOWN column's portrait must not be
    cmp/eq  #3, r0                      ; someone else's known face
    bf      fr_scanned
    mov.l   =facecue, r1                ; no mouth list carries the id: a known character's
    mov.l   @r1, r1                     ; column by content (#64), else 3 stands
    bsr     cue_char
    nop
    tst     r3, r3
    bt      fr_col
    mov.l   r6, @-r15
    mov.l   r7, @-r15
    bsr     reel_col
    nop
    bra     fr_vok
    nop
fr_scanned:
    mov.l   =facecue, r1
    mov.l   @r1, r1
    bsr     cue_char                    ; r3 = the cue's character (0 = none known)
    nop
    tst     r3, r3
    bt      fr_col
    bsr     col_act
    nop
    cmp/eq  #1, r0
    bf      fr_col
    mov.l   r6, @-r15
    mov.l   r7, @-r15
    bsr     col_char
    nop
    tst     r0, r0
    bt      fr_vok
    bsr     cue_char                    ; r3 again (col_char clobbers it)
    nop
    cmp/eq  r3, r0
    bt      fr_vok
    bsr     reel_col
    nop
    mov     r2, r0                      ; the script's column shows someone else's known
    cmp/eq  #3, r0                      ;   portrait and no shown column holds the speaker's: the
    bf      fr_vok                      ;   card goes plain-in-band NOW (3), no QHOLD wait (B230
    mov.l   @r15+, r7                   ;   'Mika!' of Gillian on Metal Gear's column: a 21-frame
    mov.l   @r15+, r6                   ;   line showed an empty window, 2026-09-23)
    lds.l   @r15+, pr
    rts
    mov     #3, r0
fr_vok:
    mov.l   @r15+, r7
    mov.l   @r15+, r6
fr_col:
    mov     r2, r0
    cmp/eq  #3, r0
    bt      fr_no
    mov.l   =0x{OBJ_BASE0:08X}, r3      ; the column must be SHOWN (act 1), or hidden with a face to
    mov     r2, r0                      ; dress it from (the cue's face words): 'Not bad.' rode a
    tst     r0, r0                      ; hidden column with no face, the dress failed and the
    bt      fr_act                      ; engine's layout (Harry under Gillian's text) came back
fr_mul:
    add     #114, r3
    add     #114, r3
    dt      r0
    bf      fr_mul
fr_act:
    mov.b   @r3, r0
    extu.b  r0, r0
    cmp/eq  #1, r0
    bt      fr_yes
    mov.l   =facecue, r1
    mov.l   @r1, r1
    mov.w   @(2, r1), r0                ; flag 2: +24 is the character, not a face to dress from
    extu.b  r0, r0                      ;   (the high byte is the character, since #68)
    cmp/eq  #2, r0
    bt      fr_no
    mov.l   @(24, r1), r0
    tst     r0, r0
    bt      fr_no
    bsr     cue_char                    ; the face words' slot must hold the speaker (or an
    nop                                 ;   unlabelled portrait): B230's Gillian lines carry Metal
    tst     r3, r3                      ;   Gear's slot [5,5,8] (the script shows his column for
    bt      fr_yes                      ;   them), the dress was believed and face_left then parked
    mov.l   @(28, r1), r0               ;   every column - an empty window beside band text
    shlr16  r0
    mov.l   r6, @-r15
    mov.l   r7, @-r15
    bsr     slot_char
    nop
    mov.l   @r15+, r7
    mov.l   @r15+, r6
    tst     r0, r0
    bt      fr_yes
    mov.l   =facecue, r1
    mov.l   @r1, r1
    bsr     cue_char
    nop
    cmp/eq  r3, r0
    bt      fr_yes
    lds.l   @r15+, pr
    rts
    mov     #3, r0
fr_yes:
    lds.l   @r15+, pr
    rts
    mov     #1, r0
fr_engine:
    lds.l   @r15+, pr
    rts
    mov     #2, r0
fr_no:
    lds.l   @r15+, pr
    rts
    mov     #0, r0
reel_col:
    ; r1 = a reel cue -> r2 = the SHOWN column (act 1) whose VDP1 slot holds a portrait of
    ; the cue's CHARACTER (+24; the blob's signature table names every portrait chunk's
    ; 16 bytes at SIG_OFF into its section = CMDSRCA base * 8 + SIG_OFF in VDP1 VRAM,
    ; cache-through at 0x25C00000), or 3. Which slot holds whom differs per room, and a
    ; reel names no line the script could be asked about: until 2026-09-16 a per-scene
    ; slot table stood here and the ruins' Metal Gear drew as a plain card in every
    ; room but the arrival's. Leaf; clobbers r0, r3-r7.
    mov.w   @(2, r1), r0                ; the character id: the flag word's high byte (#68;
    extu.w  r0, r0                      ;   +24 carries it too on reel and flag-2 cues, a face
    shlr8   r0                          ;   buffer on a mono cue with face words)
    mov     r0, r6
    mov.l   =0x{OBJ_BASE0:08X}, r3
    mov     #0, r2
rc_col:
    mov.b   @r3, r0
    extu.b  r0, r0
    cmp/eq  #1, r0
    bf      rc_next
    mov.w   @(28, r3), r0               ; CMDSRCA base of the base cel (8-byte units)
    extu.w  r0, r0
    shll2   r0
    shll    r0
    mov.l   =0x{VDP1_VRAM + SIG_OFF:08X}, r7
    add     r0, r7                      ; r7 = the slot's signature bytes
    mov.l   =sigtab, r4
    mov.l   @r4, r4
rc_rec:
    mov.w   @r4, r0
    extu.w  r0, r0
    tst     r0, r0
    bt      rc_next                     ; the table's end: nobody's portrait
    cmp/eq  r6, r0
    bf      rc_skip
    mov.l   @(4, r4), r0
    mov.l   @r7, r5
    cmp/eq  r5, r0
    bf      rc_skip
    mov.l   @(8, r4), r0
    mov.l   @(4, r7), r5
    cmp/eq  r5, r0
    bf      rc_skip
    mov.l   @(12, r4), r0
    mov.l   @(8, r7), r5
    cmp/eq  r5, r0
    bf      rc_skip
    mov.l   @(16, r4), r0
    mov.l   @(12, r7), r5
    cmp/eq  r5, r0
    bt      rc_found
rc_skip:
    add     #20, r4
    bra     rc_rec
    nop
rc_next:
    add     #114, r3
    add     #114, r3
    add     #1, r2
    mov     r2, r0
    cmp/eq  #3, r0
    bf      rc_col
rc_found:
    rts
    nop
cue_char:
    ; r1 = a cue -> r3 = its character (the flag word's high byte; 0 = none known). Leaf;
    ; clobbers r3 only (called after col_char, whose r0 is compared with it; the
    ; displacement load goes through r0, so r0 is saved on the stack around it).
    mov.l   r0, @-r15
    mov.w   @(2, r1), r0
    extu.w  r0, r0
    shlr8   r0
    mov     r0, r3
    rts
    mov.l   @r15+, r0
col_act:
    ; r2 = a column -> r0 = its base cel's act byte (1 = shown). Leaf; clobbers r0, r3.
    mov.l   =0x{OBJ_BASE0:08X}, r3
    mov     r2, r0
    tst     r0, r0
    bt      ca_at
ca_mul:
    add     #114, r3
    add     #114, r3
    dt      r0
    bf      ca_mul
ca_at:
    mov.b   @r3, r0
    rts
    extu.b  r0, r0
col_char:
    ; r2 = a column -> r0 = the known character whose portrait its VDP1 slot holds (the
    ; blob's signature table, as reel_col reads it), or 0. Leaf; clobbers r0, r3-r5, r7.
    mov.l   =0x{OBJ_BASE0:08X}, r3
    mov     r2, r0
    tst     r0, r0
    bt      cc_at
cc_mul:
    add     #114, r3
    add     #114, r3
    dt      r0
    bf      cc_mul
cc_at:
    mov.w   @(28, r3), r0               ; CMDSRCA base of the base cel (8-byte units)
    extu.w  r0, r0
slot_char:                              ; r0 = a CMDSRCA base -> r0 = its character (same leaf)
    shll2   r0
    shll    r0
    mov.l   =0x{VDP1_VRAM + SIG_OFF:08X}, r7
    add     r0, r7
    mov.l   =sigtab, r4
    mov.l   @r4, r4
cc_rec:
    mov.w   @r4, r0
    extu.w  r0, r0
    tst     r0, r0
    bt      cc_ret                      ; the table's end: nobody's portrait, r0 = 0
    mov.l   @(4, r4), r3
    mov.l   @r7, r5
    cmp/eq  r5, r3
    bf      cc_skip
    mov.l   @(8, r4), r3
    mov.l   @(4, r7), r5
    cmp/eq  r5, r3
    bf      cc_skip
    mov.l   @(12, r4), r3
    mov.l   @(8, r7), r5
    cmp/eq  r5, r3
    bf      cc_skip
    mov.l   @(16, r4), r3
    mov.l   @(12, r7), r5
    cmp/eq  r5, r3
    bt      cc_ret                      ; r0 = the record's character
cc_skip:
    add     #20, r4
    bra     cc_rec
    nop
cc_ret:
    rts
    nop
park_off:
    ; (#72) every column NOT at the window (x != FACE_X) to FACE_AWAY. Leaf; clobbers r0-r5.
    mov.l   =0x{OBJ_BASE0:08X}, r3
    mov     #0, r5
po_col:
    mov     r3, r4
    add     #8, r4
    mov.w   @r4, r0
    extu.w  r0, r0
    cmp/eq  #{FACE_X}, r0
    bt      po_next
    mov.l   =0x{FACE_AWAY:08X}, r0
    mov     #3, r1
po_cel:
    mov.w   r0, @r4
    add     #76, r4
    dt      r1
    bf      po_cel
po_next:
    add     #114, r3
    add     #114, r3
    add     #1, r5
    mov     r5, r0
    cmp/eq  #3, r0
    bf      po_col
    rts
    nop
park_all:
    ; every column's three cels to x = FACE_AWAY (the wait for the face). Leaf; clobbers r0-r5.
    mov     #3, r2
lay_col:
    ; r2 = a column (3 = none): its three cels to the window (x = FACE_X), the others'
    ; to FACE_AWAY. Leaf; clobbers r0, r1, r3-r5.
    mov.l   =0x{OBJ_BASE0:08X}, r3
    mov     #0, r5
lc_col:
    mov     r5, r0
    cmp/eq  r2, r0
    bt      lc_here
    mov.l   =0x{FACE_AWAY:08X}, r0
    bra     lc_set
    nop
lc_here:
    mov     #{FACE_X}, r0
lc_set:
    mov     r3, r4
    mov     #3, r1                      ; base, eyes, mouth
lc_cel:
    add     #8, r4
    mov.w   r0, @r4
    add     #68, r4
    dt      r1
    bf      lc_cel
    add     #114, r3
    add     #114, r3
    add     #1, r5
    mov     r5, r0
    cmp/eq  #3, r0
    bf      lc_col
    rts
    nop
dress:
    ; A speaker the room script hides (op 0x3E/0x4B: the column exists only to carry the
    ; voice id for the mouth animator, x = 0x7000) but whose face the room HAS in a VDP1
    ; slot - Mika at the front desk, Harry in the Mechanic room. The cue carries that
    ; residency (roomfaces.py: the nearest line the script SHOWS the speaker on), and the
    ; column is dressed from a shown column as the template: a hidden column's cels carry
    ; type byte 1 instead of 25/26/27, so writing the face fields on its own bytes draws
    ; nothing (work/saturn/faces/poke_mika.py); copying a live cel and re-pointing it works
    ; (poke_mika2.py). The first 60 bytes are copied, so the column keeps its voice-id list
    ; at +60 and the animator still flaps its mouth. act becomes 1, so the band close slides
    ; and clears it like any shown column - and the next frame's face_left only moves it.
    ; r2 = the hidden column; returns r0 = 1 if it was dressed. Clobbers r0-r8 (not r9).
    mov.l   =facecue, r1                ; the cue (see face_left)
    mov.l   @r1, r1
    tst     r1, r1
    bt      dr_no
    mov.w   @(2, r1), r0                ; flag 2: +24 is the character, no face words
    extu.b  r0, r0                      ;   (the high byte is the character, since #68)
    cmp/eq  #2, r0
    bt      dr_no
    mov.l   @(24, r1), r6               ; its face: the structure buffer (0 = no face here)
    tst     r6, r6
    bt      dr_no
    mov.l   @(28, r1), r7               ; CMDSRCA base << 16 | palette byte
    mov.l   =0x{OBJ_BASE0:08X}, r4      ; the target column's base cel
    mov     r2, r0
    tst     r0, r0
    bt      dr_tmpl
dr_mul:
    add     #114, r4
    add     #114, r4
    dt      r0
    bf      dr_mul
dr_tmpl:
    mov     #0, r5                      ; the template: any other column that is shown
    mov.l   =0x{OBJ_BASE0:08X}, r3
dr_t:
    mov     r5, r0
    cmp/eq  r2, r0
    bt      dr_next
    mov.b   @r3, r0
    extu.b  r0, r0
    cmp/eq  #1, r0
    bt      dr_have
dr_next:
    add     #114, r3
    add     #114, r3
    add     #1, r5
    mov     r5, r0
    cmp/eq  #3, r0
    bf      dr_t
dr_no:
    rts
    mov     #0, r0
dr_have:
    mov     #0, r8                      ; cel 0 base, 1 eyes, 2 mouth
dr_cel:
    mov     r3, r5
    mov     r4, r1
    mov     #15, r2                     ; 60 bytes: the object without its voice-id list
dr_cp:
    mov.l   @r5+, r0
    mov.l   r0, @r1
    add     #4, r1
    dt      r2
    bf      dr_cp
    mov     r6, r1                      ; +20 = [buffer + 0x10 + 4*cel]: the cel's sequence
    add     #16, r1
    mov     r8, r0
    shll2   r0
    add     r0, r1
    mov.l   @r1, r0
    mov.l   r0, @(20, r4)
    mov     #0, r0                      ; +24 = [buffer + 0x20] on the base cel, 0 on the others
    tst     r8, r8
    bf      dr_l24
    mov     r6, r1
    add     #32, r1
    mov.l   @r1, r0
dr_l24:
    mov.l   r0, @(24, r4)
    mov.l   r6, @(32, r4)               ; +32 the structure buffer
    mov     r4, r1
    add     #4, r1
    mov     r7, r0
    mov.b   r0, @r1                     ; +4 the palette byte
    add     #4, r1
    mov     #{FACE_X}, r0
    mov.w   r0, @r1                     ; +8 x (y stays the template's: the band's open y)
    add     #20, r1
    mov     r7, r0
    shlr16  r0
    mov.w   r0, @r1                     ; +28 CMDSRCA base = the VDP1 face slot
    add     #76, r3
    add     #76, r4
    add     #1, r8
    mov     r8, r0
    cmp/eq  #3, r0
    bf      dr_cel
    rts
    mov     #1, r0
clear_band:
    sts.l   pr, @-r15
    mov.l   =bplain, r1
    mov.l   @r1, r1
    tst     r1, r1
    bt      cb_face
    mov.l   =0x{CELLS:08X}, r1          ; a plain-in-band card used all 80 cells
    mov     #20, r3
    mov     #4, r4
    bra     cb_go
    nop
cb_face:
    mov.l   =0x{BAND_CELL0:08X}, r1
    mov     #{COLS}, r3
    mov     #{ROWS}, r4
cb_go:
    bsr     clear_cells
    nop
    lds.l   @r15+, pr
    rts
    nop
clear_cells:
    ; r1 = first cell, r3 = cells per row, r4 = rows; the cell array is only 2-aligned
    ; (0x060F28AA): halfword stores, never mov.l. Blank cells carry colour 7 like the
    ; engine's (0 paints the highlight blue). Clobbers r0, r2, r5, r7.
    mov.l   =0x{BLANK:08X}, r2
    mov.l   =0x00000700, r0
cc_row:
    mov     r3, r7
    mov     r1, r5
cc_cell:
    mov.w   r2, @r5
    add     #2, r5
    mov.w   r0, @r5
    add     #2, r5
    dt      r7
    bf      cc_cell
    add     #80, r1
    dt      r4
    bf      cc_row
    rts
    nop
    ; ---- data: the header ends at +0x20 = the entry, so nothing lives there ----
    .align  4
cellcodes:
    .long   0                           ; the plain card's codes at (0,0) << 16 | (1,0)
job:
    .long   0, 0                        ; the frame pick's job {{layer, picture, 1, 0}}, queued by pointer
menuhold:
    .long   0                           ; 1 once a parked box under a set menu-live byte was seen (see try_plain)
facecue:
    .long   0                           ; the cue face_left/dress lay the band out for (the card up, or the live line's while the band slides)
flmiss:
    .long   0                           ; face_left's misses running (no column carries the voice id); FL_MISSES -> native layout
qhold:
    .long   0                           ; frames the band card has waited for its speaker's column (show_band); QHOLD_MAX -> shown anyway
rlast:
    .long   0                           ; the reel position seen last frame
rsame:
    .long   0                           ; frames it has not moved; REEL_PARK -> no reel
curlist:
    .long   0                           ; the band list object 0 shows for our card: the 42-cell one (build_blob's initial value) or the 80-cell one
linger:
    .long   0
hcue:
    .long   0, 0                        ; the minimum hold: the card it counts for, frames since it went up
holdtab:
    .long   0                           ; one byte per cue: the frames it stays up at least (build_blob, hold_frames)
bplain:
    .long   0                           ; 1 while the card up is plain-in-band (nameplate + rows, every column parked)
sigtab:
    .long   0                           ; the face signature table after the cues (build_blob): u16 character, u16 0, 16 bytes per record, 0 ends
pcols:
    .long   {COLS}                      ; plain_write's cells per row (build_blob: the cue file's plain cols, INTRO 20)
ptext0:
    .long   0x{CELLS:08X}               ; plain_write's first text cell with no nameplate (INTRO: row 1)
plinger:
    .long   {LINGER}                    ; frames the open plain box waits for the next line (INTRO longer)
pcuey:
    .long   0                           ; 1: a plain card's box y is its cue's +28 word (INTRO), else 0
pslide:
    .long   8                           ; the plain box's slide step (INTRO: 128 - it appears and goes in one frame)
oprio:
    .long   0                           ; object 0's priority while a plain card is up (0 = the engine's; INTRO 31)
oprio_save:
    .long   0                           ; the byte it replaced (must follow oprio)
.pool
exhx:
    .word   0, 0, 0                     ; extras: the three columns' x at the entry (unhide)
natx:
    .word   {FACE_X}, {FACE_X + FACE_COL_PITCH}, {FACE_X + 2 * FACE_COL_PITCH}   ; ... and their native x (must follow exhx)
exown:
    .space  {EX_LAST - 9}                  ; extras: per object 10..EX_LAST, its column + 1 (0 = none)
"""


def shown_x(x):
    """A cel's or sprite's x as the layout meant it: `extras` hides a column under its own
    replacement sprite (and a stray band sprite under a card) for the frame at x + HIDE_DX -
    the harnesses read the RAM after the payload, so such a column still counts where it was."""
    x = x - 0x10000 if x >= 0x8000 else x
    return x - HIDE_DX if HIDE_DX <= x < 2 * HIDE_DX else x


def band_sprite_off(sx, sy, owner, cols):
    """A live object past the nine cels drawn where no face is (the harnesses' SPRITE-OFF-WINDOW):
    sx/sy its raw x/y, owner its `exown` byte (column + 1, 0 = none), cols the three base cels
    as (act, raw x, y). Hidden (x + HIDE_DX) or away (>= FACE_AWAY) is fine; an owned sprite must
    sit within 48 of its column's x; a sprite nobody owns must not stand on the band row (y 160)
    in the text area (x 90..399) - `extras` hides those under a band card."""
    sx = sx - 0x10000 if sx >= 0x8000 else sx
    if HIDE_DX <= sx < 2 * HIDE_DX or sx >= FACE_AWAY:
        return False
    if owner and owner <= 3:
        act, cx, cy = cols[owner - 1]
        return act == 1 and abs(sx - shown_x(cx)) >= 48
    return sy == 160 and 90 <= sx < FACE_AWAY


WIDE_COLS = 20                      # no portrait (plain-in-band, the plain box): the box's whole row


def wide_cells(row):
    """Cells a row takes, the pair font's way: ASCII runs in pairs (an odd run padded),
    anything else one cell (satglyphs.pairs_of)."""
    n, run = 0, 0
    for ch in row + "\0":
        if ch != "\0" and ord(ch) < 0x80:
            run += 1
        else:
            n += (run + 1) // 2 + (ch != "\0")
            run = 0
    return n


def wide_rows(c):
    """The card re-wrapped at the box's full 20 cells, for the layouts with no portrait
    (Luiz, 2026-09-30: "we are always limiting the number of characters per line even
    when no portrait is being shown"); None when it comes out the same as the band
    rows or does not fit their row count. Greedy on the band rows' words, so a hand
    split inside `rows` still decides the text."""
    rows = c.get("rows") or []
    words = " ".join(rows).split()
    out, cur = [], ""
    for w in words:
        cand = (cur + " " + w) if cur else w
        if wide_cells(cand) <= WIDE_COLS:
            cur = cand
        else:
            if cur:
                out.append(cur)
            cur = w
            if wide_cells(cur) > WIDE_COLS:
                return None
    if cur:
        out.append(cur)
    if not out or out == rows or len(out) > len(rows):
        return None
    return out


def encode_text(pf, rows, name=None, colour=7, cols=COLS, nrows=ROWS):
    """Card rows -> the SJIS cell codes (u16 BE), 0x818F between rows, 0 at the end.
    With `name`: the nameplate first, in `colour` (a 0x810c code before it, 0x8107
    = white back after), then a row break and the rows."""
    out = bytearray()
    if name:
        out += struct.pack(">H", COLOUR_CODE | colour)
        codes = pf.encode(name)
        for i in range(0, len(codes), 2):
            out += struct.pack(">H", satfont.code_to_sjis((codes[i] << 8) | codes[i + 1]))
        out += struct.pack(">HH", COLOUR_CODE | 7, ROWBREAK)
    codes = pf.encode("￥".join(rows))
    for i in range(0, len(codes), 2):
        out += struct.pack(">H", satfont.code_to_sjis((codes[i] << 8) | codes[i + 1]))
    assert all(len(pf.encode(r)) // 2 <= cols for r in rows), (rows, cols)
    assert len(rows) + (1 if name else 0) <= nrows, (rows, name)
    return bytes(out) + b"\0\0"


def face_words(face):
    """A cue's `face` [slot, buffer index, palette byte] -> (structure buffer address,
    CMDSRCA base << 16 | palette). Both tables are exec constants (`check_face_tables`)."""
    if not face:
        return 0, 0
    slot, bufi, pal = face
    return FACE_BUFS[bufi], ((FACE_SLOTS[slot] - 0x25C00000) >> 3 << 16) | (pal & 0xFF)


def check_face_tables(exe):
    """The two tables the room script's op 0x21 reads are where FACE_SLOTS/FACE_BUFS say."""
    for addr, want in ((SLOT_TAB, FACE_SLOTS), (BUF_TAB, FACE_BUFS)):
        got = list(struct.unpack_from(">9I", exe, addr - MAIN_BASE))
        assert got == want, f"face table {addr:#x}: {[hex(g) for g in got]}"


def pairs_used():
    """Every letter pair the subtitle cards draw (satglyphs' ranking hook,
    2026-09-16): until then the cues were not in the slot ranking, and
    Randam's spelled name in B130 (`H-A-J-I-L-E`: the pairs `J-`, `L-`) fell
    back to fullwidth letters with a `?` for the hyphen (no fullwidth
    hyphen in the codec) - Luiz's MiSTer report."""
    import glob
    import satglyphs
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "saturn", "translation", "subs_*.json"))):
        spec = json.load(open(path, encoding="utf-8"))
        for c in spec["cues"]:
            if not c.get("enabled", True):
                continue
            for r in c.get("rows", []) + (wide_rows(c) or []):
                out += satglyphs.pairs_of(r)
    return out


def build_blob(spec, exe, BLOB):
    """The blob bytes for a bank whose blob will load at `BLOB`, and a report."""
    scene = spec["scene"]
    chunk, scene_no = SCENES[scene]
    check_face_tables(exe)
    pf = SatPairFont(json.load(open(SAT_TABLE)))
    cues = [c for c in spec["cues"] if c.get("enabled", True)]
    a = Asm(BLOB + 0x20)
    code = a.assemble(payload_asm(BLOB))
    # layout: header 0x20 | code | cues | texts | list buffer
    off = 0x20 + len(code)
    off = (off + 3) & ~3
    cues_addr = BLOB + off
    off += CUE_SIZE * len(cues)
    import facechunks
    sig_rows = facechunks.sig_table()
    facechunks.check(sig_rows)
    sigs = facechunks.pack(sig_rows)                     # after the cues: {u16 character, u16 0, 16 B}, 0 ends
    sig_addr = BLOB + off
    off += len(sigs)
    hold_addr = BLOB + off                               # one byte per cue: hold_frames
    off += (len(cues) + 3) & ~3
    texts, interned = bytearray(), {}

    def intern(t):
        nonlocal texts
        if t not in interned:
            interned[t] = off + len(texts)
            texts += t
            if len(texts) % 4:
                texts += b"\0" * (4 - len(texts) % 4)
        return interned[t]

    opts = spec.get("options", {})
    pcols = opts.get("cols", COLS) if opts.get("layout") == "plain" else COLS
    ptext0 = CELLS + 80 * opts.get("row0", 0) if opts.get("layout") == "plain" else CELLS

    def two(c):
        band = encode_text(pf, c["rows"], cols=pcols, nrows=ROWS + (opts.get("row0", 0) == 0 and opts.get("layout") == "plain"))
        # the plain box and plain-in-band draw the text re-wrapped at 20 cells: it follows the
        # band text's end word (an empty text = the band rows again; the opening has none).
        # The pair interned is band + wide, so the face layout reads the band text alone.
        wide = wide_rows(c) if opts.get("layout") != "plain" else None
        band += encode_text(pf, wide, cols=WIDE_COLS, nrows=ROWS) if wide else b"\0\0"
        name = encode_text(pf, [], c.get("speaker") or None, c.get("colour", 7), 20, 1) if c.get("speaker") else None
        return band, name
    for c in cues:
        for t in two(c):
            if t is not None:
                intern(t)
    text_base = off
    off += len(texts)
    off = (off + 3) & ~3
    list_addr = BLOB + off
    band = exe[BAND_LIST - MAIN_BASE + 8:BAND_LIST - MAIN_BASE + 8 + 6 * 12]
    listbuf = struct.pack(">H6x", NREC + 6) + bytes(12 * NREC) + band
    assert len(listbuf) == BP_OFF
    listbuf += struct.pack(">H6x", NREC_PLAIN + 6) + bytes(12 * NREC_PLAIN) + band    # plain-in-band: all 80 cells + the band pieces
    off += len(listbuf)
    plain_addr = BLOB + off
    pieces = exe[PIECES - MAIN_BASE:PIECES - MAIN_BASE + 8 * 12]
    # the opening (`frame: false`): the 80 cells only - no gold box pieces, the box frame's VDP2 fill
    # alone behind the rows, as the PS1's dark band (the count word; the pieces stay in the buffer)
    npieces = 8 if opts.get("frame", True) else 0
    plainbuf = struct.pack(">H6x", NREC_PLAIN + npieces) + bytes(12 * NREC_PLAIN) + pieces
    off += len(plainbuf)
    assert BLOB + off <= WINDOW_END, f"{scene}: the blob ends at {BLOB + off:#x}, past the bank window {WINDOW_END:#x}"
    blob = bytearray(off)
    struct.pack_into(">IHHIIIII", blob, 0, MAGIC, scene_no, len(cues), cues_addr, list_addr, 0, plain_addr, 0)
    blob[0x20:0x20 + len(code)] = code
    struct.pack_into(">I", blob, a.labels["curlist"] - BLOB, list_addr)      # the 42-cell list until a card says otherwise
    struct.pack_into(">I", blob, a.labels["sigtab"] - BLOB, sig_addr)
    struct.pack_into(">I", blob, a.labels["pcols"] - BLOB, pcols)
    struct.pack_into(">I", blob, a.labels["ptext0"] - BLOB, ptext0)
    struct.pack_into(">I", blob, a.labels["plinger"] - BLOB, opts.get("linger", LINGER))
    struct.pack_into(">I", blob, a.labels["oprio"] - BLOB, opts.get("prio", 0))
    struct.pack_into(">I", blob, a.labels["pslide"] - BLOB, opts.get("slide", 8))
    struct.pack_into(">I", blob, a.labels["pcuey"] - BLOB, 1 if opts.get("cue_y") else 0)
    blob[sig_addr - BLOB:sig_addr - BLOB + len(sigs)] = sigs
    struct.pack_into(">I", blob, a.labels["holdtab"] - BLOB, hold_addr)
    blob[hold_addr - BLOB:hold_addr - BLOB + len(cues)] = bytes(hold_frames(c["en"]) for c in cues)
    o = cues_addr - BLOB
    for c in cues:
        tb, tp = two(c)
        if "reel" in c:
            sector, key = REEL_TAG, c["reel"]
        else:
            sector, key = c["sector"], (c["offset"] << 16) | (c["act"] << 8)
        char = 0
        if "reel" in c and c.get("face_char"):
            # +2 = 1: a reel cue with a known character lays the band out by content - the
            # column whose slot carries one of the character's portraits (reel_col) in the
            # window, the rest away, every column away when none does (plain-in-band);
            # +24 = the character id. 0: no character known (narration, 'TV', 'Voice') -
            # the window's column stays, the others park (fl_keep0)
            flag, fbuf, fsrca = 1, c["face_char"], 0
            char = c["face_char"]
        elif "reel" not in c and not c.get("face") and facechunks.CHARS.get(c.get("speaker")):
            # +2 = 2: a mono cue of a known character with no face words - the mouth
            # list's column is checked against the character by content (fl_verify)
            flag, fbuf, fsrca = 2, facechunks.CHARS[c["speaker"]], 0
            char = facechunks.CHARS[c["speaker"]]
        else:
            flag, (fbuf, fsrca) = 0, face_words(c.get("face"))
            if "reel" not in c:
                # a mono cue WITH face words: the character rides in the flag word's high
                # byte so the mouth list's column is checked by content all the same (#68:
                # the ending's script shows Gillian for four of Madnar's lines and Madnar
                # for one of Gillian's, own op 0x21 words and all); +24/+28 stay the face
                char = facechunks.CHARS.get(c.get("speaker"), 0)
        # the flag word: low byte the flag, high byte the character (cue_char / reel_col)
        flag |= char << 8
        if opts.get("cue_y"):
            # the opening: no face words on a narration cue; +28 carries the box y (ytarget)
            assert not fbuf and not fsrca and not flag, c["id"]
            fsrca = c["y"]
        struct.pack_into(">HHIIIIIII", blob, o, sector, flag, key, c["b0"], c["b1"],
                         BLOB + interned[tb], BLOB + interned[tp] if tp is not None else 0, fbuf, fsrca)
        o += CUE_SIZE
    blob[text_base:text_base + len(texts)] = texts
    blob[list_addr - BLOB:list_addr - BLOB + len(listbuf)] = listbuf
    blob[plain_addr - BLOB:plain_addr - BLOB + len(plainbuf)] = plainbuf
    rep = dict(scene=scene, chunk=chunk, code=len(code), cues=len(cues), texts=len(texts),
               faces=sum(1 for c in cues if c.get("face") or c.get("face_char")), sigs=len(sig_rows),
               interned=len(interned), total=len(blob), list_addr=list_addr, plain_addr=plain_addr, cues_addr=cues_addr)
    return bytes(blob), rep


def lenvar_addr(led):
    """satlong's `lenvar` word: its stub program assembled at the ledger's satlong allocation."""
    import satlong, sh2asm
    mine = next(a for a in led["allocations"] if a["who"] == "satlong")
    helper = next(a for a in led["allocations"] if a["who"].startswith("satlong-buffer "))
    _helper_code, helper_labels = sh2asm.asm(satlong.buffer_program(), helper["start"])
    _code, labels = sh2asm.asm(satlong.stub_program(helper["start"], helper_labels["buffer"]), mine["start"])
    return labels["lenvar"]


def inject_blob(mem, scene, log=print):
    """The current build's blob into a resumed savestate's bank (the PS1's raminject): a
    bookmark keeps the blob it was made with, so a payload change would go untested on
    every resumed run. The blob goes to its (unchanged) offset behind the strings, then
    the footer and satlong's tail, and satlong's `lenvar` takes the new region length so
    the renderer stub finds it. Proven 2026-09-16 on a previous build's B010 bookmark
    (the 'SH-2 cache' wedge of the day before was the pool-literal bug). Returns the
    blob address, or None when the scene has no blob in the layout file."""
    lay = json.load(open(LAYOUT_JSON, encoding="utf-8"))
    ent = lay["scenes"].get(scene)
    if not ent:
        return None
    blob = open(os.path.join(BUILD, f"subs_{scene}.blob"), "rb").read()
    BLOB = ent["blob"]
    import satexec
    led = json.load(open(satexec.LEDGER, encoding="utf-8"))     # as written: satpack's table rewrite changes the exec's hash
    lenvar = lenvar_addr(led)
    L = mem.u32(lenvar)
    tail = mem.read(STR_BASE + L - 4, 4) if L >= 4 and mem.u16(STR_BASE + L - 4) == 0xFFFF else b""
    off = BLOB - STR_BASE
    body = blob + bytes(-len(blob) % 4) + struct.pack(">II", FOOT_MAGIC, off) + tail
    assert STR_BASE + off + len(body) <= WINDOW_END, "the new region runs past the bank window"
    mem.write(BLOB, body)
    mem.write(lenvar, struct.pack(">I", off + len(body)))
    log(f"blob for {scene} injected at {BLOB:#x} ({len(blob)} B): region {L} -> {off + len(body)} B, tail {'kept' if tail else 'none'}")
    return BLOB


def patch_exec(exe):
    """The stub into the exec hole (satexec's ledger, after satnames/satlong) and the
    renderer pool word onto it. Returns (exe, stub address, stub bytes, ledger, blobptr).
    A second run on the same exec finds the pool word already on the stub and leaves it."""
    import satexec
    exe = bytearray(exe)
    po = HOOK_POOL - MAIN_BASE
    have = struct.unpack_from(">I", exe, po)[0]
    led = satexec.load_ledger(bytes(exe))
    lenvar = lenvar_addr(led)
    if have != RENDER:
        mine = next((a for a in led["allocations"] if a["who"] == "satsubs" and a["start"] == have), None)
        assert mine, f"the renderer pool word already reads {have:#x} and it is not our stub"
        asm = Asm(have)
        asm.assemble(stub_asm(lenvar))
        blobptr = asm.labels["blobptr"]
        return bytes(exe), have, exe[have - MAIN_BASE:mine["end"] - MAIN_BASE], led, blobptr
    probe = Asm(satexec.HOLE_LO).assemble(stub_asm(lenvar))
    addr = satexec.alloc(led, exe, "satsubs", len(probe), align=4)
    asm = Asm(addr)
    stub = asm.assemble(stub_asm(lenvar))
    blobptr = asm.labels["blobptr"]
    assert len(stub) == len(probe) <= STUB_ROOM
    exe[addr - MAIN_BASE:addr - MAIN_BASE + len(stub)] = stub
    struct.pack_into(">I", exe, po, addr)
    FACE_STUB_ASM = FACE_STUB_TPL.replace("{BLOBPTR:08X}", f"{blobptr:08X}").replace("{VOICE_ID:08X}", f"{VOICE_ID:08X}")
    # op 0x21's x: the pool word of the call after the write -> FACE_STUB_ASM (see there)
    fpo = FACE_POOL - MAIN_BASE
    fhave = struct.unpack_from(">I", exe, fpo)[0]
    assert fhave == FACE_TARGET, f"op 0x21's pool word {FACE_POOL:#x} reads {fhave:#x}, not {FACE_TARGET:#x}"
    fprobe = Asm(satexec.HOLE_LO).assemble(FACE_STUB_ASM)
    faddr = satexec.alloc(led, exe, "satsubs_face", len(fprobe), align=4)
    fstub = Asm(faddr).assemble(FACE_STUB_ASM)
    assert len(fstub) == len(fprobe)
    exe[faddr - MAIN_BASE:faddr - MAIN_BASE + len(fstub)] = fstub
    struct.pack_into(">I", exe, fpo, faddr)
    print(f"exec: op 0x21 face stub {len(fstub)} B at {faddr:#x}, pool word {FACE_POOL:#x} -> stub; "
          f"blobptr {blobptr:#x}, lenvar {lenvar:#x}")
    return bytes(exe), addr, stub, led, blobptr   # the caller saves the ledger once the exec is on disk


def bank_parts(data, ents, chunk):
    """(bank bytes, code_len, strings without any earlier blob/footer, marker, trailer)."""
    base, size = ents[chunk]
    bank = bytes(data[base:base + size])
    code_len, str_len = struct.unpack_from(">HH", bank, 0)
    strings = bank[4 + code_len:4 + code_len + str_len]
    trailer = bank[4 + code_len + str_len:]
    marker = b""
    if len(strings) >= 4 and strings[-4:-2] == bytes([0xFF, 0xFF]):
        strings, marker = strings[:-4], strings[-4:]
    if len(strings) >= 8 and struct.unpack_from(">I", strings, len(strings) - 8)[0] == FOOT_MAGIC:
        off = struct.unpack_from(">I", strings, len(strings) - 4)[0]       # a blob from an earlier run: dropped
        strings = strings[:off].rstrip(b"\0")
    return bank, code_len, strings, marker, trailer


def blob_addr(data, ents, chunk):
    """Where this bank's blob will load: 4-aligned, right after its strings (and longs)."""
    _bank, _cl, strings, _m, _t = bank_parts(data, ents, chunk)
    return STR_BASE + ((len(strings) + 3) & ~3)


def grow_bank(data, ents, chunk, blob):
    """The bank chunk with the blob at the END of its string region, appended to
    DATA.BIN; returns (data, (sector, size), sizes).

    Region: strings (+ satlong's longs and group) | pad to 4 | blob | pad to 4 |
    footer {'SUBF', blob offset} | satlong's tail {0xFFFF, group offset} (its LOOKUP
    reads the region's LAST four bytes, so it stays last). The renderer stub finds
    the blob through the footer at L-12 (L-8 with no tail), L = the region length
    the loader stub records (satlong's `lenvar`)."""
    bank, code_len, strings, marker, trailer = bank_parts(data, ents, chunk)
    pos = (len(strings) + 3) & ~3
    assert STR_BASE + pos == blob_addr(data, ents, chunk)
    footer = struct.pack(">II", FOOT_MAGIC, pos)
    import satlong
    body = strings + bytes(pos - len(strings)) + blob + bytes(-len(blob) % 4)
    body += bytes(satlong.region_pad(code_len, len(body) + len(footer) + len(marker)))   # the marker block behind
    new_str = body + footer + marker                                                    # the u32 stays in one sector
    assert len(new_str) < WINDOW_END - STR_BASE, f"bank {chunk}: region + blob = {len(new_str)} bytes, past the 64 KB window"
    new = struct.pack(">HH", code_len, len(new_str)) + bank[4:4 + code_len] + new_str + trailer
    if len(new) % 2:
        new += bytes(1)
    data = bytearray(data)
    assert len(data) % SECTOR == 0
    sector = len(data) // SECTOR
    data += new + bytes(-len(new) % SECTOR)
    return bytes(data), (sector, len(new)), (code_len, len(strings), len(new_str), len(new), bool(marker))


def main(argv):
    scenes = [a for a in argv if not a.startswith("--")] or ["B010"]
    if "--all" in argv:
        import gen_subs
        scenes = gen_subs.SUBTITLED + ["INTRO"]          # the opening's cues ride in B000 (gen_intro.py)
    data = open(DATA_OUT, "rb").read()
    exe = open(MAIN_OUT, "rb").read()
    # 639 entries (satdata.read_table stops at the relocated chunk 0)
    ents = [(sec * SECTOR, words * 2) for sec, words in
            (struct.unpack_from(">HH", exe, satdata.TABLE_OFF + 4 * i) for i in range(639))]
    exe, stub_addr, stub, led, blobptr = patch_exec(exe)
    print(f"exec: stub {len(stub)} B at {stub_addr:#x} (exec hole, ledger), pool word {HOOK_POOL:#x} -> stub")
    appended = 0
    layout = {"blobptr": blobptr, "scenes": {}}
    for sc in scenes:
        spec = json.load(open(os.path.join(ROOT, "saturn", "translation", f"subs_{sc}.json"), encoding="utf-8"))
        addr = blob_addr(data, ents, SCENES[sc][0])
        blob, rep = build_blob(spec, exe, addr)
        bank = "B%03X" % (SCENES[sc][1] * 0x10)            # the harness keys on the loaded bank: INTRO -> B000
        layout["scenes"][bank] = {"blob": addr, "size": len(blob), "cues": rep["cues"], "cue_file": sc}
        chunk = rep["chunk"]
        data, (sector, size), (cl, sl, nsl, total, marker) = grow_bank(data, ents, chunk, blob)
        exe = bytearray(exe)
        struct.pack_into(">HH", exe, satdata.TABLE_OFF + 4 * chunk, sector, size // 2)
        exe = bytes(exe)
        nsec = (total + SECTOR - 1) // SECTOR
        appended += nsec
        print(f"{sc}: blob {rep['total']} B at {addr:#x} (code {rep['code']}, {rep['cues']} cues, {rep['faces']} with a face, {rep['texts']} B text in "
              f"{rep['interned']} strings, lists at {rep['list_addr']:#x}/{rep['plain_addr']:#x}); bank chunk {chunk}: strings {sl} -> {nsl} B"
              f"{' (satlong tail kept last)' if marker else ''}, file {total} B, appended at DATA.BIN sector {sector} ({nsec} sectors)")
        os.makedirs(BUILD, exist_ok=True)
        open(os.path.join(BUILD, f"subs_{bank}.blob"), "wb").write(blob)
    open(DATA_OUT, "wb").write(data)
    open(MAIN_OUT, "wb").write(exe)
    json.dump(layout, open(LAYOUT_JSON, "w", encoding="utf-8"), indent=1)
    import satexec
    satexec.save_ledger(led, exe)
    print(f"wrote {DATA_OUT} ({len(data)} B, {appended} sectors appended) and {MAIN_OUT}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1:])
