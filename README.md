# Snatcher (PlayStation) — English Translation Patch

**Version 0.7.1** — 2026-09-09 — by pepa

Snatcher was released for the PlayStation in Japan only (SLPS-00154, Konami,
1996). This patch translates it into English. The PS1 port carries the
Sega CD's extra scenes and the uncensored script, and this is the first time
it has been playable in English.

## What is translated

- **The complete script** — all 39 scene banks, New Game to the ending
  (12,004 strings). Every menu, verb, item and location label.
- **Voice subtitles** — 1,042 of the 1,130 spoken lines are subtitled,
  drawn in the game's own dialogue box, timed to the voice. The remainder
  are jingles, sound effects and duplicated lines. The opening narration
  and newsreel are subtitled too.
- **The keyboard and every typed puzzle** — Latin key faces, Latin input;
  the name search, the passwords and the videophone all work in English.
- **Graphics** — the memo pages, the New Game disclaimer, the credit roll,
  the opening's title cards and the Snatcher diagram, the intro movie's
  burned-in captions and credits, and a translation card in the Konami
  boot movie.
- **Names** follow the Japanese original, so the subtitles match what
  the voice actors say: Randam Hajile, Dr. Madnar, Catherine Gibson,
  Gaudi. The Sega CD script was used as terminology and tone guidance;
  the PS1 text has extra scenes and different line breaks, so it was
  translated fresh rather than copied.
- **Uncensored** Konami shipped this port with pictures toned down:
  Gibson's body at the factory ruins, the maggot-covered skull under
  Queen Hospital, and Lisa's body at Freddy's flat.
  This patch removes the the censorship in those scenes using original
  assets that were already existing in the disc but unused, Lisa's body
  that was manually repainted based on the PC Engine.

## Known issues

- The videophone's NOT IN SERVICE card and the dossier panels are still
  Japanese (baked images, later release).
- The `MX1_*` in-game movies are not yet subtitled.
- In a couple of rooms (B120/B140) a menu can open on top of a subtitle.
- In the culture room the dialogue panel sits about 20 px below the text.
- One subtitle in the final act (B250) is clipped on a cold open.

## How to apply

You need your own dump of *Snatcher (Japan)* in BIN/CUE form, matching the
redump.org entry:

```
Size   573702192
CRC32  d5475fac
MD5    b6b825a8c91fd9879553c8a4e6e791c8
SHA1   e6cd330feb594b3951089da866db1a400f0173f6
```

Apply the `.xdelta` with xdelta3, Delta Patcher (Windows), MultiPatch
(macOS) or any xdelta front-end:

```
xdelta3 -d -s "Snatcher (Japan).bin" "Snatcher (Japan) [T-En by pepa v0.7.1].xdelta" "Snatcher (Japan) [T-En by pepa v0.7.1].bin"
```

Put the included `.cue` next to the output `.bin`. The patched image is
larger than the original (relocated data is appended past the original
end); that is expected. Expected result:

```
Size   575054592
CRC32  37188822
MD5    3271ca87f06884ee135e5d9dcb0188f3
SHA1   307713d4c999deed9ca4012858390ba5ceae5102
```

Do not apply the patch to a `.iso` (2048-byte sectors) or a `.chd`;
convert those to BIN/CUE first. The patch is ~21 MB because the intro
movie's frames were re-encoded.

## Compatibility

Tested on real hardware, PS3, MiSTer, DuckStation and Beetle PSX /
Beetle PSX HW (RetroArch). The image is a plain Mode 2 BIN/CUE and
converts to CHD with `chdman createcd`. Save files from the Japanese
game are compatible.

## Reporting bugs

Open an issue at <https://github.com/pepasjc/snatcher-translated/issues>.
Please include the scene or location, what was on screen (a screenshot
helps), and a memory card save if you can. Text that overflows its box,
a subtitle that lags or leads its voice, or any freeze — all wanted.

Downloads: <https://github.com/pepasjc/snatcher-translated/releases>.

## Credits

- Translation, tools and hacking: pepa
- Terminology reference: the 1994 Sega CD localization (Konami)
- Tools used: jPSXdec, DuckStation, Beetle PSX, PCSX-Redux, faster-whisper,
  xdelta3, chdman

This is a fan translation. It is free, and it must not be sold or bundled
with a disc image. Snatcher is © Konami.
