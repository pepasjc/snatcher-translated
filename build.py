#!/usr/bin/env python3
"""Build the Snatcher English patches from source: PlayStation, Saturn, PC Engine CD.

    python build.py doctor                     what is installed, which discs are in place
    python build.py discs PATH [PATH...]       copy your dumps into discs/ (files, folders or .zip)
    python build.py ps1    [--release] [--variant both|censored|uncensored] [--no-fmv]
    python build.py saturn [--release]
    python build.py pce    [--release]
    python build.py all    [--release]

Each port's build runs its preparation first (extracting the disc, the PS1
graphics and text references the others borrow), skipping whatever is already
done, then the same tool chain as its Windows .bat. Outputs: patched/ (the
images), release/ (xdelta patches, cues, READMEs, apply scripts, zips) with
--release.

Discs (your own dumps, redump.org BIN/CUE layout; never committed):
  discs/iso_ps1_jp/     Snatcher (Japan).bin + .cue                         PlayStation, SLPS-00154
  discs/iso_saturn_jp/  Snatcher (Japan) (Track 1|2|3).bin + .cue          Saturn, T-9508G
  discs/iso_pcecd_jp/   Snatcher CD-ROMantic (Japan) (Track 01..24).bin + .cue   PC Engine
Every port needs the PlayStation disc as well: the boot screen's Snatcher is
cut from the PS1's art, and the Saturn carries the PS1's text references. The
PS1's uncensored variant needs the Saturn disc (one picture comes from it).

Tools: Python 3.10+ with numpy, Pillow and capstone (opencv-python and scipy for the PS1
intro movie's first build), xdelta3 for --release, Java 8+ for the PS1 intro
movie (jPSXdec is fetched into lib/jpsxdec/), and five Windows fonts (see
lib/sysfont.py). The Dockerfile at the root has all of it but the fonts.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, time, urllib.request, zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(ROOT, "work")
DISCS = os.path.join(ROOT, "discs")
PATCHED = os.path.join(ROOT, "patched")
sys.path[:0] = [os.path.join(ROOT, d) for d in ("lib",)]

PY = sys.executable
JPSXDEC_URL = "https://github.com/m35/jpsxdec/releases/download/v2.0/jpsxdec_v2.0.zip"
JPSXDEC_JAR = os.path.join(ROOT, "lib", "jpsxdec", "jpsxdec_v2.0", "jpsxdec.jar")
XDELTA_URL = "https://github.com/jmacd/xdelta-gpl/releases/download/v3.1.0/xdelta3-3.1.0-x86_64.exe.zip"

PS1_DIR = os.path.join(DISCS, "iso_ps1_jp")
PS1_BIN = os.path.join(PS1_DIR, "Snatcher (Japan).bin")
PS1_SHA1 = "e6cd330feb594b3951089da866db1a400f0173f6"
SAT_DIR = os.path.join(DISCS, "iso_saturn_jp")
SAT_TRACKS = [os.path.join(SAT_DIR, f"Snatcher (Japan) (Track {n}).bin") for n in (1, 2, 3)]
SAT_SHA1 = "a3ebab5b07a2b9a17aa68554072585be8839aba3"          # track 1
PCE_DIR = os.path.join(DISCS, "iso_pcecd_jp")
PCE_BASE = "Snatcher CD-ROMantic (Japan)"
PCE_TRACKS = [os.path.join(PCE_DIR, f"{PCE_BASE} (Track {n:02d}).bin") for n in range(1, 25)]
PCE_JOINED = os.path.join(WORK, "pce", "snatcher_pce.bin")
PCE_SHA1 = "db254c2e2d888d042cb9df8dc55599feb4d1132d"           # the 24 tracks joined

PS1_SCENES = ["INTRO"] + [f"B{n:02X}0" for n in range(0x00, 0x27)]
CENSORED_IMG = "Snatcher (Japan) [censored]"


def log(msg):
    print(f"\n=== {msg}", flush=True)


def run(args, env=None, check=True):
    """A chain step: python scripts by path, from the repo root, stop on failure."""
    if args and args[0].endswith(".py"):
        args = [PY] + args
    e = dict(os.environ)
    e.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        for k, v in env.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = v
    print("+ " + " ".join(f'"{a}"' if " " in a else a for a in args), flush=True)
    r = subprocess.run(args, cwd=ROOT, env=e)
    if check and r.returncode:
        sys.exit(f"build step failed (exit {r.returncode}): {' '.join(args)}")
    return r.returncode


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def verified(path, want):
    """SHA1 check, remembered per (size, mtime) in work/verified.json."""
    cache_path = os.path.join(WORK, "verified.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    st = os.stat(path)
    key = f"{os.path.relpath(path, ROOT)}|{st.st_size}|{int(st.st_mtime)}"
    if cache.get(key) == want:
        return True
    print(f"checking {os.path.relpath(path, ROOT)} ...", flush=True)
    got = sha1(path)
    if got != want:
        return False
    cache[key] = want
    os.makedirs(WORK, exist_ok=True)
    json.dump(cache, open(cache_path, "w"), indent=1)
    return True


class keep:
    """Snapshot files a preparation tool rewrites as a side effect (committed
    data), and put them back after it: dump_strings.py rewrites
    ps1/translation/ISZ_*.json, satcarry.py saturn/translation/SAT_*.json,
    extract_ps1.py work/lba_map.json."""

    def __init__(self, *paths):
        self.paths = paths
        self.saved = {}

    def __enter__(self):
        for p in self.paths:
            full = os.path.join(ROOT, p)
            files = [full] if os.path.isfile(full) else [
                os.path.join(d, f) for d, _, fs in os.walk(full) for f in fs] if os.path.isdir(full) else []
            for f in files:
                self.saved[f] = open(f, "rb").read()

    def __exit__(self, *exc):
        for f, data in self.saved.items():
            if not os.path.exists(f) or open(f, "rb").read() != data:
                open(f, "wb").write(data)


# --- tools --------------------------------------------------------------------

def tool(name, required=True):
    """xdelta3 / chdman: lib/<name>/<name>.exe on Windows, else PATH."""
    exe = os.path.join(ROOT, "lib", {"xdelta3": "xdelta"}.get(name, name), name + ".exe")
    if os.name == "nt" and os.path.exists(exe):
        return exe
    found = shutil.which(name)
    if not found and required and os.name == "nt" and name == "xdelta3":
        fetch_xdelta()
        return exe
    if not found and required:
        sys.exit(f"{name} not found on PATH (Debian/Ubuntu: apt install {'xdelta3' if name == 'xdelta3' else 'mame-tools'})")
    return found


def download(url, dest):
    print(f"downloading {url}", flush=True)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def fetch_xdelta():
    """Windows: the official xdelta3 build into lib/xdelta/xdelta3.exe."""
    d = os.path.join(ROOT, "lib", "xdelta")
    z = os.path.join(d, "xdelta3.zip")
    download(XDELTA_URL, z)
    with zipfile.ZipFile(z) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".exe"))
        with zf.open(member) as src, open(os.path.join(d, "xdelta3.exe"), "wb") as dst:
            shutil.copyfileobj(src, dst)
    os.remove(z)


def ensure_jpsxdec():
    if os.path.exists(JPSXDEC_JAR):
        return
    base = os.path.dirname(os.path.dirname(JPSXDEC_JAR))      # lib/jpsxdec; the zip holds jpsxdec_v2.0/
    z = os.path.join(base, "jpsxdec.zip")
    download(JPSXDEC_URL, z)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(base)
    if not os.path.exists(JPSXDEC_JAR):
        sys.exit(f"jPSXdec: {JPSXDEC_JAR} not in {JPSXDEC_URL}")


# --- discs --------------------------------------------------------------------

def cmd_discs(paths):
    """Copy dumps into discs/, by file name: a folder or .zip is searched."""
    want = {}
    want[os.path.basename(PS1_BIN)] = PS1_DIR
    want["Snatcher (Japan).cue"] = None            # ambiguous: placed beside its bins below
    for t in SAT_TRACKS:
        want[os.path.basename(t)] = SAT_DIR
    for t in PCE_TRACKS:
        want[os.path.basename(t)] = PCE_DIR
    want[PCE_BASE + ".cue"] = PCE_DIR
    found = 0
    for p in paths:
        p = os.path.abspath(p)
        if p.lower().endswith(".zip"):
            with zipfile.ZipFile(p) as zf:
                names = zf.namelist()
                sat = any("(Track 1).bin" in n for n in names)
                for n in names:
                    base = os.path.basename(n)
                    dest = want.get(base, -1)
                    if base == "Snatcher (Japan).cue":
                        dest = SAT_DIR if sat else PS1_DIR
                    if dest == -1 or dest is None:
                        continue
                    os.makedirs(dest, exist_ok=True)
                    print(f"{p}:{n} -> {os.path.relpath(dest, ROOT)}")
                    with zf.open(n) as src, open(os.path.join(dest, base), "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found += 1
            continue
        files = [p] if os.path.isfile(p) else [os.path.join(dp, f) for dp, _, fs in os.walk(p) for f in fs]
        sat = any(f.endswith("(Track 1).bin") and "CD-ROMantic" not in f for f in files)
        for f in files:
            base = os.path.basename(f)
            dest = want.get(base, -1)
            if base == "Snatcher (Japan).cue":
                dest = SAT_DIR if sat else PS1_DIR
            if dest == -1 or dest is None:
                continue
            os.makedirs(dest, exist_ok=True)
            target = os.path.join(dest, base)
            if os.path.abspath(target) == f:
                continue
            print(f"{f} -> {os.path.relpath(dest, ROOT)}")
            shutil.copyfile(f, target)
            found += 1
    if not found:
        sys.exit("no Snatcher dump files found (names must be the redump ones)")
    cmd_doctor(fonts=False)


def cmd_doctor(fonts=True):
    ok = True
    log("Python")
    print(f"  {sys.version.split()[0]} at {PY}")
    for mod, need in (("numpy", "all"), ("PIL", "all"), ("capstone", "all"), ("cv2", "PS1 intro movie, first build"),
                      ("scipy", "PS1 intro movie, first build")):
        try:
            __import__(mod)
            print(f"  {mod:<8} ok")
        except ImportError:
            print(f"  {mod:<8} MISSING ({need})")
            ok &= need != "all"
    log("Tools")
    for name, need in (("xdelta3", "--release"), ("java", "PS1 intro movie"), ("chdman", "optional")):
        p = tool(name, required=False) if name != "java" else shutil.which("java")
        print(f"  {name:<8} {p or 'MISSING (' + need + ')'}")
    print(f"  jPSXdec  {JPSXDEC_JAR if os.path.exists(JPSXDEC_JAR) else 'fetched on first PS1 build'}")
    if fonts:
        log("Fonts (lib/sysfont.py)")
        import sysfont
        ok &= sysfont.report() == 0
    log("Discs")
    for label, path, want in (("PlayStation", PS1_BIN, PS1_SHA1), ("Saturn", SAT_TRACKS[0], SAT_SHA1)):
        if not os.path.exists(path):
            print(f"  {label:<12} missing: {os.path.relpath(path, ROOT)}")
        else:
            print(f"  {label:<12} {'ok' if verified(path, want) else 'WRONG DUMP (SHA1)'}")
    have = sum(os.path.exists(t) for t in PCE_TRACKS)
    joined = os.path.exists(PCE_JOINED)
    print(f"  {'PC Engine':<12} {have}/24 tracks" + (", joined image present" if joined else ""))
    return ok


def need_ps1():
    if not os.path.exists(PS1_BIN):
        sys.exit(f"PlayStation disc missing: {os.path.relpath(PS1_BIN, ROOT)} (+ .cue) - see `build.py discs`")
    if not verified(PS1_BIN, PS1_SHA1):
        sys.exit(f"{PS1_BIN} is not the redump dump (SHA1 {PS1_SHA1})")


def need_saturn():
    for t in SAT_TRACKS:
        if not os.path.exists(t):
            sys.exit(f"Saturn disc missing: {os.path.relpath(t, ROOT)} - see `build.py discs`")
    if not verified(SAT_TRACKS[0], SAT_SHA1):
        sys.exit(f"{SAT_TRACKS[0]} is not the redump dump (SHA1 {SAT_SHA1})")


# --- preparation --------------------------------------------------------------

def prep_ps1():
    """Extracted files, the Snatcher art the boot screens borrow, the text refs."""
    need_ps1()
    if not os.path.exists(os.path.join(DISCS, "extracted_ps1", "SLPS_001.54")):
        log("PS1: extracting the disc")
        with keep("work/lba_map.json"):
            run(["ps1/tools/extract_ps1.py"])
    parts = os.path.join(WORK, "gfx", "all", "CXE_B0D0_items", "CXE_B0D0_g1_00_8bpp.png")
    if not os.path.exists(parts):
        log("PS1: rendering CXE_B0D0 (the boot screens' Snatcher)")
        d = os.path.join(WORK, "gfx", "all")
        os.makedirs(d, exist_ok=True)
        shutil.copyfile(os.path.join(DISCS, "extracted_ps1", "DES", "CXE", "CXE_B0D0.BIN"),
                        os.path.join(d, "CXE_B0D0.BIN"))
        run(["ps1/tools/gfx.py", "render", os.path.join(d, "CXE_B0D0.BIN")])
        if not os.path.exists(parts):
            sys.exit(f"gfx.py render did not write {parts}")
    if not os.path.exists(os.path.join(WORK, "ref", "ISZ_B260.json")):
        log("PS1: the Japanese text references (work/ref)")
        with keep("ps1/translation"):
            run(["ps1/tools/dump_strings.py"])


def prep_saturn():
    need_saturn()
    if not os.path.exists(os.path.join(DISCS, "extracted_saturn", "DATA.BIN")):
        log("Saturn: extracting the disc")
        run(["saturn/tools/extract.py"])


def prep_saturn_text():
    prep_ps1()
    prep_saturn()
    if not os.path.exists(os.path.join(WORK, "saturn", "carry", "SAT_025_B040.json")):
        log("Saturn: the text references (work/saturn/ref, work/saturn/carry)")
        run(["saturn/tools/satdata.py", "script"])
        with keep("saturn/translation"):
            run(["saturn/tools/satcarry.py", "run"])
    if not os.path.exists(os.path.join(WORK, "saturn", "data", "022_B010.bin")):
        log("Saturn: the original scene banks (work/saturn/data, read by the harness)")
        run(["saturn/tools/satdata.py", "dump"] + [str(n) for n in range(21, 60)])


def prep_pce():
    prep_ps1()
    if not (os.path.exists(PCE_JOINED) and verified(PCE_JOINED, PCE_SHA1)):
        missing = [t for t in PCE_TRACKS if not os.path.exists(t)]
        if missing:
            sys.exit(f"PC Engine disc missing: {os.path.relpath(missing[0], ROOT)} "
                     f"({len(missing)} of 24 track files) - see `build.py discs`")
        log("PC Engine: joining the 24 tracks into work/pce/snatcher_pce.bin")
        os.makedirs(os.path.dirname(PCE_JOINED), exist_ok=True)
        with open(PCE_JOINED, "wb") as out:
            for t in PCE_TRACKS:
                with open(t, "rb") as f:
                    shutil.copyfileobj(f, out, 1 << 22)
        if not verified(PCE_JOINED, PCE_SHA1):
            os.remove(PCE_JOINED)
            sys.exit(f"the joined PC Engine tracks are not the redump dump (SHA1 {PCE_SHA1})")
    if not os.path.exists(PCE_JOINED[:-4] + ".cue"):
        write_pce_cue()
    if not os.path.exists(os.path.join(WORK, "pce", "filetable.json")):
        log("PC Engine: the file table")
        run(["pce/tools/pcetable.py"])


def write_pce_cue():
    """The single-file cue of the joined image, from the redump cue: each
    track's INDEX times moved by the size of the files before it (what
    `chdman extractcd` writes)."""
    src = os.path.join(PCE_DIR, PCE_BASE + ".cue")
    if not os.path.exists(src):
        sys.exit(f"{src} missing")
    out, offset = [f'FILE "{os.path.basename(PCE_JOINED)}" BINARY'], 0

    def msf(frames):
        return f"{frames // 4500:02d}:{frames // 75 % 60:02d}:{frames % 75:02d}"
    for line in open(src, encoding="utf-8", errors="replace"):
        w = line.split()
        if not w:
            continue
        if w[0] == "FILE":
            name = line.split('"')[1]
            cur = offset
            offset += os.path.getsize(os.path.join(PCE_DIR, name)) // 2352
        elif w[0] == "TRACK":
            out.append(f"  TRACK {w[1]} {w[2]}")
        elif w[0] == "INDEX":
            m, s, f = (int(x) for x in w[2].split(":"))
            out.append(f"    INDEX {w[1]} {msf(cur + (m * 60 + s) * 75 + f)}")
    with open(PCE_JOINED[:-4] + ".cue", "w", newline="\n") as f:
        f.write("\n".join(out) + "\n")


# --- PlayStation --------------------------------------------------------------

def ps1_chain(variant):
    """Build-Image.bat: the translated image, `censored` or `uncensored`."""
    run(["ps1/tools/check_strings.py", "--all", "--quiet"], check=False)
    for step in (["apply_translation.py"], ["keytable.py", "apply"], ["repoint.py"],
                 ["patch_keyboard.py"], ["kbdfaces.py", "apply"], ["specialmenu.py", "apply"],
                 ["specialitem.py", "apply"], ["gfxpages.py", "apply"], ["gfxlabels.py", "apply"],
                 ["disclaimer.py", "apply"], ["staffroll.py", "apply"], ["introcaption.py", "apply"],
                 ["introdiagram.py", "apply"]):
        run(["ps1/tools/" + step[0]] + step[1:])
    for s in PS1_SCENES:
        run(["ps1/subs/subs_cue.py", "on", f"ps1/translation/subs_{s}.json", "--scene", s])
    if variant == "uncensored":
        run(["ps1/tools/uncensor.py", "--lisa-saturn"], env={"SNATCHER_SATURN": ROOT})
    else:
        for f in ("CXK_B062.BIN", "CXF_B080.BIN"):     # what uncensor.py writes
            p = os.path.join(PATCHED, f)
            if os.path.exists(p):
                os.remove(p)
    for step in (["wordwrap.py", "apply"], ["pageplate.py", "apply"], ["bootcard.py", "apply"],
                 ["patch_disc.py"]):
        run(["ps1/tools/" + step[0]] + step[1:])


def ps1_fmv(image_env):
    """The intro movie's English credits: frames repainted once (cached in
    work/gfx/str/out), re-encoded into the image by jPSXdec."""
    ensure_jpsxdec()
    if not shutil.which("java"):
        sys.exit("java not found: the PS1 intro movie needs it (or build with --no-fmv)")
    out = os.path.join(WORK, "gfx", "str", "out")
    if not (os.path.isdir(out) and any(n.endswith(".png") for n in os.listdir(out))):
        log("PS1: repainting the intro movie's frames (once; needs opencv-python and scipy)")
        run(["ps1/tools/fmvtext.py", "frames"], env=image_env)
        run(["ps1/tools/fmvtext.py", "build"], env=image_env)
    run(["ps1/tools/fmvtext.py", "apply"], env=image_env)


def cmd_ps1(a):
    prep_ps1()
    variants = ["censored", "uncensored"] if a.variant == "both" else [a.variant]
    if "uncensored" in variants and not os.path.exists(os.path.join(WORK, "saturn", "sat_433.png")):
        prep_saturn()                    # uncensor.py renders one Saturn picture, once
    if a.release and (a.variant != "both" or a.no_fmv):
        sys.exit("--release builds both variants with the intro movie")
    for v in variants:
        img = CENSORED_IMG if (v == "censored" and len(variants) == 2) else "Snatcher (Japan)"
        env = {"SNATCHER_IMAGE": img}
        os.environ["SNATCHER_IMAGE"] = img          # patch_disc.py and fmvtext.py read it
        bin_path = os.path.join(PATCHED, img + ".bin")
        if os.path.exists(bin_path):
            os.remove(bin_path)          # patch_disc copies pristine only when the image is absent
        log(f"PS1: building the {v} image -> patched/{img}.bin")
        ps1_chain(v)
        if a.no_fmv:
            continue
        if v == variants[0]:
            ps1_fmv(env)
        else:
            run(["ps1/tools/fmvtext.py", "mirror", CENSORED_IMG], env=env)
    if a.release:
        log("PS1: verifying the two variants")
        run(["ps1/tools/check_variant.py", "censored"])
        run(["ps1/tools/check_variant.py", "uncensored"])
        run(["lib/stamp_notes.py"])
        log("PS1: patches")
        tool("xdelta3")                  # fetched into lib/xdelta on Windows when missing
        run(["ps1/tools/ps1release.py"])


# --- Saturn -------------------------------------------------------------------

SATURN_CHAIN = [
    ["saturn/tools/satapply.py"], ["saturn/tools/satnames.py", "apply"], ["saturn/tools/satlong.py"],
    ["saturn/tools/satkeys.py", "apply"], ["saturn/tools/satkeys.py", "faces"],
    ["saturn/subs/satsubs.py", "--all"], ["saturn/tools/satwrap.py"], ["saturn/tools/satspecial.py"],
    ["saturn/tools/satoptmenu.py"], ["saturn/tools/satpages.py", "apply"],
    ["saturn/tools/satroll.py", "apply"], ["saturn/tools/satlabels.py", "apply"],
    ["saturn/tools/satpack.py"], ["saturn/tools/satsplash.py", "apply"], ["saturn/tools/satdisc.py"],
]


def cmd_saturn(a):
    prep_saturn_text()
    log("Saturn: building -> patched/saturn/")
    for step in SATURN_CHAIN:
        run(step)
    if a.release:
        log("Saturn: patches")
        tool("xdelta3")                  # satrelease reads lib/xdelta or PATH
        run(["saturn/tools/satrelease.py"])


# --- PC Engine ----------------------------------------------------------------

PCE_CHAIN = ["pcescript", "titlemenu", "opencards", "pcekeyboard", "pcesearch", "pcesubs", "pcelongs",
             "pcecredits", "pceending", "pcecards", "pcelabels", "pceopening", "pcesplash", "pcecdguard"]


def cmd_pce(a):
    prep_pce()
    log("PC Engine: building -> patched/pce/")
    for name in PCE_CHAIN:
        run([f"pce/tools/{name}.py", "apply"])
    run(["pce/tools/pceverify.py"])
    if a.release:
        log("PC Engine: patch")
        tool("xdelta3")
        run(["pce/tools/pcerelease.py"])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("fetch", help="download jPSXdec (and xdelta3.exe on Windows) into lib/")
    p = sub.add_parser("discs")
    p.add_argument("paths", nargs="+")
    for name in ("ps1", "saturn", "pce", "all"):
        p = sub.add_parser(name)
        p.add_argument("--release", action="store_true", help="also make the patches and the zip")
        if name in ("ps1", "all"):
            p.add_argument("--variant", default="both", choices=["both", "censored", "uncensored"])
            p.add_argument("--no-fmv", action="store_true", help="skip the intro movie's English credits")
    a = ap.parse_args()
    t0 = time.time()
    if a.cmd == "doctor":
        sys.exit(0 if cmd_doctor() else 1)
    if a.cmd == "discs":
        return cmd_discs(a.paths)
    if a.cmd == "fetch":
        if os.name == "nt" and not os.path.exists(os.path.join(ROOT, "lib", "xdelta", "xdelta3.exe")):
            fetch_xdelta()
        ensure_jpsxdec()
        return
    if a.cmd in ("ps1", "all"):
        cmd_ps1(a)
    if a.cmd in ("saturn", "all"):
        cmd_saturn(a)
    if a.cmd in ("pce", "all"):
        cmd_pce(a)
    log(f"done in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
