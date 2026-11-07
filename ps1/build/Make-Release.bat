@echo off
setlocal
rem Build BOTH release images and the two patches.
rem
rem   patched\Snatcher (Japan) [censored].bin   translation only, art untouched
rem   patched\Snatcher (Japan).bin              translation + uncensored art
rem                                             (also the dev/play-test image)
rem
rem Both images are deleted first so each is a fresh copy of the pristine
rem disc: patch_disc.py only writes the files it is given, so an image kept
rem from an earlier build would carry that build's art into this one.
rem
rem The intro FMV is encoded once (jPSXdec, 1,829 frames, minutes) into the
rem censored image and mirrored byte-for-byte into the uncensored one: the
rem two builds differ only in two pictures and one file-table record, and
rem jPSXdec touches nothing but MX2_S000.STR's sectors.
cd /d "%~dp0..\.."

set "CENSORED_IMG=Snatcher (Japan) [censored]"

rem A locked image (DuckStation still running) makes `del` print and carry
rem on; the build then patches over the stale image, and its leftover pad
rem sectors shape the result (v0.8's uncensored image was built that way).
rem Both must be gone before the builds start.
if exist "patched\%CENSORED_IMG%.bin" del /f /q "patched\%CENSORED_IMG%.bin"
if exist "patched\Snatcher (Japan).bin" del /f /q "patched\Snatcher (Japan).bin"
if exist "patched\%CENSORED_IMG%.bin" (
    echo ERROR: could not delete "patched\%CENSORED_IMG%.bin" - close the emulator
    goto :fail
)
if exist "patched\Snatcher (Japan).bin" (
    echo ERROR: could not delete "patched\Snatcher (Japan).bin" - close the emulator
    goto :fail
)

echo.
echo === Building the translation-only image ===
set "SNATCHER_IMAGE=%CENSORED_IMG%"
call "%~dp0Build-Image.bat" censored || goto :fail
if not exist "patched\%CENSORED_IMG%.bin" goto :fail
python ps1\tools\fmvtext.py apply || goto :fail

echo.
echo === Building the uncensored image ===
set "SNATCHER_IMAGE="
call "%~dp0Build-Image.bat" uncensored || goto :fail
if not exist "patched\Snatcher (Japan).bin" goto :fail
python ps1\tools\fmvtext.py mirror "%CENSORED_IMG%" || goto :fail

echo.
echo === Verifying the two variants ===
python ps1\tools\check_variant.py censored || goto :fail
python ps1\tools\check_variant.py uncensored || goto :fail

echo.
echo === Release notes ===
rem The result hashes change on every rebuild; stamp them into ps1\RELEASE_NOTES.md
rem so Make-Patch's staleness guard is left to catch the half that matters,
rem the patch FILENAMES (0.6 shipped naming 0.5.2's file).
python lib\stamp_notes.py || goto :fail

echo.
echo === Patches ===
call "%~dp0Make-Patch.bat"
endlocal
exit /b 0

:fail
echo.
echo RELEASE BUILD FAILED - no patch was made.
pause
endlocal
exit /b 1
