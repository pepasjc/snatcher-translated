@echo off
rem Build one patched image. Usage:
rem
rem   Build-Image.bat                 uncensored (the dev/play-test build)
rem   Build-Image.bat censored        translation only, game art untouched
rem
rem SNATCHER_IMAGE names the output image (patch_disc.py, fmvtext.py); the
rem FMV is NOT applied here - the caller does that, so a release build can
rem encode it once and mirror it into the other variant.
rem
rem Order matters: apply_translation regenerates every patched file from
rem pristine sources, so the key table, label repointing and keyboard layout
rem must be rebuilt after it on every run.
setlocal
cd /d "%~dp0..\.."

set "VARIANT=%~1"
if /i "%VARIANT%"=="censored" (set "UNCENSOR=0") else (set "UNCENSOR=1")

rem the line breaks and the colour codes of every bank string: reported, never fatal
python ps1\tools\check_strings.py --all --quiet
python ps1\tools\apply_translation.py || pause
python ps1\tools\keytable.py apply || pause
python ps1\tools\repoint.py || pause
python ps1\tools\patch_keyboard.py || pause
python ps1\tools\kbdfaces.py apply || pause
python ps1\tools\specialmenu.py apply || pause
python ps1\tools\specialitem.py apply || pause
python ps1\tools\gfxpages.py apply || pause
python ps1\tools\gfxlabels.py apply || pause
python ps1\tools\disclaimer.py apply || pause
python ps1\tools\staffroll.py apply || pause
python ps1\tools\introcaption.py apply || pause
python ps1\tools\introdiagram.py apply || pause
rem apply_translation rebuilds every bank from pristine, which strips the
rem subtitle payloads with it - so every subtitled bank must be rebuilt here,
rem not just the one being worked on. subs_cue also rewrites the SHARED
rem executable stub, so these must all run with the same engine.
for %%S in (INTRO B000 B010 B020 B030 B040 B050 B060 B070 B080 B090 B0A0 B0B0 B0C0 B0D0 B0E0 B0F0 B100 B110 B120 B130 B140 B150 B160 B170 B180 B190 B1A0 B1B0 B1C0 B1D0 B1E0 B1F0 B200 B210 B220 B230 B240 B250 B260) do (
  python ps1\subs\subs_cue.py on ps1\translation\subs_%%S.json --scene %%S || pause
)
if "%UNCENSOR%"=="1" (
  rem Uncensored art: CXK_B062 (Gibson, the PS1's own B061), the maggot-skull
  rem repoint (edits the exec) and CXF_B080 (the Saturn's uncensored original).
  python ps1\tools\uncensor.py --lisa-saturn || pause
) else (
  rem Censored variant: no asset changes at all. patch_disc.py writes every
  rem patched\*.BIN it finds, so a leftover uncensored picture from the last
  rem build would ride along - drop the two files uncensor.py writes. The
  rem exec needs no undo: apply_translation rebuilt it from pristine, so the
  rem maggot-skull file-table repoint is not in it.
  echo Censored variant: leaving the game art alone.
  if exist "patched\CXK_B062.BIN" del /f /q "patched\CXK_B062.BIN"
  if exist "patched\CXF_B080.BIN" del /f /q "patched\CXF_B080.BIN"
)
python ps1\tools\wordwrap.py apply || pause
python ps1\tools\pageplate.py apply || pause
python ps1\tools\bootcard.py apply || pause
python ps1\tools\patch_disc.py || pause
