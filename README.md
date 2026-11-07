# Snatcher: English Translation (Sega Saturn, PlayStation and PC Engine CD)

**Version 1.5.1**, 2026, by pepa

Snatcher is Hideo Kojima's cyberpunk adventure: in Neo Kobe City, Gillian
Seed, a detective with no memory of his past, joins the JUNKER unit to hunt
the Snatchers, machines that kill people and take their place. Konami
released it in Japan only on the PC Engine Super CD-ROM² as *Snatcher
CD-ROMantic* (1992), then on the Sega Saturn (T-9508G, 1996) and the
PlayStation (SLPS-00154, 1996), all three with voice acting. This project
translates all three into English: the same translation, one patch for each
console.

**Contents:** [Which version?](#which-version) ·
[Saturn](#the-saturn-version) · [PlayStation](#the-playstation-version) ·
[PC Engine](#the-pc-engine-version) · [How it was translated](#how-it-was-translated) ·
[How it works](#how-it-works) · [Documentation](#documentation) ·
[Building from source](#building-from-source) · [Changelog](#changelog) ·
[Reporting bugs](#reporting-bugs) · [License](#license-and-reuse) · [Credits](#credits)

## Which version?

**The Saturn version is the definitive edition.** It shows the pictures
the PlayStation port greys out or mosaics, and its scene pictures are at
their full width, 240 pixels, the way Konami drew them; the PlayStation
narrows every scene picture to 192 pixels by dropping columns. It is not
entirely uncut: like the PlayStation, it reworks the scene of the dog
falling from the window so the body lands with its back to the camera,
where the PC Engine version shows its wounds. Play the Saturn version if
you can.

The PC Engine version is the original CD release, the first with the whole
story to its end. The 1996 ports added scenes to it and redrew some
pictures; the PC Engine keeps Konami's first take, the dog scene uncut
included.

The PlayStation patch comes in two variants: translation only, with the
PlayStation's art as shipped, and uncensored, which restores the pictures
the PlayStation port greys out or mosaics. The dog scene stays as the
PlayStation has it.

| | Download | Patches |
|---|---|---|
| Sega Saturn | `Snatcher-Saturn-English-v1.5.1.zip` | track 1 + track 2 |
| PlayStation | `Snatcher-PS1-English-v1.5.1.zip` | translation only, or uncensored |
| PC Engine CD | `Snatcher-PCE-English-v1.5.1.zip` | the whole disc |

Downloads: <https://github.com/pepasjc/snatcher-translated/releases>.

Version 1.5 is the first release of the PC Engine patch. The PlayStation
and Saturn patches move to 1.5 with it, so all three share one version
number; their changes since 1.0 are fixes (see the changelogs). If you are
playing an earlier version, patch your original dump again; your saves
carry over.

## The Saturn version

### What is translated

The whole game, from New Game to the ending.

- Every line of the script, in all 39 scenes: conversations, descriptions,
  Gaudi's database and the phone calls, plus the lines only the Saturn
  has (the backup memory and cartridge messages, the videophone
  directory, the scene with Konami's staff). Nothing is cut to fit the
  Japanese text boxes. When a line needs more room than the box has, it
  continues on a second page, and the speaker's name stays on top.
- The voice acting, with subtitles in every voiced scene from the opening
  narration to the ending, timed to the voices. The speaker's portrait
  sits on the left of the box and the name is drawn in the character's
  own colour; when no portrait is on screen the text uses the full width
  of the box.
- Every menu, verb, item and location label, and the speaker names.
- The keyboard and the typed puzzles. The keys show Latin letters, and
  Gaudi's name search takes English names.
- The graphics with writing in them: the memo pages, Gibson's diary, the
  New Game disclaimer, and the opening's captions and credit roll. A
  translation card and a short disclaimer about the translation play
  before the Konami logo.
- The OPTION MENU has a fifth item, WALLPAPERS. It picks one picture to sit
  behind the whole game: ACT 1, ACT 2 and ACT 3 (the three JUNKER plates),
  TWINBEE, KONAMI, TOKIMEKI, ENDING, GRADIUS and TURBOCAR (the pictures the
  original hides behind the Konami code), or BLACK for no wallpaper at all.
  Move the cursor to see each one behind the menu and confirm to keep it.
  If you never choose one, the game changes plates with each act as it
  always did.

Names follow the Japanese original, so the subtitles match what the voice
actors say: Randam Hajile, Dr. Madnar, Catherine Gibson, Gaudi.

### How to apply

You need your own dump of *Snatcher (Japan)* for the Saturn in the
redump.org BIN/CUE layout, three tracks. Track 1 must hash:

```
Size   479149440
CRC32  61c1c029
MD5    fd6c0438987fcbc8f520efeed54b37a5
SHA1   a3ebab5b07a2b9a17aa68554072585be8839aba3
```

(README.txt in the zip lists all three tracks.) Two patches are in the zip,
one for track 1 and one for track 2; track 3 (the CD audio) is not changed.

- `Snatcher (Japan) (Track 1) [T-En by pepa v1.5.1].xdelta`
- `Snatcher (Japan) (Track 2) [T-En by pepa v1.5.1].xdelta`

The easy way: put your three original track files in the folder you
unzipped and run `apply.bat` (Windows, double-click) or `apply.sh` (Linux
and macOS: `sh apply.sh`). It checks your dump, applies both patches and
checks the results. The Windows script downloads xdelta3 by itself if it
is missing; on Linux and macOS install it first (`apt install xdelta3`,
`brew install xdelta`).

By hand:

```
xdelta3 -d -s "Snatcher (Japan) (Track 1).bin" "Snatcher (Japan) (Track 1) [T-En by pepa v1.5.1].xdelta" "Snatcher (Japan) [T-En by pepa v1.5.1] (Track 1).bin"
xdelta3 -d -s "Snatcher (Japan) (Track 2).bin" "Snatcher (Japan) (Track 2) [T-En by pepa v1.5.1].xdelta" "Snatcher (Japan) [T-En by pepa v1.5.1] (Track 2).bin"
```

Delta Patcher (Windows) or MultiPatch (macOS) do the same with a window.
Put `Snatcher (Japan) [T-En by pepa v1.5.1].cue` from the zip next to the two
new files and your original `Snatcher (Japan) (Track 3).bin`, and load the
.cue. The new track 1 is larger than the original; that is expected. The
results should hash:

```
Snatcher (Japan) [T-En by pepa v1.5.1] (Track 1).bin
Size   479709216
CRC32  ad81e397
MD5    e06f7639310a4aa140d5369952201189
SHA1   23a6c177c4acfd1fe607cc98d34adc6d588e919f

Snatcher (Japan) [T-En by pepa v1.5.1] (Track 2).bin
Size   58576560
CRC32  4ddc9b55
MD5    28ed4cbbb658d448ac8e5aa38e106a6e
SHA1   a7c4e8b4825092324fe3429b85ee4496f73d1654
```

### Compatibility

Tested on a MiSTer, in Beetle Saturn (RetroArch / Mednafen) and on a
Saturn from a burned CD-R. The patched image is plain BIN/CUE and converts
to CHD with `chdman createcd`.

To burn a disc, burn from the BIN/CUE, not from a CHD. Some burning tools,
cdrdao and the MiSTer's Disc Tools among them, refuse the cue because it
mixes a Mode 1 and a Mode 2 data track ("Invalid combination of track
modes"). For those, join the three tracks into one file (Windows:
`copy /b "track1.bin" + "track2.bin" + "track3.bin" "Snatcher.bin"`,
Linux and macOS: `cat`) and burn this cue, with the FILE line naming your
joined file:

```
FILE "Snatcher.bin" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
  TRACK 02 MODE2/2352
    INDEX 00 45:19:34
    INDEX 01 45:22:34
  TRACK 03 AUDIO
    INDEX 00 50:51:39
    INDEX 01 50:53:39
```

## The PlayStation version

### What is translated

The whole game, from New Game to the ending credits.

- Every line of the script, in all 39 scenes: conversations, descriptions,
  Gaudi's database and the phone calls, 12,004 strings in all. Nothing is
  cut to fit the Japanese text boxes. When a line needs more room than the
  box has, it continues on a second page, and the speaker's name stays on
  top.
- The voice acting, with subtitles: 1,121 of the 1,130 spoken lines,
  timed to the voices from the opening narration to the ending. The
  speaker's portrait sits on the left of the box and the name is drawn in
  the character's own colour. The lines left out are jingles, sound
  effects and repeats.
- Every menu, verb, item and location label, and the speaker names.
- The keyboard and every typed puzzle. The keys show Latin letters, and
  Gaudi's name search, the passwords and the videophone numbers take
  English input.
- The graphics with writing in them: the memo pages, the New Game
  disclaimer, the credit roll, the opening's title cards and Snatcher
  diagram, and the captions and credits burned into the intro movie.
- The OPTION MENU gets a SPECIAL OPTIONS item that opens the game's hidden
  special menu (wallpaper, cursor colour, target pointer) without the
  Konami code.

Names follow the Japanese original, so the subtitles match what the voice
actors say: Randam Hajile, Dr. Madnar, Catherine Gibson, Gaudi. The 1994
Sega CD script guided terminology and tone, but it was not copied: the
PlayStation text has scenes the Sega CD lacks and breaks its lines
differently, so it was translated from the Japanese.

### How to apply

You need your own dump of *Snatcher (Japan)* in BIN/CUE form, matching the
redump.org entry:

```
Size   573702192
CRC32  d5475fac
MD5    b6b825a8c91fd9879553c8a4e6e791c8
SHA1   e6cd330feb594b3951089da866db1a400f0173f6
```

Two patches are in the zip. Pick one:

- `Snatcher (Japan) [T-En by pepa v1.5.1].xdelta`: the translation, with
  the game's artwork untouched.
- `Snatcher (Japan) [T-En by pepa v1.5.1] (Uncensored).xdelta`: the same
  translation, with the PlayStation-only censorship undone.

The easy way: put your `Snatcher (Japan).bin` in the folder you unzipped
and run `apply.bat` (Windows, double-click) or `apply.sh` (Linux and
macOS: `sh apply.sh`). It asks which version you want, checks your dump,
applies the patch and checks the result. The Windows script downloads
xdelta3 by itself if it is missing; on Linux and macOS install it first
(`apt install xdelta3`, `brew install xdelta`).

By hand: apply it with xdelta3, Delta Patcher (Windows), MultiPatch
(macOS) or any xdelta front-end:

```
xdelta3 -d -s "Snatcher (Japan).bin" "Snatcher (Japan) [T-En by pepa v1.5.1].xdelta" "Snatcher (Japan) [T-En by pepa v1.5.1].bin"
```

or

```
xdelta3 -d -s "Snatcher (Japan).bin" "Snatcher (Japan) [T-En by pepa v1.5.1] (Uncensored).xdelta" "Snatcher (Japan) [T-En by pepa v1.5.1] (Uncensored).bin"
```

Put the `.cue` of the same name next to the output `.bin`. The patched
image is larger than the original (relocated data is appended past the
original end); that is expected. Expected results:

```
Snatcher (Japan) [T-En by pepa v1.5.1].bin
Size   575687280
CRC32  ee7dbbe6
MD5    c489d1722e4cb4022ae3d44a6733c980
SHA1   7e9ff5b367ae425ba94ba50fe81d00ba1fe6d56f
```

```
Snatcher (Japan) [T-En by pepa v1.5.1] (Uncensored).bin
Size   575706096
CRC32  5338f74a
MD5    4e617d715f0d1a99460e12472b8978c9
SHA1   d4fe8a0d90cdff44349e9cfa26c64470098a8850
```

Do not apply the patch to a `.iso` (2048-byte sectors) or a `.chd`;
convert those to BIN/CUE first. The patch is about 22 MB because the intro
movie's frames were re-encoded.

### Compatibility

Tested on real hardware, PS3, MiSTer, DuckStation and Beetle PSX /
Beetle PSX HW (RetroArch) and PSP. The image is a plain Mode 2 BIN/CUE and
converts to CHD with `chdman createcd`. Save files from the Japanese
game are compatible.

## The PC Engine version

### What is translated

The whole game, from New Game to the ending.

- Every line of the script: conversations, descriptions, Gaudi's database,
  the videophone, the shop and the quiz. Nothing is cut to fit the
  Japanese text boxes.
- The voice acting, with subtitles timed to the voices, both the voice
  clips and the dialogue on the CD audio tracks, the opening's narration
  included. The speaker's portrait sits on the left of the box; a line
  with no portrait on screen shows the speaker's name instead.
- Every menu, verb, item and location label, and the speaker names.
- The keyboard and the typed puzzles. The keys show Latin letters, and
  Gaudi's name search takes English names.
- The graphics with writing in them: the title menu and the load screen,
  the opening's cards, captions and credits, Gibson's memo pages and his
  note, the videophone cards, the JUNKER poster, the epilogue card and the
  ending's credit roll. A translation card and a short disclaimer about the
  translation play before the Konami logo.

Names follow the Japanese original, so the subtitles match what the voice
actors say: Randam Hajile, Dr. Madnar, Catherine Gibson, Gaudi.

Left in Japanese on purpose: the opening newspaper's date line and
vertical columns (only its boxed headline is in English) and background
signage.

### How to apply

You need your own dump of *Snatcher CD-ROMantic (Japan)* in the
redump.org BIN/CUE layout: 24 track files, `Snatcher CD-ROMantic (Japan)
(Track 01).bin` to `(Track 24).bin`. The patch applies to the whole disc
as one file, the 24 tracks joined in order. That file must hash:

```
Snatcher CD-ROMantic (Japan).bin
Size   632974944
SHA1   db254c2e2d888d042cb9df8dc55599feb4d1132d
```

A single BIN written by `chdman extractcd` from the redump CHD is the same
file.

The easy way: put the 24 track files in the folder you unzipped and run
`apply.bat` (Windows, double-click) or `apply.sh` (Linux and macOS:
`sh apply.sh`). It joins the tracks, checks your dump, applies the patch
and checks the result. The Windows script downloads xdelta3 by itself if
it is missing; on Linux and macOS install it first (`apt install
xdelta3`, `brew install xdelta`).

By hand:

```
copy /b "Snatcher CD-ROMantic (Japan) (Track 01).bin" + ... + "Snatcher CD-ROMantic (Japan) (Track 24).bin" "Snatcher CD-ROMantic (Japan).bin"
xdelta3 -d -B 1073741824 -s "Snatcher CD-ROMantic (Japan).bin" "Snatcher CD-ROMantic (Japan) [T-En by pepa v1.5.1].xdelta" "Snatcher CD-ROMantic (Japan) [T-En by pepa v1.5.1].bin"
```

(On Linux and macOS, `cat "Snatcher CD-ROMantic (Japan) (Track "*").bin >
"Snatcher CD-ROMantic (Japan).bin"` joins the tracks.) Put `Snatcher
CD-ROMantic (Japan) [T-En by pepa v1.5.1].cue` from the zip next to the new
file and load the .cue. Track 2 is longer than the original, so the cue's
track times differ from the redump cue; use the one in the zip. The
result should hash:

```
Snatcher CD-ROMantic (Japan) [T-En by pepa v1.5.1].bin
Size   634386144
CRC32  9be8d350
MD5    87a5b52dcb2560e8f3ee7c57b4243799
SHA1   c2ec76875670506edff7b3bb290f6abf007f4300
```

### Compatibility

The game needs the Super System Card 3.0 BIOS (`syscard3.pce`), as the
original does. Tested in Beetle PCE (RetroArch / Mednafen) and on a
MiSTer. The patched image is plain BIN/CUE and converts to CHD with
`chdman createcd`.

### Known issues

Open on the tracker at release time (PC Engine label):

- #94: after saving, quitting and starting a New Game, the opening can
  play black under its subtitles.
- #86: the subtitles in Randam's scene at the end of Act 1 can run out of
  step with the voices.
- #78: at Gibson's house, the diary's spoken lines draw their subtitle
  under the computer screen.
- #58: at the start of Act 2 the game can freeze in the Chief's room with
  the recap's last subtitle on screen.

## How it was translated

This is an AI-assisted translation. The first pass was machine-translated
from the Japanese PlayStation script, not the Sega CD version. For 1.0 the
whole script was translated again at full length, now that the engine no
longer limits how long a line can be, and every line went through a human
review that changed 10,970 of them. The voice subtitles are timed from a
speech-recognition pass over the Japanese audio, checked by hand, and
reviewed the same way.

I know what an AI-slop patch looks like, and I don't want this to be one.
The English is read against the Japanese scene by scene and rewritten
wherever it reads like a machine wrote it. The 1994 Sega CD localization
is a reference for terminology and tone where the scenes overlap, not a
source. Names follow the Japanese, so the subtitles match what the voice
actors say.

The Saturn release uses the same translation. Its script follows the
PlayStation's almost line for line; where its Japanese differs (its own
phone numbers, a different quiz answer, lines split differently, the lines
only the Saturn has), the English follows the Saturn. The PC Engine script
is the same story with fewer scenes; it reuses the English wherever its
Japanese matches, and the rest was translated from its own Japanese.

The review is done in a tool built for it: every line of a scene on one
row, with the speaker, the Japanese with furigana, the English, and a
button that plays the voice line straight off the disc. A headless harness
plays the game and photographs every subtitle, and every reported bug has
a save attached so it can be reached again. See
**[The review tool](docs/review-tool.md)** for what it looks like and what
it checks.

Corrections are welcome: open an issue with the line and the scene.

## How it works

None of the three games was built to be translated: the text is not
Shift-JIS, strings sit at fixed offsets with no room to grow, and the voiced
scenes were never meant to show text. Each patch therefore changes the game
itself, not just its script.

- **PlayStation.** English letters are packed two to a glyph in unused kanji
  slots of the game's font, so an English line costs what the Japanese did;
  lines that need more room are moved to a per-scene file loaded into free
  RAM and redirected by a small stub in the executable. Subtitles come from
  a payload that watches the CD drive's position in the voice stream and
  hands each line to the game's own dialogue box. Grown files are appended
  past the end of the disc with fresh sector headers and error correction.
- **Saturn.** The same script and design on a different engine: the scene
  banks live in one packed data file that the build re-lays, the executable
  is patched with SH-2 routines, the pair glyphs extend the font in video
  memory, and subtitles follow the decoded bytes of each voice clip.
- **PC Engine.** The text is drawn from the System Card's built-in font, so
  the glyph fetch is hooked and each scene module carries its own small
  English font; long lines are read from a block loaded beside the scene,
  and subtitles cover both the ADPCM voice clips and the dialogue on the CD
  audio tracks.

## Documentation

| Document | What it covers |
|---|---|
| [docs/ps1.md](docs/ps1.md) | The PlayStation game and the patch: disc and file tables, text encoding and storage, the pair-glyph font, word wrap, menus and keyboard, voice subtitles, graphics, uncensoring, build order, engine reference |
| [docs/saturn.md](docs/saturn.md) | The Saturn port: tracks and DATA.BIN, the carried PS1 English, long strings and SH-2 stubs, font, subtitles on ADPCM lines and reels, graphics, build order, engine reference |
| [docs/pce.md](docs/pce.md) | The PC Engine port: the disc and its file table, script modules, the hooked font, long strings, voice and CD-audio subtitles, graphics, build order, engine reference |
| [ps1/README.md](ps1/README.md) | Every PlayStation data file and field: script strings, subtitle cues, pictures, credits |
| [saturn/README.md](saturn/README.md) | Every Saturn data file and field |
| [pce/README.md](pce/README.md) | Every PC Engine data file and field, including the dialogue keys and the portrait signatures |
| [BUILDING.md](BUILDING.md) | Building any of the three patches from your own discs, with or without Docker |
| [docs/review-tool.md](docs/review-tool.md) | The tool the translation is reviewed in |

## Building from source

Every tool used to make these patches is in this repository, with the
English data. Supply your own disc dumps and run:

```
pip install -r requirements.txt
python build.py discs /path/to/your/dumps
python build.py all --release
```

or use the Dockerfile. [BUILDING.md](BUILDING.md) has the details: which
discs each port needs, the fonts, and what ends up in `patched/` and
`release/`.

## Repository layout

| Folder | Contents |
|---|---|
| `build.py`, `Dockerfile` | the build, all ports |
| `lib/` | shared code: text codec, LZSS, card planner, fonts, release helpers, emulator host |
| `ps1/`, `saturn/`, `pce/` | per port: `tools/` (the build chain), `translation/` (the English data), `harness/` (headless play-testing), `build/` (Windows batch files); PS1 and Saturn also `subs/` (subtitle cue tools), PS1 `review/` (the review tool) |
| `docs/` | the architecture documents above |
| `work/` | build scratch; six committed build inputs (the pair table and its free slots, the PS1 file map, the voice census, jPSXdec's index, the font table) |

## About me

I'm an aerospace software engineer. I lived in Japan for four years and in
Germany for five, and I'm now based in Brazil. This is a hobby project and
is still a work in progress.

## Changelog

- PC Engine: 1.5 is its first release; 1.5.1 corrects Gaudi's entry on
  Napoleon (#102), as on the other two ports.
- Saturn: [saturn/CHANGELOG.md](saturn/CHANGELOG.md)
- PlayStation: [ps1/CHANGELOG.md](ps1/CHANGELOG.md)

Older releases: <https://github.com/pepasjc/snatcher-translated/releases>.

## Reporting bugs

Open an issue at <https://github.com/pepasjc/snatcher-translated/issues>.
Please include the scene or location, what was on screen (a screenshot
helps), and a save (memory card, Saturn backup memory or PC Engine save)
if you can. Text
that overflows its box, a subtitle that lags or leads its voice or names
the wrong speaker, or any freeze: all wanted. Load the game from a save,
not a save state made on an earlier version: a save state carries the old
version's text and glyphs and shows the old bugs.

Downloads: <https://github.com/pepasjc/snatcher-translated/releases>.

## License and reuse

- **Source code** (`build.py`, `lib/`, and each port's `tools/`, `subs/`,
  `harness/`, `review/` and `build/` folders): [MIT](LICENSE). Use it for
  anything, other games included; keep the copyright notice.
- **Translation and documentation** (the `translation/` folders, `docs/`, and
  the README, BUILDING and CHANGELOG files):
  [CC BY-NC-SA 4.0](LICENSE-DATA). You may adapt them, including into
  another language, as long as you credit this project, do not sell the
  result, and share it under the same license.
- **Snatcher** - its Japanese script, graphics, music and voices - is
  (c) Konami. Nothing from the game is in this repository or licensed by it.

If you translate the game into another language starting from this work,
please credit it like this:

> Based on the Snatcher English translation by pepa -
> https://github.com/pepasjc/snatcher-translated

Third-party material: the X11 "fixed" fonts in `lib/fonts` are public domain;
Tamzen keeps its own license (`lib/fonts/LICENSE-Tamzen.txt`). jPSXdec,
xdelta3, chdman and the Windows fonts some pictures are rendered in are not
included; the build fetches or asks for them.

## Credits

- Translation, tools and hacking: pepa
- Terminology reference: the 1994 Sega CD localization (Konami)
- English text: the X11 "fixed" fonts (public domain), and Tamzen for the
  PlayStation opening's JUNKER HQ caption
- Tools used: jPSXdec, DuckStation, Beetle PSX, Beetle Saturn, Beetle PCE,
  PCSX-Redux, faster-whisper, capstone, xdelta3, chdman

This is a fan translation. It is free, and it must not be sold or bundled
with a disc image. Snatcher is © Konami.
