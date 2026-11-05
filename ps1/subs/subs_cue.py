"""Subtitle payload keyed on the XA channel filter, carried in a scene bank.

Cue key
-------
The absolute disc position the driver polls into ctx+0x58C, matched against
each voice line's sector range. Two false starts are worth remembering:
CdlSetfilter is issued once per session, so it cannot key anything; and a
region picked from a single position sample gave the wrong scene entirely,
because interleaved streams put unrelated dialogue in neighbouring sectors.
The reliable way to build a cue table is to transcribe the candidate streams
(work/transcribe.py) and take the ones that are actually the scene - here
XAS_M000 channel 2, files 50-78, the whole Act 1 JUNKER HQ sequence.

Pieces
------
  exec 0x8009E228  trampoline (76 B): gate, check the HIRAM magic, call payload
  exec 0x8009E284  filter stub (36 B): gate into the high-RAM CD dispatcher
  exec 0x80078AA8  scene-loader hook (font slots 1012-1026): after the bank
                   loads, enqueue the scene's SUBS_BXXX.BIN read into HIRAM
  exec 0x80079158  per-scene blob table (font slots 1107-1117): lba|sectors<<20
  patched/SUBS_BXXX.BIN  MAGIC | current | code | args | cue table | strings
                   (appended sectors, loaded to HIRAM = 0x801F0000, 48 KB cap)

The bank itself is untouched now: the payload used to ride in its tail and
B010 ran out of room at 8 B (BUG-017).

Everything else follows the rules in CLAUDE.md: never touch sp, park ra in
high RAM, one nop after every lw.

    python ps1/subs/subs_cue.py on ps1/translation/subs_B010.json --scene B010
    python ps1/subs/subs_cue.py off ps1/translation/subs_B010.json --scene B010
"""
import json, os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import proto_sub as P
from sjis_enc import encode
from mipsasm import Asm, REG

SCENE = "ISZ_B010"                       # overridden by --scene BXXX
for _i, _a in enumerate(sys.argv):
    if _a == "--scene":
        SCENE = "ISZ_" + sys.argv[_i + 1]
BANK = os.path.join(ROOT, "patched", SCENE + ".BIN")
if not os.path.exists(BANK):                 # a bank with nothing to translate
    BANK = os.path.join(ROOT, "discs", "extracted_ps1", "PLN", "ISZ", SCENE + ".BIN")   # (B210: 3 strings)
SUBS_FILE = os.path.join(ROOT, "patched", "SUBS_" + SCENE[4:] + ".BIN")
BANK_RAM = 0x8010D000

# --- the high-RAM loader -------------------------------------------------
# The payload no longer rides in the scene bank (B010 ran out of room at
# 8 B). It is a file of its own, appended past the image end like a
# relocated bank, and the engine's scene loader is made to read it into
# high RAM right after the bank:
#
#   0x80051250  load_scene(ctx): enqueue(0xFE, lba, 0x8010D000, size,
#               callback=0x800512BC) via 0x8002C57C(index, dest, class 1,
#               callback). The CD queue at ctx+0x57C runs the read and the
#               worker (0x8002C52C) calls callback(ctx, 0) when it is done.
#   hook        replaces that callback pointer (the lui/addiu pair at
#               0x8005128C): clears the HIRAM magic, looks the scene up in
#               HOOK_TAB and, if it has a blob, enqueues a second read
#               {0xFE, lba, HIRAM, size, callback=done}; otherwise tail-
#               jumps to the original continuation.
#   done        writes the magic and tail-jumps to the continuation, so
#               the trampoline only ever sees a blob that fully arrived.
#
# HIRAM sits 60 KB under the stack page. NOT lower: the asset heap grows up
# from 0x801A6800 and reaches 0x801CF000 in B010 and B1E0 already, and an
# FMV has been seen clobbering 0x801D0800. The hook and its table live in
# font glyph slots whose kanji no string in any bank references any more
# (work/free_kanji_slots.json; pairfont refuses to draw into them).
from hiram import HIRAM, HIRAM_MAX, LONGS, LONGS_MAX   # lib/hiram.py: the two blobs' homes
LONGS_TAB = 0x80074380 + 18 * 2076       # font slots 2076-2086 (198 B): 40 x u32
LONGS_TAB_END = 0x80074380 + 18 * 2087   # lba | sectors << 20 of LONGS_<S>.BIN (0 = none)
LONGS_CODE = 0x80074380 + 18 * 3004      # font slots 3004-3012 (162 B): the second
LONGS_CODE_END = 0x80074380 + 18 * 3013  # read, chained from the loader hook's `done`
LONGS_FILE = os.path.join(ROOT, "patched", "LONGS_" + SCENE[4:] + ".BIN")
PREMAGIC = 0x00554253                    # 'SUB\0' on disc; `done` completes it
HOOK_CODE = 0x80078AA8                   # font slots 1012-1026, 270 B
HOOK_CODE_END = HOOK_CODE + 270
HOOK_TAB = 0x80079158                    # font slots 1107-1117 (198 B from
HOOK_TAB_END = 0x80079156 + 198          # 0x80079156, aligned up): 39 x u32
BAND_STUB = 0x80079E00                   # font slots 1287-1294 (142 B from
BAND_STUB_END = 0x80074380 + 18 * 1295   # 0x80079DFE, aligned up)
VOICE_STUB = BAND_STUB + 48              # second stub in the same slots
VOICE_TEST = 0x80048854                  # type-2 prepare: lw v0,0x1ACC(s0) /
                                         # lui v1,0x1000 / and / beqz -> "no
                                         # box open, skip the close". The
                                         # lui+and become a jump into
                                         # VOICE_STUB.
BAND2_STUB = 0x8007A2EC                  # font slots 1357-1362 (106 B from
BAND2_STUB_END = 0x80074380 + 18 * 1363  # 0x8007A2EA, aligned up)
BAND_OPEN_TEST = 0x800491D4              # the band open (task ctx+0x2048,
                                         # step 0x80049144): lw v0,0x1ACC(s0)
                                         # / lui v1,0x1000 / and / beqz ->
                                         # open directly, else slide the
                                         # dialogue box out first
                                         # (0x8004920C). Same shape as
                                         # VOICE_TEST; the lui+and become a
                                         # jump into BAND2_STUB.
CLOSE_GATE = BAND2_STUB + 60             # in BAND2_STUB's slack (36 B of 46)
CLOSE_CALL = 0x8004774C                  # type-0 handler's final jal
                                         # 0x80032654(task, entry): becomes
                                         # jal CLOSE_GATE (delay slot intact)
PRESS_STUB = 0x8007A184                  # font slots 1337-1340 (70 B from
PRESS_STUB_END = 0x80074380 + 18 * 1341  # 0x8007A182, aligned up)
PRESS_TEST = 0x80047CB4                  # type-0 WAIT step: bnez v0 (button
                                         # edge) -> close / (delay) addiu
                                         # s4,s0,0x22B0. Becomes j PRESS_STUB
                                         # with the delay slot intact.
MENU_STUB = 0x80079F78                   # font slots 1308-1314 (126 B)
MENU_STUB_END = 0x80074380 + 18 * 1315
MENU_SLIDE = 0x8004DB10                  # type-8 list-menu open step: sltiu
                                         # v1,ticks,0xF / beqz v1 -> finish /
                                         # (delay) sw a0,0x18(a2). Slides the
                                         # dialogue frame 15 ticks with no
                                         # "already open" test.
ENTRY_TEST = 0x800477B8                  # type-0 entry step: lw v0,0x1AF4(s0)
                                         # / lui v1,0x400 / and / beqz -> the
                                         # menu-close slide. The lui+and become
                                         # a jump into BAND_STUB.
LOADER_LUI = 0x8005128C                  # lui a3, 0x8005 / addiu a3, 0x12BC
CONT = 0x800512BC                        # the scene loader's continuation
ENQUEUE = 0x8002BF04                     # enqueue(cmd, arg, dest, size, cb@sp+0x10)
CD_READ = 0xFE
SCENE_IDX_OFF = 0x1DB8                   # ctx+0x1DB8 = scene table index
BANK_LIMIT = 0x80118000
MAGIC = 0x53554253                       # 'SUBS'
SCENE_TABLE = 0x4A68C
INTRO = SCENE == "ISZ_INTRO"             # the opening: no bank, its blob is
                                         # read by the boot load (HOOK_TAB slot
                                         # INTRO_SLOT) and lives in HIRAM until
                                         # B010's replaces it
INTRO_SLOT = 39
INTRO_ROW_DROP = 0                       # rows' home stays at 173/189/205
                                         # (Luiz: "the text itself was in a
                                         # good location"); since 2026-09-29
                                         # each card moves them (and the band)
                                         # down by its `y` where the picture
                                         # reaches below home (gen_intro.py
                                         # place), never up
INTRO_FILL_DROP = 12                     # the dark band 156-228 -> 168-240:
                                         # clear of Gillian's picture (bottom
                                         # 163), still behind the three rows
INTRO_FILL_SUB = int(os.environ.get("INTRO_FILL_SUB", "0xC0"), 0)
                                         # how dark the band is (GitHub #19):
                                         # the engine's fill is black at half
                                         # blend (ABR 0: B/2 + F/2), and the
                                         # diagram screens run the full height
                                         # under it - white rows over a half-
                                         # dimmed circuit board. 255 = opaque
                                         # black (semi-transparency off);
                                         # 1..254 = subtractive blend (ABR 2:
                                         # B - F) with this grey, 0xC0 leaves
                                         # a quarter of the picture through;
                                         # 0 = the engine's own half blend
INTRO_FILL_BUCKET = int(os.environ.get("INTRO_FILL_BUCKET", "1"), 0)
INTRO_ROW_BUCKET = int(os.environ.get("INTRO_ROW_BUCKET", "0"), 0)
                                         # OT buckets for the band and the six
                                         # rows (engine: 4 and 2; buckets
                                         # draw 15 -> 0). The diagram screens'
                                         # scrolling readouts and rules are
                                         # not in the sprite tree and draw in
                                         # bucket 2 AFTER the rows: poked
                                         # live, a band at 3 or 2 still had
                                         # them across the text, at 1 or 0 it
                                         # hid the rows too. Band 1 + rows 0
                                         # is the clean one. -1 = engine's
SNAP_RANGES = ((0x1AC0, 0xC0), (0x22B0, 0xD00), (0x31F0, 0x80), (0x46B0, 0x360))
                                         # ctx ranges the sprite creation writes
                                         # (window flags, the dialogue sprites,
                                         # cursor and face slots; the task
                                         # block is NOT touched any more).
                                         # Measured on the pristine game (the
                                         # words 0x800459E8 changes in its
                                         # frame): sprites 0x22B0..0x2FB0 at
                                         # 0x40 each, two more at 0x31F0, the
                                         # slots 0x46B0..0x4934. Until v0.7 the
                                         # second range stopped at 0x2900, so
                                         # the sprites from 0x2900 on kept the
                                         # state the opening's copy gave them,
                                         # the game's own init skipped them
                                         # (state nibble set) and linked the
                                         # rest around them: after a New Game
                                         # Gaudi's keyboard drew only the
                                         # pressed key (GitHub #12).
SNAP_OFF = [sum(n for _, n in SNAP_RANGES[:k]) for k in range(len(SNAP_RANGES))]
SPRITES_FN = 0x800459E8                  # the window task's creation step:
SPRITES_LEN = 0x80046D94 - SPRITES_FN    # builds every dialogue sprite as a
SPRITES_LOAD = 0x80046D4C - SPRITES_FN   # child of the task in a1, then kicks
                                         # the UI-asset load (jal 0x8002C57C)
                                         # whose callback chain IS the game's
                                         # boot sequence (class 4 -> 0x80046D94
                                         # -> class 6 -> 0x80047224 -> the
                                         # main task's 0x8004726C steps and the
                                         # t9(0,0) boot load). The opening
                                         # calls a COPY with that jal blanked.
SNAP_TOTAL = sum(n for _, n in SNAP_RANGES)
# The snapshot buffer is a zero block INSIDE the blob (label "snap"): a fixed
# HIRAM + 0x2000 sat on top of the blob's own tail once the copied creation
# step was appended, and the snapshot overwrote the code it was about to run.
                                         # early init, restored by the preinit
SCENE_INDEX = INTRO_SLOT if INTRO else int(SCENE[5:], 16) // 0x10
STATE = os.path.join(ROOT, "work", "subs_state.json")
RELOC = os.path.join(ROOT, "work", "relocations.json")
SRC_IMG = os.path.join(ROOT, "discs/iso_ps1_jp", "Snatcher (Japan).bin")

TRAMP = 0x8009E228                       # only proven-dead exec region
FILTER_STUB = 0x8009E284                 # gate, after the 92-byte trampoline
BLOBPTR = 0x80117FFC                     # last word of every padded bank:
                                         # points at that bank's payload
REGION_END = 0x8009E2B0                  # 0x8009E2B0 onward is engine-written
HOOK = 0x8002AAE0                        # jal 0x8002C944 (service chain)
ORIG = 0x8002C944
FILTER_CALL = 0x8002C3A8                 # jal CdControl (direct Setfilter)
PUMP_CALL = 0x8002C4A4                   # jal CdControl (queued commands -
                                         # some Setfilters flow through here)
CDCONTROL = 0x8005E918

def hi(a):
    """lui half for a lw/sw with the sign-extended low half lo(a)."""
    return ((a + 0x8000) >> 16) & 0xFFFF


def lo(a):
    return a & 0xFFFF


SCRATCH = 0x801FC000                     # +0 tramp ra, +4 payload ra,
                                         # (was 0x801D0000: the opening's
                                         # credit roll grows the asset heap
                                         # over it and the filter capture
                                         # came back as text bytes; the blob
                                         # at 0x801F0000 survives, so scratch
                                         # and dispatcher moved above it,
                                         # 8 KB below the stack page)
CAND = SCRATCH + 8                       # debounce: candidate cue
COUNT = SCRATCH + 12                     #           frames seen
DWELL_SHIFT = 3                          # in sequence: span / 8 ...
DWELL_SHIFT_COLD = 2                     # opening a scene: span / 4 ...
DWELL_MIN = 6                            # ... but never fewer than this
LOOKAHEAD = 8                            # tolerate a missed line without
                                         # stalling the rest of the scene
AWAY = SCRATCH + 16                      # frames outside every cue
CLEARED = SCRATCH + 20                   # box already wiped for this menu
CLRFLAG = SCRATCH + 24                   # draw pass should chase a dismiss
REFRACT = SCRATCH + 40                   # countdown set by a clear; cold
                                         # accepts wait it out. Time-based:
                                         # music streams from the same sector
                                         # region, so the head never idles in
                                         # the real game and an idle-based
                                         # lift never fires there.
REFRACT_TIME = 150
MENUPEND = SCRATCH + 44                  # menu held long enough; clear when
                                         # the stream stops (wiping a subtitle
                                         # mid-line killed the whole greeting)
LASTLBA = SCRATCH + 36                   # last polled LBA: dwell only counts
                                         # frames where it moved, because real
                                         # playback advances while a parked
                                         # head sits still for seconds
CLEARSLOT = SCRATCH + 32                 # cue index+1 cleared by doclear;
                                         # blocked from relatching until the
                                         # head leaves its range
MENUCTR = SCRATCH + 28                   # consecutive frames of menu bit
MENU_HOLD = 20                           # menu this long = really the menu,
                                         # not the blip between two lines
TEXTBUF = SCRATCH + 0x100                # padded line, built per cue
CODES_PER_ROW = 18                       # the engine's own row width: the
                                         # body render_text call passes 0x12
                                         # cells. (11 was a guess measured in
                                         # a portrait layout and left the
                                         # right half of the box empty.)
CLEAR_AFTER = 240                        # ~4 s away = scene over
FILTER_FILE = SCRATCH + 48               # captured CdlSetfilter {file, chan}
FILTER_CHAN = SCRATCH + 52               # NOT +8/+12: those are CAND/COUNT,
FILTER_CTR = SCRATCH + 56                # which clobbered the first capture
S000LBA = SCRATCH + 60                   # integer LBA of the last captured
                                         # CdlSetloc (any queue-pump caller)
MARKER = SCRATCH + 64                    # dispatcher installed flag: holds MAGIC_MARK
MAGIC_MARK = 0x53550000                  # 'SU' in the high half; low half stays zero
ENTRY = 12                               # bytes per cue table entry:
                                         #  +0  u32 start LBA
                                         #  +4  u16 span, bit 15 = last line
                                         #  +6  u16 ident (chan<<8 | file)
                                         #  +8  u16 speaker, offset from blob
                                         #  +10 u16 text, offset from blob
                                         # It was 6 u32 fields = 24 B, all of
                                         # them oversized: spans are a few
                                         # thousand sectors, idents 16 bits,
                                         # and the strings sit inside a blob
                                         # that can never exceed 4 KB. Halving
                                         # it bought B080 the room for a whole
                                         # conversation.
CHAINT = SCRATCH + 68                    # frames since the anchor cue drew
PRIMET = SCRATCH + 72                    # frames left of the window-open
SAVED = SCRATCH + 76                     # 1 = the cold-draw patch is applied
REBUILD = SCRATCH + 108                  # ask for a panel rebuild next frame
FINALCLR = SCRATCH + 112                 # this clear ends a conversation, so
                                         # the window state goes back to the
                                         # scene's menu layout. Mid-exchange
                                         # clears must NOT: they happen
                                         # between two subtitles.
SAVEBUF = SCRATCH + 80                   # and these are the engine's own
                                         # values, restored when the box is
                                         # cleared (leaving ours in place
                                         # mispositioned the scene's next
                                         # native dialogue until the player
                                         # pressed something)
PRIME_WAIT = 60                          # cap on waiting for the layout
                                         # switch we queued to take effect
PHASE = SCRATCH + 120                    # whose text is in the box: 0 = not
                                         # ours, 1 = ours queued, 2 = ours
                                         # reached the wait state
# The type-0 dialogue handler (0x80047548) is a state machine on the task
# at ctx+0x1EC0: +0x10 is the step function, run every frame. Steps, from
# the disassembly (work/dis_t0steps.txt):
#   0x80047788 entry: show frame+fill (ctx+0x27B0/0x27F0), pick the open
#   0x8004783C open animation (0x1AF4 bit 26)
#   0x800478D0 fade-in, 15 ticks; sets bit 28 "box open"
#   0x80047978 show nameplate
#   0x800479D8 type-on, one cell per tick (speed table 0x800711F8)
#   0x80047C30 WAIT: a button press closes; OR bit 31 of the window word
#              (set by the handler when the text ends in the SJIS bytes of
#              the `＠Ｃ` code) closes by itself once the tick counter
#              passes 0x1F. Close = hide nameplate + rows, then
#   0x80047DC4 fade-out, 15 ticks; clears bit 28, hides frame+fill
#   0x80047E90 sets the done flag (ctx+0x1AC0 bit 1) and step = 0
# So the engine's own timed close is one bit away: set bit 31 while OUR
# text is in the box and the wait state runs the game's real close path,
# per-layout bookkeeping included. That replaces the blank draw + node poke,
# which left the task parked in WAIT until the player's next press.
TASK_FN = 0x1ED0                         # ctx + 0x1EC0 + 0x10
STEP_WAIT = 0x80047C30
STEP_TYPE = 0x800479D8
STEP_CLOSE = 0x80047DC4                  # the slide-out
SLIDE = 120                              # the open slide: 15 ticks x 8 px
FACE_BAND_Y = 140                        # a face at y >= this sits in the band
KEEP = SCRATCH + 132                     # holds KEEP_MAGIC while the entry
KEEP_MAGIC = 0x4B454550                  # must NOT close the band ('KEEP')
KEEPCTR = SCRATCH + 136                  # frames left to hold it
KEEP2 = SCRATCH + 140                    # holds KEEP_MAGIC while our text is
                                         # up: the voice prepare then sees
                                         # "no box open" and does not close it
WSAVE = SCRATCH + 152                    # our row widths as first seen in WAIT
HANDOFF = SCRATCH + 144                  # the stub reports "menu took the box"
                                         # (+4/+8/+12: its register save,
                                         # +16/+20: the payload's row loop)
INTRO_DONE = SCRATCH + 180               # the opening's one-time row/fill
                                         # setup ran (holds INTRO_TAG)
FLUSHED = SCRATCH + 184                  # holds MAGIC once the I-cache has
                                         # been flushed for the blob now in
                                         # HIRAM; the loader hook zeroes it
                                         # with the magic. Every blob is code
                                         # assembled per scene and DMA'd over
                                         # the previous one at the same
                                         # address, and DMA does not touch the
                                         # R3000 I-cache: a line the loading
                                         # path did not evict ran the OLD
                                         # scene's instructions at the new
                                         # scene's addresses. Emulators do not
                                         # model the cache; PSIO (real CPU,
                                         # instant reads, fewest evictions)
                                         # froze on scene changes a few times
                                         # in a row, MiSTer (cache emulated,
                                         # drive timing too) rarely (#20).
ROWRESET = SCRATCH + 168                 # the pre-queue row reset: +0 rows
                                         # left, +4 row object, +8 saved t9
PARKED = SCRATCH + 128                   # frames the polled LBA has not moved
PARK_FRAMES = 45                         # playback advances 75 sectors/s, so
                                         # a head that sits still this long
                                         # has stopped: the line is over even
                                         # though it parked INSIDE the cue's
                                         # range (Harry's mechanic-room talk
                                         # ends that way, and no clear ever
                                         # fired - the box stayed open into
                                         # the verb menu)
FLUSHRA = SCRATCH + 188                  # flushgate's parked ra
FACEMODE = SCRATCH + 192                 # 1 while the face-left layout has
                                         # moved the portrait cels and rows
                                         # (so a band close or a real menu
                                         # can put them back)
# The face-left layout (`faceleft` bank option, GitHub #23): while the
# voice band is open, only the SPEAKING column's face stays on screen,
# parked at column 0's x, and the text rows and nameplate start to its
# right. A column is three cel objects (base, eyes, mouth) at
# ctx+0x4934 + 0x5C*(3*col+k); the cel renderer 0x80035DBC reads their
# +0x4E/+0x52 every frame, so writing all three moves the whole face (one
# slot alone moves a strip - the old "writing +0x52 moved nothing"). The
# speaking column is the menu word's bits 20-22 (script op 0x8004A000; the
# slot step 0x80049FAC animates the column that matches). The face box is
# 58 px at cel x+4, so the rows (prim template +0x30, 14 at rest) go to
# 92 and the nameplate (10 at rest) to 88: 12 cells to the frame's edge.
FACEX = SCRATCH + 204                    # while a faceleft payload runs:
                                         # FACE_HIDE_X << 16, and FACE_STUB
                                         # (in 0x80049904's two x sites)
                                         # places every new face there, so
                                         # the frame the band opens never
                                         # shows the native columns (the
                                         # payload runs AFTER the walk and
                                         # draw, 0x8002A2E4 then 0x8002AAAC);
                                         # the loader hook zeroes it per
                                         # bank, so no other scene inherits
QSAVE = SCRATCH + 212                    # +0/+4: the queue's name and text
QMODE = SCRATCH + 244                    # the queue's mode for this card (its
                                         # speaker's nameplate colour, from
                                         # the cue's prefix byte)
                                         # pointers across face_find
SHOWNT = SCRATCH + 248                   # frames since the current card was
                                         # queued (faceleft banks)
HOLDREQ = SCRATCH + 252                  # the minimum hold (2026-11-06): a
                                         # face card the script took down
                                         # before its reading time is up
                                         # (HOLD_MAGIC << 16 | frames since)
                                         # is drawn again, plain, once the
                                         # box has closed - see hold_frames()
HOLD_MAGIC = 0x484F                      # 'HO'
HOLD_PEND = 0x4850                       # 'HP': the latch forgotten, a requeue awaited
HOLD_RELATCH = 30                        # frames to wait for it before latching back
HOLD_EXPIRE = 90                         # frames a request waits for the close
HOLD_SETTLE = 4                          # frames after the band's close
HOLD_REQUEUE = not os.environ.get("NO_HOLD")


def hold_frames(text):
    """The card's reading time in frames: 20 characters a second, 1-3 s (the
    Saturn's rule, satsubs.hold_frames). B210's 'Who the hell are you?' and
    'What?!', B240's 'I know! And a good one!' were up 35-60 frames: the band
    closed with the speaker's face (the text goes with the face) while the
    voice still ran."""
    n = len(" ".join(text.replace("/n", " ").split()))
    return max(60, min(180, n * 3))


BAND_CLOSE_STEP = 0x800495F0             # the band task's (ctx+0x2048) close
                                         # step, set by its script walker
                                         # 0x80049510 at a line's end
TRACE = SCRATCH + 224                    # debug: the payload's last stage
                                         # (mark(); k0/k1 only), read by the
                                         # harness's DBGFRAMES
QHOLD = SCRATCH + 228                    # frames a card has waited for its
                                         # speaker's face (BUG-058, #40)
QHOLDIDX = SCRATCH + 232                 # the cue the wait belongs to
QHOLDT9 = SCRATCH + 236                  # the cue index across face_find
FFANY = SCRATCH + 240                    # 1: face_find matches a loaded
                                         # column whatever its cels show
QHOLD_MAX = 15                           # frames to wait (250 ms) before a
                                         # loaded-but-unshown speaker's card
                                         # goes plain after all
RA2 = SCRATCH + 220                      # hide_rows' return address around
                                         # its engine calls
PADW = SCRATCH + 208                     # the queue's row padding width:
                                         # cols with a face, 18 without
LAYOUT = SCRATCH + 200                   # the layout the current card was
                                         # typed with (0 not yet, 1 plain,
                                         # 2 face): a band opening under a
                                         # plain card would otherwise jump
                                         # its text right - retype instead
FACECOL = SCRATCH + 196                  # the column shown for the last
                                         # card (0-2, 3 = none): kept while
                                         # no card is up, so the face does
                                         # not blink between two cards
# Who is in a column: the room's face list ([ctx+0x1814], count at
# ctx+0x1828, filled by 0x8004CFB8 - class-4 file index per slot, the file
# loaded to 0x80135000 + slot*0x4800) maps a column's slot id
# (ctx+0x1AF8+col, s8, -1 = empty) to a CXN_* container, and the CXN files
# are one character per hundred: B0x0 Gillian (16 expressions), B1x0 Mika,
# B2x0 the Chief, B3x0 Harry, B4x0 Metal Gear, B5x0-BHx0 the rest of the
# cast (work/faces/cxn_sheet2.png). Class-4 indices 396..447 in the exec's
# table at 0x80073CF4. The script's own naming (bits 20-22) is only who it
# animates, and it names Gillian for Mika's front-desk lines and the
# listener for Metal's - 25 of 59 band cards in B010 - so the face shown
# is chosen by OUR cue's speaker instead: SPEAKER_CHAR gives the cue's
# character, stored as a byte in front of its interned name.
CXN_FIRST, CXN_CHARS = 396, "000000000000000011223334445556666666777789AABCDDEFGH"
SPEAKER_CHAR = {'Gillian': 0, 'Mika': 1, 'Chief': 2, 'Harry': 3, 'Metal Gear': 4,
                'Catherine': 5, 'Randam': 6, 'Jamie': 7, 'Madnar': 8, 'Napoleon': 0xA,
                'Chin': 0xB, 'Teller': 0xC}
# 0-4 seen in B010's captures; 5 = the only B5x0 room is Gibson's house
# (B0C0 loads B500/B520 and Catherine is its one other speaker); 6 = the
# morgue loads B600 for Randam (blond on the sheet, Chin is not); 7 and 8
# = the ending (B250) loads B7x0 and B800 with Jamie and Madnar speaking
# (the orange-haired girl and the grey-haired man). Still unlabelled (a
# speaker not in the table gets the nameplate and the full width, as
# before): 9 the blue Snatcher face, A a beast + Napoleon (BA10, bow
# tie; labelled for #69 - his plain cards parked the sneeze portrait
# every frame while the module moved it back), B a dark-haired man, C = the fortune teller (CXN_BC00: the wild
# hair and the hands raised over the crystal ball; #36 - her cards drew no
# portrait at all), D an old man (Madnar?),
# E bald with glasses (Joy Division loads it: the Clerk or the Cook),
# F Metal + a face, G a man in a coat, H the tricycle. Label each from a
# run of its scene: the SPKTRACE `files=` list against the cue speakers.
NO_CHAR = 0xFF                           # no portrait for this speaker
# The nameplate's colour is the engine's: the type-0 handler (0x80047548)
# draws the name in 0x800711BC[mode & 0x3F] (render_text's colour index:
# 0 white, 1 red, 2 blue, 3 cyan, 4 green, 5 yellow, 6 pink, 7 purple),
# and the script's mode for a named line is the speaker's name-table
# index + 1 (NAMETRACE on B010/B020/B0C0/B200: Metal Gear 0 -> 1,
# Gillian 3 -> 4, Mika 4 -> 5, Chief 5 -> 6, Catherine 10 -> 11, Randam
# 57 -> 58; mode 7 = Gaudi = the terminal, no plate). Until 2026-09-17
# every card queued the bank's own mode (menu_word bits 9-14: pink in
# B010, blue in the 14 banks on 0x83xx, white in the opening), so Harry's
# voice-over drew pink and Napoleon blue - "names without colour". The
# blob now carries the mode per cue (the pad byte behind the character
# code) and the queue passes it as args[1].
NAME_COLOURS = bytes.fromhex(            # 0x800711BC, 64 entries, by mode
    '00020306040605000505000700000000050000000603000000060501010606050600'
    '0504000200000000000002060003000000000005000000070100020101 00'.replace(' ', ''))
NAME_COLOUR_NAMES = ('white', 'red', 'blue', 'cyan', 'green', 'yellow', 'pink', 'purple')
# speakers the name table lacks (no game line ever names them): a colour
# nobody around them wears. Madnar speaks in the ending beside Jamie
# (yellow), Gillian (green), Metal Gear (blue) and Randam (red); Chin on
# his reel with Gillian and Metal; Gibson on his tape with Gillian, Metal
# and Catherine (purple); the Teller in Altamira; the rest are the game's
# white for bit parts (Man, Woman, Clerk, Announcer are white).
EXTRA_COLOURS = {'Madnar': 7, 'Chin': 3, 'Gibson': 3, 'Teller': 6,
                 'TV': 0, 'Cook': 0, 'Thug': 0, 'Waiter': 0}


def speaker_mode(speaker, bank_mode):
    """The mode (args[1] of the type-0 object) whose nameplate colour is the
    speaker's: the name-table index + 1 for a named speaker, else the lowest
    mode wearing EXTRA_COLOURS' colour; the bank's own mode for a speaker
    known nowhere (mode 7 is the terminal: never)."""
    from translate_names import NAMES
    if speaker in NAMES:
        m = NAMES.index(speaker) + 1
        if m != 7:
            return m
    if speaker in EXTRA_COLOURS:
        want = EXTRA_COLOURS[speaker]
        return next(m for m in range(64) if NAME_COLOURS[m] == want and m != 7)
    return bank_mode
SAME_TEXT = bytes([0xFF, 0xFF])                  # in place of a cue's 18-cell wrap:
                                         # use the 12-cell one (no SJIS
                                         # code starts with 0xFF)
FACE_X = 24                              # the speaker's face: column 0's x
FACE_HIDE_X = 400                        # the others: off-screen right (y is
                                         # left alone - the band close still
                                         # slides them and hides them)
FACE_COL_X = (24, 96, 168)               # the engine's own column x
ROW_X, ROW_X_FACE = 14, 92
NAME_X, NAME_X_FACE = 10, 88
BIOS_A0 = 0x800000A0                     # BIOS A0-table entry (KSEG0 mirror,
                                         # reachable by jalr from the exec)
BIOS_FLUSHCACHE = 0x44                   # A0:44 FlushCache()
FLUSHGATE = None                         # set when loader_hook() assembles
SCRATCH_BASE = ((SCRATCH + 0x8000) >> 16) << 16   # what lui hi(SCRATCH) gives:
                                         # every scratch offset is X - this
DISPATCH = 0x801FC800                    # high-RAM dispatcher, installed by
                                         # the payload, persists across scenes.
                                         # NOT 0x801D0100: that is TEXTBUF and
                                         # the first draw overwrote the code
                                         # with subtitle text (wedged auto34)


ROWS, COLS = 3, 36          # halves; the engine wraps at 18 cells
ROWS_NAME, COLS_NAME = 1, 12


def cellw(text):
    """Width of a row in glyph cells - what the box actually measures.

    A character count is NOT the width: ASCII pairs that own a packed glyph
    cost one cell for two letters, but the ~200 rare pairs with no slot fall
    back to fullwidth Latin at one cell per letter. "Jean-Jack Gibson's own"
    is 22 characters and 13 cells, so it overflowed an 11-cell box, the
    engine wrapped it itself, and the row after it was pushed out of a
    2-row box - which is every "missing second row" report.
    """
    # sjis_enc.encode appends the two-byte terminator: not a cell. Until
    # 2026-09-12 it was counted, so every wrap had one cell less than the
    # box (11 of 12, 17 of 18) and consolidate.py's ideal count, which
    # rebuild_pairs.py and check_cues.py now agree with, disagreed by one.
    return len(encode(text)) // 2 - 1


def wrap_only(text, rows, cols):
    """Word-wrap to the cell budget, but do NOT pad - the payload pads into
    a RAM buffer.

    Padding every line to the full block in the data cost about 35 bytes per
    cue, and a scene bank has only a few kilobytes of slack, which is what
    stopped the front-desk lines being added at all.
    """
    out = []
    budget = min(cols, CODES_PER_ROW)          # cells, not characters
    for para in text.split(chr(10)):
        words, line = para.split(), ""
        for w in words:
            cand = (line + " " + w).strip()
            if cellw(cand) <= budget:
                line = cand
            else:
                out.append(line)
                line = w
        out.append(line)
    if len(out) > rows:
        raise SystemExit(f"subtitle needs {len(out)} rows (max {rows}): {text!r}")
    return chr(10).join(out)


def pad_block(text, rows, cols):
    """Word-wrap to a fixed block of rows.

    The engine never clears the text canvas between lines - its own dialogue
    always overwrites the same area - so a short subtitle would leave the tail
    of the previous one on screen. Every line is therefore padded to the full
    block. Explicit /n marks a hard break; anything longer than `cols` is
    wrapped on word boundaries rather than cut, and overflow is reported so
    the line can be reworded instead of silently losing its end.
    """
    out = []
    for para in text.split(chr(10)):
        words, line = para.split(), ""
        for w in words:
            cand = (line + " " + w).strip()
            if len(cand) <= cols:
                line = cand
            else:
                out.append(line)
                line = w
        out.append(line)
    if len(out) > rows:
        raise SystemExit(f"subtitle needs {len(out)} rows (max {rows}): {text!r}")
    out = [ln.ljust(cols) for ln in out]
    while len(out) < rows:
        out.append(" " * cols)
    return chr(10).join(out)


def trampoline(blob_ram=None):
    """Per-frame gate: if a payload has fully arrived in HIRAM (its magic is
    only written by the loader hook's `done` callback), call it with ctx in
    $v0. blob_ram is unused (kept for the call signature)."""
    a = Asm(TRAMP)
    a.lui("$t0", 0x800B)
    a.lw("$t0", -0x409C, "$t0")
    a.lui("$t1", 0x8001)                       # fills the load delay
    a.bne("$t0", "$t1", "tail")                # ctx not the gameplay struct
    a.lui("$t2", HIRAM >> 16)                  # delay slot: blob base
    a.lw("$t3", HIRAM & 0xFFFF, "$t2")
    a.lui("$t1", MAGIC >> 16)                  # fills the load delay
    a.ori("$t1", "$t1", MAGIC & 0xFFFF)
    a.bne("$t3", "$t1", "tail")                # no (complete) payload loaded
    a.lui("$t4", hi(SCRATCH))                # delay slot
    a.sw("$ra", 0, "$t4")                      # park ra; never touch sp
    a.jal(FLUSHGATE)                           # I-cache flush, once per blob;
    a.nop()                                    # returns ctx in t0, base in t2
    a.addiu("$t5", "$t2", (HIRAM & 0xFFFF) + 8)
    a.jalr("$t5")
    a.or_("$v0", "$t0", "$zero")               # delay: hand ctx over
    a.lui("$t4", hi(SCRATCH))
    a.j(ORIG)
    a.lw("$ra", 0, "$t4")                      # delay: restore ra
    a.label("tail")
    a.j(ORIG)
    a.nop()
    return a.assemble()


def loader_hook():
    """Installed over the scene loader's callback pointer. Called by the CD
    worker as callback(ctx, 0) once the scene bank has been read.

    Table entry per scene index: lba | sectors << 20 (0 = no blob)."""
    a = Asm(HOOK_CODE)
    a.label("hook")
    a.lw("$t0", SCENE_IDX_OFF, "$a0")          # scene table index
    a.lui("$t1", HIRAM >> 16)
    a.sw("$zero", HIRAM & 0xFFFF, "$t1")       # magic := 0 (stale blob dies)
    a.lui("$t2", hi(SCRATCH))
    a.sw("$zero", FLUSHED - SCRATCH_BASE, "$t2")  # re-arm the I-cache flush
    a.sw("$zero", FACEX - SCRATCH_BASE, "$t2")    # faces at their native x
    a.bltz("$t0", "orig")                      # class-0 load (the game start,
    a.sll("$t2", "$t0", 2)                     # delay slot; not the boot: the
    a.lui("$t3", HOOK_TAB >> 16)               # INTRO blob rides the opening
                                               # overlay's load, INTRO_HOOK)
    a.ori("$t3", "$t3", HOOK_TAB & 0xFFFF)
    a.addu("$t3", "$t3", "$t2")
    a.lw("$t4", 0, "$t3")
    a.nop()
    a.beq("$t4", "$zero", "orig")              # this scene has no blob
    a.nop()
    a.addiu("$sp", "$sp", -0x18)               # a real frame: the engine's
    a.sw("$ra", 0x14, "$sp")                   # own callbacks do the same
    a.lui("$t5", HOOK_CODE >> 16)
    a._i(lambda pc, L: 0x34000000 | 13 << 21 | 13 << 16 | (L["done"] & 0xFFFF))
    a.sw("$t5", 0x10, "$sp")                   # 5th arg: callback = &done
    a.sll("$a1", "$t4", 12)
    a.srl("$a1", "$a1", 12)                    # lba = entry & 0xFFFFF
    a.srl("$a3", "$t4", 20)
    a.sll("$a3", "$a3", 11)                    # size = sectors * 2048
    a.ori("$a0", "$zero", CD_READ)
    a.lui("$a2", HIRAM >> 16)
    a.jal(ENQUEUE)
    a.ori("$a2", "$a2", HIRAM & 0xFFFF)        # delay slot: dest
    a.lw("$ra", 0x14, "$sp")
    a.addiu("$sp", "$sp", 0x18)
    a.jr("$ra")
    a.nop()
    a.label("orig")
    a.j(CONT)                                  # a0 = ctx, a1 = 0 untouched
    a.nop()
    a.label("done")                            # callback(ctx, 0): blob is in
    a.lui("$t1", HIRAM >> 16)
    a.lui("$t2", MAGIC >> 16)
    a.ori("$t2", "$t2", MAGIC & 0xFFFF)
    a.sw("$t2", HIRAM & 0xFFFF, "$t1")
    a.j(LONGS_CODE)                            # the bank's longs blob, then CONT
    a.nop()
    # flushgate: called by the trampoline (main context, never the CD
    # callback) once the magic reads SUBS. The first call after each blob
    # load invalidates the I-cache through the BIOS (A0:44 FlushCache); the
    # rest return at once. Clobbers what a BIOS call clobbers, so it hands
    # the trampoline its ctx (t0) and blob base (t2) back itself.
    a.label("flushgate")
    a.lui("$t4", hi(SCRATCH))
    a.lw("$t6", FLUSHED - SCRATCH_BASE, "$t4")
    a.lui("$t1", MAGIC >> 16)
    a.ori("$t1", "$t1", MAGIC & 0xFFFF)
    a.beq("$t6", "$t1", "flushed")
    a.sw("$ra", FLUSHRA - SCRATCH_BASE, "$t4")  # delay slot: park ra
    a.sw("$t1", FLUSHED - SCRATCH_BASE, "$t4")
    a.lui("$t2", BIOS_A0 >> 16)
    a.ori("$t2", "$t2", BIOS_A0 & 0xFFFF)
    a.jalr("$t2")
    a.ori("$t1", "$zero", BIOS_FLUSHCACHE)     # delay slot: t1 = 0x44
    a.lui("$t4", hi(SCRATCH))
    a.lw("$ra", FLUSHRA - SCRATCH_BASE, "$t4")
    a.label("flushed")
    a.lui("$t0", 0x800B)
    a.lw("$t0", -0x409C, "$t0")                # ctx again (the BIOS may
    a.jr("$ra")                                # have used t0; the trampoline
    a.lui("$t2", HIRAM >> 16)                  # reads it two instructions on)
    assert (a.labels()["done"] >> 16) == (HOOK_CODE >> 16)
    global FLUSHGATE
    FLUSHGATE = a.labels()["flushgate"]
    code = a.assemble()
    assert HOOK_CODE + len(code) <= HOOK_CODE_END, f"loader hook {len(code)} B overruns its slots"
    return code


def longs_hook():
    """Runs as the subs blob's `done` callback (a0 = ctx) once the magic is
    set: looks the scene up in LONGS_TAB and, if it has a longs blob,
    enqueues its read into LONGS with callback `done2` (which continues the
    scene); otherwise continues at once. The scene starts only after the
    last callback, so the remap group and the texts are in place before any
    string resolves."""
    a = Asm(LONGS_CODE)
    a.label("longs")
    a.lw("$t0", SCENE_IDX_OFF, "$a0")          # scene table index
    a.lui("$t3", LONGS_TAB >> 16)
    a.bltz("$t0", "cont")
    a.sll("$t2", "$t0", 2)                     # delay slot
    a.ori("$t3", "$t3", LONGS_TAB & 0xFFFF)
    a.addu("$t3", "$t3", "$t2")
    a.lw("$t4", 0, "$t3")
    a.nop()
    a.beq("$t4", "$zero", "cont")              # no longs for this scene
    a.nop()
    a.addiu("$sp", "$sp", -0x18)
    a.sw("$ra", 0x14, "$sp")
    a.lui("$t5", LONGS_CODE >> 16)
    a._i(lambda pc, L: 0x34000000 | 13 << 21 | 13 << 16 | (L["done2"] & 0xFFFF))
    a.sw("$t5", 0x10, "$sp")                   # 5th arg: callback = &done2
    a.sll("$a1", "$t4", 12)
    a.srl("$a1", "$a1", 12)                    # lba
    a.srl("$a3", "$t4", 20)
    a.sll("$a3", "$a3", 11)                    # size = sectors * 2048
    a.ori("$a0", "$zero", CD_READ)
    a.lui("$a2", LONGS >> 16)
    a.jal(ENQUEUE)
    a.ori("$a2", "$a2", LONGS & 0xFFFF)        # delay slot: dest
    a.lw("$ra", 0x14, "$sp")
    a.addiu("$sp", "$sp", 0x18)
    a.jr("$ra")
    a.nop()
    a.label("cont")
    a.j(CONT)
    a.nop()
    a.label("done2")                           # callback(ctx, 0): longs are in
    a.j(CONT)
    a.nop()
    assert (a.labels()["done2"] >> 16) == (LONGS_CODE >> 16)
    code = a.assemble()
    assert LONGS_CODE + len(code) <= LONGS_CODE_END, f"longs hook {len(code)} B overruns its slots"
    return code


INTRO_LUI = 0x8002A444                   # overlay-1 loader (the opening):
                                         # lui a3,0x8003 / addiu a3,-0x5A78 =
                                         # callback 0x8002A588. Retargeted to
                                         # INTRO_HOOK, which reads the INTRO
                                         # blob after the overlay and then
                                         # continues there.
INTRO_CONT = 0x8002A588
PREINIT_GATE = 0x80079C18                # font slots 1260-1264 (90 B)
PREINIT_GATE_END = 0x80074380 + 18 * 1265
PREINIT_CALL = 0x8002A484                # game start: jal 0x800458D4 (the
                                         # dialogue subsystem init, a0 = 0)
GAME_INIT = 0x800458D4
INTRO_TAG = 0x52544E49                   # 'INTR' at blob+16, then the
                                         # preinit routine's address at +20
INTRO_HOOK = 0x8007A0F4                  # font slots 1329-1335 (124 B from
INTRO_HOOK_END = 0x80074380 + 18 * 1336  # 0x8007A0F2, aligned up)


def preinit_gate():
    """In place of the game start's jal to the dialogue-subsystem init: if
    the INTRO payload is live (HIRAM magic, 'INTR' tag at blob+16), jump to
    its preinit routine first - it puts back what the opening borrowed so
    the init runs as at power-on - else straight to the init. a0 (0) and
    ra pass through untouched."""
    a = Asm(PREINIT_GATE)
    a.lui("$t0", HIRAM >> 16)
    a.lw("$t1", HIRAM & 0xFFFF, "$t0")
    a.lui("$t2", MAGIC >> 16)
    a.ori("$t2", "$t2", MAGIC & 0xFFFF)
    a.bne("$t1", "$t2", "orig")
    a.lw("$t1", (HIRAM & 0xFFFF) + 16, "$t0")
    a.lui("$t2", INTRO_TAG >> 16)
    a.ori("$t2", "$t2", INTRO_TAG & 0xFFFF)
    a.bne("$t1", "$t2", "orig")
    a.lw("$t1", (HIRAM & 0xFFFF) + 20, "$t0")
    a.nop()
    a.jr("$t1")
    a.nop()
    a.label("orig")
    a.j(GAME_INIT)
    a.nop()
    code = a.assemble()
    assert PREINIT_GATE + len(code) <= PREINIT_GATE_END, len(code)
    return code


def intro_hook(at):
    """Callback for the opening overlay's load: enqueue the INTRO blob
    (HOOK_TAB[INTRO_SLOT]) into HIRAM, `done` sets the magic, both continue
    to the overlay loader's own callback. The scene loader's negative-index
    load turned out to be the GAME start, after the opening."""
    a = Asm(at)
    a.lui("$t3", HOOK_TAB >> 16)
    a.ori("$t3", "$t3", HOOK_TAB & 0xFFFF)
    a.lw("$t4", INTRO_SLOT * 4, "$t3")
    a.lui("$t1", HIRAM >> 16)
    a.beq("$t4", "$zero", "orig")              # no INTRO blob built
    a.sw("$zero", HIRAM & 0xFFFF, "$t1")       # delay: magic := 0
    a.addiu("$sp", "$sp", -0x18)
    a.sw("$ra", 0x14, "$sp")
    a.lui("$t5", at >> 16)
    a._i(lambda pc, L: 0x34000000 | 13 << 21 | 13 << 16 | (L["done"] & 0xFFFF))
    a.sw("$t5", 0x10, "$sp")                   # 5th arg: callback = &done
    a.sll("$a1", "$t4", 12)
    a.srl("$a1", "$a1", 12)                    # lba
    a.srl("$a3", "$t4", 20)
    a.sll("$a3", "$a3", 11)                    # size
    a.ori("$a0", "$zero", CD_READ)
    a.lui("$a2", HIRAM >> 16)
    a.jal(ENQUEUE)
    a.ori("$a2", "$a2", HIRAM & 0xFFFF)
    a.lw("$ra", 0x14, "$sp")
    a.addiu("$sp", "$sp", 0x18)
    a.jr("$ra")
    a.nop()
    a.label("orig")
    a.j(INTRO_CONT)
    a.nop()
    a.label("done")
    a.lui("$t1", HIRAM >> 16)
    a.lui("$t2", MAGIC >> 16)
    a.ori("$t2", "$t2", MAGIC & 0xFFFF)
    a.sw("$t2", HIRAM & 0xFFFF, "$t1")
    a.j(INTRO_CONT)
    a.nop()
    assert (a.labels()["done"] >> 16) == (at >> 16)
    return a.assemble()


def filter_stub():
    """Thin gate at both retargeted CdControl call sites (direct Setfilter
    and the command-queue pump). Until the payload installs the high-RAM
    dispatcher and sets MARKER, everything passes straight through."""
    # The gate compares MARKER against MAGIC, not against zero: before any
    # bank has loaded, high RAM holds whatever the intro FMV player left
    # there, and a non-zero test sent the very first CD command after the
    # FMV into a dispatcher that was never installed - black screen, no
    # credit roll, no game (BUG-011). The lui fills the load-delay slot, so
    # the stub stays nine words and inside the dead region.
    a = Asm(FILTER_STUB)
    a.lui("$t2", hi(SCRATCH))
    a.lw("$t0", MARKER - SCRATCH_BASE, "$t2")
    a.lui("$t3", MAGIC_MARK >> 16)
    a.bne("$t0", "$t3", "thru")
    a.nop()
    a.j(DISPATCH)
    a.nop()
    a.label("thru")
    a.j(CDCONTROL)
    a.nop()
    return a.assemble()


MENU_PARK = DISPATCH + 0x40              # the menu park code, appended to
                                         # the dispatcher block in high RAM
                                         # (the exec-side gate jumps here
                                         # only while KEEP2 holds the magic,
                                         # i.e. only with a payload live)


def menu_park():
    """Reached from MENU_STUB on the list menu's first slide tick while our
    box is open. Parks the frame and fill in one go (+SLIDE, the mirror of
    the payload's instant open) so the menu's own 15-tick slide brings them
    in from where it expects them, sets HANDOFF for the payload, restores
    the step's registers and slides this tick."""
    a = Asm(MENU_PARK)
    a.lui("$at", hi(HANDOFF))
    a.sw("$ra", lo(HANDOFF + 4), "$at")
    a.sw("$a0", lo(HANDOFF + 8), "$at")
    a.sw("$a2", lo(HANDOFF + 12), "$at")
    a.addiu("$v0", "$zero", 1)
    a.sw("$v0", lo(HANDOFF), "$at")
    a.addiu("$a0", "$s0", 0x27B0)
    a.or_("$a1", "$zero", "$zero")
    a.addiu("$a2", "$zero", SLIDE)
    a.jal(0x80033848)
    a.ori("$a3", "$zero", 1)
    a.addiu("$a0", "$s0", 0x27F0)
    a.or_("$a1", "$zero", "$zero")
    a.addiu("$a2", "$zero", SLIDE)
    a.jal(0x80033848)
    a.ori("$a3", "$zero", 0xF)
    a.lui("$at", hi(HANDOFF))
    a.lw("$ra", lo(HANDOFF + 4), "$at")
    a.lw("$a0", lo(HANDOFF + 8), "$at")
    a.lw("$a2", lo(HANDOFF + 12), "$at")
    a.lui("$a1", 0x000F)
    a.ori("$a1", "$a1", 0xFFFF)                # a1 as the step left it
    a.j(MENU_SLIDE + 0xC)                      # 0x8004DB1C: slide this tick
    a.nop()
    return a.assemble()


CLOSE_FIX = MENU_PARK + 0x70                # after menu_park (100 B), in the
                                            # same high-RAM block


def close_fix():
    """Reached from CLOSE_GATE (the type-0 handler's final `jal
    0x80032654(task, entry)`) with a0 = the dialogue task, a1 = the entry
    step, ra = the handler's return. The handler resets the task to the
    entry step whatever it was doing; the entry step sees bit 28 still set
    and skips the slide-in. So a text queued while the box is closing (our
    timed close under the game's own text after a layout switch: B120's
    'You step inside...' 10 ticks into the slide-out, BUG-036) left frame and
    fill 8 px per missed tick too low for the rest of the scene. The game
    never queues over its own close (its bytecode waits on the done flag);
    our card is invisible to it. Finish the close here: slide the remaining
    ticks in one go and clear bit 28, so the entry slides in from parked."""
    a = Asm(CLOSE_FIX)
    a.lw("$t0", 0x10, "$a0")                   # step fn
    a.lui("$t1", STEP_CLOSE >> 16)
    a.ori("$t1", "$t1", STEP_CLOSE & 0xFFFF)
    a.bne("$t0", "$t1", "thru")
    a.lw("$t2", 0x18, "$a0")                   # ticks word (delay slot)
    a.lui("$t3", 0x000F)
    a.ori("$t3", "$t3", 0xFFFF)
    a.and_("$t2", "$t2", "$t3")                # k = slides done (1..15)
    a.addiu("$t4", "$zero", 15)
    a.subu("$t4", "$t4", "$t2")                # 15 - k left
    a.slt("$t8", "$zero", "$t4")               # any?
    a.beq("$t8", "$zero", "finish")
    a.sll("$a2", "$t4", 3)                     # dy = 8 * (15 - k)
    a.addiu("$sp", "$sp", -32)                 # synchronous context (the
    a.sw("$ra", 16, "$sp")                     # object-queue walker): the
    a.sw("$a0", 20, "$sp")                     # stack is fine here
    a.sw("$a1", 24, "$sp")
    a.sw("$a2", 28, "$sp")
    a.addiu("$a0", "$a0", 0x27B0 - 0x1EC0)     # the frame, task -> ctx+0x27B0
    a.or_("$a1", "$zero", "$zero")
    a.jal(0x80033848)
    a.ori("$a3", "$zero", 1)
    a.lw("$a0", 20, "$sp")
    a.lw("$a2", 28, "$sp")
    a.addiu("$a0", "$a0", 0x27F0 - 0x1EC0)     # the fill
    a.or_("$a1", "$zero", "$zero")
    a.jal(0x80033848)
    a.ori("$a3", "$zero", 0xF)
    a.lw("$ra", 16, "$sp")
    a.lw("$a0", 20, "$sp")
    a.lw("$a1", 24, "$sp")
    a.addiu("$sp", "$sp", 32)
    a.label("finish")
    a.addiu("$t5", "$a0", -0x1EC0)             # ctx
    a.lw("$t6", 0x1ACC, "$t5")
    a.lui("$t7", 0xEFFF)
    a.ori("$t7", "$t7", 0xFFFF)
    a.and_("$t6", "$t6", "$t7")                # bit 28 clear: closed for real
    a.sw("$t6", 0x1ACC, "$t5")
    a.label("thru")
    a.j(0x80032654)                            # set the entry step, as the
    a.nop()                                    # handler would
    return a.assemble()


def dispatcher():
    """Runs in place of CdControl for both hooked sites once installed.
    Captures Setfilter {file, chan} and Setloc (BCD msf decoded to an
    integer LBA in S000LBA). t-regs are caller-saved across CdControl, so
    clobbering them before the tail-call is safe."""
    a = Asm(DISPATCH)
    a.lui("$t2", hi(SCRATCH))
    a.addiu("$t3", "$zero", 0x0D)
    a.bne("$a0", "$t3", "notfilt")
    a.nop()
    a.lbu("$t0", 0, "$a1")
    a.lbu("$t1", 1, "$a1")
    a.sw("$t0", FILTER_FILE - SCRATCH_BASE, "$t2")
    a.j(CDCONTROL)
    a.sw("$t1", FILTER_CHAN - SCRATCH_BASE, "$t2")  # delay slot
    a.label("notfilt")
    a.label("out")
    a.j(CDCONTROL)
    a.nop()
    code = a.assemble()
    assert len(code) <= MENU_PARK - DISPATCH, len(code)
    park = menu_park()
    assert len(park) <= CLOSE_FIX - MENU_PARK, len(park)
    return (code + b"\x00" * (MENU_PARK - DISPATCH - len(code)) + park
            + b"\x00" * (CLOSE_FIX - MENU_PARK - len(park)) + close_fix())


def bcd_byte(a, off, dst, tmp1, tmp2):
    """dst = bcd(byte at ctx+off), with ctx in $t0."""
    a.lbu(dst, off, "$t0")
    a.nop()                                    # load delay
    a.srl(tmp1, dst, 4)
    a.andi(dst, dst, 15)
    a.sll(tmp2, tmp1, 3)
    a.sll(tmp1, tmp1, 1)
    a.addu(tmp1, tmp1, tmp2)
    a.addu(dst, dst, tmp1)


def mark(a, n):
    """Debug: TRACE := n (k0/k1 only, nothing else touched)."""
    a.addiu("$k0", "$zero", n)
    a.lui("$k1", hi(SCRATCH))
    a.sw("$k0", TRACE - SCRATCH_BASE, "$k1")


def payload(blob_ram, cues_at, args_at, blank_index=0, test_every=None,
            disp_at=0x80110000, disp_len=4, chain=None,
            clear_dismiss=True, menu_word=0x8701, rows=3,
            away_clear=True, mode=3, layout=0, cold_fields=(),
            clear_fields=(), clear_layout=0, cols=CODES_PER_ROW,
            intro=False, faceleft=False, noframe=False):
    # chain = [(anchor_idx, chain_idx, delay, window_end), ...] - all on one anchor
    # clear_dismiss: False = blank-only clear (scenes whose persistent
    # panel the dismiss damages); menu_word = the scene's verb-menu low16
    # mode = args[1] of the queued object: indexes the nameplate colour
    # table AND lands in bits 9-14 of the window word ctx+0x1ACC, i.e. it
    # selects the box layout variant. It must match the scene's own
    # dialogue mode (native win low16 bits 9-14: B010 0x87xx = 3, B020
    # 0x83xx = 1) - queueing mode 3 into B020 lost every subtitle's second
    # row and corrupted the scene's native lines after the voiced part.
    """Runs every frame with ctx in $v0; queues a line when the cue changes."""
    a = Asm(blob_ram + 8)
    RA = SCRATCH + 4
    if intro:
        # blob+8: j over the tag; +16 'INTR'; +20 the preinit routine
        a.j("start")
        a.nop()
        a._i(lambda pc, L: INTRO_TAG)
        a._i(lambda pc, L: L["preinit"])
        # Called from PREINIT_GATE at the game start, before the game's own
        # dialogue init (a0 = 0, s0 = ctx, ra = the caller's). The init
        # skips any task whose state nibble is set and any sprite likewise
        # (0x80032568 / 0x800328A4), so what we created during the opening
        # would leave the game with a window task that never signals and a
        # box that never draws (the game start stalled on a black screen).
        # Put the ctx back the way power-on left it: unlink the window task
        # (0x1EA4) and the dialogue task (0x1EC0) from the root task list
        # (ctx+0x17F0, next at +0), zero the state of every child sprite of
        # the window task (+4 chain), zero both tasks. Prims leak; once.
        a.label("preinit")
        a.lui("$t0", hi(SCRATCH + 156))
        a.addiu("$t1", "$zero", 0x1234)        # DEBUG marker: preinit ran
        a.sw("$t1", lo(SCRATCH + 156), "$t0")
        for T in ("task_t", 0x1EC0):
            a.addiu("$t0", "$s0", 0x17F0)      # prev: its +0 is the head
            if isinstance(T, str):             # our sprite parent task
                a._i(lambda pc, L: 0x3C0A0000 | (((L["task_t"] + 0x8000) >> 16) & 0xFFFF))
                a._i(lambda pc, L: 0x254A0000 | ((L["task_t"] - ((L["task_t"] + 0x8000) & ~0xFFFF)) & 0xFFFF))
                T = "t"
            else:
                a.addiu("$t2", "$s0", T)
            a.label(f"ul{T}")
            a.lw("$t1", 0, "$t0")
            a.nop()
            a.beq("$t1", "$zero", f"uld{T}")
            a.nop()
            a.bne("$t1", "$t2", f"uln{T}")
            a.nop()
            a.lw("$t3", 0, "$t1")
            a.nop()
            a.b(f"uld{T}")
            a.sw("$t3", 0, "$t0")              # prev.next = node.next
            a.label(f"uln{T}")
            a.b(f"ul{T}")
            a.or_("$t0", "$t1", "$zero")
            a.label(f"uld{T}")
        for i in range(0, 0x1C, 4):                      # the dialogue task,
            a.sw("$zero", 0x1EC0 + i, "$s0")             # as power-on left it
        for k, (base, size) in enumerate(SNAP_RANGES):   # put the ctx back
            a.addiu("$t1", "$s0", base)
            a._i(lambda pc, L, k=k: 0x3C0A0000 | ((L["snap"] + SNAP_OFF[k]) >> 16))
            a._i(lambda pc, L, k=k: 0x354A0000 | ((L["snap"] + SNAP_OFF[k]) & 0xFFFF))
            a.addiu("$t3", "$zero", size)
            a.label(f"rest{k}")
            a.lw("$t5", 0, "$t2")
            a.addiu("$t2", "$t2", 4)
            a.sw("$t5", 0, "$t1")
            a.addiu("$t1", "$t1", 4)
            a.addiu("$t3", "$t3", -4)
            a.bne("$t3", "$zero", f"rest{k}")
            a.nop()
        a.lui("$t0", HIRAM >> 16)
        a.sw("$zero", HIRAM & 0xFFFF, "$t0")   # and this payload is over
        a.j(GAME_INIT)
        a.nop()
        a.label("start")
    a.or_("$t0", "$v0", "$zero")               # ctx
    mark(a, 1)

    # Install the high-RAM CD-command dispatcher once. High RAM persists
    # across scene loads, so after the first frame of the first subtitled
    # scene the capture is live game-wide.
    # (Re)install when the marker is not MAGIC or the dispatcher's first
    # word is not its `lui $t2, SCRATCH_HI` - an in-game FMV can overwrite
    # high RAM without touching the marker.
    a.lui("$t4", hi(SCRATCH))
    a.lw("$t1", MARKER - SCRATCH_BASE, "$t4")
    a.lui("$t5", MAGIC_MARK >> 16)
    a.bne("$t1", "$t5", "dinst")
    a.lui("$t6", hi(DISPATCH))
    a.lw("$t1", lo(DISPATCH), "$t6")
    a.lui("$t5", 0x3C0A)
    a.ori("$t5", "$t5", hi(SCRATCH))
    a.beq("$t1", "$t5", "disp_ok")
    a.nop()
    a.label("dinst")
    a.lui("$t5", disp_at >> 16)                # embedded dispatcher copy
    a.ori("$t5", "$t5", disp_at & 0xFFFF)
    a.lui("$t6", DISPATCH >> 16)
    a.ori("$t6", "$t6", DISPATCH & 0xFFFF)
    a.addiu("$t7", "$zero", disp_len)
    a.label("dcopy")
    a.lw("$t1", 0, "$t5")
    a.addiu("$t5", "$t5", 4)
    a.sw("$t1", 0, "$t6")
    a.addiu("$t6", "$t6", 4)
    a.addiu("$t7", "$t7", -4)
    a.bne("$t7", "$zero", "dcopy")
    a.nop()
    a.lui("$t1", MAGIC_MARK >> 16)
    a.sw("$t1", MARKER - SCRATCH_BASE, "$t4")
    a.label("disp_ok")

    if intro:
        # The opening runs under the game ctx but before the game's own
        # init (0x800458D4, called with 0 from 0x8002A470 at game start):
        # the dialogue sprites do not exist yet (their prims are null). Do
        # the two pieces the type-0 path needs ourselves, once: the window
        # sprite task (0x80045978 creates frame, fill, nameplate, rows and
        # cursor on its next tick) and the dialogue task init (0x80047500).
        a.lw("$t1", 0x27F0 + 0x1C, "$t0")      # the fill's prim
        a.lw("$t2", 0x1EA4 + 0x10, "$t0")      # the window task's step
        a.bne("$t1", "$zero", "inited")
        a.nop()
        a.bne("$t2", "$zero", "inited")        # already scheduled
        a.nop()
        # Snapshot the ctx ranges the init writes (window flags, tasks, the
        # dialogue sprites, cursor and face slots) so the preinit can put
        # them back byte for byte before the game's own init.
        for k, (base, size) in enumerate(SNAP_RANGES):
            a.addiu("$t1", "$t0", base)
            a._i(lambda pc, L, k=k: 0x3C0A0000 | ((L["snap"] + SNAP_OFF[k]) >> 16))
            a._i(lambda pc, L, k=k: 0x354A0000 | ((L["snap"] + SNAP_OFF[k]) & 0xFFFF))
            a.addiu("$t3", "$zero", size)
            a.label(f"snap{k}")
            a.lw("$t5", 0, "$t1")
            a.addiu("$t1", "$t1", 4)
            a.sw("$t5", 0, "$t2")
            a.addiu("$t2", "$t2", 4)
            a.addiu("$t3", "$t3", -4)
            a.bne("$t3", "$zero", f"snap{k}")
            a.nop()
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        bits = int(os.environ.get("INTRO_INIT", "7"))
        if bits & 1:
            # The dialogue sprites, parented to a task of OUR OWN (task_t in
            # this blob, linked into the root list like ctx+0x1EA4 would be)
            # and built by the copied creation step with its asset-load kick
            # blanked - calling the real 0x80045978 started the game's boot
            # chain in the middle of the opening (the main task's 0x8004726C
            # steps, t9(0,0) with no bank load ever following).
            def la(reg, name):                 # reg := &label (lui/addiu)
                a._i(lambda pc, L, reg=reg, name=name: 0x3C000000 | REG[reg] << 16 | (((L[name] + 0x8000) >> 16) & 0xFFFF))
                a._i(lambda pc, L, reg=reg, name=name: 0x24000000 | REG[reg] << 21 | REG[reg] << 16 | ((L[name] - ((L[name] + 0x8000) & ~0xFFFF)) & 0xFFFF))
            # The copy runs as the task's STEP on the walker's next tick,
            # exactly as 0x80045978 arranges it - calling it directly from
            # this hook, outside the task walk, froze the frame counter at
            # once (prims made mid-frame, outside the walk).
            la("$a0", "task_t")
            la("$a1", "sprites")
            a.jal(0x80032568)                  # init the task with the step
            a.nop()
            la("$a0", "task_t")
            a.or_("$a1", "$zero", "$zero")     # parent: the root
            a.jal(0x80032288)
            a.ori("$a2", "$zero", 1)
        if bits & 2:
            a.jal(0x80047500)
            a.nop()
        if bits & 4:
            a.jal(0x80036704)                  # the text CLUT and VRAM slots
            a.nop()                            # (rows render blank without)
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t0", 0x800B)
        a.lw("$t0", -0x409C, "$t0")
        a.nop()
        a.label("inited")
        # and nothing else until the sprites exist
        a.lw("$t1", 0x27F0 + 0x1C, "$t0")
        a.nop()
        a.beq("$t1", "$zero", "ret")
        a.nop()

    # Track whether the dialogue box holds OUR text, from the task's step
    # function: 1 = queued (any step but WAIT may be our own open/type-on),
    # 2 = reached WAIT. From 2, any step other than WAIT means another
    # object (the game's own line) took the box, and step 0 means it closed.
    # The engine close below fires only while the phase is non-zero, so a
    # conversation-end clear can never auto-close a line the player is
    # meant to read.
    a.lui("$t4", hi(SCRATCH))
    a.lw("$t2", PHASE - SCRATCH_BASE, "$t4")
    a.lw("$t1", TASK_FN, "$t0")
    a.lui("$t3", STEP_WAIT >> 16)
    a.beq("$t2", "$zero", "phased")
    a.ori("$t3", "$t3", STEP_WAIT & 0xFFFF)
    a.bne("$t1", "$t3", "notwait")
    a.nop()
    # In WAIT. On the first WAIT frame remember our row widths (ctx+0x1AD0,
    # in cells); on later ones compare. Widths that change while the task
    # sits in WAIT were re-rendered by something that is not a type-0 - the
    # band open after a voice prepare renders its (empty) label rows into
    # the same widths and quads, and the canvas keeps our glyphs, so the
    # rows shrink to a letter each (BUG-013, "cropped text"). It lands
    # after our card on DuckStation, before it on Beetle. Forget the latch:
    # the accept path draws the card again over it.
    a.lbu("$t5", 0x1AD0, "$t0")
    a.lbu("$t6", 0x1AD1, "$t0")
    a.lbu("$t7", 0x1AD2, "$t0")
    a.sll("$t6", "$t6", 8)
    a.sll("$t7", "$t7", 16)
    a.or_("$t5", "$t5", "$t6")
    a.or_("$t5", "$t5", "$t7")                 # the three widths packed
    a.addiu("$t6", "$zero", 2)
    a.beq("$t2", "$t6", "waitcmp")
    a.nop()
    a.sw("$t5", WSAVE - SCRATCH_BASE, "$t4")        # first WAIT frame: remember
    a.sw("$t6", PHASE - SCRATCH_BASE, "$t4")
    # ... unless the widths are already a letter each: the band open's
    # label render landed DURING our type-on (DuckStation's order), so the
    # first WAIT frame would remember the crop and never redraw it (the
    # cropped long lines under the face-left layout, which keeps the band
    # open under every card). Rows of <= 1 cell are never a card of ours.
    a.lui("$t7", 0xFE)
    a.ori("$t7", "$t7", 0xFEFE)
    a.and_("$t7", "$t5", "$t7")
    a.bne("$t7", "$zero", "phased")
    a.lui("$t3", blob_ram >> 16)
    a.ori("$t3", "$t3", blob_ram & 0xFFFF)
    a.addiu("$t2", "$zero", -1)
    a.b("phased")
    a.sw("$t2", 4, "$t3")                      # shown := none -> redraw
    a.label("waitcmp")
    # Closed under us: the game closes the box through paths that never
    # touch the type-0 task (the layout switch at a conversation's end, the
    # band close), leaving it in WAIT with bit 28 clear and the frame
    # parked. The next press - or our bit-31 close - then ran the WAIT
    # close on a parked frame: a second +120 slide, and every box after
    # it sat 120 px lower, off the screen (Harry's conversation in B010
    # lost its box mid-way and for good). End the task ourselves, as
    # 0x80047E90 would, and let go.
    a.lw("$t6", 0x1ACC, "$t0")
    a.lui("$t7", 0x1000)
    a.and_("$t6", "$t6", "$t7")
    a.bne("$t6", "$zero", "waitopen")
    a.nop()
    a.sw("$zero", TASK_FN, "$t0")
    a.sw("$zero", PHASE - SCRATCH_BASE, "$t4")
    a.lbu("$t6", 0x1AC0, "$t0")
    a.nop()
    a.ori("$t6", "$t6", 2)
    a.sb("$t6", 0x1AC0, "$t0")
    # The rows are hidden but the text CANVAS still holds our glyphs, and
    # the verb menu that follows such a close draws its labels into the
    # same canvas without clearing it: Harry's last line stayed under
    # Move/Look/Check/Ask in B080 (BUG-022). Fill the canvas again
    # (0x80036704, the text init the opening already calls per render).
    a.lui("$t6", RA >> 16)
    a.sw("$ra", RA & 0xFFFF, "$t6")
    a.jal(0x80036704)
    a.nop()
    a.lui("$t6", RA >> 16)
    a.lw("$ra", RA & 0xFFFF, "$t6")
    a.lui("$t0", 0x800B)
    a.lw("$t0", -0x409C, "$t0")                # ctx again
    a.lui("$t4", hi(SCRATCH))
    a.b("phased")
    a.nop()
    a.label("waitopen")
    a.lw("$t6", WSAVE - SCRATCH_BASE, "$t4")
    a.nop()
    a.beq("$t5", "$t6", "phased")
    a.nop()
    a.sw("$t5", WSAVE - SCRATCH_BASE, "$t4")
    a.lui("$t3", blob_ram >> 16)
    a.ori("$t3", "$t3", blob_ram & 0xFFFF)
    a.addiu("$t2", "$zero", -1)
    a.b("phased")
    a.sw("$t2", 4, "$t3")                      # shown := none -> redraw
    a.label("notwait")
    a.addiu("$t5", "$zero", 1)
    a.bne("$t2", "$t5", "not1")
    a.lui("$t3", STEP_TYPE >> 16)
    a.ori("$t3", "$t3", STEP_TYPE & 0xFFFF)
    a.bne("$t1", "$t3", "phased")              # 1 and not typing: opening, or
    a.nop()                                    # queued and not dispatched yet
    # typing ours with every row a letter or less: the same crop as above,
    # caught while it types rather than after
    a.lbu("$t5", 0x1AD0, "$t0")
    a.lbu("$t6", 0x1AD1, "$t0")
    a.lbu("$t7", 0x1AD2, "$t0")
    a.or_("$t5", "$t5", "$t6")
    a.or_("$t5", "$t5", "$t7")
    a.sltiu("$t5", "$t5", 2)
    a.beq("$t5", "$zero", "phased")            # a real width: fine
    a.lui("$t3", blob_ram >> 16)
    a.ori("$t3", "$t3", blob_ram & 0xFFFF)
    a.addiu("$t2", "$zero", -1)
    a.b("phased")
    a.sw("$t2", 4, "$t3")                      # shown := none -> redraw
    a.label("not1")
    a.addiu("$t5", "$zero", 2)
    a.bne("$t2", "$t5", "phased")              # (0 handled above)
    a.nop()
    a.label("phase0")                          # 2 -> closed, or taken over
    a.sw("$zero", PHASE - SCRATCH_BASE, "$t4")
    # Taken over by a type-0 whose rows are a single cell or less each (a
    # blank or a bare punctuation line): same crop as above, through the
    # task. Draw ours again over it; a real line keeps the box.
    a.beq("$t1", "$zero", "phased")            # step 0: a real close
    a.lbu("$t2", 0x1AD0, "$t0")
    a.lbu("$t3", 0x1AD1, "$t0")
    a.lbu("$t5", 0x1AD2, "$t0")
    a.or_("$t2", "$t2", "$t3")
    a.or_("$t2", "$t2", "$t5")
    a.sltiu("$t2", "$t2", 2)
    a.beq("$t2", "$zero", "phased")            # real text: the game's line
    a.lui("$t3", blob_ram >> 16)
    a.ori("$t3", "$t3", blob_ram & 0xFFFF)
    a.addiu("$t2", "$zero", -1)
    a.sw("$t2", 4, "$t3")                      # shown := none -> redraw
    a.label("phased")
    mark(a, 2)

    # The band-keep hold: KEEP carries its magic for KEEPCTR frames after a
    # queue, long enough for the entry step to run, then goes back to 0.
    a.lw("$t2", KEEPCTR - SCRATCH_BASE, "$t4")
    a.nop()
    a.beq("$t2", "$zero", "keptdone")
    a.addiu("$t2", "$t2", -1)
    a.bne("$t2", "$zero", "keptdone")
    a.sw("$t2", KEEPCTR - SCRATCH_BASE, "$t4")
    a.sw("$zero", KEEP - SCRATCH_BASE, "$t4")
    a.label("keptdone")

    # Keep the box across lines. The voice object's prepare form (type 2,
    # args[0] = 0) closes the dialogue box if it finds bit 28 set
    # (0x80048854) before it opens the band for the next line - in the
    # game's design a box is never open when a voice line starts. The
    # patched test (VOICE_STUB) reads "no box" while KEEP2 holds the magic,
    # which is exactly while our text is up in WAIT (PHASE 2); the prepare
    # then skips to the band and the next card retypes into the open box.
    # (Hiding bit 28 from a pending node does not work: the node is queued
    # after this hook and dispatched before its next run.) Before this the
    # box slid off six frames after a card drew and the text sat on the
    # bare wall until the next card (BUG-016).
    # Held from the queue on (PHASE 1 as well as 2): a band opening during
    # our type-on found "a box" and closed it 40 frames into Harry's last
    # line in B080 (the retype after a press; BUG-022's second half).
    a.lw("$t2", PHASE - SCRATCH_BASE, "$t4")
    a.lui("$t1", KEEP_MAGIC >> 16)
    a.beq("$t2", "$zero", "keep2off")
    a.ori("$t1", "$t1", KEEP_MAGIC & 0xFFFF)
    a.b("keep2done")
    a.sw("$t1", KEEP2 - SCRATCH_BASE, "$t4")
    a.label("keep2off")
    a.sw("$zero", KEEP2 - SCRATCH_BASE, "$t4")
    a.label("keep2done")

    if faceleft and not intro:
        # The face-left layout (see FACE_X). Every frame while the band is
        # open (menu word bit 26): the column holding the current card's
        # speaker (face_find below) sits at FACE_X, every other column at
        # FACE_HIDE_X; with a face up the rows' template x goes to
        # ROW_X_FACE and the nameplate off-screen, without one rows and
        # nameplate sit at rest and the name says who talks. No card up,
        # or a live verb menu: the last card's column stays (FACECOL) and
        # the rows rest. Band closed: everything back once (FACEMODE) -
        # not before, a menu opening over the band slides it closed and
        # the faces would slide at their native x. The engine positions
        # the cels only at band open (0x80049904, through FACE_STUB) and
        # slides them at close (0x8004A0A0, y only), so an x written here
        # holds; the rows' template x is set once at creation (0x800459E8)
        # and by no step the box runs. FACEX keeps the stub live.
        a.lui("$t8", FACE_HIDE_X)
        a.sw("$t8", FACEX - SCRATCH_BASE, "$t4")
        if HOLD_REQUEUE:
            # The minimum hold. SHOWNT counts the current card's frames; a
            # pending HOLDREQ (set by hide_rows for a card younger than its
            # reading time) waits for the box to close (a band close in B010
            # closes it within frames; a face taken away arms the timed
            # close) or, the band gone and the box still up (B210's
            # close-ups), HOLD_SETTLE frames - then forgets the latch: if
            # the voice still plays inside the cue's range the matcher
            # queues it again, plain (no face up), as any next card. The
            # text still goes with the face; it comes back without one.
            a.lw("$t2", SHOWNT - SCRATCH_BASE, "$t4")
            a.nop()
            a.addiu("$t2", "$t2", 1)
            a.sw("$t2", SHOWNT - SCRATCH_BASE, "$t4")
            a.lw("$t2", HOLDREQ - SCRATCH_BASE, "$t4")
            a.addiu("$t7", "$zero", HOLD_MAGIC)
            a.srl("$t6", "$t2", 16)
            a.beq("$t6", "$t7", "hold_req")    # a request
            a.addiu("$t7", "$zero", HOLD_PEND)
            a.bne("$t6", "$t7", "hold_none")   # nothing pending
            a.nop()
            # the latch was forgotten: once something is up again (our
            # requeue, another card, a clear) it is done; if the matcher
            # did not take the cue again within HOLD_RELATCH frames (its
            # voice was over), latch it back, so the last-line and away
            # clears close its box as they would have
            a.lui("$t3", blob_ram >> 16)
            a.ori("$t3", "$t3", blob_ram & 0xFFFF)
            a.lw("$t6", 4, "$t3")
            a.nop()
            a.bgez("$t6", "hold_drop")
            a.nop()
            a.lw("$t6", SHOWNT - SCRATCH_BASE, "$t4")
            a.nop()
            a.sltiu("$t6", "$t6", HOLD_RELATCH)
            a.bne("$t6", "$zero", "hold_none")
            a.andi("$t6", "$t2", 0xFFFF)
            a.b("hold_drop")
            a.sw("$t6", 4, "$t3")              # shown := the card again
            a.label("hold_req")
            a.addiu("$t2", "$t2", 1)
            a.andi("$t6", "$t2", 0xFFFF)
            a.sltiu("$t6", "$t6", HOLD_EXPIRE)
            a.beq("$t6", "$zero", "hold_drop")  # waited too long: drop it
            a.sw("$t2", HOLDREQ - SCRATCH_BASE, "$t4")
            a.lw("$t6", PHASE - SCRATCH_BASE, "$t4")
            a.nop()
            a.beq("$t6", "$zero", "hold_go")    # the box closed: a fresh one
            a.nop()
            # the box stays open under a closed band (B210's close-ups:
            # the frame and the wait cursor stay up, our rows hidden):
            # HOLD_SETTLE frames after the band is gone, type it again
            # into that box, as any next card is
            a.lw("$t6", 0x1AF4, "$t0")         # menu word
            a.nop()
            a.srl("$t6", "$t6", 26)
            a.andi("$t6", "$t6", 1)
            a.bne("$t6", "$zero", "hold_back")  # band still open: wait,
            a.andi("$t6", "$t2", 0xFFFF)        # and count from its close
            a.sltiu("$t6", "$t6", HOLD_SETTLE)
            a.bne("$t6", "$zero", "hold_none")
            a.nop()
            a.label("hold_go")
            a.lui("$t3", blob_ram >> 16)
            a.ori("$t3", "$t3", blob_ram & 0xFFFF)
            # its face is gone for good: no QHOLD wait for it at the queue.
            # Only while it is still the card up: a clear (the blank, a
            # conversation's last line) or a forgotten latch since ends it
            a.lw("$t6", 4, "$t3")
            a.addiu("$t7", "$zero", blank_index)
            a.beq("$t6", "$t7", "hold_drop")
            a.nop()
            a.bltz("$t6", "hold_drop")
            a.addiu("$t7", "$zero", QHOLD_MAX)
            a.sw("$t6", QHOLDIDX - SCRATCH_BASE, "$t4")
            a.sw("$t7", QHOLD - SCRATCH_BASE, "$t4")
            a.addiu("$t2", "$zero", -1)
            a.sw("$t2", 4, "$t3")              # shown := none -> requeue
            a.sw("$zero", SHOWNT - SCRATCH_BASE, "$t4")
            a.lui("$t2", HOLD_PEND)
            a.or_("$t2", "$t2", "$t6")         # pending, with the card's index
            a.b("hold_none")
            a.sw("$t2", HOLDREQ - SCRATCH_BASE, "$t4")
            a.label("hold_drop")
            a.b("hold_none")
            a.sw("$zero", HOLDREQ - SCRATCH_BASE, "$t4")
            a.label("hold_back")
            a.lui("$t6", HOLD_MAGIC)
            a.sw("$t6", HOLDREQ - SCRATCH_BASE, "$t4")
            a.label("hold_none")
        a.lw("$t1", 0x1AF4, "$t0")             # menu word
        a.nop()
        a.srl("$t3", "$t1", 26)
        a.andi("$t3", "$t3", 1)                # bit 26: band open
        a.beq("$t3", "$zero", "face_off")
        a.nop()
        # The band's own close step (BAND_CLOSE_STEP, 15 ticks of the
        # face sliding out, then the box closes): the text goes the frame
        # the face starts to leave, once (LAYOUT 2 -> 1), and nothing else
        # is touched until the band is closed.
        a.lw("$t6", 0x2048 + 0x10, "$t0")
        a.lui("$t7", BAND_CLOSE_STEP >> 16)
        a.ori("$t7", "$t7", BAND_CLOSE_STEP & 0xFFFF)
        a.bne("$t6", "$t7", "face_live")
        a.nop()
        a.lw("$t2", PHASE - SCRATCH_BASE, "$t4")
        a.lw("$t6", LAYOUT - SCRATCH_BASE, "$t4")
        a.beq("$t2", "$zero", "face_done")     # no card
        a.addiu("$t7", "$zero", 2)
        a.bne("$t6", "$t7", "face_done")       # not a face card
        a.nop()
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.jal("hide_rows")
        a.nop()
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t4", hi(SCRATCH))
        a.addiu("$t7", "$zero", 1)
        a.b("face_done")
        a.sw("$t7", LAYOUT - SCRATCH_BASE, "$t4")
        a.label("face_live")
        # the current card's character: PHASE != 0 and shown != -1
        a.lw("$t2", PHASE - SCRATCH_BASE, "$t4")
        a.lw("$t5", FACECOL - SCRATCH_BASE, "$t4")   # default: the last
        a.beq("$t2", "$zero", "face_pick")
        a.addiu("$t9", "$zero", NO_CHAR)
        a.lui("$t3", blob_ram >> 16)
        a.ori("$t3", "$t3", blob_ram & 0xFFFF)
        a.lw("$t6", 4, "$t3")                  # shown cue index
        a.nop()
        a.bltz("$t6", "face_pick")
        a.sll("$t7", "$t6", 3)
        a.sll("$t6", "$t6", 2)
        a.addu("$t6", "$t6", "$t7")            # idx * ENTRY
        a.lui("$t7", (cues_at + 4) >> 16)
        a.ori("$t7", "$t7", (cues_at + 4) & 0xFFFF)
        a.addu("$t6", "$t6", "$t7")
        a.lhu("$t6", 8, "$t6")                 # speaker string offset
        a.nop()
        a.addu("$t6", "$t6", "$t3")
        a.lbu("$t9", 0, "$t6")                 # its character code
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.jal("face_find")                     # t5 = its column, or 3
        a.nop()
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.sw("$t5", FACECOL - SCRATCH_BASE, "$t4")
        a.label("face_pick")
        # t5 = the column to show (3 = none): place the nine cels. No card
        # up (t2 = PHASE 0) and no remembered column: the cels stay where
        # they are - nothing is written. The band open placed every column
        # at FACEX (FACE_STUB, 400: off-screen) and a card's queue moves
        # its speaker to FACE_X the frame it comes; a band the script opens
        # with no cue on it - Gillian's sneeze in the ruins, M000 f36 -
        # has its module write the cel's native (x, y) every 5th frame
        # BEFORE the walk builds the prims, and that write now holds. Until
        # 2026-09-14 this case parked every column at FACE_HIDE_X each
        # frame, so the sneeze showed one frame in five, each at a new y
        # (the "blink" of GitHub #38); the fix for #38 then wrote the
        # NATIVE x here each frame, and every band opened 10-20 frames
        # before its first card queued (the stream read, QHOLD) drew the
        # speaker at its native column - Mika on the right, then the jump
        # to the left (#40 reopened, 2026-09-14) - and the frames between
        # a card whose speaker had no face and the next one showed the
        # other columns back at their native x until the close.
        # A card whose speaker has no face here keeps the old rule (every
        # column off, plain layout): a native column sits on the text.
        a.addiu("$t9", "$zero", 3)
        a.bne("$t5", "$t9", "face_pick2")
        a.nop()
        a.beq("$t2", "$zero", "face_placed")   # no card, no column: hands off
        a.nop()
        a.label("face_pick2")
        a.addiu("$t6", "$t0", 0x4934)
        a.or_("$t7", "$zero", "$zero")         # column
        a.addiu("$t9", "$zero", 3)
        a.label("face_col")
        a.addiu("$t8", "$zero", FACE_HIDE_X)
        a.bne("$t7", "$t5", "face_colx")
        a.nop()
        a.addiu("$t8", "$zero", FACE_X)
        a.label("face_colx")
        for k in range(3):
            a.sh("$t8", 0x4E + 0x5C * k, "$t6")
        a.addiu("$t7", "$t7", 1)
        a.bne("$t7", "$t9", "face_col")
        a.addiu("$t6", "$t6", 0x5C * 3)
        a.label("face_placed")
        a.lw("$t2", PHASE - SCRATCH_BASE, "$t4")
        a.lbu("$t6", 0x1D7C, "$t0")            # a live verb menu: as no card
        a.addiu("$t7", "$zero", 0xF8)
        a.bne("$t6", "$t7", "face_nomenu")
        a.nop()
        a.or_("$t2", "$zero", "$zero")
        a.label("face_nomenu")
        a.addiu("$t8", "$zero", ROW_X)
        a.addiu("$t9", "$zero", NAME_X)
        a.beq("$t2", "$zero", "face_rows")     # no card: rows at rest
        a.addiu("$t3", "$zero", 1)
        a.addiu("$t2", "$zero", 3)
        a.addiu("$t7", "$zero", 1)             # this card's layout: plain
        a.beq("$t5", "$t2", "face_lay")        # no face: rows at rest, name on
        a.nop()
        a.addiu("$t8", "$zero", ROW_X_FACE)
        a.addiu("$t9", "$zero", FACE_HIDE_X)   # the face says who talks
        a.addiu("$t7", "$zero", 2)
        a.label("face_lay")
        a.lw("$t6", LAYOUT - SCRATCH_BASE, "$t4")
        a.nop()
        a.beq("$t6", "$zero", "face_lay1")     # not chosen yet
        a.nop()
        a.beq("$t6", "$t7", "face_rows")       # same as it was typed with
        a.addiu("$t6", "$zero", 2)
        a.beq("$t7", "$t6", "face_retype")     # plain -> face: the band opened
        a.nop()                                # after the queue, retype with it
        # face -> none under a face card: the script took the speaker's
        # face away, so the line is over for it - the text goes with the
        # face (rows and nameplate hidden now, the engine's timed close
        # armed) instead of retyping at full width and outliving it.
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.jal("hide_rows")
        a.nop()
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t4", hi(SCRATCH))
        a.lw("$t1", 0x1ACC, "$t0")
        a.lui("$t2", 0x8000)
        a.or_("$t1", "$t1", "$t2")
        a.sw("$t1", 0x1ACC, "$t0")             # bit 31: close when in WAIT
        a.b("face_lay1")
        a.addiu("$t7", "$zero", 1)
        a.label("face_retype")
        a.lui("$t6", blob_ram >> 16)
        a.ori("$t6", "$t6", blob_ram & 0xFFFF)
        a.addiu("$t2", "$zero", -1)
        a.sw("$t2", 4, "$t6")                  # shown := none -> requeue
        a.label("face_lay1")
        a.sw("$t7", LAYOUT - SCRATCH_BASE, "$t4")
        a.label("face_rows")
        a.b("face_set")
        a.sw("$t3", FACEMODE - SCRATCH_BASE, "$t4")
        a.label("face_off")
        # band closed. A live card here is in the plain layout: record
        # that (so a band opening later retypes it with the face), and if
        # it was typed with a face, retype it plain now rather than jump
        # its rows left under the reader.
        a.lw("$t2", PHASE - SCRATCH_BASE, "$t4")
        a.lw("$t6", LAYOUT - SCRATCH_BASE, "$t4")
        a.beq("$t2", "$zero", "face_off2")     # no card
        a.addiu("$t7", "$zero", 1)
        a.beq("$t6", "$zero", "face_offl")     # not chosen yet: plain
        a.nop()
        a.beq("$t6", "$t7", "face_off2")       # already plain
        a.nop()
        # a face card: the band closed under it, and every band close in
        # B010's run closed the box within two frames - so no retype (the
        # requeue reopened the box after the close and the text outlived
        # the face); hide rows and nameplate now, the close ends the card.
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.jal("hide_rows")
        a.nop()
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t4", hi(SCRATCH))
        a.addiu("$t7", "$zero", 1)
        a.label("face_offl")
        a.sw("$t7", LAYOUT - SCRATCH_BASE, "$t4")
        a.label("face_off2")
        a.lw("$t3", FACEMODE - SCRATCH_BASE, "$t4")
        a.nop()
        a.beq("$t3", "$zero", "face_done")     # nothing to undo
        a.addiu("$t2", "$zero", 3)
        a.sw("$zero", FACEMODE - SCRATCH_BASE, "$t4")
        a.sw("$t2", FACECOL - SCRATCH_BASE, "$t4")   # forget the column
        a.addiu("$t6", "$t0", 0x4934)
        for c in range(3):
            a.addiu("$t8", "$zero", FACE_COL_X[c])
            for k in range(3):
                a.sh("$t8", 0x4E + 0x5C * (3 * c + k), "$t6")
        a.addiu("$t8", "$zero", ROW_X)
        a.addiu("$t9", "$zero", NAME_X)
        a.label("face_set")
        a.lw("$t1", 0x2570 + 0x1C, "$t0")      # row 0's prim: none before
        a.nop()                                # the sprites exist
        a.beq("$t1", "$zero", "face_done")
        a.nop()
        for i in range(6):
            a.lw("$t1", 0x2570 + 0x40 * i + 0x1C, "$t0")
            a.nop()
            a.sh("$t8", 0x30, "$t1")           # template x (type 0xF)
        a.lw("$t1", 0x2530 + 0x1C, "$t0")      # the nameplate
        a.nop()
        a.sh("$t9", 0x30, "$t1")
        a.label("face_done")
        mark(a, 3)

    # ... and the band open that follows still hides the frame and fill
    # (at their open position, no slide). With our text up in WAIT and bit
    # 28 set, a hidden fill is that: show both again, the box is constant.
    if intro and not os.environ.get("INTRO_NOEXTRA"):
        # The opening: no box at all. The pictures reach y=190, the engine's
        # frame sits at 152-228, so the rows go below the picture (173/189/
        # 205 -> +20) and frame and fill stay hidden; plain subtitles on the
        # black band under the picture.
        # The nameplate is ctx+0x2530; the six row sprites start at 0x2570
        # (173/189/205 and the page-flip trio). The first build read a
        # bogus prim field as "row 0's y" and never dropped anything; the
        # second skipped row 0 (misread as the nameplate): rows 173/205/221.
        # Once (INTRO_DONE scratch): rows down by INTRO_ROW_DROP. (The
        # full-screen Snatcher diagram hides the rows whatever their OT
        # bucket: that still is not drawn through the OT at all - hiding
        # the overlay's own sprite changes nothing on screen - so its
        # narration card has to be baked into the picture, CXD_B0B0.BIN.)
        a.lui("$t4", hi(SCRATCH))
        a.lw("$t1", INTRO_DONE - SCRATCH_BASE, "$t4")
        a.lui("$t2", INTRO_TAG >> 16)
        a.ori("$t2", "$t2", INTRO_TAG & 0xFFFF)  # a magic, not a flag: the
        a.beq("$t1", "$t2", "rowsdown")           # scratch holds FMV residue
        a.nop()
        a.sw("$t2", INTRO_DONE - SCRATCH_BASE, "$t4")
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        for i in range(6):
            a.addiu("$a0", "$t0", 0x22B0 + 0x2C0 + 0x40 * i)
            a.or_("$a1", "$zero", "$zero")
            a.addiu("$a2", "$zero", INTRO_ROW_DROP)
            a.jal(0x80033848)
            a.ori("$a3", "$zero", 1)
            a.lui("$t0", 0x800B)
            a.lw("$t0", -0x409C, "$t0")
            a.nop()
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.label("rowsdown")
        a.lui("$t6", RA >> 16)                 # and no advance cursor: the
        a.sw("$ra", RA & 0xFFFF, "$t6")        # type-on shows it at the end
        a.addiu("$a0", "$t0", 0x470C)          # of every card
        a.or_("$a1", "$zero", "$zero")
        a.ori("$a2", "$zero", 1)
        a.jal(0x800358F0)
        a.ori("$a3", "$zero", 1)
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t0", 0x800B)
        a.lw("$t0", -0x409C, "$t0")
        a.nop()
        # Per-card placement (the cue's `y`, gen_intro.py place): the six
        # rows and the fill sit `y` px below home (rows 173/189/205) while
        # that card is the shown one. A byte per cue after the cue table
        # (intro_ytab), then the applied y and the pending delta - blob
        # words, so every load of the INTRO blob starts from home. Moves
        # are relative (0x80033848), as the engine's paired slides are,
        # and run the frame after the queue: the rows are zero-width then
        # (the pre-queue reset), the type-on starts on the next frame.
        ytab = intro_ytab(cues_at, blank_index + 1)
        yapplied = ytab + ((blank_index + 1 + 3) & ~3)
        a.lui("$t3", blob_ram >> 16)
        a.ori("$t3", "$t3", blob_ram & 0xFFFF)
        a.lw("$t2", 4, "$t3")                  # shown
        a.addiu("$t4", "$zero", -1)
        a.beq("$t2", "$t4", "placed")          # nothing shown
        a.nop()
        a.addiu("$t4", "$zero", blank_index)
        a.beq("$t2", "$t4", "placed")          # cleared: stay where it was
        a.nop()
        a.lui("$t6", ytab >> 16)
        a.ori("$t6", "$t6", ytab & 0xFFFF)
        a.addu("$t6", "$t6", "$t2")
        a.lb("$t5", 0, "$t6")                  # this card's y
        a.lui("$t6", yapplied >> 16)
        a.ori("$t6", "$t6", yapplied & 0xFFFF)
        a.lw("$t1", 0, "$t6")                  # where the rows are
        a.nop()
        a.beq("$t5", "$t1", "placed")
        a.subu("$t1", "$t5", "$t1")            # (delay slot) the move
        a.sw("$t5", 0, "$t6")
        a.sw("$t1", 4, "$t6")
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        for obj, mask in [(0x22B0 + 0x2C0 + 0x40 * i, 1) for i in range(6)] + [(0x27F0, 0xF)]:
            a.addiu("$a0", "$t0", obj)
            a.or_("$a1", "$zero", "$zero")
            a.lui("$a2", yapplied >> 16)
            a.ori("$a2", "$a2", yapplied & 0xFFFF)
            a.lw("$a2", 4, "$a2")
            a.jal(0x80033848)                  # (the jal is lw's delay slot)
            a.ori("$a3", "$zero", mask)
            a.lui("$t0", 0x800B)
            a.lw("$t0", -0x409C, "$t0")
            a.nop()
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.label("placed")
        # The fill stays as a dark band under the rows (the newspaper and
        # the diagrams reach below the picture edge and white text on them
        # is unreadable): once, at its open position, drop it by the same
        # amount plus the row gap. The gold frame is hidden whenever it
        # shows.
        a.lw("$t1", 0x27F0 + 0x1C, "$t0")      # the fill's prim
        a.nop()
        a.lh("$t1", 0x5A, "$t1")               # vertex 0 y (open: 156)
        a.lui("$t2", yapplied >> 16)           # load delay: without it the
        a.ori("$t2", "$t2", yapplied & 0xFFFF) # compare read the prim pointer
        a.lw("$t2", 0, "$t2")                  # ... + the card's placement
        a.nop()
        a.subu("$t1", "$t1", "$t2")
        a.addiu("$t1", "$t1", -156)
        a.bne("$t1", "$zero", "filldown")
        a.nop()
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.addiu("$a0", "$t0", 0x27F0)
        a.or_("$a1", "$zero", "$zero")
        a.addiu("$a2", "$zero", INTRO_FILL_DROP)
        a.jal(0x80033848)
        a.ori("$a3", "$zero", 0xF)
        a.lui("$t0", 0x800B)
        a.lw("$t0", -0x409C, "$t0")
        a.nop()
        # ... and darken it (#19). Same once-only path: 0x80032E54(obj,
        # semi, abr) sets flag bits 25-27 AND the semi-transparent bit of
        # the code byte in the fill's template POLY_G4 (prim+0x48; +0x4F
        # code, the two buffered copies at +0 and +0x24 are rebuilt from
        # it), and 0x80033094 would write the template's vertex colours
        # (+0x4C/0x54/0x5C/0x64) but reads its vertex mask off the caller's
        # stack frame - we have none, so the bytes go in directly.
        # (0x80032E30 only flips sprite-word bit 30: the band stayed half
        # blended with it clear.)
        if INTRO_FILL_SUB >= 255:
            a.addiu("$a0", "$t0", 0x27F0)
            a.or_("$a1", "$zero", "$zero")     # semi-transparency off:
            a.jal(0x80032E54)                  # opaque black
            a.or_("$a2", "$zero", "$zero")
        elif INTRO_FILL_SUB > 0:
            a.addiu("$a0", "$t0", 0x27F0)
            a.ori("$a1", "$zero", 1)
            a.jal(0x80032E54)                  # ABR 2: back - front
            a.ori("$a2", "$zero", 2)
            a.lui("$t0", 0x800B)
            a.lw("$t0", -0x409C, "$t0")
            a.nop()
            a.lw("$t1", 0x27F0 + 0x1C, "$t0")  # the fill's prim
            a.ori("$t2", "$zero", INTRO_FILL_SUB)
            for v in range(4):
                for c in range(3):
                    a.sb("$t2", 0x4C + 8 * v + c, "$t1")
        if INTRO_FILL_BUCKET >= 0:
            a.lui("$t0", 0x800B)
            a.lw("$t0", -0x409C, "$t0")
            a.nop()
            a.addiu("$a0", "$t0", 0x27F0)
            a.jal(0x80032D54)                  # OT bucket (flag bits 13-16)
            a.ori("$a1", "$zero", INTRO_FILL_BUCKET)
        if INTRO_ROW_BUCKET >= 0:
            for i in range(6):
                a.lui("$t0", 0x800B)
                a.lw("$t0", -0x409C, "$t0")
                a.nop()
                a.addiu("$a0", "$t0", 0x22B0 + 0x2C0 + 0x40 * i)
                a.jal(0x80032D54)
                a.ori("$a1", "$zero", INTRO_ROW_BUCKET)
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t0", 0x800B)
        a.lw("$t0", -0x409C, "$t0")
        a.nop()
        a.label("filldown")
        # A `noband` cue (span bit 14: the Snatcher diagram, whose narration
        # is baked into the still) gets no band: the engine's entry step
        # shows the fill with every card, so it is hidden again while that
        # cue is the shown one. (The rows never show over the still - the
        # picture is not drawn through the OT - but the band in bucket 1
        # does, across the baked card.)
        a.lui("$t3", blob_ram >> 16)
        a.ori("$t3", "$t3", blob_ram & 0xFFFF)
        a.lw("$t2", 4, "$t3")                  # shown
        a.addiu("$t4", "$zero", -1)
        a.beq("$t2", "$t4", "bandok")          # nothing shown
        a.nop()
        a.addiu("$t4", "$zero", blank_index)
        a.beq("$t2", "$t4", "bandok")          # cleared
        a.nop()
        a.sll("$t4", "$t2", 3)
        a.sll("$t5", "$t2", 2)
        a.addu("$t4", "$t4", "$t5")            # idx * ENTRY
        a.lui("$t6", (cues_at + 4) >> 16)
        a.ori("$t6", "$t6", (cues_at + 4) & 0xFFFF)
        a.addu("$t6", "$t6", "$t4")
        a.lhu("$t5", 4, "$t6")                 # span; bit 14 = noband
        a.nop()
        a.andi("$t5", "$t5", 0x4000)
        a.beq("$t5", "$zero", "bandok")        # not a noband cue
        a.nop()
        a.lw("$t1", 0x27F0 + 0x3C, "$t0")      # fill visible? hide it
        a.lui("$t3", 0x0100)
        a.and_("$t1", "$t1", "$t3")
        a.beq("$t1", "$zero", "bandok")
        a.nop()
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.addiu("$a0", "$t0", 0x27F0)
        a.jal(0x80032D9C)
        a.or_("$a1", "$zero", "$zero")
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t0", 0x800B)
        a.lw("$t0", -0x409C, "$t0")
        a.nop()
        a.label("bandok")
        a.lui("$t4", hi(SCRATCH))              # the code below keeps its
                                               # scratch base in t4
        a.lw("$t1", 0x27B0 + 0x3C, "$t0")      # frame visible? hide it
        a.lui("$t3", 0x0100)
        a.and_("$t1", "$t1", "$t3")
        a.beq("$t1", "$zero", "reshown")
        a.nop()
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.addiu("$a0", "$t0", 0x27B0)
        a.jal(0x80032D9C)
        a.or_("$a1", "$zero", "$zero")
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t0", 0x800B)
        a.lw("$t0", -0x409C, "$t0")
        a.lui("$t4", hi(SCRATCH))
        a.b("reshown")
        a.nop()
    if noframe and not intro:
        # A `noframe` cue (span bit 14 outside the opening; #80): the gold
        # frame stays hidden while it is the shown card - only the dimmed
        # fill under the rows. B260 loads the dynamite sprite into the
        # frame's unused inside in VRAM (x 448-494, y 2-54 of the sheet at
        # 384,0) before Metal Gear's bomb; the original never opens that
        # box there, so every card on it drew the dynamite in the box.
        # The re-show below would bring the frame back with the fill: for
        # these cards only the fill is re-shown.
        a.lui("$t3", blob_ram >> 16)
        a.ori("$t3", "$t3", blob_ram & 0xFFFF)
        a.lw("$t2", 4, "$t3")                  # shown
        a.addiu("$t5", "$zero", -1)
        a.beq("$t2", "$t5", "nf_off")          # nothing shown
        a.nop()
        a.addiu("$t5", "$zero", blank_index)
        a.beq("$t2", "$t5", "nf_off")          # cleared
        a.nop()
        a.sll("$t5", "$t2", 3)
        a.sll("$t6", "$t2", 2)
        a.addu("$t5", "$t5", "$t6")            # idx * ENTRY
        a.lui("$t6", (cues_at + 4) >> 16)
        a.ori("$t6", "$t6", (cues_at + 4) & 0xFFFF)
        a.addu("$t6", "$t6", "$t5")
        a.lhu("$t5", 4, "$t6")                 # span; bit 14 = noframe
        a.nop()
        a.andi("$t5", "$t5", 0x4000)
        a.beq("$t5", "$zero", "nf_off")        # an ordinary card
        a.nop()
        a.lw("$t1", 0x27B0 + 0x3C, "$t0")      # frame visible? hide it
        a.lui("$t3", 0x0100)
        a.and_("$t1", "$t1", "$t3")
        a.beq("$t1", "$zero", "nf_fill")
        a.nop()
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.addiu("$a0", "$t0", 0x27B0)
        a.jal(0x80032D9C)
        a.or_("$a1", "$zero", "$zero")
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t0", 0x800B)
        a.lw("$t0", -0x409C, "$t0")
        a.lui("$t4", hi(SCRATCH))
        a.label("nf_fill")
        a.lw("$t2", PHASE - SCRATCH_BASE, "$t4")
        a.lw("$t1", 0x1ACC, "$t0")
        a.addiu("$t2", "$t2", -2)
        a.bne("$t2", "$zero", "reshown")
        a.lui("$t3", 0x1000)
        a.and_("$t1", "$t1", "$t3")
        a.beq("$t1", "$zero", "reshown")       # bit 28 clear: closed for real
        a.lw("$t1", 0x27F0 + 0x3C, "$t0")
        a.lui("$t3", 0x0100)
        a.and_("$t1", "$t1", "$t3")
        a.bne("$t1", "$zero", "reshown")       # visible: nothing to do
        a.nop()
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.addiu("$a0", "$t0", 0x27F0)
        a.jal(0x80032D9C)
        a.ori("$a1", "$zero", 1)
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t0", 0x800B)
        a.lw("$t0", -0x409C, "$t0")
        a.lui("$t4", hi(SCRATCH))
        a.b("reshown")
        a.nop()
        a.label("nf_off")
    a.lw("$t2", PHASE - SCRATCH_BASE, "$t4")
    a.lw("$t1", 0x1ACC, "$t0")
    a.addiu("$t2", "$t2", -2)
    a.bne("$t2", "$zero", "reshown")
    a.lui("$t3", 0x1000)
    a.and_("$t1", "$t1", "$t3")
    a.beq("$t1", "$zero", "reshown")           # bit 28 clear: closed for real
    a.lw("$t1", 0x27F0 + 0x3C, "$t0")
    a.lui("$t3", 0x0100)
    a.and_("$t1", "$t1", "$t3")
    a.bne("$t1", "$zero", "reshown")           # visible: nothing to do
    a.nop()
    a.lui("$t6", RA >> 16)
    a.sw("$ra", RA & 0xFFFF, "$t6")
    a.addiu("$a0", "$t0", 0x27B0)
    a.jal(0x80032D9C)
    a.ori("$a1", "$zero", 1)
    a.lui("$t0", 0x800B)
    a.lw("$t0", -0x409C, "$t0")
    a.nop()
    a.addiu("$a0", "$t0", 0x27F0)
    a.jal(0x80032D9C)
    a.ori("$a1", "$zero", 1)
    a.lui("$t6", RA >> 16)
    a.lw("$ra", RA & 0xFFFF, "$t6")
    a.lui("$t0", 0x800B)
    a.lw("$t0", -0x409C, "$t0")
    a.lui("$t4", hi(SCRATCH))
    a.label("reshown")

    # The list menu took the box (MENU_STUB set HANDOFF): let go of it
    # without the slide - hide our nameplate and cursor, end the dialogue
    # task, forget the phase and latch the blank so no clear follows. The
    # frame and fill stay where they are as the menu's panel, and the ROWS
    # are the menu's too: it renders its labels into them (hiding them
    # here blanked every list menu in B020), and its own close parks the
    # frame when it is done.
    a.lw("$t2", HANDOFF - SCRATCH_BASE, "$t4")
    a.nop()
    a.beq("$t2", "$zero", "nohandoff")
    a.nop()
    a.sw("$zero", HANDOFF - SCRATCH_BASE, "$t4")
    a.sw("$zero", PHASE - SCRATCH_BASE, "$t4")
    a.sw("$zero", KEEP2 - SCRATCH_BASE, "$t4")
    a.lui("$t3", blob_ram >> 16)
    a.ori("$t3", "$t3", blob_ram & 0xFFFF)
    a.addiu("$t2", "$zero", blank_index)
    a.sw("$t2", 4, "$t3")                      # shown = blank: cleared
    a.sw("$zero", TASK_FN, "$t0")              # dialogue task: done
    a.lbu("$t2", 0x1AC0, "$t0")
    a.nop()
    a.ori("$t2", "$t2", 2)                     # the done flag, as 0x80047E90
    a.sb("$t2", 0x1AC0, "$t0")
    a.lui("$t6", RA >> 16)
    a.sw("$ra", RA & 0xFFFF, "$t6")
    a.addiu("$a0", "$t0", 0x2530)              # nameplate
    a.jal(0x80032D9C)
    a.or_("$a1", "$zero", "$zero")
    a.lui("$t0", 0x800B)
    a.lw("$t0", -0x409C, "$t0")
    a.nop()
    a.addiu("$a0", "$t0", 0x2570)
    a.jal(0x80032D9C)
    a.or_("$a1", "$zero", "$zero")
    a.lui("$t0", 0x800B)
    a.lw("$t0", -0x409C, "$t0")
    a.nop()
    a.addiu("$a0", "$t0", 0x470C)              # the advance cursor
    a.or_("$a1", "$zero", "$zero")
    a.ori("$a2", "$zero", 1)
    a.jal(0x800358F0)
    a.ori("$a3", "$zero", 1)
    a.lui("$t4", hi(SCRATCH))
    a.addiu("$t5", "$zero", 6)                 # six row sprites: hidden and
    a.sw("$t5", HANDOFF + 16 - SCRATCH_BASE, "$t4") # zero-width, as the close
    a.addiu("$t5", "$t0", 0x22B0 + 0x2C0)      # leaves them
    a.sw("$t5", HANDOFF + 20 - SCRATCH_BASE, "$t4")
    a.label("hiderow")
    a.lui("$t4", hi(SCRATCH))
    a.lw("$a0", HANDOFF + 20 - SCRATCH_BASE, "$t4")
    a.jal(0x80032D9C)
    a.or_("$a1", "$zero", "$zero")
    a.lui("$t4", hi(SCRATCH))
    a.lw("$a0", HANDOFF + 20 - SCRATCH_BASE, "$t4")
    a.or_("$a1", "$zero", "$zero")
    a.ori("$a2", "$zero", 0x10)
    a.jal(0x80033A18)
    a.ori("$a3", "$zero", 1)
    a.lui("$t4", hi(SCRATCH))
    a.lw("$t5", HANDOFF + 20 - SCRATCH_BASE, "$t4")
    a.lw("$t2", HANDOFF + 16 - SCRATCH_BASE, "$t4")
    a.addiu("$t5", "$t5", 0x40)
    a.sw("$t5", HANDOFF + 20 - SCRATCH_BASE, "$t4")
    a.addiu("$t2", "$t2", -1)
    a.bne("$t2", "$zero", "hiderow")
    a.sw("$t2", HANDOFF + 16 - SCRATCH_BASE, "$t4")
    a.lui("$t6", RA >> 16)
    a.lw("$ra", RA & 0xFFFF, "$t6")
    a.lui("$t0", 0x800B)
    a.lw("$t0", -0x409C, "$t0")
    a.lui("$t4", hi(SCRATCH))
    a.label("nohandoff")

    if not intro and not os.environ.get("NO_PANEL_FIX"):
        # BUG-042 (#18): the type-0 close hides frame and fill on its last
        # tick (0x80047E54/0x80047E60) and clears bit 28. A list menu that
        # opened while that close was still sliding has already run its own
        # show step (0x8004DA74) and its 15-tick slide, and sets bit 28
        # again at the end (0x8004DB74) - so the menu is live over a frame
        # and fill the close hid under it, and it draws with no panel at
        # all: the Act 2 HQ summons in the tricycle (B170's last cue) left
        # the destination list bare. MENU_STUB cannot see this one: our card
        # is already gone by then (KEEP2 cleared, PHASE 0), so the menu took
        # the engine's own path. Repair the state instead - a live menu
        # cursor with bit 28 set and the frame hidden is impossible in the
        # pristine game (checked on both sides of the summons) - and the
        # slides have already left both objects at their open y.
        a.lbu("$t2", 0x1D7C, "$t0")            # menu live and taking input?
        a.addiu("$t3", "$zero", 0xF8)
        a.bne("$t2", "$t3", "panelok")
        a.nop()
        a.lw("$t1", 0x1ACC, "$t0")
        a.lui("$t3", 0x1000)
        a.and_("$t1", "$t1", "$t3")
        a.beq("$t1", "$zero", "panelok")       # bit 28 clear: nothing open
        a.lw("$t1", 0x27B0 + 0x3C, "$t0")      # (delay slot) frame flags
        a.lui("$t3", 0x0100)
        a.and_("$t1", "$t1", "$t3")
        a.bne("$t1", "$zero", "panelok")       # visible: nothing to do
        a.nop()
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.addiu("$a0", "$t0", 0x27B0)
        a.jal(0x80032D9C)
        a.ori("$a1", "$zero", 1)
        a.lui("$t0", 0x800B)
        a.lw("$t0", -0x409C, "$t0")
        a.nop()
        a.addiu("$a0", "$t0", 0x27F0)
        a.jal(0x80032D9C)
        a.ori("$a1", "$zero", 1)
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t0", 0x800B)
        a.lw("$t0", -0x409C, "$t0")
        a.lui("$t4", hi(SCRATCH))
        a.label("panelok")

    if clear_fields:
        # Deferred panel rebuild requested by the clear: set the layout id
        # to something else first, or the type-3 handler early-returns on
        # "same id" and never calls the builder.
        a.lui("$t4", hi(SCRATCH))
        a.lw("$t2", REBUILD - SCRATCH_BASE, "$t4")
        a.nop()
        a.beq("$t2", "$zero", "norebuild")
        a.nop()
        a.sw("$zero", REBUILD - SCRATCH_BASE, "$t4")
        a.addiu("$t2", "$zero", -1)
        a.sw("$t2", 0x1AFC, "$t0")
        a.lui("$t5", args_at >> 16)
        a.ori("$t5", "$t5", args_at & 0xFFFF)
        a.sw("$zero", 0, "$t5")                # args[0] = 0: set-layout form
        a.lui("$t2", (clear_layout >> 16) & 0xFFFF)
        a.ori("$t2", "$t2", clear_layout & 0xFFFF)
        a.sw("$t2", 4, "$t5")
        a.sw("$zero", 8, "$t5")
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.or_("$a1", "$t5", "$zero")
        a.or_("$v0", "$t0", "$zero")
        a.jal(0x800364E0)
        a.ori("$a0", "$zero", 3)               # delay: type 3 = layout
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t0", 0x800B)                   # ctx again: t0 was clobbered
        a.lw("$t0", -0x409C, "$t0")
        a.nop()
        a.label("norebuild")

    if test_every:
        # Test rig only: fire the dismiss on a framectr cadence, but only when
        # the window word says a dialogue box is actually up (0x_048701 with
        # the menu bit clear) - firing with nothing open glitched the layout,
        # which is why the real path guards on a shown subtitle.
        a.lw("$t1", 0x18, "$t0")
        a.nop()
        a.andi("$t1", "$t1", test_every - 1)
        a.bne("$t1", "$zero", "notest")
        a.nop()
        a.lw("$t1", 0x1ACC, "$t0")
        a.nop()
        a.andi("$t2", "$t1", 0xFFFF)
        a.ori("$t3", "$zero", 0x8701)          # NOT addiu: 0x8701 sign-extends
        a.bne("$t2", "$t3", "notest")          # no box/window at all
        a.nop()
        a.lui("$t2", 0x0020)
        a.and_("$t1", "$t1", "$t2")
        a.beq("$t1", "$zero", "clearbox")      # box up, not the verb menu
        a.nop()
        a.label("notest")

    # The menu bit 0x00200000 in ctx+0x1ACC blips between dialogue lines but
    # holds while the verb menu actually waits for input. A subtitle drawn
    # into the menu layout has no panel and interleaves the menu labels, so:
    # count consecutive menu frames; at MENU_HOLD, clear any shown subtitle.
    a.lw("$t1", 0x1ACC, "$t0")
    a.lui("$t4", hi(SCRATCH))
    a.nop()
    a.andi("$t2", "$t1", 0x81FF)               # bits 9-14 are the last line's
    a.ori("$t3", "$zero", menu_word & 0x81FF)  # mode (its speaker's colour):
    a.bne("$t2", "$t3", "menuoff")             # the verb menu keeps them, so
    a.nop()                                    # 0x8B01 after Mika is B010's
                                               # 0x8701; talk UIs differ and
                                               # their voiced answers need subtitles
    # The window word is not enough: B020's escape cutscene runs with the
    # verb-menu word held and NO menu on screen, so every line was cleared at
    # its end and the box flickered open and shut (BUG-006). The engine's own
    # cursor word ctx+0x1D7C reads 0xF8 in its low byte only while a menu is
    # live and taking input (ps1/harness/menustate.py) - gate on that too.
    a.lbu("$t2", 0x1D7C, "$t0")
    a.addiu("$t3", "$zero", 0xF8)
    a.bne("$t2", "$t3", "menuoff")
    a.nop()
    a.lui("$t2", 0x0020)
    a.and_("$t1", "$t1", "$t2")
    a.beq("$t1", "$zero", "menuoff")
    a.nop()
    a.lw("$t2", MENUCTR - SCRATCH_BASE, "$t4")
    a.nop()
    a.addiu("$t2", "$t2", 1)
    a.sw("$t2", MENUCTR - SCRATCH_BASE, "$t4")
    a.addiu("$t3", "$zero", MENU_HOLD)
    a.bne("$t2", "$t3", "menudone")
    a.nop()
    a.addiu("$t2", "$zero", 1)                 # don't clear yet - voice may
    a.sw("$t2", MENUPEND - SCRATCH_BASE, "$t4")     # still be playing over the menu
    a.b("menudone")
    a.nop()
    a.label("menuoff")
    a.sw("$zero", MENUCTR - SCRATCH_BASE, "$t4")
    a.sw("$zero", MENUPEND - SCRATCH_BASE, "$t4")
    a.label("menudone")

    mark(a, 4)
    # --- absolute LBA from the driver's polled CdlGetlocL position --------
    bcd_byte(a, 0x58C, "$t1", "$t4", "$t5")    # minutes
    bcd_byte(a, 0x58D, "$t2", "$t4", "$t5")    # seconds
    bcd_byte(a, 0x58E, "$t3", "$t4", "$t5")    # frames
    a.sll("$t4", "$t1", 6)
    a.sll("$t5", "$t1", 2)
    a.subu("$t4", "$t4", "$t5")                # m * 60
    a.addu("$t4", "$t4", "$t2")                # + s
    a.sll("$t5", "$t4", 6)
    a.sll("$t6", "$t4", 3)
    a.addu("$t5", "$t5", "$t6")
    a.sll("$t6", "$t4", 1)
    a.addu("$t5", "$t5", "$t6")
    a.addu("$t5", "$t5", "$t4")                # * 75
    a.addu("$t5", "$t5", "$t3")                # + f
    a.addiu("$t5", "$t5", -150)                # $t5 = LBA
    a.lui("$t4", hi(SCRATCH))
    a.lw("$t2", LASTLBA - SCRATCH_BASE, "$t4")
    a.lw("$t3", PARKED - SCRATCH_BASE, "$t4")
    a.nop()
    a.bne("$t2", "$t5", "moved")
    a.nop()
    a.addiu("$t3", "$t3", 1)
    a.b("parkdone")
    a.sw("$t3", PARKED - SCRATCH_BASE, "$t4")       # delay slot
    a.label("moved")
    a.sw("$zero", PARKED - SCRATCH_BASE, "$t4")
    a.label("parkdone")
    a.sw("$t5", LASTLBA - SCRATCH_BASE, "$t4")

    # Data-sector reads and a parked head report file=0 chan=0 in the polled
    # record; a playing XA stream cycles real subheader values and never sits
    # at 0/0 (measured over the whole greeting in work/auto9). Those frames
    # are "no stream", so they earn no dwell - which is what let a data sweep
    # through Harry's sectors fire his last line during the front-desk scene.
    a.lbu("$t1", 0x594, "$t0")
    a.lbu("$t2", 0x595, "$t0")
    a.nop()
    a.or_("$t1", "$t1", "$t2")
    a.beq("$t1", "$zero", "nostream")
    a.nop()

    # --- find the cue matching position AND stream identity ---------------
    # Streams on different channels overlap in sectors (Mika's ch0
    # introduction sits inside Harry's ch2 ranges), so a position-first
    # match can land on the wrong cue; the filter check lives in the scan.
    a.lui("$t4", hi(SCRATCH))
    a.lw("$t3", FILTER_CHAN - SCRATCH_BASE, "$t4")
    a.lw("$t4", FILTER_FILE - SCRATCH_BASE, "$t4")
    a.sll("$t3", "$t3", 8)
    a.or_("$t4", "$t4", "$t3")                 # captured chan<<8 | file
    a.lui("$t6", cues_at >> 16)
    a.ori("$t6", "$t6", cues_at & 0xFFFF)
    a.lw("$t7", 0, "$t6")                      # count
    a.addiu("$t6", "$t6", 4)
    a.ori("$t8", "$zero", 0)                   # index
    a.addiu("$t9", "$zero", -1)                # found = none
    a.label("scan")
    a.beq("$t7", "$zero", "scanned")
    a.nop()
    a.lhu("$t2", 6, "$t6")                     # this cue's chan<<8 | file
    a.or_("$t3", "$t5", "$zero")               # pos = polled position
    a.andi("$t1", "$t2", 0xFF00)
    a.xori("$t1", "$t1", 0xFD00)               # chain cues never match by
    a.beq("$t1", "$zero", "next")              # position or identity
    a.nop()
    a.bne("$t2", "$t4", "next")                # a different stream is playing
    a.nop()
    a.label("havepos")
    a.lw("$t2", 0, "$t6")                      # start
    a.nop()
    a.sltu("$t1", "$t3", "$t2")
    a.bne("$t1", "$zero", "next")              # pos < start
    a.nop()
    a.lhu("$t1", 4, "$t6")                     # span, with `last` in bit 15
    a.nop()                                    # and `noband` in bit 14
    a.andi("$t1", "$t1", 0x3FFF)
    a.addu("$t2", "$t2", "$t1")                # end = start + span
    a.sltu("$t1", "$t3", "$t2")
    a.beq("$t1", "$zero", "next")              # pos >= end
    a.nop()
    a.label("found")
    mark(a, 51)
    a.or_("$t9", "$t8", "$zero")
    a.b("scanned")
    a.nop()
    a.label("next")
    a.addiu("$t6", "$t6", ENTRY)
    a.addiu("$t8", "$t8", 1)
    a.addiu("$t7", "$t7", -1)
    a.b("scan")
    a.nop()
    a.label("scanned")
    mark(a, 5)

    # --- act only when a *different* cue starts ---------------------------
    # The drive interleaves data reads with the audio, so the position leaves
    # the cue's range constantly. Treating that as "no line" made the subtitle
    # flicker and re-queue several times a second, so a miss is ignored and
    # the current line simply stays up until another cue begins.
    # Not inside any cue. During a conversation the head keeps dipping back
    # into the ranges, so this is only a lull; once it stays away the scene is
    # over and the box has to be wiped, otherwise the last subtitle sits on
    # top of the verb menu. The wipe uses the final table entry, which is a
    # deliberate blank line, and fires exactly once.
    a.addiu("$t2", "$zero", -1)
    a.bne("$t9", "$t2", "inside")
    a.nop()
    a.label("nostream")
    mark(a, 53)
    # The chain window: CHAINT counts frames since the anchor drew. Inside
    # the window with the chain line not yet shown, draw it - the VAG voice
    # has no CD signature, but the auto-sequence is frame-exact.
    # Several chain cues may hang off one anchor (a long VAG line split into
    # cards): each has its own [delay, wend) window on the same timer.
    if chain:
        a.lui("$t4", hi(SCRATCH))
        a.lw("$t2", CHAINT - SCRATCH_BASE, "$t4")
        a.nop()
        a.beq("$t2", "$zero", "nochain")
        a.nop()
        a.addiu("$t2", "$t2", 1)
        a.sw("$t2", CHAINT - SCRATCH_BASE, "$t4")
        for k, (anchor_i, chain_i, delay, wend) in enumerate(chain):
            a.sltiu("$t1", "$t2", delay)
            a.bne("$t1", "$zero", f"nochain{k}")   # too early
            a.nop()
            a.sltiu("$t1", "$t2", wend)
            a.beq("$t1", "$zero", f"nochain{k}")   # window over
            a.nop()
            a.addiu("$t9", "$zero", chain_i)
            a.b("accept")                          # skip the identity gate
            a.nop()
            a.label(f"nochain{k}")
    a.label("nochain")
    # The shown line is flagged as the last of its conversation and its
    # stream has stopped: clear now. Deterministic, unlike the menu-hold
    # and away timers, which only guess that an exchange is over.
    a.lui("$t3", blob_ram >> 16)
    a.ori("$t3", "$t3", blob_ram & 0xFFFF)
    a.lw("$t2", 4, "$t3")                      # shown
    a.addiu("$t4", "$zero", -1)
    a.beq("$t2", "$t4", "notlast")             # nothing shown
    a.nop()
    a.addiu("$t4", "$zero", blank_index)
    a.beq("$t2", "$t4", "notlast")             # already cleared
    a.nop()
    a.sll("$t4", "$t2", 3)
    a.sll("$t5", "$t2", 2)
    a.addu("$t4", "$t4", "$t5")                # idx * ENTRY
    a.lui("$t6", (cues_at + 4) >> 16)
    a.ori("$t6", "$t6", (cues_at + 4) & 0xFFFF)
    a.addu("$t6", "$t6", "$t4")
    a.lhu("$t5", 4, "$t6")                     # span; bit 15 = last line
    a.nop()
    a.andi("$t5", "$t5", 0x8000)
    a.beq("$t5", "$zero", "notlast")
    a.nop()
    a.lui("$t4", hi(SCRATCH))
    a.addiu("$t5", "$zero", 1)
    a.b("doclear")
    a.sw("$t5", FINALCLR - SCRATCH_BASE, "$t4")     # delay slot
    a.label("notlast")
    a.lui("$t4", hi(SCRATCH))
    a.lw("$t2", AWAY - SCRATCH_BASE, "$t4")
    a.nop()
    a.addiu("$t2", "$t2", 1)
    a.sw("$t2", AWAY - SCRATCH_BASE, "$t4")
    a.lw("$t3", MENUPEND - SCRATCH_BASE, "$t4")
    a.nop()
    a.bne("$t3", "$zero", "doclear")           # menu held and stream stopped
    a.nop()
    if away_clear:
        a.sltiu("$t3", "$t2", CLEAR_AFTER)     # threshold, not equality: a
        a.bne("$t3", "$zero", "ret")           # deferred clear must be able
        a.nop()                                # to retry on later frames
    else:
        a.b("ret")                             # scene-end clear comes from
        a.nop()                                # the menu path only
    a.label("doclear")
    a.lui("$t3", blob_ram >> 16)
    a.ori("$t3", "$t3", blob_ram & 0xFFFF)
    a.lw("$t2", 4, "$t3")                      # nothing shown -> nothing to do
    a.addiu("$t4", "$zero", -1)
    a.beq("$t2", "$t4", "ret")
    a.nop()
    a.b("clearbox")                            # shown is NOT forgotten here:
    a.nop()                                    # the accept path latches blank
                                               # only once the clear draws
    a.label("inside")
    mark(a, 52)
    a.lui("$t4", hi(SCRATCH))
    a.lw("$t2", PARKED - SCRATCH_BASE, "$t4")
    a.nop()
    a.sltiu("$t2", "$t2", PARK_FRAMES)
    a.beq("$t2", "$zero", "nochain")           # parked inside the range: the
    a.nop()                                    # stream is over (chain timers
                                               # keep their old no-stream rule)
    a.sw("$zero", AWAY - SCRATCH_BASE, "$t4")       # still in the conversation


    a.label("accept")
    mark(a, 6)
    a.lui("$t3", blob_ram >> 16)
    a.ori("$t3", "$t3", blob_ram & 0xFFFF)
    a.lw("$t2", 4, "$t3")
    a.nop()
    a.beq("$t2", "$t9", "ret")                 # same line already shown
    a.nop()
    if intro:
        # A `noband` cue with the SAME text as the shown card is its
        # continuation (gen_intro splits the card that straddles the
        # Snatcher diagram still at the still): adopt it as shown without
        # queuing - a retype paints glyphs into the text canvas, and that
        # VRAM lies inside the still's display area (the second half of
        # the baked card came out over-struck).
        a.addiu("$t4", "$zero", -1)
        a.beq("$t2", "$t4", "noadopt")         # nothing shown
        a.nop()
        a.addiu("$t4", "$zero", blank_index)
        a.beq("$t2", "$t4", "noadopt")         # cleared
        a.nop()
        a.sll("$t4", "$t9", 3)
        a.sll("$t5", "$t9", 2)
        a.addu("$t4", "$t4", "$t5")            # new idx * ENTRY
        a.lui("$t6", (cues_at + 4) >> 16)
        a.ori("$t6", "$t6", (cues_at + 4) & 0xFFFF)
        a.addu("$t6", "$t6", "$t4")
        a.lhu("$t5", 4, "$t6")                 # span; bit 14 = noband
        a.nop()
        a.andi("$t5", "$t5", 0x4000)
        a.beq("$t5", "$zero", "noadopt")
        a.lhu("$t5", 10, "$t6")                # its text (interned: equal
        a.sll("$t4", "$t2", 3)                 # text = equal offset)
        a.sll("$t1", "$t2", 2)
        a.addu("$t4", "$t4", "$t1")            # shown idx * ENTRY
        a.lui("$t1", (cues_at + 4) >> 16)
        a.ori("$t1", "$t1", (cues_at + 4) & 0xFFFF)
        a.addu("$t1", "$t1", "$t4")
        a.lhu("$t1", 10, "$t1")
        a.nop()
        a.bne("$t1", "$t5", "noadopt")
        a.nop()
        a.b("ret")
        a.sw("$t9", 4, "$t3")                  # shown := the continuation
        a.label("noadopt")


    # One subtitle at a time, and only block on a live dialogue object
    # (type 0): two of those stack, each re-applying the window state, which
    # makes the panel and portraits jump. Menus may coexist with a subtitle.
    # The cue is latched only once it is actually drawn - latching before the
    # check silently dropped the first line of every conversation, because at
    # that moment the game's own box was still up.
    # Skip only if a dialogue object (type 0) is already live: two of those
    # stack and overdraw each other. Menus and other object types are fine to
    # sit alongside a subtitle, and blocking on them suppressed every line in
    # a scene that has its own dialogue running.
    a.lw("$t2", 0x1954, "$t0")                 # engine object list head
    a.nop()
    a.label("walk")
    a.beq("$t2", "$zero", "free")
    a.nop()
    a.lw("$t4", 4, "$t2")                      # node type
    a.nop()
    a.beq("$t4", "$zero", "ret")               # a dialogue box is already up
    a.nop()
    a.lw("$t2", 0, "$t2")                      # next
    a.nop()
    a.b("walk")
    a.nop()
    a.label("free")
    mark(a, 7)
    # And never queue while the dialogue task is mid-transition. The frame
    # and fill (ctx+0x27B0/0x27F0) are not positioned per layout: they sit
    # at y=272, off the bottom of the screen, and the open step slides them
    # up 8 px a tick for 15 ticks while the close slides them back. A type-0
    # object dispatched during the open restarts the slide from wherever the
    # frame is (bit 28 not set yet), so the box ends up 120 px too high -
    # the "panel rides up around the picture"; one dispatched during the
    # close skips the slide (bit 28 still set) and the box sits too low -
    # the culture room's panel 20 px under its text. The safe steps are
    # idle (0), type-on and WAIT; anything else, try again next frame.
    a.lw("$t2", TASK_FN, "$t0")
    a.lui("$t1", STEP_TYPE >> 16)
    a.beq("$t2", "$zero", "steady")
    a.ori("$t1", "$t1", STEP_TYPE & 0xFFFF)
    a.beq("$t2", "$t1", "steady")
    a.lui("$t1", STEP_WAIT >> 16)
    a.ori("$t1", "$t1", STEP_WAIT & 0xFFFF)
    a.bne("$t2", "$t1", "ret")
    a.nop()
    a.label("steady")
    a.addiu("$t1", "$zero", blank_index)
    a.beq("$t9", "$t1", "opened")              # a clear opens nothing
    a.nop()
    if faceleft and not intro:
        # BUG-058 (#40): a card queued a few frames before its speaker's
        # face is up - the band still closed, or the column's cels not
        # shown yet - was typed plain (nameplate, 18-wide text) and retyped
        # beside the face when it appeared: the old layout flashing for
        # those frames (B010_f5_2 goes plain 3 frames before Harry's band
        # opens on Beetle; hardware spaces the two further apart). If the
        # speaker's character is loaded in the room's face list but no
        # shown column carries it, wait up to QHOLD_MAX frames for the
        # face before queueing; a card whose face never comes (a speaker
        # loaded but not in the band) goes plain 250 ms late instead.
        a.lui("$t4", hi(SCRATCH))
        a.sw("$t9", QHOLDT9 - SCRATCH_BASE, "$t4")
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.sll("$t6", "$t9", 3)
        a.sll("$t7", "$t9", 2)
        a.addu("$t6", "$t6", "$t7")            # idx * ENTRY
        a.lui("$t7", (cues_at + 4) >> 16)
        a.ori("$t7", "$t7", (cues_at + 4) & 0xFFFF)
        a.addu("$t6", "$t6", "$t7")
        a.lhu("$t6", 8, "$t6")                 # speaker string offset
        a.lui("$t3", blob_ram >> 16)
        a.ori("$t3", "$t3", blob_ram & 0xFFFF)
        a.addu("$t6", "$t6", "$t3")
        a.lbu("$t9", 0, "$t6")                 # its character code
        a.addiu("$t6", "$zero", NO_CHAR)
        a.beq("$t9", "$t6", "qhold_done")      # no portrait for this speaker
        a.addiu("$t6", "$zero", 1)
        a.sw("$t6", FFANY - SCRATCH_BASE, "$t4")
        a.jal("face_find")                     # any column of the character,
        a.nop()                                # shown or not
        a.lui("$t4", hi(SCRATCH))
        a.sw("$zero", FFANY - SCRATCH_BASE, "$t4")
        a.addiu("$t6", "$zero", 3)
        a.beq("$t5", "$t6", "qhold_done")      # not loaded here: plain, now
        a.nop()
        a.lw("$t1", 0x1AF4, "$t0")
        a.nop()
        a.srl("$t1", "$t1", 26)
        a.andi("$t1", "$t1", 1)
        a.beq("$t1", "$zero", "qhold_wait")    # band closed: wait for it
        a.nop()
        a.jal("face_find")                     # shown column of the character?
        a.nop()
        a.lui("$t4", hi(SCRATCH))
        a.addiu("$t6", "$zero", 3)
        a.beq("$t5", "$t6", "qhold_wait")      # not shown yet: wait
        a.addiu("$t7", "$zero", -1)
        a.b("qhold_done")                      # shown: queue now, and the
        a.sw("$t7", QHOLDIDX - SCRATCH_BASE, "$t4")   # next wait counts afresh
        a.label("qhold_wait")
        a.lw("$t9", QHOLDT9 - SCRATCH_BASE, "$t4")
        a.lw("$t6", QHOLDIDX - SCRATCH_BASE, "$t4")
        a.lw("$t7", QHOLD - SCRATCH_BASE, "$t4")
        a.beq("$t6", "$t9", "qhold_same")
        a.nop()
        a.or_("$t7", "$zero", "$zero")         # a new cue: count from 0
        a.sw("$t9", QHOLDIDX - SCRATCH_BASE, "$t4")
        a.label("qhold_same")
        a.addiu("$t7", "$t7", 1)
        a.sltiu("$t6", "$t7", QHOLD_MAX + 1)
        a.beq("$t6", "$zero", "qhold_done")    # waited enough: plain
        a.sw("$t7", QHOLD - SCRATCH_BASE, "$t4")
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.b("ret")                             # next frame
        a.nop()
        a.label("qhold_done")
        a.lui("$t4", hi(SCRATCH))
        a.lw("$t9", QHOLDT9 - SCRATCH_BASE, "$t4")
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.nop()
    # The voice-line band: for a voiced line the game opens the MENU window
    # (ctx+0x2830/0x2870, drawn as the two gold lines) with the speaker's
    # face in it and sets bit 26 of the menu word ctx+0x1AF4, exactly as a
    # live verb menu does. The type-0 entry step tests that bit and runs
    # the menu-close slide (0x8004783C -> 0x8004A0A0) before opening the
    # box, so every subtitle wiped the band and the face with it.
    # The faces are the nine portrait-slot tasks at ctx+0x4934 (0x5C each;
    # column = slot/3, the three per column cross-fade), live while +0x10
    # holds a step function, at the u16 pair +0x4E/+0x52. One face at the
    # right (x=168: the culture room, Metal beside the text) leaves the
    # text its 11 cells, so with no live menu (cursor byte ctx+0x1D7C !=
    # 0xF8) hold KEEP_MAGIC in KEEP for a few frames: the patched entry step
    # (BAND_STUB) then reads "no menu window" and the box slides in over the
    # band, face kept. Clearing bit 26 itself instead hung B020's escape -
    # the game tests the bit too, and a band it believes closed is never
    # closed, so the insector fight waited for it forever.
    # The three-face layout (x=24/96/168: Gibson's house, the Chief's
    # room) sits right on the text rows, so there the bit stays and the
    # band closes as before - text box, no faces. With the bank's
    # `faceleft` option the layout block above keeps every face off the
    # rows itself (speaker at FACE_X, the rest off-screen, rows at
    # ROW_X_FACE), so the band is kept whatever the columns hold. A real
    # menu keeps the bit either way.
    a.lbu("$t1", 0x1D7C, "$t0")
    a.addiu("$t2", "$zero", 0xF8)
    a.beq("$t1", "$t2", "keepmenu")
    a.addiu("$t5", "$t0", 0x4934)
    if faceleft:
        # the face-left layout keeps every face off the text rows itself
        a.b("fkeep")
        a.nop()
    a.ori("$t6", "$zero", 9)
    a.label("fscan")
    a.lw("$t1", 0x10, "$t5")
    a.lhu("$t2", 0x52, "$t5")
    a.beq("$t1", "$zero", "fnext")             # slot idle
    a.sltiu("$t2", "$t2", FACE_BAND_Y)
    a.bne("$t2", "$zero", "fnext")             # not in the band
    a.lhu("$t1", 0x4E, "$t5")
    a.nop()
    a.sltiu("$t1", "$t1", 24 + cols * 12)      # the text's right edge
    a.bne("$t1", "$zero", "keepmenu")          # a face on the text rows
    a.nop()
    a.label("fnext")
    a.addiu("$t6", "$t6", -1)
    a.bne("$t6", "$zero", "fscan")
    a.addiu("$t5", "$t5", 0x5C)
    a.label("fkeep")
    a.lui("$t4", hi(SCRATCH))
    a.lui("$t1", KEEP_MAGIC >> 16)
    a.ori("$t1", "$t1", KEEP_MAGIC & 0xFFFF)
    a.sw("$t1", KEEP - SCRATCH_BASE, "$t4")
    a.addiu("$t1", "$zero", 3)
    a.sw("$t1", KEEPCTR - SCRATCH_BASE, "$t4")
    a.label("keepmenu")
    mark(a, 8)

    # Instant open. Before each voiced line the game's voice object (type 2,
    # args {0, line}) closes any open box with the proper 15-tick slide and
    # clears bit 28, then starts the stream - in its design no box is open
    # during a voice line. Our next card then reopened with another 15-tick
    # slide, so the box blinked shut and open between every two lines.
    # The slide is a pure position delta, so run it in one go when the box
    # is closed: bit 28 clear and the fill HIDDEN (every close, ours or the
    # game's, hides the frame and fill after its slide) -> move both up by
    # the whole slide, set bit 28, and the entry step goes straight to the
    # nameplate and type-on. Bit 28 clear with the fill still visible is a
    # close in progress: wait for it. Visibility, not the vertex y: the y
    # carries a per-scene display offset (B250 draws 640 lower than B0C0).
    a.lw("$t2", 0x1ACC, "$t0")
    a.lw("$t1", 0x27F0 + 0x3C, "$t0")          # the fill's sprite flags
    a.lui("$t3", 0x1000)
    a.and_("$t2", "$t2", "$t3")
    a.bne("$t2", "$zero", "opened")            # bit 28: box open, retype
    a.lui("$t3", 0x0100)
    a.and_("$t1", "$t1", "$t3")                # bit 24: visible
    a.bne("$t1", "$zero", "ret")               # mid-slide: next frame
    a.nop()
    a.lui("$t6", RA >> 16)
    a.sw("$ra", RA & 0xFFFF, "$t6")
    a.addiu("$a0", "$t0", 0x27B0)
    a.or_("$a1", "$zero", "$zero")
    a.addiu("$a2", "$zero", -SLIDE)
    a.jal(0x80033848)
    a.ori("$a3", "$zero", 1)
    a.lui("$t0", 0x800B)
    a.lw("$t0", -0x409C, "$t0")
    a.nop()
    a.addiu("$a0", "$t0", 0x27F0)
    a.or_("$a1", "$zero", "$zero")
    a.addiu("$a2", "$zero", -SLIDE)
    a.jal(0x80033848)
    a.ori("$a3", "$zero", 0xF)
    a.lui("$t6", RA >> 16)
    a.lw("$ra", RA & 0xFFFF, "$t6")
    a.lui("$t0", 0x800B)
    a.lw("$t0", -0x409C, "$t0")
    a.nop()
    a.lw("$t2", 0x1ACC, "$t0")
    a.lui("$t3", 0x1000)
    a.or_("$t2", "$t2", "$t3")
    a.sw("$t2", 0x1ACC, "$t0")
    a.label("opened")
    mark(a, 9)
    if intro:
        # The text canvas shares VRAM with the opening's own pictures, which
        # rewrite it under our rows: the 4-px gaps between glyph rows showed
        # picture data. Fill the canvas again (0x80036704 is the text init:
        # CLUT upload + a fill of the canvas rect, no allocation state) right
        # before every render.
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.jal(0x80036704)
        a.nop()
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.lui("$t0", 0x800B)
        a.lw("$t0", -0x409C, "$t0")
        a.nop()
    a.lui("$t3", blob_ram >> 16)               # t3 = blob again (the latch
    a.ori("$t3", "$t3", blob_ram & 0xFFFF)     # and cold-open code use it)
    # Draws are allowed under the verb menu: with single-object gating and
    # the draw+dismiss clear, the subtitle opens its own panel cleanly there
    # (auto7 screenshots). The old menu garble came from object stacking in
    # the first rollout, not from the menu state itself.
    if layout:
        # Cold open: measured, not guessed (ps1/subs/subs_watch.lua state dump,
        # cold cue 0 vs warm cue 3 in B020):
        #   ctx+0x1AFC  cold ffffffff (no layout)  warm 000009be
        #   ctx+0x1B04  cold 00000000              warm 00000001
        #   ctx+0x1AF4  cold 078803f8 (box rect)   warm 03a803f8
        # The panel builder gates on bit 0 of 0x1B04 (0x8004abf0) and only
        # then reads the layout id at 0x1AFC (0x8004ac00); with no layout it
        # falls back to default geometry - the gold frame at the top of the
        # screen. During a voice-only stretch the scene has no reason to set
        # a dialogue layout, so a cold subtitle always hit that fallback.
        # Set the two fields and draw. Queueing the engine's own type-3
        # layout object instead does NOT work (it enters the transition at
        # the wrong point, exactly like the +0x44 dismiss).
        a.lw("$t2", 4, "$t3")                  # shown (clobbered by the walk)
        a.addiu("$t5", "$zero", -1)
        a.beq("$t2", "$t5", "coldck")          # nothing shown: cold
        a.nop()
        a.addiu("$t5", "$zero", blank_index)
        a.bne("$t2", "$t5", "primeok")         # a real line is up: warm
        a.nop()
        a.label("coldck")
        a.lw("$t2", 0x1AFC, "$t0")             # already a layout? leave the
        a.lui("$t5", layout >> 16)             # engine's own alone
        a.ori("$t5", "$t5", layout & 0xFFFF)
        a.beq("$t2", "$t5", "primeok")
        a.nop()
        a.lui("$t4", hi(SCRATCH))            # stash the engine's values
        a.lw("$t2", 0x1AFC, "$t0")             # first, so the clear can put
        a.nop()                                # them back
        a.sw("$t2", SAVEBUF - SCRATCH_BASE, "$t4")
        a.lw("$t2", 0x1B04, "$t0")
        a.nop()
        a.sw("$t2", SAVEBUF + 4 - SCRATCH_BASE, "$t4")
        for i, (off, _v) in enumerate(cold_fields):
            a.lw("$t2", off, "$t0")
            a.nop()
            a.sw("$t2", SAVEBUF + 8 + 4 * i - SCRATCH_BASE, "$t4")
        a.addiu("$t2", "$zero", 1)
        a.sw("$t2", SAVED - SCRATCH_BASE, "$t4")
        a.sw("$t5", 0x1AFC, "$t0")
        a.lw("$t2", 0x1B04, "$t0")
        a.nop()
        a.ori("$t2", "$t2", 1)                 # mark the layout usable
        a.sw("$t2", 0x1B04, "$t0")
        # The box rectangle at 0x1AF4 is NOT re-derived from the layout at
        # draw time, so it keeps whatever the scene left there: measured
        # 0788_03f8 cold against 03a8_03f8 warm - same width, roughly double
        # the height, i.e. the frame spanning down over the scene picture.
        # cold_fields carries the warm values per scene, straight from the
        # watcher's state dump.
        for off, val in cold_fields:
            a.lui("$t2", (val >> 16) & 0xFFFF)
            a.ori("$t2", "$t2", val & 0xFFFF)
            a.sw("$t2", off, "$t0")
        a.label("primeok")
    a.sw("$t9", 4, "$t3")                      # latch only once it can be drawn
    if chain:
        a.lui("$t4", hi(SCRATCH))
        a.addiu("$t2", "$t9", -chain[0][0])    # the anchor cue's index?
        a.bne("$t2", "$zero", "notanchor")
        a.nop()
        a.addiu("$t2", "$zero", 1)
        a.b("anchdone")
        a.sw("$t2", CHAINT - SCRATCH_BASE, "$t4")   # delay slot: timer starts
        a.label("notanchor")
        for _a, chain_i, _d, _w in chain:
            a.addiu("$t2", "$t9", -chain_i)
            a.beq("$t2", "$zero", "anchdone")  # a chain line itself keeps
            a.nop()                            # the timer running
        a.addiu("$t2", "$t9", -blank_index)
        a.beq("$t2", "$zero", "anchdone")      # a clear must not close the
        a.nop()                                # chain window early
        a.sw("$zero", CHAINT - SCRATCH_BASE, "$t4") # any other draw ends it
        a.label("anchdone")
    a.addiu("$t4", "$zero", blank_index)
    a.bne("$t9", "$t4", "draw")
    a.nop()
    if clear_dismiss:
        a.b("engineclose")                     # the blank cue = the engine's
        a.nop()                                # own close, nothing drawn
    # A blank-only scene (clear: blank) draws the padded blank and leaves
    # the box open, as before; B020 keeps its box across the game's own
    # lines and has not been re-tested with the engine close.
    a.label("draw")

    # --- reset the six row sprites' widths ---------------------------------
    # The type-on step GROWS each row sprite by 12 px per cell typed
    # (0x80033BC8 is relative), and only the close step sets the width back
    # to 0. A card queued into an open box (the retype path every second
    # card of a conversation takes) starts from the previous card's width,
    # so a row is (cols+1)*12 px wider per card; past 1023 px the GPU masks
    # the sprite width to 10 bits and the row shows its first ~10 cells
    # only - the "text cropped after a few frames" family (2026-09-07,
    # found by dumping the row prims: 0x2ac -> 0x390 -> 0x474 per card).
    # Zero them here, the way the close does, before every queue.
    a.lui("$t4", hi(SCRATCH))
    a.sw("$t9", ROWRESET + 8 - SCRATCH_BASE, "$t4")
    a.addiu("$t5", "$zero", 6)
    a.sw("$t5", ROWRESET - SCRATCH_BASE, "$t4")
    a.addiu("$t5", "$t0", 0x22B0 + 0x2C0)
    a.sw("$t5", ROWRESET + 4 - SCRATCH_BASE, "$t4")
    a.lui("$t6", RA >> 16)
    a.sw("$ra", RA & 0xFFFF, "$t6")
    a.label("rowreset")
    a.lui("$t4", hi(SCRATCH))
    a.lw("$a0", ROWRESET + 4 - SCRATCH_BASE, "$t4")
    a.or_("$a1", "$zero", "$zero")
    a.ori("$a2", "$zero", 0x10)
    a.jal(0x80033A18)
    a.ori("$a3", "$zero", 1)
    a.lui("$t4", hi(SCRATCH))
    a.lw("$t5", ROWRESET + 4 - SCRATCH_BASE, "$t4")
    a.lw("$t2", ROWRESET - SCRATCH_BASE, "$t4")
    a.addiu("$t5", "$t5", 0x40)
    a.sw("$t5", ROWRESET + 4 - SCRATCH_BASE, "$t4")
    a.addiu("$t2", "$t2", -1)
    a.bne("$t2", "$zero", "rowreset")
    a.sw("$t2", ROWRESET - SCRATCH_BASE, "$t4")
    a.lui("$t6", RA >> 16)
    a.lw("$ra", RA & 0xFFFF, "$t6")
    a.lui("$t0", 0x800B)
    a.lw("$t0", -0x409C, "$t0")                # ctx again
    a.lui("$t4", hi(SCRATCH))
    a.lw("$t9", ROWRESET + 8 - SCRATCH_BASE, "$t4")
    a.nop()

    # --- queue the line ---------------------------------------------------
    a.sll("$t4", "$t9", 3)
    a.sll("$t3", "$t9", 2)
    a.addu("$t4", "$t4", "$t3")                # idx * ENTRY
    a.lui("$t6", (cues_at + 4) >> 16)
    a.ori("$t6", "$t6", (cues_at + 4) & 0xFFFF)
    a.addu("$t6", "$t6", "$t4")
    a.lhu("$t7", 8, "$t6")                     # speaker, offset from blob_ram
    a.lhu("$t8", 10, "$t6")                    # text (unpadded), same
    a.lui("$t3", blob_ram >> 16)               # fills the load delay
    a.ori("$t3", "$t3", blob_ram & 0xFFFF)
    a.addu("$t7", "$t7", "$t3")
    a.addu("$t8", "$t8", "$t3")
    if faceleft:
        # The layout for this card, decided now: the band open and the
        # speaker's column visible -> face (LAYOUT 2, the cols-wide text,
        # rows padded to cols), else plain (LAYOUT 1, the second, 18-wide
        # text after the first's terminator, rows padded to 18). The
        # per-frame block retypes the card if its decision changes.
        a.lbu("$t9", 0, "$t7")                 # the character code
        a.lbu("$t2", 1, "$t7")                 # the speaker's mode (nameplate colour)
        a.addiu("$t7", "$t7", 2)               # past both: the name
        a.lui("$t4", hi(SCRATCH))
        a.sw("$t2", QMODE - SCRATCH_BASE, "$t4")
        a.lw("$t1", 0x1AF4, "$t0")
        a.addiu("$t5", "$zero", 3)             # no face
        a.srl("$t1", "$t1", 26)
        a.andi("$t1", "$t1", 1)
        a.lui("$t4", hi(SCRATCH))
        a.sw("$t7", QSAVE - SCRATCH_BASE, "$t4")     # face_find clobbers
        a.sw("$t8", QSAVE + 4 - SCRATCH_BASE, "$t4") # t3, t6, t7, t8
        a.beq("$t1", "$zero", "q_lay")         # band closed
        a.nop()
        a.lui("$t6", RA >> 16)
        a.sw("$ra", RA & 0xFFFF, "$t6")
        a.jal("face_find")
        a.nop()
        a.lui("$t4", hi(SCRATCH))
        a.lw("$t7", QSAVE - SCRATCH_BASE, "$t4")
        a.lw("$t8", QSAVE + 4 - SCRATCH_BASE, "$t4")
        a.lui("$t6", RA >> 16)
        a.lw("$ra", RA & 0xFFFF, "$t6")
        a.label("q_lay")
        a.lui("$t4", hi(SCRATCH))
        a.andi("$t5", "$t5", 3)                # a hidden match counts
        a.addiu("$t1", "$zero", 2)             # face layout
        a.addiu("$t2", "$zero", cols)
        a.addiu("$t6", "$zero", 3)
        a.bne("$t5", "$t6", "q_face")
        a.nop()
        a.addiu("$t1", "$zero", 1)             # plain layout: the 18-wide text
        a.addiu("$t2", "$zero", CODES_PER_ROW)
        a.label("q_skip")                      # past the first text's 0000
        a.lbu("$t6", 0, "$t8")
        a.addiu("$t8", "$t8", 2)
        a.bne("$t6", "$zero", "q_skip")
        a.nop()
        a.lbu("$t6", 0, "$t8")                 # SAME_TEXT: the first again
        a.addiu("$t3", "$zero", 0xFF)
        a.bne("$t6", "$t3", "q_face")
        a.nop()
        a.lw("$t8", QSAVE + 4 - SCRATCH_BASE, "$t4")
        a.label("q_face")
        a.sw("$t1", LAYOUT - SCRATCH_BASE, "$t4")
        a.sw("$t2", PADW - SCRATCH_BASE, "$t4")

    # Pad into a RAM buffer: every row is brought up to CODES_PER_ROW glyph
    # codes with fullwidth spaces, and all ROWS rows are emitted, so the new
    # line covers whatever the previous one left on the canvas. Doing this at
    # runtime instead of in the data is what makes room for more cues.
    a.lui("$t5", TEXTBUF >> 16)
    a.ori("$t5", "$t5", TEXTBUF & 0xFFFF)      # dst
    a.ori("$t3", "$zero", rows)                # rows left
    a.label("row")
    if faceleft:
        a.lui("$t4", hi(SCRATCH))
        a.lw("$t4", PADW - SCRATCH_BASE, "$t4")   # cells per row for this layout
        a.nop()
    else:
        a.ori("$t4", "$zero", cols)            # cells left in this row (options.cols)
    a.label("cell")
    a.beq("$t4", "$zero", "rowdone")           # row full
    a.nop()
    a.lbu("$t2", 0, "$t8")                     # first byte of the code
    a.nop()
    a.beq("$t2", "$zero", "padcell")           # end of text: pad the rest
    a.nop()
    a.ori("$t1", "$zero", 0x81)
    a.bne("$t2", "$t1", "copycell")            # not 0x81xx, so not a break
    a.nop()
    a.lbu("$t2", 1, "$t8")
    a.nop()
    a.ori("$t1", "$zero", 0x8F)
    a.bne("$t2", "$t1", "copycell")            # 0x81 but not 0x818F
    a.nop()
    a.addiu("$t8", "$t8", 2)                   # consume the line break
    a.b("padcell")                             # pad out the rest of the row
    a.nop()

    a.label("copycell")
    a.lbu("$t2", 0, "$t8")
    a.nop()
    a.sb("$t2", 0, "$t5")
    a.lbu("$t2", 1, "$t8")
    a.nop()
    a.sb("$t2", 1, "$t5")
    a.addiu("$t8", "$t8", 2)
    a.addiu("$t5", "$t5", 2)
    a.addiu("$t4", "$t4", -1)
    a.b("cell")
    a.nop()

    a.label("padcell")                         # fullwidth space, 0x8140
    a.beq("$t4", "$zero", "rowdone")
    a.nop()
    a.ori("$t2", "$zero", 0x81)
    a.sb("$t2", 0, "$t5")
    a.ori("$t2", "$zero", 0x40)
    a.sb("$t2", 1, "$t5")
    a.addiu("$t5", "$t5", 2)
    a.addiu("$t4", "$t4", -1)
    a.b("padcell")
    a.nop()

    a.label("rowdone")
    # A row that filled the width exactly stops HERE, on the source's own
    # break: consume it, or the next row starts on it and pads out empty
    # (the third row then falls off the box). Never happened while every
    # wrap was one cell short of the box - cellw counted the terminator
    # - and showed the day that was fixed (2026-09-12: 'They chose Outer
    # Heaven / [blank] / as the place to look for').
    a.lbu("$t2", 0, "$t8")
    a.nop()
    a.ori("$t1", "$zero", 0x81)
    a.bne("$t2", "$t1", "rownext")
    a.nop()
    a.lbu("$t2", 1, "$t8")
    a.nop()
    a.ori("$t1", "$zero", 0x8F)
    a.bne("$t2", "$t1", "rownext")
    a.nop()
    a.addiu("$t8", "$t8", 2)
    a.label("rownext")
    a.addiu("$t3", "$t3", -1)
    a.beq("$t3", "$zero", "textdone")
    a.nop()
    a.ori("$t2", "$zero", 0x81)                # row separator 0x818F
    a.sb("$t2", 0, "$t5")
    a.ori("$t2", "$zero", 0x8F)
    a.sb("$t2", 1, "$t5")
    a.addiu("$t5", "$t5", 2)
    a.b("row")
    a.nop()

    a.label("textdone")
    a.sb("$zero", 0, "$t5")
    a.sb("$zero", 1, "$t5")
    a.lui("$t8", TEXTBUF >> 16)
    a.ori("$t8", "$t8", TEXTBUF & 0xFFFF)      # args[2] = the padded buffer

    a.lui("$t5", args_at >> 16)
    a.ori("$t5", "$t5", args_at & 0xFFFF)
    a.sw("$t7", 0, "$t5")
    if faceleft:
        a.lui("$t4", hi(SCRATCH))
        a.lw("$t7", QMODE - SCRATCH_BASE, "$t4")   # the speaker's mode (colour)
        a.nop()
    else:
        a.addiu("$t7", "$zero", mode)          # the bank's mode
    a.sw("$t7", 4, "$t5")
    a.sw("$t8", 8, "$t5")
    a.lui("$t6", RA >> 16)
    a.sw("$ra", RA & 0xFFFF, "$t6")
    a.or_("$a1", "$t5", "$zero")
    a.or_("$v0", "$t0", "$zero")               # queue() consumes ctx in v0
    a.jal(0x800364E0)
    a.ori("$a0", "$zero", 0)                   # delay: type 0
    a.lui("$t6", RA >> 16)
    a.lw("$ra", RA & 0xFFFF, "$t6")
    a.lui("$t4", hi(SCRATCH))
    a.addiu("$t2", "$zero", 1)                 # ours is (about to be) in the box
    a.sw("$t2", PHASE - SCRATCH_BASE, "$t4")
    if faceleft and not intro and HOLD_REQUEUE:
        a.sw("$zero", SHOWNT - SCRATCH_BASE, "$t4")     # a new card: its age
        a.sw("$zero", HOLDREQ - SCRATCH_BASE, "$t4")    # and no hold pending
    a.lui("$t0", 0x800B)                       # ctx: t0 was clobbered by the
    a.lw("$t0", -0x409C, "$t0")                # queue call
    a.label("postdraw")
    if layout:
        # The clear has been queued: hand the window fields back to the
        # engine so the scene's own next dialogue opens where it expects.
        a.lui("$t4", hi(SCRATCH))
        a.lw("$t2", FINALCLR - SCRATCH_BASE, "$t4")
        a.nop()
        a.beq("$t2", "$zero", "norestore")     # mid-exchange clear: leave the
        a.nop()                                # dialogue layout in place
        a.sw("$zero", FINALCLR - SCRATCH_BASE, "$t4")
        a.lui("$t3", blob_ram >> 16)
        a.ori("$t3", "$t3", blob_ram & 0xFFFF)
        a.lw("$t2", 4, "$t3")                  # only on the blank cue
        a.addiu("$t5", "$zero", blank_index)
        a.bne("$t2", "$t5", "norestore")
        a.nop()
        # What was saved may be "no layout at all" (ffffffff, valid bit
        # clear): during a voice-only stretch the scene has no dialogue
        # layout, and putting that back leaves the verb menu drawing with
        # the fallback geometry until the player presses something - which
        # is exactly the bug the naive restore caused. So restore the saved
        # state only when it is a real layout; otherwise write the scene's
        # measured menu state from clear_fields.
        a.label("clearfields")
        for off, val in clear_fields:
            a.lui("$t2", (val >> 16) & 0xFFFF)
            a.ori("$t2", "$t2", val & 0xFFFF)
            a.sw("$t2", off, "$t0")
        # Writing the fields is not enough: the panel was already BUILT with
        # our dialogue geometry and the engine only rebuilds it when a
        # type-3 object changes the layout id (0x8004ac04 calls the builder
        # at 0x8004b264). Without that the verb menu keeps our frame until
        # the player presses something. Ask for the rebuild next frame - not
        # this one, which still has the blank draw to process.
        a.addiu("$t2", "$zero", 1)
        a.sw("$t2", REBUILD - SCRATCH_BASE, "$t4")
        a.label("norestore")
    a.b("ret")
    a.nop()

    # --- clear the box: the engine's own timed close --------------------
    # A clear is an accept of the blank cue: it rides the accept path's
    # already-shown compare (a clear that ran stops re-firing because shown
    # == blank) and its pending-object gate, then lands here instead of
    # drawing. If our text is in the box (PHASE != 0) and the task is live,
    # set bit 31 of the window word: the WAIT step treats it exactly like a
    # line that ends in `＠Ｃ` and runs the game's own close - nameplate and
    # rows hidden, the frame faded out, bit 28 cleared, step 0. Nothing is
    # queued, nothing is poked into a node. Before this the clear drew a
    # padded blank and left the task parked in WAIT, where the player's
    # next press closed it late (the floating box after every voiced scene).
    a.label("clearbox")
    a.addiu("$t9", "$zero", blank_index)
    a.b("accept")
    a.nop()

    a.label("engineclose")
    a.lui("$t4", hi(SCRATCH))
    a.lw("$t2", PHASE - SCRATCH_BASE, "$t4")
    a.lw("$t1", TASK_FN, "$t0")
    a.nop()
    a.beq("$t2", "$zero", "postdraw")          # the box is not ours
    a.nop()
    a.beq("$t1", "$zero", "eclosed")           # already closed
    a.nop()
    a.lw("$t1", 0x1ACC, "$t0")
    a.lui("$t3", 0x8000)
    a.or_("$t1", "$t1", "$t3")
    a.sw("$t1", 0x1ACC, "$t0")
    a.label("eclosed")
    a.b("postdraw")
    a.sw("$zero", PHASE - SCRATCH_BASE, "$t4")      # delay slot

    a.label("ret")
    a.jr("$ra")
    a.nop()
    if intro:
        exe = open(P.EXE, "rb").read()
        fn = bytearray(exe[P.fo(SPRITES_FN):P.fo(SPRITES_FN) + SPRITES_LEN])
        assert struct.unpack_from("<I", fn, SPRITES_LOAD)[0] == 0x0C00B15F   # jal 0x8002c57c
        struct.pack_into("<I", fn, SPRITES_LOAD, 0)                          # nop
        for i in range(0, len(fn), 4):                                       # no absolute jumps
            assert (struct.unpack_from("<I", fn, i)[0] >> 26) != 2, hex(SPRITES_FN + i)
        a.label("sprites")
        a.blob(bytes(fn))
        a.label("task_t")
        a.blob(bytes(0x1C))
        a.label("snap")
        a.blob(bytes(SNAP_TOTAL))
    if faceleft and not intro:
        # face_find: t9 = a character code -> t5 = the column showing it
        # (0-2), 3 if none. A column counts when its slot id (ctx+0x1AF8+
        # col, s8) names a CXN file of that character through the room's
        # face list ([ctx+0x1814]) AND the engine shows at least one of
        # its three cels (+0x58 bits 9 and 8: the Chief's room loads
        # Gillian twice, [396, 396, 414], and keeps one hidden; Metal
        # Gear's base cel is hidden by design, his eyes cel is the head).
        # Clobbers t3, t6, t7, t8.
        a.label("face_find")
        a.addiu("$t5", "$zero", 3)             # none
        a.lw("$t7", 0x1814, "$t0")             # the room's face list
        a.or_("$t8", "$zero", "$zero")         # column
        a.label("ff_scan")
        a.addu("$t6", "$t0", "$t8")
        a.lb("$t6", 0x1AF8, "$t6")             # slot id, -1 = empty
        a.nop()
        a.bltz("$t6", "ff_next")
        a.sll("$t6", "$t6", 2)
        a.addu("$t6", "$t6", "$t7")
        a.lw("$t6", 0, "$t6")                  # class-4 file index
        a.nop()
        a.addiu("$t6", "$t6", -CXN_FIRST)
        a.sltiu("$t3", "$t6", len(CXN_CHARS))
        a.beq("$t3", "$zero", "ff_next")       # not a CXN file
        a.nop()
        a._i(lambda pc, L: 0x3C000000 | REG["$t3"] << 16 | (((L["face_tbl"] + 0x8000) >> 16) & 0xFFFF))
        a._i(lambda pc, L: 0x24000000 | REG["$t3"] << 21 | REG["$t3"] << 16 | ((L["face_tbl"] - ((L["face_tbl"] + 0x8000) & ~0xFFFF)) & 0xFFFF))
        a.addu("$t6", "$t6", "$t3")
        a.lbu("$t6", 0, "$t6")                 # the column's character
        a.nop()
        a.bne("$t6", "$t9", "ff_next")
        a.nop()
        a.sll("$t6", "$t8", 8)                 # column stride 3 * 0x5C = 0x114
        a.sll("$t3", "$t8", 4)
        a.addu("$t6", "$t6", "$t3")
        a.sll("$t3", "$t8", 2)
        a.addu("$t6", "$t6", "$t3")
        a.addu("$t6", "$t6", "$t0")
        # any of the three cels shown (+0x58 bits 9 and 8): the engine
        # hides a cel by design when its frame argument is negative
        # (0x80049904, `nor/srl 31` on s7/fp/s6) - Metal Gear's BASE is
        # hidden in every scene and his eyes cel is the animated head, so
        # the old base-only test called his column hidden and the payload
        # forced the base on, a static picture over the animation (#37).
        # FFANY (the queue's wait for a face, BUG-058): the column counts
        # as soon as it is loaded, shown or not
        a.lui("$a2", hi(SCRATCH))
        a.lw("$a2", FFANY - SCRATCH_BASE, "$a2")
        a.nop()
        a.bne("$a2", "$zero", "ff_vis")
        a.nop()
        a.lw("$t3", 0x4934 + 0x58, "$t6")      # base   (t8 is the column)
        a.lw("$a2", 0x4934 + 0x58 + 0x5C, "$t6")   # eyes
        a.andi("$t3", "$t3", 0x300)            # bits 9 and 8 both set on a
        a.andi("$a2", "$a2", 0x300)            # shown cel; a hidden one has
        a.lw("$t6", 0x4934 + 0x58 + 0xB8, "$t6")   # mouth  (neither 9 nor, once
        a.addiu("$t3", "$t3", -0x300)          # torn down, 8)
        a.beq("$t3", "$zero", "ff_vis")        # base shown
        a.addiu("$a2", "$a2", -0x300)
        a.beq("$a2", "$zero", "ff_vis")        # eyes shown
        a.andi("$t6", "$t6", 0x300)
        a.addiu("$t6", "$t6", -0x300)
        a.beq("$t6", "$zero", "ff_vis")        # mouth shown
        a.nop()
        a.b("ff_next")                         # hidden: no face
        a.nop()
        a.label("ff_vis")
        a.or_("$t5", "$t8", "$zero")           # the speaker's column
        a.label("ff_next")
        a.addiu("$t8", "$t8", 1)
        a.addiu("$t6", "$zero", 3)
        a.bne("$t8", "$t6", "ff_scan")
        a.nop()
        a.jr("$ra")
        a.nop()
        # hide_rows: the six row sprites and the nameplate off (0x80032D9C),
        # ctx back in t0. Clobbers what the engine call does (a0, a1, v0,
        # v1, t-regs are not trusted: t0 is reloaded).
        a.label("hide_rows")
        a.lui("$t8", RA2 >> 16)
        a.sw("$ra", RA2 & 0xFFFF, "$t8")
        for off in [0x2570 + 0x40 * i for i in range(6)] + [0x2530]:
            a.addiu("$a0", "$t0", off)
            a.jal(0x80032D9C)
            a.or_("$a1", "$zero", "$zero")
            a.lui("$t0", 0x800B)
            a.lw("$t0", -0x409C, "$t0")
            a.nop()
        if HOLD_REQUEUE:
            # the minimum hold: a card of ours (PHASE != 0, shown a real
            # cue) up fewer frames than its reading time (the byte table
            # after the cue table) asks to be drawn again once the box has
            # closed (HOLDREQ, served at the top of the face block)
            holds = hold_tab(cues_at, blank_index + 1)
            a.lui("$t8", hi(SCRATCH))
            a.lw("$t2", PHASE - SCRATCH_BASE, "$t8")
            a.lui("$t3", blob_ram >> 16)
            a.beq("$t2", "$zero", "hr_ret")
            a.ori("$t3", "$t3", blob_ram & 0xFFFF)
            a.lw("$t6", 4, "$t3")              # shown
            a.addiu("$t7", "$zero", blank_index)
            a.bltz("$t6", "hr_ret")
            a.nop()
            a.beq("$t6", "$t7", "hr_ret")      # the blank (a clear)
            a.lui("$t7", hi(holds))
            a.addu("$t7", "$t7", "$t6")
            a.lbu("$t7", lo(holds), "$t7")     # its reading time, frames
            a.lw("$t2", SHOWNT - SCRATCH_BASE, "$t8")
            a.nop()
            a.sltu("$t2", "$t2", "$t7")
            a.beq("$t2", "$zero", "hr_ret")    # read long enough: it goes
            a.lui("$t7", HOLD_MAGIC)
            a.sw("$t7", HOLDREQ - SCRATCH_BASE, "$t8")
            a.label("hr_ret")
        a.lui("$t8", RA2 >> 16)
        a.lw("$ra", RA2 & 0xFFFF, "$t8")
        a.nop()
        a.jr("$ra")
        a.nop()
        a.label("face_tbl")                  # CXN file -> character, see CXN_CHARS
        a.blob(bytes(int(ch, 18) for ch in CXN_CHARS))
    return a


def scene_mode(opts):
    """The dialogue mode is DERIVED, never chosen.

    `mode` is args[1] of the queued type-0 object. The handler masks it to 6
    bits and writes it into bits 9-14 of the window word ctx+0x1ACC, so it
    selects the box layout variant - and it must equal what the scene's own
    dialogue already uses, or the scene's native boxes render wrong and lines
    go missing later on. That value is recoverable from the scene's window
    word, which is already recorded as `menu_word`:

        mode = (menu_word >> 9) & 0x3F        B010 0x8701 -> 3
                                              B020 0x8300 -> 1

    Guessing it cost two separate regressions in B020 (mode 3 lost text both
    times), so an explicit `mode` that disagrees with the window word is a
    build error rather than an override.
    """
    derived = (opts.get('menu_word', 0x8701) >> 9) & 0x3F
    given = opts.get('mode')
    if given is not None and given != derived:
        raise SystemExit(
            f"options.mode {given} contradicts menu_word "
            f"{opts.get('menu_word', 0x8701):#06x}, which means mode {derived}. "
            f"mode is derived from the scene's own window word - fix menu_word "
            f"if the scene really uses a different layout, and never set mode "
            f"by hand to make the panel look better (B020 lost text twice "
            f"that way).")
    return derived


def chain_anchor(cues, c):
    """Table index of the cue a chain cue (chan 254) fires after.

    `anchor` names the cue by id. The older form, `file` = table index, went
    stale the moment split_long.py inserted `_b` cues ahead of it: B010's
    JUNKER-card line was written against index 17 = B010_017 ("That should
    cover your assignment"), the splits moved that line to 19, and the card
    line quietly anchored on "Yes - separated now" and never fired. A bare
    `file` is therefore read as the id NUMBER (B010_017), not an index.
    """
    want = c.get('anchor')
    if want is None:
        want = f"{c['id'].rsplit('_', 1)[0]}_{c['file']:03d}"
    for i, other in enumerate(cues):
        if other.get('id') == want:
            return i
    raise SystemExit(f"{c['id']}: chain anchor {want!r} is not a cue id in this scene")


def intro_ytab(cues_at, n):
    """The opening's per-card y bytes: right after its n-entry cue table."""
    return cues_at + 4 + ENTRY * n


def hold_tab(cues_at, n):
    """A face-left bank's per-card reading times (hold_frames, one byte a cue):
    right after its n-entry cue table, like the opening's y bytes."""
    return cues_at + 4 + ENTRY * n


def build_blob(blob_ram, cues, test_every=None, opts=None):
    opts = opts or {}
    blank_index = len(cues) - 1            # the table ends with a blank line
    disp = dispatcher()
    chain = []
    for i, c in enumerate(cues):
        if c.get('chan') == 254:
            chain.append((chain_anchor(cues, c), i, c['start'], c['end']))
    assert len(set(a for a, _i, _d, _w in chain)) <= 1, "chain cues must share one anchor"
    code_len = payload(blob_ram, 0, 0, blank_index, test_every,
                       0x80110000, len(disp), chain,
                       opts.get('clear', 'dismiss') == 'dismiss',
                       opts.get('menu_word', 0x8701),
                       opts.get('rows', 3), opts.get('away_clear', True),
                       scene_mode(opts), opts.get('layout', 0),
                       [(int(k, 0), int(v, 0)) for k, v in
                        opts.get('cold_fields', {}).items()],
                       [(int(k, 0), int(v, 0)) for k, v in
                        opts.get('clear_fields', {}).items()],
                       int(opts.get('clear_layout', 0)),
                       min(opts.get('cols', CODES_PER_ROW), CODES_PER_ROW),
                   bool(opts.get('intro')), bool(opts.get('faceleft')),
                   any(c.get('noframe') for c in cues)).size()
    args_at = blob_ram + 8 + code_len
    cues_at = args_at + 12
    strings_at = cues_at + 4 + ENTRY * len(cues)
    if opts.get('intro'):                  # the per-card y bytes + 2 words
        strings_at = intro_ytab(cues_at, len(cues)) + ((len(cues) + 3) & ~3) + 8
    elif opts.get('faceleft') and HOLD_REQUEUE:     # the per-card reading times
        strings_at = hold_tab(cues_at, len(cues)) + ((len(cues) + 3) & ~3)

    # identical strings are stored once - "Chief" repeated per cue cost
    # hundreds of bytes of a bank that is byte-full
    strings, offsets, seen = bytearray(), [], {}
    def intern(b):
        if b not in seen:
            seen[b] = strings_at + len(strings)
            strings.extend(b)
        return seen[b]
    faceleft = bool(opts.get('faceleft'))
    for c in cues:
        sp = encode(pad_block(c.get("speaker", ""), ROWS_NAME, COLS_NAME))
        if faceleft:
            # the character code rides in front, padded to TWO bytes: the
            # name must stay halfword-aligned (interned strings are even-
            # sized, so a 1-byte prefix made every name pointer odd; Beetle
            # reads a misaligned halfword regardless, a real R3000 raises an
            # address error and the plate kept its previous name on MiSTer)
            sp = bytes([SPEAKER_CHAR.get(c.get("speaker", ""), NO_CHAR),
                        speaker_mode(c.get("speaker", ""), scene_mode(opts))]) + bytes(sp)
        # a cue may wrap narrower than the scene (c['cols']): the portrait
        # layout covers the right end of an 11-cell row (B010_f5_4)
        tx = encode(wrap_only(c["text"].replace("/n", chr(10)),
                              opts.get('rows', 3),
                              c.get('cols', opts.get('cols', CODES_PER_ROW))))
        if faceleft:
            # ... and after its 0000 the same text wrapped for the full
            # box, for a card with no face; SAME_TEXT when that wrap is
            # the first one again (short cards), or when the bank cannot
            # afford it (`fullwidth: false` - B250's 639 cues would put
            # the blob past the 48 KB cap): the queue then reuses the first.
            t18 = encode(wrap_only(c["text"].replace("/n", chr(10)),
                                   opts.get('rows', 3), CODES_PER_ROW))
            tail = SAME_TEXT if (bytes(t18) == bytes(tx) or not opts.get('fullwidth', True)) else bytes(t18)
            tx = bytes(tx) + tail
        offsets.append((intern(bytes(sp)), intern(bytes(tx))))

    table = struct.pack("<I", len(cues))
    for c, (sp_at, tx_at) in zip(cues, offsets):
        span = c["end"] - c["start"]
        assert 0 <= span < 0x4000, f'{c.get("id")}: span {span} needs > 14 bits'
        assert 0 <= sp_at - blob_ram < 0x10000, 'speaker offset out of range'
        assert 0 <= tx_at - blob_ram < 0x10000, 'text offset out of range'
        chan = c.get("chan", 2)
        if chan == 255:
            ident = 0xFFFF
        elif chan == 254:
            ident = 0xFD00 | (c["file"] & 0xFF)
        else:
            ident = c["file"] | (chan << 8)
        # bit 0 = the last line of its conversation: the scene knows where
        # each exchange ends, so the box is cleared and the panel handed
        # back the moment that line's stream stops, instead of waiting for
        # the menu-hold and away-timer heuristics to notice.
        if c.get("last"):
            span |= 0x8000
        # bit 14 = no band under this card (the opening only): the Snatcher
        # diagram still draws over the rows AND, since #19 moved the band
        # to bucket 1, under the band - its narration is baked into the
        # picture (introdiagram.py), so the band is hidden for that cue.
        if c.get("noband"):
            assert bool(opts.get('intro')), f'{c.get("id")}: noband is for the opening'
            span |= 0x4000
        # ... and outside the opening = `noframe` (#80): the gold frame
        # stays hidden under this card, the fill alone carries the text.
        if c.get("noframe"):
            assert not opts.get('intro'), f'{c.get("id")}: noframe is not for the opening'
            span |= 0x4000
        table += struct.pack("<IHHHH", c["start"], span, ident,
                             sp_at - blob_ram, tx_at - blob_ram)

    if opts.get('intro'):
        # the opening's placement (gen_intro.py place): one signed byte per
        # cue = the rows' offset below home, then the applied offset and the
        # pending move (payload, "Per-card placement"); zero on every load
        ys = []
        for c in cues:
            y = int(c.get('y', 0))
            assert -128 <= y < 128, f'{c.get("id")}: y {y}'
            ys.append(y & 0xFF)
        table += bytes(ys) + bytes(-len(ys) % 4) + bytes(8)
        assert cues_at + len(table) == strings_at
    elif opts.get('faceleft') and HOLD_REQUEUE:
        hs = [hold_frames(c['text']) if c['text'].strip() else 0 for c in cues]
        table += bytes(hs) + bytes(-len(hs) % 4)
        assert cues_at + len(table) == strings_at
    disp_at = strings_at + len(strings)
    while disp_at % 4:
        disp_at += 1
    code = payload(blob_ram, cues_at, args_at, blank_index, test_every,
                   disp_at, len(disp), chain,
                   opts.get('clear', 'dismiss') == 'dismiss',
                   opts.get('menu_word', 0x8701),
                   opts.get('rows', 3), opts.get('away_clear', True),
                   scene_mode(opts), opts.get('layout', 0),
                   [(int(k, 0), int(v, 0)) for k, v in
                    opts.get('cold_fields', {}).items()],
                   [(int(k, 0), int(v, 0)) for k, v in
                    opts.get('clear_fields', {}).items()],
                   int(opts.get('clear_layout', 0)),
                   min(opts.get('cols', CODES_PER_ROW), CODES_PER_ROW),
                   bool(opts.get('intro')), bool(opts.get('faceleft')),
                   any(c.get('noframe') for c in cues)).assemble()
    assert len(code) == code_len
    head = struct.pack("<iI", MAGIC, 0xFFFFFFFF)
    body = head + code + b"\x00" * 12 + table + bytes(strings)
    body += b"\x00" * ((disp_at - blob_ram) - len(body)) + disp
    return body


def next_free_lba():
    lba = os.path.getsize(SRC_IMG) // 2352
    rel = json.load(open(RELOC)) if os.path.exists(RELOC) else {}
    for fname, start in rel.items():
        size = os.path.getsize(os.path.join(ROOT, "patched", fname))
        lba = max(lba, start + (size + 2047) // 2048)
    return lba


def strip_blob(data):
    """Undo the old in-bank scheme (bank + pad + MAGIC blob + pointer). A
    bank without a blob is returned byte for byte: its own trailing nulls
    are real data and the scene record's size counts them."""
    at = data.rfind(struct.pack("<I", MAGIC))
    return bytearray(data[:at].rstrip(b"\x00")) if at >= 0 else bytearray(data)


def scene_record(exe, idx):
    return list(struct.unpack_from("<II", exe, SCENE_TABLE + idx * 12))


FACE_SITES = (0x80049A3C, 0x80049B6C)  # `addiu v0,v0,0x18; sll s1,v0,0x10`
                                          # in 0x80049904: x = 24 + 72*col for
                                          # a cleared column and a loaded one


def face_stub(at):
    """s1 = x << 16 as 0x80049904 computes it, or FACEX when a faceleft
    payload is live (the frame the band opens then draws nothing at the
    native columns; the payload places the speaker next frame). Both
    sites become `jal here` with the addiu in the delay slot.
    #44: the script re-runs the face setup mid-line too; the renderer then
    built one frame at FACEX before FACE_X put the speaker back (a
    one-frame blink). The column the payload shows (FACECOL = s3, the
    loop's column; 3 = none) goes straight to FACE_X instead. Ten words:
    the loader hook leaves 42 bytes."""
    a = Asm(at)
    a.lui("$t8", hi(SCRATCH))
    a.lw("$t9", FACEX - SCRATCH_BASE, "$t8")
    a.lw("$v1", FACECOL - SCRATCH_BASE, "$t8")
    a.beq("$t9", "$zero", "ret")
    a.sll("$s1", "$v0", 0x10)                  # (delay slot) native x
    a.bne("$v1", "$s3", "ret")                 # another column
    a.or_("$s1", "$t9", "$zero")               # (delay slot) off-screen
    a.lui("$s1", FACE_X)                       # the speaker: in place
    a.label("ret")
    a.jr("$ra")
    a.nop()
    return a.assemble()


def band_stub():
    """Replaces the type-0 entry step's menu-window test (ENTRY_TEST):
    v0 = menu word bit 26, or 0 while KEEP holds KEEP_MAGIC. The magic,
    not a flag: before the first payload runs the scratch holds whatever
    the intro FMV left there, and a stale non-zero would stop every menu
    in the game from closing."""
    a = Asm(BAND_STUB)
    a.lui("$v1", 0x0400)
    a.and_("$v0", "$v0", "$v1")
    a.lui("$a1", hi(KEEP))
    a.lw("$a1", lo(KEEP), "$a1")
    a.lui("$v1", KEEP_MAGIC >> 16)
    a.ori("$v1", "$v1", KEEP_MAGIC & 0xFFFF)
    a.bne("$a1", "$v1", "back")
    a.nop()
    a.or_("$v0", "$zero", "$zero")             # keep: "no menu window open"
    a.label("back")
    a.j(ENTRY_TEST + 12)                       # the beqz, delay slot intact
    a.nop()
    code = a.assemble()
    assert BAND_STUB + len(code) <= VOICE_STUB, len(code)
    return code


def voice_stub():
    """Replaces the type-2 prepare's box-open test (VOICE_TEST): v0 =
    window word bit 28, or 0 while KEEP2 holds KEEP_MAGIC - our text is
    up and the box must survive into the next line - and while a timed
    close is armed (bit 31, the blank cue's engineclose) with the task still
    in WAIT: that close is coming within 0x1F ticks, and the prepare's own
    slide-out on top of it parked frame and fill 120 px low for the rest of
    the scene (#65: B1E0's paper, a short card cleared mid type-on, the
    next line's prepare 40 frames later). a1 already carries the
    step the caller jumps to; only v0, v1 and $at are touched."""
    a = Asm(VOICE_STUB)
    a.lw("$v1", TASK_FN, "$s0")                # the dialogue task's step
    a.lui("$at", STEP_WAIT >> 16)
    a.bgez("$v0", "noarm")                     # v0 = the raw window word
    a.ori("$at", "$at", STEP_WAIT & 0xFFFF)    # (delay) at = WAIT
    a.beq("$v1", "$at", "nobox")               # bit 31 armed in WAIT: the
    a.label("noarm")                           # task closes the box itself
    a.addiu("$at", "$at", STEP_CLOSE - STEP_WAIT)  # (delay) at = STEP_CLOSE
    a.beq("$v1", "$at", "nobox")               # a close already sliding
    a.lui("$v1", 0x1000)                       # (a press on our card skips
    a.and_("$v0", "$v0", "$v1")                # the line and the prepare
    a.lui("$v1", hi(KEEP2))                    # came mid-fade: two slides)
    a.lw("$v1", lo(KEEP2), "$v1")
    a.lui("$at", KEEP_MAGIC >> 16)
    a.ori("$at", "$at", KEEP_MAGIC & 0xFFFF)
    a.bne("$v1", "$at", "back")
    a.nop()
    a.label("nobox")
    a.or_("$v0", "$zero", "$zero")             # "no box open"
    a.label("back")
    a.j(VOICE_TEST + 12)                       # the beqz, delay slot intact
    a.nop()
    code = a.assemble()
    assert VOICE_STUB + len(code) <= BAND_STUB_END, len(code)
    return code


def band2_stub():
    """Replaces the band open's box-open test (BAND_OPEN_TEST) with the
    VOICE_STUB rule: "no box" while our close is already sliding
    (STEP_CLOSE) or our text is up (KEEP2). A press on our card skips the
    voice line; our WAIT step starts the slide-out and ~10 frames later the
    script's band open saw bit 28 still set and ran 0x8004920C's slide-out
    on top of it - two slides, the frame parked 120 px too low, and the
    next card opened off screen (Harry's conversation, 2026-09-07)."""
    a = Asm(BAND2_STUB)
    a.lui("$v1", 0x1000)
    a.and_("$v0", "$v0", "$v1")
    a.lw("$v1", TASK_FN, "$s0")
    a.lui("$at", STEP_CLOSE >> 16)
    a.ori("$at", "$at", STEP_CLOSE & 0xFFFF)
    a.beq("$v1", "$at", "nobox")
    a.lui("$v1", hi(KEEP2))
    a.lw("$v1", lo(KEEP2), "$v1")
    a.lui("$at", KEEP_MAGIC >> 16)
    a.ori("$at", "$at", KEEP_MAGIC & 0xFFFF)
    a.bne("$v1", "$at", "back")
    a.nop()
    a.label("nobox")
    a.or_("$v0", "$zero", "$zero")
    a.label("back")
    a.j(BAND_OPEN_TEST + 12)                   # the beqz, delay slot intact
    a.nop()
    code = a.assemble()
    assert BAND2_STUB + len(code) <= BAND2_STUB_END, len(code)
    return code


def close_gate():
    """In place of the type-0 handler's final `jal 0x80032654(task, entry)`
    (CLOSE_CALL). With a payload live (MARKER set, so the high-RAM block is
    installed) go through CLOSE_FIX, which finishes a close the new text
    would otherwise cut short (BUG-036); without one, straight through -
    the game never queues over its own close."""
    a = Asm(CLOSE_GATE)
    a.lui("$v0", hi(MARKER))
    a.lw("$v0", lo(MARKER), "$v0")
    a.lui("$v1", MAGIC_MARK >> 16)             # fills the load delay
    a.bne("$v0", "$v1", "thru")
    a.nop()
    a.j(CLOSE_FIX)
    a.nop()
    a.label("thru")
    a.j(0x80032654)
    a.nop()
    code = a.assemble()
    assert CLOSE_GATE + len(code) <= BAND2_STUB_END, len(code)
    return code


def press_stub():
    """Replaces the WAIT step's press test (PRESS_TEST): a button closes
    the box unless KEEP2 holds the magic, i.e. our text is up. Players
    press through dialogue by habit, and a press on a subtitle closed it
    while the voice ran on - the rest of the line was silent text-wise
    ("text disappearing", 2026-09-07). The payload's own clears still run
    on bit 31, which the WAIT step tests before the pad."""
    a = Asm(PRESS_STUB)
    a.beq("$v0", "$zero", "stay")
    a.lui("$v1", hi(KEEP2))
    a.lw("$v1", lo(KEEP2), "$v1")
    a.lui("$at", KEEP_MAGIC >> 16)
    a.ori("$at", "$at", KEEP_MAGIC & 0xFFFF)
    a.beq("$v1", "$at", "stay")
    a.nop()
    a.j(PRESS_TEST + 0x28)                     # 0x80047CDC: close
    a.nop()
    a.label("stay")
    a.j(PRESS_TEST + 8)                        # 0x80047CBC: the bit-31 test
    a.nop()
    code = a.assemble()
    assert PRESS_STUB + len(code) <= PRESS_STUB_END, len(code)
    return code


def menu_stub():
    """Replaces the list menu's slide test (MENU_SLIDE). The menu reuses
    the dialogue frame and slides it in from parked without asking whether
    a box is already open; with our text up (KEEP2 magic) the frame IS
    open, so the slide is skipped, the menu keeps our frame as its panel
    and HANDOFF tells the payload to let go of the box."""
    a = Asm(MENU_STUB)
    a.sltiu("$v1", "$v1", 0xF)
    a.lui("$v0", hi(KEEP2))
    a.lw("$v0", lo(KEEP2), "$v0")
    a.lui("$at", KEEP_MAGIC >> 16)
    a.ori("$at", "$at", KEEP_MAGIC & 0xFFFF)
    a.bne("$v0", "$at", "decide")
    a.sw("$a0", 0x18, "$a2")                   # the tick store, both paths
    a.lw("$v0", 0x18, "$a2")                   # first tick only: the stored
    a.lui("$at", 0x000F)                       # word is ticks+1
    a.ori("$at", "$at", 0xFFFF)
    a.and_("$v0", "$v0", "$at")
    a.addiu("$v0", "$v0", -1)
    a.bne("$v0", "$zero", "decide")
    a.nop()
    a.j(MENU_PARK)                             # high RAM: only with a payload
    a.nop()                                    # live, which the magic proves
    a.label("decide")
    a.bne("$v1", "$zero", "slide")
    a.nop()
    a.j(MENU_SLIDE + 0x50)                     # 0x8004DB60: set bit 28, next
    a.nop()
    a.label("slide")
    a.j(MENU_SLIDE + 0xC)                      # 0x8004DB1C: this tick's slide
    a.nop()
    code = a.assemble()
    assert MENU_STUB + len(code) <= MENU_STUB_END, len(code)
    return code


def install_engine(exe, rel):
    """Everything exec-side, identical for every scene: trampoline + hook
    into the service chain, the CD-command gate at both CdControl sites, and
    the scene-loader hook with its per-scene blob table. The table is
    rebuilt in full from what is on disk, so the 23 per-scene runs of a
    build all write the same words and the order does not matter."""
    hk = loader_hook()                         # first: it places flushgate
    tr = trampoline()
    assert TRAMP + len(tr) <= FILTER_STUB, "trampoline overruns into the stub"
    exe[P.fo(TRAMP):P.fo(TRAMP) + len(tr)] = tr
    struct.pack_into("<I", exe, P.fo(HOOK),
                     0x0C000000 | ((TRAMP >> 2) & 0x03FFFFFF))
    fs = filter_stub()
    assert FILTER_STUB + len(fs) <= REGION_END, "filter stub overruns"
    exe[P.fo(FILTER_STUB):P.fo(FILTER_STUB) + len(fs)] = fs
    struct.pack_into("<I", exe, P.fo(FILTER_CALL),
                     0x0C000000 | ((FILTER_STUB >> 2) & 0x03FFFFFF))
    struct.pack_into("<I", exe, P.fo(PUMP_CALL),
                     0x0C000000 | ((FILTER_STUB >> 2) & 0x03FFFFFF))
    struct.pack_into("<I", exe, P.fo(0x80061960), 0x0C017ACD)  # restore
                                                               # CdIntToPos
    # The second subsystem's direct Setloc site routes through the gate too
    # (the S000 dialogue playback issues its Setloc here, not via the pump).
    # NOT the M000 driver's Setloc at 0x8002C3C0: hooking that hot path
    # crashed a real session, and M000 lines already match by filter.
    struct.pack_into("<I", exe, P.fo(0x80061970),
                     0x0C000000 | ((FILTER_STUB >> 2) & 0x03FFFFFF))
    struct.pack_into("<I", exe, P.fo(0x8002C3C0), 0x0C017A46)  # original

    # scene-loader hook: callback pointer -> hook; hook code; blob table
    exe[P.fo(HOOK_CODE):P.fo(HOOK_CODE) + len(hk)] = hk
    face_at = HOOK_CODE + ((len(hk) + 3) & ~3)
    fs_code = face_stub(face_at)
    assert face_at + len(fs_code) <= HOOK_CODE_END, "face stub overruns the loader's slots"
    exe[P.fo(face_at):P.fo(face_at) + len(fs_code)] = fs_code
    for site in FACE_SITES:
        w0, w1 = struct.unpack_from("<II", exe, P.fo(site))
        assert w0 in (0x24420018, 0x0C000000 | ((face_at >> 2) & 0x03FFFFFF)), hex(w0)
        assert w1 in (0x00028C00, 0x24420018), hex(w1)
        struct.pack_into("<II", exe, P.fo(site),
                         0x0C000000 | ((face_at >> 2) & 0x03FFFFFF), 0x24420018)
    pg = preinit_gate()
    exe[P.fo(PREINIT_GATE):P.fo(PREINIT_GATE) + len(pg)] = pg
    assert struct.unpack_from("<I", exe, P.fo(PREINIT_CALL))[0] in (
        0x0C000000 | ((GAME_INIT >> 2) & 0x03FFFFFF), 0x0C000000 | ((PREINIT_GATE >> 2) & 0x03FFFFFF))
    struct.pack_into("<I", exe, P.fo(PREINIT_CALL), 0x0C000000 | ((PREINIT_GATE >> 2) & 0x03FFFFFF))
    ih_at = INTRO_HOOK
    ih = intro_hook(ih_at)
    assert ih_at + len(ih) <= INTRO_HOOK_END, f"intro hook {len(ih)} B overruns its slots"
    exe[P.fo(ih_at):P.fo(ih_at) + len(ih)] = ih
    assert struct.unpack_from("<I", exe, P.fo(INTRO_LUI))[0] in (0x3C078003, 0x3C070000 | (ih_at >> 16))
    struct.pack_into("<I", exe, P.fo(INTRO_LUI), 0x3C000000 | 7 << 16 | (ih_at >> 16))      # lui a3
    struct.pack_into("<I", exe, P.fo(INTRO_LUI + 4),
                     0x34000000 | 7 << 21 | 7 << 16 | (ih_at & 0xFFFF))                    # ori a3
    struct.pack_into("<I", exe, P.fo(LOADER_LUI),
                     0x3C000000 | 7 << 16 | (HOOK_CODE >> 16))          # lui a3
    struct.pack_into("<I", exe, P.fo(LOADER_LUI + 4),                # ori, not the
                     0x34000000 | 7 << 21 | 7 << 16 | (HOOK_CODE & 0xFFFF))  # original addiu:
                                                                     # 0x8AA8 would sign-extend
    table = bytearray((INTRO_SLOT + 1) * 4)
    for idx in range(INTRO_SLOT + 1):
        name = "SUBS_INTRO.BIN" if idx == INTRO_SLOT else f"SUBS_B{idx * 0x10:03X}.BIN"
        path = os.path.join(ROOT, "patched", name)
        lba = rel.get(name)
        if lba is None or not os.path.exists(path):
            continue
        sectors = (os.path.getsize(path) + 2047) // 2048
        assert lba < (1 << 20) and sectors < (1 << 12), (name, lba, sectors)
        struct.pack_into("<I", table, idx * 4, lba | sectors << 20)
    assert HOOK_TAB + len(table) <= HOOK_TAB_END
    exe[P.fo(HOOK_TAB):P.fo(HOOK_TAB) + len(table)] = table
    lh = longs_hook()
    exe[P.fo(LONGS_CODE):P.fo(LONGS_CODE) + len(lh)] = lh
    ltable = bytearray((INTRO_SLOT + 1) * 4)
    for idx in range(INTRO_SLOT):
        name = f"LONGS_B{idx * 0x10:03X}.BIN"
        path = os.path.join(ROOT, "patched", name)
        lba = rel.get(name)
        if lba is None or not os.path.exists(path):
            continue
        sectors = (os.path.getsize(path) + 2047) // 2048
        assert lba < (1 << 20) and sectors < (1 << 12), (name, lba, sectors)
        struct.pack_into("<I", ltable, idx * 4, lba | sectors << 20)
    assert LONGS_TAB + len(ltable) <= LONGS_TAB_END
    exe[P.fo(LONGS_TAB):P.fo(LONGS_TAB) + len(ltable)] = ltable

    # Every exec-side stub lives in font glyph slots, and pairfont.RESERVED
    # is what keeps pair glyphs out of them - so the two must agree, or a
    # stub lands on a live pair and one letter pair renders as garbage
    # game-wide (PRESS_STUB shipped at slot 1280 instead of 1337 once: `ep`
    # and `n?` corrupted, and the validator, which renders its expected
    # rows from the patched exec, matched the garbage against itself).
    import pairfont
    font_ram = 0x80074380                    # pairfont.FONT_BASE, in RAM
    reserved = [(font_ram + 18 * a, font_ram + 18 * (b + 1)) for a, b in pairfont.RESERVED]
    for name, lo_, hi_ in (("HOOK_CODE", HOOK_CODE, HOOK_CODE_END),
                           ("PREINIT_GATE", PREINIT_GATE, PREINIT_GATE_END),
                           ("INTRO_HOOK", INTRO_HOOK, INTRO_HOOK_END),
                           ("HOOK_TAB", HOOK_TAB, HOOK_TAB_END),
                           ("LONGS_TAB", LONGS_TAB, LONGS_TAB_END),
                           ("LONGS_CODE", LONGS_CODE, LONGS_CODE_END),
                           ("BAND_STUB", BAND_STUB, BAND_STUB_END),
                           ("BAND2_STUB", BAND2_STUB, BAND2_STUB_END),
                           ("PRESS_STUB", PRESS_STUB, PRESS_STUB_END),
                           ("MENU_STUB", MENU_STUB, MENU_STUB_END)):
        assert any(a <= lo_ and hi_ <= b for a, b in reserved),             f"{name} {lo_:#x}..{hi_:#x} is not inside a pairfont.RESERVED slot range"

    # the band-keep stub and the jump into it from the type-0 entry step
    bs = band_stub()
    exe[P.fo(BAND_STUB):P.fo(BAND_STUB) + len(bs)] = bs
    assert struct.unpack_from("<I", exe, P.fo(ENTRY_TEST))[0] == 0x8E021AF4   # lw v0,0x1af4(s0)
    struct.pack_into("<I", exe, P.fo(ENTRY_TEST + 4),
                     0x08000000 | ((BAND_STUB >> 2) & 0x03FFFFFF))       # j BAND_STUB
    struct.pack_into("<I", exe, P.fo(ENTRY_TEST + 8), 0)                 # nop
    vs = voice_stub()
    exe[P.fo(VOICE_STUB):P.fo(VOICE_STUB) + len(vs)] = vs
    assert struct.unpack_from("<I", exe, P.fo(VOICE_TEST))[0] == 0x8E021ACC   # lw v0,0x1acc(s0)
    struct.pack_into("<I", exe, P.fo(VOICE_TEST + 4),
                     0x08000000 | ((VOICE_STUB >> 2) & 0x03FFFFFF))      # j VOICE_STUB
    struct.pack_into("<I", exe, P.fo(VOICE_TEST + 8), 0)                 # nop
    b2 = band2_stub()
    exe[P.fo(BAND2_STUB):P.fo(BAND2_STUB) + len(b2)] = b2
    assert struct.unpack_from("<I", exe, P.fo(BAND_OPEN_TEST))[0] == 0x8E021ACC  # lw v0,0x1acc(s0)
    assert struct.unpack_from("<I", exe, P.fo(BAND_OPEN_TEST + 4))[0] in (
        0x3C031000, 0x08000000 | ((BAND2_STUB >> 2) & 0x03FFFFFF))      # lui v1,0x1000, or ours
    assert struct.unpack_from("<I", exe, P.fo(BAND_OPEN_TEST + 12))[0] == 0x10400003  # beqz v0,+3
    struct.pack_into("<I", exe, P.fo(BAND_OPEN_TEST + 4),
                     0x08000000 | ((BAND2_STUB >> 2) & 0x03FFFFFF))      # j BAND2_STUB
    struct.pack_into("<I", exe, P.fo(BAND_OPEN_TEST + 8), 0)             # nop
    assert BAND2_STUB + len(b2) <= CLOSE_GATE, len(b2)
    cg = close_gate()
    exe[P.fo(CLOSE_GATE):P.fo(CLOSE_GATE) + len(cg)] = cg
    assert struct.unpack_from("<I", exe, P.fo(CLOSE_CALL))[0] in (
        0x0C00C995, 0x0C000000 | ((CLOSE_GATE >> 2) & 0x03FFFFFF))      # jal 0x80032654, or ours
    assert struct.unpack_from("<I", exe, P.fo(CLOSE_CALL + 4))[0] == 0x03C02821  # move a1,fp
    struct.pack_into("<I", exe, P.fo(CLOSE_CALL),
                     0x0C000000 | ((CLOSE_GATE >> 2) & 0x03FFFFFF))      # jal CLOSE_GATE
    ps = press_stub()
    exe[P.fo(PRESS_STUB):P.fo(PRESS_STUB) + len(ps)] = ps
    assert struct.unpack_from("<I", exe, P.fo(PRESS_TEST))[0] in (
        0x14400009, 0x08000000 | ((PRESS_STUB >> 2) & 0x03FFFFFF))      # bnez v0,+9, or ours
    assert struct.unpack_from("<I", exe, P.fo(PRESS_TEST + 4))[0] == 0x261422B0  # addiu s4,s0,0x22b0
    struct.pack_into("<I", exe, P.fo(PRESS_TEST),
                     0x08000000 | ((PRESS_STUB >> 2) & 0x03FFFFFF))      # j PRESS_STUB
    ms = menu_stub()
    exe[P.fo(MENU_STUB):P.fo(MENU_STUB) + len(ms)] = ms
    assert struct.unpack_from("<I", exe, P.fo(MENU_SLIDE))[0] in (
        0x2C63000F, 0x08000000 | ((MENU_STUB >> 2) & 0x03FFFFFF))       # sltiu v1,v1,0xf, or ours
    assert struct.unpack_from("<I", exe, P.fo(MENU_SLIDE + 8))[0] == 0xACC40018  # sw a0,0x18(a2)
    if not os.environ.get("NO_MENU_STUB"):
        struct.pack_into("<I", exe, P.fo(MENU_SLIDE),
                         0x08000000 | ((MENU_STUB >> 2) & 0x03FFFFFF))   # j MENU_STUB
        struct.pack_into("<I", exe, P.fo(MENU_SLIDE + 4), 0)             # nop
    else:
        struct.pack_into("<I", exe, P.fo(MENU_SLIDE), 0x2C63000F)
        struct.pack_into("<I", exe, P.fo(MENU_SLIDE + 4), 0x10600012)


def main():
    mode = sys.argv[1]
    exe = bytearray(open(P.EXE, "rb").read())
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    skey = "orig_record_" + SCENE
    if "orig_record" in state and SCENE == "ISZ_B010":
        state[skey] = state.pop("orig_record")   # migrate the old key
    rel = json.load(open(RELOC)) if os.path.exists(RELOC) else {}
    if INTRO:
        data = b""
    else:
        data = strip_blob(open(BANK, "rb").read())

    # The bank itself is no longer touched: no padding, no pointer word, no
    # relocation of its own. A padded bank from the old scheme is stripped
    # back and its scene record restored (the old scheme moved it).
    sname = SCENE + ".BIN"
    cur = [0, 0] if INTRO else scene_record(exe, SCENE_INDEX)
    if INTRO:
        pass                                   # no bank, no scene record
    elif cur[1] == 45056 and skey in state:
        # the exec still carries the old scheme's record (padded bank in a
        # slot of its own): put the LBA back. The recorded SIZE is not
        # trusted - repoint has grown several banks since those records were
        # taken, and a short size truncates its appended labels.
        orig_lba = state[skey][0]
        if rel.get(sname) not in (None, orig_lba):
            rel.pop(sname)                     # our old padded slot
        if orig_lba * 2352 >= os.path.getsize(SRC_IMG):
            rel[sname] = orig_lba              # repoint's relocation: keep
        cur = [orig_lba, len(data)]
    else:
        # fresh build: the record is repoint's; its size must be the file's
        if cur[1] != len(data):
            print(f"  note: scene record size {cur[1]} != bank {len(data)} B; using the file")
            cur[1] = len(data)
    if not INTRO:
        state[skey] = cur
        struct.pack_into("<II", exe, SCENE_TABLE + SCENE_INDEX * 12, *cur)
        if len(data) < cur[1]:
            data += b"\x00" * (cur[1] - len(data))
        open(BANK, "wb").write(data)

    if mode == "off":
        if os.path.exists(SUBS_FILE):
            os.remove(SUBS_FILE)
        rel.pop(os.path.basename(SUBS_FILE), None)
        json.dump(rel, open(RELOC, "w"))
        json.dump(state, open(STATE, "w"))
        install_engine(exe, rel)
        open(P.EXE, "wb").write(exe)
        print("off: blob removed, scene record restored, table rebuilt")
        return

    raw = json.load(open(sys.argv[2], encoding='utf-8'))
    scene_opts = {}
    if isinstance(raw, dict):                  # committed per-scene format
        scene_opts = raw.get('options', {})
        cues = [c for c in raw['cues'] if c.get('enabled', True)]
        for c in cues:
            c['text'] = c.pop('en')
        cues.append({'start': 0, 'end': 0, 'file': 0, 'chan': 2,
                     'speaker': '', 'text': ''})
    else:                                      # legacy list format
        cues = raw
    test_every = 256 if "--test-clear" in sys.argv else None
    blob = bytearray(build_blob(HIRAM, cues, test_every, scene_opts))
    if test_every:
        print(f"TEST BUILD: dismiss fires every {test_every} framectr ticks")
    if len(blob) > HIRAM_MAX:
        raise SystemExit(f"payload {len(blob)} B exceeds HIRAM_MAX {HIRAM_MAX}")
    struct.pack_into("<I", blob, 0, PREMAGIC)  # `done` completes it in RAM
    blob += b"\x00" * (-len(blob) % 2048)
    open(SUBS_FILE, "wb").write(blob)

    bname = os.path.basename(SUBS_FILE)
    lba = rel.get(bname)
    if lba is not None:
        need = len(blob) // 2048
        for other, at in rel.items():
            if other != bname and lba < at < lba + need:
                lba = None                     # slot too small now
                break
    if lba is None:
        rel.pop(bname, None)
        lba = next_free_lba()
    rel[bname] = lba
    json.dump(rel, open(RELOC, "w"))
    # The bank's long strings + remap group (repoint.py: work/longs/<S>.bin,
    # placed at LONGS) go out as LONGS_<S>.BIN, read right after the payload.
    lname = os.path.basename(LONGS_FILE)
    lsrc = os.path.join(ROOT, "work", "longs", SCENE[4:] + ".bin")
    lblob = b""
    if not INTRO and os.path.exists(lsrc):
        lblob = open(lsrc, "rb").read()
        if len(lblob) > LONGS_MAX:
            raise SystemExit(f"{lname}: {len(lblob)} B of longs exceed LONGS_MAX {LONGS_MAX}")
        lblob += b"\x00" * (-len(lblob) % 2048)
        open(LONGS_FILE, "wb").write(lblob)
        llba = rel.get(lname)
        if llba is not None:
            need = len(lblob) // 2048
            for other, at in rel.items():
                if other != lname and llba < at < llba + need:
                    llba = None
                    break
        if llba is None:
            rel.pop(lname, None)
            llba = next_free_lba()
        rel[lname] = llba
    else:
        rel.pop(lname, None)
        if os.path.exists(LONGS_FILE):
            os.remove(LONGS_FILE)
    json.dump(rel, open(RELOC, "w"))
    json.dump(state, open(STATE, "w"))
    install_engine(exe, rel)
    open(P.EXE, "wb").write(exe)

    print(f"{SCENE}: {len(cues)} cues, payload {len(blob)}B at {HIRAM:#x} "
          f"({HIRAM_MAX - len(blob)} B headroom); bank {len(data)}B untouched")
    print(f"  {bname} at LBA {lba}, {len(blob) // 2048} sectors")
    if lblob:
        print(f"  {lname} at LBA {rel[lname]}, {len(lblob) // 2048} sectors ({len(lblob)} B at {LONGS:#x})")
    for c in cues:
        print(f"    {c['start']}-{c['end']}  {c['speaker']:8s} {c['text'][:40]!r}")


if __name__ == "__main__":
    main()
