# Snatcher (Sega Saturn): English Translation Patch

**Version 1.5**, 2026, by pepa

Snatcher is Hideo Kojima's cyberpunk adventure: in Neo Kobe City, Gillian
Seed, a detective with no memory of his past, joins the JUNKER unit to hunt
the Snatchers, machines that kill people and take their place. Konami
released the Saturn version (T-9508G, 1996) in Japan only, with voice
acting throughout. This patch puts all of it into English. The Saturn
version is the definitive edition: it shows the pictures the PlayStation
port greys out or mosaics, and its scene pictures are at their full width
(240 pixels, where the PlayStation port drops columns to fit 192). Like
the PlayStation, it reworks the scene of the dog falling from the window. The PlayStation
patch came first, and the two share one translation.

Version 1.5 fixes a freeze on Jamie's answering machine, two subtitle
problems and a memory conflict behind garbled text late in the game, and
redraws in English the small labels left in pictures (see the changelog).
If you are playing an earlier version, patch your original tracks again;
your saves carry over.

## What is translated

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

## How to apply

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

- `Snatcher (Japan) (Track 1) [T-En by pepa v1.5].xdelta`
- `Snatcher (Japan) (Track 2) [T-En by pepa v1.5].xdelta`

The easy way: put your three original track files in the folder you
unzipped and run `apply.bat` (Windows, double-click) or `apply.sh` (Linux
and macOS: `sh apply.sh`). It checks your dump, applies both patches and
checks the results. The Windows script downloads xdelta3 by itself if it
is missing; on Linux and macOS install it first (`apt install xdelta3`,
`brew install xdelta`).

By hand:

```
xdelta3 -d -s "Snatcher (Japan) (Track 1).bin" "Snatcher (Japan) (Track 1) [T-En by pepa v1.5].xdelta" "Snatcher (Japan) [T-En by pepa v1.5] (Track 1).bin"
xdelta3 -d -s "Snatcher (Japan) (Track 2).bin" "Snatcher (Japan) (Track 2) [T-En by pepa v1.5].xdelta" "Snatcher (Japan) [T-En by pepa v1.5] (Track 2).bin"
```

Delta Patcher (Windows) or MultiPatch (macOS) do the same with a window.
Put `Snatcher (Japan) [T-En by pepa v1.5].cue` from the zip next to the two
new files and your original `Snatcher (Japan) (Track 3).bin`, and load the
.cue. The new track 1 is larger than the original; that is expected. The
results should hash:

```
Snatcher (Japan) [T-En by pepa v1.5] (Track 1).bin
Size   479709216
CRC32  6071e290
MD5    f5a2c950294b4608ccb7e34d8f16ff95
SHA1   9124fc2a7277f712fa532fe8b1f4750aecd0afc8

Snatcher (Japan) [T-En by pepa v1.5] (Track 2).bin
Size   58576560
CRC32  4ddc9b55
MD5    28ed4cbbb658d448ac8e5aa38e106a6e
SHA1   a7c4e8b4825092324fe3429b85ee4496f73d1654
```

## Compatibility

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

## Changelog

See <https://github.com/pepasjc/snatcher-translated/blob/main/CHANGELOG-Saturn.md>.
The script is shared with the PlayStation translation, whose full history
is at <https://github.com/pepasjc/snatcher-translated/blob/main/CHANGELOG.md>.

## Credits

- Translation and hacking: pepa.
- Terminology reference: the 1994 Sega CD localization (Konami).
- English text is drawn in the X11 "fixed" 7x13 font (public domain).
- Report bugs at <https://github.com/pepasjc/snatcher-translated/issues>
  with the scene, what was on screen and a save if possible.

This is a fan translation. It is free, and it must not be sold or bundled
with a disc image. Snatcher is © Konami.
