# ps1/translation - the English data of the PlayStation port

This folder holds every piece of English that the PlayStation build writes
into the game: the script of the 39 scene banks, the voice-line subtitles,
and the text baked into a few pictures and the intro movie. None of these
files contains the Japanese source. The build reads the Japanese from your
own disc: `build.py` extracts it to `discs/extracted_ps1/` and runs
`ps1/tools/dump_strings.py`, which writes `work/ref/ISZ_<S>.json` (the same
`off`/`budget` records as here, with a `jp` field) for review and for the
checking tools. The subtitle cue files point at audio on the disc by sector
number; the audio and its Japanese transcripts stay on your side too.

The Saturn and PC Engine tools also read some of these files as their
English source (`saturn/tools/satcarry.py`, `satpages.py`, `pce/tools/*`).

All files are UTF-8 JSON. A key that starts with `_` (`_comment`, `_note`)
is a free-text note that no tool reads; a few of those notes predate the
switch of every rendered text to the X11 6x13 bitmap font
(`lib/bdffont.py`, `DIALOGUE`) and still name the older fonts.

## Conventions inside game strings

The game's text encoding is a 2-byte font index per character (see
`lib/textcodec.py`). English is stored by packing two ASCII letters into one
otherwise unused kanji glyph (`ps1/tools/pairfont.py`). In the JSON you write
plain text plus these fullwidth control characters, which pass through
unchanged:

| In the JSON | Meaning |
|---|---|
| `￥` (U+FFE5) | Hard line break inside a dialogue box. The runtime word-wrap also breaks long rows on its own, so `￥` is only needed where you want a break. |
| `＠赤` `＠白` `＠黄` `＠緑` `＠青` `＠水` `＠紫` `＠桃` | Colour change for the rest of the string: red, white, yellow, green, blue, cyan, purple, pink. `＠白` returns to normal text. Keep the colour codes the Japanese line has. |
| `＠Ｃ` | At the end of a combat or timed line: the box closes by itself. Keep it where the Japanese has it. |
| other fullwidth characters (`ＱＵＥＥＮ`, `★`, `数`) | Written as one glyph each, unpaired. Typed-puzzle answers must be fullwidth because the keyboard emits one glyph per key. |

**Cell.** One 12x12 glyph position on screen. A cell holds two halfwidth
letters (a pair glyph) or one fullwidth character. A pair with no free glyph
slot falls back to two fullwidth letters, i.e. two cells. Dialogue boxes are
18 cells wide (14 on Gaudi's terminal in B030/B040, 12 beside a portrait).

**Budget.** The number of bytes the original Japanese string occupied in
the bank, including its terminating null. The engine finds a string by its
start offset, so a replacement written in place must fit that footprint.
Encoded size of an English string = for each ASCII run between fullwidth
characters, its length rounded up to even (one 2-byte code per pair), plus
2 bytes per fullwidth character (a colour code is 4 bytes: `＠` + colour
kanji), plus 1 null. `ps1/tools/fit_report.py` reports it per string.

## ISZ_B000.json ... ISZ_B260.json - the script

One file per scene bank `PLN/ISZ/ISZ_<S>.BIN` (39 files). Every string in a
bank's string region has one record: dialogue, menu verbs, item names,
location names, and a few data strings the engine matches against.

- Read by: `ps1/tools/apply_translation.py` (writes `en` into a copy of the
  bank in `patched/`, padded with nulls to the budget), then
  `ps1/tools/repoint.py` (handles `long`). `ps1/tools/verify_build.py`
  re-encodes every string before the image is written.
  `ps1/tools/check_strings.py` lints colour codes, control bytes and row
  widths against the Japanese in `work/ref/`.
- Created by: `ps1/tools/dump_strings.py` (one record per non-empty
  original string, `en` empty; existing `en` values are kept on re-run).
- Edited by: hand, the review server `ps1/review/server.py` (writes `en` or
  `long`), `ps1/tools/reuse_fill.py`, `ps1/tools/rewrap.py`, and
  `ps1/tools/lock_data_strings.py` (sets `lock`).

Top level:

| Key | Type | Meaning |
|---|---|---|
| `file` | string | Bank file name on the disc, e.g. `ISZ_B010.BIN`. |
| `text_base` | int | Byte offset of the string region in the bank: the big-endian 16-bit value at the start of the file. |
| `strings` | list | One record per original string, in file order. |

Per string:

| Field | Type | Meaning |
|---|---|---|
| `off` | int | Byte offset of the original string from the start of the bank file (decimal; not relative to `text_base`). Identifies the string: bytecode refers to strings by this position, so it never changes. |
| `budget` | int | Bytes available in place: original string length + 1 for the null. `off + budget` is the next string's `off` unless empty strings sit in between. |
| `en` | string | English written in place. Must encode within `budget`; a string over budget is reported and not written. Empty = the original bytes stay (engine control records, unused debug labels, locked data, the B040 search keys). |
| `long` | string, optional | The full-length English when it does not fit `budget`. No size limit. `repoint.py` stores it outside the bank and installs a runtime remap so the engine reads the `long` text instead of the in-place slot. For banks that have a subtitle file it goes into `LONGS_<S>.BIN`, loaded to high RAM after the subtitle payload; for the resident bank B050 it is appended to the bank. A `long` may only use letter pairs that already have a glyph (`ps1/tools/rebuild_pairs.py` assigns them). When both exist, the player sees `long`; `en` is the short form kept in place. |
| `lock` | bool, optional | `true`: data the engine compares against (videophone dial table `数３９３４４４`, `★`/`☆` patterns, catch-all records). `en` must stay empty; `apply_translation.py` refuses to write it and `verify_build.py` fails if English appears. `false`: a typed-puzzle answer whose text is prescribed by `lock_data_strings.PUZZLE_TARGETS` (fullwidth Latin, possibly with the `以外` "other than" suffix the matcher needs). |

The name-search keys of Gaudi's database (B040) are not in this file: they
come from `ENGLISH` in `ps1/tools/keytable.py`, which rewrites that part of
the bank and moves any dialogue it displaces through the same remap.

Example (`ISZ_B010.json`):

```json
{ "off": 10566, "budget": 71,
  "en":   "Petrovich here, your dream￥navigator! Just pick any command!",
  "long": "Hey, it's Petrovich, your guide￥through dreamland!￥Just pick a command, any command!" }
```

The original line is 70 bytes + null at file offset 10566. The `en` fits
those 71 bytes and is written there; the player sees the `long`, three rows
broken by `￥`.

## subs_<S>.json - voice-line subtitles

One file per scene bank (39) plus `subs_INTRO.json` for the opening. Each
lists the spoken lines (XA audio streams) that play while that bank is
loaded and the English card to show for each. Eight banks have an empty
`cues` list: the file still has to exist so the subtitle payload runs and
the test harness logs the streams that bank plays.

- Read by: `ps1/subs/subs_cue.py on ps1/translation/subs_<S>.json --scene
  <S>`, run for every file during the build. It wraps each card, builds the
  payload `patched/SUBS_<S>.BIN` (code + 12-byte cue table + interned
  strings, at most 48 KB), relocates it past the end of the image and
  hooks it into the bank loader. `ps1/subs/check_cues.py` checks fit,
  overlap, anchors, payload size and reading speed.
- Edited by: hand and the review server (`en`, `speaker`, `enabled`);
  `ps1/subs/add_cues.py`, `split_long.py`, `merge_cues.py`, `mark_last.py`,
  `consolidate.py`. Each file was first cut by a per-bank generator using
  `ps1/subs/subgen.py` (the generators are kept in `attic/ps1/subs/`); the
  JSON has been edited since and is the shipped truth, so do not re-run
  them.

Top level: `scene` (bank id, e.g. `"B010"`, or `"INTRO"`), `options`,
`cues` (list, in table order; when two cues match, the first wins).

### options

| Key | Type | Default | Meaning |
|---|---|---|---|
| `menu_word` | int | `0x8701` (34561) | Low 16 bits of the scene's own dialogue window word (`ctx+0x1ACC`), stored in decimal. Bits 9-14 give the box layout mode the payload queues its text with; it must match the scene's native dialogue, or rows go missing. |
| `mode` | int, optional | derived | Redundant copy of the mode in `menu_word`; the build stops if it disagrees. Only B020 carries it. |
| `rows` | int | 3 | Rows per card. A card whose wrapped text needs more rows is a build error (split it into two cues). B020's box has 2. |
| `cols` | int | 18 | Wrap width in cells (capped at 18). All banks use 12, the width beside a portrait. |
| `faceleft` | bool | false | Portrait layout: the speaking character's face at the left of the box, text to its right, no nameplate when the face identifies the speaker. Each card is then stored twice: wrapped at `cols` and wrapped at 18 for when no face is on screen. |
| `fullwidth` | bool | true | With `faceleft`: `false` drops the second (18-cell) wrap to save payload space. No shipped file sets it. |
| `away_clear` | bool | true | `true`: the box is wiped after 240 frames (about 4 s) with no cue stream playing. `false`: only the verb-menu path clears it (B020, B080, whose persistent panels the timed wipe disturbed). |
| `intro` | bool | false | The opening sequence's payload (only `subs_INTRO.json`). |
| `_note` | string | | Comment. |

`subs_cue.py` also accepts `clear`, `layout`, `cold_fields`,
`clear_fields` and `clear_layout`; no shipped file uses them.

### cues

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Unique within the file, prefixed with the scene. The rest is how the generator named it: a running number (`B010_000`), or channel/file (`B010_c4f3` = channel 4, file 3; `B020_f2_0` = file 2, piece 0). A suffix `b`, `c`... marks a later card cut from the same line. The harness logs and the review tool refer to cues by id. |
| `file` | int | XA file number of the voice stream (the CD-XA subheader's file byte). With `chan` it identifies the stream: the card only shows if the stream the game selected (captured from its `CdlSetfilter`) has this file and channel. |
| `chan` | int | XA channel number of the stream. `254` = chain cue (see below). |
| `start` | int | First disc sector of the card: absolute sector number from the start of the disc image (CD time minus 150 frames). The card is live while the drive's reported position is in `[start, end)`. For a chain cue: frames after the anchor card was drawn. |
| `end` | int | One past the last sector (or frame, for a chain cue). `end - start` must be below 16384. |
| `dur` | float | Seconds the card covers. Informational: `check_cues.py` uses `(end - start) / dur` to compute reading speed; the build does not read it. |
| `speaker` | string | English speaker name. Becomes the nameplate text (one row, up to 12 cells; `""` = no plate). Selects the nameplate colour (`ps1/tools/translate_names.py` `NAMES` index + 1, or `EXTRA_COLOURS` in `subs_cue.py`) and, with `faceleft`, the portrait (`SPEAKER_CHAR`: Gillian, Mika, Chief, Harry, Metal Gear, Catherine, Randam, Jamie, Madnar, Napoleon, Chin, Teller). Any other speaker gets the nameplate and the full 18-cell width. |
| `en` | string | The card text, plain English without `￥` or colour codes; wrapped at build time by word to `cols` cells and `rows` rows. A literal `/n` forces a line break (supported, unused). |
| `enabled` | bool | `false` leaves the cue out of the payload (a muted card). Missing = `true`. |
| `last` | bool, optional | Last line of its conversation: the box is cleared and control handed back the moment this stream stops, without waiting for the idle timers. |
| `cols` | int, optional | Narrower wrap for this card only (must not exceed the bank's). |
| `noframe` | bool, optional | Hide the box's gold frame under this card and show only the dark fill. Used in B260 where the game loads a sprite into the frame's texture area. Not allowed in the opening. |
| `anchor` | string, optional | Chain cues: the `id` of the cue they follow. Chain cues subtitle voice lines played as VAG samples, which leave no XA stream to match; they fire on a frame timer counted from the moment the anchor card is drawn, window `[start, end)`. All chain cues in a file must share one anchor. Without `anchor`, `file` is read as the anchor's id number (`<scene>_<file:03d>`). |
| `by_ear` | bool, optional | The speaker was assigned by listening to the line, against what the engine's mouth animation says. The test harness then reports the card as `ear` instead of flagging a mislabel. Not read by the build. |
| `by_text` | bool, optional | The speaker was assigned from the Japanese wording (Metal Gear's polite register, a reaction that answers the line before), against an engine that animates a listener. Reported as `ear` like `by_ear`; a listen can overrule it. Not read by the build. |
| `ear_note`, `note` | string, optional | Comments (why a speaker was chosen, why a card is muted). Not read by any tool. |

Example (`subs_B010.json`):

```json
{ "id": "B010_004b", "file": 52, "chan": 2,
  "start": 30706, "end": 31130, "dur": 5.7,
  "speaker": "Mika", "en": "I'll show you around inside.", "enabled": true }
```

Second card cut from Mika's line on XA file 52, channel 2; it shows while
the drive reads sectors 30706-31129, under her portrait (pink nameplate
when no face is on screen).

Chain cue (`subs_B010.json`): `"chan": 254, "start": 120, "end": 470,
"anchor": "B010_017"` shows from frame 120 to frame 469 after card
`B010_017` was drawn.

### subs_INTRO.json - the opening

Same format, with `options` `{"menu_word": 32769, "rows": 3, "intro": true}`
(mode 0, 18-cell rows, no portraits). The cues cover the newsreel (stereo
reel file 2, channel 2) and Gillian's profile (file 3, channel 1); `speaker`
is empty. There is no bank loaded yet, so the payload builds the dialogue
rows itself and draws them on a darkened band. Extra fields, written by
`gen_intro.py place` (now `attic/ps1/subs/gen_intro.py`) from a
measurement of the unmodified opening:

| Field | Type | Meaning |
|---|---|---|
| `y` | int | Pixels the rows and band are moved down from their home position (row tops at screen lines 173/189/205) while this card shows, so the band clears the picture. Signed byte in the payload; never negative. |
| `pic_bottom` | int | Lowest screen line (pixels) where the original opening shows picture during this card's sectors. Record of the measurement; not read by the build. |
| `over` | bool | `true` when the band could not clear the picture: `y` was capped so the last row ends by line 228. Not read by the build. |
| `noband` | bool | No band under this card (only allowed with `intro`). Set on `INTRO_news_16b`, which starts at sector 127472 where the Snatcher diagram still comes up: that still is not drawn through the normal display list, so its narration is baked into the picture instead. |

`ps1/tools/introdiagram.py` reads the `en` of `INTRO_news_16` and paints
those words into the diagram still (`CXD_B0B0`).

## disclaimer.json - the red screen after New Game

The fiction disclaimer shown after New Game (`DES/CXD/CXD_B000.BIN`).

- Read by: `ps1/tools/disclaimer.py apply` (also `saturn/tools/satpages.py`).
  Edited by hand.
- `lines`: list of strings, one per screen line, top to bottom (the
  original has 5). Each line is rendered into the container's glyph atlas,
  centred on the 256-pixel-wide screen at a 20-pixel line pitch. A line
  wider than 240 px, a full atlas or more draw records than the original
  table holds stops the build.

```json
{ "lines": ["This story is fiction. The", "groups, companies and persons", "..."] }
```

## fmv_credits.json - text burned into the intro movie

English for the Japanese drawn into the frames of the intro FMV
(`STR/MX2_S000.STR`): the disclaimer still, the `NEO KOBE CITY` caption,
and the cast and staff credits.

- Read by: `ps1/tools/fmvtext.py` (`frames` decodes frames with jPSXdec,
  `build` repaints them, `apply` re-encodes into the image after
  `patch_disc.py`). Edited by hand.
- `segments`: list, one per piece of on-screen text. A segment with
  `"skip": true` is ignored.

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Label; `fmvtext.py build NAME` rebuilds one segment. |
| `frames` | [int, int] | First and last movie frame (frame numbers as jPSXdec numbers them) to search for the text. For a non-static segment the tool finds the frames where the text actually holds and uses frames up to `pad` (default 60) on each side as clean background. |
| `lines` | list of strings | English, one per text band, top to bottom, centred horizontally. An empty string erases the band and draws nothing. |
| `rows` | list of [y0, y1], optional | Pixel rows of each text band (screen lines, end exclusive). Default by line count: 1 line `[120,138]`; 2 `[88,106] [120,138]`; 3 adds `[152,170]`; 4 `[56,74] [88,106] [136,154] [168,186]`. Columns 34-290 are searched. |
| `ink_pct` | int, optional | Brightness percentile above which a pixel in a band counts as Japanese ink (default 76; 60 for `static`). |
| `grow` | int, optional | Dilation passes applied to the ink mask before erasing (default 2). |
| `static` | bool, optional | The text never changes against the background (the disclaimer still): take the given frames as the run directly. |
| `flat` | bool, optional | Flat backdrop: erase by filling with the band's median background colour instead of inpainting. |

The English is drawn in the colour sampled from the original glyphs.

```json
{ "name": "cast-gillian", "frames": [2790, 2872], "lines": ["GILLIAN SEED", "Yusaku Yara"] }
```

## gfx_pages.json - the memo pages

The thirteen full-page memo pictures `DES/CPC/CPC_B000.BIN` ... `CPC_B0C0.BIN`
(the Snatcher notes found in Act 1, read as one document).

- Read by: `ps1/tools/gfxpages.py apply` (also `saturn/tools/satpages.py`
  and `pce/tools/pcecards.py`). Edited by hand.
- Keys: container name without `.BIN`. Value: list of lines, at most 7,
  laid out as written: line `i` sits at y = 25 + 12·i, starting at x = 17
  and running to x = 183. `CPC_B060` and `CPC_B070` keep a photograph on
  the right; their lines stop at its left edge. `""` is a blank line;
  leading spaces indent. The tool erases the whole text column first, and
  prints any line wider than its space (the overrun is clipped).

```json
"CPC_B030": ["What we would call a", "suntan kills them."]
```

## gfx_labels.json - small labels inside pictures

Short Japanese labels baked into pictures: the videophone's "number not in
use" and "no video" cards (`CMC_B000`, `CMC_B010`), the note found on
Gibson's body (`CXC_B050`, stamped into its five other copies
`CXC_B000`-`B040`), the JUNKER HQ poster (`CXH_BX30`) and the joke
phone-book pictures (`CMC_B0D0`, `CMC_B0F0`, `CMC_B100`).

- Read by: `ps1/tools/gfxlabels.py apply` (`preview` writes before/after
  PNGs). Edited by hand.
- Keys: container name. The picture is the listed items of one section of
  the decompressed container, joined left to right into one canvas. All
  coordinates are canvas pixels, rectangles `[x0, y0, x1, y1]` inclusive,
  and every colour is a **palette index**, not RGB.

Entry fields:

| Field | Meaning |
|---|---|
| `section` | Container section, 0 or 1 (default 0). |
| `items` | Item indices in that section forming the canvas (default `[0]`). |
| `edits` | List of operations, applied in order (below). |
| `tag`, `crop`, `preview_cap`, `preview_lut` | Preview only: output file name, crop rectangle, a harness capture `[png, ox, oy]` to take colours from, or `"grey"`. |

Operations (one key names the operation):

| Operation | Fields | Effect |
|---|---|---|
| `erase` | `fill` | Fill the rectangle with index `fill`. |
| `move` | `dx`, `dy`, `fill` | Move the rectangle's pixels by (dx, dy); the vacated area gets `fill`. |
| `copy` | `to` [x, y], `source`, `only` | Copy the rectangle to `to`. `"source": "original"` copies from the unedited picture; `only` copies just the listed indices. |
| `pixels` | `x` (int or `"center"`), `span` [x0, x1], `y`, `ink`, `drop` | Hand-drawn lettering: `#` = pixel in index `ink`; `drop` draws a shadow one row below each pixel. |
| `text` | `y`, `x` / `span`, `ink`, `shadow`, `font`, `scale`, `proportional` | Render text in a BDF font (default `6x13`). `y` = top of the font cell; centred within `span` unless `x` is a number; `shadow` index drawn at +1,+1; `scale` = integer magnification; `proportional` crops each glyph to its ink. An overrun of `span` is reported. |
| `remap` | `map` {"old": new} | Replace indices inside the rectangle. |
| `inpaint` | `values` | Each pixel with a listed index takes the commonest other index around it, working inward. |
| `stamp` | `src` rect, `to` [x, y] | Paste a region of another entry's finished picture, only where this picture showed the same original pixels. |

```json
"CMC_B000": {"section": 0, "items": [0, 1], "edits": [
  {"erase": [5, 26, 114, 40], "fill": 19},
  {"text": "Number not in use.", "y": 27, "span": [6, 113], "ink": 20, "shadow": 18}]}
```

## staff_roll.json - the credit roll after New Game

The cast and staff roll that plays over the city after New Game
(`DES/CXD/CXD_BX30.BIN`). It is drawn by a sprite blitter from a glyph
atlas, separately from the FMV credits above.

- Read by: `ps1/tools/staffroll.py apply`. Edited by hand.
- `screens`: list of screens in playing order; must have exactly as many
  entries as the original (22). Each screen is a list of lines, top to
  bottom, and must have as many lines as the original screen drew; each
  line takes the y position of an original line. A run of two or more
  spaces splits a line into separately centred columns.
- Limits: the atlas is 128 x 512 pixels (32 rows of 16-pixel cells); text
  is set proportionally in the 6x13 font. The tool stops with "atlas full"
  or when the screens need more draw records than the original table holds.

```json
["GRAPHICS", "Shin Toyama    Naoya Hatsumi", "Takayuki Ando    Jun Asami"]
```

## uncensor_edits.json - retired

Belongs to the retired `--lisa` option of `ps1/tools/uncensor.py`, which
transplanted the PC Engine's picture into the female Snatcher's body
picture (`CXF_B080`) and stored a hand retouch as a pixel delta. The build
now uses `--lisa-saturn` (the Saturn's original art) and does not read this
file.

- Written by `uncensor.py --lisa-edit EDITED.png`; read by `uncensor.py
  --lisa`.
- Structure: `{"CXF_B080": [[x, y, r, g, b], ...]}`: pixel position in the
  192 x 128 composite and its true-colour value (0-255 per channel), applied
  before the picture is quantised to the container palette.
