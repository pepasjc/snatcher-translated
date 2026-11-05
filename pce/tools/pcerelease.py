"""The PC Engine release: the xdelta patch, the cue, README.txt, apply.bat /
apply.sh and the zip (the PCE twin of saturn/tools/satrelease.py).

    python pce/tools/pcerelease.py            # after Build-PCE.bat / build.py pce
    python pce/tools/pcerelease.py --chd      # also a CHD of the build, for local testing

Reads the version from pce/VERSION. The patch source is the whole disc as ONE
file: the redump set's 24 track files concatenated in order (`copy /b` /
`cat`), byte-identical to the single BIN that `chdman extractcd` writes from
the redump CHD (work/pce/snatcher_pce.bin, what the build reads; SHA1 in
SOURCE_SHA1). apply.bat / apply.sh do the joining for the player. The patched
image is longer than the source (track 2 grows by patch_pce.RESERVE sectors
before track 3's pregap), so the cue with the shifted track times ships beside
the patch.

The zip holds no CHD: a CHD of the build is the whole game. --chd writes one
to release/pce/ for the MiSTer or RetroArch, never into the zip.

Inputs: work/pce/snatcher_pce.bin (the source), patched/pce/snatcher_pce.bin +
.cue (the build), pce/VERSION, pce/RELEASE_NOTES.md (hand-written; its result
hash block is stamped here, and it must name this version's patch). xdelta3
and chdman come from lib/xdelta and lib/chdman (Windows; ps1/build/Make-Patch.bat
fetches xdelta3) or from PATH (Linux, the Docker image).
"""
import os, re, shutil, subprocess, sys, tempfile, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import release_readme as R
import patchscripts

SRC = os.path.join(WORK, "pce", "snatcher_pce.bin")
DST = os.path.join(ROOT, "patched", "pce", "snatcher_pce.bin")
DST_CUE = os.path.join(ROOT, "patched", "pce", "snatcher_pce.cue")
OUTDIR = os.path.join(ROOT, "release", "pce")
NOTES = os.path.join(ROOT, "pce", "RELEASE_NOTES.md")
BASE = "Snatcher CD-ROMantic (Japan)"
TRACKS = [f"{BASE} (Track {n:02d}).bin" for n in range(1, 25)]
JOINED = f"{BASE}.bin"                 # what apply.bat / apply.sh join the tracks into
# the redump set's 24 tracks joined (= chdman extractcd of the redump CHD)
SOURCE_SHA1 = "db254c2e2d888d042cb9df8dc55599feb4d1132d"
WINDOW = "1073741824"                  # the source is 633 MB: one window holds all of it


def tool(name):
    """lib/<name>/<name>.exe on Windows, else <name> on PATH."""
    exe = os.path.join(ROOT, "lib", {"xdelta3": "xdelta"}.get(name, name), name + ".exe")
    if os.name == "nt" and os.path.exists(exe):
        return exe
    found = shutil.which(name)
    if not found:
        sys.exit(f"{name} not found: on Windows `python build.py fetch` puts xdelta3 in lib/xdelta/ "
                 f"(chdman: put chdman.exe in lib/chdman/); elsewhere install it (xdelta3, mame-tools)")
    return found


def version():
    return open(os.path.join(ROOT, "pce", "VERSION")).read().strip()


def run(*args):
    print(" ".join(f'"{a}"' if " " in a else a for a in args))
    subprocess.run(args, check=True)


def stamp_notes(out_bin, h):
    """The result hash block in pce/RELEASE_NOTES.md rewritten from this build."""
    if not os.path.exists(NOTES):
        return
    s = open(NOTES, encoding="utf-8", newline="").read()
    pat = re.escape(out_bin) + r"\nSize   \S+\nCRC32  \S+\nMD5    \S+\nSHA1   \S+"
    new = f"{out_bin}\nSize   {h['Size']}\nCRC32  {h['CRC32']}\nMD5    {h['MD5']}\nSHA1   {h['SHA1']}"
    s, n = re.subn(pat, lambda _m: new, s)
    if n:
        print(f"stamped {out_bin} in {os.path.relpath(NOTES, ROOT)}")
    open(NOTES, "w", encoding="utf-8", newline="").write(s)


def check_notes(patch, h):
    """pce/RELEASE_NOTES.md must name this version's patch and the result SHA1."""
    if not os.path.exists(NOTES):
        print(f"ERROR: {NOTES} missing")
        return 1
    text = open(NOTES, encoding="utf-8").read()
    bad = [f"does not name {patch}"] if patch not in text else []
    bad += [f"the expected SHA1 {h['SHA1']} is not there"] if h["SHA1"] not in text else []
    for b in bad:
        print("ERROR: pce/RELEASE_NOTES.md is stale -", b)
    return 1 if bad else 0


def main():
    want_chd = "--chd" in sys.argv[1:]
    ver = version()
    tag = f"[T-En by pepa v{ver}]"
    name = f"{BASE} {tag}"
    xdelta = tool("xdelta3")
    for path in (SRC, DST, DST_CUE):
        if not os.path.exists(path):
            sys.exit(f"{path} missing: build the PC Engine image first (pce/build/Build-PCE.bat or build.py pce)")
    print("hashing the source ...")
    src_h = R.hashes(SRC)
    if src_h["SHA1"] != SOURCE_SHA1:
        sys.exit(f"{SRC}: SHA1 {src_h['SHA1']}, the redump tracks joined give {SOURCE_SHA1}")
    os.makedirs(OUTDIR, exist_ok=True)
    patch = name + ".xdelta"
    cue = name + ".cue"
    out_bin = name + ".bin"
    for f in (patch, cue, "README.txt", "apply.bat", "apply.sh"):
        if os.path.exists(os.path.join(OUTDIR, f)):
            os.remove(os.path.join(OUTDIR, f))
    # the patch, verified by applying it back
    run(xdelta, "-9", "-e", "-S", "djw", "-B", WINDOW, "-s", SRC, DST, os.path.join(OUTDIR, patch))
    check = os.path.join(tempfile.gettempdir(), "snatcher_pce_patch_check.bin")
    if os.path.exists(check):
        os.remove(check)
    run(xdelta, "-d", "-B", WINDOW, "-s", SRC, os.path.join(OUTDIR, patch), check)
    ok = R.same(check, DST)
    os.remove(check)
    if not ok:
        sys.exit("the patch does not reproduce the patched image")
    dst_h = R.hashes(DST)
    # the cue, naming the patched bin
    text = open(DST_CUE).read().replace(os.path.basename(DST), out_bin)
    open(os.path.join(OUTDIR, cue), "w", newline="\r\n").write(text)
    with open(os.path.join(OUTDIR, "README.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(readme(ver, patch, out_bin, cue, src_h, dst_h))
    patchscripts.write(OUTDIR, f"Snatcher CD-ROMantic (PC Engine CD) English translation v{ver}", [
        {"label": "English translation", "join": (JOINED, TRACKS),
         "steps": [(JOINED, patch, out_bin, src_h["SHA1"], dst_h["SHA1"])]}], window=int(WINDOW))
    stamp_notes(out_bin, dst_h)
    rc = check_notes(patch, dst_h)
    zpath = os.path.join(ROOT, "release", f"Snatcher-PCE-English-v{ver}.zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for n in (patch, cue, "README.txt", "apply.bat", "apply.sh"):
            if n.endswith(".sh"):                       # executable once unzipped
                zi = zipfile.ZipInfo.from_file(os.path.join(OUTDIR, n), n)
                zi.external_attr = 0o100755 << 16
                zi.create_system = 3
                zi.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(zi, open(os.path.join(OUTDIR, n), "rb").read())
            else:
                z.write(os.path.join(OUTDIR, n), n)
    print(f"wrote {zpath} ({os.path.getsize(zpath):,} bytes)")
    if want_chd:
        chd = os.path.join(OUTDIR, name + ".chd")
        if os.path.exists(chd):
            os.remove(chd)
        run(tool("chdman"), "createcd", "-i", DST_CUE, "-o", chd)
        print(f"local CHD (not for distribution): {chd}")
    if rc:
        sys.exit("the release notes need this version's names and hashes (see above)")


def readme(ver, patch, out_bin, cue, src_h, dst_h):
    return f"""Snatcher CD-ROMantic (PC Engine CD, Konami 1992) - English translation v{ver}
by pepa - https://github.com/pepasjc/snatcher-translated

WHAT YOU NEED
  Your own dump of "Snatcher CD-ROMantic (Japan)" in the redump.org
  BIN/CUE layout: 24 track files, "{TRACKS[0]}" to
  "{TRACKS[-1]}". Joined in order into one file they must hash:
{R.block(src_h)}
  A single BIN written by `chdman extractcd` from the redump CHD is the
  same file: name it "{JOINED}".

THE EASY WAY
  Put the 24 track files (or the joined .bin) in this folder and run
  apply.bat (Windows: double-click it) or apply.sh (Linux/macOS:
  sh apply.sh). It joins the tracks, checks the dump, applies the patch
  and checks the result. apply.bat downloads xdelta3 if it is missing; on
  Linux and macOS install it first (apt install xdelta3, brew install xdelta).

BY HAND
  Windows:     copy /b "{BASE} (Track 01).bin" + ... + "{BASE} (Track 24).bin" "{JOINED}"
  Linux/macOS: cat "{BASE} (Track "*").bin > "{JOINED}"
  xdelta3 -d -B {WINDOW} -s "{JOINED}" "{patch}" "{out_bin}"
  The result should hash:
{R.block(dst_h)}

  Put "{cue}" (included: track 2 is longer than the original, so the
  track times differ) beside "{out_bin}" and load the .cue. It converts to
  CHD with `chdman createcd -i "{cue}" -o out.chd`. The game needs the
  Super System Card 3.0 BIOS, as the original does.

NOTES
  - The whole script, menus, keyboard and typed puzzles, the graphics with
    writing in them, and subtitles for the voice acting, in English.
  - Report bugs at https://github.com/pepasjc/snatcher-translated/issues
    (say PC Engine, the scene, what was on screen, and attach a save if
    you can). Downloads: https://github.com/pepasjc/snatcher-translated/releases
  - This is a fan translation. It is free and must not be sold or bundled
    with a disc image. Snatcher is (c) Konami.
"""


if __name__ == "__main__":
    main()
