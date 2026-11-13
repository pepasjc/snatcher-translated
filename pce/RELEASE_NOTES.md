# Snatcher CD-ROMantic (PC Engine CD): English Translation Patch

**Version 1.5.3**, 2026, by pepa

Snatcher is Hideo Kojima's cyberpunk adventure: in Neo Kobe City, Gillian
Seed, a detective with no memory of his past, joins the JUNKER unit to hunt
the Snatchers, machines that kill people and take their place.
*Snatcher CD-ROMantic* (Konami, 1992) is the CD-ROM remake of the 1988
original and the first version with the whole story to its end, on the PC
Engine Super CD-ROM², Japan only. This patch puts it into English.

1.5.2 and 1.5.3 fix eight bugs players reported in the first release.
The PlayStation and Saturn patches stay at 1.5.1; all three share one
translation: the PC Engine script is the same story with fewer
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
xdelta3 -d -B 1073741824 -s "Snatcher CD-ROMantic (Japan).bin" "Snatcher CD-ROMantic (Japan) [T-En by pepa v1.5.3].xdelta" "Snatcher CD-ROMantic (Japan) [T-En by pepa v1.5.3].bin"
```

(On Linux and macOS, `cat "Snatcher CD-ROMantic (Japan) (Track "*").bin >
"Snatcher CD-ROMantic (Japan).bin"` joins the tracks.) Put `Snatcher
CD-ROMantic (Japan) [T-En by pepa v1.5.3].cue` from the zip next to the new
file and load the .cue. Track 2 is longer than the original, so the cue's
track times differ from the redump cue; use the one in the zip. The
result should hash:

```
Snatcher CD-ROMantic (Japan) [T-En by pepa v1.5.3].bin
Size   634386144
CRC32  bdb43c63
MD5    bcb315c1fc4f1f64fe0def19bdb2ab67
SHA1   d5b9a7698543eb465693bb7d73574cf92ee74f1f
```

## Compatibility

The game needs the Super System Card 3.0 BIOS (`syscard3.pce`), as the
original does. Tested in Beetle PCE (RetroArch / Mednafen) and on a
MiSTer. The patched image is plain BIN/CUE and converts to CHD with
`chdman createcd`.

## Known issues

Open on the tracker at release time (PC Engine label):

- #86: the subtitles in Randam's scene at the end of Act 1 can run out of
  step with the voices.
- In about nine lines of the ending, Dr. Madnar's portrait on the right
  covers the last words of a long subtitle row.
- In the factory ruins, Gillian's "A time bomb!" sits beside her screaming
  portrait, which is wider than the others and covers the first word.

## Changelog

### 1.5.3 (2026-11-13)

- The ending's voiced lines are white and readable again, with the
  portraits out of the way; the second row no longer turns red and Metal
  Gear's face no longer scrambles (#112).
- In Catherine's bathroom the pictures of Gillian crouching and of her
  scream no longer show stray tiles or go missing under the subtitles
  (#113).

### 1.5.2 (2026-11-09)

- Pressing START to skip the opening no longer freezes the game on a
  black screen (#108).
- The Act 2 opening no longer freezes on the Outer Heaven picture when the
  music changes, or on the Chief's room after the recap (#109, #58). This
  showed on Mesen.
- After the Act 2 visit to JUNKER HQ, the item close-ups (the Hospital
  Oleen sign, the chess piece) draw whole again instead of as scrambled
  tiles or a black hole (#106).
- Chin Shu Ho's mugshot after the QUEEN deduction is whole again (#107).
- Gillian's bowed head at the end of the Neo Kobe-yaki scene no longer
  shows a black hole where his mouth was (#110).
- Every line of the video scene inside Joy Division has its subtitle, with
  Gillian's portrait beside his lines (#111).

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
