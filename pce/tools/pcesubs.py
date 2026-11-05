"""Subtitles for the voiced lines that show no text: a table per module,
the stub and a face block in the resident file, one hook in stage 2.

A voice line is queued as `0d NN` (module bytecode `1c f3 NN GG`): the
opcode asks for record NN of the act's ADPCM table ($26F3 = NN) and holds
until AD_STAT reads playing; the ADPCM service the main loop runs every
frame ($6220 in the text bank: AD_STAT into $26F2, then the pending
transfer at $6156 and the play a tick later at $61E3) does the work, and
the `0a` after it holds until the chip reads stopped. Nothing is drawn: in
these scenes the text window is hidden ($39BF = 8, set by the voice
opcode).

**The hook** replaces the vblank handler's `JSR $6021` at bank 0 $4262
(file 0x0262; the CD service after the ADPCM one) with `JSR tstat` in
bank 0's gap at $5BB4: the service, then - with the resident file rec
110's first bank at MPR5 and the stub's signature (`SB3`) in it - the
stub, every pass (it reads AD_STAT itself: the trampoline's 76 bytes
have no room for the call since it tries a third place). The handler is
the game's frame engine (picture decoding, the object walker, the text
renderer all run in it) and a pass can span frames, so the hook sees the
END of each pass; a request in $26F3 is gone by then and a streamed line
(ch 3, over 32 sectors) plays before the service's own copy, so a line is
detected as AD_STAT rising from stopped, its NN from the record pointer
$5E/$5F ($8000 + (NN - 1) * 8; $8800 on are the effects').

**The stub** (SOURCE, in rec 110's free tail after the face block - a
module carries only its table, which may run to the halfwidth font at
TABLE_END; the ending, 670, runs without rec 110 and carries the same
stub itself at MODULE_STUB_OFF, which the trampoline tries second, with
the module's fourth bank at MPR4; third, bank $6C at MPR4, where the
opening's two blocks carry a stub of their own - pceopening.py, the
newsreel and Gillian's profile, CD-DA with no ADPCM line) finds the line in the loaded module's table (SUBS_PTR at
0x7FF7, behind the module's checksum at MAGIC - a shorter module leaves
the last one's tail in the window - so the stub sums the loaded module's
first 256 bytes first, through the game's FETCH), lays it out into the
renderer's buffer ($3610) and starts it the way the game's own message
opcode does ($3471 = the message, $3470 = 1: never through the $3C00
queue, which the interpreter we sit under would have to run), and shows
the window.

**The window** is the game's: BAT rows 43-50 at columns 32-63 (blank while
the game's window is closed, tiles 0x700-0x7FF when open), a text row
16 px (row << 2 on the address high byte: 0x400 words a row) - four rows.
A line uses the first two (the window's top; the other two left blank),
mapped by the stub itself to the TILES of the renderer's rows 0-1
(region 6, VRAM 0x7000) or rows 2-3 (region 7, 0x7800) - whichever no
live object draws from (`rowsel` over the face block's `used`: every
object's region, a picture piece's too, not only the band faces'), 6
first. The renderer's base $3F32 stays the game's 0x7000: the ending's
flashback keeps a value of its own there, and putting 0x7000 back at a
line's end sent its loader's block transfer into bank 1 - the code -
and hung the game (so no other region can hold the rows, whatever the
scene draws from 6 and 7). The game never shows text and portraits together, and a
face the text wrote over stays garbage until its scene reloads it (rows
0-1 under Gillian's region put her face to noise for the rest of the
Chief's room). With every region in use one is BORROWED (7, or 6 when
the speaker's face is in 7 or a band face - hidden for the line anyway
- is in 6 alone; the speaker's own is never touched): its face is kept
off the screen for the line and its bitmap PARKED - copied (vcopy, in
bank 1's tail, MARR streaming the source and MAWR the destination on
the data port, ~8 ms) into a free face region (4, then 5: the game's
faces use 4-7, three at most, so one is free whenever a borrow is
needed) and copied back when the rows leave the region; the parked
region counts as in use meanwhile, and its bitmap is the one matched
for the borrowed region's character, so the parked face speaks from
its own region (the rows move to the other one) when its turn comes.
Until 2026-09-14 the face was drawn AGAIN at the line's end from the
scene's own data (a logger on the display-list interpreter's record
handlers kept the last record drawn into each region and a redraw
replayed it): the record's block is gone whenever the face came from
an earlier scene - the HQ reception's Metal Gear, decoded outside, was
lost, unknown from then on, taken again and again, and its sprites
drew our rows (the "corrupted colours around the text" of dev7). (Parking
the bitmap in the BAT's unseen part was tried first: the window band
is taller in scenes with a shorter picture, and rows 40-52 showed the
parked tiles.) A face arriving mid-line into the region in use moves
the text (another region chosen, the BAT re-mapped, the page laid out
again) and is LEFT as it is (the parked copy is dropped when the
borrowed region's own bitmap reads as a known face by then: the game's
decode is the truth there); clearing would take the face.
Showing the window is $39BF = 0x56 with $39CF = 1 and the
zero-page $27 = 1 the game's own open routine sets (the raster sections
follow it; without it the reception scene showed nothing); $34B7 = FF as
the voice opcode leaves it. The renderer puts cell 0 a tile in (x 8) and
wraps at 20 cells. The rows' tiles are zeroed before every page. VDC
access is absolute (`a:` in asm6280: $0000-$0003 sit below the zero
page), the select register mirrored in $F7 as the game does; a VRAM read
sets MARR a word early and reads once first (the buffer lags). Every
long run of VDC writes (the rows' clear, the BAT map, the region copy)
runs with interrupts ON and the zero-page $30 set to 2: that is the
game's own guard - a nested vblank handler takes its short path while
$30 is set (no lists, no walker: the walker moves MAWR), which is how
its renderer survives its own long passes - and the raster sections
(BXR/BYR per band, chained from the RCR interrupt) keep their lines.
Until 2026-09-14 those runs were under SEI (a nested handler had moved
MAWR into a clear), the sections missed their lines for that frame and
the picture drew a third black with a tear at every cue start and page
- Luiz's "screen flickering when changing cues". The stub runs from the
handler's $1C part, after its STZ $30, so $30 is simply set and cleared.
The game's renderer draws a page over several frames (the handler pass
runs long; nested vblanks take its short path), so the window's contents
settle a few frames after a page starts.

**The faces** (the face-left layout, as the PS1's #23): the game shows up
to three portraits on the window, x 24-232, y 144-223, each THREE
objects (base, eyes, mouth - the mouth's frame animates while its
character talks) whose sprites draw a bitmap of 32 cells at VRAM 0x6000 +
region * 0x800 (patterns 0x300 + region * 0x40; region 3 would be 0x7800
= the text rows' tiles - not met yet). Objects live in the tables at
$2A40 (exists), $27C0/$2800 (x), $2880/$28C0 (y), $2DC0 (frame),
$2700/$2740 + $2EC0 (frames, bank), $2F00/$2F40 + $2F80 (sprite list,
bank); the walker (bank 1 $6000, from the handler at $4217 and from the
picture code that creates a face) rebuilds the whole sprite table
(VRAM 0x1000, 64 entries of [y, x, pattern, attributes]; the vblank's
transfer takes it) from them every pass. The face block therefore fixes
the SPRITE TABLE right after the walker built it (a hook on the
walker's exit, bank 1 $6072 `JMP $43BE`, WALKER_HOOK -> `whook` in the
tail -> `fsprite`): every pass draws our layout, nothing ever flashes at
the native columns, and the game's OBJECT tables are never touched -
its script reads them, and took other paths whenever they were: faces
moved off the screen (y -256, then x 320: dev5-7), the ruins' end
skipped its wait for the CD track under the Chief's speech and opened
the verb menu into our rows (dev7's "permanent corruption"); hidden
with the game's own object flag (bit 1 of $3000,X, an afternoon of
dev8), the act-2 recap never asked for its second track and Metal Gear
hidden through the verb menu's opening was no `Use Metal Gear` on it.
A face object is one whose current sprite group draws patterns
0x300-0x3FF (`ochase` follows the walker's own pointer chase - frame
entry, list pointer table, group, first sprite - mapping the object's
banks at MPR6), on the band (y from 0xA0) and not hidden by the game's
own flag (the act-2 Chief's room keeps Gillian's face ready, hidden,
through his lines). While a line is up only the SPEAKER's face stays:
its sprites (the entries drawing from its region, on the band - y from
0xC0 in the table's 64-offset: a face's top cells sit above its
object's y) move left with it. A first pass measures the visible sprite
cells; a second moves their left edge to FACE_X (32), right or left, so
every speaker's face sits in the same column (Gillian's native 24 and
Metal Gear's 32 made the portraits jump 8 pixels between speakers).
This avoids animation-anchor offsets. The sprites of every other face region (4-7, patterns
0x300-0x3FF; the picture's pieces sit lower and in regions 0-3) go off
(y 0), a face nobody is known for too; and the text runs from column 8
(12 cells) with no name. With no face of the
speaker's (none up, or one the table does not know) the text takes the
game's own dialogue row (column 1, 18 cells) with the name inline
(`Mika: ` in its colour, 2 yellow, 6 Gillian's green) and every face
goes off too (a face lifted into the picture sat on the text in scenes
with a taller band, and the rule is one portrait, the speaker's). A line
whose speaker has no face up yet waits GRACE frames for one before the
plain layout (the game brings the face in 4-5 frames after the voice
starts); the table is fixed during the grace too (every face off until
the speaker's is found - they showed at their native columns for those
frames). A face is known by four words of its bitmap (offsets 0x88,
0xA8, 0xC8, 0xE8 of cells 0-7, the hair - never animated), listed per
character in pce/translation/faces.json, which `pce/harness/pcefaces.py`
fills from play (the region whose sprite patterns change most while a
line plays is the speaker's; `learn` merges a census); the signatures
themselves sit in the voice bank (sig_blob, OVERFLOW_RUNS), read at
MPR3. The table is fixed every pass while a line is up (its grace and
its linger too) and nothing is ever put back: the next pass draws the
game's own layout. (Until dev8 the face block moved the objects, with
a hook on the walker's ENTRY to place them before the table was built,
kept their native positions to put them back, and a `hold` that placed
them every pass between lines fought a slide the ending's flashback
waits on - a hang.) A borrowed region's bitmap comes back at the
release. The window stays too: a line's end unmaps its rows (blank) and
keeps the window for LINGER frames, putting it back every pass the
game's next voice opcode hides it (WIN and WIN_DIRTY - not LAYOUT, an
apply forced during the ending's scene change crashed the game), so the
next line of a conversation goes on in the same window instead of the
band blinking off and on between every two lines. All of that is the FACE
block: code and the names in the resident file rec 110's free tail
($6FC4-$7FFF of its first bank, mapped at MPR5 while the stub runs;
absent in the opening and the ending, which have no faces - the stub
checks its signature and does without).

A line is a run of word chunks `[cells | colour << 5][pair codes]`; the
stub word-wraps them into rows of the width in force, two rows a page,
and pages the line by time: the entry carries frames-per-cell (8.8 fixed
point, from the record's length: count sectors x FRAMES_PER_SECTOR) and
the page turns after its cells' share, counted on frames the chip reads
playing. A face arriving mid-line lays the page out again from its first
chunk. The first stopped after a playing gives the rows back and restores
the window as it was - unless the game's own window took over meanwhile
(a list up, LIST_COUNT, or a message, MSG_BUSY: the tricycle's
destinations open under Metal Gear's last line), when its rows, its
mapping and the shown window are left to it.

The module's table (in the module's window, or - OVERFLOW - in rec 54's
first bank behind the act's voice table): `[names offset u16]`, then entries `[NN][sector u16]
[len u16][fpc u16][char][chunks...]` with a 0 after the last - the sector
(the record's bytes 3-4) tells apart the same NN in two acts' tables (the
ending plays c8-d8 of acts 4 and 5; such keys are "c8.5" in the JSON) -,
then the names block
`[char][colour][cells][pairs]...` ending in 0 - only the speakers the
module has; the character codes are CHARS' 1-based positions (never
reorder it: faces.json and every table carry them). Costs: a chunk's
cells plus one when it switches colour (the `fe c` takes a pair's bytes
in the row); the name costs its cells plus one. A word wider than a row
beside a face is cut into pieces that fit. The tables are drafted by
pcematch.py from the PS1's cue files (pceasr.py transcribes the PCE's
lines first) and reviewed in play; a draft's `score` and `_unmatched`
fields are ignored here. Module 478 (B150) has no room for its table
(1,022 bytes free against 1,396): it goes to the voice bank (OVERFLOW,
OVERFLOW_RUNS - the runs free at runtime, the act's own table loading
over the bank's head every act), as do the face signatures, the ending's
cue block and the CD-DA clock's code.

**CD-DA cues** (pce/translation/cdda_<rec>.json, [{track, start, end
(seconds), speaker, en}], drafted by pcecdda.py from the PS1's cards):
eighteen audio tracks carry dialogue over music (the Act 2 recap, the
bike ride, the basement's snatcher, the Chief's death, the epilogue...)
that no ADPCM line names. A module's table carries them as a block of
its own at CUES_PTR (0x7FF3): `[magic u16][names offset u16]`, entries
`[track BCD][start u16][end u16][len u16][fpc u16][char][chunks]` in
frames from the track's start, 0, then the block's own names. The
clock (CD_SOURCE, in the voice bank's free run, mapped at MPR3 round the
call): $2638 rises the tick the CD service confirms a play and $263B is
the track (BCD, as the game keeps it); from then the frames are counted
by zero page $1B's steps (the vblank count: a handler pass can span
frames), and every fourth the entries are scanned for one whose span
holds the count - after the block's magic is read against the module's
MAGIC bytes (a scene load under the music replaces the table). The
verdict folds into AD_STAT's before the stub reads it: a cue counts as
a line playing, a change of cue or a real line reads stopped for a
frame first so the next line rises; `line` then takes the cue's entry
and the block's names, and the pass's end reads the folded verdict too
(the chip's own, pushed at entry, once left a cue unpaged and unended:
its stale page was re-laid from the names block at the next scene). The
module check is the table's own magic copy against MAGIC (every module
is padded to 16 sectors, so no stale tail is possible; the epilogue's
scene block over the front banks leaves the fourth bank - stub, pointers
- in place, and the ending's cues sit in the voice bank, CD_OVERFLOW). Two settings the tracks needed:
the epilogue (EPI_SOURCE, the module stub only) has no window section
and blacks palette 15 to hide the wallpaper tile, so the stub adds
sections of its own (slot 14: the picture's scroll from line 0, slot
15: the text rows from line 192, bx 0xF7) and draws in palette entries
the wallpaper does not use (EPI_COLOURS). The opening's tracks 17 and
19 (the newsreel, Gillian's profile) have a stub of their own in the
opening's blocks (pceopening.py): it draws its pages itself, since the
game's renderer held the opening's pictures back.

  python pce/tools/pcesubs.py apply     # the hook and the face block into patched/pce/snatcher_pce.bin
  python pce/tools/pcesubs.py show 318  # the wrapped pages of a module's lines
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

from asm6280 import assemble
import patch_pce as P
import pcescene as S
import pcepair

MAGIC = 0x7FF5               # module-relative: the module's checksum (magic()), then the table's u16 offset
SUBS_PTR = 0x7FF7
CUES_PTR = 0x7FF3            # module-relative: the CD-DA cue block's address (u16, 0 none) - in the fourth bank,
                             # which outlives the module's front banks under the ending's epilogue
TABLE_END = pcepair.FONT_OFF  # module-relative: the table may run to the halfwidth font
MODULE_STUB_OFF = 0x7000     # module-relative: leave 2.5 KB for the ending's stub, including planned page breaks
MODULE_STUB = 0x8000 + MODULE_STUB_OFF - 0x6000       # ... at $9000 with its fourth bank at MPR4
MODULE_STUB_END = 0x8000 + TABLE_END - 0x6000
MODULE_FACE_OFF = 0x6800     # module-relative: such a module's own face block, when there is room (the ending's table leaves none: its stub runs faceless unless rec 110 is in, which it was)
MODULE_FACE = 0x8000 + MODULE_FACE_OFF - 0x6000
MODULE_BANK3 = 0x19          # + [$3F80]: the module window's fourth bank
OPEN_BANK = 0x04             # + [$3F80]: $6C, where the opening's blocks carry their stub (pceopening)
NO_RESIDENT = {670}          # modules that run without rec 110 (the ending): the stub goes in the module
# A module whose window has no room for its table (478, the Mechanic room's chip scene: 1 KB
# free, a 1.4 KB table) keeps it in the voice bank instead (0x82: rec 54's first bank, loaded
# once; the act's own table - group 3, recs 86-106, three sectors - loads over its head at
# every act, so anything below 0x1800 there is gone by the first scene - the 0x1084 layout
# of 2026-09-13 lost 478's lines and the ending's cues to it). Two runs are free at runtime:
# 0x1800-0x1FFF, rec 54's own past the act tables' reach, and 0x940-0xFFF, 0xFF behind the
# effects' records in rec 54 AND in every act file - a block there is written into all
# seven. FETCH maps bank 0x16 + (ptr >> 13) at MPR6, so a module-relative pointer 0x9800
# reads bank 0x1A at 0x1800 - the stub needs no change.
OVERFLOW = [478]             # modules whose whole table goes to the voice bank (no room in the window)
CD_OVERFLOW = [670]          # modules whose CD-DA cues alone go there (the ending's 23 KB of lines fill it)
OVERFLOW_REC = (54, 24)
ACT_RECS = [(86, 3), (90, 3), (94, 3), (98, 3), (102, 3), (106, 3)]
OVERFLOW_RUNS = [(0x940, 0x1000, True), (0x1800, 0x1F30, False)]     # (start, end, in the act files too)
# 0x1F30-0x1FFF is NOT free: the game copies a 208-byte table there (the same bytes in the
# opening's scratch and after rec 54's load) - no layout reached it before the cards of
# 2026-10-15, whose keeper there hung the start of Act 1 (a black screen, the vblank running).
SIG_AT = 0x7E3A              # the face signatures: rec 54's 0xFF tail of its fourth bank (0x85,
SIG_END = 0x8000             # 0x1E3A-0x1FFF), untouched in every state of the 2026-10-15 runs
VOICE_BANK = 0x1A            # + [$3F80]: the voice bank, 0x82; the runs are read at MPR3 (VOICE_WIN) by the stub
VOICE_WIN = 0x6000           # and the face block, at MPR6 through FETCH by the module-relative pointers
TRAMP = 0x5BB4               # bank 0 (always mapped): the entry trampoline, file 0x1BB4 (the file table ends at $5BB2)
TRAMP_END = 0x5C00           # the runtime's own buffer from $5C00 on (a pointer at $25/$26)
FETCH = 0x5341
SIGNATURE = b"SB3"
HOOK = (0x0262, bytes([0x20, 0x21, 0x60]))      # the vblank handler's JSR $6021 (the CD service, after the ADPCM one), bank 0 $4262
WALKER_HOOK = (0x2072, bytes([0x4C, 0xBE, 0x43]))    # the object walker's exit (bank 1 $6072: JMP $43BE), after the sprite table is built
LOG_HOOKS = [(0x2F9E, bytes([0x20, 0x63, 0x47]), "logger"),      # the display-list interpreter's record handlers in bank 1, at
             (0x300B, bytes([0x20, 0x63, 0x47]), "logger48"),    # their `JSR $4763` before the decoder: $6F60 (other types),
             (0x3053, bytes([0x20, 0x63, 0x47]), "logger48")]    # $6FC8 (type 8) and $7019 (type 4): the face regions the game decodes into
WALKER_ENTRY = (0x2000, bytes([0x20, 0x6E, 0x47]))   # its entry, hooked until dev8 (inject110 puts the game's bytes back in old states)
TAIL = 0x7CD2                # bank 1's free tail (0xFF to $7FFF): the walker hook and the region copy
TAIL_OFF = 0x3CD2            # ... in the stage 2 file
TAIL_END = 0x8000
RECORD = 0x5E                # zero page: the voice record's address in its table, $8000 + (NN - 1) * 8
MSG = 0x3610                 # the message buffer the renderer reads (the module stub's: 94 bytes, $366E on is the game's)
MSG_RES = 0x3A66             # the resident stub's own: 4 rows x 12 cells need 121 ($3A65-$3AED never non-zero in 878 states, unreferenced)
WIN = 0x39BF                 # the text window: 0x56 shown, 8 hidden
WIN_DIRTY = 0x39CF
WIN_SHOWN = 0x56
ROWS = 2                     # text rows a page holds: the renderer's rows 0-1 (region 6's tiles at the game's
FIRST_REG = 6                # base 0x7000) or 2-3 (region 7's), shown at the window's first two rows; the region
MODULE_REG = 7               # with no face block (the module stub's: 7 - the ending's rows were tested on it)
COL_PLAIN, WIDTH_PLAIN = 1, 18          # x 20..235: the game's own dialogue rows (the renderer puts cell 0 a tile in)
COL_FACE, WIDTH_FACE = 8, 12            # x 104..247, beside the speaker's face at 24..87
WIDTH_FACE4 = 10                        # the resident's face rows (x 104..223): four of them in ONE face
                                        # region - the renderer reads its base per character, so each row
                                        # gets a base of its own and the rows pack into 128 tiles
ROW_TILES = {True: (0, 15, 64, 79), False: (0, 64)}   # each row's first tile in the region (face, plain);
                                        # its bottom half is 32 tiles on (the renderer's +0x200 words)
GRACE = 200                  # frames a portrait line waits for its face (the game brings it 0-190 frames
                             # after the voice starts; the rows never go up before it: the face decodes into them)
LINGER = 40                  # frames the window (rows cleared) and the faces stay after a line, for the next one
FACE_X = 32                  # visible portrait cells aligned with the subtitle window's left edge
TEXT_VRAM = 0x7000           # the text tiles ($3F32/33 - the game's to set, never written: the ending's
                             # flashback keeps its own value there and a write hung its loader), 0x400 words a row
WIN_BAT = 43 * 64 + 32       # the window's BAT: rows 43-50, columns 32-63
BLANK = 0xF110
CDDA_FPS = 59.826            # video frames a second: the CD-DA cues are timed in frames from the track's start
CDDA = os.path.join(ROOT, "pce", "translation", "cdda_{rec}.json")    # a module's CD-DA cues: [{track, start, end, speaker, en}]
FRAMES_PER_SECTOR = 14.8     # 2048 bytes x 2 nibbles at 16 kHz would be 15.36 at 60 Hz; the hook
                             # counted 164 playing frames for 11 sectors and 339 for 23
NAME_COLOUR = {"Gillian": 6}
TEXT_COLOUR = 1
EPILOGUE = {670}             # modules whose CD-DA cues draw under a scene block with palette 15 blacked (EPI_SOURCE) ...
EPI_COLOURS = {1: 3, 2: 5}   # ... in these entries instead: the wallpaper tile in the band uses 1, 2, 4, 8, 10
# the face block: rec 110's first bank ($7B = 0x13 + [$3F80]) at MPR5 while the stub runs
SYSTEM = (110, 12)
FACE_OFF = 0x0FC4            # file offset of the free tail (0xFF to 0x2000 of the first bank): the face block, then the stub
FACE_END = 0x2000
FACE = 0xA000 + FACE_OFF     # $AFC4 at MPR5
FACE_BANK = 0x13
FACE_SIG = b"FL1"
SIG_OFFS = (0x88, 0xA8, 0xC8, 0xE8)     # words of a face bitmap that name the character
FACES = os.path.join(ROOT, "pce", "translation", "faces.json")
CHARS = ["Gillian", "Mika", "Chief", "Harry", "Metal Gear", "Catherine", "Randam", "Jamie", "Madnar",
         "Chin", "Napoleon", "Ivan", "Lisa", "Freddy", "Gibson", "Alice", "Cunningham",
         "Teller", "Voice", "Cook", "Clerk", "TV", "Thug", "Waiter", "Master", "Woman",
         "Barker", "Parrot", "Announcer"]     # a byte each, 1-based: never reorder, append
PAGE_BREAKS = {               # cue-specific phrase boundaries where punctuation alone cannot choose one
    (334, "60"): "extending from",
    (574, "7d"): "back where",
    (590, "63"): "about Outer Heaven",
    (606, "b3"): "vanished into",
    (638, "3f"): "in an underground",
    (638, "71"): "in southwestern",
}

ROWVARS = "nrows:  .byte 2                  ; text rows a page holds (the resident's: 4 in regions 4/5 when both are free)\nrows2:  .byte 4                  ; ... x 2 = the BAT rows mapped\nnrw:    .byte 2                  ; rowsel's proposal\nrlen:   .byte 0                  ; a row's bytes in MSG\nfree:   .byte 0                  ; the free slots (bits 4, 5) rowsel hands out\nfree0:  .byte 0                  ; ... as computed\nlossc:  .byte 0                  ; passes the speaker's face has read unknown mid-line\ng30:    .byte 0                  ; $30 as the bank-1 thunks found it\nz90:    .byte 0                  ; $90-$92 and $F7 as the pass found them\nz91:    .byte 0\nz92:    .byte 0\nzf7:    .byte 0\ntmpa:   .byte 0\ntmpb:   .byte 0\nrreg:   .byte 0\npsp:    .byte 0xFF, 0xFF, 0xFF   ; the regions whose bitmaps are parked (the fallback's borrowed one; three slots)\nppk:    .byte 0xFF, 0xFF, 0xFF   ; ... and where (4 or 5), FF none\nnsp:    .byte 0xFF, 0xFF, 0xFF   ; rowsel's proposal of the same\nnpk:    .byte 0xFF, 0xFF, 0xFF\n"
def _rowtables():
    """Each row's tiles in the region and the renderer base that puts them there. The renderer
    draws cell c of row r at base + 16 * T(c) + 0x400 * r, T(c) = 1 + 3 * (c >> 1) + (c & 1)
    tiles (a 12-px cell, an odd one 4 px into its tile), its bottom half 0x200 words on, and
    each cell touches three tiles (read, OR, write: the third is blank); a row's base is the
    region's + 16 * (P - T(col0)) - 0x400 * r, so its first cell lands on tile P."""
    out = {}
    for face, col0, width in ((True, COL_FACE, WIDTH_FACE4), (False, COL_PLAIN, WIDTH_PLAIN)):
        t0 = 1 + 3 * (col0 >> 1) + (col0 & 1)
        ntiles = (4 * (col0 & 1) + 12 * width + 7) // 8
        last = col0 + width - 1
        touch = 1 + 3 * (last >> 1) + (last & 1) + 2 - t0          # the last tile touched, from the first
        used = set()
        bases = []
        for r, p in enumerate(ROW_TILES[face]):
            for half in (0, 32):
                span = range(p + half, p + half + ntiles)
                assert not used & set(span) and p + half + touch < 128, (face, r)
                used |= set(span)
            bases.append((16 * (p - t0) - 0x400 * r) & 0xFFFF)
        out[face] = (t0, ntiles, bases)
    return out


ROWTABLES = _rowtables()
ROWVARS += ("tlo:    .byte 0                  ; wbat: the row's first tile (low byte)\n"
            "thi:    .byte 0                  ; ... high byte with the palette\n"
            "t0v:    .byte 0                  ; ... the BAT column of its first tile\n"
            "wtv:    .byte 0                  ; ... its tiles a half row\n"
            "rpf:    .byte " + ", ".join(str(t) for t in ROW_TILES[True]) + "   ; each face row's first tile in the region\n"
            "rpp:    .byte " + ", ".join(str(t) for t in ROW_TILES[False]) + "   ; ... a plain row's\n"
            "rbf:    .byte " + ", ".join(f"{b & 0xFF}, {b >> 8}" for b in ROWTABLES[True][2]) + "   ; each face row's base, less the region's\n"
            "rbp:    .byte " + ", ".join(f"{b & 0xFF}, {b >> 8}" for b in ROWTABLES[False][2]) + "   ; ... a plain row's\n")
ROWBASE = """  LDA #0xF8              ; the row's own base: its tiles packed into the region (ROW_TILES)
  STA MSG,X
  INX
  LDA row
  ASL
  TAY
  LDA mode
  BEQ rbplain
  LDA rbf,Y
  STA MSG,X
  INX
  JSR regbase
  CLC
  ADC rbf+1,Y
  BRA rbset
rbplain:
  LDA rbp,Y
  STA MSG,X
  INX
  JSR regbase
  CLC
  ADC rbp+1,Y
rbset:
  STA MSG,X
  INX"""
WROW = f"""  LDA n                  ; ours: the BAT row's first tile (its text row's, + 32 for the bottom half)
  CMP #2
  BNE wrow1
  LDA cnt
  LSR
  CMP nrows
  BCS wrow1              ; (past the page's rows: blank)
  TAY
  LDA mode
  BNE wrf
  LDA #{ROWTABLES[False][0]}
  STA t0v
  LDA #{ROWTABLES[False][1]}
  STA wtv
  LDA rpp,Y
  BRA wrp
wrf:
  LDA #{ROWTABLES[True][0]}
  STA t0v
  LDA #{ROWTABLES[True][1]}
  STA wtv
  LDA rpf,Y
wrp:
  STA tlo
  LDA cnt
  AND #1
  BEQ wrp1
  LDA #32
  CLC
  ADC tlo
  STA tlo
wrp1:
  LDA treg               ; tile 0x400 + treg * 0x80 + that, palette 15
  LSR
  BCC wrp2
  LDA tlo
  ORA #0x80
  STA tlo
  LDA treg
  LSR
wrp2:
  CLC
  ADC #0xF4
  STA thi
wrow1:"""
WOURS_RES = """  LDA cnt                ; ours: the text row's tiles from its first, the rest blank
  CMP rows2
  BCS wblank
  LDA hdr
  AND #31
  SEC
  SBC t0v
  CMP wtv
  BCS wblank
  CLC
  ADC tlo
  STA a:VDC_LO
  LDA thi
  ADC #0
  STA a:VDC_HI
  BRA wnext"""
WOURS_MODULE = """  LDA cnt                ; ours: the window's first rows (two BAT rows a text row) show region
  CMP #4                 ; treg's tiles (0x400 + treg * 0x80 on), the rest blank
  BCS wblank
  LDA treg
  LSR
  PHA
  LDA hdr
  BCC wmap2
  ORA #0x80
wmap2:
  STA a:VDC_LO
  PLA
  CLC
  ADC #0xF4
  STA a:VDC_HI
  BRA wnext"""
MULCODE = "mul:\n  STZ left\n  STZ left+1\n  STZ mhi                ; the product's low byte, dropped\n  LDA pcells\n  STA cnt\n  LDA fpc\n  STA mlo\n  LDA fpc+1\n  STA row                ; row: the multiplicand's high byte (shifted up)\n  STZ n                  ; n: its third byte\nmloop:\n  LSR cnt\n  BCC mskip\n  CLC\n  LDA mhi\n  ADC mlo\n  STA mhi\n  LDA left\n  ADC row\n  STA left\n  LDA left+1\n  ADC n\n  STA left+1\nmskip:\n  ASL mlo\n  ROL row\n  ROL n\n  LDA cnt\n  BNE mloop\n  RTS                    ; (a zero share never turns the page: the line is too short to matter)\n"
ROWCODE_MODULE = "; ---- the text rows for the line: 2-3 (region 3's tiles) unless a face lives there, then 0-1\n; (region 2's); with faces in both, a hidden face's region is borrowed - the speaker's never -\n; and its bitmap drawn again from the scene's own record when the line ends. A = 1 when the\n; rows moved (the caller maps the BAT again) ----\nrowsel:\n  LDA #0xFF\n  STA nspill\n  LDA #{FIRST_REG}\n  STA ntreg\n  LDA faces\n  BEQ rsdone\n  JSR FACE+18            ; A = the regions in use (any object), X = those with a band face\n  STA n\n  STX n2\n  LDA n\n  AND #0x40\n  BEQ rsdone             ; region 6 free (the renderer's rows 0-1 at the game's base)\n  LDA n\n  AND #0x80\n  BNE rsboth\n  LDY #7                 ; region 7 free (rows 2-3)\n  BRA rsfree\nrsboth:\n  LDA #7                 ; both in use: 7 borrowed - unless the speaker's face is there, or a\n  LDX FACE+15            ; band face (hidden for the line anyway) is in 6 and not in 7 (and\n  CPX #7                 ; the speaker's is not: its region is never borrowed)\n  BEQ rsb6\n  CPX #6\n  BEQ rsborrow\n  LDX n2\n  CPX #0x40\n  BNE rsborrow\nrsb6:\n  LDA #6\nrsborrow:\n  STA nspill\n  TAY\nrsfree:\n  STY ntreg\nrsdone:\n  LDA ntreg              ; the renderer's rows: 0-1 for region 6, 2-3 for 7\n  SEC\n  SBC #6\n  ASL\n  STA row0\n  LDA rowsin\n  BEQ rstake\n  LDA ntreg\n  CMP treg\n  BNE rschange\n  LDA nspill\n  CMP spill\n  BNE rschange\n  LDA #0\n  RTS\nrschange:\n  LDA #1                 ; (mid-line: a face arrived in the rows' region - it is drawn again)\n  STA moving\n  JSR release\nrstake:\n  LDA ntreg\n  STA treg\n  LDA nspill\n  STA spill\n  STA FACE+16            ; the face block keeps the borrowed region's face off the screen (the\n                         ; region, FF none - as +1 it hid nothing: the borrowed face drew our rows)\n  LDA #1\n  STA rowsin\n  RTS\n; ---- the rows given back: the borrowed face drawn again from its record, else the tiles cleared ----\nrelease:\n  LDA rowsin\n  BEQ reldone\n  STZ rowsin\n  LDA spill\n  BMI relmove\nrelback:\nrelplay:                 ; (not parked - no free region: its bitmap is lost, as any face's\nrelend:                  ; the game brings back without decoding it again)\n  LDA #0xFF\n  STA spill\n  STA FACE+16\n  BRA reldone\nrelmove:\n  LDA moving             ; mid-line, a face arrived in the region: it is left as it is (over\n  BNE reldone            ; our rows; replaying its record while the game still decodes it\nrelclear:                ; derailed the decode, and clearing would take the face)\n  JSR clear\nreldone:\n  STZ moving\n  RTS\n"
ROWTAIL_VARS = ['dvb', 'left', 'mhi', 'pcells', 'cnt', 'fpc', 'mlo', 'row', 'nsp', 'npk', 'psp', 'ppk', 'free0', 'free', 'ntreg', 'nrw', 'mode', 'n2', 'n', 'faces', 'tmpa', 'tmpb', 'rreg', 'row0', 'rowsin', 'treg', 'nrows', 'rows2', 'moving', 'gw', 'gwget', 'clear', 'parkhidden']
ROWTAIL_ASM = "; ---- the text rows for the line (resident): FOUR rows - the renderer's 0-3, regions 6 and 7 -\n; in the face layout when 6 and 7 hold band faces only and each has a free slot in 4/5 to be\n; parked in (the speaker's too: its sprites are drawn from the parked copy, fsprite repoints\n; them); else TWO rows in region 6 (rows 0-1) or 7 (2-3), whichever no live object draws\n; from, else one borrowed (7, or 6 when the speaker's face is in 7 or a band face - hidden for\n; the line anyway - is in 6 alone; never the speaker's) and parked when a slot is free. A = 1\n; when the rows moved (the caller maps the BAT again) ----\nrowsel:\n  LDA #0xFF\n  LDX #5\nrsclr:\n  STA {nsp},X              ; the proposal: nsp[3] the regions parked, npk[3] their slots\n  DEX\n  BPL rsclr\n  LDA #6\n  STA {ntreg}\n  LDA #2\n  STA {nrw}\n  LDA {faces}\n  BNE rsgo\n  JMP rsdone\nrsgo:\n  JSR FACE+18            ; A = the regions in use (any object), X = those with a band face\n  STA {n}\n  STX {n2}\n  JSR {gwget}              ; the free slots among 4 and 5: no object, not a region the game\n  ORA {n}                  ; decoded into this module (a slot the last line parked in is free:\n  EOR #0xFF              ; a change of pairs releases - copies back - before it takes)\n  AND #0x30\n  STA {free}\n  STA {free0}              ; a PAIR of regions for the page - 4/5 (the game's slots) first,\n  CMP #0x30              ; then 6/7 (the game's own text rows, free when no face object\n  BNE rs1s               ; draws from them - no more: the game decodes pictures there unlogged, Harry's body in 478 came up as scraps over our rows): four rows in the face layout, three in the\n                         ; plain one (3 x 18 cells fill the buffer; 4 do not)\n  BRA rs1s               ; (one region always: the page's rows pack into it - ROW_TILES)\nrs1s:\n  JSR slot               ; one slot free: two rows in it (4, then 5)\n  BMI rs2\n  STA {ntreg}\n  JMP rsdone\nrs2:\n  LDA {n}\n  AND #0x40\n  BEQ rsdone1            ; region 6 free (the renderer's rows 0-1 at the game's base)\n  LDA {n}\n  AND #0x80\n  BNE rsboth\n  LDY #7                 ; region 7 free (rows 2-3)\n  BRA rsfree\nrsboth:\n  LDA #7                 ; both in use: 7 borrowed - unless the speaker's face is there, or a\n  LDX FACE+15            ; band face (hidden for the line anyway) is in 6 and not in 7 (and\n  CPX #7                 ; the speaker's is not: its region is never borrowed)\n  BEQ rsb6\n  CPX #6\n  BEQ rsborrow\n  LDX {n2}\n  CPX #0x40\n  BNE rsborrow\nrsb6:\n  LDA #6\nrsborrow:\n  STA {nsp}                ; the first pair: the borrowed region, parked when a slot is free\n  TAY\n  JSR slot\n  STA {npk}\nrsfree:\n  STY {ntreg}\nrsdone1:\nrsdone:\n  LDA #2                 ; the page's rows: four beside the face, two in the plain layout -\n  LDX {mode}               ; all in the one region (a base per row)\n  BEQ rsdn\n  LDA #4\nrsdn:\n  STA {nrw}\n  STZ {row0}\n  LDA {rowsin}\n  BEQ rstake\n  LDA {ntreg}\n  CMP {treg}\n  BNE rschange\n  LDA {nrw}\n  CMP {nrows}\n  BNE rschange\n  LDX #2\nrsc1:\n  LDA {nsp},X\n  CMP {psp},X\n  BNE rschange\n  LDA {npk},X\n  CMP {ppk},X\n  BNE rschange\n  DEX\n  BPL rsc1\n  LDA #0\n  RTS\nrschange:\n  LDA #1                 ; (mid-line: a face arrived in the rows' region - it is drawn again)\n  STA {moving}\n  JSR release\nrstake:\n  LDA {ntreg}\n  STA {treg}\n  LDA {nrw}\n  STA {nrows}\n  ASL\n  STA {rows2}\n  LDX #2\nrst1:\n  LDA {nsp},X\n  STA {psp},X\n  LDA {npk},X\n  STA {ppk},X\n  DEX\n  BPL rst1\n  JSR fpairs\n  LDA #1\n  STA {rowsin}\n  RTS\n; ---- the pairs into the face block: rmatch reads a parked bitmap for its region, fsprite\n; draws the speaker's sprites from its parked copy ----\nfpairs:\n  LDX #2\nfp1:\n  LDA {psp},X\n  STA FACE+27,X          ; pfrom: +27 a hidden face's region, +28 a second's, +29 the speaker's\n  LDA {ppk},X\n  STA FACE+30,X          ; pto: +30..+32 their slots\n  DEX\n  BPL fp1\n  RTS\n; ---- A = a free slot (4, then 5) taken out of `free`, FF none; Y kept ----\nslot:\n  LDA {free}\n  AND #0x10\n  BEQ slot5\n  LDA {free}\n  AND #0xEF\n  STA {free}\n  LDA #4\n  RTS\nslot5:\n  LDA {free}\n  AND #0x20\n  BEQ slotno\n  LDA {free}\n  AND #0xDF\n  STA {free}\n  LDA #5\n  RTS\nslotno:\n  LDA #0xFF\n  RTS\n; ---- the rows given back: the tiles cleared (unless a face arrived there mid-line), every\n; parked bitmap copied back (unless, mid-line, the game decoded a known face into its\n; region - its decode is the truth there), the pairs dropped ----\nrelease:\n  LDA {rowsin}\n  BEQ reldone\n  STZ {rowsin}\n  LDA {moving}\n  BNE rel1\n  JSR {clear}\nrel1:\n  JSR pdrop\nreldone:\n  STZ {moving}\n  RTS\n; ---- every pair dropped (the copies stay where they are) ----\npdrop:\n  LDA #0xFF\n  LDX #5\npd1:\n  STA {psp},X\n  DEX\n  BPL pd1\n  JMP fpairs\n; ---- left = pcells * fpc / 256 (the stub's, moved here for room) ----\ntmul:\n  STZ {left}\n  STZ {left}+1\n  STZ {mhi}                ; the product's low byte, dropped\n  LDA {pcells}\n  STA {cnt}\n  LDA {fpc}\n  STA {mlo}\n  LDA {fpc}+1\n  STA {row}                ; {row}: the multiplicand's high byte (shifted up)\n  STZ {n}                  ; n: its third byte\ntmloop:\n  LSR {cnt}\n  BCC tmskip\n  CLC\n  LDA {mhi}\n  ADC {mlo}\n  STA {mhi}\n  LDA {left}\n  ADC {row}\n  STA {left}\n  LDA {left}+1\n  ADC {n}\n  STA {left}+1\ntmskip:\n  ASL {mlo}\n  ROL {row}\n  ROL {n}\n  LDA {cnt}\n  BNE tmloop\n  RTS                    ; (a zero share never turns the page: the line is too short to matter)\n; ---- the page timer (the resident stub's, moved here for room): `left` less dvb, the frames\n; since the stub's last pass (the vblank count), not one a pass: the game's long frames skip\n; passes (8 in a row behind a picture decode) and held every page of a long line back, 10-17 %\n; late by its last card (318 3f and 41, 654 9d, 478 22). A = 1 (Z clear) when it ran out\n; (left may be left past zero then: the next page sets it, and no page means `more` is 0) ----\nttick:\n  LDA {left}\n  ORA {left}+1\n  BEQ ttret\n  SEC\n  LDA {left}\n  SBC {dvb}\n  STA {left}\n  LDA {left}+1\n  SBC #0\n  STA {left}+1\n  BCC ttz\n  ORA {left}\n  BNE ttno\nttz:\n  LDA #1\n  RTS\nttno:\n  LDA #0\nttret:\n  RTS\n"   # the row code, in bank 1's tail (the stub's variables by address)
ROWCODE_RESIDENT = """; ---- the row code lives in bank 1's tail (ROWTAIL_ASM): bank 1 at MPR3 round each call
; under the nested-vblank guard ($30 = 2, as the region copy), the text bank (2) back after ----
rowsel:
  ; Recap pictures use scratch tiles without passing through the decoder tracker.
  ; Keep face positioning active, but allocate only the native two text rows.
  LDA faces
  PHA
  LDA 0x351D
  CMP #5
  BNE rsnormal
  STZ faces
rsnormal:
  JSR tin
  JSR {TROWSEL}
  TAX
  PLA
  STA faces
  TXA
  BRA tback
release:
  JSR tin
  JSR {TRELEASE}
  BRA tback
pdrop:
  JSR tin
  JSR {TPDROP}
tback:
  PHA
  LDA #2
  JSR 0x43AA
  STZ 0x30
  PLA
  RTS
tin:
  LDA #2
  STA 0x30
  TMA #0x04              ; bank 1 at MPR3 (as gwin: from MPR2, not [$3F80])
  INC
  TAM #0x08
  RTS
"""


def pceengine_gwin():
    """The text bank's `gwin` byte (pceengine's rclr sets it when the game rebuilds its window)."""
    import pceengine
    return pceengine.build()[1]["gwin"]


def source(face=None, resident=True, tails=None, cdlabels=None):
    """The stub's source: `face` = its face block's address (rec 110's at MPR5 when resident,
    else the module's own at MPR4, already mapped by the trampoline); `tl` = the tail's labels
    (the row code's entries; placeholders of the same width when None)."""
    face = FACE if face is None else face
    tails = tails or {}                              # the tail's labels (the row code's entries)
    off = set(os.environ.get("SUBS_OFF", "").split(","))          # (debug: pieces left out)
    facemap = f"""  LDA #{FACE_BANK}               ; the face block's bank at MPR5, if the resident file is in
  CLC
  ADC 0x3F80
  TAM #0x20
""" if resident else ""
    if cdlabels is not None:
        tl = cdlabels
    else:
        vl = vfix_block()[1]
        tl = dict(cd_block()[1], vfix=vl["vfix"], keep=vl["keep"])
    out = SOURCE_TEMPLATE.replace("{FACE}", str(face)).replace("{FACEMAP}", facemap)
    entrychk = """  PHA                    ; the block is whole only when BOTH ends are in: rec 110 loads
  LDA FACE+3             ; head-first, and a scene block over it (the ending's flashback)
  CMP #0x46              ; takes the face block and the stub's head while the tail's
  BNE entryno            ; signature still stands - the face block's "FL1" is the head's
  LDA FACE+4
  CMP #0x4C
  BNE entryno
  LDA FACE+5
  CMP #0x31
  BNE entryno
  PLA
  JMP stat
entryno:
  PLA
  RTS""" if resident else ""
    out = out.replace("{ENTRYCHK}", entrychk)
    park1 = """  ; the borrowed region's bitmap parked in a free face region (4, then 5), copied back at
  ; the release: a replay of its record fails once the block it came from is gone (the HQ
  ; reception's Metal Gear, decoded outside, was lost and drew our rows in its sprites)
  LDA spill
  BMI rstake2
  JSR gwget              ; the regions the game decoded into this module: its tiles for a
  STA gw                 ; sprite not live yet (the ruins' explosion), no place for a bitmap
  LDX #4
  LDA n                  ; the regions in use (rowsel's)
  ORA gw
  AND #0x10
  BEQ rpark
  INX
  LDA n
  ORA gw
  AND #0x20
  BNE rstake2            ; neither free: the bitmap is lost
rpark:
  STX park
  STX FACE+17
  LDA spill
  JSR FACE+21            ; vcopy: region A into region X
rstake2:""" if resident else ""
    park2 = """  LDX park
  BMI relplay
  TXA                    ; the parked bitmap back, its objects shown again
  LDX spill
  JSR FACE+21            ; vcopy: region A into region X
  BRA relend""" if resident else ""
    park4 = "  STA park\n  STA FACE+17" if resident else ""
    parkmv = """  LDA moving             ; mid-line: the game may have decoded a face into the borrowed
  BEQ relback            ; region (its bitmap then reads as a known face - our rows never
  LDA spill              ; do): its decode is the truth there, the parked copy is dropped
  JSR FACE+24            ; rmatchraw: the region's own bitmap
  BEQ relback
  BRA relend""" if resident else ""
    out = out.replace("{PARKMV}", parkmv).replace("{PARK5}", park4)
    parksel = """  LDX park               ; a parked bitmap's region is in use: its face comes back (taken as
  BMI rsnopark           ; free, the rows cleared it right after the copy back)
  LDA #0x40
  LDX spill
  CPX #7
  BNE rspark6
  ASL
rspark6:
  ORA n
  STA n
rsnopark:""" if resident else ""
    out = out.replace("{PARKSEL}", parksel)
    takeover = """  LDA shown              ; the game's list opened under the line: the window is its now and
  BEQ tickp              ; the line goes on unseen (a page over a menu drew into its rows)
  LDA a:{GWIN}           ; the game rebuilt its window (pceengine's rclr on $689B: a list or a
  BNE tickt              ; message opening, whatever its item count - a list with the count the
  LDA LIST_COUNT         ; last one had escaped the count test and the line's end cleared the
  CMP lst                ; labels' tiles, #43)
  BEQ tickp
tickt:
  STZ shown
  STZ more
  STZ pend
  STZ grace
  STZ linger
  PHX
  PHY
  JMP stopped0
tickp:""" if resident else ""
    gwin = pceengine_gwin()
    out = out.replace("{TAKEOVER}", takeover.replace("{GWIN}", str(gwin)))
    out = out.replace("{GWINCHK}", f"  LDA a:{gwin}           ; the game rebuilt its window since the line began (rclr)\n  BNE stopped4" if resident else "")
    out = out.replace("{GWINCLR}", f"  STZ a:{gwin}" if resident else "")
    gwmag = """  LDY #0                 ; another module: the game's decodes so far forgotten
  JSR mfetch
  CMP gmag
  BNE gwnew
  LDY #1
  JSR mfetch
  CMP gmag+1
  BEQ gwsame
gwnew:
  LDY #0
  JSR mfetch
  STA gmag
  LDY #1
  JSR mfetch
  STA gmag+1
  JSR gwclr
gwsame:""" if resident else ""
    out = out.replace("{GWMAG}", gwmag if "gwmag" not in off else "")
    gwcode = """; ---- the tail's gwrote (stage 2's bank 1 at MPR3 meanwhile): A = it / cleared ----
; (bank 1 at MPR3 only under the game's nested-vblank guard: a vblank landing meanwhile ran
; the handler's full path with the wrong bank there - the list labels stopped drawing; $30 is
; put back as found, these run inside guarded callers too)
gwget:
  JSR gwin
  LDA a:{GWROTE}
  STA gw
  JSR gwout
  LDA gw
  RTS
gwclr:
  JSR gwin
  STZ a:{GWROTE}
  JMP gwout
gwin:
  LDA 0x30
  STA g30
  LDA #2
  STA 0x30
  TMA #0x08
  STA mpr3
  TMA #0x04              ; bank 1 = the bank after stage 2's bank 0 at MPR2 (not 1 + [$3F80]:
  INC                    ; the game moves that base while it builds a list, and a write
  TAM #0x08              ; through it landed in another bank - the verb menu came out 9 long)
  RTS
gwout:
  LDA mpr3
  TAM #0x08
  LDA g30
  STA 0x30
  RTS""" if resident else ""
    out = out.replace("{GWCODE}", gwcode).replace("{GWROTE}", str(tail()[1]["gwrote"]))
    out = out.replace("{GWTAKE}", "")
    out = out.replace("{G30S}", "  LDA 0x30               ; ($30 as found: guarded callers keep their guard)\n  PHA" if resident else "")
    out = out.replace("{G30E}", "  PLA\n  STA 0x30" if resident else "  STZ 0x30")
    out = out.replace("{DECWAIT}", "")
    out = out.replace("{BREAKCHECK}", """  BNE wordchunk
  ; Zero + mask is a boundary planned for the current width and row count.
  ; Other layouts consume the marker and continue without a page turn.
  LDY #1
  JSR tfetch
  STA cnt
  LDA #2
  JSR eat
  LDA cnt                ; bit 5: a pause in the voice here - the byte after is its length in
  AND #0x20              ; cells' worth of time, added to the page's time (inert to every
  BEQ nopause            ; layout's page and row bits)
  LDY #0
  JSR tfetch
  CLC
  ADC pcells
  BCC pzok
  LDA #0xFF
pzok:
  STA pcells
  LDA #1
  JSR eat
nopause:
  LDY {PAGEROWS}
  LDA pagemasks-2,Y
  LDY mode
  BNE pagemask
  ASL
  ASL
  ASL
pagemask:
  AND cnt
  BNE forcedpage
  LDA cnt                ; a row break the plan put here (the rows are planned whole at the
  CPY #0                 ; build, pcelayout.plan_pages): bit 7 in the plain layouts, bit 6 in
  BEQ rowplain           ; the face ones (Y = mode); bit 7 of cells then sends the next chunk to
  ASL                    ; a new row by its cost
rowplain:
  TAY                    ; (N from the bit)
  BPL tochunk
  LDA cells
  ORA #0x80
  STA cells
tochunk:
  JMP chunk
forcedpage:
  JMP pdone
pagemasks:
  .byte 1, 2, 4
wordchunk:""".replace("{PAGEROWS}", "nrows" if resident else "#2"))
    zpsave = """  LDA 0x90               ; the game's FETCH pointer ($90-$92) and VDC select shadow ($F7) as
  STA z90                ; found: the handler restores $00-$17, $30, $96-$97, $F8-$FF and the
  LDA 0x91               ; MPRs but not these, and the main loop reads its strings through
  STA z91                ; $90-$92 a byte at a time (the list labels: a vblank between the
  LDA 0x92               ; pointer's write and the fetch read OUR table's byte - an FF ended
  STA z92                ; 'Mechanic room' at 'Mech', 'Go out' came out garbled)
  LDA 0xF7
  STA zf7""" if resident else ""
    zprest = """  LDA z90
  STA 0x90
  LDA z91
  STA 0x91
  LDA z92
  STA 0x92
  LDA zf7
  STA 0xF7
  STA a:0x0000""" if resident else ""
    out = out.replace("{ZPSAVE}", zpsave).replace("{ZPREST}", zprest)
    lineres = "  STZ lossc\n  STZ fran" if resident else ""     # (fran: the walker passes the page waits for)
    out = out.replace("{LINERES}", lineres)
    midline = """  LDA FACE+15            ; the speaker's face read unknown (a decode in progress): the layout
  BPL dm5                ; kept for a few passes before the plain one
  LDA mode
  BEQ dm5
  INC lossc
  LDA lossc
  CMP #4
  BCS dm6
  JMP tickg2
dm5:
  STZ lossc
dm6:""" if resident else ""
    layout2 = """  JSR rowsel             ; a face came or went: the rows may have to move (the layout stays:
  BNE tickgw             ; it is the line's own, modeset reads its byte - no page laid out
  JMP tick2              ; again for a face arriving: the doubled lines)
tickgw:
  LDA #2
  STA n
  JSR wbat               ; the window's BAT for the new rows
  BRA tickg1""" if resident else """  JSR modeset
  JSR rowsel             ; a face came or went: the rows may have to move
  BEQ tickg1
  LDA #2
  STA n
  JSR wbat               ; the window's BAT for the new rows"""
    out = out.replace("{LAYOUT2}", layout2)
    tickg = """  JMP tick2
tickg:
  PHA
  LDX linger             ; (after the line's end the page is gone: nothing to lay out again)
  BEQ tickg3
  JMP tickg2
tickg3:
""" + (midline if "midline" not in off else "") + """
  PLA
  BEQ tick2
""" + layout2 + """
tickg2:
  PLA
  JMP tick2""" if resident else """  BRA tick2
tickg:
  CMP #0
  BEQ tick2
  LDX linger             ; (after the line's end the page is gone: nothing to lay out again)
  BNE tick2
""" + layout2
    out = out.replace("{TICKG}", tickg)
    out = out.replace("{PARK1}", park1).replace("{PARK2}", park2).replace("{PARK4}", park4)
    rowcode = ROWCODE_RESIDENT
    for k, name in (("TROWSEL", "rowsel"), ("TRELEASE", "release"), ("TPDROP", "pdrop")):
        rowcode = rowcode.replace("{" + k + "}", str(tails.get(name, 0xBFFC)))
    out = out.replace("{MULCODE}", ("mul:\n  JSR tin\n  JSR %d\n  JMP tback\n" % tails.get("tmul", 0xBFFC)) if resident else MULCODE)
    # the page timer: `left` less dvb, the frames since the last pass (the vblank count; one a
    # pass held a long line's pages back when the game's long frames skipped passes) - the
    # resident stub's in bank 1's tail (ttick), for room; the module stub's (the ending) here
    old_t = ("  LDA left\n  ORA left+1\n  BEQ pdone1\n  LDA left\n  BNE dec\n  DEC left+1\ndec:\n"
             "  DEC left\n  LDA left\n  ORA left+1\n  BNE pdone1\n")
    assert out.count(old_t) == 1
    if resident:
        out = out.replace(old_t, "  JSR tin\n  JSR %d\n  JSR tback\n  BEQ pdone1\n" % tails.get("ttick", 0xBFFC))
    else:
        out = out.replace(old_t, "  LDA left\n  ORA left+1\n  BEQ pdone1\n  SEC\n  LDA left\n  SBC dvb\n  STA left\n"
                                 "  LDA left+1\n  SBC #0\n  STA left+1\n  BCC dec\n  ORA left\n  BNE pdone1\ndec:\n")
    if resident:
        # the rest of cdinit (the block's magic, its entries, cdok) runs in the clock's own block
        # (CD_SOURCE cdini2), for room: cdinit is called with the voice bank at MPR3, where the
        # clock's variables are. (From bank 1's tail, 2026-11-05, it wrote them into bank 1 - the
        # object walker - and came back with the text bank at MPR3 under the clock's call: the
        # Act 2 recap lost its faces and drew its cue table as the speaker's name.)
        a = out.index("JSR tfetch             ; the block's magic", out.index("cdinit:\n"))
        a = out.rindex("  LDY #0\n", 0, a)
        b = out.index("cdi2:\n  RTS\n", a)
        out = out[:a] + "  LDA cdblk\n  LDX cdblk+1\n  JMP {CDINI2}\n" + out[b:]
    parkhidden = """
; ---- C set: a hidden band portrait in 6/7 parked, freeing four text rows ----
parkhidden:
  STA tmpa                ; occupied bits in 6/7, from the tail's rowsel
  CMP #0xC0               ; two portraits need two slots; the one-slot path cannot
  BEQ phno
  LDA mode
  BEQ phno
  LDA FACE+15             ; never borrow the speaker's animated bitmap
  CMP #6
  BCS phno
  LDA n2
  AND tmpa
  CMP tmpa                ; occupied region must contain band portraits only
  BNE phno
  LDA free
  BEQ phno
  LDY #6
  LDA tmpa
  AND #0x40
  BNE phregion
  INY
phregion:
  STY nsp
  LDY #4
  LDA free
  AND #0x10
  BNE phslot
  INY
phslot:
  STY npk
  STZ free                ; exactly one scratch slot was available
  SEC
  RTS
phno:
  CLC
  RTS
""" if resident else ""
    out = out.replace("{ROWCODE}", rowcode if resident else ROWCODE_MODULE)   # (parkhidden: its one caller is dead - 6/7 are never the four rows)
    drop = """  STZ rowsin             ; (the rows are the game's now: neither cleared nor drawn over)
  JSR pdrop              ; the parked bitmaps stay where they are""" if resident else """  STZ rowsin             ; (the rows are the game's now: neither cleared nor drawn over)
  LDA #0xFF
  STA spill
  STA FACE+16            ; no region borrowed any more"""
    out = out.replace("{DROP}", drop)
    # the page's rows: the resident's nrows (2 or 4), the module's 2
    out = out.replace("{NROWS}", "nrows" if resident else "#2").replace("{NROWS2}", "rows2" if resident else "#4")
    f8on_old = """  LDA #0xF8              ; the renderer's tile base for this message: regions 4/5 (0x6000)
  STA MSG,X              ; or the game's 6/7 (0x7000) - the rows go where rowsel put them,
  INX                    ; the faces untouched (the game animates the speaker's mouth into
  STZ MSG,X              ; its region while it talks: no text can live there)
  INX
  LDA treg
  AND #6
  ASL
  ASL
  ASL
  ORA #0x40
  STA MSG,X
  INX""" if resident else ""
    f8off = """  LDA #0xF8              ; the game's base back
  STA MSG,X
  INX
  STZ MSG,X
  INX
  LDA #0x70
  STA MSG,X
  INX""" if resident else ""
    f8on = ""                                    # (the resident's base is per row: ROWBASE)
    out = out.replace("{ROWBASE}", ROWBASE if resident else "").replace("{FACEW}", str(WIDTH_FACE4 if resident else WIDTH_FACE))
    out = out.replace("{WROW}", WROW if resident else "").replace("{WOURS}", WOURS_RES if resident else WOURS_MODULE)
    out = out.replace("{F8ON}", f8on).replace("{F8OFF}", f8off).replace("{ROWBODY}", "12" if resident else "9")
    out = out.replace("{CLEARN}", "  LDX #8                 ; the region: 8 x 256 words" if resident else "  LDX #8                 ; 4 x 256 words a row")
    out = out.replace("{NEXTROW}", """  LDA width              ; X = 4 + cur * (8 + 2 * width) + 8: the row's body
  ASL
  CLC
  ADC #8
  STA rlen
  LDA #12                ; (after fc 00 f9 01, the row's f8 lo hi fb col row fe colour)
  LDX cur
rowx:
  CLC
  ADC rlen
  DEX
  BNE rowx
  TAX""" if resident else """  LDA width              ; X = 9 + 5 + 2 * width: the second row's body
  ASL
  CLC
  ADC #14
  TAX""")
    out = out.replace("{MSGADDR}", str(int(os.environ.get("SUBS_MSGRES", "0"), 0) or MSG_RES if resident else MSG))
    out = out.replace("{ROWVARS}", ROWVARS if resident else "")
    for k, v in (("EPION", "  JSR epion" if not resident else ""), ("EPIOFF", "  JSR epioff" if not resident else ""),
                 ("EPITICK", "  JSR epitick" if not resident else ""), ("EPI", EPI_SOURCE if not resident else ""),
                 ("ROWCOL", str(EPI_COLOURS.get(TEXT_COLOUR, TEXT_COLOUR) if not resident else TEXT_COLOUR)),
                 ("FIRST_REG", str(FIRST_REG if resident else MODULE_REG)),
                 ("HOLDCHK", HOLDCHK if resident else "")):
        out = out.replace("{" + k + "}", v)
    for k in ("CDSCAN", "CDWAS", "CDTBL", "CDOK", "CDMAG", "CDMODE", "CDCUR", "CDSIG", "FHOLD", "VFIX", "KEEP", "CDINI2"):
        out = out.replace("{" + k + "}", str(tl[k.lower()]))
    return out


# the hold's check (#93), in the resident stub only, inside the clock's mapping of the voice
# bank (fhold sits there); a module's own stub has no face block and never holds
HOLDCHK = """  JSR {KEEP}             ; the hold's check (#93) and vfix (#91), in the voice bank beside the clock
"""


SOURCE_TEMPLATE = f"""
MSG = {{MSGADDR}}
MAGIC = {MAGIC}
CUES_PTR = {CUES_PTR}
FETCH = {FETCH}
DRAWING = 0x3470
LIST_COUNT = 0x3518              ; the game's list menu: its item count while one is up
MSG_BUSY = 0x3478                ; non-zero while a message of the game's owns the box
RECORD = {RECORD}
VOICE_BANK = 0x1A                ; + [$3F80]: the act's voice table, $8000 + (NN - 1) * 8 a record
WIN = {WIN}
WIN_DIRTY = {WIN_DIRTY}
LAYOUT = 0x27                    ; zero page: 1 = apply the window layout ($3F25 follows it)
CURSOR = 0x34B7                  ; 0 while the game's text is up (the marker sprite follows the cursor), FF else
VDC_SEL = 0x0000                 ; absolute (a:) - the ports sit below the zero page
VDC_LO = 0x0002
VDC_HI = 0x0003
VDC_SHADOW = 0xF7
FACE = {{FACE}}
  JMP stat                       ; (the signature the trampoline checks is at the END: the file
                                 ; loads sector by sector, and the hook runs meanwhile)
nn:     .byte 0
sec:    .word 0                  ; the line's record: its sector, low 16 bits
shown:  .byte 0
heard:  .byte 0
win:    .byte 0                  ; the window's state before the line
mpr3:   .byte 0
gmag:   .word 0xFFFF             ; the module's magic when the game's decodes were last forgotten
gw:     .byte 0                  ; the regions the game decoded into this module (the tail's gwrote)
mpr5:   .byte 0
mpr6:   .byte 0
faces:  .byte 0                  ; the face block is there (rec 110 resident)
hold:   .byte 0                  ; between lines: the last speaker's face kept at the left, the rest off (#93)
fixon:  .byte 0                  ; shown | hold: the walker hook fixes the sprite table while set
mode:   .byte 0                  ; 0 plain, 1 beside the speaker's face
                                 ; or the rows move: the face census flaps while the game decodes a
                                 ; face, and every verdict retyped the page - the ruins' flicker)
schar:  .byte 0                  ; the line's character
sum:    .byte 0
tbl:    .word 0
rem:    .word 0                  ; bytes of chunks left in the line
ptbl:   .word 0                  ; tbl and rem at the page's first chunk
prem:   .word 0
ltbl:   .word 0                  ; tbl at the line's first chunk
ntbl:   .word 0                  ; the module's names block: [char][colour][cells][pairs]..., 0
ctbl:   .word 0                  ; (tbl kept while the names are read)
fpc:    .word 0
left:   .word 0                  ; frames until the next page
col0:   .byte 0
width:  .byte 0
cur:    .byte 0
cells:  .byte 0
pcells: .byte 0
hdr:    .byte 0
n:      .byte 0
cnt:    .byte 0
row:    .byte 0
dl:     .word 0
pend:   .byte 0                  ; a page is built in MSG and waits for the renderer
grace:  .byte 0                  ; frames left to wait for a portrait line's face
owed:   .byte 0                  ; frames that wait took, paid back by the pages (mul)
fran:   .byte 0                  ; the walker hook's passes since the line began (whook counts them)
linger: .byte 0                  ; frames left with the window and the faces kept after a line's end
park:   .byte 0xFF               ; the free face region holding the borrowed region's bitmap, FF none
more:   .byte 0                  ; chunks left after the page on screen
mlo:    .byte 0
mhi:    .byte 0
astat:  .byte 0                  ; AD_STAT this frame
last:   .byte 0                  ; it read playing last frame
lst:    .byte 0                  ; the game's list count when the line began: a stale count (a menu the
                                 ; script cut is never zeroed) is no menu; a menu built under the line
                                 ; changes it (from 0, an item a pass)
cdmode: .byte 0                  ; the tail's: the line up is a CD-DA cue, its entry
cdcur:  .word 0
cdblk:  .word 0                  ; the module's cue block
lastvb: .byte 0                  ; $1B at the last pass
dvb:    .byte 1                  ; the frames since the last pass (the page timer's step)
epi:    .byte 0                  ; (the module stub's) our own window section is up - EPI_SOURCE
row0:   .byte 0                  ; the renderer's row the line starts at: 0 (region 6's tiles) or 2 (7's)
treg:   .byte {{FIRST_REG}}      ; the region whose tiles hold the rows (6 or 7: VRAM 0x4000 + treg * 0x800)
spill:  .byte 0xFF               ; the face region whose bitmap is parked in the BAT, FF none
moving: .byte 0                  ; the rows move mid-line: the region left gets its face back
rowsin: .byte 0                  ; the rows hold a line (tiles to give back)
ntreg:  .byte 0
nspill: .byte 0
{{ROWVARS}}
n2:     .byte 0
; ---- every frame from the vblank handler, after the ADPCM service: A = AD_STAT (returned as is) ----
stat:
  JSR 0xE045             ; AD_STAT (the trampoline's 76 bytes have no room for it any more)
  STA astat
  PHA
  PHX
  PHY
{{ZPSAVE}}
  TMA #0x40
  STA mpr6
  TMA #0x20
  STA mpr5
{{FACEMAP}}  STZ faces
  LDA FACE+3
  CMP #0x46
  BNE nofaces
  LDA FACE+4
  CMP #0x4C
  BNE nofaces
  LDA FACE+5
  CMP #0x31
  BNE nofaces
  INC faces
nofaces:
  ; a CD-DA cue (the module's table, timed from the track's start by the clock in the voice
  ; bank, CD_SOURCE) counts as a line playing: the clock folds its verdict into AD_STAT's (a
  ; real line wins; a change of cue reads stopped for a frame so the next one rises). The
  ; hook runs with the text bank (2) at MPR3: the voice bank is mapped there round the call
  LDA #VOICE_BANK
  JSR 0x43AA
  LDA {{CDSIG}}          ; the clock is in (rec 54 is the opening's scratch, and the stub
  CMP #0x43              ; arrives before it comes back: a call into it then hung the boot)
  BNE cdnone
  LDA {{CDSIG}}+1
  CMP #0x4B
  BNE cdnone
  LDA 0x2638             ; the game's playing flag rises the tick a track starts
  BEQ cdn0
  LDA {{CDWAS}}
  BNE cdn0
  JSR cdinit             ; the module's cue table for the clock
cdn0:
  LDA 0x1B               ; the vblank count: the frames since the last pass, for the clock
  SEC
  SBC lastvb
  TAY
  CMP #17                ; the page timer's step at most 16: a longer gap is a stall before
  BCC dvbok              ; the line (a load), not passes skipped under its words - the first
  LDA #16                ; tick took 34 frames off the ending's first pages
dvbok:
  STA dvb
  LDA 0x1B
  STA lastvb
  LDA astat
  LDX last
  JSR {{CDSCAN}}
  STA astat
  LDA {{CDMODE}}         ; the clock's verdict, for line (the voice bank is gone by then)
  STA cdmode
  LDA {{CDCUR}}
  STA cdcur
  LDA {{CDCUR}}+1
  STA cdcur+1
{{HOLDCHK}}  BRA cdmapped
cdnone:
  STZ cdmode
  STZ hold               ; (no clock in the voice bank, no fhold: no hold)
cdmapped:
  LDA #2
  JSR 0x43AA
{{GWMAG}}
{{GWTAKE}}
  ; a line starts: AD_STAT rises from stopped; the record pointer $5E/$5F names it
  ; (a transfer takes the chip's first tick, a streamed line - ch 3 - plays at once: the
  ; request in $26F3 is gone before a hook after the service can see it)
  LDA astat
  BNE playing
  STZ last
  BRA tick
playing:
  LDA last
  BNE tick
  LDA #1
  STA last
  JSR line
tick:
  ; the hold (#93): after a line's end the game puts a face back at its native column, so
  ; the portrait jumped between every two lines. While the last speaker's face is on the
  ; band and the game opens no list or message of its own, the walker hook keeps it at the
  ; left and the other faces off (x 0, as during a line: the y the game reads back stays)
  LDA pend
  BEQ tick00
  JSR show               ; the renderer was busy: try again
  BEQ tick00
  STZ pend
tick00:
  LDA linger             ; the window kept between two lines: the game's next voice opcode
  BEQ tick0              ; hides it (as it does its own text) the moment the last one ends -
  JSR gtake              ; once the game builds a LIST, its wish (hidden: it maps the rows and
  BEQ tick00f            ; clears their tiles, then opens the window itself) goes back ONCE -
  BCC tick0              ; (a message of its own: the forcing stops, its window stays as it
  LDA win                ; is - put back hidden, Napoleon's code question vanished) kept shown, the reception's first
  CMP #{WIN_SHOWN}       ; menu flashed a frame of stale tiles; win then reads shown, so the
  BEQ tick0              ; game's own opening is never undone
  LDY #{WIN_SHOWN}
  STY win
  BRA tick00s
tick00f:
  LDA WIN                ; the game's wish kept for the end (win) - the window NOT put back:
  CMP #{WIN_SHOWN}       ; its next voice opcode maps its own BAT (tiles 0x700-0x7FF, the last
  BEQ tick0              ; line's words or a face's bitmap) as it hides it, and a window put
  STA win                ; back showed that a frame between two lines (the blinks of r7); a
  BRA tick0              ; hidden window is the band a line's face wait shows anyway
tick00s:
  STA WIN
  LDA #1
  STA WIN_DIRTY          ; (not LAYOUT: a layout apply forced during the ending's scene change
tick0:                   ; crashed the game; the sections were built at the line's winon)
  LDA shown
  BEQ tick0n
  LDA faces
  BNE tick0s
tick0n:
  JMP tick1
tick0s:
  JSR FACE+6             ; fscan: the face objects; A = 1 when the layout changed
  LDX grace
  BEQ tickg
  ; waiting for the speaker's face before the first page
  DEC grace
  INC owed               ; (the frames the wait took: paid back by the pages, keep)
  LDA fran               ; two walker passes with this line's speaker: the second's sprite table
  CMP #2                 ; is the one on screen when the words go up (after one, the words came a
  BCC tickw              ; frame before the face moved - the oracle's +4 at 318:28)
  LDA schar              ; a card line (no speaker, PLAIN): no face to wait for
  BEQ tickfirst
  BMI tickfirst
  LDA FACE+15            ; sreg: found
  BPL tickfirst
tickw:
  LDA grace
  BEQ tickfirst
  JMP tick2              ; still waiting: the faces placed meanwhile (the others hidden: they
tickfirst:               ; showed at their native columns for these frames), no window yet
{{DECWAIT}}
  STZ grace
  JSR modeset
  JSR rowsel
  JSR clear
  JSR winon
  JSR page
{{TICKG}}
tickg1:
  LDA ptbl               ; the page from its first chunk again, its timer kept
  STA tbl
  LDA ptbl+1
  STA tbl+1
  LDA prem
  STA rem
  LDA prem+1
  STA rem+1
  LDA left
  PHA
  LDA left+1
  PHA
  JSR repage
  PLA
  STA left+1
  PLA
  STA left
tick2:
tick1:
{{EPITICK}}
  PLY
  PLX
  LDA astat              ; the verdict (the stack holds the chip's own AD_STAT, returned as
  BEQ stopped            ; is: a CD-DA cue read stopped here and never paged or ended)
  STA heard
{{TAKEOVER}}
  ; playing: the page timer
  LDA more
  BEQ pdone1
  LDA left
  ORA left+1
  BEQ pdone1
  LDA left
  BNE dec
  DEC left+1
dec:
  DEC left
  LDA left
  ORA left+1
  BNE pdone1
  PHX
  PHY
  JSR page               ; the next page
  PLY
  PLX
pdone1:
  JMP done
stopped:
  LDA shown
  BEQ stopx
  LDA heard
  BNE stoppedgo          ; (not started yet: the transfer is still pending)
stopx:
  JMP done
stoppedgo:
  PHX
  PHY
  LDA grace              ; over before its page: nothing on the screen
  BEQ stoppedl
  STZ grace
  STZ shown
  STZ heard
  LDA linger             ; (a line that never showed, after one that lingers: the linger's
  BEQ stopped2           ; window is still up - ended now)
  STZ linger
  BRA stopped0
stoppedl:
  LDA linger             ; the line's end: its rows unmapped (blank: the next face's bitmap may
  BNE stoppedl1          ; decode into their tiles meanwhile), the window and the faces kept
  LDA cdmode             ; for LINGER frames - the next line of the conversation goes on in
  BEQ stoppedlg          ; the same window (hiding and showing it between two lines blinked
  LDA 0x2638             ; the band). Not after a CD-DA track's end: the game builds its verb
  BEQ stoppedfull        ; menu there and reads the band (faces hidden = no Look, no Use Metal
stoppedlg:               ; Gear on the act-2 Chief's)
  LDA #{LINGER}
  STA linger
  STZ more
  STZ pend
  STZ n
  JSR wbat
  BRA stopped2
stoppedl1:
  DEC linger
  BNE stopped2
stoppedfull:
  STZ shown
  STZ heard
stopped0:
  ; the game's window took over meanwhile (a list or a message up: the tricycle's
  ; destinations opened under Metal Gear's last line): its rows and its mapping stay,
  ; the window stays shown; else our rows are given back and the window put as it was
{{GWINCHK}}
  JSR gtake              ; (the list count changed since the line began: the game's, built
  BEQ stopped3           ; from 0 - a count the script left behind stays, the ruins' scream)
stopped4:
{{DROP}}
  LDA #{WIN_SHOWN}
  STA win
  BRA stopped1
stopped3:
  JSR release
  INC hold               ; the hold starts (zero here: line cleared it; it only moves a lone
                         ; face, and ends as soon as the game builds a list or a message)
stopped1:
  JSR winoff
stopped2:
  PLY
  PLX
done:
{{ZPREST}}
  LDA mpr6
  TAM #0x40
  LDA mpr5
  TAM #0x20
  PLA                    ; (the trampoline sets the flags on A)
  RTS
; ---- the layout from the face block's verdict: mode, col0, width ----
modeset:
  LDA #{COL_PLAIN}
  STA col0
  LDA #{WIDTH_PLAIN}
  STA width
  STZ mode
  LDA faces
  BEQ modeset1
  LDA schar              ; the layout is the line's (its character byte, decided at build):
  BEQ modeset1           ; no speaker or bit 7 (PLAIN) the card; a portrait line beside its
  BMI modeset1           ; face, the card if the face never came in its wait - set once, at the
  LDA FACE+15            ; first page (a face coming or going later moves the rows only: never
  BMI modeset1           ; the same words as a card and then beside the face)
  LDA #{COL_FACE}
  STA col0
  LDA #{{FACEW}}
  STA width
  LDA #1
  STA mode
modeset1:
  RTS
; ---- the loaded module's table: tbl = its start, ntbl = its names block (hnames: from the
; block at tbl - a cue block reads the same way) ----
header:
  LDY #2
  JSR mfetch
  STA tbl
  LDY #3
  JSR mfetch
  STA tbl+1
hnames:
  LDY #2                 ; the table: [magic u16][names offset u16] then the entries
  JSR tfetch
  STA mlo
  LDY #3
  JSR tfetch
  STA mhi
  CLC
  LDA tbl
  ADC mlo
  STA ntbl
  LDA tbl+1
  ADC mhi
  STA ntbl+1
  RTS
; ---- a track starts: the module's cue block ([magic u16][names offset u16][entries...0]
; [names...0], at CUES_PTR - rec 54's bank for the ending's, whose front banks are gone by
; the epilogue) checked against the module's magic bytes, its entries to the tail ----
cdinit:
  STZ {{CDOK}}
  LDA #lo(CUES_PTR)
  STA tbl
  LDA #hi(CUES_PTR)
  STA tbl+1
  LDY #0
  JSR tfetch
  STA cdblk
  LDY #1
  JSR tfetch
  STA cdblk+1
  ORA cdblk
  BEQ cdi2               ; no cues: the tail stays off
  LDA cdblk
  STA tbl
  LDA cdblk+1
  STA tbl+1
  LDY #0
  JSR tfetch             ; the block's magic: the tail holds it against the module's before
  STA {{CDMAG}}          ; every scan (a block that is not this module's never scans)
  LDY #1
  JSR tfetch
  STA {{CDMAG}}+1
  CLC
  LDA cdblk
  ADC #4
  STA {{CDTBL}}
  LDA cdblk+1
  ADC #0
  STA {{CDTBL}}+1
  LDA #1
  STA {{CDOK}}
cdi2:
  RTS
; ---- a new line: a CD-DA cue's entry from the tail, else NN from the record pointer
; ($8000 + (NN - 1) * 8; $8800 on is the effects') ----
line:
  STZ hold               ; the line lays out its own faces
  LDA cdmode
  BEQ lreal
  LDA cdblk              ; the block's own names
  STA tbl
  LDA cdblk+1
  STA tbl+1
  JSR hnames
  LDA cdcur
  STA tbl
  LDA cdcur+1
  STA tbl+1
  JMP found
lreal:
  LDA RECORD+1
  SEC
  SBC #0x80
  CMP #8
  BCC lnok0
  RTS
lnok0:
  ASL
  ASL
  ASL
  ASL
  ASL
  STA nn
  LDA RECORD
  LSR
  LSR
  LSR
  ORA nn
  INC
  BNE lnok1
  RTS                    ; 256: not a line
lnok1:
  STA nn
  ; the record's sector, bytes 3-4: the same NN names another line in another act's table
  ; (the ending's c8-d8 twice), so the entry is keyed on both
  LDA #VOICE_BANK
  CLC
  ADC 0x3F80
  TAM #0x40              ; (mpr6 is put back at the end of stat)
  LDA RECORD+1
  AND #0x1F
  ORA #0xC0
  STA 0x91
  LDA RECORD
  STA 0x90
  LDY #3
  LDA (0x90),Y
  STA sec
  INY
  LDA (0x90),Y
  STA sec+1
  ; the module's table: its first two bytes are the module's magic (the front banks may hold a
  ; scene block by now - the ending's - and the tail its pointer still)
  JSR header
  LDY #1
lchk:
  JSR tfetch
  STA sum
  JSR mfetch             ; (FETCH keeps Y)
  CMP sum
  BNE lnone
  DEY
  BPL lchk
  LDA #4
  STA mlo
  STZ mhi
  JSR adv
entry:
  LDY #0
  JSR tfetch             ; the entry's NN
  CMP #0
  BEQ lnone
  CMP nn
  BNE enext
  LDY #1
  JSR tfetch             ; its sector
  CMP sec
  BNE enext
  LDY #2
  JSR tfetch
  CMP sec+1
  BEQ found
enext:
  LDY #3
  JSR tfetch             ; (FETCH clobbers the carry: read both bytes first)
  STA mlo
  LDY #4
  JSR tfetch
  STA mhi
  CLC
  LDA mlo
  ADC #5
  STA mlo
  LDA mhi
  ADC #0
  STA mhi
  JSR adv
  BRA entry
lnone:
  RTS
found:
  LDY #3
  JSR tfetch
  STA rem
  LDY #4
  JSR tfetch
  STA rem+1
  SEC
  LDA rem
  SBC #3
  STA rem
  LDA rem+1
  SBC #0
  STA rem+1
  LDY #5
  JSR tfetch
  STA fpc
  LDY #6
  JSR tfetch
  STA fpc+1
  LDY #7
  JSR tfetch
  STA schar
  LDA #8
  STA mlo
  STZ mhi
  JSR adv                ; tbl = the chunks
  LDA tbl
  STA ltbl
  LDA tbl+1
  STA ltbl+1
  LDA faces
  BEQ line1
  LDA schar
  JSR FACE+0             ; fstart: the block forgets the last line, A = the character
  JSR FACE+6             ; fscan
line1:
  JSR modeset
  STZ heard
  LDA #1
  STA shown
  LDA LIST_COUNT
  STA lst
{{GWINCLR}}
{{LINERES}}
  STZ owed
  LDA faces              ; every line waits for one walker pass with its own speaker - the page
  BEQ lnow               ; up before it showed the last speaker's face 4 frames beside the new
                         ; words (the portrait oracle, 2026-10-16) - and a portrait line for its
                         ; face too (GRACE frames at most: rows laid out before took the slot the
                         ; game then decoded the face into, and a card first doubled the line)
  LDA #{GRACE}
  STA grace
  STZ left               ; the last line's page timer stopped (it laid this line's words out
  STZ linger             ; into rows never set up for it: scraps) and the window HIDDEN (winoff:
  JMP winoff             ; the game's state back) while the face is awaited - kept shown from the
                         ; last line, the game's window rebuild for this voice opcode mapped its
                         ; own BAT over our tiles and the band showed the last card at the left
                         ; edge over picture scraps (494, 190, 398, 606 ...). The rows' tiles NOT cleared: the game
                         ; may be decoding this line's face into them (Jamie's at the ending's
                         ; e0 was wiped); rowsel gives them back without clearing what came
lnow:
  JSR rowsel
  JSR clear              ; (before the window shows: its rows' tiles hold whatever was there)
  JSR winon
  ; fall through: the first page
page:
  LDA tbl                ; the page's first chunk, for a layout again
  STA ptbl
  LDA tbl+1
  STA ptbl+1
  LDA rem
  STA prem
  LDA rem+1
  STA prem+1
repage:
  JSR clear
  ; the template: two rows of spaces at col0
  LDA #0xFC
  STA MSG
  STZ MSG+1
  LDA #0xF9
  STA MSG+2
  LDA #1
  STA MSG+3
  LDX #4
{{F8ON}}
  LDA row0
  STA row
trow:
{{ROWBASE}}
  LDA #0xFB
  STA MSG,X
  INX
  LDA col0
  STA MSG,X
  INX
  LDA row
  STA MSG,X
  INX
  LDA #0xFE
  STA MSG,X
  INX
  LDA #{{ROWCOL}}        ; the row's colour: 1, the game's white (3 under the epilogue - EPI_COLOURS)
  STA MSG,X
  INX
  LDA width
  STA cnt
tpad:
  LDA #0x89
  STA MSG,X
  INX
  LDA #0x40
  STA MSG,X
  INX
  DEC cnt
  BNE tpad
  INC row
  LDA row
  SEC
  SBC row0
  CMP {{NROWS}}
  BNE trow
{{F8OFF}}
  LDA #0xFF
  STA MSG,X
  ; the chunks into the rows
  STZ cur
  STZ cells
  STZ pcells
  LDX #{{ROWBODY}}       ; the first row's body
  ; the name first on EVERY page of a card (with or without the face block: the epilogue runs
  ; without it and its cues need the names) - a voiced page shows its speaker's name or its
  ; portrait, never neither (a card's later pages had only the words: Luiz, 2026-10-18)
  LDA mode
  BNE chunk
  LDA schar
  BEQ chunk
  ORA #0x80              ; (the names block's characters carry PLAIN: a card drawn plain for
  JSR fname              ; want of the face block looks its name up too) the name into MSG at X, A = its cost
  STA cells
  STA pcells
chunk:
  LDA rem
  ORA rem+1
  BNE chunk1
  JMP pdone              ; the line's last page
chunk1:
  LDY #0
  JSR tfetch
  STA hdr
{{BREAKCHECK}}
  AND #0x1F
  STA n
  STA cnt                ; the cost: cells, plus one for a colour code
  LDA hdr
  AND #0xE0
  BEQ cost
  INC cnt
cost:
  LDA cells
  CLC
  ADC cnt
  CMP width
  BEQ fits
  BCC fits
  ; the next row
  INC cur
  LDA cur
  CMP {{NROWS}}
  BNE nextrow
  JMP pdone              ; the page is full: the chunk waits
nextrow:
  STZ cells
{{NEXTROW}}
fits:
  LDA cells
  CLC
  ADC cnt
  STA cells
  LDA pcells
  CLC
  ADC cnt
  STA pcells
  LDA hdr
  AND #0xE0
  BEQ pairs
  LSR
  LSR
  LSR
  LSR
  LSR
  PHA
  LDA #0xFE
  STA MSG,X
  INX
  PLA
  STA MSG,X
  INX
pairs:
  LDA n
  ASL
  STA cnt
  LDY #1
copy:
  JSR tfetch
  STA MSG,X
  INX
  INY
  DEC cnt
  BNE copy
  ; consumed: 1 + 2n bytes
  LDA n
  ASL
  INC
  JSR eat
  JMP chunk
pdone:
  LDA rem
  ORA rem+1
  STA more
  BEQ ptime
  ; left = pcells * fpc >> 8
  JSR mul
ptime:
  JSR show
  BNE pshown
  LDA #1
  STA pend
pshown:
  RTS
; ---- left = pcells * fpc / 256 (fpc 8.8): a 16 x 8 product's middle bytes ----
{{MULCODE}}
; ---- the window: shown, its BAT rows 0-1 blank (their tiles may hold a face's bitmap) ----
; the game keeps the window's BAT (rows 43-50, columns 32-63) blank while its window is closed
; and maps tiles 0x700-0x7FF when it opens it; a line maps rows 2-3 only, and puts back what
; was there (the game's mapping when its window was shown, else blank): n = 0 blank, 1 the
; game's mapping, 2 ours
winon:
  LDA linger             ; still shown from the last line: the game's state kept from then
  BNE winon0
  LDA WIN
  STA win
winon0:
  STZ linger
  LDA #{WIN_SHOWN}
  STA WIN
  LDA #1
  STA WIN_DIRTY
  STA LAYOUT             ; the game's window-open routine sets it: the raster sections follow
  LDA #0xFF
  STA CURSOR             ; as the voice opcode leaves it: no page-wait marker at the text cursor
{{EPION}}
  LDA #2
  STA n
  BRA wbat
; ---- Z clear when the game took its window since the line began: a list built (its count
; changed from lst) or a message of its own up ----
gtake:
  LDA LIST_COUNT         ; (carry set: a list - its menu, built in a hidden window; clear: a
  CMP lst                ; message, drawn in the window it opens)
  SEC
  BNE gtake1
  CLC
  LDA MSG_BUSY
gtake1:
  RTS
winoff:
  STZ MSG                ; (the page gone from the buffer: the harness reads it)
  LDA WIN
  CMP #{WIN_SHOWN}
  BNE winoff1            ; the game changed the window under the line (the hospital list's
  LDA win                ; keyboard opens with WIN 0 while Catherine's line is up): its value stays
  STA WIN
winoff1:
  LDA #1
  STA WIN_DIRTY
  STA LAYOUT
{{EPIOFF}}
  LDA #0                 ; the game's mapping back when its window was open, else blank
  LDX win
  CPX #{WIN_SHOWN}
  BNE wbat0
  INC
wbat0:
  STA n
wbat:
{{G30S}}
  LDA #2                 ; the game's own guard: a nested vblank handler takes its short path
  STA 0x30               ; while $30 is set (no walker - it moves MAWR - as under the renderer's
                         ; long passes); interrupts stay on for the raster sections (a SEI over
                         ; these writes missed their lines and tore the frame). $30 is 0 here:
                         ; the stub runs from the handler's $1C part, after its STZ $30
  JSR 0x4776             ; the VDC's increment to 1
  LDA #{WIN_BAT & 0xFF}
  STA mlo
  LDA #{WIN_BAT >> 8}
  STA mhi
  STZ hdr                ; the first tile: 0x700
  STZ cnt                ; the BAT row 0..7
wrow:
  LDA #0
  STA VDC_SHADOW
  STA a:VDC_SEL
  LDA mlo
  STA a:VDC_LO
  LDA mhi
  STA a:VDC_HI
  LDA #2
  STA VDC_SHADOW
  STA a:VDC_SEL
{{WROW}}
  LDY #32
wcol:
  LDA n
  BEQ wblank
  CMP #2
  BNE wmap
{{WOURS}}
wmap:
  LDA hdr
  STA a:VDC_LO
  LDA #0xF7
  STA a:VDC_HI
  BRA wnext
wblank:
  LDA #{BLANK & 0xFF}
  STA a:VDC_LO
  LDA #{BLANK >> 8}
  STA a:VDC_HI
wnext:
  INC hdr
  DEY
  BNE wcol
  LDA mlo
  CLC
  ADC #64
  STA mlo
  BCC wsame
  INC mhi
wsame:
  INC cnt
  LDA cnt
  CMP #8
  BEQ wdone
  JMP wrow
wdone:
{{G30E}}
  RTS
{{ROWCODE}}
; ---- zero the tiles of the line's rows ----
clear:
{{G30S}}
  LDA #2                 ; (as wbat: $30 set, interrupts on)
  STA 0x30
  JSR 0x4776             ; the VDC's increment to 1
  LDA #0
  STA VDC_SHADOW
  STA a:VDC_SEL
  STA a:VDC_LO
  JSR regbase            ; the region's VRAM: 0x4000 + treg * 0x800
  STA a:VDC_HI
  LDA #2
  STA VDC_SHADOW
  STA a:VDC_SEL
{{CLEARN}}
  LDY #0
cloop:
  STZ a:VDC_LO
  STZ a:VDC_HI
  INY
  BNE cloop
  DEX
  BNE cloop
{{G30E}}
  RTS
; ---- hand MSG to the row loop (drawn from the main loop): A = 1 taken ----
show:
  LDA DRAWING
  BNE refused
  TMA #0x08
  STA mpr3
  LDA 0xFE
  STA dl
  LDA 0xFF
  STA dl+1
  LDA #2
  JSR 0x43AA             ; the text bank at $6000
  LDA #lo(MSG)
  STA 0xFE
  LDA #hi(MSG)
  STA 0xFF
  JSR 0x63A5             ; $3471 = the message, no delay, $3470 = 1
  LDA dl
  STA 0xFE
  LDA dl+1
  STA 0xFF
  LDA mpr3
  TAM #0x08
  LDA #1
  RTS
refused:
  LDA #0
  RTS
{{GWCODE}}
regbase:                 ; A = the high byte of region treg's VRAM
  LDA treg
  ASL
  ASL
  ASL
  CLC
  ADC #0x40
  RTS
; ---- Z = the checksum at MAGIC is the loaded module's ----
; ---- the character's name from the module's names block into MSG at X: `fe colour` then
; the pairs; A = the cost (cells + 1), 0 for a character without one; X advanced ----
fname:
  STA hdr                ; the character
  LDA tbl
  STA ctbl
  LDA tbl+1
  STA ctbl+1
  LDA ntbl
  STA tbl
  LDA ntbl+1
  STA tbl+1
nfind:
  LDY #0
  JSR tfetch             ; the entry's character, 0 = the end
  BEQ nnone
  CMP hdr
  BEQ ngot
  LDY #2
  JSR tfetch             ; cells
  ASL
  CLC
  ADC #3
  STA mlo
  STZ mhi
  JSR adv
  BRA nfind
nnone:
  LDA #0
  BRA ndone
ngot:
  LDA #0xFE
  STA MSG,X
  INX
  LDY #1
  JSR tfetch             ; colour
  STA MSG,X
  INX
  LDY #2
  JSR tfetch             ; cells
  STA cnt
  ASL
  STA n
  LDY #3
ncopy:
  JSR tfetch
  STA MSG,X
  INX
  INY
  DEC n
  BNE ncopy
  LDA cnt
  INC
ndone:
  PHA
  LDA ctbl
  STA tbl
  LDA ctbl+1
  STA tbl+1
  PLA
  RTS
; ---- module reads through FETCH ----
mfetch:
  LDA #lo(MAGIC)
  STA 0x90
  LDA #hi(MAGIC)
  STA 0x91
  STY 0x92
  JMP FETCH
tfetch:
  LDA tbl
  STA 0x90
  LDA tbl+1
  STA 0x91
  STY 0x92
  JMP FETCH
eat:                     ; A bytes of the table consumed: tbl past them, rem less them
  STA mlo
  STZ mhi
  JSR adv
  SEC
  LDA rem
  SBC mlo
  STA rem
  BCS eat1
  DEC rem+1
eat1:
  RTS
adv:                     ; tbl += mhi:mlo
  CLC
  LDA tbl
  ADC mlo
  STA tbl
  LDA tbl+1
  ADC mhi
  STA tbl+1
  RTS
{{EPI}}
entry:                   ; the trampoline's target, beside the signature (A = AD_STAT kept)
{{ENTRYCHK}}
  JMP stat
sig:
  .byte 0x53, 0x42, 0x33         ; "SB3": the last bytes of the block, so its presence means all of it is in
"""

# The ending's epilogue runs on a scene block with rec 110 gone: no window section in the
# raster layout (the game's window code left with rec 110) and the window's palette 15
# blacked to hide the wallpaper tile in the band. The module stub adds, while a cue is up,
# a section of its own at line 192 (the picture is 192 px) showing the text rows, another
# at line 0 with the picture's scroll (the game's own top section's, else 0, 0 - nothing
# else resets it at the frame's top), and writes the text colours into palette 15's entries
# the wallpaper tile does not use (3 white, 5 yellow, 6 green - 1, 2, 4, 8, 10 are its, and
# it sits in the band's own rows and under the display's last lines): the ending's cues are
# built in those colours (EPI_COLOURS), the row template's colour too (ROWCOL).
EPI_SOURCE = """
epion:                   ; from winon (twice a line, at times): our sections unless the game has
  LDA epi                ; a window section of its own
  BNE episet
  LDA 0x390F
  BNE epidone
  LDA #1
  STA epi
episet:
  LDA #1
  STA 0x390E             ; slot 14: the picture's scroll from line 0 - nothing else puts it back
  STA 0x390F             ; after ours (slot 15) under the 192-px picture
  LDA #0xF8              ; rcr 0xF8 = 248: the switch shows at line 192 (as the game's own 264
  STA 0x392F             ; puts its bottom section at 200: eight under the value less 64)
  STZ 0x393F
  LDA #0x40
  STA 0x392E             ; rcr 0x40: line 0
  STZ 0x393E
  LDA #0x58              ; by 0x158: the window's first two 16-px rows at lines 192-223
  STA 0x39BF
  LDA #1
  STA 0x39CF
  LDA #0xF7              ; bx 0x00F7: the text's first cell at x = 8 as in the game's scenes
  STA 0x398F             ; (their band's 0xFF sits 8 px further left under this block's timing)
  STZ 0x399F
episcroll:               ; slot 14's scroll: the game's own top section's (a slot below 14
  STZ 0x398E             ; enabled: the picture's scroll of the moment), else (0, 0)
  STZ 0x399E
  STZ 0x39BE
  STZ 0x39CE
  LDX #13
epis1:
  LDA 0x3900,X
  BNE epis2
  DEX
  BPL epis1
epidone:
  RTS
epis2:
  LDA 0x3980,X
  STA 0x398E
  LDA 0x3990,X
  STA 0x399E
  LDA 0x39B0,X
  STA 0x39BE
  LDA 0x39C0,X
  STA 0x39CE
  RTS
epioff:                  ; from winoff
  LDA epi
  BEQ epidone
  STZ epi
  STZ 0x390E
  STZ 0x390F
  RTS
epitick:                 ; every pass while the line is up: the text colours (a fade may
  LDA epi                ; have rewritten them), the picture's scroll of the moment
  BEQ epidone
  LDA shown
  BEQ epidone
  JSR episcroll
  LDA #0xF3              ; palette 15, entry 3: white (the text's, EPI_COLOURS)
  STA a:0x0402
  STZ a:0x0403
  LDA #0xFF
  STA a:0x0404
  LDA #1
  STA a:0x0405
  LDA #0xF5              ; entries 5 and 6: yellow (the names'), green (Gillian's)
  STA a:0x0402
  STZ a:0x0403
  LDA #0xF8
  STA a:0x0404
  LDA #1
  STA a:0x0405
  LDA #0xC3
  STA a:0x0404
  LDA #1
  STA a:0x0405
  RTS
"""

# The face block: rec 110's free tail at MPR5. Entry points at fixed offsets
# (a jump table the stub and the tail call): +0 fstart (A = the character),
# +3 the "FL1" signature, +6 fscan (A = 1: the layout changed), +9 fsprite
# (the sprite table fixed, from the walker's exit), +12 spare, +15 sreg (a
# byte: the speaker's face region, FF none), +16 borrow, +17 parked, +18
# fpres, +21 vcopy (A = a region: its bitmap into region X's), +24 rmatchraw
# (A = a region: the character its own bitmap carries).
FACE_SOURCE = f"""
MSG = {MSG}
VDC_SEL = 0x0000
VDC_LO = 0x0002
VDC_HI = 0x0003
VDC_SHADOW = 0xF7
OBJ_LIVE = 0x2A40                ; the object tables (64 objects; the walker at bank 1 $6000 draws them)
OBJ_XL = 0x27C0
OBJ_XH = 0x2800
OBJ_YL = 0x2880
OBJ_YH = 0x28C0
OBJ_FRAME = 0x2DC0
OBJ_FLAGS = 0x3000               ; bit 1: the walker skips the object (the game's own hide)
OBJ_FRAMES = 0x2700              ; lo; +0x40 hi
OBJ_FBANK = 0x2EC0
OBJ_LIST = 0x2F00                ; lo; +0x40 hi; bank at 0x2F80
PTR = 0x90
VOICE_BANK = {{VOICE_BANK}}      ; + [$3F80]: the voice bank, mapped at MPR3 to read the signatures ...
SIG_BANK = {{SIG_BANK}}          ; + [$3F80]: rec 54's fourth bank (0x85), where the signatures sit
SIGS = {{SIGS}}                  ; ... [char][four words] x nsigs, in one of its free runs (overflow_tables)
  JMP fstart
  .byte 0x46, 0x4C, 0x31         ; "FL1"
  JMP fscan
  JMP fsprite                    ; +9: the sprite table fixed for the layout (from the walker's exit)
  JMP fprepare                   ; +12: prepare the freshly built SAT before upload
sreg:   .byte 0xFF               ; +15: the speaker's region, FF none
borrow: .byte 0xFF               ; +16: the region whose tiles hold the text, its face kept off, FF none
parked: .byte 0xFF               ; +17: the region holding the borrowed one's bitmap meanwhile, FF none
  JMP fpres                      ; +18
  JMP vcopy                      ; +21: region A's bitmap copied into region X's
  JMP rmatchraw                  ; +24: A = a region: the character its own bitmap carries (parked or not)
pfrom:  .byte 0xFF, 0xFF, 0xFF   ; +27..+29: the regions whose bitmaps are parked (two hidden faces', the speaker's)
pto:    .byte 0xFF, 0xFF, 0xFF   ; +30..+32: their slots, FF none
occ:    .byte 0                  ; +33: bit r: region r has a face-like object on the band, known or not
schar:  .byte 0
seen:   .byte 0                  ; bit r: region r had a face-like object at the last scan (occ)
used:   .byte 0                  ; bit r: any live object draws from region r (a picture piece's too)
cachedsafe: .byte 0              ; known dormant portrait bitmap, with no live object using it
lastsreg: .byte 0xFF
present: .byte 0, 0, 0, 0, 0, 0, 0, 0     ; per region (0x800 words from VRAM 0x4000; 6-7 are the text rows'
fx:     .byte 0, 0, 0, 0, 0, 0, 0, 0     ; tiles): a portrait object on the band draws from it; its leftmost x
rchar:  .byte 0, 0, 0, 0, 0, 0, 0, 0     ; the character whose signature its bitmap carries, 0 none
n:      .byte 0
n2:     .byte 0
hdr:    .byte 0
tmp:    .byte 0
tmp2:   .byte 0
mlo:    .byte 0
mhi:    .byte 0
sigoffs: .byte {SIG_OFFS[0]}, {SIG_OFFS[1]}, {SIG_OFFS[2]}, {SIG_OFFS[3]}
words:   .byte 0, 0, 0, 0
wordsh:  .byte 0, 0, 0, 0
scount:  .byte 0
spritepass: .byte 0
spriteleft: .byte 0xFF
nsigs:   .byte {{NSIGS}}         ; (every label an instruction names comes before the code:
                                 ; the assembler sizes a forward reference as zero page)
; per object: its face region + 1 (0: not a face)
oreg:   .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
; ---- a new line: A = its character ----
fstart:
  STA schar
  STZ seen
  LDA #0xFF
  STA sreg
  STA lastsreg
  RTS
; ---- the face objects, by region: A = 1 when the layout changed (a region came or went,
; the speaker's face was found or lost) ----
; A face is an object on the window band (y from 0xA0: the Mechanic room's wall photo is
; Mika's bitmap up in the picture) whose current sprite group draws patterns 0x200-0x3FF
; (a bitmap at VRAM 0x4000 + region * 0x800: the portraits sit at 0x6000 on, the ending's
; at 0x4000); its region's bitmap names it by a KNOWN signature (rchar) - an unknown one
; (not in faces.json, or still decoding) is never the speaker's and is hidden like the rest
; while a line is up (until dev8 it was left where the game put it, over the text).
; An object on a hidden frame keeps its last verdict, one that is gone forgets it.
fscan:
  LDA 0x30               ; prevent a nested walker from reentering the scanner
  PHA
  LDA #2
  STA 0x30
  JSR fscanbody
  TAX
  PLA
  STA 0x30
  TXA
  RTS
fscanbody:
  LDX #7
fsclr:
  STZ present,X
  STZ rchar,X
  LDA #0xFF
  STA fx,X
  DEX
  BPL fsclr
  STZ used
  STZ cachedsafe
  LDX #0
oloop:
  LDA OBJ_LIVE,X
  BNE oexist
  STZ oreg,X             ; gone
  JMP onext
oexist:
  JSR ochase
  BEQ ohidden
  STA oreg,X
  JSR umark              ; its region is in use, on the band or not
  LDA OBJ_FLAGS,X        ; hidden by the game (its own flag: the walker skips it) - not a face
  AND #2                 ; on the band (the act-2 Chief's room keeps Gillian's ready, hidden,
  BNE oscene             ; through his lines: the plain layout with his name there)
  LDA OBJ_YH,X
  BNE oscene
  LDA OBJ_YL,X
  CMP #0xA0
  BCS oface
oscene:
  STZ oreg,X
  JMP onext
ohidden:
  LDA oreg,X
  BNE ohid1
  JMP onext
ohid1:
  JSR umark
oface:
  LDA oreg,X
  DEC
  TAY
  LDA #1
  STA present,Y
  LDA OBJ_XH,X
  BNE onext
  LDA OBJ_XL,X           ; the region's leftmost x
  CMP fx,Y
  BCS onext
  STA fx,Y
onext:
  INX
  CPX #64
  BEQ oscanned
  JMP oloop
oscanned:
  ; each region with objects: the character its bitmap carries (four words against the
  ; signatures); a region nobody is known for is never the speaker's, but its tiles are
  ; taken (occ): text written there shows in its sprites
  STZ tmp                ; the region
  STZ n                  ; the known bits
  STZ occ
rloop:
  LDX tmp
  LDA present,X
  BNE rhas
  CPX #6                 ; the text regions (6, 7): a known face's bitmap there with no object
  BCC rgnext0            ; drawing it is still the game's - it brings the objects back without
  JSR rmatch             ; decoding it again (the factory's Metal Gear) - so the region counts
  BEQ rgnext0            ; as in use and the rows go elsewhere
  LDA #0x40
  LDX tmp
  CPX #6
  BEQ cachebit
  ASL
cachebit:
  STA tmp2
  AND used               ; live non-band picture pieces must never be borrowed
  BNE cachemark
  LDA tmp2
  ORA cachedsafe
  STA cachedsafe
cachemark:
  LDA tmp
  INC
  JSR umark
rgnext0:
  JMP rgnext
rhas:
  JSR rmatch             ; A = the character, 0 none
  LDX tmp
  STA rchar,X
  PHA
  LDA #1
  CPX #0
  BEQ rbit0
rsh0:
  ASL
  DEX
  BNE rsh0
rbit0:
  STA tmp2
  ORA occ
  STA occ
  PLA
  BNE rknown
  LDX tmp
  STZ present,X
  JMP rgnext
rknown:
  LDA tmp2
  ORA n
  STA n
rgnext:
  INC tmp
  LDA tmp
  CMP #8
  BNE rloop
  ; the speaker's region: the one carrying the speaker
  LDA #0xFF
  STA sreg
  LDA schar
  BEQ rsdone
  LDX lastsreg           ; the region found earlier in the line stays while it carries the
  BMI rsp0               ; speaker: a decode into another region that reads as the same
  LDA rchar,X            ; character mid-line (Harry's drunk scene: region 7 under Metal
  CMP schar              ; Gear's objects) took the face there - a broken portrait on the left
  BEQ rsfound
rsp0:
  LDX #0                 ; the lowest region carrying the speaker: a later decode into a higher
rsp:                     ; one (7, under Metal Gear's objects in Harry's drunk scene) is no
  LDA rchar,X            ; face of his, and a two-region face takes its first half (4 of 4/5)
  CMP schar
  BNE rsp1
rsfound:
  STX sreg
  BRA rsdone
rsp1:
  INX
  CPX #8
  BNE rsp
rsdone:
  ; changed: the occupied set or the speaker's region
  LDA occ
  CMP seen
  BNE rchg
  LDA sreg
  CMP lastsreg
  BNE rchg
  LDA #0
  RTS
rchg:
  LDA occ
  STA seen
  LDA sreg
  STA lastsreg
  LDA #1
  RTS
; ---- A = a region + 1: its bit into used ----
umark:
  TAY
  LDA #1
um1:
  DEY
  BEQ um2
  ASL
  BRA um1
um2:
  ORA used
  STA used
  RTS
; ---- region tmp's character: its bitmap's four words against every signature; A = char, 0 none ----
; (the VDC: the region's words at 0x4000 + region * 0x800 + offset)
rmatchraw:
  STA tmp
  LDX #0xFF
  STX tmp2               ; the region's own bitmap
  BRA rmatch1
rmatch:                  ; (tmp = the region, set by the caller)
  LDX #0xFF              ; a parked region's bitmap sits in its slot meanwhile: that is the
  STX tmp2               ; face the region holds (the speaker's, when it speaks next)
  LDX #2
rm1:
  LDA tmp
  CMP pfrom,X
  BNE rm2
  LDA pto,X
  STA tmp2
rm2:
  DEX
  BPL rm1
rmatch1:
  JSR 0x4776             ; the VDC's increment to 1 (the game leaves 64 after a column write)
  LDY #0
mword:
  LDA sigoffs,Y
  STA mlo
  LDA tmp2               ; the region to read: the slot, else the region itself
  BPL mword1
  LDA tmp
mword1:
  ASL
  ASL
  ASL
  CLC
  ADC #0x40
  STA mhi
  PHY
  JSR vread
  PLY
  LDA n2
  STA words,Y
  LDA hdr
  STA wordsh,Y
  INY
  CPY #4
  BNE mword
  ; against every signature (in rec 54's fourth bank, mapped at MPR3 for the loop; the
  ; pointer in FETCH's zero-page pair)
  TMA #0x08
  PHA
  LDA #SIG_BANK
  JSR 0x43AA
  LDA #lo(SIGS)
  STA PTR
  LDA #hi(SIGS)
  STA PTR+1
  LDA nsigs
  STA scount
msig:
  LDA scount
  BNE msig0
  LDA #0
mdone:
  TAX
  PLA
  TAM #0x08
  TXA
  RTS
msig0:
  STZ tmp2
mcmp:
  LDA tmp2
  ASL
  INC
  TAY                    ; Y = 1 + 2i
  LDA (PTR),Y
  LDX tmp2
  CMP words,X
  BNE mskip
  INY
  LDA (PTR),Y
  CMP wordsh,X
  BNE mskip
  INC tmp2
  LDA tmp2
  CMP #4
  BNE mcmp
  LDY #0
  LDA (PTR),Y            ; the entry's character
  BRA mdone
mskip:
  CLC
  LDA PTR
  ADC #9
  STA PTR
  BCC msig1
  INC PTR+1
msig1:
  DEC scount
  BRA msig
; ---- object X's region + 1 from the pattern of its first sprite, 0 when it draws none or is no face ----
; (the walker's own chase: frame entry = frames + 4 * frame, its first byte an index into the
; list's pointer table unless bit 7; the group starts with a count, then 6-byte sprites
; `flags dy dx patlo pathi attr` - a record with flags bit 6 is a jump to bytes 1-2)
ochase:
  LDA OBJ_FRAME,X
  CMP #0xFF
  BNE oc1
  LDA #0
oc1:
  STZ tmp2
  ASL
  ROL tmp2
  ASL
  ROL tmp2
  CLC
  ADC OBJ_FRAMES,X
  STA PTR
  LDA tmp2
  ADC OBJ_FRAMES+0x40,X
  STA PTR+1
  LDA OBJ_FBANK,X        ; the frames' bank
  JSR mapptr
  LDY #0
  LDA (PTR),Y
  BMI ocnone
  ASL
  TAY
  LDA OBJ_LIST,X
  STA PTR
  LDA OBJ_LIST+0x40,X
  STA PTR+1
  LDA OBJ_LIST+0x80,X    ; the list's bank ($2F80)
  JSR mapptr
  LDA (PTR),Y
  CLC
  ADC OBJ_LIST,X
  STA tmp
  INY
  LDA (PTR),Y
  ADC OBJ_LIST+0x40,X
  STA PTR+1
  LDA tmp
  STA PTR
  LDA OBJ_LIST+0x80,X
  JSR mapptr
  LDY #1                 ; past the count
ocsp:
  LDA (PTR),Y
  AND #0x40
  BEQ ocreal
  INY
  LDA (PTR),Y
  STA tmp
  INY
  LDA (PTR),Y
  STA PTR+1
  LDA tmp
  STA PTR
  LDA OBJ_LIST+0x80,X
  JSR mapptr
  LDY #0
  BRA ocsp
ocreal:
  INY
  INY
  INY
  LDA (PTR),Y            ; pattern low
  STA tmp
  INY
  LDA (PTR),Y            ; pattern high: bits 4-6 -> 2 or 3 (VRAM 0x4000-0x7FFF)
  AND #0x70
  CMP #0x20
  BEQ oc2
  CMP #0x30
  BNE ocnone
oc2:
  AND #0x10              ; 0x10 for the 0x6000 half
  LSR
  LSR
  STA tmp2               ; 4 or 0
  LDA tmp
  LSR
  LSR
  LSR
  LSR
  LSR
  LSR
  ORA tmp2
  INC
  RTS
ocnone:
  LDA #0
  RTS
; A = a bank (relative to $3F80), PTR = a pointer in the game's $8000-$DFFF window over it:
; the page mapped at MPR6 and PTR moved to $C000-$DFFF
; (a pointer under $6000 is RAM or stage 2, read as is; $6000-$7FFF is bank 1, the
; walker's own MPR3 - the text bank sits there at our hook)
mapptr:
  STA tmp2
  LDA PTR+1
  LSR
  LSR
  LSR
  LSR
  LSR
  CMP #3
  BCC mdirect
  BNE mwin
  LDA #1
  BRA mmap
mwin:
  SEC
  SBC #4
  CLC
  ADC tmp2
mmap:
  CLC
  ADC 0x3F80
  TAM #0x40
  LDA PTR+1
  AND #0x1F
  ORA #0xC0
  STA PTR+1
mdirect:
  RTS
; ---- the sprite table (VRAM 0x1000: 64 entries of [y, x, pattern, attr]) fixed right after
; the walker built it from the object tables, before the vblank's transfer takes it: on the
; window band (y from 0xC0 with the table's 64 offset: a face's top cells sit above its
; object's y) a sprite drawing from the speaker's region moves left with its face (its
; region's left edge onto FACE_X, the same column for every face), one drawing from any
; other region (0-7, patterns 0x200-0x3FF: the portraits' 4-7, the ending's 0-3; the
; picture's pieces sit lower) is taken off (x 0). The game's own tables are never touched: its script reads them and took other
; paths when they were (the faces moved off the screen, the ruins' end skipped its wait for
; the CD track and opened the menu into our rows; hidden by the object flag, the act-2 recap
; never asked for its second track, and Metal Gear hidden was no Use Metal Gear on the verb
; menu) - and there is nothing to put back at a line's end: the next pass draws the game's
; own layout. The VDC is left as the walker leaves it - MAWR at the table's end, the data
; port selected: its caller writes on from there (left inside the table, those words sent
; the reception's script into the same skipped wait). ----
fprepare:
  LDA 0x26F3             ; queued or preloaded voice: speaker not resolved yet
  ORA 0x26F7
  BEQ fpscan
  LDA sreg
  PHA
  LDA #0xFF
  STA sreg
  JSR fsprite
  PLA
  STA sreg
  RTS
fpscan:
  LDA PTR
  PHA
  LDA PTR+1
  PHA
  LDA seen               ; leave change detection for the subtitle layout hook
  PHA
  LDA lastsreg
  PHA
  JSR fscan
  PLA
  STA lastsreg
  PLA
  STA seen
  PLA
  STA PTR+1
  PLA
  STA PTR
  JMP fsprite
fsprite:
  STZ spritepass
  LDA #0xFF
  STA spriteleft
fsread:
  JSR 0x4776             ; the increment to 1
  LDA #1                 ; MARR = 0x0FFF: a word early (the buffer lags)
  STA VDC_SHADOW
  STA a:VDC_SEL
  LDA #0xFF
  STA a:VDC_LO
  LDA #0x0F
  STA a:VDC_HI
  LDA #2
  STA VDC_SHADOW
  STA a:VDC_SEL
  LDA a:VDC_HI           ; the dummy read
  LDX #0
fsl:
  LDA a:VDC_LO           ; y
  STA mlo
  LDA a:VDC_HI
  STA mhi
  LDA a:VDC_LO           ; x
  STA n
  LDA a:VDC_HI
  STA n2
  LDA a:VDC_LO           ; the pattern code
  STA hdr
  LDA a:VDC_HI
  STA tmp2
  LDA a:VDC_LO           ; the attributes (as they are)
  LDA a:VDC_HI
  LDA tmp2
  AND #0xFE
  CMP #2                 ; codes 0x200-0x3FF: the regions (the portraits' 4-7 at 0x300 on,
  BNE fsn0               ; the ending's at 0x4000 in 0-3 - the picture's pieces sit lower)
  LDA mhi                ; on the band: y from 0xC0 (10 bits)
  AND #3
  BNE fsb
  LDA mlo
  CMP #0xC0
  BCS fsb
fsn0:
  JMP fsn
fsb:
  LDA tmp2               ; the region: bit 0 of the code's high byte, bits 7-6 of the low
  AND #1
  ASL
  ASL
  STA tmp
  LDA hdr
  LSR
  LSR
  LSR
  LSR
  LSR
  LSR
  ORA tmp
  STA tmp
  LDA 0x351D             ; recap page borders also use sprites below the picture
  CMP #5
  BNE fsregion
  LDY tmp
  CPY #6                 ; 6/7 hold the recap's text rows: whatever draws from them
  BCS fsregion           ; draws our text (a face kept from the last module, #85)
  LDA rchar,Y            ; elsewhere only identified portraits may be moved or hidden
  BNE fsregion
  JMP fsn
fsregion:
  LDA tmp                ; the speaker's: its region, and its pair partner (4/5, 6/7) when that
  EOR sreg               ; carries the same character - a face drawn from two regions at once,
  CMP #2                 ; Gillian's scream at the ruins' bomb (#92). Not any region reading as
  BCS fsreg1             ; the speaker: Harry's region 4 stayed in the middle over the text
  LDY tmp                ; while region 7 read as him too. (sreg FF reads as far: hidden.)
  LDA rchar,Y
  LDY sreg
  CMP rchar,Y
  BEQ fsmeasure
fsreg1:
  JMP fshide
fsmeasure:
  LDA spritepass
  BNE fsplace
  LDA n2                 ; measure the actual cells, not the object's animation anchor
  BNE fsmeasureend
  LDA n
  CMP #32
  BCC fsmeasureend
  CMP spriteleft
  BCS fsmeasureend
  STA spriteleft
fsmeasureend:
  JMP fsn
fsplace:
  LDA sreg
  TAY                    ; the speaker's: its left edge onto FACE_X, every face the same
  LDA fx,Y               ; column (Metal Gear's native 32 and Gillian's 24 left one 8 pixels
  SEC                    ; from the other, a jump at every change of speaker)
  SBC #{FACE_X}
  STA tmp2               ; the shift, signed: its high byte in mlo (the entry's y, read already)
  LDA #0
  SBC #0
  STA mlo
  LDA #0                 ; MAWR = the entry's x
  STA VDC_SHADOW
  STA a:VDC_SEL
  TXA
  ASL
  ASL
  INC
  STA a:VDC_LO
  LDA #0x10
  STA a:VDC_HI
  LDA #2
  STA VDC_SHADOW
  STA a:VDC_SEL
  SEC
  LDA n
  SBC tmp2
  STA a:VDC_LO
  LDA n2
  SBC mlo
  STA a:VDC_HI
  CPY pfrom+2            ; its bitmap parked (four rows: the text has its region): the
  BNE fsn                ; sprite drawn from the slot - the pattern word follows the x
  LDA pto+2
  BMI fsn
  AND #3
  ASL
  ASL
  ASL
  ASL
  ASL
  ASL
  STA tmp
  LDA hdr
  AND #0x3F
  ORA tmp
  STA a:VDC_LO
  LDA #3                 ; codes 0x300-0x3FF: regions 4-7
  STA a:VDC_HI
  BRA fsn
fshide:
  LDA spritepass
  BEQ fsn
  LDA #0                 ; MAWR = the entry's x: 0, off the screen's left (the y is left as
  STA VDC_SHADOW         ; it is: the game reads the table back - y 0 there took Use Metal
  STA a:VDC_SEL          ; Gear off the act-2 verb menu)
  TXA
  ASL
  ASL
  INC
  STA a:VDC_LO
  LDA #0x10
  STA a:VDC_HI
  LDA #2
  STA VDC_SHADOW
  STA a:VDC_SEL
  STZ a:VDC_LO
  STZ a:VDC_HI
fsn:
  INX
  CPX #64
  BEQ fsdone
  JMP fsl
fsdone:
  LDA spritepass
  BNE fsfinish
  INC spritepass
  LDX sreg
  CPX #8
  BCS fsrepeat
  LDA spriteleft
  CMP #0xFF
  BEQ fsrepeat
  SEC
  SBC #32
  STA fx,X
fsrepeat:
  JMP fsread
fsfinish:
  LDA #0                 ; the VDC as the walker left it: MAWR at the table's end, the data
  STA VDC_SHADOW         ; port selected (its caller goes on writing there)
  STA a:VDC_SEL
  STZ a:VDC_LO
  LDA #0x11
  STA a:VDC_HI
  LDA #2
  STA VDC_SHADOW
  STA a:VDC_SEL
  RTS
; ---- A = the regions any object draws from, X = those with a face-like object on the band,
; as bits (bit 6: the tiles of the renderer's rows 0-1, bit 7: rows 2-3) ----
fpres:
  LDA occ
  ORA cachedsafe
  TAX
  LDA used
  RTS
; ---- region A's bitmap into region X's: the copy sits in bank 1's tail (mapped at MPR3
; round the call; the caller's bank there - the text bank from the stub - goes back after) ----
vcopy:
  STA tmp
  STX tmp2
  TMA #0x08
  PHA
  LDA #1
  JSR 0x43AA
  LDA tmp
  LDX tmp2
  JSR {{VCOPY}}
  PLA
  TAM #0x08
  RTS
vread:
  LDA #1
  STA VDC_SHADOW
  STA a:VDC_SEL
  LDA mlo
  SEC
  SBC #1
  STA a:VDC_LO
  LDA mhi
  SBC #0
  STA a:VDC_HI
  LDA #2
  STA VDC_SHADOW
  STA a:VDC_SEL
  LDA a:VDC_HI           ; the dummy read: MARR to mhi:mlo
  LDA a:VDC_LO
  STA n2
  LDA a:VDC_HI
  STA hdr
  RTS
"""

# Bank 1's tail: the walker hook sits on the object walker's exit ($6072 `JMP $43BE`,
# WALKER_HOOK): once the walker has built the sprite table from the objects, the face
# block's fsprite fixes it for the line's layout, while the resident stub shows a line with
# the face block in. The region copy (vcopyt) parks a borrowed region's bitmap and brings it
# back, called from the face block with this bank at MPR3.
TAIL_SOURCE = """
VDC_LO = 0x0002
VDC_HI = 0x0003
FETCH = {FETCH}
MAGIC = {MAGIC}
FACE = {FACE}
  BRA whook              ; (the variables first: a label used before its definition is zero page)
vt0:    .byte 0                  ; the copy's source and destination high bytes, its count
vt1:    .byte 0
vt2:    .byte 0
gwrote: .byte 0                  ; bit r: the game decoded a record into face region r (the loggers;
                                 ; the stub clears it when the module changes) - such a region holds
                                 ; the game's tiles for a sprite not live yet (the ruins' explosion
                                 ; in 4), never a parked bitmap
lvl:    .byte 0                  ; the record's vram
lvh:    .byte 0
vt3:    .byte 0                  ; $30 as the copy found it
; the walker's exit (its JMP $43BE): the sprite table it built fixed for the layout while a
; line is up (its grace and its linger too) or held between lines (the stub's fixon, #93)
; and the face block is in
whook:
  PHA
  TMA #0x20
  PHA
  LDA #{FACE_BANK}
  CLC
  ADC 0x3F80
  TAM #0x20
  LDA {SIG}              ; the resident stub is in (its signature is the bank's last bytes)
  CMP #0x53
  BNE wdone
  LDA {SIG}+1
  CMP #0x42
  BNE wdone
  LDA {SIG}+2
  CMP #0x33
  BNE wdone
  LDA {FACE}+3           ; and the face block's "FL1" at the bank's head (a scene block loading
  CMP #0x46              ; over rec 110 takes the head first)
  BNE wdone
  LDA {FACE}+4
  CMP #0x4C
  BNE wdone
  LDA {FACE}+5
  CMP #0x31
  BNE wdone
  LDA 0x26F3
  ORA 0x26F7
  BNE wfix
  LDA {SHOWN}
  BEQ wdone
  LDA {FACES}
  BEQ wdone
wfix:
  PHX
  PHY
  JSR {FACE}+12          ; one adjustment, before the SAT upload
  INC {FRAN}             ; (the stub's page waits for one such pass with its line's speaker)
  PLY
  PLX
wdone:
  PLA
  TAM #0x20
  PLA
  JMP 0x43BE             ; the walker's own exit
; ---- region A's 0x800 words (its face bitmap) into region X: MARR streams the source, MAWR
; the destination, both on the data port (reads come from the buffer MARR fills). $30 set for
; the game's handler as in the stub's writes, interrupts on. ~8 ms. Called from the face
; block's thunk with bank 1 at MPR3. ----
vcopyt:
  PHA
  TXA
  ASL
  ASL
  ASL
  CLC
  ADC #0x40
  STA vt1                ; the destination's high byte
  PLA
  ASL
  ASL
  ASL
  CLC
  ADC #0x40
  STA vt0                ; the source's
  LDA 0x30               ; ($30 as found: the row code calls this under its own guard)
  STA vt3
  LDA #2
  STA 0x30
  JSR 0x4776             ; the increment to 1
  LDA #0
  STA 0xF7
  STA a:0x0000
  STA a:VDC_LO
  LDA vt1
  STA a:VDC_HI
  LDA #1
  STA 0xF7
  STA a:0x0000
  LDA #0xFF              ; MARR a word early: the buffer lags (as the block's vread)
  STA a:VDC_LO
  LDA vt0
  DEC
  STA a:VDC_HI
  LDA #2
  STA 0xF7
  STA a:0x0000
  LDA a:VDC_HI           ; the dummy read
  LDA #8
  STA vt2
  LDY #0
vcl:
  LDA a:VDC_LO
  TAX
  LDA a:VDC_HI
  STX a:VDC_LO
  STA a:VDC_HI
  INY
  BNE vcl
  DEC vt2
  BNE vcl
  LDA vt3
  STA 0x30
  RTS
; the record handlers' `JSR $4763` before the decoder, logging first: the record's vram is in
; $0E/$0F (types 4 and 8) or four bytes back in the list at ($08),Y (the others); a decode
; into a face region (vram 0x4000-0x7FFF) marks the region in gwrote
logger:
  JSR 0x4763
  PHA
  PHX
  PHY
  DEY                    ; the record's vram: the two bytes before the stream pointer, which Y
  DEY                    ; is on (the handler read the vram straight into the VDC; $0E/$0F are
  DEY                    ; the decoder's own here - writing them there sent a face's decode
  LDA (0x08),Y           ; into the picture's tiles)
  STA lvl
  INY
  LDA (0x08),Y
  STA lvh
  JSR lg
  PLY
  PLX
  PLA
  RTS
logger48:
  JSR 0x4763
  PHA
  PHX
  PHY
  LDA 0x0E               ; types 4 and 8 keep the vram in $0E/$0F
  STA lvl
  LDA 0x0F
  STA lvh
  JSR lg
  PLY
  PLX
  PLA
  RTS
lg:
  LDA lvh                ; vram high: 0x40-0x7F are the face regions
  CMP #0x40
  BCC lgout
  CMP #0x80
  BCS lgout
  SEC
  SBC #0x40
  LSR
  LSR
  LSR
  TAX                    ; the region
  LDA #1
lgsh:
  DEX
  BMI lgset
  ASL
  BRA lgsh
lgset:
  ORA gwrote
  STA gwrote
lgout:
  RTS
{ROWTAIL}
"""

# The CD-DA clock and cue scan: in the voice bank (rec 54's first bank, 0x82 - loaded once,
# its 0x1800-0x1FFF never written again: OVERFLOW_RUNS), mapped at MPR3 by the stub round the
# call (the hook runs with the text bank there, and the module stub's own bank is MPR4). Its
# variables live in the same bank (CD RAM). FETCH maps the module's bank at MPR6 for a read.
# The hold's check (#93), in the voice bank with the clock (rec 110's tail is full): called by
# the stub while it has this bank at MPR3 for the clock. Carry clear when the last line's
# speaker has its face up and it is the band's only face-like object (a second face, known
# or not, and the game's own layout comes back - nothing is hidden between lines). fscan's
# rmatch maps this bank itself and puts MPR3 back.
FHOLD_SOURCE = """
fhold:
  JSR FACE+6             ; fscan: sreg and occ for now
  LDA FACE+15            ; sreg: the speaker's face found - alone on the band or not: between
  BMI fhoff              ; two lines only the last speaker's face shows (Lisa's beside Gillian's
  CLC                    ; at Freddy's flat came back at the game's columns after every line)
  RTS
fhoff:
  SEC
  RTS
"""
# The window kept visible while a line's rows are up (#91), beside fhold in the voice bank and
# called the same way. The game's raster chain walks its sections in slot order, each waiting
# for its own line: a picture's bottom section (slot 2 under the HQ return's city, then its
# closing wipe) on a line under the window's slots 14 and 15 left their lines passed - the
# window never showed and the HQ return's first three cards were never seen. Slots 14 and 15
# go one and two lines under the lowest enabled section 0-13 while it is at or under 14's own
# line, and get the game's lines back after (unless the game rewrote 14 meanwhile: its new
# layout stands). Switching the game's section off instead stalled its wipe - the scene waits
# on it. Carry set when the window's first BAT cell reads blank under our rows (a scene load
# cleared them: the reception's picture took "Going inside"): the stub maps them again.
VFIX_SOURCE = """
vmoved: .byte 0                  ; 14 and 15 are ours (moved)
vs:     .byte 0, 0, 0, 0         ; the game's own lines: 14 lo, 15 lo, 14 hi, 15 hi (as $392E-F, $393E-F)
vw14:   .byte 0                  ; the low byte we wrote into 14 (the game's rewrite reads different)
vml:    .byte 0                  ; the lowest enabled section 0-13's line
vmh:    .byte 0
; ---- every frame, from the stub with this bank at MPR3: the hold's check (#93), then vfix and,
; when it asks, the rows mapped again (the stub's wbat, n = 2) ----
keep:
  JSR {KLOST}              ; a borrowed face's region our rows left (four regions of faces)
  LDA {HOLD}               ; (zero while a line is up: line clears it)
  BEQ kp1
  JSR {GTAKE}              ; the game took its window: no hold
  BNE kpoff
  LDA {FACES}
  BEQ kpoff
  JSR {FHOLD}              ; the last speaker's face alone on the band
  BCC kp1
kpoff:
  STZ {HOLD}
kp1:
  LDA {SHOWN}              ; fixon = shown | hold: the walker hook fixes the sprite table while set
  ORA {HOLD}
  STA {FIXON}
  LDA {OWED}               ; a portrait line's wait for its face paid back: one frame more off
  BEQ kp2                  ; the page each frame (twice the pace) until it is, so the line's
  LDA {LEFT}+1             ; pages are all shown before its voice ends
  BNE kpay
  LDA {LEFT}
  CMP #3
  BCC kp2                  ; (the page about to turn: left as it is)
kpay:
  DEC {OWED}
  LDA {LEFT}
  BNE kpay1
  DEC {LEFT}+1
kpay1:
  DEC {LEFT}
kp2:
  JMP vfix
vfix:
  LDA {SHOWN}
  BEQ vfnot
  LDA {ROWSIN}
  BNE vfgo
vfnot:
  JMP vfrest
vfgo:
  LDA {GRACE}              ; a page up (not its face wait, not the linger) and the raster sections
  ORA {LINGER}             ; off: a picture scene set up after winon cleared $27 and the band
  BNE vfgo2                ; stayed dark (the Moscow map's 638 3f, 334's 'What?!', 590, cdda_462
  LDA 0x27                 ; cue 17). All eight BAT rows mapped again (ours, the rest blank: set
  BNE vfgo2                ; alone, $27 showed the game's own mapping over picture tiles - the
  LDA 0x351D               ; farewell's scraps, a91473e), then the sections on - not in the
  CMP #5                   ; recap (its pictures decode into the rows' tiles AFTER $27 drops:
  BEQ vfgo2                ; mapped at once, they came up as scraps), nor over rows whose tiles
  JSR {KCLEAN}             ; the new picture took (kclean: the farewell's close-ups decode into
  BNE vfgo2                ; them - the band stays dark there). (A list or message of the game's
                           ; ends the line in the same pass: takeover)
  LDA #2
  STA {N}
  JSR {WBAT}
  LDA #1
  STA 0x27
vfgo2:
  LDA vmoved
  BEQ vfsave
  LDA 0x392E             ; the game rewrote 14 (another layout): its values stand
  CMP vw14
  BEQ vfmax
  STZ vmoved
vfsave:
  .byte 0x73
  .word 0x392E, vs, 2
  .byte 0x73
  .word 0x393E, vs+2, 2
vfmax:
  STZ vml
  STZ vmh
  LDX #13
vfm1:
  LDA 0x3900,X
  BEQ vfm2
  LDA 0x3930,X
  CMP vmh
  BCC vfm2
  BNE vfm3
  LDA 0x3920,X
  CMP vml
  BCC vfm2
vfm3:
  LDA 0x3920,X
  STA vml
  LDA 0x3930,X
  STA vmh
vfm2:
  DEX
  BPL vfm1
  LDA vmh                ; at or under 14's own line: blocked
  CMP vs+2
  BCC vfback
  BNE vfmove
  LDA vml
  CMP vs
  BCC vfback
vfmove:
  LDA vml                ; 14 a line under it, 15 two
  CLC
  ADC #1
  STA 0x392E
  STA vw14
  LDA vmh
  ADC #0
  STA 0x393E
  LDA vml
  CLC
  ADC #2
  STA 0x392F
  LDA vmh
  ADC #0
  STA 0x393F
  LDA #1
  STA vmoved
  BRA vfbat
vfback:
  JSR vfrest
vfbat:
  RTS
vfrest:                  ; no line up: the game's lines back (unless it rewrote 14)
  LDA vmoved
  BEQ vfr1
  STZ vmoved
  LDA 0x392E
  CMP vw14
  BNE vfr1
  .byte 0x73
  .word vs, 0x392E, 2
  .byte 0x73
  .word vs+2, 0x393E, 2
vfr1:
  CLC
  RTS
"""
# The rows borrow a face's region with no free slot to park its bitmap in when four regions
# hold faces (the fortune teller's two, Gillian's and Metal Gear's in Altamira): the face keeps
# our last rows as its bitmap, and when a new line moves the rows elsewhere (rschange's
# release, `moving` set: no clear) its sprites drew scraps of text beside the game's own
# layout between the lines. klost, from keep every pass (voice bank at MPR3, rec 110 at MPR5),
# clears that region then - only the one the last rows had borrowed unparked, and only while
# it does not read as a known face (the game's decode is back) - so the face draws nothing
# until the game decodes it again. (A face the game decodes into it mid-line that faces.json
# does not know would be cleared too: no room left for a new-line check.) kslot, first, keeps
# a slot an object only now and then draws from out of the free ones.
KSTEP_MASK = 7                # kslot looks every 8th pass
KIDLE = 8                     # its looks (x 8 passes) a slot stays marked after its object went
KLOST_SOURCE = """
FACE = {FACE}
ktreg:  .byte 0xFF               ; the rows' region last pass, FF none
kbor:   .byte 0xFF               ; ... when it was a face's borrowed with no slot to park it in
kidle:  .byte 0                  ; passes slots 4 and 5 have had no object
kmark:  .byte 0                  ; the gwrote bits kslot set (the loggers' stay theirs)
kuse:   .byte 0
kold:   .byte 0
kcnt:   .byte 0                  ; passes, for KSTEP
kvh:    .byte 0                  ; kbat's VRAM read address (high byte)
; ---- a slot (4/5) an object draws from now and then is not free in between: the kobe-yaki
; stall's region 5 came and went every few frames, the page was laid out again each time (four
; rows with Metal Gear parked there, two without - the blinking text) and the object drew the
; parked bitmap. While an object uses a slot it is marked in the tail's gwrote (the regions
; the free slots avoid); after KIDLE passes with neither slot used, kslot's marks go. ----
kslot:
  INC kcnt               ; one pass in KSTEP: the object walk is not cheap, and the vblank
  LDA kcnt               ; handler's time is the scenes' (the videophone streams through it)
  AND #{KSTEP_MASK}
  BEQ ksgo
  RTS
ksgo:
  LDA #{KIDLE}           ; no line up: kslot's marks go at once (they only keep a line's own
  LDX {SHOWN}            ; layout steady: left over, they sent the rows of the next scene into
  BEQ ksoff              ; the game's text rows - Napoleon's password lost its N)
  JSR FACE+18            ; A = the regions in use (any object)
  AND #0x30
  STA kuse
  BEQ ksi
  STZ kidle
  BRA ksm
ksi:
  LDA kidle
  CMP #{KIDLE}
  BCS ksm
  INC kidle
  BRA ksm
ksoff:
  STA kidle
  STZ kuse
ksm:
  PHP                    ; the tail's gwrote, bank 1 at MPR4 a moment (MPR2 + 1, as the thunks)
  SEI
  TMA #0x10
  PHA
  TMA #0x04
  INC
  TAM #0x10
  LDA {GW4}
  STA kold
  LDA kidle
  CMP #{KIDLE}
  BCC ksadd
  LDA kmark              ; idle long enough: kslot's own marks go
  EOR #0xFF
  AND kold
  STZ kmark
  BRA ksput
ksadd:
  LDA kold               ; marked; kmark the bits that were not there
  EOR #0xFF
  AND kuse
  ORA kmark
  STA kmark
  LDA kold
  ORA kuse
ksput:
  STA {GW4}
  PLA
  TAM #0x10
  PLP
  RTS
; ---- the rows' BAT, every KSTEP pass of a line: a scene that redraws the window's BAT blank
; under our rows (the Queen Hospital's dark rooms, where Metal Gear's mahjong line never showed)
; gets them mapped again - only while no list or message of the game's owns the window (its
; BAT stands then; a re-map every 16 frames put Napoleon's question away, b4c8bd2) ----
kbat:
  LDA kcnt
  AND #{KSTEP_MASK}
  BNE kbx                ; (kslot counted this pass)
  LDA {SHOWN}
  BEQ kbx
  LDA {GRACE}            ; not in a face wait nor the linger: the rows hold the last line's words
  ORA {LINGER}           ; then, unmapped on purpose - mapped again here they came back 8 frames
  BNE kbx                ; after the line's end (r7's blinks)
  LDA {ROWSIN}
  BEQ kbx
  JSR {GTAKE}
  BNE kbx
  JSR kclean
  BNE kbdirty
  LDA #1                 ; MARR = the window's first cell
  STA 0xF7
  .byte 0x03, 1           ; ST0 #1 (the VDC's register, as STA a:0x0000)
  .byte 0x13, {WINBAT_LO}          ; ST1, ST2: its low and high byte
  .byte 0x23, {WINBAT_HI}
  LDA #2
  STA 0xF7
  .byte 0x03, 2           ; ST0 #2 (the VDC's register, as STA a:0x0000)
  LDA a:0x0002
  CMP #0x10               ; the game's blank (tile 0x110, any palette)
  BNE kbx
  LDA a:0x0003
  AND #0x0F
  DEC                    ; (palette 0x?1)
  BNE kbx
  LDA #2
  STA {N}
  JMP {WBAT}
kbdirty:                 ; a picture went into the rows' tiles under a shown line (the recap's
  STZ {N}                ; portraits after the band was lit again): the rows unmapped - a dark
  JMP {WBAT}             ; band, not a band of scraps
kbx:
  RTS
; ---- A = the plane-3 bits of the rows' region (Z set: clean - our text's colours are 1-7; a bit
; there is the game's own picture or face gone into the region: mapping our rows over it showed
; the tiles as a band of scraps - Act 3's start, Altamira, outside Queen Hospital, the farewell's
; close-ups) ----
kclean:
  STZ kold
  LDA {TREG}             ; a bit there is the game's own picture or face gone into the region -
  ASL                    ; its blank BAT stands (mapping our rows over it showed the tiles as
  ASL                    ; a band of scraps: Act 3's start, Altamira, outside Queen Hospital)
  ASL
  ADC #0x40
  STA kvh
  LDY #8                 ; words 8-15 (planes 2 and 3) of every sixteenth tile of the region
kbc1:
  LDA #1                 ; MARR
  STA 0xF7
  .byte 0x03, 1           ; ST0 #1 (the VDC's register, as STA a:0x0000)
  .byte 0x13, 8          ; ST1 #8
  LDA kvh
  STA a:0x0003
  LDA #2
  STA 0xF7
  .byte 0x03, 2           ; ST0 #2 (the VDC's register, as STA a:0x0000)
  LDX #8
kbc2:
  LDA a:0x0002
  LDA a:0x0003           ; plane 3 (the high byte; reading it moves MARR on)
  ORA kold
  STA kold
  DEX
  BNE kbc2
  INC kvh
  DEY
  BNE kbc1
  LDA kold
  RTS
klost:
  LDA {LINGER}           ; a line's text held after its voice (LINGER frames): when the faces on
  BEQ klg                ; the band change meanwhile - the game bringing the next speaker's in -
  JSR {FACE}+6           ; it goes now (the old words beside a new face, two faces: the oracle's
  BEQ klg                ; line-change failures, 2026-10-16)
  LDA #1
  STA {LINGER}
klg:
  JSR kslot
  JSR kbat
  LDA {ROWSIN}
  BNE kl2
  LDA #0xFF              ; no rows (released and cleared)
  STA ktreg
  STA kbor
  RTS
kl2:
  LDA {TREG}
  CMP ktreg
  BEQ klkeep
  LDX kbor               ; the rows moved: from a borrowed face's region?
  STA ktreg
  CPX #8
  BCS klkeep             ; (FF: none)
  PHX
  TXA
  JSR FACE+24            ; rmatchraw: A = the character the region's own bitmap carries
  PLX
  CMP #0
  BNE klkeep             ; a known face is back: the game's decode stands
  LDA {TREG}
  PHA
  LDA {NROWS}
  PHA
  STX {TREG}
  LDA #2                 ; one region: 2 x 4 x 256 words
  STA {NROWS}
  JSR {CLEAR}
  PLA
  STA {NROWS}
  PLA
  STA {TREG}
klkeep:
  LDA {PPK}                ; this pass's: the first pair's region when it has no slot
  BPL kln
  LDA {PSP}
  BRA kls
kln:
  LDA #0xFF
kls:
  STA kbor
  RTS
"""
CD_SOURCE = """
FETCH = {FETCH}
MAGIC = {MAGIC}
FACE = {FACE}
cdsig:  .byte 0x43, 0x4B         ; "CK": the block is in (the opening overwrites the voice bank, and
                                 ; rec 110 - the stub - comes back before rec 54 does)
; (the clock's variables before its code: a label used before it is defined assembles as
; a zero-page operand and the addresses shift)
cdstat: .byte 0
cdlast: .byte 0
cdwas:  .byte 0                  ; $2638 last frame
cdlive: .byte 0                  ; a track's frames are being counted
cdok:   .byte 0                  ; the module's table was checked at the track's start
cdtrack: .byte 0
cdpos:  .word 0                  ; frames since the track started
cdtbl:  .word 0                  ; the module's cue entries
cdmag:  .word 0                  ; the module's magic bytes when the table was read
cdent:  .word 0                  ; the cue for now (its len field), 0 none
cdcur:  .word 0                  ; the cue up
cdmode: .byte 0                  ; the line up is a CD-DA cue
ctbl:   .word 0
chdr:   .byte 0, 0, 0, 0, 0, 0, 0
; ---- a track starts (the resident stub's cdinit; A/X = the module's cue block): its magic
; bytes, its entries, cdok - here, beside the clock's variables (the voice bank at MPR3) ----
cdmg:
  LDA cdtbl
  STA 0x90
  LDA cdtbl+1
  STA 0x91
  STY 0x92
  JMP FETCH
cdini2:
  STA cdtbl
  STX cdtbl+1
  LDY #0
  JSR cdmg
  STA cdmag
  LDY #1
  JSR cdmg
  STA cdmag+1
  CLC
  LDA cdtbl
  ADC #4
  STA cdtbl
  BCC cdi3
  INC cdtbl+1
cdi3:
  LDA #1
  STA cdok
  RTS
; ---- the CD-DA clock and cue scan, every pass from the stub: A = AD_STAT, X = it read
; playing last frame, Y = the frames since the last pass; A = the verdict. A track starts
; the tick $2638 rises (the game's CD service confirms the play from the sub-Q) and its
; number is $263B (BCD): from then the frames are counted and, every fourth, the module's
; cues (cdtbl, set by the stub's cdinit; entries [track][start u16][end u16][len u16]
; [fpc u16][char][chunks], frames from the start, 0 after the last) are scanned for one
; whose span holds the count - the block's magic read against the module's first (a scene
; load under the music replaces the table). A cue up (cdmode) reads playing while its
; entry holds; a different entry, or a real line, reads stopped for a frame first so the
; next line rises. ----
cdscan:
  STA cdstat
  STX cdlast
  LDA 0x2638
  TAX
  BEQ cdsoff             ; no track playing: no cue (counting on to the cue's end past the
  LDA cdwas              ; track's, the HQ return's last line met the game's menu in its rows)
  BNE cds0
  LDA 0x263B             ; a track starts: frame 0
  STA cdtrack
  STZ cdpos
  STZ cdpos+1
  LDY #0
  LDA #1
  STA cdlive
cds0:
  STX cdwas
  LDA cdlive
  BEQ cdsnone
  LDA cdok
  BEQ cdsnone
  TYA
  CLC
  ADC cdpos
  STA cdpos
  BCC cds1
  INC cdpos+1
cds1:
  LDA cdpos
  AND #3
  BNE cdverdict
  JSR cscan              ; A = 0 with the table gone
  BNE cdverdict
cdsgone:
  STZ cdok
  BRA cdsnone
cdsoff:
  STX cdwas
cdsnone:
  STZ cdlive
  STZ cdent
  STZ cdent+1
cdverdict:
  LDA cdstat
  BEQ cdv0
  ; a real line plays: a cue up ends this frame, the line rises next frame
  LDA cdmode
  BEQ cdvas
  BRA cdvnone
cdv0:
  LDA cdent
  ORA cdent+1
  BEQ cdvnone
  LDA cdent
  CMP cdcur
  BNE cdvnew
  LDA cdent+1
  CMP cdcur+1
  BNE cdvnew
  LDA #1                 ; the cue up goes on (or rises, after its stopped frame)
  RTS
cdvnew:
  LDA cdent
  STA cdcur
  LDA cdent+1
  STA cdcur+1
  LDA #1
  STA cdmode
  LDX cdlast             ; something played last frame: this frame reads stopped first
  BNE cdvstop
  RTS
cdvnone:
  STZ cdcur
  STZ cdcur+1
  STZ cdmode
cdvstop:
  LDA #0
  RTS
cdvas:
  LDA cdstat
  RTS
; the scan: cdent = the entry whose span holds cdpos, else 0; A = 0 when the module changed
cscan:
  LDA #lo(MAGIC)         ; still the module the block was read for?
  STA ctbl
  LDA #hi(MAGIC)
  STA ctbl+1
  LDY #0
  JSR cfetch
  CMP cdmag
  BNE cscgone
  LDY #1
  JSR cfetch
  CMP cdmag+1
  BNE cscgone
  LDA cdtbl
  STA ctbl
  LDA cdtbl+1
  STA ctbl+1
  BRA cloop
cscgone:
  LDA #0
  RTS
cloop:
  LDY #6                 ; the entry's header: track, start, end, len
cread:
  JSR cfetch
  STA chdr,Y
  DEY
  BPL cread
  LDA chdr
  BEQ cend               ; the end: no cue for now
  CMP cdtrack
  BNE cnext
  LDA cdpos              ; pos >= start?
  CMP chdr+1
  LDA cdpos+1
  SBC chdr+2
  BCC cnext
  LDA cdpos              ; pos < end?
  CMP chdr+3
  LDA cdpos+1
  SBC chdr+4
  BCS cnext
  CLC                    ; a cue: its entry from the len (the stub's found reads from there)
  LDA ctbl
  ADC #2
  STA cdent
  LDA ctbl+1
  ADC #0
  STA cdent+1
  BRA cyes
cnext:
  CLC                    ; the next entry: 7 + len on
  LDA ctbl
  ADC chdr+5
  STA ctbl
  LDA ctbl+1
  ADC chdr+6
  STA ctbl+1
  CLC
  LDA ctbl
  ADC #7
  STA ctbl
  LDA ctbl+1
  ADC #0
  STA ctbl+1
  BRA cloop
cend:
  STZ cdent
  STZ cdent+1
cyes:
  LDA #1
  RTS
cfetch:
  LDA ctbl
  STA 0x90
  LDA ctbl+1
  STA 0x91
  STY 0x92
  JMP FETCH
"""

TRAMP_SOURCE = """
; bank 0, in the vblank handler after the ADPCM service: the CD service the hook replaced,
; then the stub - the one in the resident file (rec 110's first bank at MPR5) when that is
; in, else one at $9000 in a bank at MPR4: the module's fourth (the ending, which runs
; without rec 110), then $6C (the opening's blocks, pceopening). Two bytes of each
; signature; AD_STAT is the stub's to read. 76 bytes, the gap's all: EOR keeps the carry,
; so the ADC of the resident's bank leaves it clear into the loop, the loop's ADC clear into
; SBC, and the SBC's own (set: no borrow) into the second ADC - 0x19, then 3 + C = 4.
tstat:
  JSR 0x6021             ; the CD service (the text bank is at MPR3 here)
  TMA #0x20
  PHA
  TMA #0x10
  PHA
  LDA #{BANK}
  CLC
  ADC 0x3F80
  TAM #0x20
  LDA {SIG}
  EOR #0x53
  BNE tmod
  LDA {SIG}+1
  EOR #0x42
  BNE tmod
  JSR {STAT}
  BRA tdone
tmod:
  LDY #{BANK3}
tm1:
  TYA
  ADC 0x3F80
  TAM #0x10
  LDA {MSIG}
  EOR #0x53
  BNE tnext
  LDA {MSIG}+1
  EOR #0x42
  BNE tnext
  JSR {MSTAT}
  BRA tdone
tnext:
  TYA
  SBC #0x{STEP:02X}
  TAY
  BCS tm1
tdone:
  PLA
  TAM #0x10
  PLA
  TAM #0x20
  RTS
"""


def magic(mod):
    """The module's checksum: the sum of its first 256 bytes, u16 LE."""
    return (sum(mod[:256]) & 0xFFFF).to_bytes(2, "little")


def char_code(speaker):
    """The character's code (1-based in CHARS), 0 for a speaker with no face."""
    return CHARS.index(speaker) + 1 if speaker in CHARS else 0


PLAIN = 0x80                 # the entry's character byte: bit 7 = the line is a plain card


def line_char(speaker, layout="face"):
    """An entry's character byte: the code, bit 7 (PLAIN) when the line is a plain card (its
    `layout`, "face" by default - decided at build, from what the runs saw: a portrait line
    is laid out beside the face from its first frame, a plain one never takes the face; the
    face block finds no speaker in a byte with bit 7). The names block carries the same bit:
    only plain cards look a name up."""
    code = char_code(speaker)
    return code | PLAIN if code and layout == "plain" else code


def chunk(text, colour=0):
    """One word as the table carries it: cells | colour << 5, then the pairs
    (the word packed on its own, a trailing space in its last cell)."""
    import pcescript as PS
    body = PS.label_bytes(text)
    cells = len(pcepair.split(text))
    assert len(body) == 2 * cells, (text, body.hex())
    assert 1 <= cells <= 31, (text, cells)
    return bytes([cells | colour << 5]) + body


def name_chunk(speaker):
    return (f"{speaker}: ", NAME_COLOUR.get(speaker, 2))


def name_cost(speaker):
    """The name's cells in a row: its colour code, its pairs, the text colour back after it."""
    return cost(*name_chunk(speaker)) + 1


def _chunks(en, trail=frozenset()):
    """chunks() and, per chunk, the index of the word it comes from."""
    words = en.replace("￥", " ").split()
    out, widx, lead = [], [], False
    for i, w in enumerate(words):
        colour = 0          # (the row starts white; a name restores it - names_block)
        t = (" " if lead else "") + w
        if i == len(words) - 1:
            tail, lead = "", False
        elif i in trail or len(pcepair.split(t)) * 2 != len(t):
            tail, lead = " ", False
        else:
            tail, lead = "", True
        while cost(t + tail, colour) > WIDTH_FACE4:
            # the longest head that fits, by letters (a pair is two letters a cell)
            k = len(t) - 1
            while k > 1 and cost(t[:k], colour) > WIDTH_FACE4:
                k -= 1
            out.append((t[:k], colour))
            widx.append(i)
            t, colour = t[k:], 0
        out.append((t + tail, colour))
        widx.append(i)
    return out, widx


def chunks(en, trail=frozenset()):
    """A line's word chunks, the first in white (the name, when drawn, comes before).
    Each chunk is whole cells (a pair is two letters a cell), so the space between two
    words goes with whichever word leaves no half-blank cell: after the word when it is
    odd, else before the next one ("Is" + " he " + "dead?" - one space each, where
    "Is " + "he " drew a space and a half-blank cell, a double space every other word).
    A word in `trail` keeps the space after it (the next one opens a row: no half-cell
    indent there). A word wider than a row beside a face (WIDTH_FACE cells, the colour
    code counted) is cut into pieces that fit - a long word wraps mid-word rather than
    never showing."""
    return _chunks(en, trail)[0]


ROW4 = 0x40                   # marker bit: a row break in the four-row face layout


def layout_marks(words, layouts, speaker=None, preferred=None):
    """{chunk index: mask} - where each layout turns its page (bit rows-2, +3 for the plain
    ones). The four-row face layout takes the two-row one's pages two at a time (its page bit
    at every second of them, ROW4 - a row break - at the others): both face layouts break
    their rows at the same words, so no chunk boundary of theirs falls mid-row in the other
    (a half-blank cell there drew a double space)."""
    from pcelayout import page_ends
    boundaries, ends2 = {}, None
    for face, rows in layouts:
        mask = 1 << (rows - 2 + (0 if face else 3))
        if face and rows == 4 and ends2 is not None:
            for j, end in enumerate(ends2[:-1]):
                boundaries[end] = boundaries.get(end, 0) | (mask if j % 2 else ROW4)
            continue
        width = WIDTH_FACE if face else WIDTH_PLAIN
        name = name_cost(speaker) if speaker and not face else 0
        ends = page_ends(words, cost, width, rows, name, preferred)
        if face and rows == 2:
            ends2 = ends
        for end in ends[:-1]:
            boundaries[end] = boundaries.get(end, 0) | mask
    return boundaries


def row_starts(words, boundaries, layouts, speaker=None):
    """The chunk indices that open a row or a page in any of the layouts (the stub's
    greedy wrap, as pages() previews it)."""
    starts = set()
    for face, rows in layouts:
        width = WIDTH_FACE if face else WIDTH_PLAIN
        mask = 1 << (rows - 2 + (0 if face else 3))
        used = name_cost(speaker) if speaker and not face else 0
        rowmask = ROW4 if face and rows == 4 else 0
        for index, word in enumerate(words):
            if boundaries.get(index, 0) & (mask | rowmask):
                starts.add(index)
                used = 0
            c = cost(*word)
            if used and used + c > width:
                starts.add(index)
                used = 0
            used += c
    return starts


def grouped_chunks(en, starts, lead=frozenset()):
    """The line's words in runs: a run from each index in `starts` to the next, packed as one
    chunk with one space between its words (the pairs run on across them) and the space
    after it at its end. A run wider than a row beside a face falls back to one chunk a word
    (the long word cut as chunks() cuts it). Returns the chunks and each one's first word.

    A run opening at an index in `lead` takes the space before it instead when the run before
    is even in letters: that space at the run's end would fill a cell of its own - a double
    space wherever the two runs share a row - while at the next run's head it pairs with its
    first letter (a half-cell indent only in a layout that opens a row there)."""
    words = en.replace("￥", " ").split()
    marks = sorted(m for m in set(starts) | {0} if 0 <= m < len(words))
    out, first = [], []
    for k, a in enumerate(marks):
        b = marks[k + 1] if k + 1 < len(marks) else len(words)
        body = " ".join(words[a:b])
        head = " " if out and not out[-1][0].endswith(" ") else ""   # the last run gave its space
        # the space after: this run's own when its letters (its head counted) are odd - the
        # space fills its last cell - or the next run is no lead; else the next run's head
        tail = " " if (b < len(words) and not (b in lead and len(head + body) % 2 == 0)) else ""
        text = head + body + tail
        colour = 0
        if cost(text, colour) <= WIDTH_FACE:
            out.append((text, colour))
            first.append(a)
            continue
        for i in range(a, b):
            t = words[i] + (" " if i < len(words) - 1 else "")
            if i == a and out and not out[-1][0].endswith(" "):
                t = " " + t
            c = 0
            while cost(t, c) > WIDTH_FACE:
                k2 = len(t) - 1
                while k2 > 1 and cost(t[:k2], c) > WIDTH_FACE:
                    k2 -= 1
                out.append((t[:k2], c))
                first.append(i)
                t, c = t[k2:], 0
            out.append((t, c))
            first.append(i)
    return out, first


ROW_FACE = 0x40               # marker bits: a row break in the face layouts (both: the four-row
ROW_PLAIN = 0x80              # one's pages are the two-row one's, two at a time) / the plain ones


def plan_marks(texts, cells_face, cells_plain, four_rows, speaker, forced, preferred):
    """{word index: mask} - every page and row the layouts open there, planned whole
    (pcelayout.plan_pages): page bits as layout_marks', ROW_FACE / ROW_PLAIN at row breaks."""
    from pcelayout import plan_pages, regroup
    marks = {}

    def add(i, m):
        if i:
            marks[i] = marks.get(i, 0) | m
    face = plan_pages(texts, cells_face, WIDTH_FACE, 2, 0, forced, preferred)
    for j, page in enumerate(face):
        add(page[0][0], 1)
        if four_rows:
            add(page[0][0], 4 if j % 2 == 0 else ROW_FACE)
        for a, _ in page[1:]:
            add(a, ROW_FACE)
    name = name_cost(speaker) if speaker else 0
    plain = plan_pages(texts, cells_plain, WIDTH_PLAIN, 2, name, forced, preferred)
    flat = [r for page in plain for r in page]
    for page in plain:
        add(page[0][0], 8)
    for a, _ in flat[1:]:
        add(a, ROW_PLAIN)
    if four_rows:
        for page in regroup(flat, 3, texts, forced, preferred):
            add(page[0][0], 16)
    return marks


def prune_rows(items, layouts, speaker=None):
    """The marker list with every bit the stub's own wrap makes anyway taken out: a row bit
    where the next chunk would not fit the row, a page bit where it would not fit the page's
    last row either - only the breaks the cards put EARLY cost their two bytes (the voice
    bank holds the ending's cue block and two of the act tables)."""
    need = {}
    nxt = {}
    following = None
    for k in range(len(items) - 1, -1, -1):
        nxt[k] = following
        if items[k][0] is not None:
            following = k
    for face, rows in layouts:
        width = face_width(rows) if face else WIDTH_PLAIN
        page_bit = 1 << (rows - 2 + (0 if face else 3))
        row_bit = ROW_FACE if face else ROW_PLAIN
        used = name_cost(speaker) if speaker and not face else 0
        row = 0
        for k, (text, colour) in enumerate(items):
            if text is None:
                j = nxt.get(k)
                c = cost(*items[j]) if j is not None else 0
                wraps = used and used + c > width
                if colour & page_bit:
                    if not (wraps and row == rows - 1):
                        need[k] = need.get(k, 0) | page_bit          # the card ends early
                    used, row = 0, -1                                # (the next chunk opens row 0)
                elif colour & row_bit:
                    if not wraps:
                        need[k] = need.get(k, 0) | row_bit
                    used = width + 1                                 # the next chunk: a new row
                continue
            c = cost(text, colour)
            if row == -1:
                row, used = 0, 0
            elif used and used + c > width:
                row, used = row + 1, 0
            used += c
    out = []
    for k, (text, colour) in enumerate(items):
        if text is None:
            colour = need.get(k, 0)
            if not colour:
                continue
        out.append((text, colour))
    return out


CARD_ROWS = 2
PLAIN_ROWS = 2               # a plain card's rows: the plain layout's two, the name first
FACE_ROWS = 4                # a portrait card's rows: the face layout's four (a card a page; drawn
                             # plain - the face never came - it is two pages, rows 1-2 and 3-4)


def card_ranges(en, cards=None, speaker=None, per_word=False, break_before=None, plain_only=False,
                plain=False, four=True):
    """The line's cards as [[(a, b), ...], ...] - word ranges, two rows a card, at most
    WIDTH_FACE cells a row (the first row of the first card leaves the plain layout room for
    the speaker's name: every layout draws the same rows); a `plain` line (its layout "plain":
    never beside a face) is planned for the plain layout alone - rows of WIDTH_PLAIN cells,
    PLAIN_ROWS a card, the name's cells held on its first and third rows; a portrait line (`four`:
    the resident stub, whose face layout has four rows) gets FACE_ROWS a card - one page beside
    the face, its words run on across the rows - its third row opening a page in the two-row
    layouts (planned as a page break: a sentence or clause end where it can). `cards` (the subs JSON's, rows
    split by "|") is taken as written - its words must be the line's, its rows must fit;
    else the rows and cards are planned (pcelayout.plan_pages)."""
    from pcelayout import plan_pages, bullet_starts
    texts = en.replace("￥", " ").split()
    n = len(texts)
    if per_word:
        cells = lambda a, b: sum(cost(t, c) for t, c in row_words(texts, a, b))
    else:
        cells = lambda a, b: (len(" ".join(texts[a:b])) + (1 if b < n else 0) + 1) // 2
    face4 = four and not plain_only and not plain
    width = WIDTH_PLAIN if plain_only or plain else WIDTH_FACE4 if face4 else WIDTH_FACE
    name = name_cost(speaker) if speaker else 0
    first = name if plain_only or plain else 0 if face4 else max(0, name - (WIDTH_PLAIN - WIDTH_FACE))
    nrows = FACE_ROWS if face4 else CARD_ROWS
    reserve = (first,)
    split = None
    if cards:
        out, i = [], 0
        for card in cards:
            rows = []
            for row in card.split("|"):
                words = row.split()
                if texts[i:i + len(words)] != words:
                    raise SystemExit(f"cards {cards!r}: {row!r} is not the line's next words ({en!r})")
                rows.append((i, i + len(words)))
                i += len(words)
            if not 1 <= len(rows) <= nrows:
                raise SystemExit(f"card {card!r}: {len(rows)} rows (1-{nrows})")
            out.append(rows)
        if i != n:
            raise SystemExit(f"cards {cards!r} leave out {' '.join(texts[i:])!r}")
        for j, card in enumerate(out):
            for k, (a, b) in enumerate(card):
                if cells(a, b) + (reserve[k] if k < len(reserve) else 0) > width:
                    raise SystemExit(f"card row {' '.join(texts[a:b])!r} is {cells(a, b)} cells (of {width})")
        return out
    forced = set(bullet_starts([(w, 0) for w in texts]))
    return greedy_cards(texts, cells, width, nrows, reserve, forced)


def greedy_cards(texts, cells, width, nrows, reserve=(), forced=()):
    """The line's cards: where they break is lib/cardplan.py's (whole sentences a card,
    then clause, phrase, word; no widow - the rule on every port), and inside a card
    every row takes every word that still fits, its reserved cells (the speaker's name
    on a card's first row) counted. Luiz, 2026-11-05."""
    import cardplan

    def lay(a, b):
        rows = []
        for j in range(a, b):
            if rows:
                k = len(rows) - 1
                res = reserve[k] if k < len(reserve) else 0
                if cells(rows[-1][0], j + 1) + res <= width:
                    rows[-1][1] = j + 1
                    continue
            if len(rows) == nrows:
                return None
            rows.append([j, j + 1])
        return rows

    cards = cardplan.plan(texts, lambda a, b: lay(a, b) is not None, forced)
    return [[tuple(r) for r in (lay(a, b) or [[a, b]])] for a, b in cards]


def row_words(texts, a, b):
    """A row's words a chunk each (the CD-DA cards': the words come up one by one), in whole
    cells as chunks() packs them: the space between two words goes after the first when it is
    odd, else at the head of the next ("Is" + " the" - one space; "Is " + "the " drew a space
    and a half-blank cell, the double space every even word left). The row's last word keeps
    its space (the next opens a row), the line's last has none."""
    out, lead = [], False
    for i in range(a, b):
        t = (" " if lead else "") + texts[i]
        if i == len(texts) - 1:
            tail, lead = "", False
        elif i == b - 1 or len(pcepair.split(t)) * 2 != len(t):
            tail, lead = " ", False
        else:
            tail, lead = "", True
        out.append((t + tail, 0))
    return out


def card_text(en, ranges):
    """The cards as the subs JSON keeps them: ["row|row", ...]."""
    texts = en.replace("￥", " ").split()
    return ["|".join(" ".join(texts[a:b]) for a, b in card) for card in ranges]


def card_chunks(en, ranges, four_rows=True, speaker=None, per_word=False, layouts=None, plain=False):
    """Chunks and markers for cards: one chunk a row (a run of whole cells with one space
    between its words; per_word: one a word, the CD-DA cards'), the rows broken where the
    cards say in every layout - the two-row ones a card a page, the four-row face one two
    cards a page, the plain three-row one a card a page - so what a card says is what shows.
    A `plain` line's cards (three rows) draw in the plain layouts only: a card a page in the
    three-row one, its third row a page of its own in the two-row fallback. A portrait line's
    four-row cards: a card a page beside the face in four rows, two pages (rows 1-2, 3-4) in
    every two- or three-row layout."""
    texts = en.replace("￥", " ").split()
    n = len(texts)
    items = []
    for j, card in enumerate(ranges):
        for k, (a, b) in enumerate(card):
            if j or k:
                if plain:
                    mask = ROW_PLAIN if k else 8
                elif four_rows:
                    mask = (4 | 8) if not k else (ROW_FACE | 8) if k == 2 else ROW_FACE
                elif k:
                    mask = ROW_FACE | ROW_PLAIN
                else:
                    mask = 1 | 8 | (16 if four_rows else 0)
                    if four_rows:
                        mask |= 4 if j % 2 == 0 else ROW_FACE
                items.append((None, mask))
            if per_word:
                items += row_words(texts, a, b)
            else:
                items.append((" ".join(texts[a:b]) + (" " if b < n else ""), 0))
    if plain and not layouts:
        layouts = [(False, 2)]
    layouts = layouts or ([(True, 4), (False, 2)] if four_rows else [(True, 2), (False, 2)])
    return prune_rows(items, layouts, speaker)


def balanced_chunks(en, four_rows=True, break_before=None, speaker=None):
    """The line's chunks with a marker `(None, mask)` before each that opens a page or a row
    in some layout - the rows and pages planned whole (plan_marks): a layout's rows are the
    plan's, never the stub's greedy wrap (a lone "damaged" on a row of its own, "both" left
    behind). Bits 0..2 face pages (2/3/4 rows), 3..5 plain pages, ROW_FACE / ROW_PLAIN rows.

    Spacing: a pair is two letters a cell and a chunk is whole cells, so the words between two
    breaks are one chunk (every space inside it one letter wide); at a break the space goes at
    the end of the chunk before it (a row's end hides it) - or, at a break only the plain
    layouts make, at the head of the chunk after it when the one before is even in letters
    (grouped_chunks' lead): the face layouts, that run on through it, draw one space there."""
    from pcelayout import bullet_starts
    texts = en.replace("￥", " ").split()
    n = len(texts)
    forced = set(bullet_starts([(w, 0) for w in texts]))
    preferred = None
    if break_before:
        preferred = next((i for i in range(1, n) if " ".join(texts[i:]).startswith(break_before)), None)
        if preferred is None:
            raise ValueError(f"page phrase {break_before!r} absent from {en!r}")
        forced.add(preferred)
    joined = lambda a, b: len(" ".join(texts[a:b]))

    def cells_face(a, b):
        # one run (its inner breaks are the plain layouts' only: no lost half cell), its
        # trailing space unless the line ends there
        return (joined(a, b) + (1 if b < n else 0) + 1) // 2
    face_marks = {}
    for _ in range(2):
        def cells_plain(a, b):
            # runs split at the face layouts' breaks inside: each keeps its trailing space
            cuts = [i for i in range(a + 1, b) if face_marks.get(i, 0) & (1 | 4 | ROW_FACE)]
            c, start = 0, a
            for cut in cuts + [b]:
                tail = 1 if (cut < b or b < n) else 0
                c += (joined(start, cut) + tail + 1) // 2
                start = cut
            return c
        marks = plan_marks(texts, cells_face, cells_plain, four_rows, speaker, forced, preferred)
        if marks == face_marks:
            break
        face_marks = marks
    starts = {0} | set(marks)
    lead = frozenset(i for i, m in marks.items() if not m & (1 | 4 | ROW_FACE))
    words, first = grouped_chunks(en, starts, lead)
    out, seen = [], set()
    for word, fi in zip(words, first):
        if fi in marks and fi not in seen:
            out.append((None, marks[fi]))
            seen.add(fi)
        out.append(word)
    layouts = [(True, 2), (False, 2)] + ([(True, 4), (False, 3)] if four_rows else [])
    return prune_rows(out, layouts, speaker)


def word_chunks(en):
    """A line's word chunks, the first in white (the name, when drawn, comes before).
    A word wider than a row beside a face (WIDTH_FACE cells, the colour code
    counted) is cut into pieces that fit - a long word wraps mid-word rather
    than never showing."""
    words = en.replace("￥", " ").split()
    out = []
    for i, w in enumerate(words):
        colour = 0          # (the row starts white; a name restores it - names_block)
        tail = " " if i < len(words) - 1 else ""
        while cost(w + tail, colour) > WIDTH_FACE4:
            # the longest head that fits, by letters (a pair is two letters a cell)
            k = len(w) - 1
            while k > 1 and cost(w[:k], colour) > WIDTH_FACE4:
                k -= 1
            out.append((w[:k], colour))
            w, colour = w[k:], 0
        out.append((w + tail, colour))
    return out


def word_balanced_chunks(en, four_rows=True, break_before=None, speaker=None):
    """The CD-DA cards': one chunk a word (word_chunks - packed chunks wedged the clock's path),
    the rows and pages planned whole as balanced_chunks' (plan_marks), with each word's own
    cells (its trailing space a half or a whole cell)."""
    from pcelayout import bullet_starts
    words = word_chunks(en)
    texts = [t.strip() for t, _ in words]
    n = len(texts)
    forced = set(bullet_starts([(w, 0) for w in texts]))
    preferred = None
    if break_before:
        preferred = next((i for i in range(1, n) if "".join(t for t, _ in words[i:]).lstrip().startswith(break_before)), None)
        if preferred is None:
            raise ValueError(f"page phrase {break_before!r} absent from {en!r}")
        forced.add(preferred)
    each = [cost(t, c) for t, c in words]
    cells = lambda a, b: sum(each[a:b])
    marks = plan_marks(texts, cells, cells, four_rows, speaker, forced, preferred)
    out = []
    for index, word in enumerate(words):
        if index in marks:
            out.append((None, marks[index]))
        out.append(word)
    # (no row breaks for the cards: the voice bank holds the ending's cue block and has no
    # room for their markers - the cards keep the planned pages, rows wrapped by the stub)
    return [(t, c & ~(ROW_FACE | ROW_PLAIN)) for t, c in out if t is not None or c & ~(ROW_FACE | ROW_PLAIN)]


def cost(text, colour):
    return len(pcepair.split(text)) + (1 if colour else 0)


def face_width(rows):
    """A face layout's row width: the resident's four rows WIDTH_FACE4, the module stub's two WIDTH_FACE."""
    return WIDTH_FACE4 if rows == 4 else WIDTH_FACE


def pages(speaker, en, face=False, rows=None, four_rows=True, break_before=None, cards=None, per_word=False,
          plain_only=False, plain=False):
    """Preview the shipped cards and renderer for a specific runtime layout."""
    rows = rows or (4 if face and four_rows else 2)
    width = face_width(rows) if face else WIDTH_PLAIN
    mask = 1 << (rows - 2 + (0 if face else 3))
    items = ([name_chunk(speaker), ("", TEXT_COLOUR)] if speaker and not face else []) + card_chunks(
        en, card_ranges(en, cards, speaker, per_word, break_before, plain_only, plain, four_rows), four_rows, speaker, per_word,
        [(False, 2)] if plain_only else None, plain and not plain_only)
    out, page, row, cells = [], [], "", 0
    for text, colour in items:
        if text is None:
            if colour & mask and (row or page):
                if row:
                    page.append(row)
                out.append(page)
                page, row, cells = [], "", 0
            elif colour & (ROW_FACE if face else ROW_PLAIN) and row:
                cells = width + 1                  # (the stub: bit 7 of cells, the next chunk's row)
            continue
        c = cost(text, colour)
        if cells + c > width and row:
            page.append(row)
            row, cells = "", 0
            if len(page) == rows:
                out.append(page)
                page = []
        row += text
        cells += c
    if row:
        page.append(row)
    if page:
        out.append(page)
    return out


def line_key(rec, key):
    """A subs_<rec>.json key -> (act, NN): "c8" for a NN the module plays in one act only,
    "c8.5" for one it plays in several (the ending's c8-d8 in acts 4 and 5)."""
    import pcevoice as V
    n = [e["n"] for e in json.load(open(os.path.join(WORK, "pce", "filetable.json")))["1"] if e["rec"] == rec][0]
    if "." in key:
        nn, act = key.split(".")
        return int(act), int(nn, 16)
    nn = int(key, 16)
    acts = sorted({a for a, b in V.module_voices(rec, n) if b == nn})
    if len(acts) > 1:
        raise SystemExit(f"{rec} {key}: NN in acts {acts}, the key needs the act ('{key}.{acts[0]}')")
    return (acts[0] if acts else 0), nn


def turn_marks(rec, key, spec, ch, ranges, name):
    """The line's chunks paced to its `turns` (pceturns.py: the seconds at which cards 2.. come
    up, from the Japanese voice), and its frames-per-cell; (ch, None) - the even pace over the
    clip - for a line without them or whose cards no longer match.

    Each card k has the slot T[k]..T[k+1] (T[0] = 0, the last slot ends with the clip). The pace
    is the fastest slot's (frames-per-cell = min over the cards of slot / cells), so every card's
    text fits its slot; the rest of a slot is held by pause markers (bit 0x20 + a weight in
    cells' worth of time, at most 255 a marker) placed at the card's end - before the markers
    already at that boundary, or the stub would add the hold to the next page. The last card
    needs none: the line's end takes its page down."""
    turns = spec.get("turns")
    if not turns or len(turns) != len(ranges) - 1 or os.environ.get("NO_TURNS"):
        return ch, None
    frames = duration_frames(rec, key)
    T = [0.0] + [t * 60 for t in turns] + [frames]
    if any(b - a < 6 for a, b in zip(T, T[1:])):
        return ch, None
    rows = [len(card) for card in ranges]
    # the name costs time only where it is drawn: the plain layout, on every page (the stub's
    # fname, `pcells`); a portrait line draws none - counting it on the first card held that
    # card's turn back in the model alone, and on screen it came up early (478 23: 0.8 s)
    if spec.get("layout", "face") != "plain":
        name = 0
    cells, firsts, k, n = [0] * len(rows), [], 0, 0
    for i, (t, c) in enumerate(ch):
        if t is None:
            continue
        if n == 0:
            firsts.append(i)
        cells[k] += cost(t, c)
        n += 1
        if n == rows[k]:
            k, n = k + 1, 0
            if k == len(rows):
                break
    if k != len(rows):
        return ch, None
    cells = [c + name for c in cells]
    fpc = min((T[j + 1] - T[j]) / max(1, cells[j]) for j in range(len(rows)))
    # a page's time is its cells and holds as ONE byte in the stub (pcells, at most 255): a pace
    # so fast that a long slot needs more lost the rest (670 56's second card turned 2.3 s
    # early) - the pace is at least the longest slot's over PAGE_CELLS
    fpc = max(fpc, max((T[j + 1] - T[j]) / PAGE_CELLS for j in range(len(rows))))
    at, now = {}, 0.0
    for j in range(len(rows) - 1):
        # each page held to its turn from where the last one really ended (one that overran its
        # slot at the floored pace starts the next late; its hold makes the time up)
        hold = min(T[j + 1] - now - cells[j] * fpc, (PAGE_CELLS - cells[j]) * fpc)
        now += cells[j] * fpc
        if hold < 1:
            continue
        i = firsts[j + 1]
        while i > 0 and ch[i - 1][0] is None:
            i -= 1
        w = int(round(hold / fpc))
        now += w * fpc
        at[i] = at.get(i, []) + [min(255, w - 255 * m) for m in range((w + 254) // 255)]
    out = []
    for i, item in enumerate(ch):
        for w in at.get(i, []):
            if w > 0:
                out.append((None, ("P", w)))
        out.append(item)
    return out, fpc


PAGE_CELLS = 250             # a page's cells and holds, the stub's one-byte pcells (255) with room


def paced_name(spec, ranges):
    """The cells the speaker's name adds to a line's time: on every page of a plain line, none
    beside a portrait (the stub draws the name in the plain layout only)."""
    if not spec.get("speaker") or spec.get("layout", "face") != "plain":
        return 0
    return name_cost(spec["speaker"]) * len(ranges)


def duration_frames(rec, key):
    """The line's length from its ADPCM record: sectors x FRAMES_PER_SECTOR."""
    import pcevoice as V
    act, nn = line_key(rec, key)
    return V.record(act, nn)["count"] * FRAMES_PER_SECTOR


def table(rec):
    """The module's subtitle table, its pair codes from the module's own pair table (pcepair);
    see _table."""
    with pcepair.using(pcepair.table_for(rec)):
        return _table(rec)


def _table(rec):
    """The module's subtitle table as (main, cues): `[names offset u16][cues address u16]`, the
    lines' entries, 0, the names block, 0 - and the CD-DA cues' block apart (place_cues() writes
    where it went: after the main part, or in rec 54's bank when the window has no room);
    (b'', b'') for a module with neither."""
    path = os.path.join(ROOT, "pce", "translation", f"subs_{rec}.json")
    if not os.path.exists(path) and not cdda_cues(rec):
        return b"", b""
    import pcescript as PS
    lines = {k: v for k, v in json.load(open(path, encoding="utf-8")).items() if not k.startswith("_")} if os.path.exists(path) else {}
    out = bytearray()
    speakers = []
    import pcevoice as V
    for key, spec in sorted(lines.items(), key=lambda kv: int(kv[0].split(".")[0], 16)):
        if spec.get("display") == "graphic":
            continue  # the translated diary picture already presents this spoken passage
        act, nn = line_key(rec, key)
        sector = V.record(act, nn)["sector"] & 0xFFFF
        speaker = spec.get("speaker")
        plain = spec.get("layout", "face") == "plain"
        ranges = card_ranges(spec["en"], spec.get("cards"), speaker,
                             break_before=PAGE_BREAKS.get((rec, key)), plain=plain, four=rec not in NO_RESIDENT)
        ch = card_chunks(spec["en"], ranges, rec not in NO_RESIDENT, speaker, plain=plain)
        total = sum(cost(t, c) for t, c in ch if t is not None) + paced_name(spec, ranges)
        ch, fpc_frames = turn_marks(rec, key, spec, ch, ranges, name_cost(speaker) if speaker else 0)
        body = b"".join((bytes([0, 0x20, c[1]]) if isinstance(c, tuple) else bytes([0, c])) if t is None
                        else chunk(t, c) for t, c in ch)
        fpc = int(round(fpc_frames * 256)) if fpc_frames else int(round(duration_frames(rec, key) * 256 / max(1, total)))
        fpc = max(1, min(0xFFFF, fpc))
        for text, colour in ch:
            if text is None:
                continue
            assert cost(text, colour) <= (WIDTH_PLAIN if plain else WIDTH_FACE), (rec, key, text)
        if speaker and char_code(speaker) == 0:
            raise SystemExit(f"{rec} {key}: speaker {speaker!r} is not in pcesubs.CHARS")
        if speaker and speaker not in speakers:
            speakers.append(speaker)
        out += bytes([nn]) + sector.to_bytes(2, "little") + (len(body) + 3).to_bytes(2, "little") + fpc.to_bytes(2, "little") + bytes([line_char(speaker, spec.get("layout", "face"))]) + body
    out += bytes([0])
    # the CD-DA cues (cdda_<rec>.json), a block of their own: [magic u16 (the placer's)][names
    # offset u16], entries [track BCD][start u16][end u16][len u16][fpc u16][char][chunks] (frames
    # from the track's start, sorted by track and start), 0, then the block's own names, 0
    cd = bytearray()
    cd_speakers = []
    recolour = (lambda c: EPI_COLOURS.get(c, c)) if rec in EPILOGUE else (lambda c: c)
    for c in sorted(cdda_cues(rec), key=lambda c: (c["track"], c["start"])):
        speaker = c.get("speaker")
        plain = c.get("layout", "face") == "plain" and rec not in EPILOGUE
        ranges = card_ranges(c["en"], c.get("cards"), speaker, per_word=True, plain_only=rec in EPILOGUE,
                             plain=plain, four=rec not in NO_RESIDENT)
        ch = [(t, recolour(cl) if t is not None else cl)
              for t, cl in card_chunks(c["en"], ranges, rec not in NO_RESIDENT, speaker, per_word=True,
                                       layouts=[(False, 2)] if rec in EPILOGUE else None,
                                       plain=plain)]   # (no faces there)
        body = b"".join(bytes([0, cl]) if t is None else chunk(t, cl) for t, cl in ch)
        total = sum(cost(t, cl) for t, cl in ch if t is not None) + (name_cost(speaker) if speaker else 0)
        s, e = int(round(c["start"] * CDDA_FPS)), int(round(c["end"] * CDDA_FPS))
        if not 0 <= s < e <= 0xFFFF:
            raise SystemExit(f"{rec} track {c['track']} {c['start']}-{c['end']}: out of range")
        # the words come up at the voice's pace: start..reveal_end (the last word said, from the
        # track's word stamps - pcecdreveal), the page then held to the cue's end
        r = int(round(c.get("reveal_end", c["end"]) * CDDA_FPS))
        fpc = max(1, min(0xFFFF, int(round((min(e, max(s + 1, r)) - s) * 256 / max(1, total)))))
        for text, colour in ch:
            if text is None:
                continue
            assert cost(text, colour) <= (WIDTH_PLAIN if plain or rec in EPILOGUE else WIDTH_FACE), (rec, c, text)
        if speaker and char_code(speaker) == 0:
            raise SystemExit(f"{rec} track {c['track']} {c['start']}: speaker {speaker!r} is not in pcesubs.CHARS")
        if speaker and speaker not in cd_speakers:
            cd_speakers.append(speaker)
        cd += (bytes([int(f"{c['track']:02d}", 16)]) + s.to_bytes(2, "little") + e.to_bytes(2, "little")
               + (len(body) + 3).to_bytes(2, "little") + fpc.to_bytes(2, "little")
               + bytes([line_char(speaker, "plain" if rec in EPILOGUE else c.get("layout", "face"))]) + body)
    cd += bytes([0])
    # the names blocks the plain layout draws from: [char][colour][cells][pairs]..., 0
    def names_block(who, recolour=lambda c: c):
        names = b""
        for name in who:
            text, colour = name_chunk(name)
            # the text's own colour back after the name, as one more cell: a line's first chunk
            # carries no colour code (the row starts in it), so the face layout's first row has
            # its cell for text
            names += (bytes([line_char(name, "plain"), recolour(colour), len(pcepair.split(text)) + 1]) + PS.label_bytes(text)
                      + bytes([0xFE, recolour(TEXT_COLOUR)]))
        return names + bytes([0])
    if cd_speakers or len(cd) > 1:
        cd = bytes(2) + (4 + len(cd)).to_bytes(2, "little") + bytes(cd) + names_block(cd_speakers, recolour)
    else:
        cd = b""
    if not lines:
        return b"", bytes(cd)
    return bytes(2) + (len(out) + 4).to_bytes(2, "little") + bytes(out) + names_block(speakers), bytes(cd)


def stamp(block, magic):
    """A table or cue block with the module's magic bytes in its header."""
    return magic + block[2:]


def cdda_cues(rec):
    """The module's CD-DA cues, [{track, start, end (seconds), speaker, en}], or []."""
    path = CDDA.format(rec=rec)
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []


def faces_db():
    """pce/translation/faces.json: {character: [[four words]...]}."""
    return json.load(open(FACES, encoding="utf-8")) if os.path.exists(FACES) else {}


def tail(stub_labels=None):
    """Bank 1's tail code (the walker hook, the region copy), and its labels. The walker hook
    reads the stub's variables: with `stub_labels` None (the face block asking where the copy
    is) placeholders of the same width stand in."""
    class Holes(dict):
        def __missing__(self, k):
            return 0xBFFC
    sl = Holes(stub_labels or {})
    rowtail = ROWTAIL_ASM
    for v in ROWTAIL_VARS:
        rowtail = rowtail.replace("{" + v + "}", str(sl[v]))
    src = TAIL_SOURCE.format(FACE_BANK=FACE_BANK, FACE=FACE, FETCH=FETCH, MAGIC=MAGIC, SIG=sl["sig"], SHOWN=sl["fixon"], FACES=sl["faces"], FRAN=sl["fran"], ROWTAIL=rowtail)
    code, labels = assemble(src, TAIL)
    if TAIL + len(code) > TAIL_END:
        raise SystemExit(f"bank 1's tail code is {len(code)} B, the gap holds {TAIL_END - TAIL}")
    return code, labels


def sig_blob():
    """The face signatures for the voice bank: [char][four words]... (faces.json)."""
    db = faces_db()
    sigs = []
    for name, entries in db.items():
        code = char_code(name)
        if not code:
            raise SystemExit(f"faces.json: {name!r} is not in pcesubs.CHARS")
        for words in entries:
            sigs.append(bytes([code]) + b"".join(int(w).to_bytes(2, "little") for w in words))
    return b"".join(sigs), len(sigs)


# A diagnostic build (PCE_WDOG=1, #90): a watchdog on the clock's pass. A load request
# pending in $3F21 (any but a seek) for 512 passes (~8.5 s; the game's own loads take 1-3 s)
# is a hung load: the stack page, MPR2-6 as the pass sees them, the BIOS arguments and the
# loader's and the CD-DA variables go once into the backup RAM's free end ($F7:06A0-07FF;
# the game's four 400-byte slots end at 0x650), and the overscan colour turns red - open the
# OSD and save the backup RAM, the .sav carries it. Silence and no red: interrupts are dead.
WDOG_SOURCE = """
wdcnt:  .word 0
wddone: .byte 0
wdhdr:  .byte 0x44, 0x42, 0x47, 0x31    ; "DBG1"
wdmpr:  .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
wdog:
  PHA
  PHX
  PHY
  LDA 0x3F21
  AND #0x3F
  BEQ wdrst
  CMP #4
  BEQ wdrst              ; a seek request waits on the game's own terms
  LDA wddone
  BNE wdout
  INC wdcnt
  BNE wd1
  INC wdcnt+1
wd1:
  LDA wdcnt+1
  CMP #2
  BCS wdfire
  BRA wdout
wdrst:
  STZ wdcnt
  STZ wdcnt+1
wdout:
  PLY
  PLX
  PLA
  RTS
wdfire:
  INC wddone
  .byte 0xBA              ; TSX
  STX wdmpr              ; S (+4 to the pass's own frame: PHA PHX PHY and the JSR)
  TMA #0x04
  STA wdmpr+1
  TMA #0x08
  STA wdmpr+2
  TMA #0x10
  STA wdmpr+3
  TMA #0x20
  STA wdmpr+4
  TMA #0x40
  STA wdmpr+5
  LDA 0x39BF
  STA wdmpr+6
  LDA 0x30
  STA wdmpr+7
  LDA 0x1B
  STA wdmpr+8
  LDA wdcnt
  STA wdmpr+9
  TMA #0x40
  PHA
  LDA #0xF7
  TAM #0x40              ; the backup RAM at $C000
  LDA #0x80
  STA 0x1807             ; unlocked
  .byte 0x73
  .word wdhdr, 0xC6A0, 16
  .byte 0x73
  .word 0x20F8, 0xC6B0, 8
  .byte 0x73
  .word 0x3F20, 0xC6C0, 16
  .byte 0x73
  .word 0x2630, 0xC6D0, 16
  .byte 0x73
  .word 0x3600, 0xC6E0, 32
  .byte 0x73
  .word 0x2100, 0xC700, 256
  LDA 0x1803             ; locked
  PLA
  TAM #0x40
  LDA #0
  STA 0x0402
  LDA #1
  STA 0x0403             ; colour 0x100, the overscan
  LDA #0x38
  STA 0x0404
  STZ 0x0405             ; red
  JMP wdout
"""


def cd_block(org=None):
    """The CD-DA clock's code and variables for the voice bank at its placed address (VOICE_WIN
    + the run offset; `org` given sizes it for the placer), and its labels."""
    if org is None:
        org = VOICE_WIN + overflow_tables()["cdcode"][0] - 0x8000
    src = CD_SOURCE.format(FETCH=FETCH, MAGIC=MAGIC, FACE=FACE) + FHOLD_SOURCE
    if os.environ.get("PCE_WDOG"):
        assert src.count("cdscan:\n  STA cdstat") == 1
        wd = WDOG_SOURCE.replace("CMP #2\n  BCS wdfire", f"CMP #{int(os.environ.get('PCE_WDOG_T', 2))}\n  BCS wdfire")
        src = src.replace("cdscan:\n  STA cdstat", wd + "cdscan:\n  JSR wdog\n  STA cdstat")
    return assemble(src, org)


def face_block(vcopy=None, org=None):
    """The face block's bytes for rec 110's first bank at FACE_OFF (or, `org` given, for a
    module that carries its own), and its labels."""
    import pcescript as PS
    if vcopy is None:
        vcopy = tail()[1]["vcopyt"]
    if org is None:
        org = FACE
    _, nsigs = sig_blob()
    sigs = VOICE_WIN + (SIG_AT & 0x1FFF)                             # in rec 54's SIG_AT bank at MPR3
    src = FACE_SOURCE.replace("{NSIGS}", str(nsigs)).replace("{SIGS}", str(sigs)).replace("{SIG_BANK}", str(VOICE_BANK + (SIG_AT >> 13))).replace("{VCOPY}", str(vcopy)).replace("{VOICE_BANK}", str(VOICE_BANK))
    code, labels = assemble(src, org)
    if org == FACE and FACE_OFF + len(code) > FACE_END:
        raise SystemExit(f"the face block is {len(code)} B, rec 110's tail holds {FACE_END - FACE_OFF}")
    if org == MODULE_FACE and org + len(code) > MODULE_STUB:
        raise SystemExit(f"the module's face block is {len(code)} B, into its stub")
    assert code[3:6] == FACE_SIG
    return code, labels


def vfix_block(org=None, fhold=None, klost=None):
    """vfix (#91) and keep (#93's hold check) for the voice bank at its placed address, and
    their labels; `fhold` = the clock block's fhold, `klost` klost's address (given while the
    bank is being placed)."""
    if org is None:
        org = VOICE_WIN + overflow_tables()["vfixcode"][0] - 0x8000
    if fhold is None:
        fhold = cd_block()[1]["fhold"]
    if klost is None:
        kl = klost_block()[1]
        klost, kclean = kl["klost"], kl["kclean"]
    else:
        klost, kclean = klost
    sv = stub_vars()
    return assemble(VFIX_SOURCE.format(SHOWN=sv["shown"], ROWSIN=sv["rowsin"], HOLD=sv["hold"], FIXON=sv["fixon"], GRACE=sv["grace"], LINGER=sv["linger"],
                                       FACES=sv["faces"], GTAKE=sv["gtake"], N=sv["n"],
                                       WBAT=sv["wbat"], FHOLD=fhold, KLOST=klost, KCLEAN=kclean, OWED=sv["owed"], LEFT=sv["left"]), org)


def klost_block(org=None):
    """klost (a borrowed face's region our rows left, cleared) for the voice bank at its placed
    address, and its labels."""
    if org is None:
        org = VOICE_WIN + overflow_tables()["klostcode"][0] - 0x8000
    sv = stub_vars()
    src = KLOST_SOURCE
    if "kbat" in os.environ.get("SUBS_OFF", "").split(","):     # (debug: the rows' re-map left out)
        src = src.replace("  JSR kbat\n", "")
    return assemble(src.format(FACE=FACE, NN=sv["nn"], ROWSIN=sv["rowsin"], TREG=sv["treg"],
                                        NROWS=sv["nrows"], CLEAR=sv["clear"], PSP=sv["psp"],
                                        PPK=sv["ppk"], GW4=tail()[1]["gwrote"] + 0x2000,
                                        KIDLE=KIDLE, KSTEP_MASK=KSTEP_MASK, SHOWN=sv["shown"],
                                        GTAKE=sv["gtake"], N=sv["n"], WBAT=sv["wbat"], GRACE=sv["grace"],
                                        WINBAT_LO=WIN_BAT & 0xFF, WINBAT_HI=WIN_BAT >> 8, LINGER=sv["linger"]), org)


_STUB_VARS = None
_STUB_VARS_BUSY = False


def stub_vars():
    """The resident stub's variable addresses (its data comes first: the clock's labels do not
    move them), for the voice bank's vfix - assembled with placeholder clock labels. Sizing the
    voice bank asks for them while they are being found (stub_org -> face_block -> the
    signatures' place -> cd_block): placeholders then, the same widths."""
    global _STUB_VARS, _STUB_VARS_BUSY
    if _STUB_VARS is not None:
        return _STUB_VARS
    if _STUB_VARS_BUSY:
        return {k: 0x8000 for k in ("shown", "rowsin", "hold", "faces", "gtake", "n", "wbat", "fixon", "owed", "left", "linger", "fran", "grace",
                                    "nn", "treg", "nrows", "clear", "psp", "ppk")}
    _STUB_VARS_BUSY = True
    try:
        dummy = {k: 0x8000 for k in ("cdscan", "cdwas", "cdtbl", "cdok", "cdmag", "cdmode", "cdcur",
                                     "cdsig", "fhold", "vfix", "keep", "cdini2")}
        _, labels = assemble(source(cdlabels=dummy), stub_org())
    finally:
        _STUB_VARS_BUSY = False
    _STUB_VARS = labels
    return labels


def stub_org():
    """The stub's address: after the face block in rec 110's tail, on a 16-byte boundary."""
    block, _ = face_block()
    return FACE + (len(block) + 15 & ~15)


def stub(org=None):
    """The stub's bytes for rec 110's tail after the face block (or, for a module without
    rec 110, its fourth bank at MODULE_STUB), and its labels."""
    if org is None:
        org = stub_org()
        limit = 0xA000 + FACE_END
        code, labels = assemble(source(), org)          # the tail's entries: placeholders first,
        _, tl = tail(labels)                             # then the real ones (the same widths)
        src = source(tails=tl)
    else:
        limit = MODULE_STUB_END
        src = source(MODULE_FACE, resident=False)
    code, labels = assemble(src, org)
    if org + len(code) > limit:
        raise SystemExit(f"the subtitle stub is {len(code)} B at {org:#06x}, past {limit:#06x}")
    assert code[-3:] == SIGNATURE
    return code, labels


def patches():
    """[(file offset, old bytes, new bytes)] for stage 2: the trampoline and the hook."""
    code, labels = stub()
    org = stub_org()
    mcode, mlabels = stub(MODULE_STUB)
    tsrc = TRAMP_SOURCE.format(BANK=FACE_BANK, SIG=labels["sig"], STAT=labels["entry"], BANK3=MODULE_BANK3, MSIG=mlabels["sig"],
                               MSTAT=MODULE_STUB, STEP=MODULE_BANK3 - (OPEN_BANK - 1) - 1)
    tramp, tlabels = assemble(tsrc, TRAMP)
    if TRAMP + len(tramp) > TRAMP_END:
        raise SystemExit(f"the trampoline is {len(tramp)} B, the gap holds {TRAMP_END - TRAMP}")
    off, expect = HOOK
    target = tlabels["tstat"]
    tcode, tl = tail(labels)
    woff, wexpect = WALKER_HOOK
    out = [(TRAMP - P.STAGE2_BASE, bytes([0xFF]) * len(tramp), tramp),
           (off, expect, bytes([0x20, target & 0xFF, target >> 8])),
           (TAIL_OFF, bytes([0xFF]) * len(tcode), tcode),
           (woff, wexpect, bytes([0x4C, tl["whook"] & 0xFF, tl["whook"] >> 8]))]
    if os.environ.get("PCE_NOWALKER"):                 # (debug: the game's sprite table untouched)
        out[-1] = (woff, wexpect, wexpect)
    for loff, lexpect, name in LOG_HOOKS:
        at = tl[name]
        out.append((loff, lexpect, bytes([0x20, at & 0xFF, at >> 8])))
    return out


def pack_runs():
    """{block key: run index} for overflow_tables: the blocks' sizes against OVERFLOW_RUNS, the
    first assignment (in first-fit order of preference) that fits them all. Any block may sit in
    either run (the act files load below 0x940 and a shared block is written into them too)
    but the CD-DA clock: its signature (CDSIG) is the stub's only test that rec 54 is in, so it
    sits in run 2 (0x1800-0x1FFF, one sector, the bank's last to load) - in run 1 it arrived
    before klost in run 2 and the stub called into the opening's scratch (a boot hang at the
    opening's end, 2026-10-15). First-fit alone left 49 + 224 B and a 233-byte block nowhere.
    None = first-fit."""
    import itertools
    sizes = []
    for rec in OVERFLOW:
        main, cd = table(rec)
        if main:
            sizes.append((rec, len(main)))
        if cd:
            sizes.append((f"cd{rec}", len(cd)))
    for rec in CD_OVERFLOW:
        if table(rec)[1]:
            sizes.append((f"cd{rec}", len(table(rec)[1])))
    sizes.append(("cdcode", len(cd_block(VOICE_WIN)[0])))
    sizes.append(("klostcode", len(klost_block(VOICE_WIN)[0])))
    sizes.append(("vfixcode", len(vfix_block(VOICE_WIN, fhold=VOICE_WIN, klost=(VOICE_WIN, VOICE_WIN))[0])))
    room = [b - a for a, b, _ in OVERFLOW_RUNS]
    for pick in itertools.product(range(len(room)), repeat=len(sizes)):
        used = [0] * len(room)
        for (_, n), i in zip(sizes, pick):
            used[i] += n
        if all(u <= r for u, r in zip(used, room)) and pick[[k for k, _ in sizes].index("cdcode")] == len(room) - 1:
            return {k: i for (k, _), i in zip(sizes, pick)}
    return None


def overflow_tables(magics=None):
    """{rec: (module-relative pointer, bytes, in the act files too)} placed first-fit in the
    voice bank's free runs (OVERFLOW_RUNS): OVERFLOW's tables and cue blocks, CD_OVERFLOW's
    cue blocks (keyed "cd<rec>"); `magics` = {rec: the module's magic bytes} stamps the
    blocks (the writer's job; the placer needs the addresses only)."""
    out, free = {}, [[a, b, shared] for a, b, shared in OVERFLOW_RUNS]
    magics = magics or {}
    runs = pack_runs()                                       # {key: run index}, every block fitting
    def place(key, rec, block):
        for i, run in enumerate(free):
            if (runs is None or runs[key] == i) and run[0] + len(block) <= run[1]:
                out[key] = (0x8000 + run[0], stamp(block, magics[rec]) if rec in magics else block, run[2])
                run[0] += len(block)
                return
        raise SystemExit(f"rec {rec}: no free run of the voice bank holds its {len(block)}-byte block "
                         f"(left: {', '.join(str(b - a) for a, b, _ in free)})")
    for rec in OVERFLOW:
        main, cd = table(rec)
        if main:
            place(rec, rec, main)
        if cd:
            place(f"cd{rec}", rec, cd)
    sig = sig_blob()[0]                                      # the face signatures: their own run (SIG_AT)
    if SIG_AT + len(sig) > SIG_END:
        raise SystemExit(f"the face signatures are {len(sig)} B, rec 54's tail at {SIG_AT:#x} holds {SIG_END - SIG_AT}")
    out["sigs"] = (0x8000 + SIG_AT, sig, False)
    for rec in CD_OVERFLOW:
        main, cd = table(rec)
        if cd:
            place(f"cd{rec}", rec, cd)
    code, _ = cd_block(VOICE_WIN)                            # sized here, assembled at its place after
    place("cdcode", None, code)
    out["cdcode"] = (out["cdcode"][0], cd_block(VOICE_WIN + out["cdcode"][0] - 0x8000)[0], out["cdcode"][2])
    fh = cd_block(VOICE_WIN + out["cdcode"][0] - 0x8000)[1]["fhold"]
    code, _ = klost_block(VOICE_WIN)                         # (the first run's tail, the act files too)
    place("klostcode", None, code)
    kl_org = VOICE_WIN + out["klostcode"][0] - 0x8000
    out["klostcode"] = (out["klostcode"][0], klost_block(kl_org)[0], out["klostcode"][2])
    kl = klost_block(kl_org)[1]
    kl = (kl["klost"], kl["kclean"])
    code, _ = vfix_block(VOICE_WIN, fhold=fh, klost=kl)      # (#91) its own run
    place("vfixcode", None, code)
    out["vfixcode"] = (out["vfixcode"][0], vfix_block(VOICE_WIN + out["vfixcode"][0] - 0x8000, fhold=fh, klost=kl)[0], out["vfixcode"][2])
    return out


def module_blocks(rec, at, magic):
    """What a module carries for its subtitles: (the bytes at module-relative `at` - its table,
    then its cue block unless CD_OVERFLOW sends that to rec 54's bank -, SUBS_PTR's value,
    CUES_PTR's value); `magic` = the module's magic bytes (magic(new)), stamped into the block."""
    main, cd = table(rec)
    if rec in OVERFLOW:
        ot = overflow_tables()
        return b"", ot[rec][0] if main else 0, ot[f"cd{rec}"][0] if cd else 0
    main = stamp(main, magic) if main else main
    if not cd:
        return main, at if main else 0, 0
    if rec in CD_OVERFLOW:
        return main, at if main else 0, overflow_tables()[f"cd{rec}"][0]
    return main + stamp(cd, magic), at if main else 0, at + len(main)


def apply(out_path=P.OUT):
    pcepair.load_registry()           # the modules' pair tables as pcescript wrote them
    img = P.Image(out_path, P.T3 + P.RESERVE)
    base = (P.T2 + P.STAGE2) * P.DATA
    # the overflow tables into the voice bank's free runs: rec 54's first bank, and the act
    # files' for a run the act tables load over (0xFF in all of them)
    for rec, n in [OVERFLOW_REC] + ACT_RECS:
        old = bytes(S.block(rec, n))
        for a, b, shared in OVERFLOW_RUNS:
            if rec == OVERFLOW_REC[0] or shared:
                assert old[a:b] == bytes([0xFF]) * (b - a), f"rec {rec}'s {a:#x}-{b:#x} is not free"
    placed = json.load(open(os.path.join(WORK, "pce", "build_map.json")))
    magics = {}
    for rec in OVERFLOW + CD_OVERFLOW:
        r, n = placed.get(str(rec), [rec, 16])
        off = (S.T2 + r) * P.DATA
        magics[rec] = bytes(img.data[off + MAGIC:off + MAGIC + 2])
    for rec, (ptr, t, shared) in overflow_tables(magics).items():
        at = ptr - 0x8000
        into = [OVERFLOW_REC[0]] + ([r for r, _ in ACT_RECS] if shared else [])
        for r in into:
            obase = (S.T2 + r) * P.DATA
            assert bytes(img.data[obase + at:obase + at + len(t)]) == bytes([0xFF]) * len(t), f"rec {r} at {at:#x} is not pristine"
            img.write(obase + at, t)
        what = {"sigs": "the face signatures", "cdcode": "the CD-DA clock", "vfixcode": "the window's keeper (#91)", "klostcode": "the borrowed region's clear"}.get(rec) or f"rec {rec}'s {'cues' if str(rec).startswith('cd') else 'table'}"
        print(f"voice bank: {what}, {len(t)} B at {at:#06x}{' of rec 54 and the six act files' if shared else ' of rec 54'}")
    ps = patches()
    for at, old, new in ps:
        assert bytes(img.data[base + at:base + at + len(old)]) == old, f"stage 2 at {at:#x} is not pristine"
        img.write(base + at, new)
    # the face block, then the stub, into rec 110's first bank (its tail is 0xFF to the bank's end)
    block, _ = face_block()
    code, _ = stub()
    tail = bytearray(block) + bytes(stub_org() - FACE - len(block)) + code
    old = bytes(S.block(*SYSTEM))
    fill = bytes([0xFF]) * len(tail)
    assert old[FACE_OFF:FACE_OFF + len(tail)] == fill, "rec 110's tail is not free"
    rbase = (S.T2 + SYSTEM[0]) * P.DATA
    assert bytes(img.data[rbase + FACE_OFF:rbase + FACE_OFF + len(tail)]) == fill, "rec 110's tail is not pristine"
    img.write(rbase + FACE_OFF, bytes(tail))
    print(f"stage 2: the subtitle hook, {len(ps[0][2])} B of trampoline, the walker hook and the region copy, "
          f"{len(ps[2][2])} B in bank 1's tail; rec 110: the face block, {len(block)} B, "
          f"{len(faces_db())} characters known, the stub, {len(code)} B at {stub_org():#06x}; {img.flush()} sectors written")


def show(rec):
    lines = {k: v for k, v in json.load(open(os.path.join(ROOT, "pce", "translation", f"subs_{rec}.json"), encoding="utf-8")).items() if not k.startswith("_")}
    for key, spec in sorted(lines.items(), key=lambda kv: int(kv[0].split(".")[0], 16)):
        frames = duration_frames(rec, key)
        for face, tag in ((False, "plain"), (True, "face")):
            pg = pages(spec.get("speaker"), spec["en"], face, four_rows=rec not in NO_RESIDENT,
                       break_before=PAGE_BREAKS.get((rec, key)))
            print(f"{key} {tag} {frames:.0f}f {len(pg)} page(s): " + " | ".join("/".join(p) for p in pg))


MERGE_GAP = 1.0              # seconds between two CD-DA cues that may become one
MERGE_SPAN = 20.0            # seconds a merged cue may run (its pages are timed by their letters)
MERGE_DRIFT = 0.25           # seconds a merged cue's reveal may miss the start of a cue folded into it


def cue_drift(rec, merged):
    """How far a merged cue's words run from the voice: the cue reveals its cells at one rate
    from its start to its end, so each folded cue's first word comes up at start + its cells
    before * rate, against that cue's own start (Luiz, 2026-10-18: wrong sync is not
    acceptable - most merges missed by 0.5-7.7 s). The folded cues' starts are the merged cue's
    `seams`, [word index, seconds]. The worst miss, in seconds (0 for a cue with no seams)."""
    sp = merged.get("speaker")
    epi = rec in EPILOGUE
    plain = merged.get("layout", "face") == "plain" and not epi
    ranges = card_ranges(merged["en"], merged.get("cards"), sp, True, None, epi, plain, rec not in NO_RESIDENT)
    ch = card_chunks(merged["en"], ranges, rec not in NO_RESIDENT, sp, per_word=True,
                     layouts=[(False, 2)] if epi else None, plain=plain)
    before, cum = [], name_cost(sp) if sp else 0
    for t, cl in ch:                               # (row_words: one chunk a word)
        if t is not None:
            before.append(cum)
            cum += cost(t, cl)
    assert len(before) == len(merged["en"].replace("￥", " ").split()), merged["en"]
    rate = (merged.get("reveal_end", merged["end"]) - merged["start"]) / max(1, cum)
    return max((abs(merged["start"] + before[w] * rate - t) for w, t in merged.get("seams", [])), default=0.0)


def merge_cues(write=False):
    """The fewest cues (Luiz, 2026-10-18: "minimum amount of cues and longer cues if a character
    is speaking sequential stuff"): a run of CD-DA cues in a row on the same track, by the same
    speaker in the same layout, at most MERGE_GAP apart, is regrouped for the fewest pages, then
    the fewest cue breaks inside a sentence (the Chief's "If we hit the Snatcher hospital Gibson
    was after," / "we may be able to stop them..." fold into one), then the most cues - a cue
    ending a sentence keeps its own timing, as a cue's pages are timed by their letters. A
    merged cue runs at most MERGE_SPAN. The merged cue runs
    from the first's start to the last's end; the PS1 ids of the cues folded in go to `ps1_more`
    (pce_sync's recut appends a PS1 card the PCE lacks to the card before it, which is where
    they now are). The opening's cards are pceopening's."""
    import glob, functools
    tdir = os.path.join(ROOT, "pce", "translation")
    total = 0
    for path in sorted(glob.glob(os.path.join(tdir, "cdda_*.json"))):
        stem = os.path.basename(path)[5:-5]
        if not stem.isdigit():
            continue
        rec = int(stem)
        raw = open(path, encoding="utf-8", newline="").read()
        nl_ = "\r\n" if "\r\n" in raw else "\n"
        cues = json.loads(raw)
        po = rec in EPILOGUE

        def ranges(c):
            return card_ranges(c["en"], None, c.get("speaker"), True, None, po,
                               c.get("layout", "face") == "plain", rec not in NO_RESIDENT)

        def joins(a, c):
            return (a.get("en") and c.get("en") and a.get("track") == c.get("track")
                    and a.get("speaker") == c.get("speaker") and a.get("layout", "face") == c.get("layout", "face")
                    and 0 <= c["start"] - a["end"] <= MERGE_GAP)

        def fold(group):
            if len(group) == 1:
                return group[0]
            m = dict(group[0], en=" ".join(c["en"] for c in group), end=group[-1]["end"])
            seams, w = list(group[0].get("seams", [])), len(group[0]["en"].split())
            for c in group[1:]:
                seams += [[w, c["start"]]] + [[w + a, t] for a, t in c.get("seams", [])]
                w += len(c["en"].split())
            m["seams"] = seams
            more = list(group[0].get("ps1_more", []))
            for c in group[1:]:
                more += ([c["ps1"]] if c.get("ps1") else []) + list(c.get("ps1_more", []))
            if more:
                m["ps1_more"] = more
            notes = [c["note"] for c in group if c.get("note")]
            if notes:
                m["note"] = " / ".join(notes)
            m["cards"] = card_text(m["en"], ranges(m))
            return m

        out, n, i = [], 0, 0
        while i < len(cues):
            j = i + 1
            while j < len(cues) and joins(cues[j - 1], cues[j]):
                j += 1
            run = cues[i:j]

            @functools.lru_cache(maxsize=None)
            def best(a):
                if a == len(run):
                    return (0, 0, 0), ()
                opts = []
                for b in range(a + 1, len(run) + 1):
                    if b - a > 1 and run[b - 1]["end"] - run[a]["start"] > MERGE_SPAN:
                        break
                    g = fold(run[a:b]) if b - a > 1 else run[a]
                    if b - a > 1 and cue_drift(rec, g) > MERGE_DRIFT:
                        continue
                    pg = len(ranges(g))
                    (p2, m2, c2), rest = best(b)
                    # a cue break inside a sentence costs one; else the cues stay apart (each
                    # keeps its own timing: a cue's pages are timed by their letters)
                    mid = 1 if b < len(run) and not run[b - 1]["en"].rstrip().endswith((".", "?", "!")) else 0
                    opts.append(((pg + p2, mid + m2, c2 - 1), ((a, b),) + rest))
                return min(opts, key=lambda o: o[0])
            for a, b in best(0)[1]:
                out.append(fold(run[a:b]))
                n += b - a - 1
            i = j
        if n:
            print(f"{os.path.basename(path)}: {len(cues)} cues -> {len(out)}")
            total += n
            if write:
                text = json.dumps(out, ensure_ascii=False, indent=1).replace("\n", nl_) + (nl_ if raw.endswith(nl_) else "")
                open(path, "w", encoding="utf-8", newline="").write(text)
    print(f"{total} merges" + ("" if write else " (dry run: --write)"))


def write_cards(replan=False, kinds=("subs", "cdda")):
    """Every subs_<rec>.json and cdda_<rec>.json entry (of `kinds`) gets its `cards` (planned
    once; a card a hand has edited stays unless `replan`): the build draws them as written."""
    import glob
    tdir = os.path.join(ROOT, "pce", "translation")
    changed = 0
    for path in sorted(p for k in kinds for p in glob.glob(os.path.join(tdir, f"{k}_*.json"))):
        raw = open(path, encoding="utf-8", newline="").read()
        nl_ = "\r\n" if "\r\n" in raw else "\n"
        data = json.loads(raw)
        per_word = os.path.basename(path).startswith("cdda_")
        stem = os.path.basename(path)[5:-5]
        if not stem.isdigit():
            continue                      # (the opening's: pceopening wraps its own pages)
        rec = int(stem)
        entries = (data.items() if isinstance(data, dict) else enumerate(data))
        n = 0
        for key, spec in entries:
            if not isinstance(spec, dict) or not spec.get("en") or (isinstance(key, str) and key.startswith("_")):
                continue
            po = per_word and rec in EPILOGUE
            pl = spec.get("layout", "face") == "plain"
            if spec.get("cards") and not replan:
                card_ranges(spec["en"], spec["cards"], spec.get("speaker"), per_word, plain_only=po, plain=pl,
                            four=rec not in NO_RESIDENT)   # (still fits)
                continue
            brk = PAGE_BREAKS.get((rec, key)) if not per_word else None
            spec["cards"] = card_text(spec["en"], card_ranges(spec["en"], None, spec.get("speaker"), per_word, brk, po, pl,
                                                              rec not in NO_RESIDENT))
            n += 1
        if n:
            text = json.dumps(data, ensure_ascii=False, indent=1).replace("\n", nl_) + (nl_ if raw.endswith(nl_) else "")
            open(path, "w", encoding="utf-8", newline="").write(text)
            changed += n
            print(f"{os.path.basename(path)}: {n} entries carded")
    print(f"{changed} entries carded")


def review_cards(out=None):
    """Every line's pages as the stub draws them, in each layout it can pick (the face 4-row
    page = two cards stacked; the face 2-row and the plain page = one card, the plain one with
    the name first) -> work/pce/cards_review.txt, one block per line."""
    import glob
    out = out or os.path.join(WORK, "pce", "cards_review.txt")
    tdir = os.path.join(ROOT, "pce", "translation")
    lines = []
    for path in sorted(glob.glob(os.path.join(tdir, "subs_*.json")) + glob.glob(os.path.join(tdir, "cdda_*.json"))):
        data = json.load(open(path, encoding="utf-8"))
        per_word = os.path.basename(path).startswith("cdda_")
        stem = os.path.basename(path)[5:-5]
        rec = int(stem) if stem.isdigit() else None
        if rec is None:
            continue                       # the opening's cards: pceopening's own renderer
        epi = per_word and rec in EPILOGUE
        lines.append(f"==== {os.path.basename(path)}")
        for key, spec in (data.items() if isinstance(data, dict) else enumerate(data)):
            if not isinstance(spec, dict) or not spec.get("en") or (isinstance(key, str) and key.startswith("_")):
                continue
            sp = spec.get("speaker")
            lines.append(f"[{key}] {sp or '-'}")
            pl = spec.get("layout", "face") == "plain" and not epi
            res = rec not in NO_RESIDENT
            modes = ([("plain", False)] if epi or pl else [("face", True), ("plain", False)])
            lines[-1] += f" ({'plain' if pl or epi else 'face'})"
            for name, face in modes:
                rows = 4 if face and res else 2
                for i, page in enumerate(pages(sp, spec["en"], face, rows, res,
                                               cards=spec.get("cards"), per_word=per_word, plain_only=epi,
                                               plain=pl)):
                    lines.append(f"  {name:6} {i + 1}: " + " / ".join(r.strip() for r in page))
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"{out}: {len(lines)} lines")


def check_cards(files, every=False):
    """Hand-set cards checked (the editorial pass, Luiz 2026-10-18: "do the hard work and arrange
    the text like a proper translation"): per line its layout's limits, each card's rows with
    their cells, and the flags - ERROR (words or fit), PAGES (more cards than the planner's
    fewest), ROWEND (a row ending on an article, preposition, conjunction or possessive), NAME (a
    name cut between rows or cards), LONE (a row of one short word mid-sentence), MIDPAGE (a card
    turning mid-clause), SYNC (a merged CD-DA cue whose words drift from the voice). `every` prints every line, else the flagged ones. Returns the flag count."""
    from pcelayout import ROW_DEPENDENT
    tdir = os.path.join(ROOT, "pce", "translation")
    flags_total = 0
    for f in files:
        path = f if os.path.exists(f) else os.path.join(tdir, f)
        name = os.path.basename(path)
        stem = name.split("_", 1)[1][:-5]
        if not stem.isdigit():
            continue
        rec = int(stem)
        cd = name.startswith("cdda_")
        data = json.load(open(path, encoding="utf-8"))
        for key, spec in (data.items() if isinstance(data, dict) else enumerate(data)):
            if not isinstance(spec, dict) or not spec.get("en") or str(key).startswith("_") \
                    or spec.get("display") == "graphic":
                continue
            en, sp = spec["en"], spec.get("speaker")
            epi = cd and rec in EPILOGUE
            plain = spec.get("layout", "face") == "plain" and not epi
            four = rec not in NO_RESIDENT
            if epi or plain:
                nc = name_cost(sp) if sp else 0
                limit = f"plain: <= {PLAIN_ROWS} rows of {WIDTH_PLAIN} cells" + (f", the name ({nc}) on row 1" if nc else "")
            elif four:
                limit = f"face: <= {FACE_ROWS} rows of {WIDTH_FACE4} cells"
            else:
                nc = max(0, name_cost(sp) - (WIDTH_PLAIN - WIDTH_FACE)) if sp else 0
                limit = f"face (ending): <= {CARD_ROWS} rows of {WIDTH_FACE} cells" + (f", {nc} held on row 1" if nc else "")
            flags = []
            texts = en.replace("￥", " ").split()
            n = len(texts)
            try:
                ranges = card_ranges(en, spec.get("cards"), sp, cd, None, epi, plain, four)
            except SystemExit as e:
                ranges = None
                flags.append(f"ERROR {e}")
            fewest = len(card_ranges(en, None, sp, cd, PAGE_BREAKS.get((rec, key)), epi, plain, four))
            body = []
            if ranges:
                if len(ranges) > fewest:
                    flags.append(f"PAGES {len(ranges)} cards, {fewest} possible")
                for j, card in enumerate(ranges):
                    rows = []
                    for k, (a, b) in enumerate(card):
                        if cd:
                            c = sum(cost(t, cl) for t, cl in row_words(texts, a, b))
                        else:
                            c = (len(" ".join(texts[a:b])) + (1 if b < n else 0) + 1) // 2
                        rows.append(f"{' '.join(texts[a:b])} ({c})")
                        if b >= n:
                            continue
                        prev, nxt = texts[b - 1], texts[b]
                        last = k == len(card) - 1
                        if prev.lower() in ROW_DEPENDENT:
                            flags.append(f"ROWEND {prev!r} ends {'card' if last else 'row'} {j + 1}.{k + 1}")
                        if prev[:1].isupper() and nxt[:1].isupper() and not prev.endswith((".", "?", "!", ",", ":", ";")) \
                                and b - 1 > a:
                            flags.append(f"NAME {prev} / {nxt} at {j + 1}.{k + 1}")
                        if b - a == 1 and len(prev) < 8 and not prev.endswith((".", "?", "!", ",", ":", ";")):
                            flags.append(f"LONE {prev!r} at {j + 1}.{k + 1}")
                        if last and not prev.endswith((".", "?", "!", ",", ":", ";", "--")):
                            flags.append(f"MIDPAGE card {j + 1} ends on {prev!r}")
                    body.append(f"    {j + 1}: " + " | ".join(rows))
            if cd and ranges and spec.get("seams"):
                d = cue_drift(rec, spec)
                if d > MERGE_DRIFT:
                    flags.append(f"SYNC a merged cue's words miss the voice by {d:.2f} s (max {MERGE_DRIFT})")
            flags_total += len(flags)
            if every or flags:
                print(f"{name} [{key}] {sp or '-'} - {limit}; fewest {fewest}")
                print("\n".join(body))
                for fl in flags:
                    print(f"    ! {fl}")
    print(f"{flags_total} flags")
    return flags_total


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        args = [a for a in sys.argv[2:] if not a.startswith("--")]
        if not args:
            import glob
            args = sorted(glob.glob(os.path.join(ROOT, "pce", "translation", "subs_*.json"))
                          + glob.glob(os.path.join(ROOT, "pce", "translation", "cdda_*.json")))
        check_cards(args, "--all" in sys.argv)
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        show(int(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == "cards":
        write_cards("--replan" in sys.argv, tuple(k for k in ("subs", "cdda") if "--" + k in sys.argv) or ("subs", "cdda"))
    elif len(sys.argv) > 1 and sys.argv[1] == "merge":
        merge_cues("--write" in sys.argv)
    elif len(sys.argv) > 1 and sys.argv[1] == "review":
        review_cards()
    else:
        apply()
