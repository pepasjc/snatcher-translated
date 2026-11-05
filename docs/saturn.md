# Snatcher on the Sega Saturn: how the English patch works

This document describes the Saturn port of the Snatcher English translation:
how the Japanese game is laid out on disc and in memory, and what each build
step changes. It is written for programmers. To build the patch, read
[BUILDING.md](../BUILDING.md). The PlayStation port has its own document,
[docs/ps1.md](ps1.md). The Saturn port reuses much of that design, and this
document links there for it instead of repeating it. The subtitle cue format
is documented in [saturn/translation/README.md](../saturn/translation/README.md).

All addresses are SH-2 addresses in the running game unless a file offset is
given. `MAIN_L.BIN` loads at `0x060B0000`, so its file offset = address -
`0x060B0000`.

## 1. Overview

The target is **Snatcher (Japan), Sega Saturn, T-9508G** (Redump, `V1.000`).
The disc has three tracks:

| Track | Mode | Contents |
|---|---|---|
| 1 | MODE1/2352 | ISO9660 data: the IP, `A.BIN`, `MAIN_L.BIN`, `DATA.BIN`, the reels `SDAIF_*.AIF`, sound banks |
| 2 | MODE2/2352, Form 2 | `ACT1.CAT`, `ACT2.CAT`, `ACT3.CAT` (the voice lines), `WARNING.DA` |
| 3 | CD-DA | audio |

The Saturn game is close to the PlayStation one. The 39 scene banks use the
PS1's bank layout and the same 2-byte text encoding. The 1,040 voice lines
are the same recordings, and the cinematic reels match the PS1's stereo XA
streams. So the English is **carried over from the PS1 translation** and is
not translated again. The Saturn tools match each Saturn string to its PS1
twin, copy the English across, and fit it to Saturn budgets and geometry.

What the patch changes:

- **Text**: every scene bank's strings (DATA.BIN entries 21-59), the speaker
  name table in the exec, long strings and over-budget lines carried at
  runtime by SH-2 remap stubs, and paging for lines longer than the box.
- **Font**: Latin letter-pair glyphs in an extended VDP1 font, and a new
  SJIS-to-glyph table.
- **Input**: a Latin keyboard, English name-search keys, English answers for
  the typed puzzles.
- **Voice subtitles**: a per-bank payload drawn from the frame wait, with
  face-left portraits and nameplate colours (the PS1's design).
- **Graphics**: memo pages, Gibson's diary, the New Game disclaimer, the
  opening's credit roll and caption, small labels, the keyboard faces.
- **Options**: a WALLPAPER screen on the title's OPTION MENU.
- **Boot**: two boot screens played from the IP before Konami's logo.
- **Disc**: `DATA.BIN` is re-packed from scratch, track 1 is rebuilt (and
  grows when needed), track 2's sector headers move with it.

The Saturn release is uncensored as shipped, so this port needs no
uncensoring step. The PS1 build takes one uncensored picture from the
Saturn disc (see [docs/ps1.md](ps1.md)).

## 2. Disc and files

### Boot chain

The BIOS loads the IP (track 1 sectors 0-15) at `0x06002000` and the first
root file, `A.BIN`, at `0x06010000`. `A.BIN` is a boot shell: the GFS/CD
library, the 68000 SCSP driver, and the TrueMotion movie player for
`LOGO.TRM`, `MX0.TRM` and `MX1.TRM`. It loads **`MAIN_L.BIN` at
`0x060B0000`** (259 KB, the game), keeps a backup copy of it at
`0x002B0000` in low work RAM, and jumps to it. The game calls back into the shell to play movies
(`0x060B59DC`). While a movie plays, the memory at `0x060B0000` belongs to
the player. `MAIN_L.BIN` is restored afterwards.

`MAIN_L.BIN` is a C image: text, data, then BSS from `0x060EF480` to
`0x060FF090`, then the heap. No file slack exists for new code: bytes
appended to the file land in BSS and are cleared at startup.

### DATA.BIN and the chunk table

`DATA.BIN` is a flat, sector-aligned pack of **639 chunks**. Only a table in
the exec addresses it: `0x060E62F4` holds 639 big-endian records
`{u16 sector, u16 size/2}`, with sectors counted from the start of the file.
`0x060B22EC(idx)` opens the file (`0x060B22B4`), and `load_chunk`
(`0x060B2F8C`) reads a chunk through a 2 KB sector cache. A second,
streamed loader (`0x060B2620`) serves large pictures.

| Chunks | Contents |
|---|---|
| 0 | the font (LZ3) |
| 0-7 | boot bitmaps |
| 21-59 | the 39 scene banks, raw, in PS1 order (21 = B000 ... 59 = B260) |
| 60-98 | room scripts, raw (chunk 60 + N for scene N) |
| 100+ | graphics containers (LZ3) |

Two banks differ from the PS1's split. Chunk 41 (scene B140) is a 902-byte
stub, and chunk 42 holds the PS1's B150 strings followed by B140's.

### LZ3 compression

561 of the 639 chunks use a three-stream LZ format, decompressed by
`0x060CB548` (setup `0x060CB6FC`). `saturn/tools/lz3.py` decodes it and
re-encodes it bit-exactly.

```
header   u32 outsize, u16 nwords, u16 nhalf          (big-endian)
bits     nwords x u32, consumed LSB-first
tokens   nhalf x u16
bytes    literals, short offsets, long lengths

bit 0          literal byte
bits 1,1       short match: dist = byte + 1 (1..256), len = 2 bits + 2 (2..5)
bits 1,0       token w (0 ends the stream): len = w & 15, off = w >> 4
                 len != 0: len + 2 (3..17), dist off + 1
                 len == 0: len = raw byte (1..255), dist = off
```

Matches address the output directly; there is no ring buffer. The step
function runs in time slices until the vblank counter reaches its argument,
and it stops only on the 0 token. The encoder (`lz3.encode`) does an optimal
parse over the four forms with a hash-chain match finder and beats Konami's
packer on almost every chunk.

### Graphics containers

A container (`saturn/tools/satgfx.py`) is a header list of `{u8 type, 3 x 0,
u32 size}` entries ended by eight `FF` bytes, then the sections back to back,
each 4-aligned:

| Type | Contents |
|---|---|
| 0 | VDP2 background: 8-bpp 16x16 characters, 240x128 or 480x256 |
| 1 | palettes: 256 x RGB555 per palette |
| 2 | sprite index: animation sequences and sprite lists `{u16 ctrl, u16 size, u16 clut, u16 srca, u16 x, u16 y}` |
| 3 | VDP1 sprite pixels, 8 bpp, addressed by the lists |

Each offset table in a type-2 index is padded to a multiple of four entries
(the registrar at `0x060B2CF0` rounds up).

### How the build re-packs DATA.BIN

The build does not patch `DATA.BIN` in place: `satpack.py` re-lays the whole
file. Every LZ chunk is re-encoded, raw chunks are copied, each chunk starts
at the next free sector in table order, and the table is rewritten. Each
chunk's content comes from the first of these sources that has it:

1. an override `patched/saturn/chunks/NNN.bin`: the decoded content for an LZ
   chunk, raw bytes for a raw one. Graphics tools write these.
2. the build's own `DATA.BIN`, as `satapply`, `satlong` and `satsubs` left
   it (font and banks).
3. the pristine file.

The streamed loader places two constraints on any re-encoded chunk:

- **In-place decode.** The packed bytes are read to the top of a 256 KB
  high-WRAM region and decoded upward from its bottom. On a large chunk the
  output can catch up with input not yet read. `inplace_margin` simulates
  the decode. A chunk with a negative margin keeps Konami's exact bytes,
  and an override with a negative margin is refused.
- **Sector spill.** Whole sectors are read, so `ceil2048(size) -
  ceil16(size)` bytes spill into the neighbouring region. A new chunk is
  zero-padded so it spills no more than the original did.

Each packed chunk is decoded back and compared with its intended content
before anything is written. Packed bytes are cached by content hash in
`work/saturn/pack_cache/`.

One chunk needs special care. The opening's street scene (chunk 387) decodes
a garbage tail that reads into the bytes of the credit-roll chunk 394. The
rebuilt 394 keeps Konami's bytes at `[0x228, 0x8000)` so that tail decodes
as before (see section 7).

### Track 1, track 2 and the IP

`satdisc.py` writes track 1 from pristine. `DATA.BIN` sits at LBA 96 and
`MAIN_L.BIN` follows it with no slack. The chunk table is file-relative, so
the file cannot move. When it grows, every file after it shifts. Each
shifted sector gets a fresh Mode 1 header and EDC/ECC, and every directory
record after `DATA.BIN` gets its new extent.

Pristine track 1 ends with 75 empty sectors. When the shifted files run past
the track's end, **track 1 grows** by `grow` sectors (keeping a 75-sector
tail) and the rest of the disc moves with it:

- the directory records of the track 2 files (`ACT*.CAT`, `WARNING.DA`) and
  the PVD's volume size get `+grow`;
- every track 2 sector header's MSF moves by `grow`. Form 1 ECC and Form 2
  EDC exclude the header, so only the header changes. The Mode 1 sectors of
  track 2's pregap are re-EDC'd;
- track 3 and the cue stay as they are (cue INDEX times are per file). No
  absolute frame address is hard-coded in `A.BIN` or `MAIN_L.BIN`.

The system area (sectors 0-15) is copied from pristine unless
`patched/saturn/IP.BIN` exists. `satsplash.py` writes that file (section 8).

## 3. Text

### Encoding and the text path

A bank's text is the PS1 encoding: 2-byte font-index codes, `￥` (line
break), `＠` + a colour kanji, and null-terminated strings. On the Saturn the
converter `0x060C4D24` copies a string and **negates every byte**, and the
result is Shift-JIS. The two encodings are the same thing seen from either
side, so `lib/textcodec.py`, the PS1 budgets and the PS1 pair codes all carry
over byte for byte.

A bank is `{u16 code_len, u16 str_len}`, then the bytecode, the string region
and a trailing u32. The scene loader `0x060B915E` puts the bytecode at
`0x002F8000` and the strings at `0x002E8000`, and the string base is kept at
`[0x060FD164]`. The region's window is 64 KB, ending where the bytecode
starts.

Dialogue flows as follows:

```
0x060B82A8(off) / 0x060B8390 (with speaker) -> [0x060FD164] + off
  -> 0x060C4D24 (negate to SJIS)
  -> layout 0x060B45C4(col, row, sjis)       ＠ colours via table 0x060E4DA8; ￥ = 0x818F
  -> cells at ctx 0x060F24B0 + 0x3FA + row*80 + col*4, {u16 sjis, u8 colour, pad}
  -> cell renderer 0x060B4970 -> 80 sprite records at 0x060E5358
```

The box is **4 rows x 20 cells** (14 cells when `ctx+0x56A == 7`, Gaudi's
terminal). The PS1's is 3 x 18. The blank cell is `0x889E`. List menus give
each item 10 cells, at cell `[0, 20, 40, 60, 10, 30, 50, 70][i]`.

The text engine is **synchronous**. Script execution, box slides, type-on and
the press wait are all loops around the frame wait `0x060B55A0`. Nothing in
the text path can be called from a per-frame hook. Code that draws text
(the subtitles) writes the cells itself.

### Carrying the PS1 English

`satdata.py script` dumps every bank to `work/saturn/ref/SAT_NNN_Bxxx.json`
(`off`, `budget`, `jp`). `satcarry.py run` matches each Saturn bank against
its PS1 twin. It runs `difflib` over the `￥`-stripped Japanese and assigns
one of these kinds:

| `carry` | Meaning |
|---|---|
| `exact` | the Japanese is identical |
| `rebroken` | only the `￥` placement differs |
| `candidate` | reworded. The PS1 line is offered as `en_candidate` and a person resolves it |
| `control` | engine records with no text |
| `new` | Saturn-only lines written by hand: backup-RAM and cartridge messages, the joke phone book, the extra cast |

The committed `saturn/translation/SAT_NNN_Bxxx.json` records hold `off,
budget, en, long?, lock?, src, carry, ...` and no Japanese. `src` names the
PS1 string the English came from. A PS1 row (at most 18 cells) fits the
Saturn's 20, so `￥` breaks carry over unchanged, and only rows that overflow
are re-wrapped. Gaudi's terminal strings (`＠緑` and `▽` rows in B030/B040)
are re-flowed at 14 cells by `satcarry.py terminal`, because the terminal
has no runtime wrap. Locked strings (engine data) follow the PS1's
`lock_data_strings` rules. A re-carry after the PS1 data changes is a
three-way merge, so hand edits in the Saturn files survive.
`satcandidates.py` lists the candidate records that still need adapting.

### Budgets and the in-place apply

`satapply.py` encodes every record's `en` with the PS1 `PairFont`, using the
Saturn pair table (section 4), and writes it at `off` inside `budget`
(null-terminated, zero-padded). Budgets are counted as on the PS1, and each
written string is decoded back and checked. A string over budget keeps its
Japanese in place and goes on `work/saturn/build/over_budget.txt`. `satlong`
then shows its English.

### Long strings and the remap stubs

`satlong.py` is the Saturn's version of the PS1 `repoint.py`. A record with a
`long` field (a fuller label than the slot holds), or one over budget, gets
its text stored outside the slot. The engine is redirected at runtime. **No
bytecode is changed.**

Bytecode names a string by a BE16 word index. Reader `0x060C08B0` turns it
into a region offset, and four consumers add the string base. Each consumer
calls through a literal-pool word, and `satlong` points each word at a stub:

| Pool word | Site | Original target |
|---|---|---|
| `0x060B835C` | show dialogue text (`0x060B82A8`) | converter `0x060C4D24` |
| `0x060B84A0` | show text with speaker (`0x060B8390`) | converter |
| `0x060B907C` | text op from `0x060C4B1A` | converter |
| `0x060C320C` | add list-menu item (`0x060C31A0`) | strlen `0x060DBEF8`, then strcpy into the 64-byte label table `0x060FAC60` |
| `0x060B93AC` | the loader's read helper `0x060B9144` | records the region length (`lenvar`) when the destination is the string base |
| `0x060B93B8` | the loader's trailing-u32 read `0x060B9108` | then streams the bank's LNGS payload |

`LOOKUP(r4)` finds the bank's remap group without any directory in the
exec. The last four bytes of the string region are a tail `{0xFFFF, group
offset}` (`0xFFFF` cannot occur in text). The group is `{u16 count, u16 pad,
(u16 old, u16 pad, u32 new) x count}`. A pointer that falls outside the
region, a bank without a tail, or a load with no region recorded all miss
and pass through unchanged.

Long texts do not live in the region. They follow the bank's trailing u32
as `{'LNGS', u32 length, bytes}`. The load hook streams them into **one
32 KB buffer that the game's own allocator owns** (`xmalloc` `0x060C4DA0`).
The buffer is allocated once and reused for every bank. On disc, long
pointers are biased by `LONGS_BASE` (`0x20201000`), and `LOOKUP` rebases
them onto the live buffer. The build rejects a bank whose longs exceed the
buffer. Search keys and typed puzzle answers stay inside the region, because
the keyboard code reads them there.

The game's two show-text routines (`0x060B82A8`, `0x060B8390`) convert every
line into a fresh allocation and never free it. The Japanese game leaks one
small block per card shown; the English pair codes make each block larger,
and the 32 KB pool takes its share of the 288 KB arena, so a long session
used to run out of heap and draw garbage text, then hang (issue #88). The
patch routes both routines' converter call through a stub that frees the
previous line's buffer before converting the next one: the buffer is dead
once its show-text call has returned, because the engine is synchronous and
the cells already hold the text.

When a bank's grown region outgrows its sector slot, `place()` moves it to a
slot another bank vacated or to the end of `DATA.BIN`. `satpack` then
re-lays everything regardless.

### Row accounting and paging

In the original layout code, a cell landing in the last column advances the
row with no bounds check, and a following `￥` advances it again. A full
row followed by `￥` therefore costs two rows. A fifth row writes cells past
the cell array into the game context, over the script PC at `ctx+0x58C`.
The Japanese never runs into this; English often would. `satwrap.py` points
two pool words at stubs:

- `0x060B4728` (write-cell): after a row's last cell, swallows a following
  `￥`.
- `0x060B4698` (the `￥` path's scroll call) and full row 3 with text still
  to come: instead of the engine's scroll, they call **`page`**. `page` runs
  the end-of-card wait (press cursor, pad loop, blip; `ctx+0xB74` set so the
  harness sees a waiting card), clears rows 3..start, and continues at the
  start row. Row 0 is kept when it holds a speaker's name, as the PS1's
  continuation pages keep the nameplate.

The engine's own scroll pushes the top row away while the text types on.
Paging keeps every row readable.

## 4. Font and pair glyphs

The font is DATA.BIN chunk 0, loaded by `0x060B4530` = `load_chunk(0,
0x25C08000, 0xD000)` straight into VDP1 VRAM in the form VDP1 draws:

- 112-byte blocks, each one 16x14 4-bpp sprite holding **four glyphs, one
  per bit-plane**. Glyph `g` is block `g >> 2`, plane `g & 3`, and the 12x12
  glyph sits at (1, 1) in its cell. The pristine font has 1,880 slots.
- The renderer sets `CMDSRCA = 0x1000 + 14*(g >> 2)` and `CMDCOLR = 0x2A00 +
  16*colour + 4*(g & 3)`. Each colour has a CLUT per plane.
- SJIS to glyph: a BE u16 table at **`0x060E6CF0`**, indexed by `sjis -
  0x8140`, 0x1734 entries, with no range check. 0 is the blank glyph. The
  font holds only the characters the Japanese game draws.

Because any table code can name any glyph, the **PS1 pair codes stay
verbatim** in the text. The build sets `table[code - 0x8140] = slot` for
each pair. See [docs/ps1.md](ps1.md) for the pair-glyph scheme itself.

The Saturn has a supply problem the PS1 does not. The font holds only the
used characters, and the Japanese text still left in a build keeps about a
thousand kanji in use. **`satglyphs.py` extends the font downward** into
VDP1 VRAM `0x4020..0x8000`, a range the game never writes, adding 146
blocks (584 slots) contiguous with the original:

| Patch | Original | New |
|---|---|---|
| loader destination / budget (`0x060B4590` / `0x060B458C`) | `0x25C08000` / `0xD000` | `0x25C04020` / `0x10FE0` |
| CMDSRCA base, both renderers (`0x060B4A58`, `0x060B9DD4`) | `0x1000` | `0x0804` |
| SJIS table | original glyph indices | shifted by +584, freed kanji -> 0, pair codes -> their slots |

`plan()` iterates the applied set, the drawn set and the free slots to a
fixed point. Slots go to the most frequent pairs of the wanted text,
including longs, names and subtitle rows. A pair whose PS1 code is a kanji
the Saturn build still draws gets a fresh, unused code. The result is
`work/saturn/pair_table_sat.json` (pair -> `[slot, code]`). `satapply`
rebuilds chunk 0 with these glyphs and writes the new table into the exec.
`--no-ext` builds a conservative layout without the extension.

Text cells sit at a 14-px pitch. `satpair.py` draws each pair as two 7-px
letters (X11 misc-fixed 7x13 from `lib/fonts/7x13.bdf`), baseline at cell
row 10, which keeps pairs, fullwidth fallbacks and kana on one line.
`satfont.py` dumps, renders and compares the font.

### Exec space

The exec has no free gaps, so the build creates one. The SJIS table's entries
for codes no drawn text can contain (Greek, Cyrillic and box drawing,
`0x83C0..0x889E`) are zero and unread. `satexec.py` computes the hole:
`used_codes()` collects every code a drawn text can contain (bank strings,
English and longs, names, cues, the exec's own strings, every pair code),
and `hole()` returns the longest run of zero entries outside that set,
currently `0x060E7220..0x060E7BAE`. One code inside the range, `0x83D6`
(ω, which some verbs end with), is in use and its entry must stay zero. The
computation leaves it out.

Allocation runs upward through a ledger, `work/saturn/build/exec_alloc.json`,
keyed on the exec's SHA-1. Each allocation is asserted to lie in the hole,
cover no used code, and still be zero. The tools allocate in this order:
names, satlong's stubs, satkeys, satsubs, satwrap, satspecial, satoptmenu.
A second source of space is the table entries for codes whose second byte
is not valid Shift-JIS (`satoptmenu.SPARE_RUNS`, 134-byte runs). The longs
buffer helper lives there.

## 5. Names, menus, keyboard, puzzles, wallpaper

### Speaker names

The speaker op `0x060B8390` lays out the speaker's name on row 0 with
`0x060B45C4(0, 0, sjis)`. The names are **plain SJIS**: 78 strings at
`0x060C17F4`, reached through 79 pointers at `0x060C1F18`, and they never
pass through the negating converter. `satnames.py` writes each English
name as the pair-code stream converted to SJIS (each byte negated), inside
the original `＠colour ... ＠白` wrapper. Names that do not fit the original
1,048 bytes go to the exec hole, and every pointer is rewritten. The source
is `saturn/translation/names.json`: the PS1 names, plus romanised names for
the 21 Saturn-only speakers. Name pairs join the glyph ranking.

### List menus and labels

Menu items pass through the `0x060C320C` stub, so long labels work in menus.
The 64-byte label entries limit a label to 63 bytes.

### Keyboard, name search and typed puzzles

`satkeys.py` covers the PS1's `patch_keyboard`, `kbdfaces` and `keytable`.
One routine, `0x060B9A74(list, keydata, maxlen, mode)`, drives every typing
screen. Mode 2 is the 15 x 4 kana keyboard; the numeric pads (modes 0/1/3)
are left alone. Cursor `{u16 col, u16 row}` at `0x060F2C00`, cell map
`0x060E5254`, key layout `0x060E5294` (60 x `{code, kind}`), typed buffer
`0x060EF6B4`.

**The matcher never sees text.** `0x060B9748` converts each live menu label
to one byte per character (SJIS low byte - 0x40), and the typed buffer is
compared against those bytes with `strcmp` or `strchr`. Changes:

- The keyboard grid is re-coded as the PS1 Latin grid, and the glyph view
  moves from `0x8340` to `0x8240` (one pool word), so key codes draw
  Ａ..Ｚ and ０..９.
- Every key and puzzle answer is stored **fullwidth** in the JSON, because a
  pair-encoded string could never match.
- Field lengths grow: the puzzle field from 4 to 10, the search field from
  10 to 13. The fields' sprite list is copied into the hole and re-centred.
- **B040's name search** has 17 section items, one per kana row. The first
  typed letter picks a section through `strchr` over the section labels.
  English initials do not follow kana rows, so the `strchr` pool word
  `0x060BA528` goes to `KEYSEL`. `KEYSEL` compares the typed buffer with every
  key in a directory read from the built bank and claims the section that
  holds the match. Without a match it falls back to `strchr` on new
  initials. Key records carry `key: true`, section headers `initials: true`.
- `satkeys.py faces` redraws the key faces (chunk 310) as an override.
- `satkeys.py check` holds the JSON, the bank, the exec and the PS1's
  `PUZZLE_TARGETS` (B060, B070, B1A0, B1D0) together.

### WALLPAPER option

The Saturn has a hidden option: the wallpaper set behind the rooms, stepped
by the Konami code on the title screen and kept in u16 `[0x060E4B54]+4`.
The patch turns it into a menu:

- **`satspecial.py`** replaces the room script's load op `0x0F` (table word
  `0x060E4E2C`) with a copy. When the word holds `0xA5 << 8 | row` with row
  0..8, any request for one of the nine wallpaper chunks is swapped for
  `PICTURES[row]`. A chunk argument with bit 15 set loads unswapped (for the
  previews). The CONTINUE loader's set term (`0x060C5EB0`) is dropped, so a
  loaded game shows the chosen picture too. An unmarked word gives Konami's
  per-act defaults.
- **`satoptmenu.py`** adds a WALLPAPERS row to the title's OPTION MENU
  (state `0x060B0BE2`, five rows) and a WALLPAPER screen with ten rows in
  two columns: ACT 1, ACT 2, ACT 3, TWINBEE, KONAMI, TOKIMEKI, ENDING,
  GRADIUS, TURBOCAR, BLACK. The highlighted picture previews behind the
  panel. BLACK loads nothing extra; a new front for op `0x1D` zeroes the
  wallpaper palette. The patch has three parts: exec stubs, new blocks
  appended to the title room script (chunk 60), and new word images in the
  option graphics (chunk 331), built from Konami's own 6x7 lettering.

## 6. Voice subtitles

### Audio on the disc

**Voice lines**: `ACT1/2/3.CAT` on track 2 are single IMA ADPCM streams (4-bit
mono, 22,050 Hz, Form 2 sectors of 2,324 bytes). The index that splits them
into lines is in the exec: the **voice table** `0x060EB5A8`, 1,040 x
`{u8 act, u8, u16 sector, u32 size, u16 offset, u8 0x0A, u8}`. Sound id
`0x700 + n` plays line n (`0x060BD3AC`). While a line plays, the live state
is:

| Address | Meaning |
|---|---|
| u16 `0x060EA2C2` | sector of the line |
| u32 `0x060EA2C4` | `offset << 16 \| act << 8 \| flags` |
| u32 `0x060EA2BC` | ADPCM bytes decoded so far (11,025 per second) |
| `ctx+0x560` | voice id, 0 once the line is over |

`saturn/translation/voice_map.json` maps each PS1 mono XA stream to its
Saturn line by envelope match. `satcat.py` lists, extracts and matches the
lines.

**Reels**: the PS1's stereo XA reels are `SDAIF_*.AIF` (plain AIFF PCM) on
track 1. The live reel number is u16 `0x060EFE6A`, u32 `0x060EFE64` = 1 once
loaded, and u32 `0x060EFF0C` = bytes of the file played. Short reels are
loaded whole into sound RAM and have no position word; their cues key on
the reel number and the load marker.

### Timing: byte windows

The Saturn cue files are generated from the PS1 ones. `gen_subs.py` converts
each PS1 cue's sector window into a fraction of its stream and multiplies
that by the Saturn line's size:

```
b0 = round((start - stream.start) / (stream.end - stream.start) * line.size)
```

The payload shows a card while `b0 <= decoded < b1`. A reel cue gets file
bytes instead: 54 (the SSND data offset) + frames x frame size, after
`reelalign.py` fits `saturn_t = a * ps1_t + b` from the two audio envelopes.
Past its window a card stays up for its reading time, counted from the frame
it went up (`satsubs.hold_frames`: 20 characters a second, 1 to 3 seconds,
one byte per cue in the blob), unless the next cue takes the box or a menu
or the engine's own text does. Without it a 0.4-second line such as B020's
"What?!" was on screen for a quarter of a second.
`bridge_cues.py` closes small gaps between consecutive cards of one line.
Banks that play a line differently from the PS1 are handled in
`gen_subs.LINE_HOME` and `CHAINS`. The cue JSON is the shipped data; hand
edits live there. Its fields are documented in
[saturn/translation/README.md](../saturn/translation/README.md).

### Card cutting

Cards are cut by `lib/cardplan.py`, shared by all ports. A card holds as many
whole sentences as fit; a long sentence breaks at a clause, then before a
phrase opener, then at a word; there are no widows; a numbered item opens a
card. `saturn/subs/sat_recut.py` applies the planner to the Saturn cue
files. A chain (consecutive cards with the same speaker on one line, whose
windows touch) is re-cut so each card fits both the band layout (14 x 3)
and the plain box (18 x 3, one more row without a speaker). Each new card
starts at the byte where its first character sat in the old cut. Single
cards and unchanged chains are left alone.

### How the engine draws, and where the payload hooks

VDP1 draws what sprite **object 0** points at (`ctx+0x830` = `0x060F2CE0`,
76-byte objects: `+12` box y 0..128, `+24` the sprite list). The dialogue box
is list `0x060E5350` (80 cell records and 8 box pieces). During a voiced
line, **the voice band** (the face at the left; `0x060F2A08 == 2`,
`ctx+0x558 == 2`) switches object 0 to list `0x060E5778`, which has 6 gold
pieces and no cells. That is why the Japanese game shows no text during
voice.

The frame wait `0x060B55A0` calls the cell renderer through the pool word
**`0x060B563C`**. The build points that word at a stub in the exec hole. The
stub finds the current bank's blob and runs the payload instead of the
renderer. The payload calls the renderer itself and then copies records, so
a card shows on the frame it is decided. The payload runs in the frame
wait's own context: during type-on, box slides and script waits.

### The blob

Each subtitled bank carries a blob at the **end of its string region**:

```
strings | longs group | pad | blob | pad | footer {'SUBF', blob offset} | tail {0xFFFF, group}
```

The stub reads the region length that satlong's load hook recorded
(`lenvar`), finds the footer, checks the magic `'SUBS'`, caches the address
in `blobptr`, and jumps to `blob + 0x20`. The payload is assembled per bank
at its own load address (`saturn/subs/sh2s.py`, a text-syntax SH-2
assembler). `work/saturn/build/subs_layout.json` records each bank's blob
address for the harness. Region plus blob must fit the 64 KB window.
`unstale` in the stub repairs object 0 when a bank change leaves it pointing
into an old blob.

Blob layout: `+0 'SUBS'`, `+4` scene number (`ctx+0x54A`), `+6` cue count,
`+8` cue table, `+12` the 42-cell band list (an 80-cell plain-in-band list
follows), `+16` current cue, `+20` the plain list, `+24` layout, `+28`
state, `+0x20` code. Each cue is 32 bytes: sector (`0xFFFF` = reel), flags
with the character in the high byte, key (`offset << 16 | act << 8` or the
reel number), `b0`, `b1`, band text, nameplate text, face buffer, and
`CMDSRCA base << 16 | palette`. Texts are interned u16 SJIS (`0x818F` row
break, `0x8101..0x8107` colour). Each card's band text is followed by the
same words re-wrapped at 20 cells, for layouts with no portrait. A
signature table for the portraits follows the cues.

### Layouts

Every frame, if the blob's scene is live and no card is waiting for a press,
the payload chooses a layout:

- **Band (face-left)**: the band is up and object 0 shows the band list or
  ours. The speaker's portrait column moves to x = 24 and the others to
  x = 400. The text goes in rows 1-3, columns 6-19 (14 x 3) beside the
  face. Object 0 points at the blob's 42-cell list.
- **Plain-in-band**: the band is up but no column carries the speaker
  (no portrait, or it never arrives). Every column is parked, the nameplate
  goes at (0, 0), and the 20-cell text goes below it.
- **Plain box**: no band and no live menu, the engine's box closed and idle
  (y = 128 on the box list), and the line already decoding. The payload
  picks the box frame (the job `0x060B6F20(10, 20)` builds, run from a word
  in the blob), writes all cells at once (nameplate on row 0 in the
  speaker's colour), points object 0 at its 88-record list, and slides the
  box in by 8 px a frame.

A state word tracks idle / opening / open / closing / lost. The payload keeps
the two cell codes it wrote at (0, 0) and (1, 0) and checks them every frame.
A mismatch means the engine took the box for its own text, and the card is
dropped without touching anything. A reel whose byte counter stops for 8
frames is over.

### Portraits by pixels

Which column shows which character is decided **from VDP1 pixels**, not the
script's speaker labels. `facechunks.py` catalogues every portrait chunk
(type-3 sections) with a 16-byte signature at offset `0x800`. The blob
carries the table, and the payload reads each shown column's slot in VDP1
VRAM (`0x25C00000 + CMDSRCA*8 + 0x800`) and compares. Each cue carries its
character (`facechunks.CHARS`: Gillian, Mika, Chief, Harry, Metal Gear,
Catherine, Randam, Teller, Madnar, Ivan, Napoleon, Chin, Jamie, Cook,
Woman).

The room script supplies the rest. Chunks `60 + N` run on a second u16
interpreter (`0x060B81B0`, table `0x060E4DF0`; `saturn/tools/satroom.py`
disassembles them). Op `0x21 col face buf slot` shows a column at
`x = 24 + 96*col`, op `0x3E`/`0x4B` sets up a hidden column, op `0x36` adds a
voice to a column's mouth list, and an event table entry `59 <voice id>
<addr>` per line points at those set-ups. `roomfaces.py` harvests them so a
cue knows the face buffer and slot of a speaker the script hides; the
payload then copies a shown column's cels over the hidden one.

Further rules:

- A card waits up to 15 frames for its speaker's column, with all columns
  parked, before falling back to plain-in-band. It upgrades to face-left if
  the column arrives later.
- A speaker with no portrait chunk restores the engine's layout after 30
  frames. Only shown columns are restored; hidden ones stay hidden.
- Face-buffer sprites (props drawn on a face slot) move with their column.
- The op `0x21` call site (pool word `0x060B6D60`) goes through a stub that
  writes x = 400 when the live voice id has a cue, so a band never draws one
  frame at the native column.

### Nameplate colours

The nameplate uses the speaker's own colour from `names.json`: blue 1, red 2,
purple 3, green 4, cyan 5, yellow 6, white 7, the byte the layout stores per
cell. Speakers that have no colour in the game's table get one from
`gen_subs.EXTRA_COLOURS`. The scheme follows the PS1's (see
[docs/ps1.md](ps1.md)).

### The opening

The opening has no bank of its own. B000 (chunk 21) is in RAM from the title
until B010 loads, so the `INTRO` blob rides in B000's region and the plain
path draws it. `gen_intro.py` takes the PS1's 24 opening cards verbatim and
times them on the two narration reels (`SDAIF_E0` = reel 140, the newsreel;
`SDAIF_E1` = reel 141, the roll and Gillian's profile). Display matches the
PS1's: no nameplate, no gold frame, no slide, up to 3 rows of 20 cells. Each
card has its own y, taken from the lowest picture row measured on the
pristine opening (`intro_run.py --measure`). Object 0's draw priority is
raised to 31 while a card is up and restored afterwards.

## 7. Graphics

All graphics tools write decoded overrides to `patched/saturn/chunks/NNN.bin`,
and `satpack` packs them. Each starts from pristine data, so it can be
re-run.

| Tool | Chunks | What |
|---|---|---|
| `satpages.py` | 369 | the red New Game disclaimer: VDP2 background, 16-px English lines, white index 6 on red |
| `satpages.py` | 268-280 | Gibson's thirteen memo pages: VDP2 backgrounds on the PS1's line grid (ink 7 on 2); two pages keep a photograph with their own palettes |
| `satpages.py` | 267 | Gibson's diary as the computer screen draws it: ten sprite lists of 8-bpp text pieces, rebuilt as one block per page, photographs kept; the pixel section keeps its size |
| `satroll.py` | 394 | the opening's credit roll and "2042.12 / NEO KOBE CITY": 23 screens of VDP1 sprite lists, one piece per line, centred on x 160 |
| `satroll.py` | 452 | the JUNKER HQ type-on caption (40x32 pieces drawn by chunk 453's lists 79-94): "KONAMI OMNI BLDG" / "JUNKER HQ", typing on in the original beats |
| `satlabels.py` | 237/238, 361-366, 489, 250/252/253/261 | videophone cards, the note among the item close-ups (Konami's mark kept), the JUNKER poster, the phone-book jokes |
| `satkeys.py faces` | 310 | Latin keyboard faces |
| `satoptmenu.py` | 60, 331 | the WALLPAPER menu's script blocks and word images |

English sources: the PS1's `gfx_pages.json` and disclaimer data,
`saturn/translation/staff_roll.json`, `saturn/translation/gfx_labels.json`.
`satlabels` edits pictures in palette indices: `erase`, `move`, `copy`,
`pixels`, `remap`, `inpaint`, `text`.

Chunk 394 keeps Konami's bytes at `[0x228, 0x8000)` as an unused palette
section, because the street scene's garbage decode (chunk 387) reads them.
The English pixels and a rebuilt index follow, and the chunk keeps its
original decoded size.

## 8. Boot screens

`satsplash.py` plays the translation card (3 s) and the Snatcher walk-in
with the disclaimer (about 10.7 s), the Saturn port of the PS1's `bootcard`
and `bootsplash`. It runs from the **IP**:

- The IP's start-up code ends with a `jsr` through the literal at
  `0x06002FD4`, which normally holds A.BIN's entry. That literal now points
  at the player.
- The IP size in the header (`+0xE0`) goes from `0x1800` to `0x8000`, so the
  BIOS loads all sixteen system sectors. Player and data sit at
  `0x06003400..0x0600A000`.
- The player masks interrupts, backs up VDP2 VRAM and CRAM to
  `0x06040000`, shows RLE-packed bitmaps on NBG0/NBG1 (the figure walks by
  scroll registers, fades by colour offset), paces on TVSTAT's VBLANK bit,
  then restores VRAM, CRAM and the register file as it found them, zeroes
  its scratch memory, and jumps to `0x06010000`.

No file moves, and `A.BIN` and `MAIN_L.BIN` are untouched. The figure comes
from the PS1's art (`CXE_B0D0`), so the Saturn build reads the PS1 disc.

## 9. Build order and outputs

`python build.py saturn [--release]` (see [BUILDING.md](../BUILDING.md)).
`saturn/build/Build-Saturn.bat` and `build_saturn.sh` run the same chain.
Preparation, once: `extract.py` (track 1's root into
`discs/extracted_saturn/`), `satdata.py script`, and `satcarry.py run` into a
scratch copy for the text references. Then:

| # | Step | Does |
|---|---|---|
| 1 | `satapply.py` | `en` into banks 21-59, pair plan, font chunk 0 + SJIS table + VDP1 extension; `MAIN_L.BIN` and `DATA.BIN` from pristine |
| 2 | `satnames.py apply` | English speaker names in the exec (first allocation in the hole) |
| 3 | `satlong.py` | longs and over-budget lines, remap group, LNGS payload, the six stubs |
| 4 | `satkeys.py apply` | Latin keyboard, field lengths, `KEYSEL`, search directory |
| 5 | `satkeys.py faces` | key faces -> override 310 |
| 6 | `satsubs.py --all` | subtitle blobs in every bank + renderer and op `0x21` stubs |
| 7 | `satwrap.py` | row accounting and paging stubs |
| 8 | `satspecial.py` | wallpaper swap in op `0x0F`, CONTINUE set term |
| 9 | `satoptmenu.py` | OPTION MENU / WALLPAPER: exec stubs, overrides 60 and 331 |
| 10 | `satpages.py apply` | disclaimer, memo pages, diary |
| 11 | `satroll.py apply` | credit roll, JUNKER HQ caption |
| 12 | `satlabels.py apply` | small labels |
| 13 | `satpack.py` | `DATA.BIN` re-laid densely, table rewritten |
| 14 | `satsplash.py apply` | `patched/saturn/IP.BIN` |
| 15 | `satdisc.py` | track 1 rebuilt (grown if needed), track 2 headers moved, cue |

The order matters. Every exec tool allocates from the ledger in turn, and
the ledger is keyed on the exec's hash, so a step run out of order starts
over. `satpack` must run after everything that writes chunks, and `satdisc`
last. Steps 2-12 assume the pristine layout that `satapply` restores.

Outputs in `patched/saturn/`: `Snatcher (Japan) (Track 1).bin`, tracks 2 and
3, the `.cue`, plus `DATA.BIN`, `MAIN_L.BIN` and `IP.BIN`.
`SATURN_IMAGE="<name>"` makes `satdisc` write a side image under another
name. `--release` runs `satrelease.py`, which makes xdelta patches for
tracks 1 and 2 (track 3 is unchanged), verifies each against the pristine
track, and zips them with the cue and README into `release/`.
`saturn/tools/devtest.py` makes a separate dev-only image (trivial fights,
fast-forward) that is never released.

## 10. Testing tools

- **`saturn/harness/satrun.py`**: `SaturnEmu`, the PS1's `lib/emurun.py`
  libretro host pointed at Beetle Saturn. It needs the JP BIOS
  (`sega_101.bin`) and must set the pad device on port 0. Pad A/C confirm
  and B cancels; the game ignores START. Beetle's system RAM is WorkRAM-L
  then WorkRAM-H, halfword byte-swapped. `satmem.py` reads it and states
  (`SatMem`, `cells`, `menu_labels`) and refreshes a restored state's chunk
  table, GFS directory cache, exec patches and blob, so a bookmark from any
  build runs the current build.
- **`satpilot.py` / `satplay.py`**: route-driven play, closed-loop on the
  engine's menu state (menu live `ctx+0x3F7`, index `ctx+0x3F8`, card
  waiting `ctx+0xB74`, scene `ctx+0x54A`), as on the PS1. `satplay` reads
  every card and menu back from the text cells through the pair table, and
  `--lint` checks data against the box geometry. Routes are in
  `saturn/harness/routes/`. `subs_run.py` and `intro_run.py` focus on
  subtitles and give face verdicts (`face-ok`, `WRONG-FACE`,
  `TEXT-OVER-FACE`, ...).
- **Saves**: `satsave.py` keeps a library of 32 KB backup-RAM images and
  converts them for the MiSTer (`.sav`, 64 KB) and RetroArch (`.bkr`).
  `mint_saves.py` makes one per bank through the game's own Save, and
  `satsave_check.py` verifies each by CONTINUE.
- **`regress_saves.py`**: boots every library save on the current image,
  plays its scene with `satplay`, and tables cards, cues, face problems and
  wedges (`--jobs`, per-run save directories). `playthrough.py` chains the
  routes from New Game.
- **`satstress.py`**: a long continuous session with no restores, resets or
  pokes. Seeded menu choices from a late Act 1 save (or New Game with
  `--whole-game`) through Acts 2 and 3. It checks VDP1 font pixels and
  glyph mappings, and stops on the first serious error. `fontwatch.py`
  compares the VDP1 font with chunk 0 during a route.
- **The full regression**: `regress_full.py` runs the static checks
  (`satverify.py` reads every letter-pair glyph back from the built image,
  `satcardlint.py` holds every cue file to the card rules and the box
  geometry, `satplay.py --lint`, the unit tests), then the scene saves, the
  whole game from New Game on the dev-test image (`satwhole.py`), a deep sweep
  of every save and the coverage routes (`routes/cov_*.json`: the phone books,
  the fortune teller, being thrown out, the reception's detour...), and judges
  everything at once. Every satplay run carries `satsubcheck.py`, which follows
  each voice line and reel as it plays and checks the subtitle cards against
  it: a cue heard but never shown, a line carded only in another scene's file,
  a card out of step with its voice, a card left up with nothing playing, a card
  the screen does not show, the font and glyph table, and the game's heap.
  `satcoverage.py --gate` fails the regression when a scene bank was never
  loaded or a cue was never read on screen without a documented reason.
- **Analysis**: `sh2dis.py` (capstone SH-2: `at`, `xref`, `const`, `func`,
  `full`), `satroom.py` (room scripts), `satgfx.py`, `satfont.py`,
  `lz3.py`, `satcat.py`. `satvision.py` and `saturn/tools/mister_play.py`
  drive the game from screenshots on real hardware.

## 11. Engine reference

Context block `ctx` = `0x060F24B0`.

| Address | What |
|---|---|
| `0x06002FD4` | IP literal: A.BIN entry (the boot-screen hook) |
| `0x06010000` | `A.BIN` boot shell; `0x060B0000` `MAIN_L.BIN` |
| `0x060E62F4` | DATA.BIN chunk table, 639 x `{u16 sector, u16 size/2}` |
| `0x060B22EC` / `0x060B22B4` | open chunk / open DATA.BIN |
| `0x060B2F8C` | `load_chunk` (decode via `0x00248000` -> `0x00258000`) |
| `0x060B2620` | streamed loader (in-place decode in high WRAM) |
| `0x060CB6FC` / `0x060CB548` | LZ3 setup / step |
| `0x060B2788` | graphics container section dispatcher |
| `0x060B915E` | scene loader; strings `0x002E8000` (`[0x060FD164]`), bytecode `0x002F8000` |
| `0x060C08B0` | string word -> region offset |
| `0x060C4D24` | negating converter (bank text -> SJIS) |
| `0x060B82A8` / `0x060B8390` | show text / show text with speaker |
| `0x060C31A0` | add list-menu item; labels `0x060FAC60` (64 B each) |
| `0x060B45C4` | layout `(col, row, sjis)`; write-cell `0x060B45B0`; scroll `0x060B4730` |
| `0x060B4970` | cell renderer -> 80 records at `0x060E5358` |
| `0x060B4E28` | type-on / end-of-card wait |
| `0x060B55A0` | frame wait; renderer pool word `0x060B563C` |
| `0x060B4BA4` | pre-text (finishes a band close) |
| `0x060B4AE0` | band close |
| `0x060B6F20` | VDP2 frame pick `(layer, picture)` |
| `0x060B4530` | font load into VDP1 |
| `0x060E6CF0` | SJIS -> glyph table (0x1734 x u16) |
| `0x060E4DA8` | `＠` colour table |
| `0x060C17F4` / `0x060C1F18` | speaker names / name pointers |
| `0x060B9A74` | typing screen; cursor `0x060F2C00`, keydata `0x060E5254`, layout `0x060E5294`, buffer `0x060EF6B4` |
| `0x060B9748` | label -> one byte per character (matcher input) |
| `0x060B81B0` | room-script interpreter, op table `0x060E4DF0` |
| `0x060E5350` / `0x060E5778` | dialogue box list / voice band list |
| `0x060F2CE0` (`ctx+0x830`) | sprite object 0 (76-byte objects; faces = objects 1-9) |
| `0x060F2A08`, `ctx+0x558` | band flag, band state |
| `0x060F28A7` | menu-live byte |
| `ctx+0x3FA` | text cells, 4 x 20 x 4 bytes |
| `ctx+0x3F7` / `ctx+0x3F8` / `0x060FD0C3` | menu live / index / count |
| `ctx+0xB74` | card waiting for a press |
| `ctx+0x54A` | scene number |
| `ctx+0x56A` | window mode (7 = terminal) |
| `ctx+0x560` | live voice id |
| `0x060EB5A8` | voice table, 1,040 x 12 B |
| `0x060BD3AC` | play voice line; decoder `0x060BD940` |
| `0x060EA2C2` / `0x060EA2C4` / `0x060EA2BC` | live line sector / key / bytes decoded |
| `0x060EFE6A` / `0x060EFE64` / `0x060EFF0C` | reel number / loaded / bytes played |
| `0x060E4B54` | wallpaper word pointer (`+4`) |
| `0x060C4DA0` / `0x060C4E38` | game allocator `xmalloc` / `xfree` |
| `0x060F5640` | vblank counter (stops on a wedge) |
| `0x060E7220..0x060E7BAE` | exec hole used for patch code (computed per build) |
