"""The PC Engine regression, whole: every check, every scene, and the coverage gate.

    python pce/harness/regress.py [--jobs N] [--image CUE] [--only KEY ...] [--out DIR]

Freezes a copy of the image (a build may run while this does), then runs in parallel:

  opening   opening_check.py: the opening's 30 pages read off the screen
  act1      playthrough.py from a fresh boot through act1_g (glitchwatch on)
  act2      playthrough.py from the act2_0 save (the recap) through act2_i
  act3      playthrough.py from the act3_0 save through the ending
  saves     regress_saves.py: every scene save in the library, its sweep
  cov_*     the coverage routes (coverage_routes.json): branches the act routes do not take

and offline: sync_audit.py (page turns against the Japanese words), table_check.py
(every line decoded back from the image). Then judges the logs:

  subtext.py       every page in RAM against its English (WRONG TEXT, BAD GLYPH), every
                   page on screen against RAM (GARBLED ON SCREEN), page turns on screen
                   against `turns` (LATE TURN)
  voice_coverage   --gate: every module loaded, every voice line played, every CD-DA cue
                   shown, or excused in coverage_known.json
  glitchwatch      hang / garbled / band / invisible / dupe / blink events in the playthroughs
  the runs         an act route that stopped, a save that did not boot or sat stuck

Exit 1 on any of them. Summary: <out>/summary.txt (default work/pce/reg/latest).
"""
import argparse, glob, json, os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'pce/tools', 'pce/harness')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PY = sys.executable
FAIL_GLITCH = {"hang", "garbled", "band", "invisible", "dupe", "blink"}
ROUTES = os.path.join(HERE, "coverage_routes.json")


def jobs_for(img_cue, out, save_jobs):
    j = {
        "opening": [PY, "pce/harness/opening_check.py", "--image", img_cue, "--out", os.path.join(out, "opening")],
        "act1": [PY, "pce/harness/playthrough.py", os.path.join(out, "act1"), img_cue, "--until", "act1_g", "--endsave"],
        "act2": [PY, "pce/harness/playthrough.py", os.path.join(out, "act2"), img_cue, "--bram", "act2_0",
                 "--from", "act2_a", "--until", "act2_i", "--endsave"],
        "act3": [PY, "pce/harness/playthrough.py", os.path.join(out, "act3"), img_cue, "--bram", "act3_0",
                 "--from", "act3_a", "--pre", '[{"read": 40000}]', "--skip", "4"],   # (act3_a opens on act 2's save prompt)
        "saves": [PY, "pce/harness/regress_saves.py", "--jobs", str(save_jobs), "--image", img_cue,
                  "--outdir", os.path.join(out, "saves")],
    }
    if os.path.exists(ROUTES):
        for name, spec in json.load(open(ROUTES, encoding="utf-8")).items():
            if name.startswith("_"):
                continue
            j[f"cov_{name}"] = [PY, "pce/harness/coverage_run.py", name, "--image", img_cue,
                                "--out", os.path.join(out, f"cov_{name}")]
    return j


def run(cmd, log):
    os.makedirs(os.path.dirname(log), exist_ok=True)
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT,
                            env=dict(os.environ, PYTHONIOENCODING="utf-8")).returncode
    return rc, int(time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6, help="emulator jobs at once (the saves take 2 of them)")
    ap.add_argument("--image", default=os.path.join(ROOT, "patched", "pce", "snatcher_pce.cue"))
    ap.add_argument("--out", default=os.path.join(WORK, "pce", "reg", "latest"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--judge", action="store_true", help="only judge the logs already in --out")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    lines, bad = [], 0
    t_all = time.time()
    if not a.judge:
        # the image, frozen: a build writes patched/pce in place
        img = os.path.join(out, "img")
        os.makedirs(img, exist_ok=True)
        src_bin = os.path.splitext(a.image)[0] + ".bin"
        shutil.copyfile(src_bin, os.path.join(img, "snatcher_pce.bin"))
        shutil.copyfile(a.image, os.path.join(img, "snatcher_pce.cue"))
        cue = os.path.join(img, "snatcher_pce.cue")
        jobs = jobs_for(cue, out, 2)
        if a.only:
            jobs = {k: v for k, v in jobs.items() if k in a.only}
        # the longest first: act2 and act3 take hours, the coverage routes minutes
        order = sorted(jobs, key=lambda k: {"act2": 0, "act3": 1, "act1": 2, "saves": 3}.get(k, 5))
        print(f"{len(order)} jobs: {', '.join(order)}", flush=True)
        offline = {}
        for name, cmd in (("sync_audit", [PY, "pce/harness/sync_audit.py"]),
                          ("table_check", [PY, "pce/harness/table_check.py", "--image", os.path.join(img, "snatcher_pce.bin")])):
            offline[name] = run(cmd, os.path.join(out, f"{name}.log"))
            print(f"{name}: rc {offline[name][0]}", flush=True)

        def go(name):
            rc, secs = run(jobs[name], os.path.join(out, f"{name}.log"))
            print(f"-- {name}: rc {rc}, {secs} s", flush=True)
            return name, rc, secs
        with ThreadPoolExecutor(max_workers=max(1, a.jobs - 1)) as ex:
            results = list(ex.map(go, order))
        json.dump({"offline": offline, "jobs": results}, open(os.path.join(out, "jobs.json"), "w"), indent=1)
    state = json.load(open(os.path.join(out, "jobs.json")))
    lines.append(f"PCE regression - {time.strftime('%Y-%m-%d %H:%M')} - {out}")
    for name, (rc, secs) in state["offline"].items():
        tail = open(os.path.join(out, f"{name}.log"), encoding="utf-8", errors="replace").read().strip().splitlines()[-1:]
        lines.append(f"{'FAIL' if rc else 'ok  '} {name:12} {tail[0] if tail else ''}")
        bad += bool(rc)
    for name, rc, secs in state["jobs"]:
        note = ""
        if name.startswith(("act", "cov_")):
            sp = os.path.join(out, name, "summary.json")
            summ = json.load(open(sp)) if os.path.exists(sp) else []
            stopped = [s for s in summ if s["ended"] != "done"]
            kinds = {}
            for s in summ:
                for k, n in s["glitches"].items():
                    kinds[k] = kinds.get(k, 0) + n
            failing = {k: n for k, n in kinds.items() if k in FAIL_GLITCH}
            note = (f"{len(summ)} routes, " + (f"STOPPED {stopped[0]['route']}: {stopped[0]['ended']}; " if stopped else "")
                    + f"glitches {kinds or 'none'}")
            rc = rc or bool(stopped) or bool(failing) or not summ
        elif name == "saves":
            sp = os.path.join(out, "saves", "summary.txt")
            note = open(sp, encoding="utf-8").read().strip().splitlines()[-1] if os.path.exists(sp) else "no summary"
        else:
            log = os.path.join(out, f"{name}.log")
            t = open(log, encoding="utf-8", errors="replace").read().strip().splitlines() if os.path.exists(log) else []
            note = t[-1] if t else ""
        lines.append(f"{'FAIL' if rc else 'ok  '} {name:12} {note[:150]} ({secs} s)")
        bad += bool(rc)
    # the logs: pages against the English and the screen, page turns, coverage
    logs = [p for p in glob.glob(os.path.join(out, "**", "*.log"), recursive=True)
            if os.path.basename(p) not in ("sync_audit.log", "table_check.log")]
    r = subprocess.run([PY, "pce/harness/subtext.py"] + logs, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    open(os.path.join(out, "subtext.txt"), "w", encoding="utf-8").write(r.stdout)
    tail = r.stdout.strip().splitlines()
    lines.append(f"{'FAIL' if r.returncode else 'ok  '} {'pages':12} {tail[-1] if tail else ''}")
    lines += ["       " + l for l in tail[:-1] if l.strip()][:40]
    bad += bool(r.returncode)
    r = subprocess.run([PY, "pce/harness/voice_coverage.py", out, "--gate"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8")
    open(os.path.join(out, "coverage.txt"), "w", encoding="utf-8").write(r.stdout)
    cov = r.stdout.strip().splitlines()
    gate = [l for l in cov if l.startswith(("NOT COVERED", "STALE"))]
    summary = [l for l in cov if "subtitled voice lines played" in l or l.startswith("coverage gate")]
    lines.append(f"{'FAIL' if r.returncode else 'ok  '} {'coverage':12} " + " | ".join(summary))
    lines += ["       " + l for l in gate[:60]]
    bad += bool(r.returncode)
    lines.append(f"{bad} check(s) failed; {int(time.time() - t_all)} s")
    open(os.path.join(out, "summary.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
