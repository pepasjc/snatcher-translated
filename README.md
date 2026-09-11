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
