# -*- coding: utf-8 -*-
"""The Saturn play-test pilot: drive Snatcher from a route, closed-loop on RAM.

    python saturn/harness/satpilot.py --route saturn/harness/routes/B010_new.json
    python saturn/harness/satpilot.py --state B010_start --route ... --frames 20000

Ported from the PS1 harness (ps1/harness/scripted.py + menustate.py): every
decision reads the ENGINE's own state, never a screenshot. The Saturn engine
keeps it in the same context block the PS1 does, at a different address
(satmem.py has the evidence for each):

    menu live    byte  ctx+0x3F7          1 while a list menu takes input
    menu index   u16   ctx+0x3F8          0..count-1, wraps both ways
    menu count   byte  0x060FD0C3         items (stale when not live)
    labels       cells ctx+0x3FA          4 rows x 20 cells {u16 sjis, u8 colour, pad};
                                          item i = cells [start_i, start_i+10),
                                          starts 0/20/40/60 (left column), 10/30/50/70 (right)
    box waiting  byte  ctx+0xB74          1 once a card has typed on and waits for a press
    scene        u16   ctx+0x54A          the scene number (0 opening, 1 B010 ...)

Buttons: A and C confirm, B cancels (back to the parent menu, cursor kept),
START does nothing on the title or in menus (the game ignores it; the core
does map it - satmem.py, START). The opening runs by itself for ~23,500
frames after NEW GAME and ANY press skips it, so `new` presses nothing until
the first card waits (ctx+0xB74).

Route (JSON, the PS1 shape with the Saturn's buttons and Japanese labels):
    {"scene": "B010", "actions": [
        {"new": true},                       boot to NEW GAME, sit through the opening
        {"wait_menu": true},                 advance cards (A when waiting) until a menu is live
        {"save": "B010_start"},              bookmark -> work/saturn/states/<name>.state.gz
        {"path": ["見る", "扉"]},             descend menus by label (prefix match)
        {"menu": 1},                         pick an index on the live menu
        {"press": "a"}, {"idle": 300}, {"cancel": true}
    ]}
"""
import argparse, gzip, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import satrun, satmem

STATES = os.path.join(WORK, "saturn", "states")
PRESS = 8            # frames a button is held
STEP_GAP = 30        # frames between cursor presses (release edge + the engine's repeat guard)
MENU_SETTLE = 12     # frames a menu must be live before it is acted on
ADVANCE = 70         # frames between A presses on a waiting card
PATIENCE = 3000      # frames to wait for a label before an action is skipped
OK, BACK = "a", "b"
# the title screen and the NEW GAME menu (pristine timeline, satrun.py):
# PUSH BUTTON ~2100-2800, the menu after any of A/B/C, NEW GAME is item 0
TITLE_PRESS, NEWGAME_PRESS = 2300, 2700


def presses(emu):
    """(title press, NEW GAME press) frames for the loaded image: the pristine ones
    pushed back by the English build's boot screens (satrun.boot_screens)."""
    d = getattr(emu, "boot_screens", 0)
    return TITLE_PRESS + d, NEWGAME_PRESS + d


class Pilot:
    def __init__(self, emu, log=print):
        self.emu, self.mem, self.log = emu, satmem.SatMem(emu.core), log
        self.f = 0
        self.held_until = -1

    # ---- primitives --------------------------------------------------------
    def run(self, n=1, hook=None):
        for _ in range(n):
            if self.f == self.held_until:
                self.emu.held = set()
            self.emu.run(); self.f += 1
            if hook:
                hook(self.f)

    def press(self, btn, hold=PRESS):
        self.emu.held = {satrun.BTN[btn]}
        self.held_until = self.f + hold

    def menu(self):
        """(live, index, count, labels) from RAM."""
        m = self.mem
        live = m.u8(satmem.MENU_LIVE) == 1
        idx = m.u16(satmem.MENU_INDEX)
        cnt = m.u8(satmem.MENU_COUNT) if live else 0
        return live, idx, cnt, (satmem.menu_labels(m)[:cnt] if live else [])

    def box(self):
        """(up, waiting, rows): up = text in the cells with no menu live."""
        m = self.mem
        rows = satmem.cells(m)
        up = any(rows) and m.u8(satmem.MENU_LIVE) != 1
        return up, m.u8(satmem.BOX_WAIT) == 1, rows

    # ---- closed-loop steps --------------------------------------------------
    def wait_menu(self, patience=PATIENCE, hook=None, hold_after_card=0):
        """Run until a menu is live and settled; A advances any card that waits.
        Returns the (live, idx, count, labels) tuple, or None on timeout."""
        start, live_since, last_press, last_wait = self.f, None, -ADVANCE, None
        while self.f - start < patience:
            self.run(1, hook)
            live, idx, cnt, labels = self.menu()
            if live:
                live_since = live_since if live_since is not None else self.f
                if self.f - live_since >= MENU_SETTLE:
                    return live, idx, cnt, labels
                continue
            live_since = None
            up, waiting, rows = self.box()
            if waiting and self.f - last_press >= ADVANCE:
                if last_wait is None:
                    last_wait = self.f
                if self.f - last_wait >= hold_after_card:
                    self.log(f"{self.f}: card {[r for r in rows if r]} - A")
                    self.press(OK); last_press = self.f; last_wait = None
        return None

    def select(self, target, hook=None):
        """Move the cursor to `target` (an index, or a label prefix) and confirm.
        Believed once the menu goes away or its labels change; a confirm that
        leaves the same menu live is pressed again."""
        got = self.wait_menu(hook=hook)
        if got is None:
            return False, []
        live, idx, cnt, labels = got
        if isinstance(target, str):
            want = next((i for i, l in enumerate(labels) if l.startswith(target)), None)
            if want is None:
                return False, labels
        else:
            want = target
            if want >= cnt:
                return False, labels
        steps = 0
        while idx != want:
            down = (want - idx) % cnt
            self.press("down" if down <= cnt - down else "up")
            self.run(STEP_GAP, hook)
            live, idx, cnt, _ = self.menu()
            steps += 1
            if not live or steps > 3 * cnt + 4:
                self.log(f"{self.f}: cursor stuck at {idx}, wanted {want} ({target!r})")
                return False, labels
        before = labels
        for attempt in range(3):
            self.press(OK)
            for _ in range(90):
                self.run(1, hook)
                live, idx2, cnt2, labels2 = self.menu()
                if not live or labels2 != before:
                    self.log(f"{self.f}: picked {before[want]!r} (index {want})")
                    return True, before
        self.log(f"{self.f}: confirm on {before[want]!r} never took")
        return False, before

    def save(self, name):
        os.makedirs(STATES, exist_ok=True)
        path = os.path.join(STATES, f"{name}.state.gz")
        if os.path.exists(path):
            os.replace(path, path[:-9] + ".prev.state.gz")
        open(path, "wb").write(gzip.compress(self.emu.state()))
        live, idx, cnt, labels = self.menu()
        json.dump({"frame": self.f, "menu": labels, "cells": satmem.cells(self.mem)},
                  open(path[:-9] + ".json", "w", encoding="utf-8"), ensure_ascii=False)
        self.log(f"{self.f}: saved state {name} at {labels}")
        return path


def run_route(route, emu, out, frames, log, every=500, state=None):
    pilot = Pilot(emu, log)
    actions = route["actions"]
    shots = [0]

    def hook(f):
        if every and f % every == 0 and emu.frame:
            emu.image().save(os.path.join(out, f"f{f:06d}.png"))
        if f in dump_at:
            open(os.path.join(out, f"state_{f:06d}.gz"), "wb").write(gzip.compress(emu.state()))

    dump_at = set(route.get("dump_states", []))
    if state:
        path = os.path.join(STATES, f"{state}.state.gz")
        emu.restore(gzip.decompress(open(path, "rb").read()))
        meta = json.load(open(path[:-9] + ".json", encoding="utf-8")) if os.path.exists(path[:-9] + ".json") else {}
        pilot.f = meta.get("frame", 0)
        log(f"{pilot.f}: restored {state}")
        pilot.run(1, hook)
    for i, act in enumerate(actions):
        if pilot.f >= frames:
            log(f"{pilot.f}: frame budget spent before action {i} {act}")
            break
        if act.get("new"):
            # the title takes A (START is ignored), the menu's first item is NEW GAME
            title, newgame = presses(pilot.emu)
            pilot.run(title - pilot.f, hook); pilot.press(OK)
            pilot.run(newgame - pilot.f, hook); pilot.press("c")
            log(f"{pilot.f}: NEW GAME confirmed; the opening runs untouched")
            # nothing is pressed until the first card waits for one
            while pilot.f < frames and not pilot.box()[1]:
                pilot.run(1, hook)
            log(f"{pilot.f}: first card waits: {[r for r in pilot.box()[2] if r]}")
        elif act.get("wait_menu"):
            got = pilot.wait_menu(act.get("patience", PATIENCE), hook, act.get("hold", 0))
            log(f"{pilot.f}: menu {got[3] if got else 'never came'}")
        elif "path" in act:
            for label in act["path"]:
                ok, labels = pilot.select(label, hook)
                if not ok:
                    log(f"{pilot.f}: {label!r} not in {labels} - action {i} skipped")
                    break
        elif "menu" in act:
            ok, labels = pilot.select(int(act["menu"]), hook)
        elif "press" in act:
            pilot.press(act["press"]); pilot.run(PRESS + 2, hook)
            log(f"{pilot.f}: press {act['press']}")
        elif "cancel" in act:
            pilot.press(BACK); pilot.run(STEP_GAP, hook)
        elif "idle" in act:
            pilot.run(int(act["idle"]), hook)
        elif "save" in act:
            pilot.wait_menu(hook=hook)
            pilot.save(act["save"])
        else:
            log(f"{pilot.f}: unknown action {act}")
    if emu.frame:
        emu.image().save(os.path.join(out, "final.png"))
    return pilot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", required=True)
    ap.add_argument("--state", help="resume from work/saturn/states/<name>.state.gz")
    ap.add_argument("--frames", type=int, default=40000)
    ap.add_argument("--every", type=int, default=500)
    ap.add_argument("--out")
    ap.add_argument("--image", default=satrun.DISC)
    a = ap.parse_args()
    route = json.load(open(a.route, encoding="utf-8"))
    out = a.out or os.path.join(WORK, "saturn", f"s_{route.get('scene', 'run').lower()}")
    os.makedirs(out, exist_ok=True)
    logf = open(os.path.join(out, "log.txt"), "w", encoding="utf-8")

    def log(m):
        logf.write(m + "\n"); logf.flush(); print(m, flush=True)

    emu = satrun.SaturnEmu()
    emu.load(a.image)
    t0 = time.time()
    pilot = run_route(route, emu, out, a.frames, log, a.every, a.state)
    log(f"done at frame {pilot.f} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
