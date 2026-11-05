"""The opening's subtitles, played headless from a fresh boot: New Game, then the opening
untouched (or skipped with a press at --skip), then B010 until the reception's first card.

Logs every card of the INTRO blob (B000's; its address from work/saturn/build/subs_layout.json)
with its first and last frame on screen, captures each card once it is open and every
--every frames while one is up, then checks what must hold after the opening: B010 loaded,
object 0 back at the engine's priority 28 (the blob raises it to 31 while a card is up), the
box parked, the reception's first card typed by the engine, the vblank counter running.

    python saturn/harness/intro_run.py [image.cue] [--skip 9000] [--out DIR] [--layout FILE]

--measure (on the PRISTINE image by default, so no card of ours is on screen): every frame of
the two narration reels, the reel number, its stream position and the picture's lowest
non-black row (a row with >= MIN_PIX pixels brighter than DARK) -> work/saturn/intro_sub/
picture_rows.json, which gen_intro.py turns into each card's y.

    python saturn/harness/intro_run.py --measure
"""
import os, sys, json, argparse
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'ps1/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]
import satrun, satmem, satsubs

CTX = satsubs.CTX
BOX_WAIT = satsubs.BOX_WAIT
VBLANK = 0x060F5640
PRESSES = {2300: {0}, 2308: set(), 2700: {11}, 2708: set()}      # A on the title, C on NEW GAME
PRISTINE = os.path.join(ROOT, "discs", "iso_saturn_jp", "Snatcher (Japan).cue")
PICTURE_ROWS = os.path.join(WORK, "saturn", "intro_sub", "picture_rows.json")
DARK, MIN_PIX = 40, 4                   # a pixel counts as picture above this (max of R, G, B)


def measure(image, out):
    """Per frame while reel 140 or 141 plays: [reel, stream position, lowest picture row]."""
    import numpy as np
    emu = satrun.SaturnEmu(); emu.load(image)
    m = satmem.SatMem(emu.core)
    d = emu.boot_screens                # satsplash's boot screens (0 on the pristine disc)
    presses = {k + d: v for k, v in PRESSES.items()}
    rows = []
    for f in range(25400 + d):
        if f in presses:
            emu.held = presses[f]
        emu.run()
        reel = m.u16(0x060EFE6A)
        if f < 3000 + d or reel not in (140, 141) or m.u32(0x060EFE64) != 1:
            continue
        a = np.asarray(emu.image()).max(axis=2)
        lit = np.nonzero((a > DARK).sum(axis=1) >= MIN_PIX)[0]
        rows.append([f, reel, m.u32(0x060EFF0C), int(lit[-1]) if len(lit) else -1])
        if f % 1000 == 0:
            print(f, rows[-1], flush=True)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"image": os.path.basename(image), "dark": DARK, "min_pix": MIN_PIX, "height": a.shape[0],
               "frames": rows}, open(out, "w"))
    print(f"{len(rows)} frames -> {out}")


def main():
    if "--measure" in sys.argv:
        rest = [x for x in sys.argv[1:] if not x.startswith("--")]
        measure(rest[0] if rest else PRISTINE, PICTURE_ROWS)
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default=os.path.join(ROOT, "patched", "saturn", "Snatcher (Japan).cue"))
    ap.add_argument("--layout", default=satsubs.LAYOUT_JSON)
    ap.add_argument("--out", default=os.path.join(WORK, "saturn", "intro_run"))
    ap.add_argument("--skip", type=int, default=0, help="press A at this frame (skips the opening)")
    ap.add_argument("--frames", type=int, default=0, help="stop here (default: the reception's first card + 300)")
    ap.add_argument("--every", type=int, default=120)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    blob = json.load(open(a.layout, encoding="utf-8"))["scenes"]["B000"]["blob"]
    spec = json.load(open(os.path.join(ROOT, "saturn", "translation", "subs_INTRO.json"), encoding="utf-8"))
    cues = [c for c in spec["cues"] if c.get("enabled", True)]
    log = open(os.path.join(a.out, "log.txt"), "w", encoding="utf-8")

    def P(s):
        print(s.encode("ascii", "replace").decode(), flush=True)
        log.write(s + "\n")

    emu = satrun.SaturnEmu(); emu.load(a.image)
    m = satmem.SatMem(emu.core)
    press = {k + emu.boot_screens: v for k, v in PRESSES.items()}     # after satsplash's boot screens
    if a.skip:
        press[a.skip] = {0}
        press[a.skip + 8] = set()
    P(f"image {a.image}; INTRO blob at {blob:#x}; skip {a.skip or 'none'}")
    spans, cur_id, since, ids = [], None, 0, None
    b010_at = card_at = fc_at = None
    checked = False
    problems = []
    stop = a.frames or 40000
    f = 0
    while f < stop:
        if f in press:
            emu.held = press[f]
        emu.run()
        scene, bank = m.u16(satsubs.SCENE_VAR), None
        live = scene == 0 and m.u32(blob) == satsubs.MAGIC
        if live and ids is None:
            base = m.u32(blob + 8)
            ids = {base + satsubs.CUE_SIZE * i: c["id"] for i, c in enumerate(cues)}
        cid = None
        if live and ids:
            cur, pst = m.u32(blob + 16), m.u32(blob + 28)
            cid = ids.get(cur) if cur and pst in (1, 2) else None
        if cid != cur_id:
            if cur_id:
                spans.append((cur_id, since, f - 1))
                P(f"{f - 1}: card {cur_id} down (up {since}..{f - 1}, {f - since} frames)")
            if cid:
                P(f"{f}: card {cid} up - reel {m.u16(0x060EFE6A)} pos {m.u32(0x060EFF0C)}")
            cur_id, since = cid, f
        if cid and (f - since == 20 or (f - since) % a.every == 0 and f > since):
            emu.image().save(os.path.join(a.out, f"card_{f:06d}_{cid}.png"))
        if b010_at is None and scene == 1 and satmem.bank_in_ram(m) == 22:
            b010_at = f
            P(f"{f}: B010 loaded; object 0 priority {m.u8(satsubs.OBJ0_PRIO)}, list {m.u32(satsubs.OBJ0_LIST):#x}, box y {m.u16(satsubs.BOX_Y)}")
        if b010_at is not None and fc_at is None:
            fc_at = m.u32(CTX)                  # the frame wait's counter (ctx+0): it stands still through
        if fc_at is not None and not checked and m.u32(CTX) >= fc_at + 2:
            # the load and ACT 1 (a skip: ~75 frames, nothing redrawn); the renderer stub's `unstale`
            # puts a raised priority and a stale list back on the new bank's first frame wait
            checked = True
            P(f"{f}: B010's frame waits run: object 0 priority {m.u8(satsubs.OBJ0_PRIO)}, list {m.u32(satsubs.OBJ0_LIST):#x}, box y {m.u16(satsubs.BOX_Y)}")
            if m.u8(satsubs.OBJ0_PRIO) != 28:
                problems.append(f"object 0 priority {m.u8(satsubs.OBJ0_PRIO)} after the opening")
            if m.u32(satsubs.OBJ0_LIST) not in (satsubs.BOX_LIST, satsubs.BAND_LIST):
                problems.append(f"object 0 on list {m.u32(satsubs.OBJ0_LIST):#x} after the opening")
        if b010_at is not None and card_at is None and m.u8(BOX_WAIT) and any(satmem.cells(m, 4, 20)):
            card_at = f
            rows = satmem.cells(m, 4, 20)
            P(f"{f}: the reception's first card waits: {rows}; object 0 priority {m.u8(satsubs.OBJ0_PRIO)}")
            emu.image().save(os.path.join(a.out, f"b010_card_{f:06d}.png"))
            if not a.frames:
                stop = f + 300
        if f % 1000 == 0:
            v = m.u32(VBLANK)
            P(f"{f}: scene {scene} bank {satmem.bank_in_ram(m)} vblank {v}")
        f += 1
    emu.image().save(os.path.join(a.out, f"final_{f:06d}.png"))
    if cur_id:
        spans.append((cur_id, since, f - 1))
    v0 = m.u32(VBLANK); emu.run(); emu.run()
    if m.u32(VBLANK) == v0:
        problems.append("the vblank counter stopped (a wedge)")
    if b010_at is None:
        problems.append("B010 never loaded")
    elif card_at is None:
        problems.append("no engine card in B010")
    shown = {s[0] for s in spans}
    missing = [c["id"] for c in cues if c["id"] not in shown]
    P(f"cards shown {len(shown)} of {len(cues)}; missing {missing}")
    for cid, s0, s1 in spans:
        P(f"  {cid:18} frames {s0}..{s1} ({(s1 - s0 + 1) / 59.94:.1f} s)")
    P("PROBLEMS: " + ("; ".join(problems) if problems else "none"))
    json.dump({"spans": spans, "b010": b010_at, "card": card_at, "problems": problems},
              open(os.path.join(a.out, "result.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
