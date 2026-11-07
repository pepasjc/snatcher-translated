"""The PlayStation release: two xdelta patches (translation only, uncensored),
their cues, README.txt, apply.bat / apply.sh and the zip - Make-Patch.bat in
Python, so it runs on Linux and in the Docker image too.

    python ps1/tools/ps1release.py          # after both variants are built (build.py ps1 / Make-Release.bat)

Inputs: discs/iso_ps1_jp/Snatcher (Japan).bin (pristine), patched/Snatcher
(Japan) [censored].bin and patched/Snatcher (Japan).bin (the two variants),
ps1/VERSION, ps1/RELEASE_NOTES.md (must name both patches and both result SHA1s:
lib/stamp_notes.py stamps the hashes). Each patch is verified by decoding it
against the pristine image. xdelta3: lib/xdelta/xdelta3.exe on Windows, else
PATH.
"""
import os, shutil, subprocess, sys, tempfile, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import release_readme as R

SRC = os.path.join(ROOT, "discs", "iso_ps1_jp", "Snatcher (Japan).bin")
DST = os.path.join(ROOT, "patched", "Snatcher (Japan) [censored].bin")
DST_UNC = os.path.join(ROOT, "patched", "Snatcher (Japan).bin")
OUTDIR = os.path.join(ROOT, "release")
WINDOW = "536870912"


def xdelta():
    exe = os.path.join(ROOT, "lib", "xdelta", "xdelta3.exe")
    if os.name == "nt" and os.path.exists(exe):
        return exe
    found = shutil.which("xdelta3")
    if not found:
        sys.exit("xdelta3 not found: Windows - run ps1/build/Make-Patch.bat once (it fetches lib/xdelta/xdelta3.exe) "
                 "or `python build.py ps1 --release`; Linux/macOS - install xdelta3")
    return found


def make(xd, dst, out, label):
    print(f"\nCreating patch ({label}): {out}")
    if os.path.exists(out):
        os.remove(out)
    subprocess.run([xd, "-9", "-e", "-S", "djw", "-B", WINDOW, "-s", SRC, dst, out], check=True)
    print("Verifying (apply to pristine, compare)...")
    chk = os.path.join(tempfile.gettempdir(), "snatcher_patch_check.bin")
    if os.path.exists(chk):
        os.remove(chk)
    subprocess.run([xd, "-d", "-B", WINDOW, "-s", SRC, out, chk], check=True)
    ok = R.same(chk, dst)
    os.remove(chk)
    if not ok:
        sys.exit(f"ERROR: {out} does not reproduce {dst}")


def main():
    ver = open(os.path.join(ROOT, "ps1", "VERSION")).read().strip()
    name = f"Snatcher (Japan) [T-En by pepa v{ver}]"
    name_unc = name + " (Uncensored)"
    out = os.path.join(OUTDIR, name + ".xdelta")
    out_unc = os.path.join(OUTDIR, name_unc + ".xdelta")
    for p, why in ((SRC, "pristine image"), (DST, "translation-only image"), (DST_UNC, "uncensored image")):
        if not os.path.exists(p):
            sys.exit(f"ERROR: {why} not found: {p} (build both variants first)")
    xd = xdelta()
    os.makedirs(OUTDIR, exist_ok=True)
    make(xd, DST, out, "translation only")
    make(xd, DST_UNC, out_unc, "uncensored")
    print("Writing cue and README...")
    rc = R.readme(ver, SRC, DST, out, os.path.join(OUTDIR, "README.txt"), DST_UNC, out_unc)
    if rc:
        sys.exit("ERROR: ps1/RELEASE_NOTES.md is stale (see above)")
    zpath = os.path.join(OUTDIR, f"Snatcher-PS1-English-v{ver}.zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in (out, out_unc, os.path.join(OUTDIR, name + ".cue"), os.path.join(OUTDIR, name_unc + ".cue"),
                  os.path.join(OUTDIR, "README.txt"), os.path.join(OUTDIR, "apply.bat"),
                  os.path.join(OUTDIR, "apply.sh")):
            n = os.path.basename(p)
            if n.endswith(".sh"):                       # executable once unzipped
                zi = zipfile.ZipInfo.from_file(p, n)
                zi.external_attr = 0o100755 << 16
                zi.create_system = 3
                zi.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(zi, open(p, "rb").read())
            else:
                z.write(p, n)
    print(f"\nDone: {zpath} ({os.path.getsize(zpath):,} bytes)")


if __name__ == "__main__":
    main()
