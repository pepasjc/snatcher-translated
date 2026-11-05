# -*- coding: utf-8 -*-
"""Mint a backup-RAM save per scene module from the harness's savestates, for the MiSTer.

    python pce/harness/mint_saves.py                 # every module without a save yet
    python pce/harness/mint_saves.py 382 574         # these modules (re-minted)
    python pce/harness/mint_saves.py --all           # every module, saves re-minted
    python pce/harness/mint_saves.py --list          # what each module would try

The PCE twin of ps1/harness/mint_cards.py. The savestates are the ones the act
routes left behind (`work/pce/chain/`, `work/pce/route/`, `work/pce/census/*/`,
`work/pce/run_*/`, any dir given with --states); each is restored once to read which scene module it holds
(`Pilot.module()`, cached in work/pce/mint/states.json by mtime), then, per
module, the states are tried newest first: `pcemenu.game_save` drives the
game's own Use Metal Gear > Save from the verb menu the state sits at, and the
2 KB backup RAM goes to work/pce/saves/mod<rec>.sav (`pce_saves.py list` /
`scenes` show it; `pce_saves.py push mod<rec>` puts it on the MiSTer).

A module whose states all sit in rooms without Metal Gear (no Save on the menu)
or mid-dialogue is reported, not invented - pce_saves.NO_SAVE says why for the
modules that never offer it. States older than the image are fine here: the
save flow loads only the save handler (rec 158 and its act copies), and a save
loads its scene from the disc when it is picked, so nothing stale is kept.

Results go to work/pce/mint/summary.txt.
"""
import argparse, glob, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]

import pce_saves
import pcemenu as M

OUT = os.path.join(WORK, "pce", "mint")
CACHE = os.path.join(OUT, "states.json")
STATE_DIRS = [os.path.join(WORK, "pce", "chain"), os.path.join(WORK, "pce", "route"),
              os.path.join(WORK, "pce", "census", "*"), os.path.join(WORK, "pce", "run_*")]
MAX_TRIES = int(os.environ.get("MINT_TRIES", "4"))     # states per module
# states that are not the English game at a verb menu: the pristine's (jp_*, pr_*),
# probes, and the pilot's own mid-flow snapshots
SKIP = ("jp_", "pr_", "_probe", "probe", "old_", "kb_", "ram_", "boot")
BUDGET = int(os.environ.get("MINT_FRAMES", "9000"))     # frames a save attempt may take


class Budget(Exception):
    pass


class TimedPilot(M.Pilot):
    """A Pilot whose step() gives up past a frame budget: a state mid-opening or
    in a wait the pilot presses through costs seconds, not minutes."""
    deadline = None

    def step(self, n=1, held=()):
        if self.deadline is not None and self.frame >= self.deadline:
            raise Budget(f"{self.frame} frames")
        super().step(n, held)


def log_to(path):
    fh = open(path, "a", encoding="utf-8")

    def log(msg):
        print(msg, flush=True)
        fh.write(msg + "\n"); fh.flush()
    return log


def states(dirs):
    out = []
    for d in dirs:
        for p in glob.glob(os.path.join(d, "*.mdf")):       # a dir may be a glob (census/*)
            n = os.path.basename(p)[:-4]
            if any(s in n for s in SKIP):
                continue
            out.append(p)
    return sorted(set(out))


def scan(pilot, paths, log=print):
    """{path: {module, mtime}} - each state restored once (cached by mtime)."""
    os.makedirs(OUT, exist_ok=True)
    cache = {}
    if os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
        except ValueError:
            cache = {}
    todo = [p for p in paths if p not in cache or cache[p].get("mtime") != os.path.getmtime(p)]
    if todo:
        log(f"reading the module of {len(todo)} state(s)...")
    for p in todo:
        try:
            pilot.restore(p)
            pilot.step(2)
            rec = pilot.module()
        except Exception as e:                       # a truncated or foreign state
            rec, err = "?", str(e)
            log(f"  {os.path.basename(p)}: {err}")
        cache[p] = {"module": rec, "mtime": os.path.getmtime(p)}
    for p in list(cache):
        if p not in paths:
            del cache[p]
    with open(CACHE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cache, f, indent=1, sort_keys=True)
    return cache


def candidates(cache, rec):
    """The states in module `rec`, the act routes' chain first, newest first."""
    hits = [(p, c["mtime"]) for p, c in cache.items() if str(c.get("module")) == str(rec)]
    hits.sort(key=lambda x: (0 if os.sep + "chain" + os.sep in x[0] else 1, -x[1]))
    return [p for p, _ in hits]


def mint(pilot, rec, path, log=print):
    """Restore the state, save through the game, dump the RAM as mod<rec>."""
    name = os.path.basename(path)[:-4]
    t = time.time()
    pilot.restore(path)
    pilot.frame = 0
    pilot.pages = []
    pilot.page = None
    pilot.deadline = BUDGET
    try:
        ok = M.game_save(pilot, every=90, log=log)
    except Budget as e:
        return f"no verb menu within {e}", time.time() - t
    finally:
        pilot.deadline = None
    if not ok:
        return "not written", time.time() - t
    live = pilot.module()
    if str(live) != str(rec):
        # the save says which module was live when it took (a state named for a
        # room can sit in its neighbour's module) - it is that module's save
        M.dump_bram(pilot, "mod%s" % live, route=f"state {name}", saved=True, log=log)
        return f"saved, but that state is in module {live} (kept as mod{live})", time.time() - t
    M.dump_bram(pilot, "mod%s" % rec, route=f"state {name}", saved=True, log=log)
    return "saved", time.time() - t


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("module", nargs="*", help="module recs (default: every one without a save)")
    ap.add_argument("--all", action="store_true", help="re-mint modules that already have a save")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--states", action="append", default=[], help="another dir of .mdf states")
    ap.add_argument("--cue", default=M.PATCHED)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    log = log_to(os.path.join(OUT, "log.txt"))
    pilot = TimedPilot(cue=a.cue)
    cache = scan(pilot, states(STATE_DIRS + a.states), log=log)
    have = pce_saves.index()
    mods = [str(e["rec"]) for e in pce_saves.modules()]
    todo = [m for m in a.module] or mods
    if a.list:
        for m in todo:
            c = candidates(cache, m)
            saved = have.get(f"mod{m}", {}).get("saved")
            why = pce_saves.NO_SAVE.get(int(m)) if m.isdigit() else None
            print(f'{m:>4} {pce_saves.label(m):32} {"save ok" if saved else "-":8} '
                  f'{len(c)} state(s): {", ".join(os.path.basename(p)[:-4] for p in c[:MAX_TRIES]) or "-"}'
                  f'{"   (no Save here: " + why + ")" if why else ""}')
        return
    summary = []
    for m in todo:
        if not a.module and not a.all and have.get(f"mod{m}", {}).get("saved"):
            summary.append((m, "kept", ""))
            log(f"{m}: save already there")
            continue
        if not a.module and int(m) in pce_saves.NO_SAVE:
            summary.append((m, "no Save here: " + pce_saves.NO_SAVE[int(m)], ""))
            log(f"{m}: no Save here: {pce_saves.NO_SAVE[int(m)]}")
            continue
        c = candidates(cache, m)
        if not c:
            summary.append((m, "no state", ""))
            log(f"{m}: no state in that module")
            continue
        result = None
        for p in c[:MAX_TRIES]:
            name = os.path.basename(p)[:-4]
            log(f"{m}: trying {name}")
            try:
                verdict, dt = mint(pilot, m, p, log=log)
            except SystemExit as e:                  # the pilot's own bail-outs
                verdict, dt = f"pilot: {e}", 0
            except Exception as e:
                verdict, dt = f"crashed: {e!r}", 0
            log(f"{m}: {name}: {verdict} ({dt:.0f}s)")
            result = (m, verdict, name)
            if verdict == "saved":
                break
        summary.append(result)
    with open(os.path.join(OUT, "summary.txt"), "w", encoding="utf-8") as fh:
        for m, v, n in summary:
            fh.write(f"{m:>4} {pce_saves.label(m):32} {v:44} {n}\n")
    print()
    print(open(os.path.join(OUT, "summary.txt"), encoding="utf-8").read())


if __name__ == "__main__":
    main()
