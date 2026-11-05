"""Play the Saturn build through the game from a fresh boot, one satplay route
after another, so every bank the chain reaches gets a bookmark (`<bank>_auto`,
satplay's autosave) made on THIS build's exec - a bookmark from an older build
keeps the old exec and payload in its RAM, so nothing resumed from it exercises
the current subtitles (2026-09-16).

    python saturn/harness/playthrough.py                 the whole chain
    python saturn/harness/playthrough.py --from 3        from step 3 (its start state must exist)
    python saturn/harness/playthrough.py --list

Each step is (route, start): `new` boots New Game, otherwise a bookmark the
earlier steps leave behind. Steps run as separate satplay processes (a wedge or
a crash in one does not end the night), each with its own frame budget; a step
whose start bookmark is missing is skipped with a note. The summary
(work/saturn/play/playthrough_<stamp>.txt) lists, per step, the run directory,
the banks reached, the cards and the problems (FACE / WEDGE / JP ...), and the
bookmarks now available; then `mint_saves.py` can mint a save per bank.
"""
import argparse, datetime, glob, json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]

ROUTES = os.path.join(ROOT, "saturn", "harness", "routes")
STATES = os.path.join(WORK, "saturn", "states")
PLAY = os.path.join(WORK, "saturn", "play")

# (route, start state or "new", frame budget)
CHAIN = [
    ("B010.json", "new", 260000),            # New Game, the HQ tour; saves B010_chief, B010_toured
    ("B010_leave.json", "B010_toured", 120000),   # Item, the rooms again, the tricycle to the ruins -> B020_auto
    ("B020.json", "B020_arrive", 160000),    # the ruins from the arrival (run 6's state at the first card): Gibson's body, the front, the fight; B020_prefight
    ("B080.json", "B080_auto", 160000),      # JUNKER HQ after the ruins (B020.json ends there): B080_front, B080_done
    ("B0D0.json", "B080_front", 120000),     # Altamira
    ("B0E0.json", "B080_front", 120000),     # Joy Division
    ("B0B0.json", "B0A0_auto", 100000),      # Gillian's apartment (from the tricycle's destination list at HQ)
    ("B0C0.json", "B0A0_auto", 100000),      # Gibson's house
]


def have_state(name):
    return name == "new" or os.path.exists(os.path.join(STATES, name + ".state.gz"))


def newest_run():
    runs = sorted(glob.glob(os.path.join(PLAY, "run_*")), key=os.path.getmtime)
    return runs[-1] if runs else None


def summarize(run_dir):
    """(banks reached, cards, problems by kind) from a satplay run directory."""
    out = dict(banks=[], cards=0, problems={}, faces_ok=0)
    p = os.path.join(run_dir, "cards.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        out["cards"] = len(d.get("cards", []))
        out["banks"] = sorted({c.get("bank") for c in d.get("cards", []) if c.get("bank")})
        for pr in d.get("problems", []):
            out["problems"][pr["kind"]] = out["problems"].get(pr["kind"], 0) + 1
        out["faces_ok"] = sum(1 for c in d.get("cards", []) if str(c.get("face", "")).startswith("face-ok"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--to", type=int, default=len(CHAIN))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (r, s, n) in enumerate(CHAIN):
            print(f"{i}: {r:20s} from {s:16s} {n} frames  {'' if have_state(s) else '(start missing)'}")
        return
    stamp = datetime.datetime.now().strftime("%m%d_%H%M")
    summary = os.path.join(PLAY, f"playthrough_{stamp}.txt")
    os.makedirs(PLAY, exist_ok=True)
    lines = []

    def note(m):
        print(m, flush=True)
        lines.append(m)
        open(summary, "w", encoding="utf-8").write("\n".join(lines) + "\n")

    note(f"playthrough {stamp}: steps {a.start}..{a.to - 1}")
    for i in range(a.start, a.to):
        route, start, frames = CHAIN[i]
        if not have_state(start):
            note(f"step {i} {route}: start {start} missing - skipped")
            continue
        run = os.path.join(PLAY, f"pt_{stamp}_{i}_{os.path.splitext(route)[0]}")
        cmd = [sys.executable, os.path.join(HERE, "satplay.py"), "--route", os.path.join(ROUTES, route),
               "--frames", str(frames), "--out", run]
        cmd += ["--new"] if start == "new" else ["--state", start]
        t0 = time.time()
        note(f"step {i} {route} from {start}: {' '.join(cmd[2:])}")
        rc = subprocess.call(cmd, cwd=ROOT, stdout=open(run + ".out", "w", encoding="utf-8") if os.makedirs(run, exist_ok=True) is None else None, stderr=subprocess.STDOUT)
        s = summarize(run)
        note(f"  rc {rc} in {time.time() - t0:.0f}s; run {os.path.relpath(run, ROOT) if run else '?'}; banks {s.get('banks')}; "
             f"cards {s.get('cards')}; faces ok {s.get('faces_ok')}; problems {s.get('problems')}")
    autos = sorted(os.path.basename(p)[:-9] for p in glob.glob(os.path.join(STATES, "*_auto.state.gz")))
    note(f"bookmarks now: {autos}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
