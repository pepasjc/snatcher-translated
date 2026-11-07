"""Release helpers for Make-Patch.bat.

  python release_readme.py same A B            exit 1 unless A and B are byte-identical
  python release_readme.py readme VER SRC DST PATCH OUT [DST2 PATCH2]
                                               write release/README.txt with the
                                               source/target hashes and how to
                                               apply; DST2/PATCH2 add the second
                                               (uncensored) variant
"""
import hashlib
import os
import sys
import zlib


def hashes(path):
    crc, md5, sha1 = 0, hashlib.md5(), hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            crc = zlib.crc32(chunk, crc)
            md5.update(chunk)
            sha1.update(chunk)
    return {"Size": os.path.getsize(path), "CRC32": f"{crc:08x}",
            "MD5": md5.hexdigest(), "SHA1": sha1.hexdigest()}


def same(a, b):
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(1 << 22), fb.read(1 << 22)
            if x != y:
                return False
            if not x:
                return True


def block(h):
    return "\n".join(f"      {k:<5} {v}" for k, v in h.items())


def readme(ver, src, dst, patch, out, dst2=None, patch2=None):
    """README for the release zip. Two variants ship since v0.8: the plain
    patch is the translation alone, `(Uncensored)` also restores the art the
    PS1 port censored (ps1/tools/uncensor.py). Both come from the same build, so
    the only difference is two pictures and one file-table record."""
    patch_name = os.path.basename(patch)
    bin_name = os.path.splitext(patch_name)[0] + ".bin"
    write_cue(patch)
    variants = f"""WHICH PATCH
  Two patches are included. Both carry the identical English translation;
  they differ only in the game's own artwork.

  "{patch_name}"
      Translation only. The game's graphics are left exactly as Konami
      shipped them on the Japanese PlayStation disc.

  "{os.path.basename(patch2)}"
      The same translation, plus the PlayStation-only censorship undone.
      The PS1 port greys out the corpse in the factory ruins and mosaics
      the maggot-covered body in the hospital; the Saturn and PC Engine
      versions do neither, and both uncensored pictures were left on the
      PS1 disc unused. This patch loads those instead, and restores the
      female Snatcher's body. No art is redrawn or added.

  Apply ONE of them to your dump. Saves are compatible between the two.

""" if patch2 else ""
    result = f"""  The patched .bin is larger than the original (relocated data is appended
  past the original image end); this is expected. Result should hash:
{block(hashes(dst))}
"""
    if patch2:
        result = f"""  The patched .bin is larger than the original (relocated data is appended
  past the original image end); this is expected. Results should hash:

    {bin_name}:
{block(hashes(dst))}

    {os.path.splitext(os.path.basename(patch2))[0] + ".bin"}:
{block(hashes(dst2))}
"""
    import patchscripts
    src_sha1 = hashes(src)["SHA1"]
    pv = [{"label": "Translation only" if patch2 else "English translation",
           "steps": [(os.path.basename(src), patch_name, bin_name, src_sha1, hashes(dst)["SHA1"])]}]
    if patch2:
        pv.append({"label": "Uncensored",
                   "steps": [(os.path.basename(src), os.path.basename(patch2),
                              os.path.splitext(os.path.basename(patch2))[0] + ".bin", src_sha1, hashes(dst2)["SHA1"])]})
    patchscripts.write(os.path.dirname(os.path.abspath(out)), f"Snatcher (PlayStation) English translation v{ver}", pv)
    apply_cmds = f'  xdelta3 -d -s "Snatcher (Japan).bin" "{patch_name}" "{bin_name}"'
    if patch2:
        bin2 = os.path.splitext(os.path.basename(patch2))[0] + ".bin"
        write_cue(patch2)
        apply_cmds += (f'\n  xdelta3 -d -s "Snatcher (Japan).bin" '
                       f'"{os.path.basename(patch2)}" "{bin2}"')
    text = f"""Snatcher (PlayStation, SLPS-00154): English translation patch v{ver}
by pepa

WHAT YOU NEED
  - Your own dump of "Snatcher (Japan)" in BIN/CUE form (redump.org layout:
    one MODE2/2352 track). Hashes of the expected source .bin:
{block(hashes(src))}
  - xdelta3 (https://github.com/jmacd/xdelta-gpl/releases) or any xdelta
    front-end: Delta Patcher (Windows), MultiPatch (macOS), xdelta3 (Linux).

{variants}APPLY: THE EASY WAY
  Put your "Snatcher (Japan).bin" in this folder and run apply.bat (Windows:
  double-click it) or apply.sh (Linux/macOS: sh apply.sh). It asks which
  version you want, checks your dump, applies the patch and checks the
  result. The .bat downloads xdelta3 by itself if it is missing; on
  Linux/macOS install it first (apt install xdelta3 / brew install xdelta).

APPLY: BY HAND
{apply_cmds}

  Put the .cue of the same name next to the output .bin. Load the .cue in
  your emulator (DuckStation, Beetle PSX, real hardware via ODE) or convert
  to CHD with chdman createcd.

{result}
  If xdelta3 reports a source mismatch, your dump differs from redump:
  re-dump or find a matching one. Do not apply to a .iso (2048-byte
  sectors) or to a CHD; convert those to BIN/CUE first.

NOTES
  - Full script, menus, keyboard puzzles, baked graphics and voice subtitles
    in English.
  - English text is drawn in the X11 "fixed" 6x13 font (public domain)
    and, in the opening's JUNKER HQ caption, Tamzen
    (https://github.com/sunaku/tamzen-font) by Suraj N. Kurapati, based on
    Tamsyn by Scott Fial; both are free to use, copy, modify and distribute.
  - Report bugs at https://github.com/pepasjc/snatcher-translated/issues
    with the scene, what was on screen and a memory card save if possible.
    Downloads: https://github.com/pepasjc/snatcher-translated/releases
"""
    with open(out, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)
    print(out)
    rc = check_notes(patch_name, hashes(dst))
    if patch2:
        rc |= check_notes(os.path.basename(patch2), hashes(dst2))
    return rc


def write_cue(patch):
    """The cue sheet for a patch's output .bin: one MODE2/2352 track, as redump."""
    name = os.path.basename(patch)
    cue = os.path.join(os.path.dirname(patch), os.path.splitext(name)[0] + ".cue")
    bin_name = os.path.splitext(name)[0] + ".bin"
    with open(cue, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(f'FILE "{bin_name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    print(cue)


def check_notes(patch_name, dst_hashes):
    """RELEASE_NOTES.md repeats the patch filename and the result hashes by
    hand, and it shipped naming the previous version's files once (v0.6 went
    out telling players to run the v0.5.2 command). README.txt is generated,
    so it cannot drift; this is the guard for the one that can."""
    notes = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "ps1", "RELEASE_NOTES.md")
    if not os.path.exists(notes):
        return 0
    text = open(notes, encoding="utf-8").read()
    bad = []
    if patch_name not in text:
        bad.append(f"the apply command does not name {patch_name}")
    if dst_hashes["SHA1"] not in text:
        bad.append(f"the expected-result SHA1 is not {dst_hashes['SHA1']}")
    if bad:
        print("ERROR: ps1/RELEASE_NOTES.md is stale -")
        for b in bad:
            print("   -", b)
        print("   update its 'How to apply' block, then re-run Make-Patch.")
        return 1
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "same":
        sys.exit(0 if same(sys.argv[2], sys.argv[3]) else 1)
    elif sys.argv[1] == "readme":
        sys.exit(readme(*sys.argv[2:9]) or 0)
    else:
        sys.exit(__doc__)
