"""One coverage route (coverage_routes.json): a scene save booted fresh, then the route's
steps, with the pilot's page log and glitchwatch on - the branches the act routes do not
take (a wrong answer, a second visit, a game over) for voice_coverage.py.

    python pce/harness/coverage_run.py NAME [--image CUE] [--out DIR]

coverage_routes.json: {"NAME": {"save": "<library save>", "steps": [...route steps...],
"why": "..."}} - "save": "new" boots a New Game to the reception's verb menu instead.
"""
import argparse, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]
os.environ["LINELOG"] = "1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--image", default=os.path.join(ROOT, "patched", "pce", "snatcher_pce.cue"))
    ap.add_argument("--out")
    a = ap.parse_args()
    spec = json.load(open(os.path.join(HERE, "coverage_routes.json"), encoding="utf-8"))[a.name]
    out = a.out or os.path.join(WORK, "pce", "cov", a.name)
    os.makedirs(out, exist_ok=True)
    import pcemenu as M
    from glitchwatch import GlitchWatch
    p = M.Pilot(cue=a.image)
    if p.text_monitor is None:
        from rendered_text import Monitor
        p.text_monitor = Monitor()
    gw = GlitchWatch(p, out)
    if spec["save"] == "new":
        import playthrough
        playthrough.boot(p)                     # to the building's verb menu; the steps go on
    else:
        bdir = os.path.join(out, "bram")
        subprocess.run([sys.executable, os.path.join(HERE, "regress_saves.py"), spec["save"], "--frames", "60",
                        "--image", a.image, "--outdir", bdir], capture_output=True)
        p.restore(os.path.join(bdir, spec["save"], "loaded.mdf"))
    ended = "done"
    try:
        M.run(p, spec["steps"], every=90, outdir=os.path.join(out, "states"), bram=False)
    except SystemExit as e:
        ended = f"stopped: {e}"
    gw.save()
    p.emu.image().save(os.path.join(out, "end.png"))
    kinds = {}
    for e in gw.events:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    json.dump([{"route": a.name, "frames": p.frame, "glitches": kinds, "ended": ended}],
              open(os.path.join(out, "summary.json"), "w"), indent=1)
    print(f"coverage route {a.name}: {ended}; glitches {kinds or 'none'}; {p.frame} frames", flush=True)
    sys.exit(0 if ended == "done" else 1)


if __name__ == "__main__":
    main()
