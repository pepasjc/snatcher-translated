# -*- coding: utf-8 -*-
"""The full Saturn regression: static checks, every scene save, the whole game from New
Game, the coverage routes - then one verdict with a coverage gate.

    python saturn/harness/regress_full.py [--jobs N] [--out DIR] [--skip-whole] [--only static|play]
    python saturn/harness/regress_full.py --verdict DIR      (re-judge finished runs, run nothing)

1. Static (seconds): satverify.py on the image and the dev-test image (every pair glyph read
   back from the image), satcardlint.py (the card rules and geometry over every cue file),
   satplay.py --lint (rows over the box / the terminal), the harness unit tests.
2. Play, in parallel:
   - regress_saves.py on the release image: every scene save, its route or the generic sweep;
   - satwhole.py on the dev-test image (devtest.py: shots always hit, so no route dies in a
     fight): New Game to the final subtitle in one session, nothing restored;
   - then regress_saves --deep (every verb four times, every room three times) and the
     COVERAGE routes below, each from a bookmark: what the story path and the sweeps miss.
   Every satplay run carries satsubcheck's checks (missed / uncarded / out-of-sync / stuck /
   inkless cards, font, glyph table, allocator) beside satplay's own (JP, BLANK, GARBAGE,
   WIDE, FROZEN, INVISIBLE, WEDGE, faces).
3. Verdict: satcoverage.py --gate over every run (all 39 banks loaded, every cue read or
   documented unreachable, not below the committed floor) and every PROBLEM line of every
   run judged by kind: SERIOUS fail the regression, NOTED are listed.

Output DIR (default work/saturn/regress_full): one directory per run, static.txt,
coverage.txt / coverage.json, verdict.txt. Exit 1 on any failure. Never build while it runs.
"""
import argparse, collections, glob, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'saturn/tools', 'saturn/harness', 'saturn/subs')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PY = sys.executable
IMAGE = os.path.join(ROOT, "patched", "saturn", "Snatcher (Japan).cue")
DEV = os.path.join(ROOT, "patched", "saturn", "Snatcher (Japan) [dev-test].cue")
OUT = os.path.join(WORK, "saturn", "regress_full")
ROUTES = os.path.join(HERE, "routes")

# a problem of these kinds fails the regression
SERIOUS = {"JP", "BLANK", "GARBAGE", "WIDE", "LABEL", "FULL", "FROZEN", "INVISIBLE", "WEDGE", "INKLESS",
           "STUCK-CARD", "DESYNC", "MISSED-CUE", "UNCARDED", "FONT", "HEAP", "FACE", "WRONG-FACE",
           "TEXT-OVER-FACE", "SPRITE-OFF-WINDOW", "JP?", "UNMATCHED-BAND"}
# listed, not failing: PAD (Luiz keeps the half-cell before a colour code, as the PS1), DEATH (a
# lost shootout on the release image; the route continues), UNMATCHED (engine text no bank
# string accounts for), untranslated (a string with no `en`: lock records, kept Japanese)
NOTED = {"PAD", "DEATH", "UNMATCHED", "untranslated"}

# (name, route in saturn/harness/routes, start bookmark in work/saturn/states). The `<save>_rg`
# bookmarks are the ones regress_saves boots from the scene saves on THIS image (so these run
# after it); "new" = New Game through the opening (a bookmark keeps the bank text it was made
# with - B010_start showed an old build's curly apostrophes, 2026-11-06); cov_B120_bath is a
# whole-game state copied into the bookmarks. Each reaches cues no story route and no sweep reaches.
COVERAGE = [
    ("B010_reroute", "cov_B010_reroute.json", "new"),
    ("B0D0_teller", "cov_B0D0_teller.json", "B0D0_start_manual_rg"),
    ("B0C0_indecent", "cov_B0C0_indecent.json", "B0C0_start_manual_rg"),
    ("B120_indecent", "cov_B120_indecent.json", "cov_B120_bath"),
    ("B100_showid", "cov_B100_showid.json", "B100_start_manual_rg"),
    ("phone_B060", "cov_phone_B060.json", "B080_after_outer_heaven_manual_rg"),
    ("phone_B070", "cov_phone_B070.json", "B150_start_manual_rg"),
    ("phone_extra_act1", "cov_phone_extra.json", "B080_after_outer_heaven_manual_rg"),
    ("phone_extra_act2", "cov_phone_extra.json", "B150_start_manual_rg"),
    ("B040_search", "cov_B040_search.json", "B150_start_manual_rg"),
    # cov_B100_binge = the whole-game run's state at the end of stage 07 (in Outer Heaven);
    # it and cov_B120_bath carry their build's font: after a rebuild re-mint both from the
    # new whole run (stages/07_*, states/start_B120_*) - the verdict fails STALE-BOOKMARK
    ("B100_binge_hq", "cov_B100_binge_hq.json", "cov_B100_binge"),
]


def run(cmd, log_path, timeout=None, env=None):
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8") as fh:
        try:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT, timeout=timeout,
                                env=dict(os.environ, **(env or {}))).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    return rc, time.time() - t0


def static(out, image, dev):
    lines, ok = [], True
    checks = [("satverify image", [PY, "saturn/tools/satverify.py", image]),
              ("satverify dev-test", [PY, "saturn/tools/satverify.py", dev]),
              ("satcardlint", [PY, "saturn/subs/satcardlint.py"]),
              ("harness tests", [PY, "-m", "pytest", "-q", "saturn/harness/tests"])]
    for name, cmd in checks:
        if "dev-test" in name and not os.path.exists(dev):
            lines.append(f"{name}: SKIPPED (no {os.path.basename(dev)})"); continue
        log = os.path.join(out, f"static_{name.replace(' ', '_')}.log")
        rc, _ = run(cmd, log)
        tail = open(log, encoding="utf-8", errors="replace").read().strip().splitlines()
        lines.append(f"{name}: {'ok' if rc == 0 else 'FAIL'}  {tail[-1] if tail else ''}")
        ok &= rc == 0
    log = os.path.join(out, "static_lint.log")
    run([PY, "saturn/harness/satplay.py", "--lint", "--image", image], log)
    text = open(log, encoding="utf-8", errors="replace").read()
    wide = [l for l in text.splitlines() if re.match(r"^  off \d+: \d+ > \d+", l)]
    labels = [l for l in text.splitlines() if "LABEL" in l]
    lines.append(f"satplay --lint: {'ok' if not wide else 'FAIL'}  {len(wide)} rows over the box" +
                 "".join("\n    " + w for w in wide[:20]))
    ok &= not wide
    open(os.path.join(out, "static.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)
    return ok


def play(out, image, dev, jobs, skip_whole):
    # phase 1: the whole game (its own session, hours) beside the scene saves (they also
    # mint the `<save>_rg` bookmarks phase 2 starts from); phase 2: the deep sweep over every
    # save and the coverage routes, while the whole game goes on
    import threading
    whole = None
    if not skip_whole:
        wd = os.path.join(out, "whole")
        whole = threading.Thread(target=lambda: print("-- whole: rc", run(
            [PY, "saturn/harness/satwhole.py", "run", "--out", wd, "--image", dev, "--no-calib"],
            os.path.join(out, "whole.log"), 12 * 3600)[0], flush=True))
        whole.start()
    print("== regress_saves", flush=True)
    rc, dt = run([PY, "saturn/harness/regress_saves.py", "--jobs", str(max(1, jobs - 1)), "--image", image],
                 os.path.join(out, "regress_saves.log"), 6 * 3600)
    print(f"-- regress_saves: rc {rc}, {dt / 60:.0f} min", flush=True)
    tasks = [("regress_deep", [PY, "saturn/harness/regress_saves.py", "--deep", "--reuse", "--jobs",
                               str(max(1, jobs // 2)), "--frames", "150000", "--image", image], None, 8 * 3600)]
    for name, route, start in COVERAGE:
        d = os.path.join(out, "cov", name)
        os.makedirs(d, exist_ok=True)
        cmd = [PY, "saturn/harness/satplay.py", "--route", os.path.join(ROUTES, route), "--out", d,
               "--no-autosave", "--image", dev, "--frames", "200000"]
        cmd += ["--new"] if start == "new" else ["--state", start]
        tasks.append((f"cov_{name}", cmd, {"EMU_SAVE_DIR": os.path.join(d, "emu")}, 3 * 3600))

    def one(t):
        name, cmd, env, timeout = t
        print(f"== {name}", flush=True)
        rc, dt = run(cmd, os.path.join(out, f"{name}.log"), timeout, env)
        print(f"-- {name}: rc {rc}, {dt / 60:.0f} min", flush=True)
        return name, rc
    with ThreadPoolExecutor(max_workers=max(2, jobs // 2)) as ex:
        res = list(ex.map(one, tasks))
    if whole:
        whole.join()
    return res


def run_dirs(out):
    dirs = [os.path.join(WORK, "saturn", "regress"), os.path.join(WORK, "saturn", "regress_deep")]
    for d in [os.path.join(out, "whole")] + glob.glob(os.path.join(out, "cov", "*")):
        if os.path.isdir(d):
            dirs.append(d)
    return dirs


def verdict(out):
    import satcoverage
    dirs = run_dirs(out)
    lines = []
    cov_txt = os.path.join(out, "coverage.txt")
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        gate = satcoverage.report(dirs, os.path.join(out, "coverage.json"), gate=True)
    open(cov_txt, "w", encoding="utf-8").write(buf.getvalue())
    lines.append(buf.getvalue().strip())
    probs = collections.Counter()
    serious = []
    for d in dirs:
        for log in glob.glob(os.path.join(d, "**", "log.txt"), recursive=True):
            for raw in open(log, encoding="utf-8", errors="replace"):
                m = re.match(r"^(\d+): PROBLEM (\S+) (.*)$", raw)
                if m:
                    probs[m.group(2)] += 1
                    if m.group(2) in SERIOUS:
                        serious.append(f"{os.path.relpath(log, ROOT)}: {raw.strip()[:300]}")
                # a bookmark from another build keeps that build's VDP1 font: the bank text
                # draws as garbage the checks cannot see (cov_B100_binge, 2026-11-07) -
                # re-mint it from this build's whole-game run
                if "carries another build's font" in raw:
                    probs["STALE-BOOKMARK"] += 1
                    serious.append(f"{os.path.relpath(log, ROOT)}: {raw.strip()[:300]}")
                for k in ("WRONG-FACE", "TEXT-OVER-FACE", "SPRITE-OFF-WINDOW"):
                    if re.search(rf": {k} ", raw) and " face " in raw:
                        probs[k] += 1
                        serious.append(f"{os.path.relpath(log, ROOT)}: {raw.strip()[:300]}")
    lines.append(f"problems by kind: {dict(probs)}")
    lines.append(f"serious: {len(serious)}")
    lines += ["  " + s for s in serious[:200]]
    st = os.path.join(out, "static.txt")
    static_ok = os.path.exists(st) and "FAIL" not in open(st, encoding="utf-8").read()
    lines.append(f"static: {'ok' if static_ok else 'FAIL or not run'}")
    ok = gate == 0 and not serious and static_ok
    lines.append("REGRESSION " + ("PASS" if ok else "FAIL"))
    open(os.path.join(out, "verdict.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", default=IMAGE)
    ap.add_argument("--dev", default=DEV)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--skip-whole", action="store_true")
    ap.add_argument("--only", choices=("static", "play"))
    ap.add_argument("--verdict", metavar="DIR")
    a = ap.parse_args()
    if a.verdict:
        sys.exit(0 if verdict(a.verdict) else 1)
    os.makedirs(a.out, exist_ok=True)
    if a.only != "play":
        static(a.out, a.image, a.dev)
        if a.only == "static":
            return
    play(a.out, a.image, a.dev, a.jobs, a.skip_whole)
    sys.exit(0 if verdict(a.out) else 1)


if __name__ == "__main__":
    main()
