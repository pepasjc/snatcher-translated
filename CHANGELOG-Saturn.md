# Changelog (Sega Saturn)

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
