# The PlayStation port: how the game works and how the patch changes it

This is the architecture document for the PlayStation translation. It covers
how Konami's engine stores and draws text, pictures and voice, and what each
tool in `ps1/` changes. Read it if you want to maintain the patch, retarget
it to another language, or carry the method to another game.

Related documents:

- [BUILDING.md](../BUILDING.md): building the images and patches from your own dumps.
- [ps1/README.md](../ps1/README.md): the data files
  a translator edits (bank strings, cue files, picture texts) and their fields.
- [docs/review-tool.md](review-tool.md): the local web page used to review the
  script against the Japanese and the voices.

Addresses are KSEG0 RAM addresses (`0x80xxxxxx`) unless marked "file", and
exec file offsets follow `file = RAM - 0x80028000 + 0x800`.
`ps1/tools/disasm.py at <addr> [n]` and `disasm.py xref <addr>` disassemble
the executable; `DISASM_FILE=<overlay> DISASM_BASE=0x800B4000` does the same
for an overlay.

---

## 1. Overview

**Snatcher** for PlayStation (Konami, SLPS-00154) is a Japan-only adventure
game: a menu-driven script engine running 39 scene banks of bytecode and
text, a dialogue box with nameplates and portrait faces, XA-streamed voice
acting, and a handful of baked pictures with Japanese in them.

The patch changes:

| Area | What changes | Main tools |
|---|---|---|
| Script | every bank's strings in English, at full length | `apply_translation.py`, `repoint.py` |
| Font | unused kanji glyphs redrawn as two-letter pairs | `pairfont.py`, `rebuild_pairs.py` |
| Engine | word wrap, nameplate on continuation pages | `wordwrap.py`, `pageplate.py` |
| Input | Latin keyboard (emits and key faces), fullwidth puzzle answers | `patch_keyboard.py`, `kbdfaces.py`, `lock_data_strings.py` |
| Name search | Gaudi's database keyed on English names | `keytable.py` |
| Options | the hidden SPECIAL MENU reachable without the Konami code | `specialmenu.py`, `specialitem.py` |
| Voice | English subtitles for the voiced scenes and the opening | `ps1/subs/subs_cue.py` + `ps1/translation/subs_*.json` |
| Pictures | memo pages, disclaimer, credit roll, captions, labels, intro movie | `gfxpages.py`, `disclaimer.py`, `staffroll.py`, `introcaption.py`, `introdiagram.py`, `gfxlabels.py`, `fmvtext.py` |
| Boot | a translation card and an animated disclaimer before the game | `bootcard.py`, `bootsplash.py` |
| Disc | grown files appended past the image end, sectors rebuilt | `patch_disc.py` |

**Two release variants** come out of one build:

- The plain patch is the **translation only**: every picture as Konami shipped it.
- `(Uncensored)` also runs `uncensor.py`, which undoes the PlayStation-only
  censorship. The two images differ in two pictures and one file-table record,
  and nothing else. `check_variant.py` proves each image carries the art its
  name promises.

---

## 2. The disc and its files

The image is a single MODE2/2352 track. User data sits at byte 24 of each
2352-byte sector (Mode 2 Form 1). `ps1/tools/extract_ps1.py` walks the
ISO9660 tree into `discs/extracted_ps1/`. `work/lba_map.json` maps each file to
its `(LBA, size)`.

| Path | Contents |
|---|---|
| `SLPS_001.54` | Main executable, loaded at `0x80028000`, LBA 24. Font at file `0x4CB80` |
| `PLN/ISZ/ISZ_B000..B260.BIN` | The 39 scene banks: bytecode, then the string region |
| `PLN/NSZ/NSZ_B000.BIN` | Speaker name table: 59 length-prefixed records |
| `PRG/SXM/SXX_*.BIN` | Overlays at `0x800B4000`: `B000` title, `B020` opening, `B030` game |
| `PRG/FXM/F*_B*.BIN` | 58 per-scene code modules |
| `DES/*/C*.BIN` | ~500 compressed graphics containers |
| `SND/XAS/XAS_M000.XA` | 1,040 mono XA streams: the voice lines (LBA 2408) |
| `SND/XAS/XAS_S000.XA` | 199 stereo reels: music, cinematic reels, the opening (LBA 64888) |
| `STR/*.STR` | MDEC movies. `MX0_S000` boot logo, `MX2_S000` intro movie, `MX1_*` mid-game |

### How files are found

The game does not read the ISO9660 directory after boot. It locates files
through tables in the executable:

- **The general file table**: 12-byte `{lba, size, pad}` records starting at
  file `0x4B4E4` (RAM `0x80072CE4`), grouped into classes. A tool finds a
  file's record with `pristine.find(struct.pack("<II", lba, size))`. Graphics,
  overlays and the name table load through it.
- **The scene table**: 39 records `{LBA, size, pad}` at `0x80071E8C`, indexed by
  the bank number divided by `0x10` (`ISZ_B1A0` is index `0x1A`). The loader
  reads class 1 through `{ram_src, LBA, size}` at `0x80071E88`.

Every bank loads at `0x8010D000`. `ISZ_B050` is the exception: it stays
resident at `0x80118000`. The bank's first halfword (big-endian) is the
offset of its string region.

The engine reads exactly as many bytes as a record says. A file that grows
past its record is cut short on load, so every tool that grows a file updates
its record. `gfxpages.resize`, `repoint.relocate`, `introdiagram.relocate`,
`subs_cue`, `uncensor` and `apply_translation` (for the name table) all do this.

### Relocation past the image end

A file that outgrows its sectors cannot stay where it is, because the next
file follows it directly. Such files are appended after the original last
sector (the pristine image has 243,921 sectors) and listed in
`work/relocations.json` as `{name: lba}`. The record in the exec's table then
takes the new LBA and size. Nothing reads the PVD, so the longer image
needs no volume-size change.

Files that relocate on a normal build:

- `ISZ_B040` (name-search keys, `keytable.py`), plus any bank that outgrows
  its slot (`repoint.py`)
- `CXD_B0B0` (the diagram still, `introdiagram.py`)
- every `SUBS_<S>.BIN` and `LONGS_<S>.BIN` (`subs_cue.py`)
- `SLPS_001.54` itself (`bootcard.py`). `patch_disc.repoint_exec` rewrites the
  executable's ISO9660 directory record, which is what the BIOS reads at boot.
- in the uncensored variant, `CXF_B080`

`keytable.py apply` starts the table afresh on every build. `repoint.relocate`
only understands bank keys, so it runs before the tools that add other entries.

### Writing the image (`patch_disc.py`)

- It copies the pristine image to `patched/<name>.bin` only when that file is
  absent. `build.py` deletes it first, so every build starts from pristine.
- It runs `verify_build.check()` first and refuses to write an image that fails.
- It writes every `patched/*.BIN` and the exec at its LBA, from
  `lba_map.json` or `relocations.json`. It refuses a file that outgrows its
  sectors without a relocation entry.
- Appended sectors are built fresh: sync, BCD MSF header, Form 1 subheader,
  data, then EDC (over bytes 16..2071, at +2072) and ECC P/Q (+2076/+2248,
  header zeroed as Mode 2 requires). Any sector in range whose sync is
  missing is rebuilt the same way, so the image has no header-less gaps.
- After the last appended file it pads **150 empty sectors** (`POSTGAP`), as
  the pristine image does. The drive reads ahead, and a file on the image's
  final sector makes some hardware read past the end.
- It refuses to write an image that an emulator holds open.

Beetle PSX reads sectors that other emulators and hardware reject. An image
that boots under Beetle is not proven valid. Check the appended sectors'
headers, or play it on DuckStation or hardware.

---

## 3. Text

### Encoding

Bank text is **not Shift-JIS**. Each character is a 2-byte big-endian font
index that runs in descending order relative to JIS X 0208. `lib/textcodec.py`
implements the codec:

```
pair = (ku + 1) // 2 ; high = 0x80 - pair
pos  = (0 if ku odd else 94) + (ten - 1)
low  = 0xC0 - pos ; if low <= 0x80: low -= 1     # 0x80 is reserved
```

`decode_stream()` shows bytes it cannot map as `<xx>`. The engine converts
this encoding to Shift-JIS before it reaches the rasterizer. Text injected at
runtime (subtitles) is therefore written as SJIS bytes (`ps1/tools/sjis_enc.py`).

### Control codes inside strings

| Code | Meaning |
|---|---|
| `￥` | line break (SJIS `0x818F` after conversion) |
| `＠` + colour kanji | colour from here on: `白` white, `赤` red, `青` blue, `水` cyan, `緑` green, `黄` yellow, `桃` pink, `紫` purple. Four bytes |
| `＠Ｃ` at the end | the box closes by itself after a delay (combat and timed lines). Keep it |
| `<xx>` bytes | engine control bytes. Keep them where they are |

The Japanese colours a name red when it is introduced
(`＠赤『ランナー』＠白`), and the English keeps those codes.
`check_strings.py` lints line breaks and colour codes against the Japanese.

### Storage and the byte budget

Strings are null-terminated in the bank's string region. Bytecode refers to
them by start offset (a BE16 word index from `sbase + 4`), so a replacement
written in place must fit the original's bytes. `fit_report.py` lists strings
over budget.

English is encoded by `pairfont.encode` (section 4). The encoder flushes at
every fullwidth character, so each ASCII run between `￥` or colour codes
rounds up to an even length on its own:

```
cost = sum(each ASCII run rounded up to even) + 2 per fullwidth code + 1 (null)
```

### Long strings (`repoint.py`)

Any string may carry a `"long"` field beside `"en"`. The `en` text is written
in place and stays within budget. The `long` text has no length limit and
replaces `en` at runtime. Most of the script ships as longs.

The bytecode is never edited. References take several forms: dialogue words,
menu items whose top bits are flags (mask `0x3FFF`), and counted lists. A
bytecode scan cannot find them all safely. Instead the patch exploits a
choke point: every string display computes `[0x800AB5A4] + offset` at one of
three sites:

| Site | Function |
|---|---|
| `0x80043790` | dialogue resolver |
| `0x8003DF5C` | display-string variant A (also the no-name text op) |
| `0x8003E000` | display-string variant B |

Each site's `jal` to its measure/copy helper is retargeted to one shared stub
at `0x8009E330`. The stub:

1. reads the bytecode base `[0x800ABFF0]`. If it is not a `0x80xxxxxx` pointer
   (no bank loaded), it does nothing;
2. takes the bank base (bytecode base − 4) and reads the bank's **header
   halfword** as its key. `ISZ_B040` runs with two string bases, so the string
   base alone cannot identify the bank;
3. converts the request to a **bank-absolute** offset;
4. finds the bank's remap group through the directory at `0x8009F628`. Each
   entry is `[key u16][pad][group pointer u32]`, ended by `0xFFFF`;
5. scans the group's entries, `[count u16][pad]` then
   `[old u16][pad][new u32]` each, where `new` is an absolute RAM pointer. On a
   hit it substitutes the pointer, then tail-calls the original helper.

The groups and the long texts do not live in the bank. `repoint.py` writes
each bank's group and texts to `work/longs/<S>.bin`, and `subs_cue.py on <S>`
ships that as `LONGS_<S>.BIN`. After the subtitle blob is read, the loader
hook chains a second CD read that loads it to `LONGS = 0x801E1000`
(`lib/hiram.py`, up to 44 KB, ending below `0x801EC000`). That range was chosen
by a write census of the running game (`scripted.py RAMTOUCH=N`,
`ps1/harness/ramfree.py`), which found no other writer there. The per-bank
`{lba | sectors<<20}` words of the LONGS files sit in font slots 2076-2086 and
the read code in slots 3004-3012. `ISZ_B050` (resident) and any bank without
a cue file keep their longs and group in the bank's own tail.

A long must not need a letter pair that has no glyph slot. Its glyph would
never reach the exec, so `repoint.py` refuses such a long, and
`rebuild_pairs.py` is run after any text change. `repoint.py` exits non-zero
when anything does not fit.

### Locked data strings

Some strings are data the engine compares against input, not text:

- the videophone dial table (`数` followed by fullwidth digits, with `★`/`☆`
  wildcards for prefixes),
- the `ハズレ` catch-all records and the `数☆` wildcards.

The player dials one glyph code per digit, and a pair-encoded string could
never match. These entries carry `"lock": true` (`lock_data_strings.py`).
`apply_translation.py` refuses to write them, and `verify_build.py` fails if
English appears there. The `数` lock applies only when a digit, `☆` or `★`
follows it.

Typed-puzzle answers are matcher targets too, but they are translated. They
must be **fullwidth** Latin (`ＱＵＥＥＮ`, `ＢＥＮＳＯＮ`...), because the
keyboard emits one glyph code per key. `lock_data_strings.PUZZLE_TARGETS`
prescribes all 63 of them, and over-budget ones ride a `long`. The `以外`
suffix on two catch-all records ("other than ...") is matcher syntax and
stays.

### The speaker name table

`NSZ_B000.BIN` holds 59 records of the form `[len u8][encoded name]`, walked
in order. The script's `mode` for a named line is the name's **index + 1**,
and that mode also selects the nameplate colour (section 7). The English
names (`translate_names.NAMES`) are written at natural length: the file is
alone in its sector with room to spare. `apply_translation.py` encodes the
table from the same pair table as the banks and updates its file-table size.
The `ガウディ黄` plate (Gaudi) is `Gaudi  (Y)`, with two spaces so its
letters stay on pairs that have slots.

---

## 4. The font and the pair glyphs

The exec carries a **12×12 1-bpp font**: 18 bytes per glyph at file `0x4CB80`
(RAM `0x80074380`). For JIS level 1 (ku 16-47) the kanji slot is
`(ku-1)*94 + (ten-1) - 845`. Level-2 rows do not follow that layout and are
never read back. **Glyph data ends at slot 3529** (file `0x5C3B4`). Slots
3530-3572 are an engine pointer table, and writing there hangs the game on
several emulators and on hardware.

### Two letters per glyph

English would cost one 12-pixel cell per letter. Instead the patch packs
**two halfwidth letters into one glyph** in a kanji slot the translated game
no longer draws, so two letters cost one 2-byte code, the density of the
Japanese.

- `ps1/tools/pairfont.py` holds the `PairFont`: encode, decode, and
  `render_pair` (two 6-px letters drawn into one 12×12 cell).
- `work/pair_table.json` (committed) maps each pair to `[slot, code]`.
- `rebuild_pairs.py` builds the slot pool from every level-1 slot the built
  game no longer needs: kanji left in untranslated or locked strings, colour
  codes, and the name table stay reserved. That gives about 2,900 slots for
  about 1,600 pairs in use, so every pair the text needs has a slot. Pairs are
  ranked by weighted frequency (bank text 4, longs 2, subtitles 1), with
  speaker names given priority (`translate_names.NAME_WEIGHT`).
- The assignment is **incremental**: a pair keeps its slot across rebuilds,
  and new pairs take free slots. Savestates carry rendered text, so a
  reshuffle would garble them. `--fresh` ranks everything from scratch.
  `recover_pair_table.py` reads a table back out of a built image's glyphs.
- A pair with no slot falls back to two fullwidth letters, one cell each, and
  2 bytes more. Some pairs (` Z`, ` K`, ` 5`) are rare enough to stay
  fallback. `pairfont` reports them (`fb`).

The glyph face is X11 misc-fixed **6x13** (public domain), with its blank top
row trimmed (`lib/bdffont.py`, `DIALOGUE`, `TRIM_TOP`). That leaves 12 rows,
letters standing on row 9 like the original MS Gothic, and 9-px capitals. The
same face draws the memo pages, the disclaimer, the intro-movie captions, the
first caption line and, set proportionally, the credit roll.

### Verification

`rebuild_pairs.py` invalidates every encoded file, so the build re-encodes
everything from one `PairFont`:

- `apply_translation.py` rebuilds the exec from pristine and writes, from
  that one table, the bank text, the name table and every pair glyph.
- `verify_build.check()` re-encodes every string and compares it with the
  bytes in `patched/`. It also decodes the name table, reads every pair glyph
  back from the exec against `render_pair`, and checks locks and puzzle
  targets. `patch_disc.py` will not build an image that fails it.

### Code in dead glyph slots

The executable has almost no free file-backed space. The only dead region is
`0x8009E228..0x8009E2A8`, plus two zero regions repoint uses (`0x8009E330`
stub, `0x8009F628` directory). Exec-side stubs therefore live in **glyph slots
the game never draws**, listed in `pairfont.RESERVED`, which `rebuild_pairs`
never hands out:

```
1012-1026  1107-1117  1260-1264  1287-1294  1308-1314  1329-1335  1337-1340
1357-1362  1550-1554  1564-1570  2076-2086  3004-3012
```

A slot's address is `0x80074380 + 18 * slot`; compute it, do not read it off
a dump. `subs_cue.install_engine` asserts every stub lies inside `RESERVED`.

---

## 5. Word wrap, the dialogue box and list menus

### The rasterizer

`render_text(sjis, x, line, colour, width, dest)` at `0x800367D8` fills a row
cell by cell. It cuts the row at `width` (the fifth argument: **18** cells in
the dialogue box, **14** in window mode 7, Gaudi's terminal) or at a `￥`.
The cut is hard: a word one cell over the edge splits.

### The wrap hook (`wordwrap.py`)

The `move s3, a0` at `0x800367E0` becomes the delay slot of a jump into a stub
at **`RESIDENT = 0x801FE000`** (4 KB below the stack page). The stub copies
the string into its own buffer and inserts `￥` at the latest legal break of
any row that would overflow, then resumes at `0x800367E8` with `s3` on the copy.

- A break is legal after a cell whose right half is blank (`d `) or before
  one whose left half is blank (` r`). The stub reads the glyph itself through
  the engine's SJIS range table (`0x80074AA8`, 46 `{sjis_start, slot_base}`
  entries; glyphs at `0x80074B60 + 18 * slot`), so pairs, fullwidth spaces
  and punctuation need no table. The engine's range test is
  `addiu 0x7EC0; andi 0xFFFF; sltiu 0x1734`.
- Colour codes count as zero cells. A row with no legal break keeps the hard
  cut. Strings over 1 KB, or widths of 64 or more, pass through untouched.
- Calls from the list-menu renderer (return address `0x8004D9B8`) are left
  alone. That buffer is four rows laid back to back.

Nothing file-backed can hold the stub: the exec's tail is BSS that the entry
code clears. `bootcard.py` therefore appends `wordwrap.resident()` to the exec,
and its boot stub copies it to `RESIDENT` before the game starts. The hook is
unconditional, so any RAM image without the resident runs into zeros.
`ps1/harness/wrap_sim.py <scene> <off> <width>` runs the stub in an R3000
interpreter against the real font, beside `wordwrap.wrap_rows`, the Python
model the lints use.

`￥` in the data is the translator's hard break, and the runtime wrap is a
safety net. Terminal text (`＠緑` strings in B030/B040) is pre-broken at 14
(`rewrap.py --scene B030 --scene B040 --width 14 --prefix ＠緑 --write`). The
terminal shows 4 rows per page. `wordwrap.py lint 18` lists dialogue rows
over 18 cells.

### Continuation pages (`pageplate.py`)

The box shows three rows. When a line has more, the WAIT step (`0x80047C30`)
hides the nameplate and goes straight back to type-on, so the next page has
no speaker name. The Japanese never pages, so the original game never shows
this. `pageplate.py` changes one halfword (the `addiu a1, a1, 0x79D8` at
`0x80047D6C` becomes `0x7978`) so paging goes through the nameplate step
`0x80047978`. That step shows the plate whenever the line has a name.

### List menus

The list renderer (`0x8004D90C`) fills one buffer of four 18-cell rows laid
back to back. Item `i` goes to row `i % 4`, at cell 0 for `i < 4` and cell 10
for `i >= 4`. `render_text` then cuts at 18 with no newline between rows. So:

- a right-column label longer than **8 cells** runs into the next row;
- a left-column label longer than **10 cells** runs under its neighbour.

Every menu label is 8 cells or fewer. A cell is one pair (two letters) or one
fullwidth character. `ps1/harness/menuread.geometry()` judges every live list
during a harness run, and `regress.py` fails on an overflow.

---

## 6. Names, menus, keyboard and puzzles

### Gaudi's name search (`keytable.py`)

`ISZ_B040` holds a key table: sections selected by the first typed character,
each section a list of `[key word][09][len][action]` records. An action
either shows a dossier (`03 E0 xx xx`) or shows a correction line. The table's
byte layout is engine ABI, and `keytable.build` changes only the BE16 word
references. `keytable.ENGLISH` holds 160 English keys.

A consumer of the key words keeps only 13 bits, so key strings must sit at
word offset `0x1FFF` or lower. Dialogue that sat there is evicted to the bank
tail. A new string must never be packed at an evicted string's old offset,
because the remap keys on offsets. The search field takes 11 letters.
`ps1/harness/gaudi_search.py NAME...` types searches headless and captures
the results.

### The keyboard

- **Emits**: a Shift-JIS table in the exec at file `0x49DB8`, null-separated
  groups (mostly five cells) followed by the dakuten conversion rows.
  `patch_keyboard.py` replaces the kana cells with fullwidth Latin and keeps
  the function keys in place.
- **Faces**: pixels in `CPS_B0A0.BIN` (`kbdfaces.py`). Section 0 items 0+1 are
  the resting 4×15 keyboard. Section 1 item 0 holds the pressed-key sprites, a
  grid of 16×16 cells. Faces and emits share `patch_keyboard.ROWS`, so they
  cannot drift apart.
- **Length**: a clamp stub at `0x8009E204` raises the input-length nibble to
  at least 8 so English answers fit.
- **Field layout**: the reposition pass `0x8004E864` keys the field's base x on
  that nibble. Three stubs from `repoint.py` (KEYPOS/KEYCELL/KEYWIDTH, font
  slots 1550-1554 and 1564-1570) re-centre a clamped field. They narrow the
  pitch to 14 px with 12-px cells, keep the Japanese centre, and are live only
  while the maximum length exceeds the nibble. The 11-letter name search is
  never clamped and stays untouched.

Shootouts need SELECT to draw the Blaster. That is the original game's
control scheme, not a patch issue.

### The SPECIAL MENU (`specialmenu.py`, `specialitem.py`)

The game hides options (wallpaper, cursor colour, target pointer) behind the
Konami code on the OPTION MENU. The pad handler `0x8002B4E8` keeps a listener
in the pad block: `ctx+0x111` armed, `+0x112` unlocked, `+0x113` position,
`+0x114` timeout. It walks the halfword sequence at `0x80070930` (file
`0x49130`) and unlocks when it reaches `0xFFFF`. `specialmenu.py` writes
`0xFFFF` over the first entry, so START alone unlocks.

`specialitem.py` adds a fifth item, SPECIAL OPTIONS. The option menu is
data. Its labels are words on a 128×72 8-bpp sheet (`CPT_B090` section 1
item 0, eight-pixel letters). A draw list in the blitter format (section 8)
places them inside a fixed 208×96 panel at (24, 64). The tool:

- adds a sheet row composed from existing letters;
- re-cuts list 0 to five rows at a 12-px pitch, shifting every section-relative
  offset;
- patches the title overlay `SXX_B000`: the last cursor index
  (`0x800CE0B4[2]`), the highlight-bar table (`0x800CE11C`), the `ori 3` → 4
  in open and cancel, and the confirm switch, which now sends cursor 3 into
  the START handler body at `0x800C17BC`.

`B000` strings 4-238 are Konami's debug scene-select labels. They are not
visible to the player and are left short.

---

## 7. Voice subtitles

The voiced scenes put no text on screen. The engine plays an XA stream and
animates a face. Subtitles are therefore created: timed to the audio, carried
in a per-bank blob, and drawn through the game's own dialogue box.

### Identifying voice lines

- `XAS_M000.XA` holds 1,040 mono streams (75 sectors/s) and `XAS_S000.XA` 199
  stereo reels (150 sectors/s). Some mono channels run at about 150. Use each
  stream's measured rate, never a constant. A few lines are VAG samples with
  no CD stream at all.
- A stream's identity is `chan<<8 | file` **plus its absolute sector range**.
  The same (file, channel) pair recurs across the disc.
  `ps1/subs/xa_census.py` turns a jPSXdec index into `work/master_lines.json`
  (`{xa, ch, file, start, end, dur, stereo, rate, stride, key}`).
- The Japanese comes off the audio: `lib/asr/transcribe_xa.py` (faster-whisper,
  Japanese, with the vocabulary prompt `lib/asr/asr_prompt.txt`). A sector is
  `start + t * (end - start) / wav_duration`, per stream.
- A stream belongs to the bank that is **live** when it plays. The harness
  logs every `stream file= chan=` the game switches to. A bank with no cue
  file logs nothing, so every bank has one, even when empty.

### Pieces of the runtime

```
ps1/translation/subs_<S>.json         cue data (INTRO = the opening)
        | ps1/subs/subs_cue.py on <json> --scene <S>
        v
patched/SUBS_<S>.BIN                  'SUB\0' | code | cue table | SJIS strings
patched/LONGS_<S>.BIN                 the bank's long strings + remap group
        |  both relocated past the image end
        v
exec (shared by every bank)
  0x80078AA8  HOOK_CODE   loader hook on the scene loader's callback (0x8005128C):
                          after the bank, read SUBS into HIRAM, then LONGS
  0x80079158  HOOK_TAB    40 x (lba | sectors<<20): 39 banks + INTRO (slot 39)
  0x8009E228  trampoline  in the per-frame service chain (0x8002AAE0):
                          if the magic reads 'SUBS', call the payload (ctx in $v0)
  0x8009E284  filter stub on both CdlSetfilter sites -> high-RAM dispatcher
  font slots  behaviour stubs (table below)
        v
HIRAM 0x801F0000 (48 KB cap)          the payload, run every frame
SCRATCH 0x801FC000, DISPATCH 0x801FC800   its state and dispatcher
```

The blob carries `'SUB\0'` on disc. The read-completion callback turns it
into `'SUBS'`, so a half-read blob never runs. `subs_cue.py on` rewrites the
**shared** exec (hooks, stubs, table), so every bank must be built with the
same revision. The build always runs it for all 40.

**Cue table.** 12 bytes per cue: `u32 start LBA`, `u16 span` (bit 15 =
last line of a conversation), `u16 ident` (`chan<<8 | file`), `u16 speaker`
and `u16 text` (offsets into the blob). Strings are SJIS, padded at runtime
to `rows × cols`. The per-cue speaker carries its nameplate mode.

### Matching a cue

Every frame the payload reads the polled `CdlGetlocL` that the XA driver
keeps at `ctx+0x58C` (`{amin, asec, aframe}` BCD, mode, file, chan...). A
cue matches when:

> the polled sector lies inside the cue's range **and** the last captured
> `CdlSetfilter` names the cue's file and channel.

Position alone is not enough. Streams are interleaved, and the drive reads
ahead while a menu is up. The filter is re-issued on every stream switch
through the driver site `0x8002C3A8` and the queue pump `0x8002C4A4`, and both
are hooked. The driver's Setloc (`0x8002C3C0`) is never hooked. The scan
takes the first matching cue in file order. A polled sector unchanged for 45
frames (`PARK_FRAMES`) means no stream. **Chain cues** (`chan` 254) fire a
set number of frames after an anchor cue draws, which covers VAG lines.

### Drawing through the engine's own box

The payload renders nothing. It queues the engine's **type-0 dialogue object**
`{name_ptr, mode, sjis_text_ptr}` with `0x800364E0(type, &args)`, ctx in `$v0`.
The engine then opens the box, shows the nameplate, types the text and closes
the box as it does for its own lines. The payload tracks whose text is up
(`PHASE`: 1 queued, 2 reached WAIT, 0 not ours) and clears a card by setting
window-word bit 31, the engine's own timed close, only while it is ours.

Rules the payload follows:

- Queue only when the dialogue task's step is idle, type-on or WAIT.
- Zero the six row sprites (`0x80033A18`) before every queue. The type-on
  grows them and only the close resets them.
- If bit 28 (box open) is cleared under a card in WAIT (a layout switch or a
  band close), end the task itself and refill the text canvas (`0x80036704`).
- Into a box opened over the live verb menu, queue a single card.
- If a live list cursor (`ctx+0x1D7C` byte `0xF8`) meets an open box with the
  frame hidden, a state the original game never reaches, show frame and fill
  again.
- Never wrap an engine call in a stub that pushes a frame; tail-call with `j`.
  Never touch `sp`; park `ra` in scratch. R3000 load-delay slots are real, so
  no register is used in the instruction after its load.

Behaviour stubs, each gated on a scratch magic so stale RAM cannot fire them:

| Stub | Address | Changes |
|---|---|---|
| `BAND_STUB` | `0x80079E00` | type-0 entry's menu-window test (`0x800477B8`) reads "no window" while `KEEP`, so the face band stays open beside the card |
| `VOICE_STUB` | `0x80079E30` | the voice-prepare box test (`0x80048854`) reads "no box" while our card holds the box or it is closing |
| `BAND2_STUB` | `0x8007A2EC` | the band-open box test (`0x800491D4`), same rule |
| `CLOSE_GATE` | `0x8007A328` | type-0 handler's final `jal` (`0x8004774C`): finishes a close that new text would cut short (slides the remaining `8*(15-k)`, clears bit 28) |
| `MENU_STUB` | `0x80079F78` | a list menu opening over our card (`0x8004DB10`) parks frame and fill and takes the box |
| `PRESS_STUB` | `0x8007A184` | pad presses in WAIT are ignored while our card is up (`0x80047CB4`) |
| `FACE_STUB` | on `0x80049A3C`, `0x80049B6C` | the face loader's `x = 24 + 72*col` sites take the payload's x |
| `PREINIT_GATE` | `0x80079C18` | the opening: restores ctx before `GAME_INIT` |
| `INTRO_HOOK` | `0x8007A0F4` | the opening: loads `SUBS_INTRO` from the overlay loader callback |

**Nameplate colour.** The type-0 handler draws the name in
`0x800711BC[mode & 0x3F]` (0 white, 1 red, 2 blue, 3 cyan, 4 green,
5 yellow, 6 pink, 7 purple), and a named line's mode is the speaker's
name-table index + 1. `subs_cue.speaker_mode` gives each cue the mode of its
speaker. Speakers missing from the name table take a colour from
`EXTRA_COLOURS`. Mode 7 is the terminal window and never used.

### The face-left layout

Every subtitled bank uses the `faceleft` option. The speaking character's
portrait goes at the left of the box, and the text sits to its right in 12
cells, with no nameplate when the face says who is talking.

- **Faces** are nine cel objects at `ctx+0x4934`, three per column (base, eyes,
  mouth). The engine places a column at `(24 + 72*col, 156)`. Each column's
  slot id (`ctx+0x1AF8+col`) indexes the room's face list (`[ctx+0x1814]`),
  which names a `CXN_*` container. Each container covers one character per
  hundred (`B0` Gillian, `B1` Mika, `B2` Chief, `B3` Harry, `B4` Metal Gear,
  `B5` Catherine, `B6` Randam, `B7` Jamie, `B8` Madnar, `BB` Chin, `BC` Teller).
  `subs_cue.SPEAKER_CHAR` maps cue speakers to those.
- Each frame while the band is open and no verb menu is live, the payload
  finds the column carrying the cue's speaker, moves its three cels to x=24
  and the others to x=400, sets the rows' template x to 92 and parks the
  nameplate. The renderer `0x80035DBC` rebuilds prims from the cels' integer
  positions every frame, so all three cels must be written.
- The column is chosen from the room's face list, never from the script's
  naming. The script sometimes animates a listener.
- If the speaker's face is loaded but not yet shown, the card waits up to
  15 frames (`QHOLD_MAX`), then draws plain. A plain card uses the cue's
  second, 18-cell wrap, which the blob stores beside the 12-cell one
  (`FF FF` when the two are equal).
- The text ends with the face. The band's close step hides rows and
  nameplate on its first frame, and a card whose face is taken away mid-line
  is hidden the same way.
- The minimum hold. A card hidden that way before it has been up its reading
  time (20 characters a second, 1 to 3 seconds; one byte per cue after the
  cue table) comes back plain, with the nameplate and the 18-cell wrap, while
  its voice still plays: the payload forgets the card once the box has closed,
  or 4 frames after the band has gone if the box stays up, and the matcher
  queues it again. A clear or the next card cancels the request
  (`SHOWNT`, `HOLDREQ`; `NO_HOLD=1` builds without it).
- A speaker with no `SPEAKER_CHAR` entry gets the nameplate and the full width.

### The opening

The opening (`subs_INTRO.json`) plays before any bank is loaded, on two
stereo reels. The blob builds the dialogue sprites under its own task with a
copy of the sprite step `0x800459E8`, with the asset load blanked. It
snapshots the ctx ranges that step writes (`SNAP_RANGES`), and `PREINIT_GATE`
restores them before `GAME_INIT`.

- Rows draw on a band under the picture: frame and cursor hidden, the fill
  dropped 12 px and set to subtractive blend at a quarter
  (`0x80032E54(fill, 1, 2)`, grey vertex colours). The fill goes in OT bucket 1
  and the rows in bucket 0, above the scrolling boards. The rows' home is
  y 173/189/205.
- Each cue carries a `y` (one signed byte per cue after the cue table). When
  the shown card changes, the payload slides the rows and the fill by the
  difference (`0x80033848`), so a card clears the picture behind it.
  `ps1/subs/gen_intro.py place` computes `y` from a per-frame measurement of
  the pristine opening's lowest picture row.
- The Snatcher diagram still is not drawn through the OT, so nothing can
  appear over it. Its narration is baked into the picture (`introdiagram.py`).
  The card that straddles it is split, and the second half is `noband`: it is
  adopted without a retype.

### Cue data and cards

Cue files are described field by field in
[ps1/README.md](../ps1/README.md). In short, a cue is
`{id, file, chan, start, end, dur, speaker, en, enabled, last?, cols?,
anchor?, by_ear?, y?, noband?}`, with `options` holding `rows`, `cols`,
`menu_word` (the scene's verb-menu window word; `mode` is derived from it),
`away_clear`, `faceleft`, `fullwidth` and `intro`. The JSON is the shipped
truth; nothing regenerates it.

Box width is counted in **cells**, not characters: `subs_cue.cellw()` counts a
pair as one cell and a fallback pair as two.

Where a line breaks into cards is decided by `lib/cardplan.py`, shared by all
three ports. Rows fill greedily. A card holds whole sentences, and a sentence
that does not fit what is left opens the next card. A sentence longer than a
card breaks at a clause end, then before a phrase opener, then word by word.
No card ends with a lone widowed word, and a numbered item opens its card.
`ps1/subs/consolidate.py --write` re-cuts same-speaker chains with it; run
`rebuild_pairs.py` afterwards. Subtitles carry the complete dialogue: a card
that does not fit is split into more cards, never condensed.

Tools: `check_cues.py` (offline lint: fit, overlap, anchors, sector sanity,
reading speed, blob budget), `split_long.py`, `merge_cues.py`, `add_cues.py`,
`mark_last.py`, `jp_sidecar.py` (Japanese beside English for review),
`pan_audit.py` (a reel cue's speaker by stereo position), `new_scene.py`
and `subgen.py` (first cut of a bank from ASR segments).

---

## 8. Graphics

### Containers

`DES/*/C*.BIN` containers start with `01 00 00 00` and a bit-level **LZSS**
stream (`lib/lzss.py`; decompressor `0x8003B924`):

- flags MSB-first; flag 1 = literal byte, flag 0 = match: 12-bit **absolute**
  ring position, then 4 bits of length − 2;
- a 4 KB ring at `0x800A0D48`. The write index starts at 1, and position 0
  ends the stream. The ring is not cleared between files, so a match may
  only reference bytes written by the current stream.

`lzss.compress` is greedy, round-trips byte-exactly, and stays within the
original size for shipped files. Dithered art compresses badly, so redrawn
pictures stay flat.

Decompressed layout (`ps1/tools/gfx.py dump|render`): `u32 A, u32 B`, then two
sections of A and B bytes. Each section begins with an offset to a descriptor.
The item table offset and count sit at `+0x0C/+0x14` in section 0 and
`+0x14/+0x24` in section 1. An item is a packed size word (width in VRAM
halfwords, height in rows) followed by pixels, 4 or 8 bpp. The depth is not
stored; it follows from how the game uploads the item. The first record of a
section often carries a 256-colour RGB555 palette. `render` writes PNGs in
palette colours; edits work on indices in the decompressed bytes.

### The data-driven blitter

34 containers carry a glyph atlas plus draw lists in this format:

```
u32 count << 24
count * { u16 y, u16 x, u8 h, u8 w, u16 src }     src = (v/8)*16 + (u/8), 8x8 blocks
... then a u32 per list pointing at its records (section-relative)
```

The game reaches a list through that pointer table, so a rewrite updates the
pointers and keeps the total length.

### Redrawn pictures

| Picture | Container(s) | Tool / data | Notes |
|---|---|---|---|
| Memo pages | `CPC_*` (13 pages) | `gfxpages.py`, `gfx_pages.json` | two items side by side, 192×128, 12-px line pitch |
| New Game disclaimer | `CXD_B000` | `disclaimer.py` | blitter: atlas + one list |
| Credit roll | `CXD_BX30` | `staffroll.py`, `staff_roll.json` | blitter, 22 screens, 128×512 4-bpp atlas; 6x13 set proportionally; atlas and record table are full |
| Key faces | `CPS_B0A0` | `kbdfaces.py` | section 6 |
| Option menu item | `CPT_B090` | `specialitem.py` | section 6 |
| Opening caption | `CXH_B000` items 4/5 | `introcaption.py` | below |
| Diagram still | `CXD_B0B0` items 3-6 | `introdiagram.py` | narration baked in, relocated |
| Small labels | `CMC_B000/B010` (videophone cards), `CXC_*` (Gibson's note), `CXH_BX30` (poster), `CMC_B0D0/B0F0/B100` (phone-book jokes) | `gfxlabels.py`, `gfx_labels.json` | edits in palette indices |
| Intro movie | `STR/MX2_S000.STR` | `fmvtext.py`, `fmv_credits.json` | below |

**Opening caption.** "KONAMI OMNI BLDG / JUNKER HQ" is not a picture of its
own. It is sixteen 16×16 sprite cells cut from the Neo Kobe sign sheets. Each
cell draws all 16 columns 1:1 at an irregular 11-13 px pitch, so neighbours
overlap. `introcaption.py` draws each line at screen resolution and gives
every column to the nearest-centred cell. Line 1 uses 6x13, line 2 Tamzen
8x16 bold with Konami's shadow. `cal` and `fit` modes measure the geometry.

**Diagram still.** `CXD_B0B0` section 1 items 3-6 (2×2 tiles of 128×128,
8 bpp) are shown straight from VRAM, outside the OT. The narration card's
rows are painted into them at the subtitle rows' position, on the band's
rectangle baked dark. The recompressed file is relocated.

**Small labels.** `gfxlabels.py` applies an ordered list of edits per picture,
all in palette indices: `erase`, `move`, `copy`, `pixels` (hand-set letters in
the picture's own lettering), `stamp` (another entry's result), `remap`,
`inpaint`. The `CMC_*` pictures carry no palette. On Gibson's note only the
text is replaced: the `！` mark is part of the drawing and a puzzle clue.

**Intro movie.** `MX2_S000.STR` has the credits burned into the picture.
Within a credit the text is static while the city moves, so `fmvtext.py`
takes a run median (background blurred plus text), a plate from frames
outside the run (background only), and a mask where the two differ. It
repairs the masked pixels from the plate and draws the English into the same
bands in the sampled colour. jPSXdec re-encodes the frames
(`-replaceframes`), each capped to its original size. This edits the
**image**, so it runs after `patch_disc.py`. `fmvtext.py mirror` copies the
finished extent from one variant's image to the other. The first build also
runs `frames` and `build`, which need OpenCV and SciPy.

**Left as is**: background signage, handwriting, the BENSON chart (a puzzle),
the opening newspaper (vertical columns at an angle), the boot logo movie
`MX0_S000.STR`. The `MX1_*` mid-game movies have voice but no burned-in text,
and carry no subtitles.

### Uncensoring (`uncensor.py`, uncensored variant only)

The PlayStation release censors three pictures. Two of the originals still sit
on the disc, unused:

- **Factory ruins (B020)**: `CXK_B062` (greyed and dithered) is replaced by
  `CXK_B061`, the original. Both files share one palette and item layout,
  and the framing is unchanged.
- **The maggot skull (B200)**: file-table record 321 (exec file `0x4C3F0`) is
  pointed at `CXQ_B0A0` instead of the mosaiced `CXQ_B0D0`. No data is written.
- **The female Snatcher (B120)**: `CXF_B080` is a repaint with no original on
  the PS1 disc. `--lisa-saturn` takes the Saturn release's uncensored picture
  (`DATA.BIN` chunk 433, 240×128, rendered by the Saturn tree's `satgfx.py`),
  squeezes it to 192 columns by nearest neighbour (the PS1 art is that
  squeeze), writes its own colours as the palette, and relocates the larger
  file. This is why the uncensored build needs the Saturn disc.

The scene with Catherine in the shower is deliberately not restored, because
she is fourteen in the Japanese script. `--pack NAME PNG` puts any flat picture
into a single-picture container.

The censored build removes `patched/CXK_B062.BIN` and `patched/CXF_B080.BIN`.
The exec needs no undo, because `apply_translation.py` rebuilds it from
pristine.

---

## 9. Boot screens

Two screens run before the game's own entry point, on bare metal: no BIOS
calls and no interrupts, with the GPU driven by CPU stores to GP0/GP1.

**`bootcard.py`** grows the exec by a small stub, a 1-bpp bitmap of the
translation card, and the resident payloads, then points the PS-EXE header's
entry at the stub. The stub:

1. copies the resident payloads (the word-wrap stub) to `0x801FE000`. The tail
   lands in BSS, which the game's entry code clears, so they must be moved
   first;
2. resets the GPU, sets 320×240, and uploads the card with one `GP0 A0`
   transfer, expanding two pixels per word;
3. holds about 3 s by counting h-blanks on timer 1 in free-running mode;
4. jumps to the `bootsplash.py` player.

The grown exec no longer fits its 242 sectors, so it is relocated and its
ISO9660 record rewritten. Its header's `t_size` is raised to cover the tail.

**`bootsplash.py`** is a data-driven sprite player. An endoskeleton cut from
`CXE_B0D0` walks in on white, its eyes light up, and the disclaimer lines
appear, followed by a fade and a jump to the original entry `0x80029A28`. The
data: an 8-bpp parts page at VRAM (640,0) with two CLUTs (the second dims the
eyes), a 4-bpp text page at (768,0), a 12-byte sprite table
(`E1 word, clut|v|u, h|w`), and a repeat-compressed timeline of
`id<<24 | y<<16 | x` entries (id `0xFF` = subtractive fade rectangle). The
player double-buffers at (0,0)/(0,256) and waits 263 h-blanks per frame on
timer 1, carrying the overshoot. Sync-to-vblank counting does not hold on all
hardware. `bootsplash.py preview` renders a GIF from the same data. The
headless harness skips these screens with a fixed frame offset (`BOOT_SHIFT`).

---

## 10. Build order

`python build.py ps1 [--variant both|censored|uncensored] [--no-fmv] [--release]`
(see [BUILDING.md](../BUILDING.md)). `ps1/build/Build-Image.bat` and
`build_all.sh` run the same chain. On a first build `build.py` extracts the
disc and dumps the Japanese reference text (`dump_strings.py` → `work/ref/`).
Per variant, starting from a deleted image:

| # | Step | Why it is here |
|---|---|---|
| 0 | `check_strings.py --all` | lint only (line breaks, colour codes); never stops the build |
| 1 | `apply_translation.py` | rebuilds the exec **from pristine**, writes bank text, name table and pair glyphs. Everything after it patches this exec |
| 2 | `keytable.py apply` | B040 keys and evictions; **resets** `relocations.json` |
| 3 | `repoint.py` | longs, remap groups, directory and stub, keyboard-field stubs; relocates overflowing banks (bank keys only, so before other relocations); writes `work/longs/` for step 14 |
| 4 | `patch_keyboard.py` | key emits |
| 5 | `kbdfaces.py apply` | key faces |
| 6 | `specialmenu.py apply` | Konami-code table |
| 7 | `specialitem.py apply` | option-menu sheet and list, title overlay |
| 8 | `gfxpages.py apply` | memo pages |
| 9 | `gfxlabels.py apply` | small labels |
| 10 | `disclaimer.py apply` | New Game disclaimer |
| 11 | `staffroll.py apply` | credit roll |
| 12 | `introcaption.py apply` | opening caption |
| 13 | `introdiagram.py apply` | diagram still, relocated |
| 14 | `subs_cue.py on subs_<S>.json --scene <S>` for INTRO and B000-B260 | blobs, LONGS files, shared exec hooks; all banks against one engine revision |
| 15 | `uncensor.py --lisa-saturn` (uncensored) / remove its two outputs (censored) | file-table record and pictures |
| 16 | `wordwrap.py apply` | hook in `render_text`; its resident is carried by step 18 |
| 17 | `pageplate.py apply` | one halfword |
| 18 | `bootcard.py apply` | last exec change: appends stub, card, resident and splash, relocates the exec |
| 19 | `patch_disc.py` | `verify_build`, then sectors, EDC/ECC, post-gap, ISO record |
| 20 | `fmvtext.py apply` (first variant) / `fmvtext.py mirror` (second) | edits the image, so it comes after `patch_disc` |

With `--release`, `check_variant.py` checks both images, `lib/stamp_notes.py`
stamps the result hashes into `RELEASE_NOTES.md`, and `ps1release.py` writes
the two xdelta patches (pristine → each image), their cues, `README.txt`, the
apply scripts and the zip. Each patch is verified by applying it. The patch
is around 21 MB, most of it the re-encoded intro movie.

Outputs: `patched/Snatcher (Japan).bin/.cue` (uncensored, the dev image),
`patched/Snatcher (Japan) [censored].bin/.cue`, every changed file as
`patched/*.BIN`, and `release/` for the release files.
`SNATCHER_IMAGE=<name>` makes `patch_disc.py` and `fmvtext.py` write a
differently named image.

---

## 11. Testing tools

- **`lib/emurun.py`** hosts the Beetle PSX libretro core through ctypes: about
  300 fps headless, PNG frames, savestates, memory cards and core options
  (a second memory card by default; `RETRO_OPTIONS=<.opt>` replays a player's
  configuration).
- **`ps1/harness/scripted.py`** plays a scene from a route
  (`ps1/harness/routes/<scene>.json`: `path`, `sweep`, `type`, `dial`,
  `fight`, `idle`, `press`, `save`, `mcard`...). It steers by reading the
  engine's menu cursor (`ctx+0x1D7C`, `menustate.py`), never screenshots. It
  logs every cue draw and stream switch, takes settled captures scored by
  `subs_validate.py` and `panel_check.py` (box position), and bookmarks every
  bank it reaches (`work/states/<bank>_auto`). `HOLD_AFTER_CUE` sets the
  pilot's patience, and both patient and impatient runs must agree.
- **`subs_validate.py`** renders a card's expected rows with the game's own
  glyphs and finds them together inside the box (rows 16 px apart at one x).
  The font is drawn 1:1, so a correct card matches exactly: any missing ink
  or stray ink in the rows' band (a wrong pair glyph, a stale row tail, an
  overflowing row) fails it. Captures at +24/+40/+60/+120/+200 frames; a
  card gone before +24 is `NOSETTLE`, a box left empty by the band's close
  is `HIDDEN`.
- **The sync gate** (`scripted.py`): every frame the voice stream moves, the
  harness applies the payload's own match (polled position in a cue's
  sectors, Setfilter on its file and channel). A line heard for half a
  second with no card is `UNSHOWN`; a card 1.5 s behind its line is `LATE`;
  our card held in WAIT with nothing playing and no menu for 30 s is
  `FROZEN`; a stopped game frame counter is `HANG`.
- **`raminject.py`** brings a savestate up to the current build: bank, blobs,
  exec code and tables, the resident, B050, the font. It never touches
  globals. Savestates also carry the CD controller's buffered sectors, so
  after the disc layout changes, bookmarks are re-minted from fresh runs.
- **The speaker check**: for each card the harness compares the character whose
  mouth the engine animates (menu word bits 20-22 → column → face list →
  `CXN`) with the cue's speaker (`DATA?`), and the face the payload placed at
  x=24 (`FACE!`). Cues marked `by_ear` were attributed by listening and are
  exempt.
- **`regress.py`** runs the regression set in parallel (New Game through B010
  at two patience settings, B020, B0C0, B250 into B260, the B010 Harry
  scene, the B200 basement into B210/B220, the opening, `verify_build`, an
  offline `lint` of the cue files and strings, and the whole game as `wgNN`
  stretches between the checkpoints of `wholegame.py`'s chain, on the
  dev-test image so the pilot never loses a fight) and prints one verdict
  table. It exits non-zero on a speaker mismatch, a text FAIL, a sync flag,
  a bank under its cue minimum, a panel or list-geometry problem, a lint
  error or an unfinished run, and after a full set on a coverage drop:
  every bank must load and every enabled cue must draw, except what
  `ps1/harness/coverage_exempt.json` lists with its reason. It reads the
  image, so nothing may build while it runs.
- **Other tools**: `coverage.py` (cues never drawn, streams with no cue);
  `wholegame.py` (every route from New Game, with in-game saves as
  checkpoints; `lib/mister_play.py` replays it on a MiSTer); `mcard.py` and
  `mint_cards.py` (a memory card per bank: test a build from a card save,
  since an emulator savestate keeps the previous build's code in RAM); probes
  `--trace`, `BOXDUMP`, `ROWDUMP`, `SLIDELOG`, `NAMETRACE`, `SPKTRACE`,
  `CELTRACE`, `RAMTOUCH` on `scripted.py`; `ps1/subs/subs_watch.lua` under
  PCSX-Redux.

Beetle is lenient about sector headers and strict about load delays and the
font pointer table. A fix confirmed on Beetle alone is not confirmed. Play it
on DuckStation or hardware too.

---

## 12. Engine reference

### Context and tasks

| Address | Meaning |
|---|---|
| `[0x800ABF64]` | game context `ctx` (`0x80010000` once the game proper runs; early boot uses another struct) |
| `ctx+0x18` | frame counter |
| `ctx+0x17F0` | root task list. Task: `+0` next, `+4` first child, `+8` parent, `+0xC` state nibble, `+0x10` step fn, `+0x18` ticks (low 20 bits) |
| `0x80032568(task, fn)` | init a task (only if its nibble is 0) |
| `0x80032288(obj, parent, 1)` | link under a parent |
| `0x80032654(task, fn)` | set step, reset ticks |
| `ctx+0x1954` | object queue (`+0` next, `+4` type, `+8..` args), walked by `0x800363D4` through the 11-entry table `0x80071044` |
| `0x800364E0(type, &args)` | queue an object (ctx in `$v0`). Types: 0 dialogue text `{name, mode, sjis}`, 2 voice (`{0, line}` prepare, `{1,0,0}` play), 3 layout, 6 timer, 7 layout switch, 8 list menu, 9 scene load |
| `[ctx+0x1808]` | module vtable directory (`0x80070FF4`). Scene modules `PRG/FXM` call the exec only through it, so `xref` cannot see their calls |

### Strings and text

| Address | Meaning |
|---|---|
| `0x800AB5A4` | current string base |
| `0x800ABFF0` | bytecode base (bank + 4) |
| `0x80043B20` / `0x8003EDE4` / `0x80043790` | bytecode dispatcher / offset fetch / dialogue resolver |
| `0x8003DF5C`, `0x8003E000` | display-string variants (with the resolver, the three remap sites) |
| `0x8009E330`, `0x8009F628` | remap stub, remap directory (patch) |
| `0x800367D8` | `render_text(sjis, x, line, colour, width, dest)` |
| `0x80036704` | text canvas / CLUT init |
| `0x800711BC` | 64-entry mode → colour table |
| `0x800AE670` | live menu labels, 64-byte entries |
| `0x80074380` / `0x80074AA8` / `0x80074B60` | font slot 0 / SJIS range table / range-table glyph base |

### Sprites and the OT

| Item | Meaning |
|---|---|
| sprite object | `+0x1C` prim, `+0x3C` flags (bit 24 visible, bits 13-16 OT bucket, bits 4-8 type) |
| `0x80032D9C(obj, vis)` | show/hide |
| `0x80033560(obj, x, y, mask)` / `0x80033848(obj, dx, dy, mask)` | position / slide |
| `0x80033A18(obj, w, h, 1)` / `0x80033BC8(obj, dw, dh)` | absolute / relative size (GPU masks widths to 10 bits) |
| `0x80032E54(obj, on, abr)` | semi-transparency |
| OT | 16 buckets drawn 15 → 0: scene art 14-6, UI 5-2. Never splice prims in from outside |

### The dialogue box

| Address | Meaning |
|---|---|
| `ctx+0x1EC0` / `ctx+0x1ED0` | dialogue task / its step |
| `0x80047548` | type-0 handler: renders rows (widths `ctx+0x1AD0`), writes the window word |
| `ctx+0x1ACC` | **window word**: bits 9-14 mode, 17-19 rows, 20-22 row, 23-27 column, bit 28 box open, 29 skip slides, 31 timed close |
| `0x80047788` → `0x800478D0` → `0x80047978` → `0x800479D8` → `0x80047C30` → `0x80047DC4` → `0x80047E90` | entry → slide-in (15 × −8) → nameplate → type-on → WAIT (pad `0x80047CB4`) → slide-out (15 × +8; hides frame/fill on the last tick) → done (`ctx+0x1AC0` bit 1) |
| `ctx+0x27B0` / `ctx+0x27F0` | frame / fill, created at y 272/276 by `0x800459E8`; moved only by paired 120-px slides |
| `ctx+0x2570` (+0x40 each) | six row sprites; nameplate `ctx+0x2530`, cursor `ctx+0x470C` |
| `ctx+0x1AF4` | menu word: bit 26 = menu window (the face band) open, bits 20-22 = column whose mouth animates (6 stopped, 7 none) |
| `ctx+0x2048`, `0x80049144`, `0x800491D4`, `0x800495F0`, `0x8004A0A0` | band task, open step, open's box test, close step, close |
| `0x80048854` | voice-prepare box test |
| `0x8004D90C`, `0x8004DA74`, `0x8004DB10` | list menu: renderer, show, slide |
| `ctx+0x1D7C` | menu cursor: byte 0 `0xF8` live (`0xF9` save list), byte 1 `count<<4 \| index<<1 \| live` |
| `ctx+0x1D9E`, `+0x1D88`, `+0x1D9B`, `+0x1D9D` | keyboard cell (15 wide), text, length, max; START submits |

### Faces

| Address | Meaning |
|---|---|
| `ctx+0x4934` | nine cels, 0x5C each: `+0x58` flags (bit 9 visible, bit 8 prims built, bits 26-27 column), `+0x4C/+0x50` 16.16 x/y |
| `0x80049904(col, face_id, ...)` | script op: load face to `0x80135000 + id*0x4800`, upload, place at `(24 + 72*col, 156)` |
| `0x80035DBC` | cel renderer (rebuilds prims every frame) |
| `[ctx+0x1814]`, `ctx+0x1828`, `ctx+0x1AF8+col` | room face list, its count, column slot ids |

### Boot, loaders, CD

| Address | Meaning |
|---|---|
| `0x80029A28` | original exec entry |
| `0x800458D4` | `GAME_INIT(0)`: 13 inits (main task `0x80045978`, dialogue task `0x80047500`, ...) |
| `0x80051250` → `0x8002C57C(index, dest, class, cb)` | `load_scene` → class-N file read |
| `0x8002BF04` | enqueue a CD command `{0xFE, lba, dest, size, cb}` on `ctx+0x57C`; worker `0x8002C52C` calls `cb(ctx, 0)` |
| `0x8005128C` | scene loader's callback pointer (subtitle hook) |
| `0x8002A444` / `0x8002A484` | opening loader callback / `jal GAME_INIT` |
| `ctx+0x1DB8` | scene index (negative during boot) |
| `ctx+0x20F0` | opening script task |
| `0x8005E918` | `CdControl` (issuer `0x8005E7F8`) |
| `0x8002C164`, `0x8002AAAC` | XA state machine, per-frame service chain |
| `ctx+0x58C` | polled `CdlGetlocL`: `{amin, asec, aframe (BCD), mode, file, chan, ...}` |
| `0x8002C3A8`, `0x8002C4A4` | `CdlSetfilter` sites (hooked); Setloc `0x8002C3C0` (never hooked) |
| `0x8002B4E8`, `0x80070930` | pad handler, Konami-code table |

### Memory the patch uses

| Range | Use |
|---|---|
| `0x8009E228..0x8009E2A8` | trampoline and filter stub (the only dead file-backed region) |
| `0x8009E204` | keyboard length clamp |
| `0x8009E330`, `0x8009F628` | remap stub and directory (zero regions) |
| font slots in `pairfont.RESERVED` | loader hook, tables, behaviour stubs, keyboard-field stubs, LONGS read |
| `0x8010D000` / `0x80118000` | bank / resident B050 |
| `0x801E1000..0x801EC000` | `LONGS` |
| `0x801F0000` (48 KB) | `HIRAM`: subtitle payload |
| `0x801FC000` / `0x801FC800` | `SCRATCH` / `DISPATCH` |
| `0x801FD000..` | debug rings (`SLIDELOG`, `NAMETRACE`) |
| `0x801FE000` (4 KB) | `RESIDENT`: word-wrap stub |
| `0x801FF000..` | stack page |

The exec's `InitHeap` hands the C library everything up to `0x80200000`, so
no high RAM is free by contract. Each region above was established by
measuring what the running game writes, and new uses need the same proof.
The asset heap starts at `0x801A6800` and some scenes write past `0x801D9000`.
