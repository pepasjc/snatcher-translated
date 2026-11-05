set -e
# Build one patched image, the bash twin of Build-Image.bat.
#   SNATCHER_CENSORED=1   translation only, game art untouched
#   SNATCHER_IMAGE=<name> write a scratch/variant image
#   SNATCHER_NO_FMV=1    skip the FMV pass (mirror it from the other variant)
# the line breaks and the colour codes of every bank string (a review pass
# accepts prose, and a reviewer drops a `＠赤` or lengthens a row) - reported,
# never fatal: the build itself keeps the Japanese for anything it cannot place
python ps1/tools/check_strings.py --all --quiet || echo "# check_strings: see above"
python ps1/tools/apply_translation.py
python ps1/tools/keytable.py apply
python ps1/tools/repoint.py
python ps1/tools/patch_keyboard.py
python ps1/tools/kbdfaces.py apply
python ps1/tools/specialmenu.py apply
python ps1/tools/specialitem.py apply
python ps1/tools/gfxpages.py apply
python ps1/tools/gfxlabels.py apply
python ps1/tools/disclaimer.py apply
python ps1/tools/staffroll.py apply
python ps1/tools/introcaption.py apply
python ps1/tools/introdiagram.py apply
for S in INTRO B000 B010 B020 B030 B040 B050 B060 B070 B080 B090 B0A0 B0B0 B0C0 B0D0 B0E0 B0F0 B100 B110 B120 B130 B140 B150 B160 B170 B180 B190 B1A0 B1B0 B1C0 B1D0 B1E0 B1F0 B200 B210 B220 B230 B240 B250 B260; do
  python ps1/subs/subs_cue.py on ps1/translation/subs_$S.json --scene $S > /dev/null
done
if [ "${SNATCHER_CENSORED:-0}" = "1" ]; then
  # patch_disc.py writes every patched/*.BIN it finds, so the two pictures
  # uncensor.py writes must not be left over from an earlier build. The exec
  # needs no undo - apply_translation rebuilt it from pristine, without the
  # maggot-skull file-table repoint.
  rm -f "patched/CXK_B062.BIN" "patched/CXF_B080.BIN"
else
  python ps1/tools/uncensor.py --lisa-saturn
fi
python ps1/tools/wordwrap.py apply
python ps1/tools/pageplate.py apply
python ps1/tools/bootcard.py apply
python ps1/tools/patch_disc.py
if [ "${SNATCHER_NO_FMV:-0}" != "1" ]; then
  # The FMV lives inside the image, so its text is replaced after the rebuild:
  # patch_disc regenerates the image and would undo it. SNATCHER_NO_FMV=1 skips
  # it for a variant image whose FMV is mirrored from the other one.
  python ps1/tools/fmvtext.py apply
fi
