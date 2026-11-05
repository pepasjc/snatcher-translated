set -e
# Build the patched Saturn disc, the bash twin of Build-Saturn.bat.
#   SATURN_NOEXT=1   the conservative font layout (see Build-Saturn.bat)
cd "$(dirname "$0")/../.."
EXT=""
[ "${SATURN_NOEXT:-0}" = "1" ] && EXT="--no-ext"
python saturn/tools/satapply.py $EXT
python saturn/tools/satnames.py apply      # English speaker names into the exec
python saturn/tools/satlong.py             # `long` labels appended to the banks + the remap stubs
python saturn/tools/satkeys.py apply       # Latin keyboard, the B040 name-search keys, the puzzle answers checked
python saturn/tools/satkeys.py faces       # the Latin key faces -> patched/saturn/chunks/310.bin (satpack picks it up)
python saturn/subs/satsubs.py --all    # voice-line subtitles: the payload blob in each bank, the frame-wait hook
python saturn/tools/satwrap.py             # the layout's row accounting: a full row + its `￥` is one row, a line past row 3 pages on a press (the terminal wedge)
python saturn/tools/satspecial.py          # the chosen wall paper set loaded in every room (op 0x0F stub)
python saturn/tools/satoptmenu.py          # OPTIONS > SPECIAL OPTIONS: pick + preview the wall paper set (exec stubs; chunk 60/331 overrides)
python saturn/tools/satpages.py apply      # memo pages, Gibson's diary, the New Game disclaimer -> patched/saturn/chunks/
python saturn/tools/satroll.py apply       # the opening's credit roll and JUNKER HQ caption (chunks 394, 452)
python saturn/tools/satlabels.py apply     # small Japanese labels redrawn (videophone cards, the note, the JUNKER poster, B180 phone book) -> patched/saturn/chunks/
python saturn/tools/satpack.py             # DATA.BIN re-laid densely from the chunk list (+ patched/saturn/chunks/ overrides), table rewritten
python saturn/tools/satsplash.py apply     # the two boot screens (card + Snatcher/disclaimer) played from the IP -> patched/saturn/IP.BIN
python saturn/tools/satdisc.py
