# Changelog

## 0.8.1 — 2026-09-10

- **Re-issue of 0.8; the game is unchanged.** The 0.8 `(Uncensored)` image
  was built over a leftover image instead of a fresh copy of the original,
  which left the last sector of the relocated executable with a blank
  sector subheader. Its contents were identical and it played the same,
  but the two 0.8 images were not made the same way and a clean rebuild
  did not reproduce the published one. The build now stamps every sector
  it writes and refuses to start over an image it could not delete, so
  both patches come from fresh, identical builds. If you already applied
  0.8, there is nothing you need to do; 0.8.1 is the one to download.

## 0.8 — 2026-09-10

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

## 0.7.1 — 2026-09-09

- **PS3: 0.7 froze on the Sony logo - fixed** (GitHub issue #13). 0.7
  moved the game executable to the very last sector of the image, and the
  PS3's PlayStation emulator hangs when the drive reads ahead past the end
  of the disc; real hardware, MiSTer and the PC emulators tolerate it.
  The image now ends with the same 2-second run of empty sectors the
  original disc has after its last file.

## 0.7 — 2026-09-09

- **Nothing is abbreviated for space any more.** Earlier releases
  shortened labels to fit the original byte budgets; the remap that
  freed menu labels in 0.6 now carries everything. "Joy Division" (was
  "J. Division"), "Fortune teller", "Bounty Hunters", "Red Square",
  "Oleen Hospital", "Hospital list", "Little John's memory", "Queen
  Hospital" in the item descriptions, "Chess piece", "Chinese doctor",
  "Food stall", "Answerphone", "Bloodstain", "Time machine",
  "Volleyball", the phone book's prefectures, and every topic in Gaudi's
  database ("City founding", "Siberian Territory", "Nuclear Abolition",
  "Witch hunts", "Scanning warrant", "Nanomachines", "Retina Reading",
  "Mars Chronicles"...) - about eighty labels in all, each checked
  against the Japanese. Initials the Japanese script itself uses stay
  (the dossiers' "S. Glazer", the "JK card").
- **Gibson's body at the factory ruins is the disc's own uncensored
  picture and nothing more.** 0.6 also pasted his severed head into the
  shot the way the PC Engine frames it; that edit is gone. Only the
  PS1's grey-out is undone.
- **Outer Heaven, Act 1: the thug and the master are subtitled** when
  the JUNKER ID is shown inside (and the shooting that can follow). The
  lines had been filed under the entrance scene and never drew.
- **RetroArch (Beetle PSX / Beetle PSX HW): black screen after the Konami
  boot movie - fixed.** The translation card baked into the boot movie
  hung the BIOS memory-card check whenever a second memory card was
  present, which every RetroArch setup has; DuckStation and hardware were
  unaffected. The boot movie is now untouched: the translation card is
  drawn by code before the game starts instead of being baked into the
  movie.
- Gaudi's name search drew only the highlighted key - no keyboard, no
  input box - in any game started from New Game (GitHub issue #12). The
  opening's subtitles left part of the dialogue sprite set in a state the
  game's own start-up then skipped over. Present since 0.5; fixed.
- Outer Heaven's interior said "Use Metal" where every other place says
  "Use Metal Gear" (GitHub issue #10).

## 0.6 — 2026-09-08

- Character names now follow the Japanese original instead of the Sega CD
  localization (GitHub issue #1): **Randam Hajile** (not Random - the name
  is Madnar spelled backwards), **Dr. Madnar** (not Modnar), **Catherine
  Gibson** (not Katrina - カトリーヌ), **Gaudi** (the JUNKER computer).
  Applied everywhere: dialogue, voice subtitles, menus, the Gaudi name
  search, the memo pages, the credit rolls.
- Menu labels that never fit their slots now have room: the label
  redirection table lives inside each scene bank instead of a full 1.3 KB
  corner of the executable. "Mechanic room", "Near desk" and "About
  Catherine" read in full everywhere; "Queen Hospital" and "Door 1/2/3"
  too.
- Konami shipped this port with pictures toned down:
  Gibson's body at the factory ruins, the maggot-covered skull under
  Queen Hospital, and Lisa's body at Freddy's flat.
  This patch removes the censorship in those scenes using original
  assets that were already existing in the disc but unused, Lisa's body
  that was manually repainted based on the PC Engine.
- Jamie's videophone call in the turbocycle, after JUNKER HQ, is subtitled
  (it played without subtitles before).
- Napoleon's conversation in Outer Heaven uses the full width of the box
  instead of wrapping at ten characters; his sneeze no longer gets a card.
- Three lines that had stayed in Japanese are translated: Metal on the
  maggot-covered body and its insects, on the torn collar at Gibson's
  house, and Gillian on the rows of pods.
- A few voice lines showed a short card where a longer, complete one had
  been written (GitHub issue #9) - Ivan's scanning-warrant speech, Harry
  calling Metal Gear in. The complete cards show now.

## 0.5.2 — 2026-09-08

First round of play-test reports from the v0.5.1 build, all in Act 1:

- JUNKER HQ, Harry's drunk scene: the verb menu no longer draws over the
  last subtitle, and the last card is no longer cut short when Metal's
  face band opens.
- Gibson's house: the goodbye when leaving (Gillian's address and number,
  Katrina's farewell) is now subtitled; two lines wrongly credited to
  Katrina and Gillian are Metal's ("G-Gillian...", "What a false alarm!").
- Videophone: Napoleon's riddle prompt reads "Revolution?" instead of
  "Revolt?"; his first greeting is "Yeah? Who is it?" (was a
  mis-transcription); Jamie's date menu says "Sea" instead of "Se".
- The picture item label reads "Pic" in three rooms (B060, B080, Gillian's
  flat) — the space went to the fixes above.

## 0.5.1 — 2026-09-07

- The flight to the factory ruins (the narration over Gillian in the
  cockpit) is subtitled.

## 0.5 — 2026-09-07

- First public release.

Earlier downloads: <https://github.com/pepasjc/snatcher-translated/releases>
