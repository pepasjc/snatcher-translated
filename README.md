# Snatcher: English Translation (Sega Saturn and PlayStation)

**Version 1.0.1** (Sega Saturn, 2026-10-01) and **1.0** (PlayStation, 2026-09-30), by pepa

Snatcher is Hideo Kojima's cyberpunk adventure: in Neo Kobe City, Gillian
Seed, a detective with no memory of his past, joins the JUNKER unit to hunt
the Snatchers, machines that kill people and take their place. Konami
released it in Japan only on the Sega Saturn (T-9508G, 1996) and the
PlayStation (SLPS-00154, 1996), both with voice acting throughout. This
project translates both into English: the same translation, one patch for
each console.

## Which version?

**The Saturn version is the definitive edition.** It shows the pictures
the PlayStation port greys out or mosaics, and its scene pictures are at
their full width, 240 pixels, the way Konami drew them; the PlayStation
narrows every scene picture to 192 pixels by dropping columns. It is not
entirely uncut: like the PlayStation, it reworks the scene of the dog
falling from the window so the body lands with its back to the camera,
where the PC Engine version shows its wounds. Play the Saturn version if
you can.

The PlayStation patch comes in two variants: translation only, with the
PlayStation's art as shipped, and uncensored, which restores the pictures
the PlayStation port greys out or mosaics. The dog scene stays as the
PlayStation has it.

| | Download | Patches |
|---|---|---|
| Sega Saturn | `Snatcher-Saturn-English-v1.0.1.zip` | track 1 + track 2 |
| PlayStation | `Snatcher-PS1-English-v1.0.zip` | translation only, or uncensored |

Downloads: <https://github.com/pepasjc/snatcher-translated/releases>.

Saturn 1.0.1 fixes a softlock in 1.0: after Metal Gear's introduction at
JUNKER HQ, Harry's last subtitle stayed on screen over the menu. If you are
playing 1.0, patch your original tracks again with 1.0.1; your saves carry
over.

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

- `Snatcher (Japan) (Track 1) [T-En by pepa v1.0.1].xdelta`
- `Snatcher (Japan) (Track 2) [T-En by pepa v1.0.1].xdelta`

The easy way: put your three original track files in the folder you
unzipped and run `apply.bat` (Windows, double-click) or `apply.sh` (Linux
and macOS: `sh apply.sh`). It checks your dump, applies both patches and
checks the results. The Windows script downloads xdelta3 by itself if it
is missing; on Linux and macOS install it first (`apt install xdelta3`,
`brew install xdelta`).

By hand:

```
xdelta3 -d -s "Snatcher (Japan) (Track 1).bin" "Snatcher (Japan) (Track 1) [T-En by pepa v1.0.1].xdelta" "Snatcher (Japan) [T-En by pepa v1.0.1] (Track 1).bin"
xdelta3 -d -s "Snatcher (Japan) (Track 2).bin" "Snatcher (Japan) (Track 2) [T-En by pepa v1.0.1].xdelta" "Snatcher (Japan) [T-En by pepa v1.0.1] (Track 2).bin"
```

Delta Patcher (Windows) or MultiPatch (macOS) do the same with a window.
Put `Snatcher (Japan) [T-En by pepa v1.0.1].cue` from the zip next to the two
new files and your original `Snatcher (Japan) (Track 3).bin`, and load the
.cue. The new track 1 is larger than the original; that is expected. The
results should hash:

```
Snatcher (Japan) [T-En by pepa v1.0.1] (Track 1).bin
Size   479711568
CRC32  3c4bfeac
MD5    f0885e32a22448f1301e69ed4b4ac522
SHA1   68813581415ad00ea7acb99d3bc7c5fa6deaa0a3

Snatcher (Japan) [T-En by pepa v1.0.1] (Track 2).bin
Size   58576560
CRC32  eb6d51c3
MD5    0eb71c69d0236e6b872905d008f6e087
SHA1   1d73a5b5f83eb455562c5bec9dba791d593fd57d
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

- `Snatcher (Japan) [T-En by pepa v1.0].xdelta`: the translation, with
  the game's artwork untouched.
- `Snatcher (Japan) [T-En by pepa v1.0] (Uncensored).xdelta`: the same
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
xdelta3 -d -s "Snatcher (Japan).bin" "Snatcher (Japan) [T-En by pepa v1.0].xdelta" "Snatcher (Japan) [T-En by pepa v1.0].bin"
```

or

```
xdelta3 -d -s "Snatcher (Japan).bin" "Snatcher (Japan) [T-En by pepa v1.0] (Uncensored).xdelta" "Snatcher (Japan) [T-En by pepa v1.0] (Uncensored).bin"
```

Put the `.cue` of the same name next to the output `.bin`. The patched
image is larger than the original (relocated data is appended past the
original end); that is expected. Expected results:

```
Snatcher (Japan) [T-En by pepa v1.0].bin
Size   575675520
CRC32  8385d077
MD5    72f5dbe88854823ddc365c5087cb6a34
SHA1   9b7a6e812fb60c91e9daa8a47446ce6b14001ceb
```

```
Snatcher (Japan) [T-En by pepa v1.0] (Uncensored).bin
Size   575694336
CRC32  0f06d4b0
MD5    2e0e412e40d63ed7de2968f8af092b63
SHA1   d8a4294608aef1b934e9a8cd9511735803a6a454
```

Do not apply the patch to a `.iso` (2048-byte sectors) or a `.chd`;
convert those to BIN/CUE first. The patch is about 22 MB because the intro
movie's frames were re-encoded.

### Compatibility

Tested on real hardware, PS3, MiSTer, DuckStation and Beetle PSX /
Beetle PSX HW (RetroArch) and PSP. The image is a plain Mode 2 BIN/CUE and
converts to CHD with `chdman createcd`. Save files from the Japanese
game are compatible.

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
only the Saturn has), the English follows the Saturn.

The review is done in a tool built for it: every line of a scene on one
row, with the speaker, the Japanese with furigana, the English, and a
button that plays the voice line straight off the disc. A headless harness
plays the game and photographs every subtitle, and every reported bug has
a save attached so it can be reached again. See
**[The review tool](docs/review-tool.md)** for what it looks like and what
it checks.

Corrections are welcome: open an issue with the line and the scene.

## Technical Details

### PlayStation

Most of the work in this project is not translation. It is reverse
engineering: the game's text encoding, font, dialogue box, CD streaming and
graphics containers all had to be taken apart before a single English line
could go in. That work is done, and it is what makes the game fully
playable in English for everyone.

**Text.** The script is not Shift-JIS. Each character is a two-byte index
into the game's font, and every string is referenced by its byte offset,
so a string cannot grow in place. Japanese is dense: one kanji carries
what takes several English letters. So unused kanji slots in the font are
redrawn to hold two Latin letters each, and two letters then cost the same
two bytes as one kanji. A line that still needs more room than the
Japanese took is moved to a separate file per scene, loaded into free RAM
alongside it, and a small patch in the executable redirects the original
string to it at runtime. No line has to be cut to fit.

**Extraction.** A tool walks the disc image, pulls the 39 scene files,
decodes every string with its byte budget, and writes them out as JSON.
The English goes back the same way: encoded with the new font, checked
against the budget, and patched in place. A build verifies every string,
every name and every redrawn glyph before it writes a disc.

**Subtitles.** The PS1 voices were never subtitled; the game just plays the
audio. This patch adds a small subtitle payload per scene, loaded into
spare RAM after the scene file. Every frame it reads where the CD drive is
in the voice stream, and when a known line starts it hands the English to
the game's own dialogue box (the same routine that draws the script), so
subtitles look and behave like the rest of the game's text. In voiced
scenes the game draws the characters' portraits in that same box, so the
payload also moves them: only the speaker's portrait stays, at the left,
and the subtitle sits beside it. Cue timings come from speech recognition
over the extracted Japanese audio, then checked by hand.

**Graphics.** The memo pages, the New Game disclaimer, the credit roll, the
keyboard, the opening's title cards and the intro movie's burned-in text
are all baked images. Each lives in Konami's own compression format, which
was decoded and re-encoded so the pictures could be redrawn in English and
put back at the same size.

**Disc.** The patched files are written back at their original positions;
anything that grew is appended past the end of the original image, with
fresh sector headers and error correction, so the result is a valid disc
that boots on real hardware.

### Saturn

The Saturn port reuses the PlayStation translation and its tools, on a
different engine. The script sits in the same scene banks as on the
PlayStation, inside one data file of 639 compressed chunks; the build
rebuilds that file from the chunk list and writes a new disc image, whose
data track grows to hold the longer English. The executable is patched
with small SH-2 routines placed in unused space: long lines are appended
to each scene's text and remapped at runtime, a line too long for the box
pages instead of scrolling, the font is extended in video RAM for the
two-letter glyphs, and a subtitle payload stored with each scene draws the
voice subtitles and moves the speaker's portrait to the left, the same
design as the PlayStation's. The keyboard, the memo pages, the diary, the
opening's captions and credit roll, and the option menu's WALLPAPERS
screen are redrawn in the game's own formats.

## About me

I'm an aerospace software engineer. I lived in Japan for four years and in
Germany for five, and I'm now based in Brazil. This is a hobby project and
is still a work in progress.

## Changelog

- Saturn: [CHANGELOG-Saturn.md](CHANGELOG-Saturn.md)
- PlayStation: [CHANGELOG.md](CHANGELOG.md)

Older releases: <https://github.com/pepasjc/snatcher-translated/releases>.

## Reporting bugs

Open an issue at <https://github.com/pepasjc/snatcher-translated/issues>.
Please include the scene or location, what was on screen (a screenshot
helps), and a save (memory card or Saturn backup memory) if you can. Text
that overflows its box, a subtitle that lags or leads its voice or names
the wrong speaker, or any freeze: all wanted. Load the game from a save,
not a save state made on an earlier version: a save state carries the old
version's text and glyphs and shows the old bugs.

Downloads: <https://github.com/pepasjc/snatcher-translated/releases>.

## Credits

- Translation, tools and hacking: pepa
- Terminology reference: the 1994 Sega CD localization (Konami)
- English text: the X11 "fixed" fonts (public domain), and Tamzen for the
  PlayStation opening's JUNKER HQ caption
- Tools used: jPSXdec, DuckStation, Beetle PSX, Beetle Saturn,
  PCSX-Redux, faster-whisper, capstone, xdelta3, chdman

This is a fan translation. It is free, and it must not be sold or bundled
with a disc image. Snatcher is © Konami.
