# -*- coding: utf-8 -*-
"""The partial regression over Luiz's scene saves: every save in the library that
names a bank is booted on the current image (satsave_check: CONTINUE, the file, the
bank's verb menu -> a bookmark `<save>_rg`), then the scene is played standalone
from that bookmark with satplay (its route where one fits the save, else the
generic sweep: every verb twice, then every room once) and the run's verdicts
are tabled - cards, cues drawn, face problems, wedges. The Act 1 end save plays
the Act 2 recap through saturn/harness/probe_recap.py instead (no verb
menu until B150).

    python saturn/harness/regress_saves.py [SAVE...] [--frames N] [--reuse] [--image CUE] [--jobs N]

`--reuse` skips the boot when `<save>_rg` exists. Output: work/saturn/regress/
<save>/ per run (satplay's log, cards, captures) and work/saturn/regress/
summary.txt. Route saves are stripped from the routes it runs (a route's `save`
overwrites the bookmark it names).

`--jobs` (default 4) runs that many saves at once - each is its own
process pair (boot, then play), the image is only read, and the harness
counts frames, so the verdicts do not depend on the load. The one file
the runs used to share is the core's backup RAM, `work/emu/<image>.bkr`,
which the boot writes before load and Beetle Saturn writes back at unload:
each run gets its own through EMU_SAVE_DIR (lib/emurun.py, satsave.py),
work/saturn/regress/<save>/emu. 22 saves at ~12 min each ran 4+ hours in
a row; at 4 jobs the wall time is about a quarter of that.
"""
import argparse, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'saturn/tools', 'saturn/harness', 'saturn/subs')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = os.path.join(WORK, "saturn", "regress")
ROUTES = os.path.join(ROOT, "saturn", "harness", "routes")
IMAGE = os.path.join(ROOT, "patched", "saturn", "Snatcher (Japan).cue")
PY = sys.executable

GENERIC = {"note": "the generic scene sweep: every verb twice at the arrival, then every room once",
           "actions": [{"wait_menu": True, "patience": 8000},
                       {"sweep": ["Look", "Investigate", "Talk", "Ask", "Sniff", "Listen"], "rounds": 2},
                       {"sweep": ["Move"], "each": ["Look", "Investigate", "Ask", "Talk"], "each_rounds": 1,
                        "avoid": ["Go out", "Board Tricycle", "Exit Tricycle", "Tricycle", "Leave", "Front", "Exit"]},
                       {"idle": 300}]}

# the coverage pass (--deep): lines a scene gives only on the third or fourth look, a room
# visited again, an item shown twice
DEEP = {"note": "the deep sweep: every verb four times, every room three times, every item shown",
        "actions": [{"wait_menu": True, "patience": 8000},
                    {"sweep": ["Look", "Investigate", "Talk", "Ask", "Sniff", "Listen", "Smell", "Knock",
                               "Buy something", "Hear", "Call", "Yell", "Peek", "Press him", "Order"], "rounds": 4},
                    {"sweep": ["Item"], "rounds": 2},
                    {"sweep": ["Move"], "each": ["Look", "Investigate", "Ask", "Talk", "Sniff", "Listen",
                                                 "Buy something", "Item"], "each_rounds": 3, "rounds": 2,
                     "avoid": ["Go out", "Board Tricycle", "Exit Tricycle", "Tricycle", "Leave", "Front", "Exit"]},
                    {"idle": 300}]}
# save -> (route file or None for the generic sweep); the recap save is special
ROUTE_FOR = {
    "B080_after_outer_heaven_manual": os.path.join(ROUTES, "B080.json"),
    "B080_computer_manual": os.path.join(ROUTES, "B080.json"),
    "B0C0_start_manual": os.path.join(ROUTES, "B0C0_disk.json"),
    "B0D0_start_manual": os.path.join(ROUTES, "B0D0_full.json"),
    "B0E0_start_manual": os.path.join(ROUTES, "B0E0_sweeps.json"),
    # the autopilot's Act 3 saves (2026-09-17) with the routes that minted them
    "B200_auto": os.path.join(ROUTES, "B200.json"),
    "B220_auto": os.path.join(ROUTES, "B220.json"),
    "B230_auto": os.path.join(ROUTES, "B230.json"),
    "B240_auto": os.path.join(ROUTES, "B240.json"),
}
RECAP = {"act1_end_manual"}
# runs from power-on (no save reaches them: B010 has no Metal Gear to save with): name -> route.
# The scene saves start at B020, so before 2026-10-01 nothing replayed JUNKER HQ after a build
# and the navigator reel's frozen card shipped in v1.0.
NEWGAME = {"B010_newgame": os.path.join(ROUTES, "B010_full.json")}
# a save minted past its route's opening: the actions before this index are dropped
# (B240_auto sits at the tricycle after the quiz - the quiz picks are optional and
# their patience ate the whole frame budget, 0 cards)
START_AT = {"B240_auto": 11}
# the saves worth a run: Luiz's per bank first, the harness's autos where he has none
PREFER = ["B010_newgame", "B020_auto", "B080_after_outer_heaven_manual", "B0B0_front_manual", "act2_apartment_prejamie_manual",
          "B0C0_start_manual", "B0D0_start_manual", "B0E0_start_manual", "B0F0_start_manual", "B100_start_manual",
          "B110_start_manual", "B120_start_manual", "act1_end_manual", "B150_start_manual", "B190_start_manual",
          "B1B0_start_manual", "B1C0_start_manual", "B1D0_start_manual", "B1E0_start_manual",
          "B200_auto", "B220_auto", "B230_auto", "B240_auto"]


def run(cmd, log_path, timeout, env=None):
    with open(log_path, "w", encoding="utf-8") as fh:
        t0 = time.time()
        try:
            p = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout, cwd=ROOT,
                               env=dict(os.environ, **(env or {})))
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    return rc, time.time() - t0


def stripped_route(path, dst, start=0):
    r = json.load(open(path, encoding="utf-8")) if path else dict(GENERIC)
    r = dict(r)
    # the dropped opening keeps its fight aims (else the church's insectors are shot with the default)
    r["actions"] = [a for a in r["actions"][:start] if "fight" in a] + \
                   [a for a in r["actions"][start:] if not ("save" in a or "bsave" in a or "mcard" in a)]
    json.dump(r, open(dst, "w", encoding="utf-8"), indent=1)
    return dst


def summarize_play(log):
    text = open(log, encoding="utf-8", errors="replace").read()
    ms = re.findall(r"^  (B[0-9A-F]{3}): (\d+) frames, (\d+) cards, (\d+) menus, (\d+) problems", text, re.M)
    probs = re.search(r"^  problems: (\{.*?\});", text, re.M)
    return {
        "bank": "+".join(m[0] for m in ms) if ms else "?",
        "frames": sum(int(m[1]) for m in ms),
        "cards": sum(int(m[2]) for m in ms),
        "problems": probs.group(1) if probs else "?",
        "cues": len(re.findall(r"\(cue [A-Za-z0-9_]+,", text)),
        "face_ok": len(re.findall(r"\bface-ok\b", text)),
        "face_bad": len(re.findall(r"WRONG-FACE|PORTRAIT-PARKED|TEXT-OVER-FACE|SPRITE-OFF-WINDOW", text)),
        "plain_in_band": len(re.findall(r"plain-in-band", text)),
        "wedged": len(re.findall(r"WEDGED", text)),
        "never_took": len(re.findall(r"never took", text)),
    }


def summarize_recap(log):
    text = open(log, encoding="utf-8", errors="replace").read()
    return {"bank": "B140", "frames": 0, "cards": len(re.findall(r"^\d+: card \d+", text, re.M)),
            "problems": "-", "cues": len(re.findall(r"\(cue [A-Za-z0-9_]+,", text)),
            "face_ok": len(re.findall(r"face-ok", text)),
            "face_bad": len(re.findall(r"WRONG-FACE|PORTRAIT-PARKED|TEXT-OVER-FACE", text)),
            "plain_in_band": len(re.findall(r"plain-in-band", text)),
            "wedged": 0, "never_took": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("saves", nargs="*")
    ap.add_argument("--frames", type=int, default=60000)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--image", default=IMAGE)
    ap.add_argument("--jobs", type=int, default=4, help="saves run at once (default 4)")
    ap.add_argument("--deep", action="store_true",
                    help="the coverage pass: every save plays DEEP (four rounds of every verb, every room "
                         "three times) instead of its route, into work/saturn/regress_deep/")
    a = ap.parse_args()
    global OUT
    if a.deep:
        OUT = os.path.join(WORK, "saturn", "regress_deep")
        ROUTE_FOR.clear()
        GENERIC.clear(); GENERIC.update(DEEP)
        START_AT.clear()
    ix = json.load(open(os.path.join(WORK, "saturn", "saves", "index.json")))["snapshots"]
    saves = a.saves or [s for s in PREFER if s in ix or s in NEWGAME]
    os.makedirs(OUT, exist_ok=True)
    t_all = time.time()

    def one(name):
        if name in NEWGAME:
            out = os.path.join(OUT, name)
            os.makedirs(out, exist_ok=True)
            env = {"EMU_SAVE_DIR": os.path.join(out, "emu")}
            os.makedirs(env["EMU_SAVE_DIR"], exist_ok=True)
            print(f"== {name} (New Game)", flush=True)
            rc, dt = run([PY, os.path.join(HERE, "satplay.py"), "--new", "--route", NEWGAME[name], "--out", out,
                          "--frames", str(max(a.frames, 150000)), "--no-autosave", "--image", a.image],
                         os.path.join(out, "play.log"), 3600, env)
            s = summarize_play(os.path.join(out, "log.txt")) if os.path.exists(os.path.join(out, "log.txt"))                 else summarize_play(os.path.join(out, "play.log"))
            s["rc"] = rc; s["secs"] = int(dt)
            print(f"-- {name}:", s, flush=True)
            return (name, "B010", s)
        entry = ix.get(name)
        if not entry or not entry.get("bank"):
            return (name, "?", "no such save / no bank")
        bank = entry["bank"]
        out = os.path.join(OUT, name)
        os.makedirs(out, exist_ok=True)
        env = {"EMU_SAVE_DIR": os.path.join(out, "emu")}     # this run's backup RAM
        os.makedirs(env["EMU_SAVE_DIR"], exist_ok=True)
        bm = f"{name}_rg"
        state = os.path.join(WORK, "saturn", "states", f"{bm}.state.gz")
        print(f"== {name} ({bank})", flush=True)
        if name in RECAP:
            rc, dt = run([PY, os.path.join(ROOT, "saturn", "harness", "probe_recap.py"), name, "1", "16000"],
                         os.path.join(out, "recap.log"), 1800, env)
            s = summarize_recap(os.path.join(out, "recap.log"))
            s["boot"] = rc; s["secs"] = int(dt)
            print(f"-- {name}:", s, flush=True)
            return (name, bank, s)
        if not (a.reuse and os.path.exists(state)):
            rc, dt = run([PY, os.path.join(HERE, "satsave_check.py"), name, "--image", a.image, "--bookmark", bm,
                          "--slot", str(entry.get("slot") or 1)], os.path.join(out, "boot.log"), 1200, env)
            boot = open(os.path.join(out, "boot.log"), encoding="utf-8", errors="replace").read()
            v = re.search(r"verdict: (.*)", boot)
            verdict = v.group(1) if v else f"rc {rc}"
            print(f"   {name} boot:", verdict[:120], f"({int(dt)} s)", flush=True)
            if not os.path.exists(state):
                return (name, bank, {"boot": verdict[:80], "cards": 0})
        route = stripped_route(ROUTE_FOR.get(name), os.path.join(out, "route.json"), START_AT.get(name, 0))
        rc, dt = run([PY, os.path.join(HERE, "satplay.py"), "--state", bm, "--route", route, "--out", out,
                      "--frames", str(a.frames), "--no-autosave", "--image", a.image],
                     os.path.join(out, "play.log"), 3600, env)
        s = summarize_play(os.path.join(out, "log.txt")) if os.path.exists(os.path.join(out, "log.txt")) \
            else summarize_play(os.path.join(out, "play.log"))
        s["rc"] = rc; s["secs"] = int(dt)
        print(f"-- {name}:", s, flush=True)
        return (name, bank, s)

    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        rows = list(ex.map(one, saves))          # PREFER order kept; runs overlap
    lines = [f"partial regression over the scene saves - {time.strftime('%Y-%m-%d %H:%M')} - image {os.path.basename(a.image)}"
             f" - {a.jobs} job(s)",
             f"{'save':32} {'bank':5} {'cards':>5} {'cues':>4} {'ok':>4} {'bad':>4} {'pib':>4} {'wedge':>5} {'took?':>5}  problems / boot"]
    for name, bank, s in rows:
        if isinstance(s, str):
            lines.append(f"{name:32} {bank:5} {s}"); continue
        lines.append(f"{name:32} {bank:5} {s.get('cards', 0):5d} {s.get('cues', 0):4d} {s.get('face_ok', 0):4d} "
                     f"{s.get('face_bad', 0):4d} {s.get('plain_in_band', 0):4d} {s.get('wedged', 0):5d} "
                     f"{s.get('never_took', 0):5d}  {s.get('problems', s.get('boot', ''))}")
    lines.append(f"{len(rows)} saves in {int(time.time() - t_all)} s wall, {a.jobs} job(s)")
    open(os.path.join(OUT, "summary.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
