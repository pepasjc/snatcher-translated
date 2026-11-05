@echo off
setlocal
rem Build the distributable patches from discs\iso_ps1_jp\Snatcher (Japan).bin
rem (pristine redump) to the two patched images Make-Release.bat produces:
rem
rem   release\Snatcher (Japan) [T-En by pepa vN].xdelta
rem       <- patched\Snatcher (Japan) [censored].bin   translation only
rem   release\Snatcher (Japan) [T-En by pepa vN] (Uncensored).xdelta
rem       <- patched\Snatcher (Japan).bin              + uncensored art
rem
rem The work is ps1\tools\ps1release.py, the same on Linux and in Docker
rem (build.py ps1 --release). `build.py fetch` puts xdelta3.exe in lib\xdelta
rem first when it is missing.
cd /d "%~dp0..\.."
python build.py fetch || goto :fail
python ps1\tools\ps1release.py || goto :fail
dir /b release
pause
endlocal
exit /b 0

:fail
echo.
echo PATCH BUILD FAILED - see the message above.
pause
endlocal
exit /b 1
