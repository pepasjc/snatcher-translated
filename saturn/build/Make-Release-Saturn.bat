@echo off
rem The Saturn release: a fresh build, then the two track patches, the cue,
rem README.txt and release\Snatcher-Saturn-English-v<VERSION>.zip
rem (saturn\tools\satrelease.py). saturn\RELEASE_NOTES.md must already name
rem this version's files and result hashes - satrelease checks it.
setlocal
cd /d "%~dp0..\.."
call "%~dp0Build-Saturn.bat" || goto :fail
python saturn\tools\satrelease.py || goto :fail
echo.
echo Done: release\Snatcher-Saturn-English-v*.zip
endlocal
exit /b 0
:fail
echo.
echo SATURN RELEASE FAILED.
pause
endlocal
exit /b 1
