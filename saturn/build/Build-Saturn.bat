@echo off
rem Build the patched Saturn disc (patched\saturn\). Usage:
rem
rem   Build-Saturn.bat            the extended font layout (584 extra glyph slots
rem                               below the font in VDP1 VRAM, three exec constants)
rem   Build-Saturn.bat noext      the conservative layout (0xD000 font, the residual
rem                               Japanese frees too few slots - most text stays JP)
rem
rem Order: satapply writes DATA.BIN (banks + the repacked font chunk 0) and
rem MAIN_L.BIN (SJIS table, chunk table, loader/renderer constants) from the
rem pristine extraction; satnames puts the English speaker names into that
rem exec (the table and its pointer pool, overflow into the exec hole -
rem satexec.py); satlong appends every `long` label to its bank, relocates
rem the banks that outgrow their sectors and installs the remap stubs in the
rem exec; satkeys makes the typing keyboard Latin, seats the English name-search
rem keys (their longs + a section directory in the exec hole) and checks the
rem puzzle answers; satdisc builds track 1 from the pristine image with those two
rem files and copies tracks 2/3 and the cue beside it. satapply rebuilds
rem both files from pristine, so the tools run in this order every build.
rem satsubs puts the voice-line subtitle blobs into their banks; satpack
rem re-lays DATA.BIN densely (every LZ chunk re-encoded, chunk overrides
rem from patched\saturn\chunks\NNN.bin) and rewrites the chunk table -
rem the earlier tools assume the pristine layout, so it runs last. satwrap
rem (before satpack: the exec-hole ledger keys on the exec's sha1, which satpack
rem changes) fixes the text layout's row accounting - a row that fills the width
rem no longer doubles up with its `￥`, and a page past row 3 scrolls instead of
rem writing cells over the game context (the terminal wedge, B030 'Witch hunts').
rem satsplash writes patched\saturn\IP.BIN (the PEPA SOFT HOUSE card and the
rem Snatcher/disclaimer screen before Konami's logo, played from the IP);
rem satdisc puts it in track 1's sectors 0-15. satlabels writes its decoded
rem chunk overrides (saturn\translation\gfx_labels.json) before satpack.
setlocal
cd /d "%~dp0..\.."

set "EXT="
if /i "%~1"=="noext" set "EXT=--no-ext"

python saturn\tools\satapply.py %EXT% || pause
python saturn\tools\satnames.py apply || pause
python saturn\tools\satlong.py || pause
python saturn\tools\satkeys.py apply || pause
python saturn\tools\satkeys.py faces || pause
python saturn\subs\satsubs.py --all || pause
python saturn\tools\satwrap.py || pause
python saturn\tools\satspecial.py || pause
python saturn\tools\satoptmenu.py || pause
python saturn\tools\satpages.py apply || pause
python saturn\tools\satroll.py apply || pause
python saturn\tools\satlabels.py apply || pause
python saturn\tools\satpack.py || pause
python saturn\tools\satsplash.py apply || pause
python saturn\tools\satdisc.py || pause
