# Snatcher (PlayStation): English Translation Patch

**Version 1.5.1**, 2026, by pepa

Snatcher is Hideo Kojima's cyberpunk adventure: in Neo Kobe City, Gillian
Seed, a detective with no memory of his past, joins the JUNKER unit to hunt
the Snatchers, machines that kill people and take their place. Konami
released the PlayStation version (SLPS-00154, 1996) in Japan only. It has
the scenes the Sega CD version added, voice acting throughout and the
uncensored script. This patch puts all of it into English.

## What is translated

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

## Changelog

See <https://github.com/pepasjc/snatcher-translated/blob/main/CHANGELOG.md>.

## How to apply

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

## Compatibility

Tested on real hardware, PS3, MiSTer, DuckStation and Beetle PSX /
Beetle PSX HW (RetroArch) and PSP. The image is a plain Mode 2 BIN/CUE and
converts to CHD with `chdman createcd`. Save files from the Japanese
game are compatible.

## Reporting bugs

Open an issue at <https://github.com/pepasjc/snatcher-translated/issues>.
Please include the scene or location, what was on screen (a screenshot
helps), and a memory card save if you can. Text that overflows its box,
a subtitle that lags or leads its voice or names the wrong speaker, or
any freeze: all wanted. Load the game from a memory card save, not a
save state made on an earlier version: a save state carries the old
version's text and glyphs and shows the old bugs.

Downloads: <https://github.com/pepasjc/snatcher-translated/releases>.

## Credits

- Translation, tools and hacking: pepa
- Terminology reference: the 1994 Sega CD localization (Konami)
- Tools used: jPSXdec, DuckStation, Beetle PSX, PCSX-Redux, faster-whisper,
  xdelta3, chdman

This is a fan translation. It is free, and it must not be sold or bundled
with a disc image. Snatcher is © Konami.
