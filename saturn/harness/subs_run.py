# -*- coding: utf-8 -*-
"""Play-test the Saturn voice-line subtitles headless: any scene's cue check.

    python saturn/harness/subs_run.py                  New Game -> reception, then the exchange (the B010 POC)
    python saturn/harness/subs_run.py --state B010_subs_start   from the bookmark this run leaves
    python saturn/harness/subs_run.py --scene B020 --state B020_start --route saturn/harness/routes/B020_subs.json

The B010 default: from the reception's verb menu, Enter (item 0, the
receptionist's card), then Talk (item 3: three voiced lines, 198/199/227,
under the face band). With `--route` the pilot plays that route's actions
instead (satpilot's JSON shape) with the same per-frame hook. Every frame the
payload's state is read back (blob+16 = the current cue pointer, object 0's
list pointer 0x060F2CF8, the cells, the live line and its decoded bytes, the
box y, the band flag) and logged on change; a capture every 20 frames while
a card is up (every 100 otherwise) goes to `--out` (default
work/saturn/subs_<scene>/) as run_*.png. The game's own cards are pressed
through after 60 frames of waiting. After the actions the run idles
(`--idle`) and reports the frame counter still moving. Verdict lines at the
end: each cue that showed, when, for how long, what the cells held (decoded
through the Saturn pair table, so the English reads back) and its layout
(band / plain box), the cues of the file never drawn while their line
played, and the game's cards seen. A restored state gets the current build's
chunk table written into RAM first (satmem.refresh_chunk_table: satpack
moves every chunk, and a bookmark carries its build's table).
"""
import argparse, gzip, json, os, re, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import satrun, satmem, satpilot, satsubs, satfont

OUT_DEFAULT = os.path.join(WORK, "saturn", "subs_poc")
TICK = 0x060F5640                     # a free-running frame counter (0x060B1608 bumps it every vblank)
VERBOSE = os.environ.get("SUBS_VERBOSE") == "1"   # log every frame while a line or reel is live
OBJTRACE = os.environ.get("OBJTRACE") == "1"      # log every live sprite object past the nine face cels (10..0x84) on change


def pair_decoder():
    """SJIS cell code -> text through the build's pair table (fallbacks stay fullwidth)."""
    table = json.load(open(satsubs.SAT_TABLE))
    rev = {satfont.code_to_sjis(code): pair for pair, (slot, code) in table.items()}
    def dec(code):
        if code in rev:
            return rev[code]
        try:
            return code.to_bytes(2, "big").decode("cp932")
        except UnicodeDecodeError:
            return "?"
    return dec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state")
    ap.add_argument("--image", default=os.path.join(ROOT, "patched", "saturn", "Snatcher (Japan).cue"))
    ap.add_argument("--idle", type=int, default=2000)
    ap.add_argument("--then", default="", help="menu indices to pick after the exchange, comma-separated (e.g. 2,3)")
    ap.add_argument("--scene", default="B010")
    ap.add_argument("--route", help="a satpilot route to play instead of the B010 Enter/Talk exchange")
    ap.add_argument("--out", help="capture/log directory (default work/saturn/subs_<scene>/, subs_poc for B010)")
    ap.add_argument("--frames", type=int, default=40000, help="frame budget for a --route run")
    ap.add_argument("--dump-at", default="", help="frames at which to save raw states (work/saturn/states/<scene>_f<N>.state.gz)")
    ap.add_argument("--inject-blob", action="store_true",
                    help="(the default since 2026-09-16; NO_INJECT=1 keeps the bookmark's own blob) after a restore, "
                         "write the current build's blob for the scene into the bank's string region")
    a = ap.parse_args()
    OUT = a.out or (OUT_DEFAULT if a.scene == "B010" and not a.route else os.path.join(WORK, "saturn", f"subs_{a.scene.lower()}"))
    os.makedirs(OUT, exist_ok=True)
    logf = open(os.path.join(OUT, "run_log.txt"), "w", encoding="utf-8")

    def log(m):
        logf.write(m + "\n"); logf.flush(); print(m, flush=True)

    emu = satrun.SaturnEmu(); emu.load(a.image)
    pilot = satpilot.Pilot(emu, log)
    m = pilot.mem
    dec = pair_decoder()

    def pair_menu_labels(mem):
        """satmem.menu_labels through the build's pair table, so the pilot's label matching reads English."""
        grid = []
        for r in range(4):
            row = mem.read(satmem.TEXT_CELLS + r * satmem.TEXT_ROW, 80)
            grid.append([" " if struct.unpack_from(">H", row, c * 4)[0] in (0, satmem.BLANK_CELL)
                         else dec(struct.unpack_from(">H", row, c * 4)[0]) for c in range(20)])
        return ["".join(grid[st // 20][st % 20:st % 20 + 10]).strip() for st in satmem.MENU_STARTS]
    satmem.menu_labels = pair_menu_labels
    cues = {}
    spec = json.load(open(os.path.join(ROOT, "saturn", "translation", f"subs_{a.scene}.json"), encoding="utf-8"))
    blob = open(os.path.join(satsubs.BUILD, f"subs_{a.scene}.blob"), "rb").read()
    BLOB = json.load(open(satsubs.LAYOUT_JSON, encoding="utf-8"))["scenes"][a.scene]["blob"]   # this scene's blob address
    from sh2s import Asm
    _asm = Asm(BLOB + 0x20); _asm.assemble(satsubs.payload_asm(BLOB))
    BPLAIN = _asm.labels["bplain"]                     # 1 while the card up is plain-in-band (nameplate + rows, columns parked)
    EXOWN = _asm.labels.get("exown", 0)                # extras: per object 10..EX_LAST its column + 1
    cues_addr = struct.unpack_from(">I", blob, 8)[0]
    for i, c in enumerate(spec["cues"]):
        cues[cues_addr + satsubs.CUE_SIZE * i] = c
    dump_at = {int(x) for x in a.dump_at.split(",") if x}
    shown = []          # (cue id, first frame, last frame, text, layout)
    parkedby = {}       # cue id -> the columns (characters) parked at FACE_AWAY while it was up
    upgraded = set()    # cues that started plain-in-band and got their face when its chunk landed
    last = None
    seen_cards = []
    seen_lines = {}     # voice sector -> first frame it was live
    last_raw = [None]
    under_band = []     # frames where the cells changed under the engine's own band list
    overlap = {}        # cue id -> frames a band card was up with a shown column under its text (x 90..340)
    spoff = {}          # cue id -> {object: frames} a face-buffer sprite sat neither in the window nor away (#48)

    def cell_rows():
        """The 4 x 20 cells as decoded strings per cell (blank = ' ')."""
        out = []
        for r in range(4):
            row = m.read(satmem.TEXT_CELLS + r * 80, 80)
            out.append([dec(struct.unpack_from(">H", row, c * 4)[0]) if struct.unpack_from(">H", row, c * 4)[0] not in (0, satmem.BLANK_CELL) else " " for c in range(20)])
        return out

    def rows(col0=0, row0=0, nrows=4):
        return ["".join(r[col0:]).rstrip() for r in cell_rows()[row0:row0 + nrows]]

    OBJ = lambda n: satsubs.CTX + 0x830 + 76 * n

    def faces():
        """The three face columns: (act, x, y, srca, buf) of each base cel, and the voice ids
        its mouth cel carries. A column is objects 1+3c/2+3c/3+3c (76-byte objects at
        ctx+0x830); +0 act (1 shown, 3 hidden), +8 x, +12 y, +28 CMDSRCA base = the VDP1
        face slot, +32 the structure buffer = the face's identity in the room."""
        out = []
        for c in range(3):
            b = m.read(OBJ(1 + 3 * c), 76)
            mo = m.read(OBJ(3 + 3 * c), 76)
            out.append(dict(col=c, act=b[0], x=satsubs.shown_x(struct.unpack_from(">H", b, 8)[0]), y=struct.unpack_from(">h", b, 12)[0],
                            srca=struct.unpack_from(">H", b, 28)[0], buf=struct.unpack_from(">I", b, 32)[0],
                            ids=[v for v in struct.unpack_from(">8H", mo, 60) if v]))
        return out

    import facechunks
    ident = {}                                   # (srca, buf) -> character name, per card (the slot changes per room)

    def who(srca):
        """The character whose portrait sits in the VDP1 slot at CMDSRCA base `srca`: the 16
        bytes at facechunks.SIG_OFF read out of a savestate (the emulator maps no VRAM)."""
        blob = emu.state()
        off = 32
        while off + 36 <= len(blob):
            name = blob[off:off + 32].split(b"\0")[0]
            size = struct.unpack_from("<I", blob, off + 32)[0]
            if name.startswith(b"VDP1"):
                p, end = off + 36, off + 36 + size
                while p < end:
                    nl = blob[p]; nm = blob[p + 1:p + 1 + nl]
                    vs = struct.unpack_from("<I", blob, p + 1 + nl)[0]
                    p += 1 + nl + 4
                    if b"VRAM" in nm:
                        a = srca * 8 + facechunks.SIG_OFF
                        sig = satmem.unswap(blob[p + (a & ~1):p + (a & ~1) + facechunks.SIG_LEN + 2])[a & 1:][:facechunks.SIG_LEN]
                        return facechunks.char_of(sig)
                    p += vs
            off += 36 + size
        return None

    def face_key(f):
        k = (f["srca"], f["buf"])
        if k not in ident:
            ident[k] = who(f["srca"])
        return ident[k] or k

    def face_state():
        return [(f["act"], f["x"], f["y"], f["srca"], f["buf"]) for f in faces()]

    def at_window():
        """The column sitting in the band's window (x = 24) and shown, or None."""
        return next((f for f in faces() if f["act"] == 1 and f["x"] == satsubs.FACE_X), None)

    FACE_SRCA0 = (satsubs.FACE_SLOT0 - satsubs.VDP1_VRAM) >> 3

    def sprites_off():
        """Live sprite objects past the nine cels on a column's row or the band row drawn where no
        face is (satsubs.band_sprite_off: against the owning column's x, `exown`; a stray band
        sprite in the text area) - the op 0x05 animations (#48/#55/#57/#59), the ruins' Metal
        Gear room sprite (#45)."""
        cols = [(m.u8(OBJ(1 + 3 * c)), m.u16(OBJ(1 + 3 * c) + 8), m.u16(OBJ(1 + 3 * c) + 12)) for c in range(3)]
        rows = {y for act, x, y in cols if act == 1} | {160}
        out = []
        for n in range(10, 0x85):
            o = OBJ(n)
            if m.u8(o) != 1 or m.u16(o + 12) not in rows:
                continue
            owner = m.u8(EXOWN + n - 10) if EXOWN and n <= satsubs.EX_LAST else 0
            if satsubs.band_sprite_off(m.u16(o + 8), m.u16(o + 12), owner, cols):
                out.append(n)
        return out

    def hook(f):
        nonlocal last
        cur = m.u32(BLOB + 16)
        v = dict(sec=m.u16(0x060EA2C2), dec=m.u32(0x060EA2BC), band=m.u16(0x060F2A08), s558=m.u16(satsubs.CTX + 0x558),
                 y=m.u16(0x060F2CEC), lst=m.u32(0x060F2CF8), cur=cur, wait=m.u8(satsubs.BOX_WAIT),
                 menu=m.u8(satmem.MENU_LIVE), scene=m.u16(satsubs.SCENE_VAR), magic=m.u32(BLOB), rows=rows(),
                 reel=m.u16(satsubs.REEL_NO) if m.u32(satsubs.REEL_PLAYING) == 1 else -1, rpos=m.u32(satsubs.REEL_POS),
                 lay=m.u32(BLOB + 24), pst=m.u32(BLOB + 28))
        v["faces"] = face_state()
        v["voice"] = m.u16(satsubs.VOICE_ID)
        if OBJTRACE:
            # objects the room script builds beside the columns (op 0x05: an animation from a face
            # buffer, e.g. the Teller's trance in B0D0): act, type, x, y, list, srca, buf, frame
            objs = []
            for n in range(10, 0x85):
                b = m.read(OBJ(n), 76)
                if b[0]:
                    objs.append((n, b[0], b[1], struct.unpack_from(">h", b, 8)[0], struct.unpack_from(">h", b, 12)[0],
                                 struct.unpack_from(">I", b, 24)[0], struct.unpack_from(">H", b, 28)[0],
                                 struct.unpack_from(">I", b, 32)[0], struct.unpack_from(">H", b, 36)[0]))
            v["objs"] = objs
        key = {k: v[k] for k in v if k not in ("dec", "rpos")}
        if VERBOSE and (v["reel"] >= 0 or v["sec"]):
            key = dict(v)                       # every frame while a line or reel is live
        if key != last:
            cid = cues[cur]["id"] if cur in cues else "-"
            log(f"{f}: sec={v['sec']} dec={v['dec']} reel={v['reel']} rpos={v['rpos']} band={v['band']} y={v['y']} list={v['lst']:#x} "
                f"cue={cid} lay={v['lay']} pst={v['pst']} wait={v['wait']} menu={v['menu']} scene={v['scene']} magic={v['magic']:#x} "
                f"voice={v['voice']:#06x} faces={v['faces']} rows={[r for r in v['rows'] if r]}"
                + (f" objs={[(n, act, t, x, y, f'{lst:#x}', srca, f'{buf:#x}', fr) for n, act, t, x, y, lst, srca, buf, fr in v['objs']]}" if OBJTRACE and v.get('objs') else ""))
            if cur in cues and (not shown or shown[-1][0] != cues[cur]["id"] or shown[-1][2] < f - 5):
                ident.clear()                                        # a new card: name its columns afresh
                band = v["band"] == 2
                lay = ("bandplain" if m.u32(BPLAIN) == 1 else "band") if band else "plain"
                shown.append([cues[cur]["id"], f, f, [r for r in (rows(satsubs.COL0, satsubs.ROW0, satsubs.ROWS) if lay == "band" else rows()) if r], lay, set(), set()])
            last = key
        if v["sec"] and v["sec"] not in seen_lines:
            seen_lines[v["sec"]] = f
        if v["reel"] >= 0 and ("reel", v["reel"]) not in seen_lines:
            seen_lines[("reel", v["reel"])] = f
        # goal-3 detector: cells changing while the engine's own band list is up and no card of ours
        # is shown = the engine laying out text under the band (its type-on writes a cell a frame)
        raw = m.read(satmem.TEXT_CELLS, 320)
        typed = last_raw[0] is not None and raw != last_raw[0] and any(
            struct.unpack_from(">H", raw, i)[0] not in (0, satmem.BLANK_CELL) and raw[i:i + 2] != last_raw[0][i:i + 2]
            for i in range(0, 320, 4))                      # a non-blank cell appeared: text, not the engine's clear
        if v["band"] == 2 and v["lst"] == satsubs.BAND_LIST and not cur and typed:
            under_band.append(f)
            if len(under_band) < 20:
                log(f"{f}: ENGINE TEXT UNDER THE BAND? cells changed while the band list is up: {[r for r in v['rows'] if r]}")
        last_raw[0] = raw
        if cur in cues and shown and shown[-1][0] == cues[cur]["id"]:
            shown[-1][2] = f
            if shown[-1][4] == "bandplain" and m.u32(BPLAIN) == 0 and v["band"] == 2:
                shown[-1][4] = "band"                 # the speaker's portrait landed late: upgraded to the face layout
                upgraded.add(shown[-1][0])
            w = at_window()                       # the face in the band's window while this card is up
            if not shown[-1][5]:
                shown[-1].append(face_key(w) if w else None)      # the face up on the card's FIRST frame
            shown[-1][5].add(face_key(w) if w else None)
            shown[-1][6].update(face_key(x) for x in faces() if x["act"] == 1 and x["x"] != satsubs.FACE_AWAY
                                and x["x"] != satsubs.FACE_X)
            parkedby.setdefault(shown[-1][0], set()).update(face_key(x) for x in faces() if x["act"] == 1 and x["x"] == satsubs.FACE_AWAY)
            if shown[-1][4] in ("band", "bandplain") and any(x["act"] == 1 and 90 <= x["x"] <= 340 for x in faces()):
                overlap[shown[-1][0]] = overlap.get(shown[-1][0], 0) + 1   # a portrait under the text cells
            if shown[-1][4] in ("band", "bandplain"):
                for n in sprites_off():
                    spoff.setdefault(shown[-1][0], {})[n] = spoff.get(shown[-1][0], {}).get(n, 0) + 1
        if (cur and f % 20 == 0) or f % 100 == 0:
            emu.image().save(os.path.join(OUT, f"run_f{f:06d}.png"))
        if f in dump_at:
            os.makedirs(satpilot.STATES, exist_ok=True)
            open(os.path.join(satpilot.STATES, f"{a.scene}_f{f}.state.gz"), "wb").write(gzip.compress(emu.state()))
            log(f"{f}: state dumped ({a.scene}_f{f})")

    t0 = time.time()
    if a.state:
        path = a.state if os.path.exists(a.state) else os.path.join(satpilot.STATES, a.state + ".state.gz")
        emu.restore(gzip.decompress(open(path, "rb").read()))
        meta_path = path[:-9] + ".json" if path.endswith(".state.gz") else ""
        meta = json.load(open(meta_path, encoding="utf-8")) if meta_path and os.path.exists(meta_path) else {}
        mf = re.search(r"state_(\d+)\.gz$", path)
        pilot.f = meta.get("frame", int(mf.group(1)) if mf else 0)
        fresh = satmem.refresh_chunk_table(m, image=a.image)      # the chunk table AND GFS's directory cache
        log(f"{pilot.f}: restored {a.state}" + (" (chunk table refreshed from the current MAIN_L.BIN)" if fresh else ""))
        if not os.environ.get("NO_INJECT"):
            # the bookmark's RAM carries the blob of ITS build (cue table, payload code); every run
            # tests the current one (satplay does the same) - NO_INJECT=1 keeps the state's
            satsubs.inject_blob(m, a.scene, lambda t: log(f"{pilot.f}: {t}"))
        if m.u16(satsubs.SCENE_VAR) == 0:
            # a state from the opening: the bank (and its blob) load from THIS image
            log(f"{pilot.f}: the opening is still running; waiting for the first card")
            while pilot.f < 60000 and not pilot.box()[1]:
                pilot.run(1, hook)
            log(f"{pilot.f}: first card waits {[r for r in rows() if r]}")
            got = pilot.wait_menu(3000, hook, hold_after_card=60)
            log(f"{pilot.f}: menu {got[3] if got else None}")
            if not a.route:
                pilot.save(f"{a.scene}_subs_start")
    elif a.route:
        pass
    else:
        title, newgame = satpilot.presses(pilot.emu)
        pilot.run(title - pilot.f); pilot.press("a")
        pilot.run(newgame - pilot.f); pilot.press("c")
        log(f"{pilot.f}: NEW GAME; the opening runs untouched")
        while pilot.f < 40000 and not pilot.box()[1]:
            pilot.run(1)
        log(f"{pilot.f}: first card waits {[r for r in rows() if r]}")
        got = pilot.wait_menu(3000)
        log(f"{pilot.f}: menu {got[3] if got else None}")
        pilot.save("B010_subs_start")
    log(f"{pilot.f}: blob magic {m.u32(BLOB):#x} scene {m.u16(BLOB + 4)} ncues {m.u16(BLOB + 6)}; "
        f"pool word {m.u32(satsubs.HOOK_POOL):#x}")

    def play(end):
        """Run to frame `end`, pressing the game's own cards through after 60 waiting frames."""
        wait_since, last_press = None, -1000
        while pilot.f < end:
            pilot.run(1, hook)
            if m.u8(satsubs.BOX_WAIT) == 1 and pilot.f - last_press > 100:
                wait_since = wait_since or pilot.f
                if pilot.f - wait_since >= 60:
                    seen_cards.append((pilot.f, [r for r in rows() if r]))
                    log(f"{pilot.f}: the game's card waits {seen_cards[-1][1]} - A")
                    pilot.press("a"); last_press = pilot.f; wait_since = None
            else:
                wait_since = None

    if a.route:
        route = json.load(open(a.route, encoding="utf-8"))
        for i, act in enumerate(route["actions"]):
            if pilot.f >= a.frames:
                log(f"{pilot.f}: frame budget spent before action {i}"); break
            if "path" in act:
                for label in act["path"]:
                    got = pilot.wait_menu(act.get("patience", 3000), hook, hold_after_card=60)
                    ok, labels = pilot.select(label, hook) if got else (False, [])
                    if not ok:
                        log(f"{pilot.f}: {label!r} not in {labels} - action {i} skipped")
                        if label != act["path"][0]:
                            pilot.press("b"); pilot.run(30, hook)      # back out of the submenu
                        break
                else:
                    play(pilot.f + act.get("settle", 120))
            elif "menu" in act:
                pilot.wait_menu(3000, hook, hold_after_card=60); pilot.select(int(act["menu"]), hook)
                play(pilot.f + act.get("settle", 120))
            elif "idle" in act:
                play(pilot.f + int(act["idle"]))
            elif "press" in act:
                pilot.press(act["press"]); pilot.run(10, hook)
            elif "cancel" in act:
                pilot.press("b"); pilot.run(30, hook)
            elif "save" in act:
                pilot.wait_menu(3000, hook, hold_after_card=60); pilot.save(act["save"])
            elif "wait_menu" in act:
                got = pilot.wait_menu(act.get("patience", 3000), hook, hold_after_card=60)
                log(f"{pilot.f}: menu {got[3] if got else 'never came'}")
            else:
                log(f"{pilot.f}: unknown action {act}")
    else:
        ok, labels = pilot.select(0, hook)                      # Enter: the receptionist's card
        log(f"{pilot.f}: Enter -> {ok}")
        got = pilot.wait_menu(3000, hook, hold_after_card=60)
        log(f"{pilot.f}: menu {got[3] if got else None}")
        ok, labels = pilot.select(3, hook)                      # Talk: the voiced exchange
        log(f"{pilot.f}: Talk -> {ok} (the confirm is believed only when the menu changes; the band keeps the byte at 1)")
        play(pilot.f + 1400)
    for item in [x for x in a.then.split(",") if x]:
        if item.startswith("@"):                                # a bare press (e.g. @right on a two-column list)
            pilot.press(item[1:]); pilot.run(10, hook)
            log(f"{pilot.f}: pressed {item[1:]}")
            continue
        item = int(item) if item.lstrip("-").isdigit() else item   # an index, or label prefixes 'A|B'
        got = pilot.wait_menu(3000, hook, hold_after_card=60)
        log(f"{pilot.f}: menu {got[3] if got else None}; picking {item!r}")
        if isinstance(item, str) and "|" in item and got:
            item = next((alt for alt in item.split("|") if any(l.startswith(alt) for l in got[3])), item.split("|")[0])
        ok, labels = pilot.select(item, hook)
        if not ok:
            log(f"{pilot.f}: {item!r} not picked ({labels})")
        play(pilot.f + 1500)
    t1 = m.u32(TICK)
    pilot.run(a.idle, hook)
    t2 = m.u32(TICK)
    log(f"{pilot.f}: idled {a.idle} frames; vblank ticks {t1} -> {t2} ({'alive' if t2 > t1 else 'WEDGED'})")
    emu.image().save(os.path.join(OUT, "run_final.png"))
    log("---- cards shown by the payload ----")
    faceprob = []
    for cid, f0, f1, text, layout, wins, others, *first in shown:
        c = next(c for c in spec["cues"] if c["id"] == cid)
        exp = c["rows"] if layout == "band" else ([c["speaker"]] if c.get("speaker") else []) + (satsubs.wide_rows(c) or c["rows"])   # the plain box (and plain-in-band) draws the rows re-wrapped at 20 under the nameplate
        ok = [r.strip() for r in text] == [r.strip() for r in exp]
        want = c.get("speaker") if c.get("speaker") in facechunks.CHARS else None   # the speaker, when a portrait chunk of theirs exists
        got = sorted(str(w) for w in wins if w)
        others = sorted(str(o) for o in others)
        parked = sorted(str(k) for k in parkedby.get(cid, ()))
        verdict = ""
        if layout == "bandplain":
            verdict = "plain-in-band" + (" +column" + str(sorted(got)) if got else "")   # no portrait by design: nothing may be in the window
            if want and want in parked:
                verdict += f" PORTRAIT-PARKED({want})"               # the speaker's face was there, parked instead of shown
            if got or others or overlap.get(cid) or (want and want in parked):
                faceprob.append(cid)
            if overlap.get(cid):
                verdict += f" TEXT-OVER-FACE({overlap[cid]} frames)"
        elif layout == "band":
            if not got:
                verdict = "noface"
            elif want and all(g != want for g in got):
                verdict = "FACE!"                                    # someone else's portrait in the window
            elif want:
                verdict = "face-ok"
            else:
                verdict = "face?" + ("" if len(got) == 1 else " (changed)")
            if first and first[0] != want and want and str(first[0]) != want:
                verdict += " late"       # the script appends the voice id a frame or more after the card starts
            if cid in upgraded:
                verdict += " (late portrait)"                        # plain-in-band first, the face when its chunk landed
            if others:
                verdict += " +others" + str(sorted(others))          # a second column still on screen
            if overlap.get(cid):
                verdict += f" TEXT-OVER-FACE({overlap[cid]} frames)"  # a column at 120/216 under the text (Luiz, B020's first reel)
            if verdict.startswith("FACE!") or "+others" in verdict or overlap.get(cid) or (verdict.startswith("noface") and want):
                faceprob.append(cid)
        if layout in ("band", "bandplain") and any(v >= 3 for v in spoff.get(cid, {}).values()):
            # a sprite the script cut from a face buffer (op 0x05) left at the game's column: the
            # Teller's trance beside her still face (#48); extras in the payload moves it with its column
            verdict += f" SPRITE-OFF-WINDOW{ {n: v for n, v in spoff[cid].items() if v >= 3} }"
            if cid not in faceprob:
                faceprob.append(cid)
        # a mono line decodes 11,025 B/s; a reel's counter is file bytes at rate x channels x 2
        bps = (c["rate"] * 2 * (c["size"] - 54) // (c["frames"] * 2) if c.get("frames") else 11025) if "reel" in c else 11025
        log(f"{cid} [{layout}]: frames {f0}-{f1} ({(f1 - f0) / 60:.1f} s; the cue is {(c['b1'] - c['b0']) / bps:.1f} s) "
            f"rows={text} expected={exp} {'OK' if ok else 'MISMATCH'}"
            + (f" | speaker={c.get('speaker')} face_want={want} face_in_window={got} {verdict}" if layout in ("band", "bandplain") else ""))
    log(f"face problems: {faceprob or 'none'}")
    # the under-band detector fires for one frame at every verb-menu redraw (the labels land while
    # the band list is still up): only a run of frames is the engine typing under our band
    problems = len(faceprob) + (1 if len(under_band) > 3 else 0) + (1 if t2 <= t1 else 0)   # a wedge counts too
    drawn = {cid for cid, *_ in shown}
    missed = [c["id"] for c in spec["cues"] if c.get("enabled", True) and c["id"] not in drawn
              and (("reel", c["reel"]) if "reel" in c else c["sector"]) in seen_lines]
    log(f"lines heard: {len(seen_lines)}; cues drawn: {len(drawn)}; cues of heard lines never drawn: {missed}")
    log(f"engine text under the band: {len(under_band)} frames" + (f" (first {under_band[:10]})" if under_band else " - none"))
    log(f"game cards pressed: {seen_cards}")
    log(f"done at {pilot.f} in {time.time() - t0:.0f}s")
    log(f"PROBLEMS: {problems}" if problems else "PROBLEMS: 0")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
