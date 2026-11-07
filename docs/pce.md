# The PC Engine CD port

How *Snatcher CD-ROMantic* (Konami, 1992, PC Engine Super CD-ROM², Japan only)
works, and how the English patch changes it. The PlayStation port has its own
document, [ps1.md](ps1.md): the PCE build carries the PlayStation's English and
borrows several of its designs (the face-left subtitle layout, the 6x13 face, the
card-cutting rules, the label edit operations), and this document points there
instead of restating them. Building from your own dumps is in
[BUILDING.md](../BUILDING.md) (`python build.py pce [--release]`); the formats of
the files under `pce/translation/` are in
[pce/README.md](../pce/README.md).

Every tool named here lives in `pce/tools/` unless another path is given, and
nearly every one is `python pce/tools/<tool>.py apply` in the build plus a
`show`/`check`/`preview` mode for looking without writing. Each module's
docstring is the detailed reference for its area.

Contents:

1. [Overview](#1-overview)
2. [Disc, file table and memory](#2-disc-file-table-and-memory)
3. [Text](#3-text)
4. [Font and letter pairs](#4-font-and-letter-pairs)
5. [Names, menus, keyboard and search](#5-names-menus-keyboard-and-search)
6. [Voice subtitles](#6-voice-subtitles)
7. [Graphics](#7-graphics)
8. [Boot splash](#8-boot-splash)
9. [Build order and outputs](#9-build-order-and-outputs)
10. [Testing tools](#10-testing-tools)
11. [Engine reference](#11-engine-reference)

---

## 1. Overview

The disc has 24 tracks. Track 2 is the game, MODE1/2352 sectors with user data
at byte 16 of each sector and no filesystem. Track 1 (the warning a CD player
plays) and tracks 3 to 24 are CD-DA (Red Book audio): the music, and eighteen
tracks of spoken dialogue mixed over music (the opening newsreel, the Act 2
recap, the bike ride, the epilogue and others). The game needs the Super
System Card 3.0. Its 192 KB of extra RAM holds the resident code, the current
scene module and the scene's pictures.

What the patch changes:

| Area | How |
|---|---|
| Dialogue | every scene module's text re-encoded in English; references rewritten; overflow moved out of the module |
| Font | the glyph fetch hooked to draw two halfwidth letters in each 12x12 cell |
| Menus, names | word lists rebuilt in English; speaker names moved into the modules |
| Typed input | Latin keyboard picture, key table and name search |
| Voice | subtitles for the ADPCM voice lines and the CD-DA dialogue, drawn by a resident stub in the vblank handler |
| Graphics | title menu, opening cards, captions and credits, memo pages, videophone cards, labels, ending roll |
| Boot | a translation card and an animated splash before the title |

**The patch source is the disc as one file.** The redump set's 24 track files,
concatenated in order (`copy /b` / `cat`), are byte-identical to the single BIN
that `chdman extractcd` writes from the redump CHD. `build.py` joins them into
`work/pce/snatcher_pce.bin`, checks the SHA1 and writes the matching single-file
cue. Track 2 grows (see 2.3), so the patched image ships with its own cue,
whose later track times are shifted.

## 2. Disc, file table and memory

### 2.1 Boot

The IPL loads stage 1 at `$3000`. Stage 1 checks for the System Card, maps
MPR2-6 to banks `$68-$6C` and reads stage 2 (track 2 sector 22, 15 sectors)
into bank `$68`, at `$4000`. Stage 2 is the resident engine. It occupies SCD
RAM banks `$68-$6A`:

| Bank | File offset | Mapped at | Holds |
|---|---|---|---|
| 0 (`$68`) | `0x0000-0x1FFF` | `$4000` (always) | the vblank handler, CD and file loader, the byte fetch FETCH, the file table, the script queue |
| 1 (`$69`) | `0x2000-0x3FFF` | `$6000` (MPR3, when needed) | the object walker, the display-list interpreter |
| 2 (`$6A`) | `0x4000-0x5FFF` | `$6000` (when text runs) | the text decoder, the glyph fetch, the renderer, the ADPCM service |

Throughout this document an address inside stage 2 is a CPU address; its file
offset is `address - 0x4000` (bank 0) or `address - 0x2000` (banks 1 and 2,
both mapped at `$6000`).

### 2.2 The file table and "rec" numbers

Stage 2 keeps a file table of 8-byte records
`{rec_hi, rec_lo, rec_mid, mode, bank, bh, sectors, 0}`. `rec` =
`hi<<16 | mid<<8 | lo` is **track-relative**: a file's first sector is
`T2 + rec`, where `T2` = 4174 is track 2's first sector in the joined image.
Files are named by that number throughout the tools ("rec 110", "module 318").
`pcetable.py` reads the table into `work/pce/filetable.json`, which every other
tool reads:

| Group | Table at | Contents |
|---|---|---|
| 0 | `$5505` | six system files: rec 110 is the resident system file (loaded at `$6000`, first bank `$7B`), rec 54 the voice bank (bank `$82`, loaded once) |
| 1 | `$5535` | the 33 scene modules: bytecode and text (rec 158 to 670, 16 apart) |
| 3 | `$563D` | six per-act ADPCM voice tables (recs 86, 90 ... 106, three sectors each) |
| 2 | `$566D` | the scene blocks: pictures and their display lists. The run continues past the group pointers and is read until the records stop looking like records |

Two other records matter throughout:

- **rec 750** is loaded with the title and stays resident all game in banks
  `$6B/$6C`. It holds the 18 item close-ups (six sprite picture streams and
  their display lists).
- **recs 858 and 758** are the two opening blocks (100 sectors each, over banks
  `$6C-$84`), and **rec 130** is the ending's code file.

Past relative sector 7858, track 2 is ADPCM voice data (about 108 minutes),
addressed by the per-act voice tables (section 6.1).

### 2.3 Scene modules and the 16-sector cap

A scene module loads into banks `$7E-$81`: 16 sectors, 32 KB, base pointer
`$3F80` = `$68` folded into every bank number the engine computes. Sector 17
would land on bank `$82`, the act's voice table, so **16 sectors is a hard cap**.
The build pads every module to exactly 16 sectors and keeps its own data in the
top of the fourth bank (section 3.6).

| Module | Scene | Module | Scene |
|---|---|---|---|
| 158, 270, 286, 302 | save handlers | 318 | JUNKER HQ, Act 1 |
| 174, 190 | videophone | 334 | factory ruins |
| 206 | the telephone quiz | 350 | JUNKER HQ after the factory |
| 222 | Gaudi's database | 366, 574 | Gillian's home |
| 238 | the Act 2 recap | 382, 526 | Gibson's house |
| 254 | Gaudi's name search | 478, 622 | JUNKER HQ, Act 2 / final part |
| 510 | Oleen Hospital, the cockpit | 590 | basement, morgue |
| 638 | Act 3 start | 670 | the ending |

(`pce_saves.MODULES` lists all 33.)

**Room for growth.** Track 2 is packed to its last sector, and the game plays
music by track number, so the CD-DA tracks can move. `patch_pce.fresh_copy`
copies the source image and inserts `RESERVE` (600) blank MODE1 sectors at the
end of track 2, before track 3's pregap. It then rewrites the cue with every
later INDEX shifted by 600 sectors. `Image.alloc` hands out sectors from the old
end of data (relative 33970) on, and `Image.retable` repoints a file-table
record. Anything that outgrows its record moves there: grown modules, the long
string blobs (3.5), the splash blob (8). The reserve sits **inside** track 2,
because some drives cannot read sectors past a data track's end.

**Sectors** are Mode 1, unlike the PlayStation's Mode 2 Form 1: EDC at +2064
over bytes 0-2063, ECC P/Q at +2076/+2248 over bytes 12-2075 with the header
included. `patch_pce.fix_sector` regenerates both, byte-exact against pristine
sectors.

### 2.4 Scene blocks and the module window

A scene block loads into SCD RAM at `$3F80 + bank` and is reached through the
MPRs. All the engine's reads of module data go through **FETCH** (`$5341`):
`$90/$91` hold an offset from the module base and `$92` is zero. FETCH maps
bank `$16 + [$3F80] + (ptr >> 13)` at MPR6 (`$C000`). The pointer's top three
bits pick one of eight "windows":

| Window | Pointer | Bank | Use |
|---|---|---|---|
| 0-3 | `0x0000-0x7FFF` | `$7E-$81` | the module |
| 4 | `0x8000-0x9FFF` | `$82` | the voice bank (subtitle overflow tables ride here) |
| 5 | `0xA000-0xBFFF` | `$83` | sound and music data |
| 6, 7 | `0xC000-0xFFFF` | `$6B`, `$6C` | **added by the patch**: long strings (3.5) |

## 3. Text

### 3.1 Modules and the script

A module is `[bytecode][menu word list][text]`. The interpreter's say opcode is
`12 <mode> 00 lo hi`, where `lo|hi` is the string's offset from the module start.
**Every mode references a string** (2-5 the dialogue box, 1/6/7 Metal Gear's
lines, 8, 10, 30-74 the terminals), so the rebuild remaps every `12 xx 00`
reference (`REF_ANY`). Opcode `62 lo hi` (and `1c 62`) points at blank
placeholder strings that hold the box while a picture shows, and is remapped
too. There is no pointer table: strings decode sequentially, so the text block
starts at the lowest referenced offset. `pcescript.strings_of` extends it
backwards to strings that only an earlier reference names.

Other opcodes the tools rely on: `f1 lo hi` names a menu item by its module
offset; `1c f3 NN GG` queues voice line NN of table GG; `09 lo hi` sets a flag,
`35 addr id` jumps on one (a bit array at `$3595`); `33 var16 f1 ref` shows a
menu entry while a flag is set; `1c 54 var16` adds an item.

### 3.2 The dialogue codec

Dialogue is not Shift-JIS on the disc. It is a stream of **12-bit codes**,
nibble-packed (two codes in three bytes), decoded by `$7272` (`pcetext.py`).
A code is `n:b` (4 + 8 bits):

| Code | Meaning |
|---|---|
| `b >= 0x40` | a JIS level-1 kanji, SJIS rows 0x88-0x98 (lead byte from `n`), trail byte `b` |
| `b < 0x40`, `n = 0` | end of string |
| `b < 0x40`, `n = 1, 2` | a run of `b` one-byte characters follows (punctuation, hiragana, katakana or fullwidth alphanumerics) |
| `b < 0x40`, `n >= 3` | SJIS rows 0x81-0x84 |

SJIS `82F2-82FF` are in-text commands, not glyphs: line end (`<nl>`), page wait
(`<wait>`), message end (`<end>`) and `82F8-82FF` = `<cmdN>`, emitted as
`FE n`. The colour commands are cmd1 white, cmd2 yellow, cmd3 red, cmd5 cyan,
cmd6 green (Gaudi's terminal).

### 3.3 The English

`pcescript.py dump` writes each module's Japanese to `work/pce/script/<rec>.json`.
The English is keyed by line, not by module:

- `pce/translation/dialogue.json` maps `key(jp)` (12 hex digits of the line's
  SHA1, so no Japanese is committed) to English, with the codec's tags kept.
  One entry serves every module that carries the line.
- `dialogue_hand.json` has the same shape and wins over the seeded file. It
  covers lines the PlayStation version lacks (the PCE save system, the
  shooting range, the quiz).

`pce_reuse.py` seeds `dialogue.json` from the PlayStation translation
([ps1.md](ps1.md)): it matches each PCE line to a PS1 string by its bare Japanese,
ignoring punctuation, breaks and colour codes. It prefers a PS1 `long` over a
shortened `en` because the PCE box has no byte budget, then re-breaks the text
for the PCE box and turns `＠` colour codes into commands. `pce_stitch.py` covers
a long PCE line with a run of PS1 lines. `pce_reuse.py --refresh <commit>` and
`pce_words.py --refresh` carry later PS1 changes over without touching
hand-edited entries.

**Layout.** The box is **18 cells x 3 rows**, and an English cell holds two
letters (section 4), so a row is 36 letters. The wrappers break at 17 cells
(`pcescript.WRAP`) because a row of exactly 18 wraps by itself. Gaudi's terminal
strings (`<cmd6>`) are 14 cells wide and re-broken by words (`terminal_wrap`).
`align_colours` moves one character across a colour change that would otherwise
split a letter pair.

**Markers.** Every English string starts with the code `84 40`, which raises the
English flag for the message (section 4). A module whose every string is English
sets `ALL_EN` (module `0x7FFB`) = 1 instead, and its strings drop the marker.

### 3.4 The dictionary

When a module's English overflows, `pcedict.py` turns frequent runs of **cells**
into row-0x84 codes `0x41-0xFF` (190 entries, table at `DICT_PTR` `0x7FFC`).
Working on cells rather than characters keeps each reference on a cell
boundary, so rows keep their widths. The decoder stub sees such a code with the
English flag up, saves the string pointer, decodes the entry (an ordinary
nibble stream) and returns. It saves about a quarter of the text.

### 3.5 Long strings outside the module

Even with the dictionary, a few modules exceed 16 sectors with the full English
(318, 350 and 478, by 1.8-4.7 KB). `pcescript.build` evicts their largest strings
into a **longs blob** (same codec, same markers) written as its own record in
the reserved sectors. `pcelongs.py` arranges for it to be read into banks
`$6B/$6C` after the module loads:

- **Where.** `$6B/$6C` is rec 750, the item close-ups, resident all game. Each
  blob therefore goes where its own module never shows an item (`PLACE`): 318
  over streams S0-S2 at `$6B:0000` (318 only shows items 9, 10 and 14), 350 in
  the `0xFF` fill at `$6C:1758`, and 478 over S5 at `$6C:0CF4` (no module from
  478 on shows items 14 and 15).
- **Pointers.** The evicted strings' references become pointers in windows 6/7
  (`0xC000+`). FETCH (`$5341`, 40 bytes rewritten in place) maps those windows
  to `$6B`/`$6C`.
- **The read.** The shared loader's completion at `$54F1` jumps to a hook for
  every completed group-1 (module) read, so the blob comes in whichever way the
  module was entered: scene start, CONTINUE, or an interpreter-driven change
  such as the recap's. The scene start's `JSR $5451` and init block (`$50E7`,
  92 bytes) are compressed into a bridge that maps stage 2's bank 1 at MPR3,
  calls the hook in bank 1's free tail and restores MPR3. The init calls run
  from a table with X preserved.
- **Descriptors** in the module's last bank tell the hook what to read, each
  copied into the BIOS argument bytes `_al.._dh` with one TII and read with
  `CD_READ`: `DESC` (`0x7FE3`, 9 bytes) is the blob's read and its bank (0 =
  none), and `REST` (`0x7FDB`, 8 bytes) re-reads rec 750's `$6B` half first.
  Every module below 478 carries `REST`, so 318's overwrite never outlives
  318.

`pceverify` decodes evicted strings from the blob, and `pcelongs.py check`
checks the built descriptors, blobs and patches. Setting `LONGS_IN_MODULE=1`
skips the eviction.

### 3.6 A module's tail

The build writes the module's own data at fixed offsets from its start, at the
top of its fourth bank:

| Offset | Size | Contents |
|---|---|---|
| `0x7B5C` (`FONT_OFF`) | 95 x 12 B | the 6x12 halfwidth font (section 4), up to `0x7FD0` |
| `0x7FDB` | 8 | `REST`: rec 750's restore read (longs) |
| `0x7FE3` | 9 | `DESC`: the longs blob's read (`_al.._dh`, mode 0, its bytes to its place) and its bank |
| `0x7FF0` | 2 | `PAIRS_PTR`: the pair table |
| `0x7FF3` | 2 | `CUES_PTR`: the CD-DA cue block (0 = none) |
| `0x7FF5` | 2 | `MAGIC`: a checksum of the module's first 256 bytes |
| `0x7FF7` | 2 | `SUBS_PTR`: the voice-line subtitle table |
| `0x7FF9` | 2 | `SEARCH_PTR`: the name-search table (module 254) |
| `0x7FFB` | 1 | `ALL_EN` |
| `0x7FFC` | 2 | `DICT_PTR`: the dictionary's slot table |
| `0x7FFE` | 2 | `NAMES_PTR`: the speaker-name table |

The text, names, dictionary, pair table and subtitle table sit between the end
of the word list and `FONT_OFF`. `pcescript.py apply` records where every string
and table went in `work/pce/build_map.json`; `pceverify.py` and the later tools
read it.

## 4. Font and letter pairs

The game draws text with the System Card's 12x12 font (`EX_GETFNT`, 18 bytes a
glyph). It is in the card's ROM, so no glyph can be added. The glyph fetch in
stage 2 (`$6473`) is instead hooked (`pceengine.py`, at `$648C`): while the
English flag is up (or, outside a message, while the module's `ALL_EN` is set),
a code in SJIS rows **0x88-0x98** is a **letter pair**, composed on the fly into
the 32-byte glyph buffer from a 6x12 halfwidth font the module carries at
`FONT_OFF`. The face is X11 misc-fixed 6x13 with its blank top row trimmed
(`lib/bdffont.py`, `lib/fonts/6x13.bdf`), the same face as the PlayStation
build.

**Pair codes.** Rows 0x89-0x97 give 184 codes each (2,760 slots), plus row 0x98
with trail bytes under 0x9F and row 0x88 from 0x9F up (94 each, the two halves
the codec's `n=8` case splits): 2,948 codes. A code is a slot in **the module's
own pair table** (`PAIRS_PTR` -> `[n u16]`, then n entries
`{glyph a, glyph b}`, glyph = ASCII - 0x20). The encoder hands slots out in order
of first use (`pcepair.PairTable.slot`), so any two printable characters can
share a cell. A module needs 330-940 pairs; slot 0 is always two spaces, which
the subtitle stub uses for padding. Encoders run inside
`pcepair.using(table_for(rec))`. Later tools reload the build's tables from
`work/pce/pair_tables.json`, and decoders read the module's own
(`PairTable.from_module`).

**The English flag.** The decoder hook (`$733F` -> `dhook`) raises it on the
`84 40` marker and routes other row-0x84 codes to the dictionary. The message
init (`$7204`) clears it. It drops once the message's last row has drawn
(`$7521`, `$66F5`), since rows draw asynchronously (`$3470`). A label left in
kanji in an all-English module would draw as pair glyphs, so every label has an
English form.

**Where the stubs live.** Stage 2's speaker-name list (`$6D47-$6FBB`, 629
bytes) moves into the modules, freeing its bytes for the compose, decoder and
name-lookup stubs. `asm6280.py` assembles them (an HuC6280 subset; a label used
before its definition is refused). `sim6280.py` runs them against real module
data, and `huc6280.py` disassembles stage 2, its banks and rec 110
(`pcetable.py dump` writes them out).

## 5. Names, menus, keyboard and search

**Speaker names.** The name lookup (`$70A7` -> `ncopy`) reads a module table at
`NAMES_PTR`: 74 u16 offsets, each entry `{attr, codes.., FF}` in the old list's
format but pair-coded (`pce/translation/names.json`). An entry must not cross an
8 KB bank.

**Menus.** Verbs, Ask topics and room labels are raw Shift-JIS records separated
by `0xFF` in each module's word list, and the bytecode names an item by module
offset (`f1 lo hi`). `pcescript.word_block` therefore rebuilds the list at any
length, and `remap_labels` rewrites every `f1`. The labels come from
`pce/translation/words.json`: `pce_words.py` looks each label up in the PS1
translation, `HAND` holds the PCE's own, and a key may be module-qualified
(`"254:ミカ"`). **The list's highlight box is 8 cells wide and cuts the rest**, so
every label is at most 8 cells; a digit or symbol alone costs a whole cell.
`pceverify` fails on a longer one.

**Data strings.** What the engine matches against player input keeps its
Japanese form or becomes **fullwidth Latin**: wildcards, `以外` catch-alls, dial
numbers, and in the data lists (`pcescript.DATA_LISTS`) the kana keyboard's row
records, which must stay because the keyboard is built on them.
`pce_words.KEYS` gives the typed answers (Gaudi's search keys, BENSON, OLEEN and
QUEEN, the chess pieces) as fullwidth Latin, one glyph per key.

**The keyboard** (`pcekeyboard.py`) has three parts:

- **A picture.** A 129-tile stream at VRAM `$2000` in each act's computer-room
  block (recs 1266, 2482, 3186, 3506), laid as BAT rows 32-39. A-Z are redrawn
  in a bold 6x8 face where the kana were, in the picture's own ink and paper.
- **A key table** in rec 110, 30 bytes a row at `0x5AC1/0x5AF1/0x5B21`. The
  threshold at `0x5BF1` makes letters go in as Ａ-Ｚ.
- **The kana row records** in module 254, which stay as they are.

**The name search** (`pcesearch.py`, in rec 110). On OK the engine walks
fifteen kana row records and takes the first row whose record contains the
typed name's first character (`$BA41`), then compares the typed name with the
names filed under that row. Latin initials cannot index kana rows, so `$BA41`
jumps to a stub at `$BE56`. The stub asks the module's own table
(`SEARCH_PTR`: `{row u16, name u16}` pairs, `FFFF` after the last, written by
`pcescript.search_table` from the bytecode's filing) whether the row holds the
typed name. A module whose `SEARCH_PTR` reads 0 or `FFFF` gets the engine's scan
back; the videophone modules 174 and 190 use it for numbers. Two more stubs
clamp the typed length to at least 8 (`$B754`, `$B784`) and decide keyboard or
pad without the catch-all record's lead byte (`$B72B`).

## 6. Voice subtitles

The PCE shows no text while a voice line plays: the voice opcode hides the
window (`$39BF` = 8). The patch adds subtitles from a stub that runs every
vblank. `pcesubs.py` builds the stub, the tables and the hooks, and its
docstring is the full reference. The English comes from the PlayStation
port's cue files ([ps1.md](ps1.md)), matched to the
PCE's lines.

### 6.1 Where the voices are

**ADPCM lines.** `1c f3 NN GG` queues `0d NN`, record NN of the act's voice
table. The table is loaded into bank `$82` over the head of the voice bank
(rec 54). A record is `{type, ch, 0, sec lo, sec hi, count, 0, rate}`: `count`
sectors of OKI MSM5205 ADPCM from relative sector `sec`, at `32000 / (16 - rate)`
Hz (rate `0x0E` = 16 kHz) (`pcevoice.py`). The ADPCM service in the text bank
(`$6220`, `AD_TRANS` at `$6281`, `AD_PLAY` at `$62C2`) plays or streams it, and
`0a` waits for AD_STAT to read stopped.

**Identifying a line.** The vblank handler runs the game's frame engine (picture
decoding, the object walker, the renderer), and one pass can span frames. A line
is therefore detected after the fact: AD_STAT rising from stopped. Its NN comes
from the record pointer `$5E/$5F` (`$8000 + (NN-1)*8`; from `$8800` on are the
effects'). The same NN in two acts is told apart by the record's sector field;
such keys read `c8.5` in the JSON.

**CD-DA dialogue.** The game plays tracks with `CD_PLAY` to the start of the next
track. The CD service sets `$2638` the tick it confirms a play, and `$263B` holds
the track in BCD. From then the stub counts frames by zero page `$1B` (the
vblank count) and shows the cue whose span holds the count. A cue folds into
the AD_STAT verdict, so the rest of the stub treats it as a line. Placed tracks:

| Module | Tracks | Module | Tracks |
|---|---|---|---|
| opening (858, 758) | 17, 19 | 510 | 7, 8, 9 |
| 238 | 5, 6 | 590 | 10 (the game plays it before the tunnel, 606, loads) |
| 318 | 20 | 622 | 11, 12, 13 |
| 350 | 3 | 638 | 14 |
| 462 | 4 | 670 | 16 |

### 6.2 The hook and where the stub lives

One hook replaces the vblank handler's `JSR $6021` (the CD service, `$4262`)
with `JSR` to a 76-byte trampoline in bank 0's gap (`$5BB4-$5BFF`). The
trampoline runs the service, then looks for a stub by signature in three places:

1. **rec 110's free tail**, its first bank (`$7B`) at MPR5. This holds the
   face block (signature `FL1`, at `$AFC4`), then the stub with `SB3` as its
   last bytes. The file loads sector by sector with the hook live, so the
   trampoline checks a head and a tail signature. This is the normal case.
2. **the module's fourth bank** at MPR4, entry `$9000` (module `0x7000`). The
   ending (670) runs without rec 110 and carries a two-row stub of its own.
3. **bank `$6C`** at MPR4, the same entry. The opening's blocks each carry their
   own stub there (6.6).

A module carries only its **table**: `SUBS_PTR` at `0x7FF7`, behind a checksum of
the module's first 256 bytes (`MAGIC` `0x7FF5`), which the stub recomputes
through FETCH before trusting the table. Tables that do not fit in their module
(478), the face signatures, the ending's CD-DA cues and the CD-DA clock's code
go into the voice bank's runs that are free at runtime: `0x940-0xFFF` and
`0x1800-0x1F2F` of rec 54's first bank, reached through window 4, and the
signatures at `0x7E3A` (`OVERFLOW_RUNS`, `SIG_AT`). `0x1F30-0x1FFF` is not
free: the game copies a table there.

**Table format.** `[names offset u16]`, then entries
`[NN][sector u16][len u16][fpc u16][char][chunks...]`, a 0 after the last, then a
names block `[char][colour][cells][pairs]...` ending in 0. A chunk is
`[cells | colour << 5][pair codes]`. A marker is `00` + a mask (page and row
bits per layout); mask bit `0x20` is a **hold**: the byte after it is added to
the page's cells as time, so a page stays up while the voice is still on its
words. `fpc` is frames per cell in 8.8 fixed point. A page turns after its
cells' (and holds') time, counted on frames the chip reads playing. A line with
`turns` in its cue file (the seconds at which its cards 2, 3... come up, measured
from the Japanese voice by `pce/tools/pceturns.py`) is paced to them: `fpc` is the
fastest slot's, every other slot filled with holds; a line without them is paced
evenly over the clip (`FRAMES_PER_SECTOR` 14.8 frames a sector). `char` is a 1-based
index into `pcesubs.CHARS`, which only ever grows by appending. The CD-DA block at
`CUES_PTR` is `[magic u16][names offset u16]`, then
`[track BCD][start u16][end u16][len u16][fpc u16][char][chunks]`, with times in
frames from the track's start.

### 6.3 Drawing the rows

The stub uses the game's own renderer. It lays the page out as a message in its
buffer (`MSG_RES` `$3A66` for the resident stub, `$3610` for the module stub) and
starts it the way the message opcode does (`$3471` = the message, `$3470` = 1),
never through the script queue at `$3C00`. In the resident stub each row opens
with the renderer's `f8 lo hi` base opcode, so its cells land in tiles the stub
chose, and before the terminator the message puts back the game's base
(`0x7000`). The module stub draws at the game's base, in region 6 or 7. The game's own base
word `$3F32` is never written, because the ending's loader keeps its own value
there.

The text window is the game's: BAT rows 43-50 at columns 32-63. Showing it
means `$39BF` = `0x56`, `$39CF` = 1 and zero page `$27` = 1, which makes the
raster sections follow. The stub maps the window's BAT to its rows' tiles and
zeroes the tiles before every page. A picture scene the game sets up after the
window opened can clear `$27`, which turns the band dark under a page; the
stub then maps all eight window rows again (its rows, the rest blank) and sets
`$27`, unless the new picture has already been decoded into the rows' tiles
(a plane-3 bit there: text never uses colours 8-15) or the scene is the Act 2
recap. Setting `$27` alone would show the game's own window mapping over
picture tiles.

**Face regions.** A portrait's bitmap lives at VRAM `0x6000 + region * 0x800`
(regions 4-7, sprite patterns `0x300-0x3FF`). The game's text rows use regions 6
and 7. **The game animates the speaker's mouth by writing cells into its face
region**, so text never shares the speaker's region. `rowsel` picks a free
region for the page: 4 or 5 first, then 6 or 7 when no face object draws from
them. When every region is in use, it borrows one (never the speaker's), keeps
that face off screen, **parks** its bitmap in a free region with `vcopy`
(bank 1's tail, VRAM to VRAM through the data port) and copies it back when the
rows leave. A region the game decoded a picture into for this module (logged
by hooks on the display-list handlers' `JSR $4763`) is never treated as free.
The resident stub packs all of a page's rows into one region, each row with its
own base.

| Layout | Rows | Cells a row | x |
|---|---|---|---|
| face (resident) | 4 | 10 | 104-223, beside the portrait |
| face (module stub) | 2 | 12 | 104-247 |
| plain | 2 | 18 | 20-235, the name inline in its colour |

A page is laid out again only when its rows move or the layout changes.

**VDC discipline.** Every long run of VDC writes (clears, BAT maps, region
copies) runs with interrupts **on** and zero page `$30` = 2. That is the game's
own guard: a nested vblank takes the handler's short path, and the raster
sections (BXR/BYR per band, chained from the RCR interrupt) keep their lines.
Bank 1 goes at MPR3 only under that guard. The stub saves and restores `$90-$92`
and `$F7` (the game's label copy fetches through them) and mirrors the VDC
select register in `$F7` as the game does.

### 6.4 Portraits

A portrait is three objects (base, eyes, mouth). The game's object walker
(bank 1 `$6000`) rebuilds the whole sprite table (VRAM `0x1000`, 64 entries)
from the object tables every pass. The **face block** hooks the walker's exit
(`$6072`, `WALKER_HOOK`) and edits the **sprite table** only. It never touches
the object tables, which the script reads. While a line is up:

- A face object is one whose sprites draw patterns `0x300-0x3FF` on the band
  (y from `0xA0`) and that the game's own flag (bit 1 of `$3000,X`) does not
  hide.
- A face is identified by four words of its bitmap (`SIG_OFFS` `0x88, 0xA8, 0xC8,
  0xE8`: the hair, which never animates) against the signatures in
  `pce/translation/faces.json`.
- The **speaker's** face stays and moves so that its visible cells' left edge
  sits at `FACE_X` (32). Every other face's sprites on the band go off.
- If the speaker has no known face up, the line waits up to `GRACE` (200)
  frames for one, with every face off meanwhile, then falls back to the plain
  layout.
- A line's end unmaps the rows and keeps the faces for `LINGER` (40) frames.
  The window is left as the game sets it: the next voice opcode hides it while
  it maps its own BAT over the text tiles, so putting it back would show the
  last line's words for a frame. A CD-DA cue ends with its span.
- A list or game message taking the window ends the display at once (`$3518`
  changing, `$3478`).

Nothing is restored afterwards: the next walker pass draws the game's layout.
`pce/harness/pcefaces.py` builds the signature table from play. It takes the
region whose mouth sprite changes most during a line as the speaker's, and
`learn` merges a census into `faces.json`.

### 6.5 Cue data and card cutting

`pce/translation/subs_<rec>.json` maps a voice key (NN in hex) to
`{speaker, en, ps1, layout, cards}`. `cdda_<rec>.json` lists
`{track, start, end (seconds), speaker, en, layout, cards, ...}`. The schema is in
[pce/README.md](../pce/README.md). How the drafts are made:

- `pceasr.py` transcribes every line (faster-whisper, Japanese) into
  `work/pce/asr_cache.json`.
- `pcematch.py <rec>` matches each PCE line to a PS1 stream by character-bigram
  Dice similarity and takes that stream's cards. The takes are the same
  recordings.
- `pcecdda.py` matches CD-DA tracks to the PS1's stereo reels and warps the
  reel's cards onto the track's clock (piecewise-linear over matched segments).
- `pcecdalign.py` re-times cues from word stamps, aligning the two Japanese
  transcripts character by character. Hand-placed timings in
  `work/pce/cdsync/` win.

**Cards.** A `cards` field (rows split by `|`) is taken as written, after checks
that the words are the line's own and fit. Otherwise `pcesubs.greedy_cards` plans
the cards with `lib/cardplan.py`, the rule shared by every port: as many whole
sentences as fit a card, then clause, phrase and word breaks, no widows, and
numbered items open a card. `pcelayout.py` chooses page boundaries using the
renderer's exact cell costs. A face card is four rows (one page beside the
face); a plain card is two rows, with the name on the first. A `layout` of
`plain` never waits for a face. A line marked `display: graphic` emits no
overlay, because the picture already shows the passage.

### 6.6 Special scenes

- **The ending (670)** runs without rec 110, so its module carries the stub.
  The epilogue is a scene block with no window section, so the stub adds its
  own raster sections (slot 14 for the picture's scroll, slot 15 for the rows
  from line 192) and draws in palette entries the wallpaper does not use
  (`EPI_COLOURS`).
- **The opening** (tracks 17 and 19: the newsreel and Gillian's profile,
  `pceopening.py`, `cdda_opening.json`) runs before rec 110 and the voice bank
  load. Each opening block carries its own stub in `$6C` `0x1000-0x1FFF`, which
  is free in both. The game's renderer would hold the opening's pictures back,
  so this stub does not use it. Pages are wrapped (40 letters, 2 rows, centred)
  and timed at build time, then drawn from the vblank pass as 1-bit glyphs into
  VRAM `0x7800` tiles, mapped at BAT rows 43-50 in palette 14 on a solid black
  band. Two raster sections of its own (slots 14/15) show the band. Stage 2's
  raster path (`$42F9-$4334`, rewritten in place) turns sprites off below the
  band's line when slot 15's enable byte reads `SPR_OFF` (`0xA5`). In the
  opening `$2638` is a one-frame pulse, and the count runs while `$263B` still
  names the track.
- **The CD-DA wait** (`pcecdguard.py`). Opcode `0b` (`$4CE7`) waits for a track to
  stop. Some drives play past the requested end into the next track. The
  rewritten opcode (same 22 bytes) also ends the wait when the sub-Q track
  (`$20A2`) is no longer the requested one (`$263B`), pausing the drive first.

## 7. Graphics

### 7.1 Formats (`pcecodec.py`, `pcescene.py`, `tilescan.py`)

Pictures are drawn by **display lists** (interpreter `$6F00`): a header, then
6-byte records `{bank, type, vram_lo, vram_hi, ptr_lo, ptr_hi}` until a bank of
`FF`. `bank` maps at `$8000` (MPR4-6 = `$3F80 + bank` ...), so `ptr` is in
`$8000-$DFFF`. Types 8 and 4 point at `{flags, rowlen, stream}`: with flags bit 6
the stream is **BAT words** in `rowlen`-byte runs, and with bit 5 the runs are
columns of the 64-wide map. Other types point at
`{flags, remap[flags & 0x7F], stream}`, tiles recoloured through the remap.

The stream is a byte RLE whose output (through `$71B0`, a 128-byte buffer
pushed as four 8x8 planar tiles) **is VDC tile data**:

| Control | Output |
|---|---|
| `00 n b` | n pairs of (b, literal) |
| `01 lo hi b` | b repeated `lo|hi<<8` times |
| `02 n b1 b2` | (b1 b2) n times |
| `03-3F b` | b repeated c times |
| `40-7F` | `c & 3F` zero bytes |
| `80 lo hi` / `81-BF` | literal bytes follow |
| `C0-FD` | `c & 3F` pairs of (0, literal) |
| `FE n b1..b4` | (b1..b4) n times |
| `FF` | end |

(n = 0 means 256.) Palette records (`$6B94`) are `{vce_lo, vce_hi, ptr_lo,
ptr_hi, bank}`, holding 9-bit GGGRRRBBB colours. Every graphics tool re-encodes
its streams **in place**: a new stream must not outgrow the old one and is padded
to its length (`titlemenu.encode`). A sprite table entry is
`{cgx/size, dy, dx, pattern, attr}`.

### 7.2 What is redrawn

| Tool | What | Where |
|---|---|---|
| `titlemenu.py` | NEW GAME / CONTINUE (16x16 sprite cells, Arial Bold), the CASE FILES header | rec 958, and the copy the game returns to after a game over |
| `opencards.py` | the disclaimer, dedication and notice cards (tile pictures, 6x13, centred per line as on the PS1); the date/place sprite captions (*June 6, 1991*, *Moscow*, *50 years later*, *NEO KOBE CITY*); the building caption KONAMI OMNI BLDG / JUNKER HQ | rec 858, rec 758; the caption is a ready-decoded message in rec 126, moved to the file's free tail with its copy loop (`$8B77`) repointed |
| `pcecredits.py` | the 23 opening credits: RLE sprite strips to VRAM `$7000` with their sprite tables, all rewritten as type-02 tables in the shared 688-byte region | rec 758 |
| `pcecards.py` | Gibson's 13 memo pages (PS1 page texts reused), the epilogue card, the videophone's "not in service" and "no video signal" cards | rec 2802 (and 1586), 7218, 3506, 3570 |
| `pcelabels.py` | Gibson's note (a rec 750 item close-up, also in an older unreferenced twin at track sector 722), the reception's poster close-up, the opening newspaper's boxed headline; edit operations as the PS1's `gfxlabels.py`, from `pce/translation/gfx_labels.json` | rec 750, blocks 5/13/33, rec 858 |
| `pceending.py` | the ending's credit roll | rec 130 |

**The ending roll.** The roll walks 409 line pointers (file `0x051D`, u16,
`$8000`-based). Each line is ready-decoded: 14 cells of SJIS, colour codes
`fe 02`/`fe 01`, and `ff` at the end. No decoder runs, so the English is written
as pair codes (`pcescript.label_bytes`), centred, and every row opens with
`f9 81`, which selects the 12x12 font because the pair glyphs are drawn for it.
Module 670 gets the font and `ALL_EN` so the glyph hook composes the pairs. The
three level-2 lines that are the Konami logo are copied as they are.

Left Japanese: background signage, the newspaper's date line, vertical columns
and the second paper.

## 8. Boot splash

`pcesplash.py` adds a 3-second translation card and a 10.7-second animated
splash (the PlayStation's [bootsplash](ps1.md), redrawn for 256 pixels) before the
title:

- **Hook.** Stage 1's `LDA #0 / TAM #$80` at `$30A4`, just before it reads stage 2,
  becomes `JSR $3300; NOP`. The loader in stage 1's zero tail (`$32A0-$37FF`)
  reads the blob (magic `PEPASPLASH`, at most 5 banks, from a fixed place in the
  reserve) into `$70-$74`, maps it at `$4000-$DFFF` and calls it. On return it
  zeroes `$70-$7F`, restores MPR2-7, and stage 1 carries on.
- **Player.** It runs with `PHP/SEI` and paces on the VDC status VD bit, so the
  BIOS vsync handler never runs. It saves the whole VRAM into `$78-$7F` and the
  palette, then sets a 64x32 map (MWR `0x10`: the card in columns 32-63, the
  disclaimer in 0-31, switched by BXR) and double-buffered SAT DMA. It replays
  a timeline: the endoskeleton (the PS1's `CXE_B0D0` parts, quantised to one
  15-colour sprite palette plus a dark-eyed copy) walks in, the disclaimer comes
  up line by line, and eight palette steps fade it out.
- **Exit.** It puts VRAM back and restores the VDC registers measured at the
  hook (CR `0xC8`, MWR/BXR/BYR/DCR 0, DVSSR `0x0700`), with the palette black
  except entry 511.

The title comes up about 840 frames later than on the original. The art comes
from the PlayStation build's extracted graphics, so the PS1 disc is a build input
(see [BUILDING.md](../BUILDING.md)).

## 9. Build order and outputs

`build.py pce` prepares the source (joins the tracks, writes the cue, runs
`pcetable.py`; the PS1 preparation runs first because the PCE reads the PS1's
English and art), then runs `pce/tools/<tool>.py apply` for each tool in order,
then `pceverify.py`:

| # | Tool | Does |
|---|---|---|
| 1 | `pcescript` | fresh copy of the image with the reserve; every module rebuilt (text, words, names, dictionary, longs eviction, subtitle tables, pair table, font); the stage-2 engine stubs (`pceengine.install`); `build_map.json` |
| 2 | `titlemenu` | title menu sprites |
| 3 | `opencards` | opening cards, sprite captions, building caption |
| 4 | `pcekeyboard` | Latin key picture and key table |
| 5 | `pcesearch` | name-search, length and input-kind stubs in rec 110 |
| 6 | `pcesubs` | the vblank hook, trampoline, face block and stub in rec 110; voice-bank overflow; walker and logger hooks |
| 7 | `pcelongs` | FETCH windows 6/7, the loader-completion hook and bridge, the blobs |
| 8 | `pcecredits` | opening credits |
| 9 | `pceending` | ending roll |
| 10 | `pcecards` | memo pages, epilogue, videophone cards |
| 11 | `pcelabels` | note, poster, headline |
| 12 | `pceopening` | the opening's own subtitle stubs and pages; the raster patch |
| 13 | `pcesplash` | boot card and splash |
| 14 | `pcecdguard` | the CD-DA wait |
| - | `pceverify` | reads the built image back; exit 1 on any problem |

Each `apply` edits `patched/pce/snatcher_pce.bin` in place. Only `pcescript`
starts from the pristine source, so the chain runs as a whole.
`pce/build/Build-PCE.bat` is the Windows twin.

**Verification.** `pceverify.py` walks every module the file table names and
decodes each string with the Python decoder (dictionary references expanded,
pairs rendered back to letters, evicted strings read from their blob). It
compares each against the intended English, checks every menu label (8 cells)
and speaker name, and measures every row against the box.

**Release** (`--release`, `pcerelease.py`): an xdelta patch against the joined
source, the shifted cue, `README.txt`, `apply.bat`/`apply.sh` (which do the
joining for the player) and a zip, in `release/pce/`, versioned by
`pce/VERSION`. `--chd` also writes a CHD of the build for local testing, never
into the zip.

## 10. Testing tools

All headless tools host **Beetle PCE** (`mednafen_pce_libretro`) through
`lib/emurun.py`. **Only a fresh boot of the built image tests a build**: a
savestate carries the modules, rec 110 and the stubs it was taken under, while
a BRAM save loads everything from the disc.

| Tool | Purpose |
|---|---|
| `pce/harness/pcerun.py`, `pceboot.py` | boot and run for N frames; boot to the reception's verb menu |
| `pce/tools/pcestate.py` | BaseRAM, VRAM, CDRAM, SysCardRAM, ADPCM.RAM and SaveRAM out of a state |
| `pce/harness/pcemenu.py` | **the pilot**: steers on the engine's list state in RAM (section 11) and plays routes from `pce/harness/routes/` (`choose`, `read`, `sweep`, `items`, `shot`, `save`, `dial`, `type`, `phone`, `light_scan`, `wait`, `repeat`, `press`); fights by aiming at the biggest sprite cluster; `LINELOG=1` logs every line and subtitle page |
| `pce/harness/regress_saves.py` | boots each scene's BRAM save fresh (title > CONTINUE > CASE FILES), plays its route or a generic sweep, tables cards drawn, voice lines with and without a subtitle, lines without a portrait; `--jobs` |
| `pce/harness/mint_saves.py`, `pce/tools/pce_saves.py` | mint a BRAM save per module (2 KB, checksum = negated 16-bit sum); push to a MiSTer or RetroArch |
| `pce/harness/text_integrity.py`, `rendered_text.py` | the longs banks against the disc at settled menus; live text buffers checked against the module's pair table |
| `pce/harness/pcestress.py` | a continuous New Game to ending pilot that never restores a state or writes RAM, keeping screenshots and states as evidence |
| `pce/harness/pcefaces.py` | the portrait census behind `faces.json` |
| `pce/harness/sync_audit.py` | offline: every multi-page voiced line's page turns, as the build paces them, against when the Japanese voice says each card's words; lists the lines that drift past a threshold and exits 1 - run it after any change to the cards or the pacing |
| `pce/harness/regress.py` | **the regression, whole**: freezes the image, runs the opening check, the three acts (act 2 and 3 from their saves) and every scene save in parallel with the coverage routes (`coverage_routes.json`, `coverage_run.py`), then `sync_audit` and `table_check`, and judges every log: pages, timing, coverage gate, glitches, stopped routes; `work/pce/reg/<run>/summary.txt` |
| `pce/harness/subtext.py` | every subtitle page the pilot logged (`subpage`, LINELOG=1) against the line's or cue's English (WRONG TEXT, BAD GLYPH), the screen's reading of it (GARBLED ON SCREEN, `screentext.py`), and its timing on screen: a line's first page over 1.5 s after its voice (LATE PAGE), a card off its turn by 0.75 s (LATE TURN), a line that played and showed no page at all (NO PAGE) |
| `pce/harness/screentext.py` | reads a page off the screen glyph by glyph (the 6x12 module font) and holds it against the rows the stub laid out |
| `pce/harness/table_check.py` | offline: every line and cue decoded back from the built image's tables (the lines no run reaches included) |
| `pce/harness/opening_check.py` | the opening's 30 pages read off the screen at six points each |
| `pce/harness/voice_coverage.py` | modules loaded, voice lines played, CD-DA cues shown; `--gate` fails on any gap `coverage_known.json` does not excuse (with why) |

Libretro results are not proof for hardware; the image is also played on real
consoles and FPGA cores.

## 11. Engine reference

### Memory

| Where | What |
|---|---|
| `$2000-$3FFF` | BaseRAM (zero page `$2000`); the BIOS argument bytes `_al.._dh` at `$F8-$FF` |
| `$3F80` | the SCD RAM base (`$68`), added to every bank number |
| `$68-$6A` | stage 2 (bank 0 at `$4000`, banks 1/2 at `$6000` in turn) |
| `$6B-$6C` | rec 750 (item close-ups), resident; the longs blobs |
| `$6C-$84` | the opening blocks while the opening runs |
| `$70-$7F` | the splash's blob and VRAM save (boot only) |
| `$7B-$7D` | rec 110, the resident system file (loaded at `$6000`); free tail of its first bank from `0xFC4` = the face block and stub |
| `$7E-$81` | the scene module (16 sectors) |
| `$82` | rec 54, the voice bank; the act's voice table over its head |
| `$82-$87` | sound-cue table and music |
| VRAM `0x1000` | the sprite table the walker builds |
| VRAM `0x6000 + r*0x800` | face regions 4-7; 6/7 = the game's text rows |
| BAT rows 43-50, cols 32-63 | the text window |

### Routines and hooks

| Address | What | Patched by |
|---|---|---|
| `$30A4` (stage 1) | before the stage-2 read | `pcesplash` -> `$3300` |
| `$4262` | vblank handler's `JSR $6021` (CD service) | `pcesubs` -> trampoline `$5BB4` |
| `$42F9-$4334` | raster section path | `pceopening` (`SPR_OFF`) |
| `$4C98`, `$4CE6` | opcode `0b`, the CD-DA wait | `pcecdguard` |
| `$50E7` | scene start: `JSR $5451` + init block | `pcelongs` bridge |
| `$5341` | FETCH (module byte, maps MPR6) | `pcelongs` (windows 6/7) |
| `$5451` | the scene loader | - |
| `$54F1` | loader completion | `pcelongs` hook |
| `$5505`... | the file table | `Image.retable` |
| `$6000` / `$6072` (bank 1) | object walker / its exit | `pcesubs` `WALKER_HOOK` |
| `$6F00` (bank 1) | display-list interpreter; `$6F60/$6FC8/$7019` handlers | `pcesubs` loggers on `JSR $4763` |
| `$6220`, `$6281`, `$62C2` | ADPCM service, AD_TRANS, AD_PLAY | - |
| `$63C0` -> `$6899` | window rebuild | `pceengine` `rclr` at `$689B` |
| `$6473` / `$648C` | glyph fetch / its `JSR $69C2` | `pceengine` compose |
| `$66F5` | `STZ $3470` (row done) | `pceengine` |
| `$6D47-$6FBB` | old speaker-name list | `pceengine` stubs |
| `$70A7` | name lookup | `pceengine` `ncopy` |
| `$7204` | message init | `pceengine` |
| `$7272`, `$7290`, `$733F`, `$7357` | text decoder, ends, row branch | `pceengine` |
| `$7521` | row-loop exit | `pceengine` |
| `$71B0` | tile output (RLE to VRAM) | - |
| `$B72B`, `$B754/$B784`, `$BA41` (rec 110) | input kind, length clamp, row scan | `pcesearch` |
| `0x5AC1/0x5AF1/0x5B21`, `0x5BF1` (rec 110) | key table, letter threshold | `pcekeyboard` |

### RAM variables

| Address | Meaning |
|---|---|
| `$347B` | list cursor |
| `$3518` | live list count (0 = none; the script can close a list without zeroing it, so watch for a change) |
| `$3478` | non-zero while a message owns the box |
| `$3490` | the highlighted item's codes |
| `$3470` / `$3471` | message running / message |
| `$3610` | the renderer's message buffer (94 bytes) |
| `$363E/$363F` | the typed name's first character |
| `$36B0` | the keypad's state (dialling) |
| `$39BF` / `$39CF` | text window (`0x56` shown, 8 hidden) / dirty |
| `$34B7` | `FF` after the voice opcode |
| `$3595` | flag bit array |
| `$3728` | 2-bit per-object counters |
| `$3F2C` | 1 during a shootout (with object `0x37` live) |
| `$2638`, `$263B` | CD play confirmed / its track (BCD) |
| `$26F2`, `$26F3` | AD_STAT copy / requested voice line |
| `$20A0`, `$20A2` | sub-Q status / track |
| `$5E/$5F` | the current voice record's address |
| `$1B` | the vblank count |
| `$27` | raster interrupt enable (the window's sections) |
| `$30` | the handler's re-entry guard (2 = nested vblanks take the short path) |
| `$F7` | VDC select register mirror |
