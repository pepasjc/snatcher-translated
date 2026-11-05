"""The whole game on a FRESH boot of an image, every act route in order (act1_a is the HQ tour alone, not part of the chain) in one process, with
glitchwatch on: a savestate carries the stub it was made with, so only a boot proves a build.

  python pce/harness/playthrough.py <out> [cue] [--from act2_a] [--until act2_i] [--endsave]
         [--bram act2_0 --pre '[{"read": 40000}]' --skip N]   # an act from a BRAM save

Boots through the opening to the reception's verb menu, then plays act1_b .. act3_b (each
from where the last one left off), writes <out>/<route>_end.mdf/.png after each route,
<out>/events.json (glitchwatch) and <out>/summary.json (per route: frames, glitches by kind,
how it ended). A route that stops (a menu item missing, a budget hit, a hang) ends the run:
the state there is kept for a look.
"""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]
os.environ["LINELOG"] = "1"

import pcemenu as M
from glitchwatch import GlitchWatch

ROUTES = ["act1_b", "act1_c", "act1_d", "act1_e", "act1_f", "act1_g",
          "act2_a", "act2_b", "act2_c", "act2_d", "act2_e", "act2_f", "act2_g", "act2_h", "act2_i",
          "act3_a", "act3_b"]
CUE = os.path.join(ROOT, "patched", "pce", "snatcher_pce.cue")


def boot(p, limit=70000):
    """RUN, then I every 90 frames (title, NEW GAME, the opening's cards) until a verb menu is
    up ($3518, the live list count) - no fixed timings: the splash and the cards move them."""
    p.step(1000)
    p.step(8, ['start'])
    p.step(3000)
    while p.frame < limit:
        if p.ram()[0x1518]:
            p.step(30)
            if p.ram()[0x1518]:
                return
        p.step(8, ['a'])
        p.step(82)
    raise SystemExit(f"no verb menu by frame {limit}")


def main():
    argv = sys.argv[1:]
    opt = {}
    endsave = "--endsave" in argv
    argv = [a for a in argv if a != "--endsave"]
    for k in ("--from", "--bram", "--pre", "--skip", "--until", "--routes"):
        if k in argv:
            i = argv.index(k)
            opt[k], argv = argv[i + 1], argv[:i] + argv[i + 2:]
    start = opt.get("--from")
    args = [a for a in argv if not a.startswith("--")]
    out = args[0]
    cue = args[1] if len(args) > 1 else CUE
    start = start or ROUTES[0]
    os.makedirs(out, exist_ok=True)
    p = M.Pilot(cue=cue)
    if getattr(p, "text_monitor", None) is None:       # (the pilot reviews the rendered text on
        from rendered_text import Monitor               # patched/pce only; a frozen copy of this
        p.text_monitor = Monitor()                      # build's image gets it too)
    gw = GlitchWatch(p, out)
    summary = []
    if "--bram" in opt:
        # a fresh boot of the image with a BRAM save loaded (CONTINUE > CASE FILES, slot 1):
        # an act's start in parallel with the rest (regress_saves boots it)
        import subprocess
        bdir = os.path.join(out, "bram")                # (its own: never another run's)
        subprocess.run([sys.executable, os.path.join(HERE, "regress_saves.py"), opt["--bram"],
                        "--frames", "60", "--image", cue, "--outdir", bdir], capture_output=True)
        p.restore(os.path.join(bdir, opt["--bram"], "loaded.mdf"))
        if "--pre" in opt:
            M.run(p, json.loads(opt["--pre"]), every=90, outdir=os.path.join(out, "states"))
    elif start == ROUTES[0]:
        boot(p)
        print(f"{p.frame}: booted", flush=True)
        M.run(p, [{"maybe": "Go inside"}, {"read": 3000}], every=90)    # the building, then the reception
    else:
        prev = os.path.join(out, f"{ROUTES[ROUTES.index(start) - 1]}_end")
        p.restore(prev + ".mdf")
        if os.path.exists(prev + ".pages.json"):         # the pages read before (a typed answer
            p.pages = json.load(open(prev + ".pages.json", encoding="utf-8"))   # follows the question)
    for name in ROUTES[ROUTES.index(start):]:
        rdir = opt.get("--routes") or os.path.join(HERE, "routes")      # (--routes: another set)
        route = json.load(open(os.path.join(rdir, f"{name}.json"), encoding="utf-8"))
        if name == start and "--skip" in opt:
            route = route[int(opt["--skip"]):]
        if endsave and name == opt.get("--until"):
            # the act's closing save prompt answered Save > End the game instead of Don't save:
            # Metal Gear's farewell (line 86) in the module that asks (the run ends there)
            i = next((k for k, st in enumerate(route) if st.get("choose") == "Don't save"), None)
            if i is not None:
                route = route[:i] + [{"endgame": 1, "wait": 60}, {"read": 4000}]
        f0, n0, t0 = p.frame, len(gw.events), time.time()
        print(f"==== {name} at {p.frame}", flush=True)
        ended = "done"
        try:
            M.run(p, route, every=90, outdir=os.path.join(out, "states"))
        except SystemExit as e:
            ended = f"stopped: {e}"
        except Exception as e:
            ended = f"error: {type(e).__name__}: {e}"
        kinds = {}
        for e in gw.events[n0:]:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        summary.append({"route": name, "frames": p.frame - f0, "glitches": kinds, "ended": ended,
                        "secs": round(time.time() - t0)})
        open(os.path.join(out, f"{name}_end.mdf"), "wb").write(p.emu.state())
        json.dump(p.pages[-40:], open(os.path.join(out, f"{name}_end.pages.json"), "w", encoding="utf-8"))
        p.emu.image().save(os.path.join(out, f"{name}_end.png"))
        gw.save()
        json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=1)
        print(f"{name}: {ended}; glitches {kinds or 'none'}", flush=True)
        if ended != "done" or name == opt.get("--until"):
            break
    print("playthrough done", p.frame, flush=True)


if __name__ == "__main__":
    main()
