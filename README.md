# Snatcher (PlayStation) — English Translation Patch

**Version 0.8.1** — 2026-09-10 — by pepa

Snatcher was released for the PlayStation in Japan only (SLPS-00154, Konami,
1996). This patch translates it into English. The PS1 port carries the
Sega CD's extra scenes and the uncensored script, and this is the first time
it has been playable in English.

## What is translated

- **The complete script** — all 39 scene banks, New Game to the ending
  (12,004 strings). Every menu, verb, item and location label.
- **Voice subtitles** — 1,047 of the 1,130 spoken lines are subtitled,
  drawn in the game's own dialogue box, timed to the voice. The remainder
  are jingles, sound effects and duplicated lines. The opening narration
  and newsreel are subtitled too.
- **The keyboard and every typed puzzle** — Latin key faces, Latin input;
  the name search, the passwords and the videophone all work in English.
- **Graphics** — the memo pages, the New Game disclaimer, the credit roll,
  the opening's title cards and the Snatcher diagram, the intro movie's
  burned-in captions and credits, and a translation card drawn before the
  game starts.
- **Names** follow the Japanese original, so the subtitles match what
  the voice actors say: Randam Hajile, Dr. Madnar, Catherine Gibson,
  Gaudi. The Sega CD script was used as terminology and tone guidance;
  the PS1 text has extra scenes and different line breaks, so it was
  translated fresh rather than copied.

## How it was translated

This is an AI-assisted translation, and an ongoing one. The first pass was
machine-translated from the **Japanese PS1 script** — not the Sega CD — and
every line is then gone over by hand: refitted to the game's byte budgets,
re-broken for the dialogue box, and corrected where the machine pass got it
wrong. The voice subtitles are timed from a speech-recognition pass over
the extracted Japanese audio and translated the same way.

I know what an AI-slop patch looks like, and I don't want this to be one.
A lot of the effort here has gone into making sure the result is not a
soulless machine translation: the English is read against the Japanese
scene by scene and rewritten wherever the first pass reads like a machine
wrote it. The Sega CD localization is a reference for terminology and tone
where the scenes overlap, not a source — see **Names** above.

This will evolve slowly. The tooling is built so that reviewing is cheap:
every scene has the Japanese text, the byte budget and the current English
side by side, a report lists every line that does not fit, a headless
harness plays a scene and photographs every subtitle, and every bug has a
save attached so it can be reached again. Reviewing a scene means sitting
down with it, not rebuilding the pipeline. Releases will keep coming as
scenes get their second and third pass.

The second pass is done in a review tool built for it: every line of a
scene on one row — speaker, the Japanese with furigana, the English, a
button that plays the voice line straight off the disc — and a correction
typed into the row wherever the machine pass got a line wrong or left it
sounding like a machine. See **[The review tool](docs/review-tool.md)**
for what it looks like and what it checks.

Corrections are welcome: open an issue with the line and the scene.

## Technical Details

Most of the work in this project is not translation. It is reverse
engineering: the game's text encoding, font, dialogue box, CD streaming and
graphics containers all had to be taken apart before a single English line
could go in. That work is done, and it is what makes the game fully
playable in English for everyone.

**Text.** The script is not Shift-JIS. Each character is a two-byte index
into the game's font, and every string is referenced by its byte offset,
so a translation has to fit inside the space the Japanese line took.
Japanese is dense — one kanji carries what takes several English letters —
so unused kanji slots in the font are redrawn to hold two Latin letters
each. Two letters then cost the same two bytes as one kanji, and English
fits at Japanese density. Menu labels too short for any English word are
appended to the end of their scene file and redirected at runtime by a
small patch in the executable.

**Extraction.** A tool walks the disc image, pulls the 39 scene files,
decodes every string with its byte budget, and writes them out as JSON.
The English goes back the same way: encoded with the new font, checked
against the budget, and patched in place. A build verifies every string,
every name and every redrawn glyph before it writes a disc.

**Subtitles.** The PS1 voices were never subtitled; the game just plays the
audio. This patch adds a small subtitle payload per scene, loaded into
spare RAM after the scene file. Every frame it reads where the CD drive is
in the voice stream, and when a known line starts it hands the English to
the game's own dialogue box — the same routine that draws the script — so
subtitles look and behave like the rest of the game's text. Cue timings
come from speech recognition over the extracted Japanese audio, then
checked by hand.

**Graphics.** The memo pages, the New Game disclaimer, the credit roll, the
keyboard, the opening's title cards and the intro movie's burned-in text
are all baked images. Each lives in Konami's own compression format, which
was decoded and re-encoded so the pictures could be redrawn in English and
put back at the same size.

**Disc.** The patched files are written back at their original positions;
anything that grew is appended past the end of the original image, with
fresh sector headers and error correction, so the result is a valid disc
that boots on real hardware.

## About me

I'm an aerospace software engineer. I lived in Japan for four years and in
Germany for five, and I'm now based in Brazil. This is a hobby project and
is still a work in progress.

## Changelog

See [CHANGELOG.md](CHANGELOG.md). Older releases:
<https://github.com/pepasjc/snatcher-translated/releases>.

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

- `Snatcher (Japan) [T-En by pepa v0.8.1].xdelta` — the translation, with
  the game's artwork untouched.
- `Snatcher (Japan) [T-En by pepa v0.8.1] (Uncensored).xdelta` — the same
  translation, with the PlayStation-only censorship undone.

Apply it with xdelta3, Delta Patcher (Windows), MultiPatch (macOS) or any
xdelta front-end:

```
xdelta3 -d -s "Snatcher (Japan).bin" "Snatcher (Japan) [T-En by pepa v0.8.1].xdelta" "Snatcher (Japan) [T-En by pepa v0.8.1].bin"
```

or

```
xdelta3 -d -s "Snatcher (Japan).bin" "Snatcher (Japan) [T-En by pepa v0.8.1] (Uncensored).xdelta" "Snatcher (Japan) [T-En by pepa v0.8.1] (Uncensored).bin"
```

Put the `.cue` of the same name next to the output `.bin`. The patched
image is larger than the original (relocated data is appended past the
original end); that is expected. Expected results:

```
Snatcher (Japan) [T-En by pepa v0.8.1].bin
Size   575127504
CRC32  1bcdba5e
MD5    8006b69296c9594592882b926d0f3aa9
SHA1   80a9c7af004c1442bd8371641ac516a41d5e3f92
```

```
Snatcher (Japan) [T-En by pepa v0.8.1] (Uncensored).bin
Size   575127504
CRC32  a7da4cad
MD5    0f624a86587e9752e01c8b042486b37b
SHA1   3c056d7ade1e10cdadd95524c7ac0caad74f2c57
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
