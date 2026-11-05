"""apply.bat / apply.sh for a release zip: the player unzips next to the dump
and runs one of them - the dump's SHA1 is checked, xdelta3 found (the .bat
downloads the official Windows build next to itself when it is missing),
each patch applied, each result's SHA1 checked.

    write(outdir, title, variants)

variants = [{"label": "...", "steps": [(src, patch, out, src_sha1, out_sha1), ...],
             "join": (src, [part, ...])}, ...]
- file names only (everything sits in the script's own folder). The optional
"join" concatenates the redump track files into a step's single-file source
first (the PC Engine patch: its 24 tracks joined are exactly the source the
patch was made against), skipped when that file is already there. One variant
applies at once; with several, the script asks (or takes 1/2/... as its
argument). Used by lib/release_readme.py (the PS1's Make-Patch.bat) and
saturn/tools/satrelease.py; the scripts are generated, never hand-edited.

The .bat avoids parenthesised blocks around anything that echoes a file
name: every name here has "(Japan)" in it, and a `)` inside an unquoted
echo in a block ends the block. Checks run through :sha1 / :apply
subroutines instead.
"""
import os

XDELTA_URL = "https://github.com/jmacd/xdelta-gpl/releases/download/v3.1.0/xdelta3-3.1.0-x86_64.exe.zip"


def _bat(title, variants, window=536870912):
    L = ["@echo off", "setlocal", 'cd /d "%~dp0"', 'set "HERE=%~dp0"', f"title {title}", "echo.",
         f"echo {title}", "echo ============================================================", "echo."]
    if len(variants) > 1:
        L += ['set "V=%~1"', 'if not "%V%"=="" goto :have_v', "echo Which version do you want?"]
        for i, v in enumerate(variants, 1):
            L.append(f"echo   {i}. {v['label']}")
        L += ["echo.", 'set /p "V=Type the number and press Enter: "', ":have_v"]
        for i in range(1, len(variants) + 1):
            L.append(f'if "%V%"=="{i}" goto :v{i}')
        L += ["echo Not a choice: %V%", "goto :fail"]
    for i, v in enumerate(variants, 1):
        L.append(f":v{i}")
        L.append(f"echo Building: {v['label']}")
        L.append("call :xdelta || goto :fail")
        if v.get("join"):
            out, parts = v["join"]
            L.append(f'if exist "{out}" goto :joined{i}')
            for part in parts:
                L += [f'set "J={part}"', 'if not exist "%J%" goto :nojoin']
            L.append(f'echo Joining the {len(parts)} track files into "{out}"...')
            L.append("copy /b " + " + ".join(f'"{part}"' for part in parts) + f' "{out}" >nul || goto :fail')
            L.append(f":joined{i}")
        for src, patch, out, s1, o1 in v["steps"]:
            L.append(f'call :apply "{src}" "{patch}" "{out}" {s1} {o1} || goto :fail')
        L += ["goto :done"]
    L += [
        ":done", "echo.", "echo All done. Load the .cue file that came in the zip.",
        "echo.", "pause", "exit /b 0",
        ":fail", "echo.", "echo PATCHING FAILED - see the message above. Nothing was deleted.",
        "echo.", "pause", "exit /b 1",
        "",
        ":xdelta",
        'if exist "%HERE%xdelta3.exe" exit /b 0',
        "where xdelta3 >nul 2>nul && exit /b 0",
        "echo xdelta3 not found - downloading the official build from GitHub...",
        "powershell -NoProfile -ExecutionPolicy Bypass -Command \"$ProgressPreference='SilentlyContinue';"
        f" Invoke-WebRequest -Uri '{XDELTA_URL}' -OutFile 'xdelta3.zip';"
        " Expand-Archive -Force 'xdelta3.zip' 'xdelta3_tmp';"
        " Get-ChildItem 'xdelta3_tmp' -Filter 'xdelta3*.exe' -Recurse | Select-Object -First 1 | Move-Item -Destination 'xdelta3.exe' -Force;"
        " Remove-Item -Recurse -Force 'xdelta3_tmp','xdelta3.zip'\"",
        'if exist "%HERE%xdelta3.exe" exit /b 0',
        "echo Could not download xdelta3. Get it from",
        "echo   https://github.com/jmacd/xdelta-gpl/releases",
        "echo and put xdelta3.exe in this folder.",
        "exit /b 1",
        "",
        ":sha1",
        'set "H="',
        'for /f "delims=" %%a in (\'certutil -hashfile "%~1" SHA1 ^| findstr /v ":"\') do if not defined H set "H=%%a"',
        'set "H=%H: =%"',
        "exit /b 0",
        "",
        ":apply",
        'if not exist "%~1" goto :nosrc',
        'echo Checking "%~1"...',
        'call :sha1 "%~1"',
        'if /i not "%H%"=="%~4" goto :badsrc',
        'echo Patching into "%~3"...',
        'set "XD=%HERE%xdelta3.exe"',
        'if not exist "%HERE%xdelta3.exe" set "XD=xdelta3"',
        f'"%XD%" -d -f -B {window} -s "%~1" "%~2" "%~3" || goto :badpatch',
        'call :sha1 "%~3"',
        'if /i not "%H%"=="%~5" goto :badout',
        'echo   OK: "%~3"',
        "exit /b 0",
        ":nojoin",
        'echo Not found: "%J%"',
        "echo Put every track file of your dump in this folder, named exactly as in its .cue, and run this again.",
        "goto :fail",
        ":nosrc",
        'echo Not found: "%~1"',
        "echo Put your dump in this folder, named exactly as above, and run this again.",
        "exit /b 1",
        ":badsrc",
        'echo "%~1" is not the expected dump.',
        "echo   SHA1 found:    %H%",
        "echo   SHA1 expected: %~4",
        "echo It must match the redump.org dump - see README.txt.",
        "exit /b 1",
        ":badpatch",
        "echo xdelta3 failed.",
        "exit /b 1",
        ":badout",
        'echo The result "%~3" does not have the expected SHA1.',
        "echo   found:    %H%",
        "echo   expected: %~5",
        "exit /b 1",
    ]
    return "\r\n".join(L) + "\r\n"


def _sh(title, variants, window=536870912):
    L = ["#!/bin/sh", f"# {title} - generated by lib/patchscripts.py", "set -e",
         'cd "$(dirname "$0")"', f'echo "{title}"',
         'echo "============================================================"', "",
         "if command -v xdelta3 >/dev/null 2>&1; then XD=xdelta3",
         "elif [ -x ./xdelta3.exe ]; then XD=./xdelta3.exe",
         "else",
         '  echo "xdelta3 is not installed. Install it and run this again:"',
         '  echo "  Debian/Ubuntu: sudo apt install xdelta3"',
         '  echo "  Fedora:        sudo dnf install xdelta"',
         '  echo "  Arch:          sudo pacman -S xdelta3"',
         '  echo "  macOS:         brew install xdelta"',
         "  exit 1",
         "fi",
         "if command -v sha1sum >/dev/null 2>&1; then sha1() { sha1sum \"$1\" | cut -d' ' -f1; }",
         "else sha1() { shasum -a 1 \"$1\" | cut -d' ' -f1; }",
         "fi",
         "apply() {",
         '  [ -f "$1" ] || { echo "Not found: $1"; echo "Put your dump in this folder, named exactly as above, and run this again."; exit 1; }',
         '  echo "Checking $1..."',
         '  h=$(sha1 "$1")',
         '  [ "$h" = "$4" ] || { echo "$1 is not the expected dump."; echo "  SHA1 found:    $h"; echo "  SHA1 expected: $4"; echo "It must match the redump.org dump - see README.txt."; exit 1; }',
         '  echo "Patching into $3..."',
         f'  "$XD" -d -f -B {window} -s "$1" "$2" "$3"',
         '  h=$(sha1 "$3")',
         '  [ "$h" = "$5" ] || { echo "The result $3 does not have the expected SHA1."; echo "  found:    $h"; echo "  expected: $5"; exit 1; }',
         '  echo "  OK: $3"',
         "}",
         "join_tracks() {",
         '  out="$1"; shift',
         '  [ -f "$out" ] && return 0',
         '  for p in "$@"; do [ -f "$p" ] || { echo "Not found: $p"; echo "Put every track file of your dump in this folder, named exactly as in its .cue, and run this again."; exit 1; }; done',
         '  echo "Joining the $# track files into $out..."',
         '  cat "$@" > "$out"',
         "}", ""]

    def joins(v, ind):
        if not v.get("join"):
            return []
        out, parts = v["join"]
        return [ind + f'join_tracks "{out}" ' + " ".join(f'"{part}"' for part in parts)]
    if len(variants) > 1:
        L += ['V="$1"', 'if [ -z "$V" ]; then', '  echo "Which version do you want?"']
        for i, v in enumerate(variants, 1):
            L.append(f'  echo "  {i}. {v["label"]}"')
        L += ['  printf "Type the number and press Enter: "', "  read V", "fi", 'case "$V" in']
        for i, v in enumerate(variants, 1):
            L.append(f"  {i})")
            L.append(f'    echo "Building: {v["label"]}"')
            L += joins(v, "    ")
            for src, patch, out, s1, o1 in v["steps"]:
                L.append(f'    apply "{src}" "{patch}" "{out}" {s1} {o1}')
            L.append("    ;;")
        L += ['  *) echo "Not a choice: $V"; exit 1 ;;', "esac"]
    else:
        L += joins(variants[0], "")
        for src, patch, out, s1, o1 in variants[0]["steps"]:
            L.append(f'apply "{src}" "{patch}" "{out}" {s1} {o1}')
    L += ['echo', 'echo "All done. Load the .cue file that came in the zip."']
    return "\n".join(L) + "\n"


def write(outdir, title, variants, window=536870912):
    """apply.bat and apply.sh into outdir; returns their paths."""
    bat = os.path.join(outdir, "apply.bat")
    sh = os.path.join(outdir, "apply.sh")
    with open(bat, "w", encoding="ascii", newline="") as f:
        f.write(_bat(title, variants, window))
    with open(sh, "w", encoding="ascii", newline="") as f:
        f.write(_sh(title, variants, window))
    return bat, sh
