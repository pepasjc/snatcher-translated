# Changelog (Sega Saturn)

## 1.5.1 (2026-11-07)

- Gaudi's entry on Napoleon names the Hundred Days' Reign, the answer to
  the videophone password (#102). It read "the Hundred Days".

## 1.5 (2026-11-07)

Released together with the first PC Engine CD patch; all three ports now
share one version number and one source tree.

- Redrew in English the small Japanese labels in pictures: the
  videophone's "Number not in use" and "No video signal" cards (Konami's
  "AVALABLE" spelling fixed), Gibson's note, the JUNKER poster at the
  reception and the joke phone-book pictures.
- Fixed a freeze on Jamie's answering machine when the next card opened
  while a subtitle box was still closing (#98).
- Fixed Gillian's last line after the fortune teller opening an empty
  subtitle box (#97).
- Fixed the Act 2 recap's narration drawing beside an empty portrait
  window; the Chief's portrait stays up while he reads the report (#101).
- Re-cut the voice subtitles: every row fills before the text wraps, and
  each card holds whole sentences (a card no longer ends with the first
  words of the next sentence; a sentence too long for one card breaks at a
  comma or a phrase).
- Added subtitles to three voiced moments that had none: the Chief's
  scolding in his office after a binge at Outer Heaven, Gillian's "A time
  bomb!" in the factory ruins and her "Ow!" late in Act 1.
- Very short voice lines ("What?!", "Snow?") keep their subtitle up long
  enough to read instead of flashing for a fraction of a second.
- Metal Gear's hair and skin analyses, Jamie's call about Queen Hospital and
  the opening's profile of Gillian read as sentences ("2. The hair is brown,
  with a hair index of 65.", "Gillian Seed. He's estimated to be 31.")
  instead of form labels ("Hair color: brown.").
- Changed where long dialogue lines are loaded: they now take a buffer
  from the game's own memory allocator instead of a fixed address the
  game could also use (#88).
- Script: Catherine is fourteen, not "turning fourteen this year" (#100);
  Gibson's memo page describes the Snatchers' vampire-like habits; the
  caption at Jean's house reads "This is Jean's house."

<details>
<summary><b>Story spoilers</b> (2 entries)</summary>

- Metal Gear calls himself Metal Gear Saturn in the ending, as the voice
  says (was "Metal Gear PS") (#96).
- The bounty hunter passage of the Act 1 recap is the report's narration
  throughout.

</details>

## 1.0.1 (2026-10-01)

- Fixed a softlock after Metal Gear's introduction at JUNKER HQ. Harry's
  last subtitle ("But this one was developed for peaceful use.") stayed
  on screen over the verb menu, so the game looked stuck on that line
  while it went on underneath. When the game writes its own text into an
  open subtitle box, the subtitle code now gives the box back to it.
  Saves from 1.0 work in 1.0.1.

## 1.0 (2026-09-30)

First release.

- Translated the complete script, the menus, the keyboard and typed
  puzzles, and the in-game graphics (memo pages, Gibson's diary, the
  disclaimer, the opening's captions and credit roll). Same translation
  as PlayStation 1.0; lines that differ in the Saturn's Japanese follow
  the Saturn.
- Added subtitles for the voice acting, with the speaker's portrait on
  the left and the name in the speaker's colour; full-width text when no
  portrait is on screen.
- Modified the text engine to read long lines appended to each scene's
  text region, remapped through a pointer table by SH-2 stubs, so line
  length is not limited by the Japanese string slots.
- Replaced the engine's row-4 scroll with paging: a line longer than the
  text box waits for a button press and continues on a clean box, name
  plate kept.
- Added a WALLPAPERS item to the OPTION MENU: ten backgrounds (ACT 1,
  ACT 2, ACT 3, TWINBEE, KONAMI, TOKIMEKI, ENDING, GRADIUS, TURBOCAR,
  BLACK) with a live preview, kept for the whole game.
- Added boot screens: a translation card and a disclaimer before the
  Konami logo.
