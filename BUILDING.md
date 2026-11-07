# Building the patches from source

This repository holds the tools and the English data for the Snatcher
translations of three consoles: PlayStation (`ps1/`), Sega Saturn
(`saturn/`) and PC Engine CD (`pce/`), with shared code in `lib/`. One
script, `build.py`, builds any of them from your own disc dumps, and with
`--release` makes the same xdelta patches, cues, READMEs and zips that are
published on the releases page.

No game data is in the repository. You need your own dumps, in the
redump.org BIN/CUE layout.

## What you need

| Disc | Files | Needed for |
|---|---|---|
| Snatcher (Japan), PlayStation, SLPS-00154 | `Snatcher (Japan).bin` + `.cue` | every port (see below) |
| Snatcher (Japan), Saturn, T-9508G | `Snatcher (Japan) (Track 1).bin`, `(Track 2)`, `(Track 3)` + `.cue` | Saturn; the PS1's uncensored variant |
| Snatcher CD-ROMantic (Japan), PC Engine CD | `Snatcher CD-ROMantic (Japan) (Track 01).bin` ... `(Track 24).bin` + `.cue` | PC Engine |

The PlayStation disc is needed for all three: the boot screen's Snatcher
figure is cut from the PS1's art, and the Saturn build reads the PS1's
Japanese text to line its own up. The PS1's uncensored variant takes one
picture from the Saturn disc.

Fonts: most English is drawn from bitmap fonts shipped in `lib/fonts`
(public domain X11 faces and Tamzen). A few pictures were set in Windows
fonts, which cannot be redistributed. Copy these five files from a Windows
install (`C:\Windows\Fonts`) into a `fonts/` folder at the repository root:

    arial.ttf  arialbd.ttf  impact.ttf  times.ttf  msgothic.ttc

On Windows the build finds them in place. Other versions of these fonts
(Linux's msttcorefonts) also work, but the result will not hash the same as
the release.

Reproducing a release bit for bit: the releases are built on Windows. A
Linux or Docker build with the same five font files is byte-identical
except for the pictures rendered from TrueType, which FreeType rasterises a
hair differently from one build of it to the next: the boot screen's
disclaimer (all three ports) and the Saturn's credit roll, whose new size
also moves the chunks after it in DATA.BIN. Checked: the PC Engine image
differs in the 16 sectors of its splash and nowhere else; the Saturn in the
splash, chunk 394 and the table that locates the chunks. The game plays the same either way; only the hashes in the release
notes will not match.

## With Docker

```sh
docker build -t snatcher-build .
mkdir -p discs fonts out/patched out/release out/work
python3 build.py discs /path/to/your/dumps ...      # or lay discs/ out by hand, see below
# copy the five fonts into fonts/
docker run --rm \
    -v "$PWD/discs:/src/discs" -v "$PWD/fonts:/src/fonts:ro" \
    -v "$PWD/out/patched:/src/patched" -v "$PWD/out/release:/src/release" \
    -v "$PWD/out/work:/src/work-cache" \
    snatcher-build all --release
```

The image has Python and its packages, xdelta3, Java with jPSXdec (the PS1
intro movie) and chdman. `out/work` keeps the scratch between runs (disc
extractions, the repainted movie frames), so a second build is much faster.
`snatcher-build doctor` lists what it found.

## Without Docker

Python 3.10 or newer, then:

```sh
pip install -r requirements.txt
python build.py discs /path/to/ps1-dump /path/to/saturn-dump.zip /path/to/pce-dump
python build.py doctor
python build.py all --release
```

`build.py discs` takes folders, single files or the redump .zip and copies
each file it recognises into place:

```
discs/iso_ps1_jp/Snatcher (Japan).bin, .cue
discs/iso_saturn_jp/Snatcher (Japan) (Track 1).bin, (Track 2), (Track 3), Snatcher (Japan).cue
discs/iso_pcecd_jp/Snatcher CD-ROMantic (Japan) (Track 01).bin ... (Track 24).bin, .cue
```

Also needed: xdelta3 for `--release` (Windows: fetched into `lib/xdelta`
automatically; Linux: `apt install xdelta3`; macOS: `brew install xdelta`)
and Java 8 or newer for the PS1 intro movie (jPSXdec is fetched into
`lib/jpsxdec` on first use). `--no-fmv` skips the movie.

## Commands

```
python build.py doctor                   what is installed, which discs are in place
python build.py ps1    [--release] [--variant both|censored|uncensored] [--no-fmv]
python build.py saturn [--release]
python build.py pce    [--release]
python build.py all    [--release]
```

Each build prepares what it needs first and skips whatever is already done:
the disc extraction, the PS1 graphics and text references, the PC Engine
tracks joined into one image (`work/pce/snatcher_pce.bin`). Outputs:

- `patched/` the translated images: `Snatcher (Japan).bin` (PS1; with
  `--variant both` the translation-only one is `[censored]`),
  `patched/saturn/`, `patched/pce/`
- `release/` with `--release`: `Snatcher-PS1-English-v<ver>.zip`,
  `Snatcher-Saturn-English-v<ver>.zip`, `Snatcher-PCE-English-v<ver>.zip`,
  each with its patches, cues, README and `apply.bat` / `apply.sh`

A release build refuses to finish when the port's `RELEASE_NOTES.md` does
not name this version's patch files; the result hashes in it are stamped by
the build.

Rough times on a desktop: PS1 about 25 minutes the first time (the intro
movie's frames are repainted once, then reused), Saturn 10, PC Engine 5.

## On Windows, the old way

The per-port batch files still work and run the same chains:
`ps1\build\Make-Release.bat`, `saturn\build\Make-Release-Saturn.bat`,
`pce\build\Build-PCE.bat` then `python pce\tools\pcerelease.py`.

## Layout

```
build.py        the build, all ports
lib/            shared: text codec, LZSS, fonts, release helpers, emulator host
ps1/            tools/ (build chain), subs/ (voice subtitles), harness/ (headless
                play-testing), review/ (translation review web tool), translation/
                (the English data), build/ (Windows batch files)
saturn/         the same for the Saturn port
pce/            the same for the PC Engine port
docs/           ps1.md, saturn.md, pce.md (how each port works), review-tool.md
work/           scratch; only six committed build inputs (pair table, free slots,
                the PS1 file map, the voice census, jPSXdec's index, the font table)
```

How each port works - disc, text, font, subtitles, graphics, build order,
engine addresses - is in [`docs/ps1.md`](docs/ps1.md),
[`docs/saturn.md`](docs/saturn.md) and [`docs/pce.md`](docs/pce.md); every
data file is described in its port's `README.md` (`ps1/`, `saturn/`, `pce/`).
