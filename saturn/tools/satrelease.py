"""The Saturn release: xdelta patches for the two tracks the build changes, the
cue, README.txt and the zip (the Saturn twin of ps1/build/Make-Patch.bat).

    python saturn/tools/satrelease.py            # after build_saturn.sh / Build-Saturn.bat

The build (satdisc.py) rewrites track 1 (the data track: DATA.BIN, MAIN_L.BIN,
the IP, grown past the redump size) and track 2 (the Mode 2 voice track: every
sector header's MSF moves with the grown track 1); track 3 (CD-DA) is copied
verbatim, so it ships no patch and the release cue names the player's own
"Snatcher (Japan) (Track 3).bin". Each patch is verified by decoding it
against the pristine track and comparing with the build's output.

Inputs: discs/iso_saturn_jp/ (the redump set, checked against REDUMP below),
patched/saturn/ (the build), saturn/VERSION, saturn/RELEASE_NOTES.md (hand-written;
checked like the PS1's: it must name this version's files and the result
SHA1s). Output: release/saturn/ - two .xdelta, the .cue, README.txt, and
release/Snatcher-Saturn-English-v<VER>.zip. xdelta3 comes from lib/xdelta
(ps1/build/Make-Patch.bat bootstraps it).
"""
import os, subprocess, sys, tempfile, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

from release_readme import hashes, same, block
import patchscripts

SRC_DIR = os.path.join(ROOT, "discs", "iso_saturn_jp")
DST_DIR = os.path.join(ROOT, "patched", "saturn")
OUT_DIR = os.path.join(ROOT, "release", "saturn")
NOTES = os.path.join(ROOT, "saturn", "RELEASE_NOTES.md")
XDELTA = os.path.join(ROOT, "lib", "xdelta", "xdelta3.exe")
if not (os.name == "nt" and os.path.exists(XDELTA)):
    import shutil
    XDELTA = shutil.which("xdelta3") or XDELTA        # Linux / macOS / the Docker image
BASE = "Snatcher (Japan)"
TRACKS = [f"{BASE} (Track {n}).bin" for n in (1, 2, 3)]
PATCHED = (0, 1)                       # tracks 1 and 2 change; track 3 is verbatim
# redump T-9508G V1.000 (the redump zip): SHA1 per track
REDUMP = {
    TRACKS[0]: "a3ebab5b07a2b9a17aa68554072585be8839aba3",
}
WINDOW = str(1 << 29)                  # the PS1's -B: the whole track in one source window


def version():
    return open(os.path.join(ROOT, "saturn", "VERSION"), encoding="utf-8").read().strip()


def run(cmd):
    r = subprocess.run(cmd)
    if r.returncode:
        sys.exit(f"failed: {' '.join(cmd)}")


def names(ver):
    tag = f"[T-En by pepa v{ver}]"
    out_bins = [f"{BASE} {tag} (Track {n}).bin" for n in (1, 2)]
    patches = [f"{BASE} (Track {n}) {tag}.xdelta" for n in (1, 2)]
    return tag, out_bins, patches


def write_cue(path, out_bins):
    """The redump cue with the two patched tracks' names; track 3 is the player's own."""
    cue = (f'CATALOG 0000000000000\n'
           f'FILE "{out_bins[0]}" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n'
           f'FILE "{out_bins[1]}" BINARY\n  TRACK 02 MODE2/2352\n    INDEX 00 00:00:00\n    INDEX 01 00:03:00\n'
           f'FILE "{TRACKS[2]}" BINARY\n  TRACK 03 AUDIO\n    INDEX 00 00:00:00\n    INDEX 01 00:02:00\n')
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(cue)


def readme(ver, tag, out_bins, patches, src_h, dst_h, cue_name):
    apply_cmds = "\n".join(
        f'  xdelta3 -d -s "{TRACKS[i]}" "{patches[k]}" "{out_bins[k]}"' for k, i in enumerate(PATCHED))
    srcs = "\n\n".join(f"    {TRACKS[i]}:\n{block(src_h[i])}" for i in range(3))
    dsts = "\n\n".join(f"    {out_bins[k]}:\n{block(dst_h[k])}" for k in range(2))
    return f"""Snatcher (Sega Saturn, T-9508G): English translation patch v{ver}
by pepa

WHAT YOU NEED
  - Your own dump of "Snatcher (Japan)" for the Saturn in BIN/CUE form, the
    redump.org layout: three tracks (1 data, 2 voice data, 3 audio).
    Hashes of the expected source files:

{srcs}

  - xdelta3 (https://github.com/jmacd/xdelta-gpl/releases) or any xdelta
    front-end: Delta Patcher (Windows), MultiPatch (macOS), xdelta3 (Linux).

APPLY: THE EASY WAY
  Put your three original .bin files (named as above) in this folder and run
  apply.bat (Windows: double-click it) or apply.sh (Linux/macOS: sh apply.sh).
  It checks your dump, applies both patches and checks the results. The .bat
  downloads xdelta3 by itself if it is missing; on Linux/macOS install it
  first (apt install xdelta3 / brew install xdelta).

APPLY: BY HAND
  Two patches, one for track 1 and one for track 2. Track 3 is not changed.

{apply_cmds}

  Put the .cue from this zip in the same folder as the two new .bin files
  and your original "{TRACKS[2]}", and load the .cue:
    {cue_name}
  Tested in Beetle Saturn (RetroArch / Mednafen) and on a MiSTer (convert
  to CHD with chdman createcd). Other emulators and real hardware through
  an ODE should work but have not been tried.

  The new track 1 is larger than the original (the translated data is
  larger than the Japanese); this is expected. Results should hash:

{dsts}

  If xdelta3 reports a source mismatch, your dump differs from redump:
  re-dump or find a matching one. Do not apply to an .iso, a .ccd/.img set
  or a CHD; convert those to the redump BIN/CUE first.

NOTES
  - Script, menus, keyboard puzzles, the memo pages, the diary, the
    opening's captions and credit roll, and subtitles for the voice acting,
    in English.
  - English text is drawn in the X11 "fixed" 7x13 font (public domain).
  - Report bugs at https://github.com/pepasjc/snatcher-translated/issues
    with the scene, what was on screen and a save if possible.
    Downloads: https://github.com/pepasjc/snatcher-translated/releases
"""


def stamp_notes(out_bins, dst_h):
    """The result hash blocks in saturn/RELEASE_NOTES.md rewritten from this
    build (the PS1's lib/stamp_notes.py); the file names stay hand-edited and
    check_notes holds them to this version."""
    import re
    if not os.path.exists(NOTES):
        return
    s = open(NOTES, encoding="utf-8").read()
    for name, h in zip(out_bins, dst_h):
        pat = re.escape(name) + r"\nSize   \d+\nCRC32  \w+\nMD5    \w+\nSHA1   \w+"
        new = f"{name}\nSize   {h['Size']}\nCRC32  {h['CRC32']}\nMD5    {h['MD5']}\nSHA1   {h['SHA1']}"
        s, n = re.subn(pat, lambda _m: new, s)
        if n:
            print(f"stamped {name}")
    open(NOTES, "w", encoding="utf-8").write(s)


def check_notes(patches, dst_h):
    """saturn/RELEASE_NOTES.md repeats the file names and the result hashes by
    hand (the PS1's check_notes: v0.6 once shipped naming v0.5.2's files)."""
    if not os.path.exists(NOTES):
        print(f"ERROR: {NOTES} missing")
        return 1
    text = open(NOTES, encoding="utf-8").read()
    bad = [f"does not name {p}" for p in patches if p not in text]
    bad += [f"the expected SHA1 {h['SHA1']} is not there" for h in dst_h if h["SHA1"] not in text]
    if bad:
        print("ERROR: saturn/RELEASE_NOTES.md is stale -")
        for b in bad:
            print("   -", b)
        return 1
    return 0


def main():
    ver = version()
    tag, out_bins, patches = names(ver)
    if not os.path.exists(XDELTA):
        sys.exit(f"{XDELTA} missing: `python build.py fetch` downloads it (Windows); elsewhere install xdelta3")
    src = [os.path.join(SRC_DIR, t) for t in TRACKS]
    dst = [os.path.join(DST_DIR, TRACKS[i]) for i in PATCHED]
    for p in src + dst:
        if not os.path.exists(p):
            sys.exit(f"missing: {p}")
    print("hashing the sources ...")
    src_h = [hashes(p) for p in src]
    for i, t in enumerate(TRACKS):
        want = REDUMP.get(t)
        if want and src_h[i]["SHA1"] != want:
            sys.exit(f"{t}: SHA1 {src_h[i]['SHA1']}, redump says {want}")
    if not same(src[2], os.path.join(DST_DIR, TRACKS[2])):
        sys.exit("track 3 of the build differs from the source: it would need a patch too")
    os.makedirs(OUT_DIR, exist_ok=True)
    dst_h = []
    for k, i in enumerate(PATCHED):
        out = os.path.join(OUT_DIR, patches[k])
        if os.path.exists(out):
            os.remove(out)
        print(f"encoding {patches[k]} ...")
        run([XDELTA, "-9", "-e", "-S", "djw", "-B", WINDOW, "-s", src[i], dst[k], out])
        chk = os.path.join(tempfile.gettempdir(), "snatcher_saturn_patch_check.bin")
        if os.path.exists(chk):
            os.remove(chk)
        run([XDELTA, "-d", "-B", WINDOW, "-s", src[i], out, chk])
        if not same(chk, dst[k]):
            sys.exit(f"{patches[k]}: decoding it does not give the build's track {i + 1}")
        os.remove(chk)
        dst_h.append(hashes(dst[k]))
        print(f"  ok: {os.path.getsize(out):,} bytes, decodes to the build's track {i + 1}")
    cue_name = f"{BASE} {tag}.cue"
    write_cue(os.path.join(OUT_DIR, cue_name), out_bins)
    text = readme(ver, tag, out_bins, patches, src_h, dst_h, cue_name)
    with open(os.path.join(OUT_DIR, "README.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)
    patchscripts.write(OUT_DIR, f"Snatcher (Saturn) English translation v{ver}", [
        {"label": "English translation", "steps": [
            (TRACKS[i], patches[k], out_bins[k], src_h[i]["SHA1"], dst_h[k]["SHA1"]) for k, i in enumerate(PATCHED)]}])
    stamp_notes(out_bins, dst_h)
    rc = check_notes(patches, dst_h)
    zpath = os.path.join(ROOT, "release", f"Snatcher-Saturn-English-v{ver}.zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for n in patches + [cue_name, "README.txt", "apply.bat", "apply.sh"]:
            if n.endswith(".sh"):                       # executable once unzipped
                zi = zipfile.ZipInfo.from_file(os.path.join(OUT_DIR, n), n)
                zi.external_attr = 0o100755 << 16
                zi.create_system = 3                      # Unix, or unzip ignores the mode
                zi.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(zi, open(os.path.join(OUT_DIR, n), "rb").read())
            else:
                z.write(os.path.join(OUT_DIR, n), n)
    print(f"wrote {zpath} ({os.path.getsize(zpath):,} bytes)")
    if rc:
        sys.exit("the release notes need this version's names and hashes (see above)")


if __name__ == "__main__":
    main()
