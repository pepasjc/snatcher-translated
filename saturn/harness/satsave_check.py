# -*- coding: utf-8 -*-
"""Boot the Saturn image headless with a library save in place, take CONTINUE
on the title, load the file and report which bank comes up.

    python saturn/harness/satsave_check.py B020_auto [--image CUE] [--slot 1]

The save goes to work/emu/<image stem>.bkr first (Beetle Saturn reads it at
retro_load_game - satsave.py's `use`); the title is pressed at ~2300 (A),
the NEW GAME / CONTINUE / OPTIONS menu at ~2700 (down, C), then the load
list is read from the cells (satplay's decoder) and the slot picked; the
run ends when a bank other than B000 is in RAM and its first verb menu is
live, or at --frames. Verdict: the bank against the entry's `bank`.
"""
import argparse, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import satrun, satmem, satpilot, satplay, satsave


def continue_from_title(play, log=print):
    """A on the title, then CONTINUE (item 1) on NEW GAME / CONTINUE / OPTIONS.
    The title menu keeps its cursor in the list-menu index u16 at ctx+0x3F8
    (found 2026-09-15 by diffing high WRAM across down/down/down/up on it:
    the only byte going +1 +1 wrap -1 was 0x060F28A9) but never sets the
    live byte ctx+0x3F7, and its labels are not in the cells: the menu being
    up is read from the picture (mean brightness 42.7 against the title's
    124; probe_title2.py). Blind timings (down+C at 2730) took only every
    other run - Beetle's autortc seeds the title from the host clock. The
    confirm is believed when a card waits (ctx+0xB74: 'Loading the internal
    RAM data.') or a list menu goes live. Returns True on that."""
    import numpy as np
    m = play.mem
    play.run(max(satpilot.presses(play.emu)[0] - play.f, 1)); play.press(satpilot.OK)
    dark = 0
    for _ in range(200):
        play.run(20)
        if float(np.asarray(play.emu.image()).mean()) < 60:
            dark += 1
            if dark >= 2:
                break
        else:
            dark = 0
    else:
        log(f"{play.f}: title menu never came up"); return False
    play.run(satpilot.MENU_SETTLE)
    for attempt in range(8):
        idx = m.u16(satmem.MENU_INDEX)
        if idx != 1:
            play.press("down" if idx == 0 else "up"); play.run(satpilot.STEP_GAP)
            continue
        play.press("c")
        for _ in range(600):
            play.run(1)
            if m.u8(satmem.BOX_WAIT) == 1:
                log(f"{play.f}: CONTINUE confirmed (cursor {idx}): {[r for r in satmem.cells(m) if r]}")
                return True
    log(f"{play.f}: CONTINUE never took (cursor {m.u16(satmem.MENU_INDEX)})")
    return False


def load_file(play, slot, log=print):
    """On the load list ('1 ACT 1' .. '4 NO DATA' / "Don't load"): pick the
    slot and believe it once the list is gone or another bank is in RAM
    (the list's cells and live byte stay behind while the scene loads, so
    satplay.pick's 'labels changed' test never fires). Returns the labels."""
    got = play.wait_menu(patience=3000)
    labels = play.labels_now() if got else []
    low = [x.lower() for x in labels]
    if not (len(low) >= 4 and all(x[:1] == str(i + 1) for i, x in enumerate(low[:4]))):
        log(f"{play.f}: no load list ({labels})"); return labels
    log(f"{play.f}: load list {labels}")
    bank0 = play.bank
    play.pick(slot - 1)                     # steers, presses, may report 'never took'
    if play.bank != bank0:
        log(f"{play.f}: file {slot} taken (bank {satplay.BANK_NAMES.get(play.bank)})")
        return labels
    for k in range(6):
        for _ in range(120):
            play.run(1)
            if play.bank != bank0 or play.mem.u8(satmem.MENU_LIVE) != 1:
                log(f"{play.f}: file {slot} taken (bank {satplay.BANK_NAMES.get(play.bank)})")
                return labels
        play.press(satpilot.OK)
    log(f"{play.f}: file {slot} never loaded"); return labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--image", default=satsave.PLAY_IMAGE)
    ap.add_argument("--slot", type=int, default=0, help="file to load (default: the entry's)")
    ap.add_argument("--frames", type=int, default=40000)
    ap.add_argument("--out")
    ap.add_argument("--bookmark", help="save the state at the loaded bank's verb menu under this name (work/saturn/states/)")
    a = ap.parse_args()
    s = satsave.entry_of(a.name)
    slot = a.slot or s.get("slot") or 1
    out = a.out or os.path.join(satsave.STORE, "runs", f"check_{a.name}")
    os.makedirs(out, exist_ok=True)
    logf = open(os.path.join(out, "log.txt"), "w", encoding="utf-8")

    def log(m):
        logf.write(m + "\n"); logf.flush(); print(m, flush=True)

    os.makedirs(satsave.EMU_SAVES, exist_ok=True)
    bkr = os.path.join(satsave.EMU_SAVES, satsave.image_stem(a.image) + ".bkr")
    raw = satsave.read_image(s["path"])
    open(bkr, "wb").write(raw)
    log(f"{a.name} -> {bkr}: files {[f['name'] for f in satsave.parse_dir(raw)]}, want bank {s.get('bank')}, slot {slot}")
    emu = satrun.SaturnEmu(); emu.load(a.image)
    play = satplay.Play(emu, out, log, a.image, autosave=False)
    got = satmem.state_ram(emu.state(), "BackupRAM", swap=False)
    log(f"core BackupRAM after load {'matches' if got == raw else 'DIFFERS FROM'} the file")
    t0 = time.time()
    if not continue_from_title(play, log):
        sys.exit(2)
    emu.image().save(os.path.join(out, f"f{play.f:06d}_continue.png"))
    labels = load_file(play, slot, log)
    low = [x.lower() for x in labels]
    is_list = len(low) >= 4 and all(x[:1] == str(i + 1) for i, x in enumerate(low[:4]))
    verdict, since = "no load list" if not is_list else "file never loaded", play.f
    while is_list and play.f < a.frames:
        # the load list's cells and live byte stay behind while the scene
        # loads and, on a stalled load, for ever: wait for the verb menu of
        # a bank other than B000 without pressing anything
        play.run(30)
        b = play.bank
        live = play.mem.u8(satmem.MENU_LIVE) == 1
        now = play.labels_now() if live else []
        if b and b != 21 and live and now and now != labels and play.is_top(now):
            verdict = f"bank {satplay.BANK_NAMES.get(b)} verb menu {now}"; break
        if b and b != 21 and play.f - since > 3000:
            verdict = f"bank {satplay.BANK_NAMES.get(b)} loaded, then STALLED (no verb menu in {play.f - since} frames; cells {[r for r in satmem.cells(play.mem) if r][:2]})"
            emu.image().save(os.path.join(out, f"f{play.f:06d}_stalled.png"))
            break
    want = (s.get("slot_banks") or {}).get(str(slot), s.get("bank"))   # a packed image: one bank per slot
    ok = want is not None and verdict.startswith(f"bank {want} verb menu")
    log(f"verdict: {verdict}; want {want}: {'OK' if ok else 'MISMATCH'} ({time.time() - t0:.0f}s)")
    if a.bookmark and verdict.startswith("bank "):
        play.save(a.bookmark)
        log(f"bookmark {a.bookmark} saved at frame {play.f}")
    if ok and s.get("slot_banks"):
        ix = satsave.load_index()
        ix["snapshots"][a.name].setdefault("checked_slots", {})[str(slot)] = time.strftime("%Y-%m-%d %H:%M")
        satsave.write_index(ix)
    emu.image().save(os.path.join(out, "final.png"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
