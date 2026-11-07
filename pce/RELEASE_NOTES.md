# Snatcher CD-ROMantic (PC Engine CD): English Translation Patch

**Version 1.5.1**, 2026, by pepa

Snatcher is Hideo Kojima's cyberpunk adventure: in Neo Kobe City, Gillian
Seed, a detective with no memory of his past, joins the JUNKER unit to hunt
the Snatchers, machines that kill people and take their place.
*Snatcher CD-ROMantic* (Konami, 1992) is the original release, on the PC
Engine Super CD-ROM², Japan only. This patch puts it into English.

This is the first public release of the PC Engine patch. Its version
number matches the PlayStation and Saturn patches (1.5.1), which share one
translation with it: the PC Engine script is the same story with fewer
scenes, and where its Japanese differs, the English follows it.

## What is translated

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

## How to apply

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

## Compatibility

The game needs the Super System Card 3.0 BIOS (`syscard3.pce`), as the
original does. Tested in Beetle PCE (RetroArch / Mednafen) and on a
MiSTer. The patched image is plain BIN/CUE and converts to CHD with
`chdman createcd`.

## Known issues

Open on the tracker at release time (PC Engine label):

- #94: after saving, quitting and starting a New Game, the opening can
  play black under its subtitles.
- #86: the subtitles in Randam's scene at the end of Act 1 can run out of
  step with the voices.
- #78: at Gibson's house, the diary's spoken lines draw their subtitle
  under the computer screen.
- #58: at the start of Act 2 the game can freeze in the Chief's room with
  the recap's last subtitle on screen.
- In the factory ruins, Gillian's "A time bomb!" sits beside her screaming
  portrait, which is wider than the others and covers the first word.

## Changelog

### 1.5.1 (2026-11-07)

- Gaudi's entry on Napoleon names the Hundred Days' Reign, the answer to
  the videophone password (#102). It read "the Hundred Days".

### 1.5 (2026-11-07)

1.5 is the first release of the PC Engine patch. Changes since the last
test builds:

- Subtitles no longer go dark when the scene sets up a new picture under a
  line (Metal Gear's report over the Moscow map at the start of Act 3, the
  factory, the basement, Randam at the hospital).
- The previous line's words no longer flash up for a frame between two
  lines of a conversation.

## Credits

- Translation and hacking: pepa.
- Terminology reference: the 1994 Sega CD localization (Konami).
- Report bugs at <https://github.com/pepasjc/snatcher-translated/issues>
  with the scene, what was on screen and a save if possible.

This is a fan translation. It is free, and it must not be sold or bundled
with a disc image. Snatcher is © Konami.
