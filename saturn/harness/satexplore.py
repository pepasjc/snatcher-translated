# -*- coding: utf-8 -*-
"""Breadth-first exploration of a scene's menus from a bookmark, for coverage: every verb,
every item it offers, and again from every state where something new happened - so lines
the story path never asks for (a tape found on the floor after the third look, the second
answer to a question) are read too. Restores savestates between branches, so it is a
coverage tool, not a play-test of a session (satwhole.py is that).

    python saturn/harness/satexplore.py --state BOOKMARK [--image CUE] [--out DIR]
                                         [--nodes 30] [--frames 600000] [--depth 4] [--allow-move]

A node is a savestate at a live menu. From each node every top-level label is tried (and
every item of the submenu it opens, one level down; a third level - Item > Use > X - too);
after each branch the pilot advances the cards until a menu is live again (satplay's
wait_menu, so every card is read and checked as in any satplay run: cues, faces, text).
The state after a branch becomes a new node when the branch showed a card no earlier branch
showed or the top menu changed; nodes are taken in order, up to --nodes or --frames.
Travel (tricycle, go out, leave) is avoided unless --allow-move; Save never. Everything
lands in DIR/log.txt like a satplay run, so satcoverage.py reads it.
"""
import argparse, gzip, hashlib, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AVOID_ALWAYS = {"save", "load", "quit", "quit game", "don't save", "new game"}
TRAVEL = {"go out", "board tricycle", "exit tricycle", "leave", "exit", "move", "go inside", "go upstairs",
          "go downstairs", "enter shop", "front", "back", "hang up", "don't call"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", required=True, help="a bookmark name in work/saturn/states, or a .state.gz path")
    ap.add_argument("--image", default=os.path.join(ROOT, "patched", "saturn", "Snatcher (Japan) [dev-test].cue"))
    ap.add_argument("--out")
    ap.add_argument("--nodes", type=int, default=30)
    ap.add_argument("--frames", type=int, default=600000)
    ap.add_argument("--depth", type=int, default=4, help="branches from the bookmark a node may sit behind")
    ap.add_argument("--allow-move", action="store_true", help="also take Move / travel items")
    ap.add_argument("--avoid", default="", help="labels never picked, comma-separated")
    a = ap.parse_args()
    out = os.path.abspath(a.out or os.path.join(WORK, "saturn", "explore", os.path.basename(a.state).split(".")[0]))
    os.makedirs(out, exist_ok=True)
    os.environ.setdefault("EMU_SAVE_DIR", os.path.join(out, "emu"))
    os.makedirs(os.environ["EMU_SAVE_DIR"], exist_ok=True)
    import satrun, satplay, satpilot, satmem, satsubs
    satplay.PLAY = os.path.join(out, "captures")
    side = os.path.splitext(a.image)[0] + ".pair_table.json"
    if os.path.exists(side):
        satplay.SAT_TABLE = side
    logf = open(os.path.join(out, "log.txt"), "w", encoding="utf-8")

    def log(m):
        logf.write(m + "\n"); logf.flush()

    emu = satrun.SaturnEmu(); emu.load(a.image)
    play = satplay.Play(emu, out, log, a.image, autosave=False)
    avoid = AVOID_ALWAYS | {x.strip().lower() for x in a.avoid.split(",") if x.strip()}
    if not a.allow_move:
        avoid |= TRAVEL
    # the start: satplay's own restore (chunk table, exec, blob refreshed for this build)
    state = a.state if a.state.endswith(".gz") else os.path.join(satplay.STATES, f"{a.state}.state.gz")
    satplay.STATES = os.path.dirname(state)
    name = os.path.basename(state)[:-len(".state.gz")]
    satplay.run_route({"actions": [{"wait_menu": True, "patience": 8000}]}, play, 20000, log, name, False)
    t0 = time.time()
    seen_text = set(c["src"] + "|" + "/".join(c["rows"]) for c in play.cards)

    def snap():
        return (emu.state(), play.f)

    def reset(node):
        emu.restore(node[0])                  # play.f runs on: logs and the checks' windows stay monotonic
        play.last_cells = play.card_key = play.face_watch = None
        play.live_since = None
        play.tick = None
        play.subwatch.inst = play.subwatch.reel = None
        play.subwatch.last_mono = None
        play.run(2)

    def new_cards(n0):
        fresh = []
        for c in play.cards[n0:]:
            k = c["src"] + "|" + "/".join(c["rows"])
            if k not in seen_text:
                seen_text.add(k); fresh.append(c)
        return fresh

    def branch(node, hist, i, lab):
        reset(node)
        if not play.wait_menu(patience=4000):
            return
        n0 = len(play.cards)
        if not play.pick(i)[0]:
            return
        got = play.wait_menu(patience=12000)
        sub = list(got[3]) if got else []
        if not (got and sub and not play.is_top(sub)):
            fresh = new_cards(n0)
            lab_now = tuple(sub)
            if (fresh or (lab_now and lab_now not in tops)) and len(hist) < a.depth and lab_now:
                tops.add(lab_now)
                queue.append((snap(), hist + (lab,), lab_now))
            return
        after_verb = snap()
        for j, item in enumerate(sub):
            if item.lower() in avoid:
                continue
            reset(after_verb)
            n1 = len(play.cards)
            if not play.pick(j)[0]:
                continue
            got2 = play.wait_menu(patience=12000)
            sub2 = list(got2[3]) if got2 else []
            if got2 and sub2 and not play.is_top(sub2):
                # a third level (Item > Use > the item; Ask > topic > follow-up)
                lvl3 = snap()
                for k, it3 in enumerate(sub2):
                    if it3.lower() in avoid:
                        continue
                    reset(lvl3)
                    n2 = len(play.cards)
                    if play.pick(k)[0]:
                        got3 = play.wait_menu(patience=12000)
                        if new_cards(n2) and got3 and len(hist) < a.depth:
                            play.ensure_top()
                            queue.append((snap(), hist + (f"{lab}>{item}>{it3}",), tuple(play.labels_now())))
                continue
            fresh = new_cards(n1)
            play.ensure_top()
            lab_now = tuple(play.labels_now())
            if (fresh or (lab_now and lab_now not in tops)) and len(hist) < a.depth:
                tops.add(lab_now)
                queue.append((snap(), hist + (f"{lab}>{item}",), lab_now))

    root = snap()
    reset(root)
    got = play.wait_menu(patience=8000)
    if not got:
        log("explore: no menu at the start"); return
    queue = [(root, (), tuple(got[3]))]
    tops = {tuple(got[3])}
    nodes = 0
    budget_end = play.f + a.frames
    while queue and nodes < a.nodes and play.f < budget_end:
        node, hist, top = queue.pop(0)
        nodes += 1
        log(f"==== node {nodes} depth {len(hist)} {list(hist)} top {list(top)} ({len(queue)} queued, {time.time() - t0:.0f}s)")
        for i, lab in enumerate(top):
            if lab.lower() in avoid:
                continue
            try:
                branch(node, hist, i, lab)
            except satplay.Wedged as e:
                log(f"{play.f}: explore: branch {lab!r} wedged ({e}) - next branch")
            if play.f >= budget_end:
                break
    log(f"explore: {nodes} nodes, {len(queue)} left in the queue, {len(seen_text)} distinct cards, "
        f"{play.f} frames, {time.time() - t0:.0f}s")
    play.finish(t0)




if __name__ == "__main__":
    main()
