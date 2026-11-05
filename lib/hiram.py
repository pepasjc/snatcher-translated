"""Where the per-bank blobs live in RAM. One source for subs_cue, repoint and
the harness.

Two blobs per bank, read one after the other by the loader hook after the
bank itself: the subtitle payload SUBS_<S>.BIN at HIRAM (the place it has
been play-tested at since v0.5) and the long strings + their remap group in
LONGS_<S>.BIN at LONGS.

LONGS was 0x801D1000 from the RAM census of 2026-09-18 (five runs incl.
New Game, the basement, Act 3) until #95: B220's Tube Liner tunnel picture
writes 0x801A6804..0x801D9989, over the whole of LONGS_B220, and the remap
stub then read a garbage group count and handed out wild pointers (an empty
line on Beetle, a freeze on stricter hardware). The 2026-10-13 census
(scripted.py RAMTOUCH=30 over every regress.py key + the tunnel,
ps1/harness/ramfree.py) leaves 0x801E0774..0x801EC004 untouched: New Game
writes 0x801E0000..0x801E0773 and 0x801EC004..0x801EE377. LONGS starts on
the next 4 KB boundary and ends below the engine bytes at 0x801EC004; the
largest blob (B030) is 30 KB of the 44. Not covered by either census: the
MX1 mid-game movies and B230/B240 past their fights.
"""
HIRAM = 0x801F0000           # subtitle payload, 64K-aligned (lui only)
HIRAM_MAX = 0xC000           # 48 KB; SCRATCH/DISPATCH/rings/RESIDENT from 0x801FC000, stack page 0x801FF000
LONGS = 0x801E1000           # long strings + remap group (was 0x801D1000: #95)
LONGS_MAX = 0xB000           # 44 KB, up to 0x801EC000
