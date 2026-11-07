# pce/translation - English data for the PC Engine CD port

`pce/translation/` holds the English for *Snatcher CD-ROMantic* (PC Engine Super CD-ROM2).
Nothing there is code and nothing there is Japanese text: the Japanese is read from
your own disc image at build time (`python build.py pce` joins the tracks in
`discs/iso_pcecd_jp/` into `work/pce/snatcher_pce.bin`; `pce/tools/pcescript.py dump`
decodes every module's script into `work/pce/script/<rec>.json`). Where a file
needs to point at a Japanese string it uses either a hash of it (`dialogue*.json`)
or the bare Japanese word as a lookup key (`words.json`); those keys are never
shown to the player.

Conventions used across the files:

- **rec** - a record number in the disc's file table (stage 2, track 2). A
  record number is track-relative: the file's first sector is track 2's first
  sector + rec. The scene *modules* (bytecode + text of one scene) are
  records 158-670 in steps of 16; `pce/tools/pce_saves.py` (`MODULES`) names them,
  e.g. 158/270/286/302 save handlers, 174/190 videophone, 206 the quiz, 222/254
  Gaudi, 238 Act 2 recap, 318 JUNKER HQ (Act 1), 382 Gibson's house, 478 HQ
  (Act 2), 670 the ending. Other numbers (750, 758, 858, 958) are picture blocks.
- **Cells.** Text is drawn in 12x12 cells. English uses a 6x12 halfwidth font
  and packs **two characters into one cell** (pair glyphs, `pcepair.py`); so
  widths are counted in cells, roughly letters / 2. The dialogue box is 18 cells
  x 3 rows (36 letters a row; the wrapper breaks at 17 cells, `pcescript.WRAP`).
  A menu label is at most 8 cells.
- **In-text tags** (dialogue files only; the codec in `pcetext.py`):
  `<nl>` row break (game code 82F2), `<wait>` 82F4, `<end>` 82F6 - at the end
  of a page it makes the box wait for a button and continue on a clean page
  (`pce_hand.py`: "`<end>` a page break, `<wait>` a pause"), `<cmdN>` an
  in-text switch 82F8+N that costs no cell. Observed colour switches: `<cmd1>`
  white (normal text), `<cmd2>` yellow, `<cmd3>` red, `<cmd5>` light blue,
  `<cmd6>` green (`pce_reuse.CMD`). `<cmd4>` occurs twice in
  `dialogue_hand.json`; its effect is not pinned down in the code.
- Subtitle and cue files use no tags: `en` is plain English, and `cards` mark
  rows with `|` (see below).

All files are UTF-8 JSON. Several tools rewrite them in place (`indent=1`);
keep the format when editing by hand.

---

## dialogue.json

**Purpose.** The English for every line of in-game dialogue and narration in
the scene modules (the text box, Metal Gear's lines, Gaudi's terminal...).
**Build:** `pcescript.py apply` (via `pcescript.load_english()`), which re-encodes
each module's text block and rewrites every reference. **Written by:**
`pce/tools/pce_reuse.py` (seeds it from the PS1 translation; `--refresh <commit>`
carries later PS1 edits into entries nobody edited on the PCE side).

**Structure.** One flat object, `{key: English}`, ~6,500 entries.

| Part | Type | Meaning |
|---|---|---|
| key | 12 hex chars | `hashlib.sha1(jp.encode("utf-8")).hexdigest()[:12]` (`pcescript.key`) - the first 12 hex digits (48 bits) of the SHA-1 of the Japanese line's UTF-8 bytes |
| value | string | The English, with `<nl>`/`<wait>`/`<end>`/`<cmdN>` tags |

`jp` is the line exactly as `pcetext.decode()` returns it from the module: Shift-JIS
decoded to Unicode, the in-text commands written as the tags above, including
any trailing fullwidth space; it is the `jp` field of `work/pce/script/<rec>.json`.
One key serves every module that carries the same Japanese line. A line whose key
is in neither dialogue file stays Japanese (`pcescript.py lint` lists them).

`<nl>` is a hard row break the seeder places: `pce_reuse.py` takes the PS1
English (its full-length `long` wording where there is one), maps the PS1 colour
codes (`＠白/黄/赤/水/緑`) to `<cmd1/2/3/5/6>` and re-wraps at 17 cells. A row of
exactly 18 cells wraps by itself, so a `<nl>` after it would leave an empty row.
The box shows three rows a page.

Example (module 318, the reception):

```json
"6e4ef2dd6716": "This is JUNKER HQ. How can I help<nl>you?"
```
`6e4ef2dd6716` = sha1("ＪＵＮＫＥＲ本部です。<nl>何のご用でしょうか？　")[:12].

## dialogue_hand.json

Same format and same key as `dialogue.json`, for lines the PS1 has no counterpart
for (the PCE save system, the shooting range, the staff quiz, Jamie's calls,
PCE-only wording). ~1,380 entries. `load_english()` loads `dialogue.json` first
and this file on top, so **an entry here wins** over a seeded one; seed refreshes
never touch it. **Written by:** hand, folded in by `pce/tools/pce_hand.py` from
`work/pce/todo.json` (stub from `pce_reuse.py --todo`: key, uses, jp, en), which
wraps each `en` to 17 cells and keeps the tags; `pce/tools/pce_stitch.py` fills
todo entries from runs of PS1 lines (Gaudi's articles).

```json
"bec421440a56": "And you waste a lot of shots...<end>Cut the waste and take proper aim,<nl>all right?"
```

## words.json

**Purpose.** Menu items: verbs, Ask topics, room/object labels, list entries,
and the strings the game compares typed input against. These live in each
module's 0xFF-separated word list. **Build:** `pcescript.word_block()` during
`pcescript.py apply`; `pce/harness/pcemenu.py` also reads it to match route
labels. **Written by:** `pce/tools/pce_words.py` (generator: PS1 labels + its
`HAND` and `KEYS` tables), then hand-maintained; refresh with
`pce_words.py --refresh <commit> --write`, never a plain rebuild (it would undo
hand edits).

| Key form | Meaning |
|---|---|
| `"あたり見る"` (bare Japanese) | The label as stored on the disc. Applies in every module whose word list holds that exact record. |
| `"254:ミカ"` (`module:Japanese`) | Applies only in module `<rec>`; wins over the bare key there. Used where the record is data the game matches (typed answers, name-search keys). |

Lookup is `words.get(f"{rec}:{jp}", words.get(jp))`. The Japanese key must match
the record byte for byte as decoded from the disc (cp932), including the
disc's own spellings (`オワツタ` with a full-size ツ, `ギブスン`). Keys are lookup
keys only. A record with no entry keeps its Japanese bytes.

Rules for values:
- **Labels** are English, at most **8 cells** (the highlight box cuts the rest;
  `pceverify.py` fails on a wider one). Any length is otherwise allowed: the
  bytecode names an item by offset and `pcescript` remaps every `f1 lo hi`.
- **Typed answers** (qualified keys in 174/190 Napoleon's videophone, 254 Gaudi's
  name search, 558 BENSON, 574 OLEEN/QUEEN) are **fullwidth Latin**
  (`ＲＥＩＧＮ`): the keyboard enters one fullwidth letter per key. Misspelling
  variants are listed on purpose (`558:ベソン` -> `ＢＮＳＯＮ`).
- Catch-all matchers keep their `以外` suffix (`"558:ベンソン以外": "ＢＥＮＳＯＮ以外"`).
  ★/☆ wildcards, digit-only records and the kana keyboard rows get no entry.

```json
"あたり見る": "Look around",
"174:テンカ": "ＲＥＩＧＮ"
```

## names.json

**Purpose.** The speaker names (nameplates) of the original 73-entry list in
stage 2 (`$6D47`). Each module gets its own English copy (`pcescript.name_block`,
pointer at module 0x7FFE). **Build:** `pcescript.py apply`. **Written by:** hand.

| Part | Type | Meaning |
|---|---|---|
| key | decimal string `"0"`..`"72"` | 0-based index into the stage-2 list (`pcescript.speaker_names`); the game's speaker number is this + 1 (0 = no name) |
| value | string | English name, drawn as pair glyphs; the entry keeps its original attribute byte |

Indices not listed keep their original bytes (Japanese, or an empty slot).

```json
"5": "Metal Gear", "66": "Ans. Machine"
```

## subs_&lt;rec&gt;.json (29 files)

**Purpose.** Subtitles for the voiced (ADPCM) lines of module `<rec>`. These lines
show no text in the original. **Build:** `pcesubs.table()` (called from
`pcescript.py apply`) turns the file into the module's subtitle table (or,
for 478, a table in the voice bank); `pcesubs.py apply` installs the hook and
stub. **Written by:** `pce/tools/pcematch.py <rec> --write` (draft, matching
each PCE line's whisper transcript against the PS1 voice streams), then by hand;
`pce/tools/pce_sync.py` carries PS1 changes; `pcesubs.py cards` fills `cards`;
`pce/harness/layout_from_oracle.py --write` sets `layout`.
`pcesubs.py check` lints cards, `pcesubs.py show <rec>` prints the pages.

Top level: `{key: cue, ..., "_unmatched": {...}}`. Keys starting with `_` are
ignored by the build.

| Key | Meaning |
|---|---|
| `"1a"` | Two lowercase hex digits = **NN**, the voice record number the module plays with `1c f3 NN GG` (1-based record in the act's ADPCM table; the stub detects it from the record pointer `$5E/$5F` = `$8000 + (NN-1)*8`). |
| `"c8.5"` | `NN.G` - the same NN played from more than one act table in this module (the ending's c8-d8 in acts 4 and 5; `ad.2`, `86.3`). G = the act-table index, the opcode's GG byte (0-5 = voice tables rec 86, 90, 94, 98, 102, 106). The entry stores the record's start sector to tell them apart. |
| `_unmatched` | Written by `pcematch.py`: `{NN: "score stream"}` for lines with no PS1 match above the threshold, e.g. `"0.05 XAS_M000.XA[722]"` (best bigram-Dice score, best PS1 stream). Informational. |

Cue fields:

| Field | Type | Meaning |
|---|---|---|
| `speaker` | string | Who speaks. Must be in `pcesubs.CHARS` (the build stops otherwise); its position there is the character code faces.json is matched against. In the plain layout the name is drawn inline in the speaker's colour. |
| `en` | string | The full English line. `￥` counts as a space. An empty `en` (670 `8e`) gives an entry with no text; its runtime effect is not documented in the code. |
| `cards` | list of strings | The pages as drawn: one string per card, rows separated by `|`. Taken as written: the words must be exactly `en`'s, in order, and every row must fit (else the build stops). Missing = planned automatically (`lib/cardplan.py`). |
| `turns` | list of numbers | Seconds from the clip's start at which cards 2, 3... come up, measured from the Japanese voice (`pce/tools/pceturns.py`). The build paces the line to them (hold markers keep each page up until its turn). Absent = the line is paced evenly over the clip. |
| `turns_by` | `"hand"` | The `turns` were read off the Japanese word timings by hand (where pceturns' share matching lands mid-word, 494 `29`): `pceturns.py turns --write` leaves them, and `sync_audit.py` holds the pacing to them. |
| `layout` | `"face"` / `"plain"` | Absent = `"face"`. **face**: the speaker's portrait moves to the left of the window and the text runs beside it, **1-4 rows of 10 cells** a card (12 cells, 2 rows in 670, which runs without the resident file); if no known face comes up the stub falls back to plain. **plain**: never beside a face; the game's own dialogue row, **1-2 rows of 18 cells** a card, the first row also holding the speaker's name. Set from recordings of the original game (`layout_from_oracle.py`). |
| `display` | `"graphic"` | The line is skipped by the build: the English memo picture shown during it already carries the text (Gibson's diary in 382). |
| `ps1` | list of strings | PS1 cue ids the English came from (`B010_000` = cue `B010_000` in `ps1/translation/subs_B010.json`). Used by `pce_sync.py`; ignored by the build. |
| `score` | number | Draft-only match score from `pcematch.py`; dropped after review; ignored by the build. |

Timing comes from the disc, not from the file: a line's length is its ADPCM
record's sector count x 14.8 frames, shared among its cells, and pages turn as
the voice plays.

```json
"1f": {
  "speaker": "Mika",
  "en": "All right, Gillian. I'll open the door to HQ. I'll show you around inside.",
  "ps1": ["B010_004", "B010_004b"],
  "cards": ["All right, Gillian.|I'll open the door|to HQ. I'll show|you around inside."],
  "layout": "face"
}
```
Voice record 0x1F in module 318; one card of four rows beside Mika's portrait.

## cdda_&lt;rec&gt;.json (238, 318, 350, 462, 510, 590, 622, 638, 670)

**Purpose.** Subtitles for dialogue mixed into CD audio tracks (the Act 2 recap,
the bike ride, the basement, the Chief's death, the epilogue...) that play while
module `<rec>` is loaded. **Build:** `pcesubs.table()` writes them as a cue
block (pointer at module 0x7FF3; 670's goes to the voice bank); the stub runs a
frame clock from the moment the game confirms the track's play. **Written by:**
`pce/tools/pcecdda.py draft <track> <rec> --write` (the PS1 reel's cards warped
onto the PCE track), `pcecdalign.py apply` (start, end, seams from
hand-checked `work/pce/cdsync/out_<rec>.json`), `pcecdreveal.py write`
(`reveal_end`), `pcesubs.py merge --write` (folds consecutive cues), `pcesubs.py
cards`, `pce_sync.py`, and hand edits.

Structure: a JSON **list** of cues, any order (the build sorts by track, start).

| Field | Type | Meaning |
|---|---|---|
| `track` | int | CD-DA track number on the disc (decimal here; stored as BCD) |
| `start` | float, s | When the card comes up, seconds from the track's start (converted at 59.826 frames/s; must stay under 65,535 frames) |
| `end` | float, s | When it goes; must be > `start` |
| `reveal_end` | float, s | When the last word is spoken. Words appear one by one from `start` to `reveal_end`, then the card holds to `end`. Absent = `end`. |
| `speaker` | string | As in subs files (must be in `pcesubs.CHARS`; `""` = no name) |
| `en` | string | The English |
| `cards` | list | As in subs files (`|` = row) |
| `layout` | `"face"`/`"plain"` | As in subs files; forced plain in 670 (the epilogue has no faces) |
| `ps1` | string | The PS1 card id this cue came from (one id, not a list) |
| `ps1_more` | list | PS1 card ids of cues merged into this one |
| `seams` | list of `[word index, seconds]` | For a merged cue: where each folded cue began - the index of its first word in `en` and its original start. Used by `pcesubs.check` / `cue_drift` to flag words drifting from the voice; not used by the stub. |
| `note` | string | Free-text remark; ignored |

There is no `merged` field: a merge leaves `seams` and `ps1_more` behind.

```json
{"track": 5, "start": 5.2, "end": 11.88, "speaker": "Chief",
 "en": "Let's go over your report again. Metal Gear, if you would.",
 "ps1": "B080_2_00", "ps1_more": ["B080_2_00b"],
 "cards": ["Let's go over your|report again. Metal|Gear, if you would."],
 "layout": "face", "reveal_end": 11.48}
```

## cdda_opening.json

**Purpose.** The opening narration: the newsreel (track 17) and Gillian's profile
(the end of track 19). **Build:** `pce/tools/pceopening.py apply`, which puts its
own stub and page table into the opening's two picture blocks (rec 858 for
track 17, rec 758 for track 19). **Written by:** hand (the PS1's `INTRO` cards,
timed on the PCE tracks' whisper word stamps); no generator in the tree.

A list of cues with `track`, `start`, `end` (seconds), `speaker` (always `""`,
unused), `en`, `ps1` (an id in `ps1/translation/subs_INTRO.json`), `cards`.
**`cards` is ignored here**: `pceopening.py` re-wraps `en` itself into pages of
up to 2 rows x 40 letters, centred, split at sentence/clause ends, each page's
time proportional to its letters; a gap under 0.6 s to the next cue keeps the
band up.

```json
{"track": 19, "start": 170.9, "end": 173.7, "speaker": "",
 "en": "Separated from Jamie for two years.", "ps1": "INTRO_gillian_04",
 "cards": ["Separated from Jamie|for two years."]}
```

## faces.json

**Purpose.** Lets the subtitle stub recognise which character's portrait is on
screen, so it keeps only the speaker's face (moved to the left) and hides the
others. **Build:** `pcesubs.sig_blob()` packs it into the voice bank (rec 54, at
0x7E3A) as 9-byte records `[character code][w0][w1][w2][w3]` (words little-endian;
code = 1-based index of the name in `pcesubs.CHARS`). **Written by:**
`pce/harness/pcefaces.py learn <census.json>` (from play: the region whose mouth
sprites change most during a line is the speaker's), `pcefaces.py label <index>
<character>` (from the sheet of every face bitmap on the disc, `pcefaces.py
sheet` -> `work/pce/faces_sheet.png`), `layout_from_oracle.py --learn`.

Structure: `{character: [[w0, w1, w2, w3], ...]}`. The character must be in
`pcesubs.CHARS`. Each inner list is one **signature**: four 16-bit words
(decimal) of one portrait bitmap; a character has one signature per distinct
portrait (expressions, outfits, scenes).

**What the four numbers are.** A portrait is drawn by sprites from a face
region of VRAM: region *r* (4-7) starts at word address `0x4000 + r * 0x800`
(0x6000, 0x6800, 0x7000, 0x7800) and holds 32 sprite cells of 16x16 pixels, 64
words each (4 bit-planes x 16 rows, one bit per pixel, one word per row). The
signature is the VRAM words at offsets **0x88, 0xA8, 0xC8, 0xE8** from the
region's start (`pcesubs.SIG_OFFS`): row 8 of bit-planes 0 and 2 of cell 2
(0x88, 0xA8) and of cell 3 (0xC8, 0xE8). The code comments describe this as the
top of the hair, which the eye and mouth animation never rewrites, so it is
stable while the character talks. The numbers are the raw word values as read
through the VDC (`pcefaces.faces_of` reads them out of a savestate's VRAM).

**At runtime** the face block (in the resident file rec 110) reads those four
words from each face region on screen (`rmatch`: VRAM word address
`(0x40 + region*8) << 8 | offset`) and compares them with every signature;
all four must be equal. The match gives the region's character code, which is
compared with the character byte of the line being subtitled. A region that
matches nothing counts as unknown and is hidden; a speaker with no known face
on screen gets the plain layout.

```json
"Metal Gear": [[38237, 64136, 62972, 65031], [2047, 999, 15, 12]]
```
Two Metal Gear bitmaps: the first reads 0x955D, 0xFA88, 0xF5FC, 0xFE07 at
region+0x88/+0xA8/+0xC8/+0xE8.

## title_menu.json

**Purpose.** The English lettering of the title menu (NEW GAME, CONTINUE) and
the load screen's header bar (CASE FILES, replacing 捜査ファイル). These are
pictures, not text. **Build:** `pce/tools/titlemenu.py apply`: paints each mask
(a lighter edge on the top/left of each stroke, the fill colour, a two-step drop
shadow; palette indices from `titlemenu.LINES` / `HEADER`) into the sprite cells
of the title block (rec 958, streams A and B, both disc copies) and the header
tiles (stream U), re-encoded in place. **Written by:** `titlemenu.py render`
(Arial Bold 15 px through `lib/sysfont.py`); can be edited by hand, but `render`
overwrites hand edits.

`{label: [row, ...]}`, three labels. Each row is a string of `#` (ink) and `.`
(none); all rows of a label have the same length (width in pixels; 11 rows high).
The mask must fit its band (`titlemenu` exits if not).

```json
"CONTINUE": ["...####......####....##.....##.########...", ...]
```

## opening_sprites.json

**Purpose.** The opening's sprite captions: `June 6, 1991`, `Moscow`,
`50 years later` (rec 858, light grey with a blue two-step shadow) and `NEO KOBE
CITY` (rec 758, light fill with a double dark outline). **Build:**
`pce/tools/opencards.py apply` paints them into the sprite streams listed in
`opencards.SPRITE_SETS`. **Written by:** `opencards.py render` (same font and
format as title_menu.json); hand edits are lost on the next `render`.

Same format as title_menu.json: `{label: ["#..#", ...]}`; the label must match a
card label in `SPRITE_SETS`, and the mask must fit the card's band (32 px high,
16 px per cell column). The disclaimer, dedication and RSS cards are not here:
their English is in `opencards.CARDS` (code).

## gfx_labels.json

**Purpose.** Small Japanese labels baked into pictures, redrawn in English:
Gibson's note (`note`), the reception's JUNKER poster (`poster`), the opening
newspaper's headline (`newspaper`). Same edit language and wording as the PS1's
`ps1/tools/gfxlabels.py` and the Saturn's `satlabels.py`. **Build:**
`pce/tools/pcelabels.py apply` (`preview` writes before/after PNGs, `fit` checks
stream sizes). **Written by:** hand.

Top level: `{name: spec}`. Keys starting with `_` are comments; keys ending in
`_parked` are skipped.

| Spec field | Kind | Meaning |
|---|---|---|
| `tag` | all | Name used in messages and preview files |
| `kind` | all | `sprite` (an item close-up in rec 750), `object` (a sprite object whose cells sit in a scene picture's tile streams), `screen` (one display list's tile picture) |
| `block` | sprite | `[rec, sectors, first bank]` of the picture block |
| `block` | object | Index into the scene-block group of the file table (`work/pce/filetable.json` group "2") |
| `screen` | screen | `[block index, list index]` (the n-th display list with 2+ records) |
| `list` | all | Hex offset of the display list in the block (for `screen`, checked against `screen`) |
| `frames`, `frame` | object | Hex offset of the object's frame table; the frame to edit |
| `palette` | sprite (optional), object | Hex offset of the palette record to render with |
| `patterns` | object (optional) | Pattern base, default `"0x100"` |
| `also_at` | sprite | `[[track sector, hex offset]]`: byte-identical copies of the stream to rewrite too (rec 750's unnamed twin at sector 722) |
| `also` | object | `[[block index, hex list]]`: other blocks carrying the same cells (HQ in later acts) |
| `keep` | all | Boxes that must come out pixel-identical (checked) |
| `edits` | all | Operations applied in order |

Coordinates are pixels on the composed picture; boxes are inclusive
`[x0, y0, x1, y1]`; colours are palette indices (`screen`: palette*16 + index).

| Edit | Fields |
|---|---|
| `erase` | box; `fill` colour; `only` (optional: erase only these values) |
| `move` | box; `fill` for the vacated area; `dx`, `dy` |
| `copy` | box; `to` `[x, y]`; `source: "original"` copies from the unedited picture; `only` copies only these values |
| `remap` | box; `map` `{"old": new}` |
| `inpaint` | box; `values`: pixels of these values are filled from their most common 5x5 neighbour, repeatedly |
| `pixels` | `pixels`: rows of `#`/`.`; `x` (number or `"center"` within `span` `[x0, x1]`); `y`; `ink`; `drop` (shadow colour one row under) |
| `text` | `text`; `y`; `span`; `x` (default `"center"`); `ink`; `font` (`"6x13"` default, `"5x7"`); `scale`; `shadow` (colour at +1,+1) |

```json
{"text": "Search", "y": 13, "span": [3, 32], "ink": 1, "font": "5x7"}
```
One of the three rows that replace 家を捜せ on Gibson's note.
