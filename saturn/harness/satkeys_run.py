# -*- coding: utf-8 -*-
"""Reach Gaudi's name search on the Saturn and type names on the keyboard.

    python saturn/harness/satkeys_run.py tour  [--image CUE] [--frames N]
        New Game -> the reception -> the Chief's room (the JUNKER ID) -> the
        Mechanic room (Metal Gear) -> the Squad room -> the Computer room ->
        Use Gaudi -> Use card -> Person file -> Search name. Bookmarks
        work/saturn/states/keys_computer (the Computer room's verb menu) and
        keys_search (the keyboard open), captures under work/saturn/keys/.
    python saturn/harness/satkeys_run.py type GIBSON RANDAM [--state keys_search]
        Types each name on the keyboard (cursor driven from RAM: the key grid
        cursor at 0x060F2C00 {u16 col, u16 row}, the typed buffer at
        0x060EF6B4), presses OK, captures the result cards.

The keyboard (satkeys.py has the engine): 15 x 4 key cells, key index =
KEYDATA[2 + row*15 + col] (exec 0x060E5254), the OK button on row 3 cols
11-14. The pilot's route actions have no sweep, so the tour drives
satpilot.Pilot directly (the PS1 harness's "every slot twice").
"""
import argparse, gzip, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import satrun, satmem, satpilot, satfont
import satkeys

PAIR_TABLE = os.path.join(WORK, "saturn", "pair_table_sat.json")


def pair_decoder():
    """SJIS cell code -> letter pair, from the build's pair table (English
    labels are pair codes in the cells; satmem.cells shows them as kanji)."""
    t = json.load(open(PAIR_TABLE))
    return {satfont.code_to_sjis(code): pair for pair, (slot, code) in t.items()}


def cells_en(mem, pairs, rows=4, cols=20):
    import struct
    out = []
    for r in range(rows):
        row = mem.read(satmem.TEXT_CELLS + r * satmem.TEXT_ROW, cols * 4)
        s = ""
        for c in range(cols):
            code = struct.unpack_from(">H", row, c * 4)[0]
            if code in (0, satmem.BLANK_CELL):
                s += " "
            elif code in pairs:
                s += pairs[code]
            else:
                try:
                    ch = code.to_bytes(2, "big").decode("cp932")
                    s += chr(ord(ch) - 0xFEE0) if 0xFF01 <= ord(ch) <= 0xFF5E else ch
                except UnicodeDecodeError:
                    s += "?"
        out.append(s)
    return out


class Pilot(satpilot.Pilot):
    """satpilot.Pilot reading English labels through the pair table."""

    def __init__(self, emu, log=print):
        super().__init__(emu, log)
        self.pairs = pair_decoder()
        self.trace = 0                    # frames between trace lines (0 = off)

    def run(self, n=1, hook=None):
        for _ in range(n):
            super().run(1, hook)
            if self.trace and self.f % self.trace == 0:
                live, idx, cnt, labels = self.menu()
                up, waiting, rows = self.box()
                self.log(f"{self.f}: trace menu={live}/{idx}/{cnt} {labels} box={up}/{waiting} "
                         f"{[r for r in rows if r]} scene={self.mem.u16(satmem.SCENE_INDEX)} "
                         f"kbd={keyboard_up(self.mem)}")
                shot(self.emu, "trace", self.f)
                if self.f % (self.trace * 5) == 0:
                    self.save("keys_trace")

    def labels(self):
        rows = cells_en(self.mem, self.pairs)
        return [rows[s // 20][s % 20:s % 20 + 10].strip() for s in satmem.MENU_STARTS]

    def menu(self):
        m = self.mem
        live = m.u8(satmem.MENU_LIVE) == 1
        idx = m.u16(satmem.MENU_INDEX)
        cnt = m.u8(satmem.MENU_COUNT) if live else 0
        return live, idx, cnt, (self.labels()[:cnt] if live else [])

    def box(self):
        rows = [r.rstrip() for r in cells_en(self.mem, self.pairs)]
        up = any(rows) and self.mem.u8(satmem.MENU_LIVE) != 1
        return up, self.mem.u8(satmem.BOX_WAIT) == 1, rows

OUT = os.path.join(WORK, "saturn", "keys")
STATES = satpilot.STATES
CURSOR = 0x060F2C00          # u16 col, u16 row of the key grid cursor
TYPED = 0x060EF6B4           # the typed key codes, null-terminated (14 bytes)
CAND = 0x060EF554            # the candidate labels converted (14 bytes each)

IMAGE = os.path.join(ROOT, "patched", "saturn", "Snatcher (Japan) [keys].cue")


def log_to(path):
    fh = open(path, "a", encoding="utf-8")

    def log(m):
        fh.write(m + "\n"); fh.flush(); print(m, flush=True)
    return log


def shot(emu, tag, f):
    p = os.path.join(OUT, f"{tag}_{f:06d}.png")
    emu.image().save(p)
    return p


def poke_flag(mem, emu, flag, log):
    """Set a 1-bit script flag: 0xA000+ are bank-local (index + [0x060FD150]
    - 0xA000) bits in the array at [0x060FABC0], MSB first (0x060C09C8)."""
    import ctypes as C
    base = mem.u32(0x060FD150); arr = mem.u32(0x060FABC0)
    bit = flag + base - 0xA000
    addr = arr + (bit >> 3)
    off = satmem.block_offset(addr) ^ 1
    ptr = emu.core.retro_get_memory_data(2)
    cur = C.string_at(C.c_void_p(ptr + off), 1)[0]
    C.memmove(C.c_void_p(ptr + off), bytes([cur | (0x80 >> (bit & 7))]), 1)
    log(f"poked flag {flag:#x}: byte {addr:#x} {cur:#04x} -> {mem.u8(addr):#04x}")


def keyboard_up(mem):
    """The keyboard panel's sprite list is live with its typed cells (the
    wrapper sets the count to pieces + cells while the keyboard is up)."""
    lst = mem.u32(satkeys.LIST_PTR)
    try:
        return mem.u16(lst) == satkeys.NPIECES + satkeys.NCELLS
    except ValueError:
        return False


def has(labels, prefix):
    return any(l.startswith(prefix) for l in labels)


def same(a, b):
    """Two label lists are the same level when they share half their labels
    (Ask topics grow as answers unlock more)."""
    a, b = set(a), set(b)
    return len(a & b) >= max(1, min(len(a), len(b)) // 2)


def explore(p, sub, v, depth, log, budget):
    """Pick every item of the live list `sub` (a verb's submenu), descending
    into lists that open under an item (Ask topics with follow-ups), coming
    back up with B. Returns False when the menus are gone (a new room)."""
    i = 0
    while i < len(sub) and budget[0] > 0:
        got = p.wait_menu()
        if got is None:
            return False
        cur = got[3]
        if not same(cur, sub):
            if (v in cur):             # back at the verb menu: re-enter
                p.select(v)
                got = p.wait_menu(patience=1500)
                if got is None or not same(got[3], sub):
                    return True
            else:
                return depth > 0        # a parent list (fine) or a new room (over)
        sub = got[3] if same(got[3], sub) else sub
        if i >= len(sub):
            break
        ok, _ = p.select(i)
        if not ok:                          # a live menu that takes no input: a cutscene
            nudge(p, log)                   # waits on the pad without a card (the videophone)
            continue
        budget[0] -= 1
        got = p.wait_menu(patience=1500)
        if got is None:
            return False
        nxt = got[3]
        if not same(nxt, sub) and not (v in nxt) and depth < 2:
            log(f"{p.f}: {sub[i]!r} opens {nxt}")
            explore(p, nxt, v, depth + 1, log, budget)
            got = p.wait_menu()
            if got and same(got[3], nxt):
                p.press(satpilot.BACK); p.run(satpilot.STEP_GAP)
        i += 1
    return True


def nudge(p, log):
    """Press A until the live menu's labels change (a screen that waits on the
    pad while a menu reads live - the PS1 routes' {"press": "circle"})."""
    before = p.menu()[3]
    for i in range(30):
        p.press(satpilot.OK); p.run(60)
        if p.menu()[3] != before:
            log(f"{p.f}: nudged through after {i + 1} presses: {p.menu()[3]}")
            return True
    log(f"{p.f}: nudging did not move the menu {before}")
    return False


def sweep(p, verbs, rounds, log):
    """Every verb, every item of its submenu (and the lists under them),
    `rounds` times - the PS1 harness's sweep. A verb menu that only grew
    (Talk appearing) is the same level, not a submenu."""
    budget = [400]
    for r in range(rounds):
        for v in verbs:
            got = p.wait_menu()
            if got is None:
                return
            top = got[3]
            if not (v in top):
                continue
            ok, _ = p.select(v)
            if not ok:
                continue
            got = p.wait_menu(patience=1500)
            if got is None:
                continue
            sub = got[3]
            if (v in sub):                 # the verb acted by itself; back at the verb menu
                continue
            log(f"{p.f}: sweep {v!r} round {r}: {sub}")
            if not explore(p, sub, v, 0, log, budget):
                log(f"{p.f}: sweep {v!r} left the menus")
                return
            for _ in range(4):              # back to the verb menu
                got = p.wait_menu()
                if got is None or (v in got[3]):
                    break
                p.press(satpilot.BACK); p.run(satpilot.STEP_GAP)


def go(p, log, *labels, patience=3000):
    for label in labels:
        got = p.wait_menu(patience=patience)
        ok, got_labels = p.select(label)
        if not ok and got and (label in got_labels if isinstance(label, str) else True):
            nudge(p, log)
            ok, got_labels = p.select(label)
        log(f"{p.f}: {label!r} -> {ok} {got_labels}")


STAGES = ["new", "reception", "chief", "range", "squad", "computer", "gaudi"]


def tour(a):
    """The stages run from `a.stage` on (--state restores a bookmark first).
    Labels are the menu's 10-cell truncations ('Mechanic r')."""
    os.makedirs(OUT, exist_ok=True)
    log = log_to(os.path.join(OUT, "tour_log.txt"))
    emu = satrun.SaturnEmu()
    emu.load(a.image)
    p = Pilot(emu, log)
    p.trace = 3000
    mem = p.mem
    t0 = time.time()

    def hook(f):
        if f % 2000 == 0:
            shot(emu, "tour", f)

    if a.state:
        path = os.path.join(STATES, f"{a.state}.state.gz")
        emu.restore(gzip.decompress(open(path, "rb").read()))
        meta = json.load(open(path[:-9] + ".json", encoding="utf-8"))
        p.f = meta.get("frame", 0)
        log(f"{p.f}: restored {a.state}")
        if satmem.refresh_chunk_table(mem, image=a.image):
            log(f"{p.f}: chunk table / exec / GFS cache refreshed from the image (the bookmark's build differs)")
    stage = STAGES.index(a.stage)
    if stage <= 0:
        title, newgame = satpilot.presses(p.emu)
        p.run(title - p.f, hook); p.press(satpilot.OK)
        p.run(newgame - p.f, hook); p.press("c")
        log(f"{p.f}: NEW GAME; the opening runs untouched")
        while p.f < a.frames and not p.box()[1]:
            p.run(1, hook)
        log(f"{p.f}: first card waits: {[r for r in p.box()[2] if r]}")
        got = p.wait_menu(hook=hook)
        log(f"{p.f}: reception menu {got[3] if got else None}")
        p.save("keys_reception")
    if stage <= 1:
        # the reception: Mika, then Enter -> the Chief's room (any room reroutes there)
        sweep(p, ["Enter", "Talk", "Ask", "Look", "Check"], 2, log)
        got = p.wait_menu(); log(f"{p.f}: after the reception {got[3] if got else None}")
        if got and "Enter" in got[3]:
            go(p, log, "Enter", "Chief's r")
        sweep(p, ["Ask", "Talk", "Look", "Check"], 2, log)       # the JUNKER ID
        p.save("keys_chief")
    if stage <= 2:
        # Mika's guided tour ends with the Range (item 4: its label is painted
        # over by 'Computer room'). The Mechanic room is left alone: Harry and
        # Metal Gear's scene there (Ask Nanomachines) sends Gillian out to the
        # turbocycle and the HQ rooms are gone until Act 2.
        go(p, log, "Go out", 4)
        sweep(p, ["Talk", "Ask", "Look", "Check"], 1, log)
        p.save("keys_range")
    if stage <= 3:
        go(p, log, "Go out", "Squad room")
        sweep(p, ["Talk", "Ask", "Look", "Check"], 1, log)
        p.save("keys_squad")
    if stage <= 4:
        go(p, log, "Go out", "Computer r")
        sweep(p, ["Look", "Check", "Ask"], 1, log)
        got = p.wait_menu()
        log(f"{p.f}: Computer room verbs {got[3] if got else None}")
        p.save("keys_computer")
    if stage <= 5:
        got = p.wait_menu()
        if got and not has(got[3], "Use Gaudi") and a.poke_gaudi:
            # B010's local flag 0xA091 gates 'Use Gaudi' (the item's `fb` skip
            # in the Computer room's verb menu); how the story sets it on the
            # Saturn is not found yet - poked for the keyboard test only
            poke_flag(mem, emu, 0xA091, log)
            go(p, log, "Go out", "Computer r")
            got = p.wait_menu()
            log(f"{p.f}: Computer room verbs after the poke {got[3] if got else None}")
            p.save("keys_computer_gaudi")
        elif got and not has(got[3], "Use Gaudi"):
            # Mika's tour ends once the Mechanic room is seen (Harry); Metal
            # Gear's topics there are NOT asked (Nanomachines sends Gillian out)
            go(p, log, "Go out", "Mechanic r")
            got = p.wait_menu()
            log(f"{p.f}: Mechanic room verbs {got[3] if got else None}")
            p.save("keys_mechanic")
            go(p, log, "Go out", "Computer r")
            got = p.wait_menu()
            log(f"{p.f}: Computer room verbs {got[3] if got else None}")
            p.save("keys_computer2")
    # the Computer room's verb menu -> the search keyboard. Gaudi's terminal
    # (B030) waits on the pad without the card flag, so A is pressed whenever
    # no menu is live.
    go(p, log, "Use Gaudi")
    mem = p.mem
    chain = ("Use card", "Person fil", "Search nam")
    for i, label in enumerate(chain):
        # a menu further down the chain (or the keyboard itself) means this
        # step was already taken: an OK press on the open keyboard types A
        # (the 2026-09-16 bookmark carried 13 of them)
        if keyboard_up(mem):
            break
        for _ in range(60):
            live, idx, cnt, labels = p.menu()
            if live and any(has(labels, l) for l in chain[i:]) or keyboard_up(mem):
                break
            p.press(satpilot.OK); p.run(90)
        live, idx, cnt, labels = p.menu()
        if keyboard_up(mem) or not has(labels, label):
            continue
        ok, labels = p.select(label)
        log(f"{p.f}: {label!r} -> {ok} {labels}")
    for _ in range(3000):
        p.run(1)
        if keyboard_up(mem):
            break
    p.run(200)
    log(f"{p.f}: keyboard up: {keyboard_up(mem)}")
    shot(emu, "search_open", p.f)
    p.save("keys_search")
    log(f"{p.f}: keyboard state saved; cursor {mem.u16(CURSOR)},{mem.u16(CURSOR + 2)} in {time.time() - t0:.0f}s")


def inject_exec(emu, mem, old_exec, log):
    """A bookmark carries its build's exec: write into RAM every byte where
    the current patched/saturn/MAIN_L.BIN differs from `old_exec` (the exec
    the state was made with), so a rebuilt stub runs without a new tour."""
    import ctypes as C
    bdir = os.environ.get("KEYS_BUILD") or os.path.dirname(satkeys.OUT_MAIN)   # a private copy of the build
    new = open(os.path.join(bdir, "MAIN_L.BIN"), "rb").read()
    old = open(old_exec, "rb").read()
    assert len(new) == len(old)
    ptr = emu.core.retro_get_memory_data(2)
    n = 0
    for i in range(len(new)):
        if new[i] != old[i]:
            off = satmem.block_offset(satkeys.MAIN_BASE + i) ^ 1     # halfword-swapped host bytes
            C.memmove(C.c_void_p(ptr + off), bytes([new[i]]), 1)
            n += 1
    log(f"injected {n} exec bytes that differ from {os.path.basename(old_exec)}")
    # the bank's string region too (the keys' longs moved with the rebuild), and
    # satlong's recorded region length so LOOKUP finds the tail
    import re, struct
    data = open(os.path.join(bdir, "DATA.BIN"), "rb").read()
    bank = satkeys.built_bank(data, new)
    w0, region = satkeys.region_of(bank)
    if mem.read(0x002F8000, 64) != bank[4:68]:
        log("state holds another bank - region not injected")
        return
    base = 0x002E8000
    for i in range(0, len(region), 2):
        off = satmem.block_offset(base + i)
        C.memmove(C.c_void_p(ptr + off), bytes([region[i + 1] if i + 1 < len(region) else 0, region[i]]), 2)
    rep = open(os.path.join(bdir, "long_report.txt"), encoding="utf-8").read()
    lenvar = int(re.search(r"lenvar (0x[0-9a-f]+)", rep).group(1), 16)
    off = satmem.block_offset(lenvar)
    C.memmove(C.c_void_p(ptr + off), struct.pack("<I", len(region))[::-1][::-1], 4)
    # a u32 in host order: the halfword-swapped image of BE bytes b0 b1 b2 b3 is b1 b0 b3 b2
    be = struct.pack(">I", len(region))
    C.memmove(C.c_void_p(ptr + off), bytes([be[1], be[0], be[3], be[2]]), 4)
    log(f"injected B040 region ({len(region)} bytes) and lenvar at {lenvar:#x} = {mem.u32(lenvar)}")


def type_names(a):
    os.makedirs(OUT, exist_ok=True)
    log = log_to(os.path.join(OUT, "type_log.txt"))
    emu = satrun.SaturnEmu()
    emu.load(a.image)
    p = Pilot(emu, log)
    path = os.path.join(STATES, f"{a.state}.state.gz")
    emu.restore(gzip.decompress(open(path, "rb").read()))
    meta = json.load(open(path[:-9] + ".json", encoding="utf-8"))
    p.f = meta.get("frame", 0)
    mem = p.mem
    if a.inject:
        inject_exec(emu, mem, a.inject, log)
    elif satmem.refresh_chunk_table(mem, image=a.image):
        log(f"{p.f}: chunk table / exec / GFS cache refreshed from the image (the bookmark's build differs)")
    p.run(30)
    grid = satkeys.grid_cells(a.layout)          # char -> (row, col)

    def cursor():
        return mem.u16(CURSOR + 2), mem.u16(CURSOR)

    def tap(btn, gap=satpilot.STEP_GAP):
        p.press(btn); p.run(gap)

    def goto(row, col):
        for _ in range(40):
            r, c = cursor()
            if (r, c) == (row, col):
                return True
            if r != row:
                tap("down" if r < row else "up")
            else:
                tap("right" if c < col else "left")
        log(f"{p.f}: cursor stuck at {cursor()}, wanted {(row, col)}")
        return False

    def typed():
        b = mem.read(TYPED, 14)
        return b[:b.index(0)] if 0 in b else b

    for name in a.names:
        log(f"{p.f}: typing {name!r} from cursor {cursor()} typed={typed().hex()}")
        for ch in name.upper():
            rc = grid.get(ch)
            assert rc, (name, ch)
            assert goto(*rc)
            tap(satpilot.OK, 24)
        log(f"{p.f}: typed {typed().hex()} ({len(typed())} keys)")
        shot(emu, f"{name}_typed", p.f)
        # the OK button (key 56) is skipped by left/right on row 3 (the pad
        # handler wraps the column past it); it is reached from row 2 by down
        assert goto(2, 12)
        tap("down")
        log(f"{p.f}: on OK at {cursor()}")
        tap(satpilot.OK, 90)
        shot(emu, f"{name}_ok", p.f)
        # let the reply come up: advance cards, capture each
        for i in range(a.cards):
            for _ in range(600):
                p.run(1)
                up, waiting, rows = p.box()
                if waiting:
                    break
            up, waiting, rows = p.box()
            log(f"{p.f}: card {i}: waiting={waiting} rows={[r for r in rows if r]}")
            shot(emu, f"{name}_card{i}", p.f)
            if not waiting:
                break
            tap(satpilot.OK, 40)
        p.run(120)
        shot(emu, f"{name}_after", p.f)
        # back to the keyboard for the next name: it reopens by itself in the JP flow
        # (Search name again); the state is restored fresh instead
        if name != a.names[-1]:
            emu.restore(gzip.decompress(open(path, "rb").read()))
            p.f = meta.get("frame", 0)
            if a.inject:
                inject_exec(emu, mem, a.inject, log)
            p.run(30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["tour", "type"])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--image", default=IMAGE)
    ap.add_argument("--state", default=None)
    ap.add_argument("--frames", type=int, default=400000)
    ap.add_argument("--cards", type=int, default=6)
    ap.add_argument("--layout", default="latin", choices=["latin", "kana"])
    ap.add_argument("--poke-gaudi", action="store_true", help="tour: force 'Use Gaudi' with the flag poke")
    ap.add_argument("--inject", default=None, metavar="OLD_EXEC",
                    help="type: refresh the state's exec from patched/saturn/MAIN_L.BIN (bytes differing from OLD_EXEC)")
    ap.add_argument("--stage", default="new", choices=STAGES,
                    help="with --state: where the state sits (the tour resumes from there)")
    a = ap.parse_args()
    if a.cmd == "tour":
        tour(a)
    else:
        a.state = a.state or "keys_search"
        type_names(a)


if __name__ == "__main__":
    main()
