# Snatcher (PlayStation) — English Translation Patch

**Version 0.8** — 2026-09-10 — by pepa

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

### 0.8 — 2026-09-10

- **Two patches: translation only, or translation plus uncensored art.**
  The plain patch leaves Konami's artwork exactly as it shipped on the
  Japanese PlayStation disc. The `(Uncensored)` patch is the one earlier
  releases were: the PlayStation port greys out the corpse in the factory
  ruins and puts a mosaic over the maggot-covered body in the hospital,
  where the Saturn and PC Engine versions do neither — and both uncensored
  pictures were left on the PS1 disc, unused. That patch loads those
  instead, and restores the female Snatcher's body. Nothing is redrawn or
  added, and the translation is identical in both. Saves work across the
  two, so you can switch by re-patching.
- **The Act 2 videophone had no subtitles at all** (GitHub issues #17,
  #16). Calling Jamie when she is not home plays her recorded message;
  calling the Kobe Pharmaceuticals lab, Napoleon, the Chief or a wrong
  number all answer with a voice. None of it was subtitled - the Act 2
  videophone scene carried no subtitle data whatsoever. Every call there
  is now carded, including the lab's greeting after Jamie's tape.
- **The dialogue frame vanished after the emergency call from HQ**
  (GitHub issue #18). In Act 2, getting into the tricycle after the
  hospital brings a call from HQ; once it ended, the destination list and
  the text that followed drew with no panel behind them.
- "Gibson hm" in the Act 2 travel menu is now "Gibson's", with the full
  "Gibson's home" where there is room for it.
- **A menu could open on top of a subtitle** (GitHub issue #3): after the
  Lisa fight, the verb menu drew over "Is it really dead?", and in the Act 2
  debrief a panel edge sat across the text.
- **The first two and a half minutes of Act 2 had no subtitles.** Arriving
  at HQ, Metal replays his Act 1 report to the Chief - the montage, the two
  suspects, Lisa, Gibson's ulcer - and none of it was subtitled; text only
  appeared once the new montage began. The game replays a recording it also
  uses in Act 1, and the subtitles for it only existed in the Act 1 scene.
- **Text no longer breaks in the middle of a word** (GitHub issue #14).
  The game filled each row to a fixed number of characters and cut there,
  wherever that fell, so lines split as `Euras / ian` and a row one
  character too long dropped its last word onto the next line. The game
  now breaks rows at a space, and every line of Gaudi's database and
  person files was re-broken for that terminal's narrower window.
- **Ivan Rodriguez's door: five spoken lines had no subtitles.** After the
  disarming shot, Gillian and Metal's exchange over the unconscious Ivan —
  and Ivan's own plea — played over an empty box.
- **The dialogue frame could stay stuck 80 px low** for the rest of a
  scene (GitHub issue #15). Re-entering Freddy Nielsen's room, the game's
  own text arrived while a subtitle was still closing, and the box never
  came back to where it belonged.
- One subtitle in Freddy's apartment was spoken by Metal but labelled
  Gillian.

Earlier versions: <https://github.com/pepasjc/snatcher-translated/releases>
## Known issues (v0.8)

- The videophone's NOT IN SERVICE card and the dossier panels are still
  Japanese (baked images, later release).
- The `MX1_*` in-game movies are not yet subtitled.
- In the culture room the dialogue panel sits about 20 px below the text.
- One subtitle in the final act (B250) is clipped on a cold open.
- In rooms where three faces share the band, a speaker's portrait can sit
  over his own subtitle (Metal in the Mechanic room).
- The scrap of paper found on Gibson's body is a baked image and still
  reads Japanese; the dialogue under it is English.
- Six voiced lines still have no subtitles (GitHub issue #16). Three are in
  scenes we can reach and will be written for the next release; three are
  audio no playthrough has ever triggered, and may not be used by the game
  at all. If you hear one, please say where.

Not bugs: shootouts need **SELECT** to draw the Blaster — this is the
game's own control scheme.

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

- `Snatcher (Japan) [T-En by pepa v0.8].xdelta` — the translation, with
  the game's artwork untouched.
- `Snatcher (Japan) [T-En by pepa v0.8] (Uncensored).xdelta` — the same
  translation, with the PlayStation-only censorship undone.

Apply it with xdelta3, Delta Patcher (Windows), MultiPatch (macOS) or any
xdelta front-end:

```
xdelta3 -d -s "Snatcher (Japan).bin" "Snatcher (Japan) [T-En by pepa v0.8].xdelta" "Snatcher (Japan) [T-En by pepa v0.8].bin"
```

or

```
xdelta3 -d -s "Snatcher (Japan).bin" "Snatcher (Japan) [T-En by pepa v0.8] (Uncensored).xdelta" "Snatcher (Japan) [T-En by pepa v0.8] (Uncensored).bin"
```

Put the `.cue` of the same name next to the output `.bin`. The patched
image is larger than the original (relocated data is appended past the
original end); that is expected. Expected results:

```
Snatcher (Japan) [T-En by pepa v0.8].bin
Size   575127504
CRC32  b93d7f64
MD5    c0bcc82c66e7c215148c1abdf5687fa5
SHA1   0fb458ebf08ae3127bf4b2296e77f85f228649a2
```

```
Snatcher (Japan) [T-En by pepa v0.8] (Uncensored).bin
Size   575127504
CRC32  9890a66e
MD5    2f53eaa0aa604982fafa46aa074a7a75
SHA1   076dca1436372f7647a67a1705e92bc0b0949adf
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
