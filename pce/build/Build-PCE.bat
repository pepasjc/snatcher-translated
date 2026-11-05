@echo off
rem Build the English PC Engine image: patched\pce\snatcher_pce.bin/.cue from
rem work\pce\snatcher_pce.bin (fresh copy, track 2 extended), every module's
rem dialogue, menus and names re-encoded, grown modules relocated, the title
rem menu, the load screen, the opening cards, the keyboard and the credits
rem redrawn in English, the opening's narration subtitled, the boot
rem screens (PEPA SOFT HOUSE card, the Snatcher splash) added; then the
rem image is read back and every string, label and name proved to decode to
rem what was meant. Stops on the first error.
setlocal
cd /d "%~dp0..\.."
python pce\tools\pcescript.py apply || exit /b 1
python pce\tools\titlemenu.py apply || exit /b 1
python pce\tools\opencards.py apply || exit /b 1
python pce\tools\pcekeyboard.py apply || exit /b 1
python pce\tools\pcesearch.py apply || exit /b 1
python pce\tools\pcesubs.py apply || exit /b 1
python pce\tools\pcelongs.py apply || exit /b 1
python pce\tools\pcecredits.py apply || exit /b 1
python pce\tools\pceending.py apply || exit /b 1
python pce\tools\pcecards.py apply || exit /b 1
python pce\tools\pcelabels.py apply || exit /b 1
python pce\tools\pceopening.py apply || exit /b 1
python pce\tools\pcesplash.py apply || exit /b 1
python pce\tools\pcecdguard.py apply || exit /b 1
python pce\tools\pceverify.py || exit /b 1
