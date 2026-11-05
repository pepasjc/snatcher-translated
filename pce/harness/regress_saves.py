# -*- coding: utf-8 -*-
"""The PCE regression over the scene saves: every module with a backup-RAM save in
the library (work/pce/saves/mod<rec>.sav, pce_saves.py scenes) is booted FRESH
on the built image - the save into the core's BRAM, the title's CONTINUE >
CASE FILES > its slot, the module's verb menu - then played from there (its
route where one fits, else the generic sweep: every verb of the arrival menu
twice, then every room once) and the run's verdicts are tabled: the module
that loaded, cards drawn, voice lines with and without a subtitle, subtitled
lines with no portrait beside them, where the route stopped. Only a boot that
does not reach the module's verb menu, a game that sits with no menu and no
new card after the route, or a child that died flag the set (exit 1); the
counts are for reading against the last summary. Persistent rendered-text
findings also flag the set and link their evidence report.

    python pce/harness/regress_saves.py [mod334 ...] [--frames N] [--jobs N] [--image CUE]
    python pce/harness/regress_saves.py --list

`--jobs` (default 4) runs that many saves at once: each is its own process
(a fresh Pilot; `--one mod<rec> --out DIR` is that child), the image is only
read, the BRAM travels in-process (SAVE_RAM - Beetle PCE keeps no file), and
the harness counts frames, so the verdicts do not depend on the load. A fresh
boot is the honest test here: a savestate carries the modules and the stub it
was taken under (CLAUDE.md, the chain states), a BRAM save loads everything
from the disc. Output: work/pce/regress/<save>/ per run (run.log, loaded.png,
loaded.mdf, end.png, result.json) and work/pce/regress/summary.txt.
"""
import argparse, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = os.path.join(WORK, "pce", "regress")
SAVES = os.path.join(WORK, "pce", "saves")
IMAGE = os.path.join(ROOT, "patched", "pce", "snatcher_pce.cue")
PY = sys.executable

# save -> a route to play from the loaded verb menu (None = the generic sweep). The
# library's saves were minted at the END of their module's act route (fred_last,
# gibson_done...), so the act routes do not fit them; the generic sweep is the run.
ROUTE_FOR = {}
# rooms the generic sweep never takes: they leave the scene (or start a ride)
LEAVE = ["Go out", "Board Tricycle", "Exit Tricycle", "Tricycle", "Leave", "Exit", "Front", "Back",
         "Get out", "Go outside", "Forward"]
# the verbs swept at the arrival, in this order, each twice when the menu has it
VERBS = ["Look", "Investigate", "Check", "Talk", "Ask", "Listen", "Hear", "Sniff", "Survey", "Look around"]


LONG_OPENING = {"act2_0": 60000, "act3_0": 60000}     # frames to the first verb menu after the load
LANDS_ON_LIST = {"act3_0"}       # its opening ends on the quiz (an answer list, not verbs): reaching it is the pass

def generic_route(items):
    have = {t.strip().lower() for t in items}
    route = [{"sweep": v, "rounds": 2, "avoid": ["Save", "Videophone", "Terminal"]} for v in VERBS if v.lower() in have]
    if "move" in have:
        route.append({"sweep": "Move", "rounds": 1, "avoid": LEAVE})
    route.append({"wait": 300})
    return route


# ---------------------------------------------------------------- the child: one save
class Budget(Exception):
    pass


def one(name, out, image, frames, slot):
    os.environ["LINELOG"] = "1"                   # pcemenu reads it at import: lines, pages, faces
    import pcemenu as M
    import pce_saves
    os.makedirs(out, exist_ok=True)
    res = {"save": name, "module": None, "want": None, "boot": "?", "cards": 0, "lines": 0, "subbed": 0,
           "nosub": 0, "noface": 0, "stopped": "", "frames": 0, "stuck": False}
    entry = pce_saves.index().get(name)
    if not entry or not isinstance(entry.get("module"), int):
        res["boot"] = "no such save / no module"; return res
    want = entry["module"]; res["want"] = want
    slot = slot or entry.get("slot") or 1

    class Timed(M.Pilot):
        deadline = None

        def step(self, n=1, held=()):
            if self.deadline is not None and self.frame >= self.deadline:
                raise Budget(f"{self.frame} frames")
            super().step(n, held)

    p = Timed(cue=image)
    p.emu.load_card(os.path.join(SAVES, entry["file"]))
    # the boot as work/pce/repro_recap_fresh.py does it: RUN at 1000, I past the title,
    # CONTINUE > CASE FILES, the slot, I - then the module load (a few thousand frames)
    p.step(1000); p.press("start"); p.step(3900)
    p.press("a"); p.step(600)
    for _ in range(slot - 1):
        p.press("down"); p.step(20)
    p.emu.image().save(os.path.join(out, "pick.png"))
    p.press("a")
    m = "?"
    for _ in range(40):
        p.step(300)
        m = p.module()
        if m != "?" and p.settled(tries=1):
            break
    res["module"] = m
    p.emu.image().save(os.path.join(out, "loaded.png"))
    open(os.path.join(out, "loaded.mdf"), "wb").write(p.emu.state())
    # a save at an act's start plays a long scene before the first verb menu
    # (the Act 2 recap, the Act 3 opening): wait it out instead of flagging it
    mm = M.wait_menu(p, 90, limit=LONG_OPENING.get(name, 3000))
    items = [t.strip() for t in p.items()] if mm else []
    print(f"{p.frame}: loaded module {m} (want {want}), menu {items}", flush=True)
    if str(m) != str(want):
        res["boot"] = f"loaded module {m}, wanted {want}"; return res
    if name in LANDS_ON_LIST and items:
        res["boot"] = "ok"; res["stopped"] = f"reached its list menu ({items[0]}...)"; return res
    if not M.is_verb_menu(items):
        res["boot"] = f"no verb menu after the load: {items}"; return res
    res["boot"] = "ok"
    route_path = ROUTE_FOR.get(name)
    route = json.load(open(route_path, encoding="utf-8")) if route_path else generic_route(items)
    route = [a for a in route if not ("save" in a or "bram" in a)]      # never over the library
    json.dump(route, open(os.path.join(out, "route.json"), "w", encoding="utf-8"), indent=1)
    p.deadline = p.frame + frames
    f0 = p.frame
    pages0, lines0 = len(p.pages), len(p.lines)          # the title's own line and the load's are not the run's
    try:
        M.run(p, route, every=90, outdir=out, bram=False, route_name="regress")
        res["stopped"] = "route done"
    except Budget as e:
        res["stopped"] = f"budget ({e})"
    except SystemExit as e:
        res["stopped"] = f"route stopped: {e}"
    # stuck? no menu and no new card in the next 900 frames after the route
    p.deadline = None
    pages_end = len(p.pages)
    try:
        mm = M.wait_menu(p, 90, limit=900)
    except Exception:
        mm = None
    res["stuck"] = mm is None and len(p.pages) == pages_end
    res["frames"] = p.frame - f0
    res["text_findings"] = len(p.text_monitor.findings) if p.text_monitor else 0
    res["text_report"] = p.text_monitor.directory if p.text_monitor else None
    # voice lines heard after the load: `line 00` is an ADPCM effect (no voice-table
    # number), not a line - the factory's 26 of them are the wind
    lines = [l for l in p.lines[lines0:] if l[1]]
    res["cards"] = pages_end - pages0                  # pages the census buffer showed (the stub's and the game's)
    res["lines"] = len(lines)
    res["subbed"] = sum(1 for _, _, text, _ in lines if text)
    res["nosub"] = res["lines"] - res["subbed"]
    # subtitled lines drawn with no named portrait on the band (`rN@x,..:Name` - a
    # region with sprites up AND a name in faces.json; regions r0-r5 hold scene
    # graphics on every line and are not faces): the nameplate layout, or a face
    # the census does not know - to look at, not a failure by itself
    res["noface"] = sum(1 for _, _, text, faces in lines
                        if text and not re.search(r"r\d@\d[^:]*:[A-Z]", faces))
    p.emu.image().save(os.path.join(out, "end.png"))
    open(os.path.join(out, "end.mdf"), "wb").write(p.emu.state())
    print(f"{p.frame}: end module {p.module()} {res}", flush=True)
    return res


# ---------------------------------------------------------------- the parent
def run_child(name, out, image, frames, jobs_note=""):
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    cmd = [PY, os.path.abspath(__file__), "--one", name, "--out", out, "--image", image, "--frames", str(frames)]
    with open(os.path.join(out, "run.log"), "w", encoding="utf-8") as fh:
        try:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT, timeout=7200).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    rp = os.path.join(out, "result.json")
    res = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else {"save": name, "boot": f"no result (rc {rc})"}
    res["rc"] = rc; res["secs"] = int(time.time() - t0)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("saves", nargs="*", help="mod<rec> names (default: every module with a save)")
    ap.add_argument("--frames", type=int, default=40000, help="frame budget for the route per save")
    ap.add_argument("--jobs", type=int, default=4, help="saves run at once (default 4)")
    ap.add_argument("--image", default=IMAGE)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--one", help="(internal) run this save in-process and write result.json")
    ap.add_argument("--out")
    ap.add_argument("--outdir", default=OUT, help="where the runs go (default work/pce/regress)")
    ap.add_argument("--slot", type=int)
    a = ap.parse_args()
    import pce_saves
    ix = pce_saves.index()
    if a.one:
        res = one(a.one, a.out, a.image, a.frames, a.slot)
        json.dump(res, open(os.path.join(a.out, "result.json"), "w", encoding="utf-8"), indent=1)
        return
    saves = a.saves or sorted((n for n, e in ix.items() if isinstance(e.get("module"), int)),
                              key=lambda n: ix[n]["module"])
    if a.list:
        for n in saves:
            print(f"{n:8s} {ix[n]['module']:4d}  {pce_saves.label(ix[n]['module'])}")
        return
    os.makedirs(a.outdir, exist_ok=True)
    t_all = time.time()

    def go(name):
        print(f"== {name} ({pce_saves.label(ix[name]['module']) if name in ix else '?'})", flush=True)
        r = run_child(name, os.path.join(a.outdir, name), a.image, a.frames)
        print(f"-- {name}: boot {r.get('boot')}, {r.get('cards', 0)} cards, {r.get('subbed', 0)}/{r.get('lines', 0)} lines subbed, "
              f"{r.get('noface', 0)} noface, {r.get('stopped', '')}{', STUCK' if r.get('stuck') else ''} ({r['secs']} s)", flush=True)
        return r

    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        rows = list(ex.map(go, saves))            # library order kept; runs overlap
    lines = [f"PCE regression over the scene saves - {time.strftime('%Y-%m-%d %H:%M')} - image {os.path.basename(a.image)} - {a.jobs} job(s)",
             f"{'save':8} {'mod':>4} {'scene':32} {'cards':>5} {'lines':>5} {'sub':>4} {'nosub':>5} {'noface':>6} {'stuck':>5}  boot / stopped"]
    bad = 0
    for r in rows:
        mod = r.get("want") or (ix.get(r["save"], {}).get("module"))
        scene = pce_saves.label(mod) if isinstance(mod, int) else "?"
        flag = r.get("boot") != "ok" or r.get("stuck") or r.get("rc") not in (0,) or bool(r.get("text_findings"))
        bad += bool(flag)
        if r.get("text_findings"):
            lines.append(f"TEXT REVIEW {r['save']}: {r['text_findings']} buffers; {r['text_report']}")
        lines.append(f"{r['save']:8} {mod if mod is not None else '?':>4} {scene[:32]:32} {r.get('cards', 0):5d} {r.get('lines', 0):5d} "
                     f"{r.get('subbed', 0):4d} {r.get('nosub', 0):5d} {r.get('noface', 0):6d} {'yes' if r.get('stuck') else '-':>5}  "
                     f"{r.get('boot')}; {r.get('stopped', '')}" + (f"; rc {r['rc']}" if r.get("rc") not in (0,) else ""))
    lines.append(f"{len(rows)} saves in {int(time.time() - t_all)} s wall, {a.jobs} job(s); {bad} flagged")
    open(os.path.join(a.outdir, "summary.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
