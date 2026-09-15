# Changelog

## 0.9.1 — 2026-09-15

### Game changes

- The OPTION MENU has a fifth item, SPECIAL OPTIONS, that opens the
  hidden SPECIAL MENU (wall paper per act, cursor colour, target pointer)
  - the Konami code is no longer needed (#30); START on the OPTION MENU
  opens it too. The Sega CD's plain black background is WALL PAPER ->
  POE BLACK.
- The tricycle's verbs read "Board Tricycle" and "Exit Tricycle" (were
  "Get in" / "Get out"), after the Sega CD's ENTER/EXIT TURBOCYCLE (#34);
  "Board" so that the door beside it, "Go inside" (was "Enter"), reads
  apart from it.
- The "Check" verb is "Investigate", the Sega CD's name for it.
- A sweep over every menu label (verbs, Look and Investigate targets,
  Ask topics, the videophone lists): some 400 labels that had been cut
  short to fit the Japanese footprint are spelled out (Receptionist,
  Right hand, Time bomb, Shooting range, Practice booth, Under near
  desk / Under far desk / Behind terminal where a list showed "Under"
  and "Behind" twice, Outline 1-6 in the montage, About Alice / About
  Ivan for every "On X", Harry's location for a topic that read as his
  name, Continue / Quit game after a save), and a few were wrong: the
  pet shop's "Oume" is a parrot, Jamie's date list has the VR Aquarium,
  her "Mind" topic is Memory, the "Chessmen" are a chessboard, the
  JUNKER files' "City founding" is the unit's founding history, the
  ruins' "People" is the man on the ground, and a lone "Back" that meant
  the far desk or the back of the room says so.

### Script fixes

- The dash the English leaned on ("Oh, right - that's what you're here
  for", "Plain paper--Jean's handwriting") is gone: 162 subtitle cards
  and 259 bank strings re-punctuated with commas and full stops, where
  the Japanese has a pause or a new sentence. A card that continues on
  the next one no longer ends in a dash.
- A plain-English pass over every scene (some 840 bank strings and 76
  subtitle cards): stiff or bookish lines now read the way people talk
  ("Hence the marksmanship" is "So you need good aim", "Function has
  wholly ceased" is "Completely shut down", "your file says you're an
  amnesiac" is "your file says you suffer from amnesia"), with the
  Japanese meaning kept as it was. Gaudi's database entries and the
  person file keep their reference tone.
- The Chief on the Snatchers: "Nobody knows where they're from or what
  they want" (was a fragment, "Where they come from, what they want:
  unknown").

### Bug fixes

- Two of Metal Gear's replies at the Neo Kobe-yaki stand (the street
  after meeting Napoleon) had no subtitle: his portrait sat alone in the
  box with no text. Both are carded now, and Gillian's reply to the
  cook (#39).
- The fortune teller's portrait shows beside her lines, at Altamira and
  on the Christmas visit (#36).
- Metal Gear's portrait animates again beside his lines: the light, the
  head turns. A still of him was being drawn over the animation (#37).
- Gillian's sneeze in the factory ruins no longer blinks: a face the
  game shows on its own, with no subtitle up, stays where the game puts
  it (#38).
- A subtitle whose speaker's portrait was a few frames from appearing
  was drawn first in the old layout (nameplate, full-width text) and
  redrawn beside the portrait when it came - a brief flash of the old
  look, seen in several places on real hardware. The card now waits for
  the portrait (#40).
- The typed-answer field on the videophone (Napoleon's password) sits
  inside the TV picture again: the English field has eight letter boxes
  where the Japanese had four, and it grew to the right over the keypad.
  It now keeps the original's centre, with the boxes a little closer
  together; the hospital-list and cipher fields are centred the same way
  (#35).

## 0.9 — 2026-09-13

Entries that quote or describe later parts of the story are folded away
under **Story spoilers** in each section - click to open them.

### Script fixes

- The tricycle's destination list says "Factory ruins" (was "Ruins").
- The tricycle's destination list says "Gillian's home" (was "Home") in
  every act.
- Gillian's home: the Look target is "Building" (was "Home" - the
  Japanese is the building, not the home).
- The phone book's answer is "Homemade" (was "Home" - a
  mistranslation).
- The verb "Do something" everywhere the menu had "Do" or "Act".
- "A still photo hidden in the Chief's room" (was "the Chief's rm") in
  the five places the item is described.
- "Gibson's living room" in Act 3 (was "Gibson's living rm.").
- "Imagine" (was "Muse") on Randam's motorcycle.
- "Forward" in the tube liner (was "Fwd.").
- The Act 3 debrief's answers read "UV rays", "Gamma rays", "Life line",
  "Loop line" and "Pollen" (were "UV ray", "Gamma", "Life", "Loop",
  "Poln").
- "Snatch process" in the culture room (was "Snatch proc").
- "Disaster" (was "Ruin") in Gaudi's database and the phone book.
- Gaudi's database: the entry header "Uncontrolled Zones" is
  "Uncensored areas", matching the menu label that opens it.
- The subtitles name the robot "Metal Gear", as the game's own nameplate
  does (was "Metal").
- Several subtitles in Act 2 and Act 3 re-read from the audio and
  reworded, and three cards that the voice does not say removed - the
  lines are quoted below.

<details>
<summary><b>Story spoilers</b> (Act 2 and Act 3) - 10 entries</summary>

- Harry's death, re-read from the audio: "Ah... Gillian, is it. I've
  grown old, too. What a state I'm in!" (was "I've gone and got old.
  Look at the state of me!").
- Harry's death: Gillian's "Old man..." is its own line before Harry's
  "I like you. I can't put it well, but..." (the two were one card
  under Harry's name).
- Harry's death: "Let's have a drink of Napoleon together again" (was
  "Let's play Napoleon again together" - Napoleon is the brandy the
  game's own text names, not a game).
- Harry's death: "Now... you're the last JUNKER..." (was "So... the last
  round...").
- Harry's death: Mika's "Harry! Harry!" (was "Rock... paper..." - a
  transcription artefact; there is no rock-paper-scissors in the scene).
- Harry's death: the unintelligible fragment carded as "Napoleon..."
  before "Gillian." is gone; the card reads "Gillian...".
- Mika at the sealed HQ: "No! Don't come! It's a trap, Gillian!" (the
  card had only "Gillian!").
- The morgue: "The Snatchers pick out the originals they'll snatch at
  places like Outer Heaven, and kill them" (was "The Snatchers play the
  part of the originals they target, in places like Outer Heaven",
  shown three times over).
- The basement: "Go! Die!" is one two-second card (was "Go!" for a
  fifth of a second and "Die." held over eleven seconds of music).
- The sealed HQ: two cards that read "I swore it to Randam. There are
  still Snatchers in this city." are gone - the transcription had looped
  back over earlier speech; the voice does not say them.

</details>

### Bug fixes

- **The last scenes of the game had no subtitles.** From the door of the
  last room of Act 3 to the escape, nothing was subtitled: the cards
  existed but were filed under the scene before it, which had already
  ended.
- **The ending had never been subtitled**: the scene after the escape,
  28 lines, written for this release.
- **The hospital basement had no subtitles from the face reconstruction
  on** - Metal Gear rebuilding the four faces and everything after it
  played without text.
- The basement: Metal's "We did it! Door 3 has opened!" after the two
  switches are pressed together had no subtitle (#25).
- The morgue: Gillian's "Good God..." at the sight of the bodies had no
  subtitle (#28).
- The news bulletin under the Act 3 title card (the Kyoto summit twelve
  hours away, the calls to quarantine Neo Kobe) had no subtitle (#16).
- The tube liner: Metal's explanation of the abandoned subway lines
  ("Ah, why didn't I realise it sooner?...") had no subtitle (#16).
- The ride on Randam's motorcycle after the sabotaged tricycle had no
  subtitles (#21).
- Oleen Hospital: the woman behind the blind glass ("Eeek! Pervert!",
  "Get out of here, now!") had no subtitles.
- The factory ruins: Metal's "Jean!!" after the scream had no subtitle.
- **Gaudi's topic lists no longer break their entries across rows**
  (#31): "Uncensored areas", "Back to menu", "Scanning warrant" and
  every other right-column entry with a space had their last word pushed
  onto the next row, in front of that row's entry.
- **No more gaps inside words** ("hand ke rchief", "cros sr oad", "need
  s"): every letter pair the text uses now has its own glyph; the 241
  rarest pairs were drawn as two wide letters.
- **Subtitles no longer end a row on a detached letter** ("So Queen
  Hospital an d the tube liner wer e connected"): a letter left alone at
  the end of a row was drawn as a wide, centred glyph.
- A subtitle whose row filled the box exactly left an empty row under
  it, pushing the rest of the text down or out of the box.
- JUNKER HQ, Act 1: "There's a call from Jean Jack Gibson. Putting him
  through" is Metal Gear's, not Mika's, and "Gillian! We have a case!
  Get to the scene!" is Harry's, not the Chief's.
- **The wrong character was named on some thirty more subtitles** in
  the morgue, the basement, the Act 3 debrief and the last scenes - each
  is listed below.
- **Subtitles that came up before the voice, or flashed by unreadably**:
  one in the sealed HQ came up four seconds early, one of Metal's
  sentences in the morgue was carded three times in a row, a 0.7-s
  repeat in the Act 3 debrief - listed below.
- **A long subtitle near the end was clipped to a few characters per
  row** for its whole duration (#4). A card that started during the
  switch from the portrait layout to the plain box inherited a cropped
  text area; it is redrawn in full now.
- **A dropped instruction-cache flush after every scene load.** The
  subtitle code is loaded fresh with each scene and the processor could
  keep running the previous scene's copy; on real hardware that is a
  possible cause of the rare freezes and of the bare menu after the
  two-switch conversation (#20, #26). The PSIO freeze in Gibson's house
  happens on the unpatched game too and is not the patch's.

<details>
<summary><b>Story spoilers</b> (Act 2 and Act 3) - 20 entries</summary>

- The last room of Act 3: from the church door - Gillian finds Jamie -
  through Jamie's memory, Madnar's confession, Metal Gear's countdown and
  the escape from the Kremlin, none of it was subtitled (the entry
  above).
- The ending: the airport farewell - the flight announcement, Jamie and
  Gillian's goodbye, Metal Gear's stopgap body, "Get aboard, quick,
  partner" - had never been written.
- The basement: the Chief's arrival, Chin Shu Ho's reveal and the fight
  had no subtitles (the face-reconstruction entry above).
- The basement: Gillian's "Th-the Chief!" had no subtitle.
- The morgue: the taxi-driver deduction ("And the one who linked Outer
  Heaven to the Snatchers was the taxi driver, Freddy..."), "to hide a
  needle, a pincushion; to hide a body, a morgue" and "if we identify
  these four bodies..." are Randam's, not Gillian's - ten cards named
  the wrong speaker (#28).
- The basement: "The buttons are so far apart that one person can't
  press both at once" is Gillian's, not Metal's.
- The basement: "By the look of it, this seems to be a very important
  room" is Randam's, not Metal's.
- The basement: "This is the director of this very hospital, Queen
  Hospital" is Randam's, not Metal's.
- The basement: "That's the freshest one. There's still skin on it" is
  Gillian's, not Randam's.
- The basement: "Wh-what?!" at the reveal is Randam's, not Gillian's.
- The basement: "That's far enough, JUNKER! Let's put an end to the
  detective games!" is Chin Shu Ho's, not the Chief's - and Chin now has
  his portrait on his lines.
- The Act 3 debrief: "You two are the only witnesses" is Mika's, not
  Metal's.
- The Act 3 debrief: "We have to find the Snatchers' hideout, fast!" is
  Metal's, not Gillian's.
- The Act 3 debrief: "The time limit is twelve hours" is Gillian's, not
  Metal's.
- The Kremlin: "That was the Snatcher Project. Secretly replace enemy
  VIPs with puppets of the Kremlin..." is Gillian's, not Jamie's.
- The Kremlin: "Elijah Madnar - that man in the ruined chapel, the one
  who looked like Randam" is Gillian's, not Jamie's.
- The Kremlin: "What a terrible thing to do..." is Gillian's, not
  Jamie's.
- Mika's "Harry! Why?..." at the sealed HQ came up four seconds before
  she spoke, as a plain card, and was redrawn with her face when the
  voice started. It comes up on the voice.
- The morgue: one of Metal's sentences was carded three times in a row,
  the repeats a fraction of a second long and unreadable; the Act 3
  debrief had a 0.7-s repeat of the card before it, now merged into it.
- The Kremlin: the clipped card was Metal's "For a radius of several
  kilometres around me, nothing will remain" (#4).

</details>

### Game changes

- **The speaker's portrait stays on screen, and the subtitle sits beside
  it.** In voiced scenes the game draws the characters' portraits inside
  the dialogue box - the same place the subtitles have to go - so earlier
  releases hid the portraits (GitHub #8, #23). Now only the person
  speaking is shown, at the left of the box, with the subtitle beside
  them.
- The speaker's name is dropped from a card that shows the speaker's
  face, since the face says who talks. Where the speaker has no portrait
  in that room the card keeps the name and the full width of the box.
- The portrait leaves with its line, and the text goes with it: a card
  no longer stays behind alone after its speaker's face slides away.
- Portraits now cover every character the game has one for.
- **Longer subtitle cards.** A spoken line now shares one card wherever
  it fits the box, and a line too long for one card is cut at the end of
  a sentence or a clause, never after the last word that happened to fit
  ("For that too, we mustn't let the Chief reach the summit" / "venue."
  was the kind of cut it replaces). Each card still comes up on its own
  part of the voice.
- **The opening narration is easier to read** (#19): the band under the
  text is darker, so the diagram boards no longer show through it, and
  the text no longer sits across their scrolling readouts.
- The opening: the card that straddles the Snatcher diagram is split in
  two, so the band no longer covers the diagram's own caption.

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
