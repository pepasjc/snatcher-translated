"""Drive the PCE game's menus headlessly by their labels.

The engine keeps the list menu's state in BaseRAM: the cursor at $347B, the
item count at $3518 while a list is up (0 otherwise; $347A keeps the last
count), $3478 non-zero while a message owns the box - and it redraws the
highlighted item through the message renderer, so the label under the
cursor sits as codes in the buffer at $3490 (`fc 00 f9 01 fe 01 fb`, the
column and row bytes - items 0-3 down column 1, the rest down column 11 -
then the label, then FF) - pair codes for English, Shift-JIS for Japanese.
A route is a list of steps:

  {"choose": "Talk"}          move the cursor until the label reads so, confirm
  {"choose": ["Go inside", "Move"]}   the first of these the menu has
  {"maybe": "Forward"}        choose it if the menu has it, else carry on
  {"wait_screen": {"crop": [112,80,168,120], "white": 0.35, "red": 0.03}}   until the region shows the colours
  {"repeat": [...], "until": "Back", "max": 6}   the steps until the verb menu has the label
                              ("until": "fought": until a shootout was fought)
  {"press": "a", "n": 3}      press a button n times (dialogue advances)
  {"wait": 120}               idle frames
  {"shot": "name"}            capture work/pce/route/<name>.png
  {"save": "name"}            savestate work/pce/route/<name>.mdf
  {"endgame": 1}              the game's own Save, then End the game (Metal Gear's farewell)
  {"bram": "name"}            the game's own Save (Use Metal Gear > Save > slot), then
                              the backup RAM out to work/pce/saves/<name>.sav for the MiSTer
  {"type": "REIGN"}           spell on the Latin keyboard from its A key, then OK
  {"dial": "395644"}          the videophone keypad (after Call > What number?)
  {"dial": "55", "confirm": "start"}   the same pad as an answer, RUN to confirm
  {"items": 1}                log the open menu's labels
  {"sweep": "Investigate", "rounds": 2, "avoid": ["Terminal"]}   every topic twice, never those
  {"when": "revolution", "steps": [...]}   the steps only if the word was said lately
  {"aim": ["auto", "none"]}   shootouts: humanoids take head shots, bugs the centre; the
                              second and later ones are not fought (the last battle)

Between steps the pilot presses I every `--every` frames whenever no menu
is open (the impatient reader), and never while one is.

With PCESAVE=1 (or --bram) the pilot also saves the game at the first verb menu
of every module it reaches and writes the 2 KB backup RAM to
work/pce/saves/mod<rec>.sav - `pce/tools/pce_saves.py push <name>` puts one on
the MiSTer, where the game's Load menu picks it up.

  python pce/harness/pcemenu.py --state work/pce/mn_35700.mdf --route pce/harness/routes/hq_search.json
"""
import argparse, ctypes as C, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):          # pages carry any character; a cp1252 console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")    # ended a playthrough on one
import emurun as E
import pcerun as R
import pcepair
import pcetext as T

BASE = 0x2000
MSG = 0x3610                          # the message buffer (pcesubs.MSG)
MSG_RES = 0x3A66                      # the resident stub's own (pcesubs.MSG_RES; four rows)
LINELOG = bool(os.environ.get("LINELOG"))
SIGS = os.path.join(WORK, "pce", "sigs")            # renders of the unknown face bitmaps the census meets
CURSOR, COUNT = 0x347B, 0x3518        # $3518 holds the count only while a list is open
BUSY = 0x3478                         # non-zero while the message renderer has the box
LABEL = 0x3490
HEAD = bytes.fromhex("fc00f901fe01fb")   # then column, row: items 0-3 in column 1, the rest in column 11


PATCHED = os.path.join(ROOT, "patched", "pce", "snatcher_pce.cue")


class Pilot:
    def __init__(self, cue=PATCHED, core=R.CORE):        # (pcerun.CUE is the pristine image)
        self.cue = cue
        from rendered_text import Monitor
        # the rendered-text review on a built image (patched/pce or a frozen copy of it); the
        # pristine image's text is Japanese
        self.text_monitor = Monitor() if "snatcher_pce" in os.path.basename(cue) and os.path.abspath(cue) != os.path.abspath(R.CUE) else None
        self.emu = E.Emu(core=core)
        self.emu.load(cue)
        c = self.emu.core
        c.retro_get_memory_data.restype = C.c_void_p
        c.retro_get_memory_size.restype = C.c_size_t
        self.emu.run()
        self.frame = 0
        _PILOT[0] = self

    PAIRS_EVERY = 30

    def pairs(self):
        """The loaded module's pair table (None: a module with none), re-read from the module
        window - SysCardRAM banks $7E-$7F, then CD RAM $80-$81 - at most every PAIRS_EVERY
        frames (a scene load takes far longer than that before its first menu)."""
        if self.frame - getattr(self, "_pairs_at", -10 ** 9) >= self.PAIRS_EVERY:
            import pcestate as ST
            sec = ST.sections(self.emu.state(), ("SysCardRAM", "CDRAM"))
            win = sec["SysCardRAM"][0x2C000:0x30000] + sec["CDRAM"][0:0x4000]
            self._pairs = pcepair.PairTable.from_module(win)
            self._pairs_at = self.frame
        return self._pairs

    def ram(self):
        c = self.emu.core
        return C.string_at(c.retro_get_memory_data(2), c.retro_get_memory_size(2))

    def restore(self, path):
        self.emu.restore(open(path, "rb").read())
        self._pairs_at = -10 ** 9           # another module, maybe

    def step(self, n=1, held=()):
        self.emu.held = {E.BTN[b] for b in held}
        for _ in range(n):
            self.emu.run()
            self.frame += 1
            self.watch()
            if self.text_monitor is not None:
                self.text_monitor.sample(self)
            if self.frame % 16 == 0 and not self.fighting and self.shootout():
                self.fight()
                self.emu.held = {E.BTN[b] for b in held}
        self.emu.held = set()

    # --- shootouts ---
    # In a shootout $3F2C reads 1 and object 0x37 is live ($2A77; the corner brackets, objects
    # 1-4, are there outside fights too). SELECT draws the blaster: the crosshair (SAT patterns 194/196/198/202, four 16x16
    # quadrants) sits in the cell of the held direction(s) - columns at x 60/120/180, rows at
    # y 25/64/102 (sprite top-left + 8) - and springs back to the centre when released, so aim
    # = hold, and I fires while holding. Targets are the other field sprites (patterns
    # 0x280-0x2BF: the insectors; later foes may need more). Over when the crosshair is gone.
    fighting = False
    fought = False                  # a shootout was fought (routes loop "until": "fought")
    aim = "centre"                  # route step {"aim": "centre" | "head" | "up" | "sides" | "auto" | "none"},
                                    # or a list: one per shootout, the last covering the rest
    CROSS = {194, 196, 198, 202}

    def shootout(self):
        r = self.ram()
        return r[0x1F2C] == 1 and r[0xA77] == 1

    def sat(self):
        import struct, pcestate as ST
        v = ST.sections(self.emu.state(), ("VRAM",))["VRAM"]
        return [struct.unpack_from("<HHHH", v, 0x2000 + i * 8) for i in range(64)]

    def fight(self, limit=8000):
        self.fighting = True
        aim = self.aim[0] if isinstance(self.aim, list) else self.aim
        print(f"{self.frame}: shootout, aim {aim}", flush=True)
        shots, t0, tries = 0, self.frame, 0
        if aim == "none":
            # the blaster stays holstered (Act 3's last battle: "don't fire at all"); I only
            # reads the texts, and does nothing else without the blaster
            while self.frame - t0 < limit and self.shootout():
                self.step(56); self.step(4, ["a"])
            self.done_fight(aim, shots)
            return
        self.step(4, ["select"]); self.step(20)
        while self.frame - t0 < limit:
            s = self.sat()
            if not any((p & 0x7FF) in self.CROSS and y for y, x, p, a in s):
                if shots or tries >= 12 or not self.shootout():
                    break
                # no crosshair yet: a text is up ('Gillian, look out!!' at Ivan's door) - read
                # it and draw again
                tries += 1
                self.step(3, ["a"]); self.step(6); self.step(4, ["select"]); self.step(12)
                continue
            # the foe = the sprite-group pieces on the field (patterns 0x200 up: insectors
            # 0x280-0x2BF, Ivan 0x2C8-0x2E8 with 0x298-0x2AA firing...), clustered by nearness;
            # aim at the biggest cluster's centre (Ivan is 2 x 3 pieces: the centre cell wins,
            # a piece's own cell missed him 21 times)
            pieces = [(y - 64 + 8, x - 32 + 8) for y, x, p, a in s if y and (p & 0x7FF) >= 0x200 and 0 <= y - 64 < 160 and 0 <= x - 32 < 256]
            if not pieces:
                if self.frame - t0 in range(120, 128) or self.frame - t0 in range(600, 608):
                    # nothing on the field: the SAT, for labelling a new foe
                    print(f"{self.frame}: shootout sat " + " ".join(f"{p & 0x7FF:03x}@{x - 32},{y - 64}" for y, x, p, a in s if y), flush=True)
                self.step(4); continue
            clusters = []
            for py, px in pieces:
                for c in clusters:
                    if any(abs(py - qy) <= 40 and abs(px - qx) <= 40 for qy, qx in c):
                        c.append((py, px)); break
                else:
                    clusters.append([(py, px)])
            # the biggest cluster; among singles the lowest on the field (the insector nearest
            # Gillian bites first - the duct's swarm lost 272 shots to the top-left one)
            best = max(clusters, key=lambda c: (len(c), max(py for py, px in c)))
            fy = sum(py for py, px in best) / len(best)
            fx = sum(px for py, px in best) / len(best)
            if aim == "auto":                   # a humanoid (2 x 3 pieces) takes the head, a bug the centre
                aim = "head" if len(best) >= 4 else "centre"
            if aim in ("head", "sides"):        # snatchers take head shots only: the top piece
                fy = min(py for py, px in best)
                fx = [px for py, px in best if py == fy][0]
            if aim == "sides" and not (fx > 150 or fx < 90):
                self.step(2); continue          # Mika is the shield (the Act 2 finale): the head
                                                # is shot at the left or right only, never centre
            held = []
            if fx > 150: held.append("right")
            elif fx < 90: held.append("left")
            if aim == "up":                     # the last snatcher: straight up (top-middle)
                held = ["up"]
            elif fy > 85: held.append("down")
            elif fy < 45: held.append("up")
            self.step(4, held); self.step(2, held + ["a"]); self.step(2, held); shots += 1
            aim = self.aim[0] if isinstance(self.aim, list) else self.aim
        self.done_fight(aim, shots)

    def done_fight(self, aim, shots):
        print(f"{self.frame}: shootout over, {shots} shots", flush=True)
        if isinstance(self.aim, list) and len(self.aim) > 1:
            self.aim.pop(0)                     # the next shootout takes the next aim
        self.fighting = False
        self.fought = True

    # --- the voice lines (LINELOG=1): AD_STAT rising, the record's NN, and 30 frames on
    # whether the subtitle stub wrote the message buffer ---
    playing = False
    due = None
    lines = []

    def module(self):
        """The loaded scene module's rec, by its first 64 bytes against the pristine modules'
        (the bytecode head; a build's remapped refs change a few bytes, so the best match
        over 48 wins; the module window's first bank is SysCardRAM bank 0x7E, offset 0x2C000)."""
        import pcestate as ST
        if not hasattr(self, "_mods"):
            import json, patch_pce as P, pcescript as PS
            img = P.Image(P.SRC, 12000)
            self._mods = [(e["rec"], PS.read_file(img, e["rec"], e["n"])[:64])
                          for e in json.load(open(os.path.join(WORK, "pce", "filetable.json")))["1"]]
        cd = ST.sections(self.emu.state(), ("SysCardRAM",))["SysCardRAM"]
        head = cd[0x2C000:0x2C040]
        same, rec = max((sum(1 for a, b in zip(head, h) if a == b), r) for r, h in self._mods)
        return rec if same >= 48 else "?"

    cdda = 0                        # the CD-DA track playing ($263B, BCD) as last seen
    cdreq = 0                       # the last track requested ($26F9)
    page = None                     # the last page logged (its text) and its frame
    page_frame = 0
    pages = []                      # every page's text, in order
    page_mark = 0                   # len(pages) at the last type step (a `when` reads from there)

    def watch(self):
        r = self.ram()
        if not LINELOG:
            # the pages alone (a route's `type` may read the question)
            msg = msgbuf(r)
            if msg[0] == 0xFC and msg[4] == 0xFB:
                end = msg.find(bytes([0xFF]))
                text = decode_label(msg[9:end if end > 0 else 96]).strip()
                if text and text != self.page:
                    self.page, self.page_frame = text, self.frame
                    self.pages.append(text)
            return
        # the module loaded, looked up every 60 frames and logged when it changes (the coverage
        # of the modules: voice_coverage.py - a save handler is in for a few hundred frames)
        if self.frame % 60 == 0:
            try:
                m = self.module()
            except Exception:
                m = "?"
            if m != "?" and m != getattr(self, "_modlog", None):
                self._modlog = m
                print(f"{self.frame}: module {m}", flush=True)
        # a CD-DA track starting ($2638 = playing, $263B = the track in BCD): the module it plays under
        track = r[0x63B] if r[0x638] else 0
        if track != self.cdda:
            self.cdda = track
            self.cur_mod = None
            if track:
                print(f"{self.frame}: cdda track {track:02x} under module {self.module()}", flush=True)
            else:
                print(f"{self.frame}: cdda stopped", flush=True)
        if r[0x6F9] != self.cdreq:
            self.cdreq = r[0x6F9]
            print(f"{self.frame}: cdda request {self.cdreq} under module {self.module()}", flush=True)
        # every new page in the renderer's buffer (the stub's - a voice line's or a CD-DA
        # cue's - and the game's own messages alike), for the census and the shots
        msg = msgbuf(r)
        if msg[0] == 0xFC and msg[4] == 0xFB:
            end = msg.find(bytes([0xFF]))
            text = decode_label(msg[9:end if end > 0 else 96]).strip()
            if text and text != self.page:
                self.page, self.page_frame = text, self.frame
                self.pages.append(text)
                print(f"{self.frame}: page {text[:60]!r}", flush=True)
        now = r[0x6F2] != 0
        if now and not self.playing:
            hi, lo = r[0x5F], r[0x5E]
            nn = ((hi & 7) << 5 | lo >> 3) + 1 & 0xFF if 0x80 <= hi < 0x88 else 0
            self.due = (self.frame + 30, nn)
            self.due_sec = None
            if 0x80 <= hi < 0x88:           # the record's start sector (the same NN in two acts' tables)
                try:
                    import pcestate as ST
                    cd = ST.sections(self.emu.state(), ("CDRAM",))["CDRAM"]
                    at = 0x4000 + ((hi << 8 | lo) - 0x8000)
                    self.due_sec = cd[at + 3] | cd[at + 4] << 8
                except Exception:
                    pass
            if nn:
                self.cur_nn, self.cur_mod = nn, None
        self.playing = now
        if track:
            self.cur_nn = None
        self.subpage(r, track)
        if self.due and self.frame >= self.due[0]:
            f, nn = self.due
            msg = msgbuf(r)
            end = msg.find(bytes([0xFF]))
            # `fc 00 f9 01 fb col row fe colour` then the pairs (the game's own messages look the same)
            text = decode_label(msg[9:end if end > 0 else 96]).strip() if msg[0] == 0xFC and msg[4] == 0xFB else ""
            faces = self.faces()
            self.lines.append((f - 30, nn, text, faces))
            try:
                mod = self.module()
            except Exception:
                mod = "?"
            self.last_mod = mod
            print(f"{f - 30}: line {nn:02x} {'sub ' + repr(text[:24]) if text else 'no subtitle'} mod {mod} | {self.rows()} | {faces} | sec {getattr(self, 'due_sec', None)}", flush=True)
            self.due = None

    cur_nn = None                   # the voice line last started (None under a CD-DA track)
    cur_mod = None                  # the module the current line plays under (looked up once)
    last_mod = None                 # the module of the last line logged
    _sub_raw = None                 # the stub page last logged / the candidate and since when
    _sub_cand = (None, 0)

    def subpage(self, r, track):
        """Log each new page of the subtitle stub's buffer (the resident stub's at MSG_RES; the
        ending's module stub draws its epilogue cues - CD-DA, after rec 110 is gone - through the
        game's MSG; its voiced lines are the resident's since #112) once it has held for 4 frames - the
        stub lays a page out over more than one frame - as `subpage mod R line NN|cd TT rows
        [...] issues [...]` for subtext.py to judge against the English."""
        import subtext
        m = r[MSG_RES - BASE:MSG_RES - BASE + 136]
        module_stub = False
        if not (m[0] == 0xFC and m[1] == 0 and 0xF8 in (m[2], m[4])):   # `fc 00 [f9 01] f8 lo hi`
            if self.last_mod != 670 or not track:
                return
            m = r[MSG - BASE:MSG - BASE + 96]
            module_stub = True
            if not (m[0] == 0xFC and (self.cur_nn or track)):
                return
        end = m.find(0xFF, 3)
        raw = bytes(m[:end + 1 if end > 0 else len(m)])
        if raw == self._sub_raw:
            self.screen_sample()
            return
        if raw != self._sub_cand[0]:
            self._sub_cand = (raw, self.frame)
            return
        if self.frame - self._sub_cand[1] < 4:
            return
        self._sub_raw = raw
        if self.cur_mod is None:
            try:
                self.cur_mod = self.module()
            except Exception:
                self.cur_mod = "?"
        rows, issues = subtext.rows(raw, self.pairs())
        self.screen_judge()                 # the page before, as it was last seen on screen
        if not any(x.strip() for x in rows) and not issues:
            return
        what = f"cd {track:02x}" if track else (f"line {self.cur_nn:02x}" if self.cur_nn else "-")
        print(f"{self.frame}: subpage mod {self.cur_mod} {what} rows {rows!r}"
              + (f" issues {issues!r}" if issues else ""), flush=True)
        if not issues and isinstance(self.cur_mod, int) and not module_stub:
            # (the epilogue's module-stub pages are not judged: its scene block overwrites the
            # module's head, "?"; the ending's voiced lines are the resident's and are read, #112)
            self._scr = {"rows": rows, "frame": self.frame, "what": what, "mod": self.cur_mod}

    _scr = None
    SCREEN_EVERY = 8

    def screen_sample(self):
        """While a page is up, read the band off the screen whenever it changes: the verdict of
        the LAST capture that shows the page's first row is the page's (a capture with the next
        page already drawn, or the window gone, does not count; a page garbled after it typed
        on does)."""
        s = self._scr
        if s is None or self.frame % self.SCREEN_EVERY:
            return
        if self.frame - s["frame"] > 900:
            self.screen_judge()
            return
        import numpy as np, screentext
        r = self.ram()
        if r[BUSY - BASE] or r[0x1472] != (MSG_RES >> 8):
            return                          # the renderer last drew a message of the game's own
                                            # ($3471/2, its read pointer, outside our buffer)
        img = self.emu.image()
        band = np.asarray(img.convert("RGB"))[136:236]
        key = hash(band.tobytes())
        if key == s.get("key"):
            if s.get("pend"):               # the garble held still: it stands
                s["last"], s["pend"] = s["pend"], None
            return
        s["key"] = key
        verdict, seen = screentext.judge(img, s["rows"])
        if verdict == "GARBLED ON SCREEN" and not s.get("pend"):
            s["pend"] = (verdict, seen, img)    # held for the next look: one frame of the next
            return                              # page's clear going over the rows is no garble
        s["pend"] = None
        if verdict in ("ok", "GARBLED ON SCREEN"):
            s["last"] = (verdict, seen, img)
        elif s.get("blind") is None:
            s["blind"] = img

    def screen_judge(self):
        """The page last laid out, as screen_sample last read it: logged when it is not ok as
        `screen <verdict> mod R line NN rows [...] seen [...] capture <png>`."""
        s, self._scr = self._scr, None
        if s is None:
            return
        if s.get("last"):
            verdict, seen, img = s["last"]
        elif s.get("blind") is not None:
            verdict, seen, img = "NOT ON SCREEN", [], s["blind"]
        else:
            return
        if verdict == "ok":
            return
        path = os.path.join(WORK, "pce", "screen_audit", f"{str(s['mod']).replace('?', 'x')}_{s['frame']}.png")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path)
        print(f"{self.frame}: screen {verdict} mod {s['mod']} {s['what']} rows {s['rows']!r} seen {seen!r} "
              f"capture {path}", flush=True)

    def rows(self):
        """The stub's rows for the line up: 'rows=N treg=R' (the resident stub's variables in rec 110's bank)."""
        try:
            import pcesubs as X, pcestate as ST
            if not hasattr(self, "_sl"):
                self._sl = X.stub()[1]
            sc = ST.sections(self.emu.state(), ("SysCardRAM",))["SysCardRAM"]
            bank = (0x7B - 0x68) * 0x2000
            v = lambda n: sc[self._sl[n] - 0xA000 + bank]
            return f"rows={v('nrows')} treg={v('treg')} free={v('free0'):02x} gw={v('gw'):02x}"
        except Exception as e:
            return f"rows=? ({e})"

    def faces(self):
        """The census: the band's sprite objects by face region (pattern group 0x200-0x3FF,
        y on the band) and every region's four signature words, `*` when faces.json knows it."""
        import struct, pcestate as ST, pcesubs as X
        v = ST.sections(self.emu.state(), ("VRAM",))["VRAM"]
        sat = [struct.unpack_from("<HHHH", v, 0x2000 + i * 8) for i in range(64)]
        objs = {}
        for y, x, pat, attr in sat:
            p = pat & 0x7FF
            if 0x40 + 0xA0 <= y < 0x400 and p >= 0x200:
                objs.setdefault((p - 0x200) >> 6, set()).add(x - 32)
        db = X.faces_db()
        owners = {tuple(w): k for k, ws in db.items() for w in ws}
        out = []
        for reg in range(8):
            words = struct.unpack_from("<%dH" % 0x800, v, (0x4000 + reg * 0x800) * 2)
            sig = tuple(words[o] for o in X.SIG_OFFS)
            if not any(sig):
                continue
            name = owners.get(sig)
            at = ",".join(str(x) for x in sorted(objs.get(reg, ()))) or "-"
            out.append(f"r{reg}@{at}:" + (name if name else " ".join(f"{w:04x}" for w in sig)))
            if not name:
                # the bitmap, laid out as a portrait, for labelling (work/pce/sigs/<words>.png)
                import pcefaces
                from PIL import Image
                os.makedirs(SIGS, exist_ok=True)
                path = os.path.join(SIGS, "_".join(f"{w:04x}" for w in sig) + ".png")
                if not os.path.exists(path):
                    Image.fromarray(pcefaces.face_image(words) * 17, "L").resize((128, 128), Image.NEAREST).save(path)
        return " ".join(out)

    def press(self, button, hold=3, release=12):
        self.step(hold, [button])
        self.step(release)

    # --- the menu ---
    def menu(self):
        """(cursor, count, label) of an open list menu, else None."""
        r = self.ram()
        count, cursor = r[COUNT - BASE], r[CURSOR - BASE]
        if not (1 <= count <= 24 and cursor < count) or r[BUSY - BASE]:
            return None
        if r[LABEL - BASE:LABEL - BASE + len(HEAD)] != HEAD:
            return None
        col, row = r[LABEL - BASE + len(HEAD)], r[LABEL - BASE + len(HEAD) + 1]
        # Resident 9232 maps the real list highlight $34B0 to the renderer's
        # two-column position. $347B is only a renderer row, not that index.
        # Scope this check to the proved normal <=8-option layout; terminal
        # and other layouts retain their existing decoder.
        native_count,native_index=r[0x14B2],r[0x14B0]
        if 1<=count<=8 and 1<=native_count<=8 and col in (1,11) and row<4:
            expected=(1+10*((native_index&4)>>2),native_index&3)
            if count!=native_count or native_index>=native_count or (col,row)!=expected:
                if getattr(self,'validation_only',False):
                    key=(count,native_count,native_index,col,row)
                    seen=getattr(self,'_menu_disagreements',set())
                    if key not in seen and len(seen)<16:
                        seen.add(key);self._menu_disagreements=seen
                        stem=f'native-highlight-disagreement-{self.frame}-{len(seen)}'
                        record=dict(frame=self.frame,label_position=[col,row],expected_position=list(expected),
                                    label_count=count,native_count=native_count,native_index=native_index,
                                    highlight_address='34B0',count_address='34B2',screenshot=stem+'.png',state=stem+'.mdf')
                        with open(os.path.join(self.out,'native-highlight-disagreements.jsonl'),'a') as f:f.write(json.dumps(record)+'\n')
                        self.emu.image().save(os.path.join(self.out,stem+'.png'))
                        open(os.path.join(self.out,stem+'.mdf'),'wb').write(self.emu.state())
                return None
        start = LABEL - BASE + len(HEAD) + 2
        end = r.find(b"\xff", start)
        raw = r[start:end]
        return (col, row), count, decode_label(raw)

    def settled(self, tries=8):
        """The menu once its label has been redrawn (None if none opens)."""
        for _ in range(tries):
            m = self.menu()
            if m is not None:
                return m
            self.step(6)
        return None

    def choose(self, label, tries=30):
        """Move down until the highlighted item reads `label`, then confirm.
        An exact label wins; failing one full round, a label the item
        starts with does (the two 外に/外へ出る)."""
        want = norm(label)
        seen = 0
        for _ in range(tries):
            m = self.settled()
            if m is None:
                self.step(10)
                continue
            self.step(12)
            if self.menu() != m:              # a list on its way out (the montage's hint texts)
                continue
            cursor, count, text = m
            have = norm(text)
            if have == want or (seen > count and have.startswith(want) and not have.endswith(" tricycle")):
                if hasattr(self,'confirm_probe'):
                    self.confirm_probe(label)
                # (a prefix never takes the tricycle's Enter/Exit for a room's Enter / Exit: the
                # ruins' building is "Go inside", the ride "Board Tricycle")
                # a press the engine missed (a busy vblank) leaves the same menu up: press again -
                # after a wait long enough for a slow list to open (a second press into a list
                # that opened late took its first item: the montage's Eyes 1)
                for _ in range(3):
                    self.press("a", hold=6, release=30)
                    gone = False
                    for _ in range(10):
                        self.step(4)
                        now = self.menu()
                        if now != m:
                            gone = True
                            if now is not None:
                                return True          # the next list is up
                    if gone:
                        return True                  # (a text, or a list still opening: the caller waits)
                return True
            seen += 1
            self.press("down")
        raise SystemExit(f"frame {self.frame}: no item {label!r} (last menu: {self.menu()})")

    def items(self, limit=24):
        """Every label of the open menu, by walking the cursor round."""
        out, seen = [], {}
        m = self.settled()
        if m is None:
            return []
        count = m[1]
        for _ in range(limit):
            if m is None:
                break
            cursor, _, text = m
            if cursor not in seen:
                seen[cursor] = text
                out.append((cursor, text))
            if len(seen) >= count:
                break
            # a press the engine missed leaves the key as it was: press again
            for _ in range(3):
                self.press("down")
                self.step(18)                 # the label is redrawn a few frames after the move
                m = self.settled(tries=12)
                if m is None or m[0] != cursor:
                    break
        return [t for _, t in sorted(out)]


JAPANESE = False          # --japanese: the pristine game, labels are plain Shift-JIS


def msgbuf(r):
    """The message up: the resident stub's own buffer when a page is in it, else the game's."""
    m = r[MSG_RES - BASE:MSG_RES - BASE + 136]
    if m[0] == 0xFC and m[4] == 0xF8:        # its tile-base opcode (f8 lo hi) skipped
        m = m[:4] + m[7:]
    if m[0] == 0xFC and m[4] == 0xFB:
        return m
    return r[MSG - BASE:MSG - BASE + 96]


def norm(label):
    """A label for matching: one space between words (a pair's trailing space doubles
    them - 'Room  301', 'Face  3'), lower case."""
    return " ".join(label.split()).lower()


AGAIN = {"Ask again", "もう一度聞く"}


_PILOT = [None]           # the Pilot whose loaded module's pair table decodes labels


def decode_label(raw):
    """Pair codes through the loaded module's pair table (pcepair; read from the module
    window, refreshed every PAIRS_EVERY frames); a module from a build before the tables
    (no PAIRS_PTR) by the old 54-letter arithmetic."""
    table = _PILOT[0].pairs() if _PILOT[0] is not None and not JAPANESE else None
    out, i = [], 0
    while i + 1 < len(raw):
        hi, lo = raw[i], raw[i + 1]
        if not JAPANESE and pcepair.is_pair(hi, lo):
            if table is not None:
                p = table.pair(pcepair.slot_of_code(hi, lo))
                out.append("".join(p) if p else "?")
            else:
                p = pcepair.legacy_pair_of(hi, lo) or ("?", " ")
                out.append(p[0] + ("" if p[1] == " " and pcepair.slot_of_code(hi, lo) >= 54 * 54 else p[1]))
        else:
            out.append(T.sjis_char(hi, lo))
        i += 2
    if JAPANESE:                          # the pristine game: its label as the routes name it
        text = "".join(out)
        return _jp_words().get(text.strip("　 "), text)
    return "".join(out)


_JP = {}


def _jp_words():
    """words.json read backwards for --japanese: a Japanese label -> the English the routes use
    (module-qualified keys "254:ミカ" by their label alone)."""
    if not _JP:
        d = json.load(open(os.path.join(ROOT, "pce", "translation", "words.json"), encoding="utf-8"))
        for k, v in d.items():
            if k.startswith("_") or not isinstance(v, str):
                continue
            _JP.setdefault(k.split(":", 1)[-1].strip("　 "), v)
    return _JP


def native_keyboard_ready(pilot):
    """Resident $BD56 geometry plus the actually rendered Latin key panel.

    Geometry persists after closing the keyboard. These PCE panel colors were
    measured on native BENSON and phone keyboards, including their empty state.
    """
    state=pilot.ram()
    if not (state[0x16B1]==24 and state[0x16B7]==24 and state[0x16B8]==184
        and {state[0x103E],state[0x103F]}=={0,3} and state[BUSY-BASE]==0):
        return False
    img=pilot.emu.image().convert('RGB')
    return all(max(abs(a-b) for a,b in zip(img.getpixel(pos),rgb))<=8
        for pos,rgb in [((8,192),(32,36,104)),((240,192),(32,36,104)),
                        ((16,192),(72,72,144)),((120,192),(72,72,144))])


def wait_menu(pilot, every=90, limit=6000):
    """Read through whatever text is up until a menu opens and stays 24 frames (a verb
    menu still up while its submenu is on its way does not count)."""
    started = pilot.frame
    while pilot.frame - started < limit:
        if native_keyboard_ready(pilot):
            return None  # Native keyboard is ready; never scan it as a verb list.
        m = pilot.settled()
        if native_keyboard_ready(pilot):
            return None
        if m is not None:
            pilot.step(24)                    # let the list finish drawing
            m = pilot.settled()
            if native_keyboard_ready(pilot):
                return None
            if m is not None and len(pilot.items()) >= m[1]:
                import text_integrity
                text_integrity.check(pilot)
                return m                      # (the montage's hints flash the category list
            if m is not None:
                continue
        pilot.press("a")
        pilot.step(every)
    m = pilot.settled()
    return m if m is not None and len(pilot.items()) >= m[1] else None


# --- the game's own Save, and the backup RAM out (PCESAVE=1 / {"bram": name}) ---

BRAM = os.path.join(WORK, "pce", "saves")           # the .sav library the MiSTer tool pushes from
AUTOSAVE = os.environ.get("PCESAVE", "") not in ("", "0")
SLOT = int(os.environ.get("PCESAVE_SLOT", "1"))     # the game's save slot 1-4
TRIES = int(os.environ.get("PCESAVE_TRIES", "4"))   # goes at a module before giving up
# a verb menu, as against a topic list or the save lists: one of these labels is in it
VERBS = {"look", "investigate", "check", "move", "go out", "item", "call", "talk", "use metal gear",
         "ask", "enter", "go inside", "press", "press switch", "press button", "survey", "look around",
         "exit tricycle", "board tricycle", "get out", "hear", "listen", "forward"}


def is_verb_menu(items):
    return any(norm(t) in VERBS for t in items)


def card(pilot):
    """The core's 2 KB backup RAM as bytes (SAVE_RAM; a savestate carries it too)."""
    c = pilot.emu.core
    return C.string_at(c.retro_get_memory_data(0), c.retro_get_memory_size(0))


def game_save(pilot, slot=None, every=90, log=print, end=False):
    """Save through the game's own flow, from an open verb menu, and come back to it.

    Use Metal Gear > Save (some rooms put Save straight in the verb menu) > the
    four-slot list ('Save  1', or 'Replace save  1' once the slot is taken) >
    the Save / Don't save confirm > 'Save complete.' > Continue / End the game.
    Each list takes 300-700 frames to open, so the flow is ~2,000 frames."""
    slot = SLOT if slot is None else slot
    want = {"save %d" % slot, "replace save %d" % slot}
    before = card(pilot)                           # the verdict is the RAM, not the menus
    m = wait_menu(pilot, every, limit=1800)
    if m is None:
        log(f"{pilot.frame}: bram: no menu to save from")
        return False
    items = [norm(t) for t in pilot.items()]
    if "save" in items:
        pilot.choose("Save")
    elif "use metal gear" in items:
        pilot.choose("Use Metal Gear")
        pilot.step(24)
        if "save" not in [norm(t) for t in pilot.items()]:
            log(f"{pilot.frame}: bram: no Save under Use Metal Gear here")
            pilot.press("b"); pilot.step(30)
            return False
        pilot.choose("Save")
    else:
        log(f"{pilot.frame}: bram: no Save in {items}")
        return False
    for _ in range(24):
        m = wait_menu(pilot, every, limit=900)
        if m is None:                              # a text between the lists ('Save complete.')
            pilot.press("a"); pilot.step(every)
            continue
        labels = pilot.items()
        items = [norm(t) for t in labels]
        pick = next((l for l, n in zip(labels, items) if n in want), None)
        if pick is not None:                       # the four-slot list
            log(f"{pilot.frame}: bram: slot {pick.strip()!r}")
            pilot.choose(pick)
            continue
        if "don't save" in items:                  # the confirm (a press the slot list ate
            pilot.choose("Save")                   # already takes it: the cursor sits on Save)
            continue
        if "continue" in items:                    # after 'Save complete.'
            if end and "end the game" in items:    # (the endgame step: Metal Gear's farewell)
                pilot.choose("End the game")
                log(f"{pilot.frame}: bram: saved, End the game")
                return card(pilot) != before
            pilot.choose("Continue")
            continue
        if is_verb_menu(labels):                   # back where we started
            break
        log(f"{pilot.frame}: bram: unexpected list {labels}, backing out")
        pilot.press("b"); pilot.step(30)
    ok = card(pilot) != before
    log(f"{pilot.frame}: bram: save {'written' if ok else 'NOT written'} (menu {pilot.items()})")
    return ok


def dump_bram(pilot, name, route=None, slot=None, saved=None, log=print):
    """Write the core's 2 KB backup RAM to work/pce/saves/<name>.sav and index it.

    The PCE BRAM is 'HUBM', a free pointer at +6 ($8010 = empty) and the save
    entries; the MiSTer's TGFX16 core keeps the same 2,048 bytes in
    /media/fat/saves/TGFX16/<game>.sav, so the file travels as it is."""
    import datetime
    slot = SLOT if slot is None else slot
    os.makedirs(BRAM, exist_ok=True)
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in name)
    path = os.path.join(BRAM, safe + ".sav")
    pilot.emu.save_card(path)
    raw = open(path, "rb").read()
    used = (raw[6] | raw[7] << 8) - 0x8000 if raw[:4] == b"HUBM" else 0
    entry = {"file": safe + ".sav", "module": pilot.module(), "frame": pilot.frame,
             "route": route, "slot": slot, "bytes": len(raw), "used": used,
             "header": raw[:4].decode("latin1"), "saved": saved,
             "page": (pilot.page or "")[:60],
             "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    if route:
        a = re.match(r"act(\d)", os.path.basename(str(route)))
        if a:
            entry["act"] = int(a.group(1))
    ix = os.path.join(BRAM, "index.json")
    data = {}
    if os.path.exists(ix):
        try:
            data = json.load(open(ix, encoding="utf-8"))
        except ValueError:
            data = {}
    data[safe] = entry
    with open(ix, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    log(f"{pilot.frame}: bram {path} ({used} B used, module {entry['module']}, saved={saved})")
    if used <= 0x10:
        log(f"{pilot.frame}: bram WARNING: the backup RAM is empty - no save was written")
    return path


def autosave(pilot, every=90, route=None, log=print):
    """At the first verb menu of a module not saved yet: save the game, dump the RAM."""
    rec = pilot.module()
    tries = pilot.__dict__.setdefault("_bram_tries", {})
    if rec == "?" or tries.get(rec, 0) >= TRIES:
        return
    if pilot.settled(tries=2) is None:
        return                                    # no list up: try again at the next step
    if not is_verb_menu(pilot.items()):
        return
    # Save is not in every room's menu (the HQ tour has none before Metal Gear),
    # and a room's menu grows as the scene goes on, so a module gets TRIES goes
    tries[rec] = tries.get(rec, 0) + 1
    log(f"{pilot.frame}: bram: module {rec}, save attempt {tries[rec]}")
    if not game_save(pilot, every=every, log=log):
        if tries[rec] >= TRIES:
            log(f"{pilot.frame}: bram: module {rec} never offered Save, given up")
        return
    tries[rec] = TRIES
    dump_bram(pilot, "mod%s" % rec, route=route, saved=True, log=log)


def run(pilot, route, every=90, outdir=None, log=print, bram=None, route_name=None):
    """`bram`: save the backup RAM once per module (None = the PCESAVE default; the
    recursive calls pass False, so a sweep never saves in the middle of a list)."""
    outdir = outdir or os.path.join(WORK, "pce", "route")
    os.makedirs(outdir, exist_ok=True)
    if bram is None:
        bram = AUTOSAVE
    for st in route:
        if bram:
            autosave(pilot, every=every, route=route_name, log=log)
        if "endgame" in st:
            # {"endgame": 1}: the game's own Save into a slot, then End the game - the line
            # the save handlers play on the way out (86, "Promise you'll come back")
            game_save(pilot, slot=st.get("slot"), every=every, log=log, end=True)
            pilot.step(st.get("wait", 1500))
            continue
        if "bram" in st:
            ok = game_save(pilot, slot=st.get("slot"), every=every, log=log)
            dump_bram(pilot, st["bram"], route=route_name, slot=st.get("slot"),
                      saved=ok, log=log)
            continue
        if "phone" in st:
            # Use Metal Gear > Videophone > Call > the number: Metal may say something first (a
            # text to read) or the Call list may already be up, or the pad itself (the answer
            # to "What number?" is a 10-item list with the cursor on 0) - whichever comes
            m = wait_menu(pilot, every)
            if m is not None and "use metal gear" in [norm(t) for t in pilot.items()]:
                pilot.choose("Use Metal Gear")
                pilot.choose("Videophone")
            for _ in range(20):
                pilot.step(30)
                r = pilot.ram()
                if r[0x16B0] == 45 and r[0x16B2] == 0:
                    break                                        # the pad is up (dial presses on)
                m = pilot.settled()
                if m is not None and "call" in [norm(t) for t in pilot.items()]:
                    pilot.choose("Call"); break
                if m is None:
                    pilot.press("a")
            st = {"dial": st["phone"], **({"confirm": st["confirm"]} if "confirm" in st else {})}
        if "choose" in st:
            m = wait_menu(pilot, every)
            if m is None:
                raise SystemExit(f"frame {pilot.frame}: no menu opened for {st['choose']!r}")
            want = st["choose"]
            if isinstance(want, list):                   # alternatives: the first one the menu has
                have = [norm(t) for t in pilot.items()]
                want = next((w for w in want if norm(w) in have), want[0])
            log(f"{pilot.frame}: menu {m[1]} items, choose {want!r}")
            pilot.choose(want)
        elif "repeat" in st:
            # the steps again and again: until a label is in the verb menu ("until"), or until
            # a shootout has been fought ("until": "fought"), at most "max" times
            for k in range(st.get("max", 8)):
                if st.get("until") == "fought":
                    if pilot.fought:
                        break
                else:
                    wait_menu(pilot, every, limit=600)
                    if norm(st.get("until", "")) in [norm(t) for t in pilot.items()]:
                        break
                log(f"{pilot.frame}: repeat {k + 1}")
                run(pilot, st["repeat"], every=every, outdir=outdir, log=log, bram=False)
        elif "wait_screen" in st:
            # wait until a screen region shows enough of some colours: {"crop": [x0,y0,x1,y1],
            # "white": 0.35, "red": 0.03, "max": 4000} - Altamira's ad display cycles ~3,600
            # frames and the Joy Division number must be LOOKED at while it is up
            import numpy as np
            spec = st["wait_screen"]
            waited = 0
            while waited < spec.get("max", 4000):
                im = np.array(pilot.emu.image().convert("RGB").crop(tuple(spec["crop"]))).astype(int)
                r_, g_, b_ = im[:, :, 0], im[:, :, 1], im[:, :, 2]
                frac = {"white": ((r_ > 200) & (g_ > 200) & (b_ > 200)).mean(),
                        "red": ((r_ > 150) & (g_ < 100) & (b_ < 100)).mean(),
                        "blue": ((b_ > 150) & (r_ < 120)).mean()}
                if all(frac[k] >= v for k, v in spec.items() if k in frac):
                    log(f"{pilot.frame}: screen matched {spec} after {waited}")
                    break
                pilot.step(10); waited += 10
            else:
                log(f"{pilot.frame}: screen never matched {spec}")
        elif "chief_room" in st:
            def offered():
                wait_menu(pilot,every,limit=6000)
                return [norm(x) for x in pilot.items()]
            for attempt in range(4):
                have=offered()
                if 'investigate' in have:
                    pilot.choose('Look');pilot.step(120)
                    if any('desk' in norm(x) for x in pilot.items()):   # ("On the desk" since the label review)
                        break
                    pilot.press('b');pilot.step(120)
                if 'move' in offered():
                    pilot.choose('Move');pilot.step(120)
                have=offered()
                if 'hallway' in have:
                    pilot.choose('Hallway')
                    run(pilot,[{'read':3000}],every,outdir,log,bram=False)
                    offered()
                    pilot.choose('Move');pilot.step(120)
                have=offered()
                if "chief's room" not in have:
                    raise RuntimeError(f'No actual Chief room destination: {have}')
                pilot.choose("Chief's room")
                run(pilot,[{'read':3000}],every,outdir,log,bram=False)
                offered()
                pilot.emu.image().save(os.path.join(outdir,f'chief-arrival-attempt-{attempt}-{pilot.frame}.png'))
            else:raise RuntimeError('Native Chief room did not expose Look/Desk in four arrivals')
        elif "hospital_list_keyboard" in st:
            if not native_keyboard_ready(pilot):
                have=[norm(x) for x in pilot.items()]
                if 'check the list' not in have:
                    pilot.choose('Investigate')
                    pilot.step(120)
                    pilot.choose('Hospital list')
                    run(pilot,[{'read':6000}],every,outdir,log,bram=False)
                if not native_keyboard_ready(pilot):
                    pilot.choose('Check the list')
                    run(pilot,[{'read':1200}],every,outdir,log,bram=False)
            if not native_keyboard_ready(pilot):
                raise RuntimeError('Hospital list did not open the actual native keyboard')
        elif "light" in st or "light_scan" in st:
            # Metal's light in a dark room (Queen Hospital's door 3): holding II hides the menu
            # and the pad moves the lit circle - the only bright pixels on the black picture -
            # and an object is found when it sits in the circle. "light": [x, y] moves the
            # circle there; "light_scan" visits a grid and takes every Look/Check item that
            # appears (the base lists are what the dark room offered)
            import numpy as np
            def spot():
                im = np.array(pilot.emu.image().convert("L").crop((0, 0, 256, 152))).astype(int)
                ys, xs = np.nonzero(im > 40)
                return (float(xs.mean()), float(ys.mean())) if len(xs) > 30 else None
            tol = st.get("tol", 6)           # (the vase at the end of door 3's room wants 2: off by
            def move_to(tx, ty):            # 5 px Metal says the light is off target)
                for _ in range(120):
                    pilot.step(4, ["b"])
                    pos = spot()
                    if pos is None:
                        pilot.step(4, ["b"]); continue
                    dx, dy = tx - pos[0], ty - pos[1]
                    if abs(dx) <= tol and abs(dy) <= tol:
                        break
                    held = ["b"]
                    if abs(dx) > tol: held.append("right" if dx > 0 else "left")
                    if abs(dy) > tol: held.append("down" if dy > 0 else "up")
                    pilot.step(2 if tol < 6 else 4, held)
                pilot.step(20)
                return spot()
            if "light" in st:
                log(f"{pilot.frame}: light to {st['light']} -> {move_to(*st['light'])}")
            else:
                spec = st["light_scan"] if isinstance(st["light_scan"], dict) else {}
                if "xs" in spec:
                    targets = [(tx, ty) for ty in spec.get("ys", [24, 64, 104, 136]) for tx in spec["xs"]]
                else:
                    # the room's objects are sprites (drawn only inside the light): their cells
                    sat = pilot.sat()
                    cells = sorted({((x - 32) // 16 * 16 + 8, (y - 64) // 16 * 16 + 8) for y, x, p_, a in sat
                                    if y and 0x100 <= (p_ & 0x7FF) < 0x300 and (p_ & 0x7FF) != 0x1AA and 0 <= y - 64 < 152 and 0 <= x - 32 < 256})
                    targets = cells
                    log(f"{pilot.frame}: light targets from the SAT: {targets}")
                base = {}
                for verb in ("Look", "Investigate"):
                    m = wait_menu(pilot, every, limit=1200)
                    if m and norm(verb) in [norm(t) for t in pilot.items()]:
                        pilot.choose(verb); pilot.step(24); base[verb] = set(norm(t) for t in pilot.items()); pilot.press("b"); pilot.step(20)
                    else:
                        base[verb] = set()
                found = []
                for tx, ty in targets:
                    if True:
                        pos = move_to(tx, ty)
                        log(f'{pilot.frame}: light scan target {(tx,ty)} reached {pos}')
                        for verb in ("Look", "Investigate"):
                            m = wait_menu(pilot, every, limit=1200)
                            if not m or norm(verb) not in [norm(t) for t in pilot.items()]:
                                continue
                            pilot.choose(verb); pilot.step(24)
                            m2 = pilot.settled()
                            if m2 is not None and norm(verb) not in [norm(t) for t in pilot.items()]:
                                # a sub-list: the lit object (Look/Investigate act on the light directly otherwise)
                                items = [t for t in pilot.items() if norm(t) not in base[verb]]
                                if items:
                                    log(f"{pilot.frame}: light at {pos}: {verb} > {items[0].strip()}")
                                    pilot.choose(items[0]); found.append((verb, items[0].strip(), pos))
                                    base[verb].add(norm(items[0]))
                                else:
                                    pilot.press("b"); pilot.step(20); continue
                            for _ in range(st.get("read", 4000) // every):
                                if pilot.menu() is not None: break
                                pilot.press("a"); pilot.step(every)
                log(f"{pilot.frame}: light scan found {found}")
        elif "submenu" in st:
            # choose the first label if a menu has it, then the second inside; back out (II)
            # when the second is not there (Use Metal Gear > Light on where there is no light)
            first, second = st["submenu"]
            m = wait_menu(pilot, every, limit=600)
            if m is None or norm(first) not in [norm(t) for t in pilot.items()]:
                log(f"{pilot.frame}: no {first!r} here")
                continue
            pilot.choose(first)
            pilot.step(24)
            if norm(second) in [norm(t) for t in pilot.items()]:
                log(f"{pilot.frame}: {first} > {second}")
                pilot.choose(second)
            else:
                log(f"{pilot.frame}: no {second!r} under {first!r}")
                pilot.press("b")
        elif "maybe" in st:
            # choose the label if a menu with it is up; else nothing
            m = wait_menu(pilot, every, limit=600)
            have = [norm(t) for t in pilot.items()] if m else []
            if norm(st["maybe"]) in have:
                log(f"{pilot.frame}: choose {st['maybe']!r}")
                pilot.choose(st["maybe"])
            else:
                log(f"{pilot.frame}: no {st['maybe']!r} here")
        elif "when" in st:
            # the steps only when a word was said lately (Napoleon rejecting REIGN: call again
            # and answer OVER)
            recent = " ".join(pilot.pages[pilot.page_mark:]).lower()     # since the last type step
            if st["when"].lower() in recent:
                log(f"{pilot.frame}: {st['when']!r} was said: {len(st['steps'])} steps")
                run(pilot, st["steps"], every, outdir, log, bram=False)
            else:
                log(f"{pilot.frame}: {st['when']!r} not said: skipped")
        elif "aim" in st:
            pilot.aim = st["aim"]
            pilot.fought = False
        elif "press" in st:
            for _ in range(st.get("n", 1)):
                pilot.press(st["press"])
                pilot.step(st.get("gap", 60))
        elif "wait" in st:
            pilot.step(st["wait"])
        elif "read" in st:
            # advance dialogue until a menu opens (or the frames run out); a list the last
            # choice opened may still be on its way: a moment first, no press into it
            pilot.step(30)
            for _ in range(st["read"] // every):
                if native_keyboard_ready(pilot):
                    break
                if wait_menu(pilot, every, limit=every) is not None:
                    break
                if native_keyboard_ready(pilot):
                    break
                pilot.press("a")
                pilot.step(every)
        elif "shot" in st:
            pilot.emu.image().save(os.path.join(outdir, st["shot"] + ".png"))
            log(f"{pilot.frame}: shot {st['shot']}")
        elif "save" in st:
            open(os.path.join(outdir, st["save"] + ".mdf"), "wb").write(pilot.emu.state())
            log(f"{pilot.frame}: saved {st['save']}")
        elif "items" in st:
            log(f"{pilot.frame}: items {pilot.items()}")
        elif "dial" in st:
            # the videophone's keypad (1 2 3 / 4 5 6 / 7 8 9 / * 0 #), reached from the verb menu
            # by Use Metal Gear > Videophone > Call > (What number?); the cursor's key is read
            # back from $36B0 = 7 + 12 * row + 2 * col (closed loop: a press held 8 frames moves one key)
            pad = ["123", "456", "789", "*0#"]
            def cursor():
                v = pilot.ram()[0x16B0] - 7
                return divmod(v, 12) if 0 <= v < 48 else (None, None)
            # through "What number?" to the pad: a fresh pad reads cursor 45 (the 0 key), 0 typed
            # and a 10-item list; the bytes keep the last call's values until then
            pilot.press("a"); pilot.step(60)
            for _ in range(12):                                  # (the phone's pad lists 10 items, the answer pad 12)
                r = pilot.ram()
                if r[0x16B0] == 45 and r[0x16B2] == 0:
                    break
                pilot.press("a"); pilot.step(60)
            pilot.step(30)
            trace = []
            for ch in st["dial"]:
                want = next((r, pad[r].index(ch)) for r in range(4) if ch in pad[r])
                trace.append((ch, pilot.ram()[0x16B0], pilot.ram()[0x16B2], pilot.ram()[0x1518]))
                for _ in range(24):
                    row, col = cursor()
                    if row is None:
                        raise SystemExit(f"frame {pilot.frame}: no keypad cursor ($36B0)")
                    col //= 2
                    if (row, col) == want:
                        break
                    before = pilot.ram()[0x16B0]
                    for _ in range(3):                             # a move the pad missed: again
                        # the bottom row has only the 0 key: down/up through column 1
                        if row != want[0] and (3 in (row, want[0])) and col != 1:
                            pilot.step(8, ["right" if col < 1 else "left"])
                        elif row != want[0]:
                            pilot.step(8, ["down" if want[0] > row else "up"])
                        else:
                            pilot.step(8, ["right" if want[1] > col else "left"])
                        pilot.step(24)
                        if pilot.ram()[0x16B0] != before:
                            break
                for _ in range(4):                                 # a press the game missed: again
                    n = pilot.ram()[0x16B2]                        # $36B2 = digits typed
                    pilot.step(12); pilot.step(6, ["a"]); pilot.step(36)
                    if pilot.ram()[0x16B2] != n:
                        break
            if st.get("confirm"):                                # a number answered with RUN (Catherine's questions)
                pilot.step(12); pilot.step(6, [st["confirm"]]); pilot.step(30)
            log(f"{pilot.frame}: dialled {st['dial']} (cursor/count/list before each digit: {trace})")
        elif "type" in st:
            # the Latin keyboard (pcekeyboard.KEYS): row 0 A-T, row 1 U-Z, the marks and OK
            # below. The cursor's key is read back from $36B0: row 0 = 25 + i + i // 5 (a gap
            # between the groups of five), row 1 = 73 + i + i // 5, OK = 133 (down from any
            # of K-O; row 1 has nothing under them). Closed loop, a press held 8 frames.
            rows = ["ABCDEFGHIJKLMNOPQRST", "UVWXYZ"]
            bases = [25, 73]
            def value(row, i):
                return bases[row] + i + i // 5
            def cur():
                return pilot.ram()[0x16B0]
            def goto(row, i):
                path = []
                for _ in range(60):
                    v = cur()
                    path.append(v)
                    if v == value(row, i):
                        return True
                    if v >= 121:                                  # the marks row: up to row 0
                        pilot.step(8, ["up"])
                    elif v >= 73 and row == 0:
                        pilot.step(8, ["up"])
                    elif v < 73 and row == 1:
                        # row 1 (U-Y, then Z) is entered by down from A-E; elsewhere down lands on OK
                        pilot.step(8, ["down"] if v <= value(0, 4) else ["left"])
                    else:
                        pilot.step(8, ["right" if value(row, i) > v else "left"])
                    pilot.step(20)
                raise SystemExit(f"frame {pilot.frame}: keyboard cursor stuck at {cur()} (want {row},{i}; path {path})")
            word = st["type"]
            if isinstance(word, dict):
                # a second try by what was said (Napoleon rejects the 100-year REIGN with "the
                # revolution is OVER?" and opens the keyboard again): the first key found in the
                # pages read lately, nothing at all - not a press - when none is
                recent = " ".join(pilot.pages[-12:]).lower()
                word = next((w for k, w in word.items() if k != "else" and k.lower() in recent), word.get("else", ""))
                log(f"{pilot.frame}: the pages read {recent[-80:]!r}: typing {word!r}")
                if not word:
                    continue
            # a text still up in front of the keyboard (Metal's 'type the hospital name'):
            # read it through until the cursor sits on a key (the fresh keyboard opens on A)
            letter_keys={value(r,i) for r in range(2) for i in range(len(rows[r]))}
            for _ in range(20):
                state=pilot.ram()
                # Resident $BD56 places the native keyboard cursor using these
                # row/base fields. COUNT belongs to an earlier menu/question.
                keyboard_live=native_keyboard_ready(pilot)
                if keyboard_live and state[0x16B2]==0:
                    break
                if keyboard_live and state[0x16B2]:
                    # A cursor scan may have moved the active keyboard away from A.
                    # Clear existing text via the native backspace key, never by RAM writes.
                    goto(0,10)
                    pilot.step(8,['down']);pilot.step(20)
                    pilot.step(8,['right']);pilot.step(20)
                    if cur()!=128:
                        raise SystemExit(f'frame {pilot.frame}: no native keyboard backspace ({cur()})')
                    for _ in range(32):
                        count=pilot.ram()[0x16B2]
                        if count==0:break
                        pilot.step(6,['a']);pilot.step(30)
                        if pilot.ram()[0x16B2]>=count:
                            raise SystemExit(f'frame {pilot.frame}: native keyboard backspace did not erase')
                    else:raise SystemExit('Native keyboard text exceeded32 characters')
                    goto(0,0)
                    break
                pilot.step(60)
            else:
                raise SystemExit(f'frame {pilot.frame}: native keyboard did not become ready')
            for ch in word.upper():
                row, i = next((r, rows[r].index(ch)) for r in range(2) if ch in rows[r])
                goto(row, i)
                for _ in range(4):                                 # a press the game missed: again
                    n = pilot.ram()[0x16B2]                        # $36B2 = letters typed
                    pilot.step(8); pilot.step(6, ["a"]); pilot.step(30)
                    if pilot.ram()[0x16B2] == n+1:
                        break
                else:
                    raise SystemExit(f'frame {pilot.frame}: native keyboard did not accept {ch!r}')
            if pilot.ram()[0x16B2] != len(word):
                raise SystemExit(f'frame {pilot.frame}: native typed count differs from {word!r}')
            log(f'{pilot.frame}: native keyboard count {pilot.ram()[0x16B2]}, bytes {pilot.ram()[0x16B0:0x16F0].hex()}')
            pilot.emu.image().save(os.path.join(outdir,f'keyboard-before-ok-{pilot.frame}.png'))
            if st.get("ok", True):
                goto(0, 10)                                       # K, then down = OK
                pilot.step(8, ["down"]); pilot.step(20)
                if cur() != 133:
                    raise SystemExit(f"frame {pilot.frame}: no OK under K ({cur()})")
                pilot.step(6, ["a"]); pilot.step(30)
            log(f"{pilot.frame}: typed {word!r}")
            pilot.page_mark = len(pilot.pages)
        elif "sweep" in st:
            if norm(st['sweep'])=='item' and norm('Item') in [norm(x) for x in pilot.items()]:
                # Repeated JUNKER ID/Funds/Evidence labels belong to distinct
                # Look/Investigate/Show paths. Use the proved native full-path
                # walker rather than sharing a label counter across branches.
                from pcestress_items import native_explore
                native_explore(pilot,outdir,f'item-paths-{pilot.frame}')
                continue
            # open the verb, take every topic once (rounds: each twice...)
            verb, rounds = st["sweep"], st.get("rounds", 1)
            avoid = {norm(t) for t in st.get("avoid", [])}       # topics never taken (Terminal ends the church)
            taken = {}
            parent = None                      # the topic whose sub-list is up
            for _ in range(120):
                here = []
                for _ in range(3):
                    wait_menu(pilot, every)
                    here = [t.strip() for t in pilot.items()]
                    if here:
                        break
                if norm(verb) not in [norm(t) for t in here]:
                    # a prompt or a sub-topic list: take what is untaken, else
                    # the closing item (Others / その他 / No), never Ask again
                    fresh = [t for t in here if taken.get(t, 0) < rounds and t not in AGAIN and norm(t) not in avoid]
                    if not here:
                        log(f"{pilot.frame}: no menu, sweep {verb!r} over")
                        break
                    if any(t.strip() in ("Look", "Move", "Use Metal Gear", "Exit Tricycle") for t in here):
                        # a verb menu without the verb, or the tricycle's list (the scene moved on
                        # under the sweep - Ivan's bathroom ends on the plastic bag): never into
                        # Save or a ride round the city
                        log(f"{pilot.frame}: a verb menu without {verb!r}, sweep over")
                        break
                    pick = min(fresh, key=lambda t: taken.get(t, 0)) if fresh else here[-1]     # the least taken first
                    if any(norm(t) in ("quit game", "stop") for t in here) and any(norm(t) == "continue" for t in here):
                        # the game-over prompt under a sweep: always Continue (a sweep took Quit game
                        # after a basement death and the run went back to the title)
                        pick = next(t for t in here if norm(t) == "continue")
                    if not fresh and pick in AGAIN:
                        log(f"{pilot.frame}: only {here}, sweep {verb!r} over")
                        break
                    if parent and fresh:
                        # a sub-list with a fresh item: the topic that opened it stays fresh, so
                        # the next round comes back (Lisa's About Freddy > How he's been /
                        # Health / Occupation, and Alibi appears in Occupation's place after)
                        taken[parent] = max(0, taken.get(parent, 0) - 1)
                    parent = None
                    log(f"{pilot.frame}: {here} -> {pick!r}")
                    try:
                        pilot.choose(pick)
                    except SystemExit as e:              # the menu went away under us (a scene moved on)
                        log(f"{pilot.frame}: {e}; sweep {verb!r} over")
                        break
                    taken[pick] = taken.get(pick, 0) + 1
                    continue
                parent = None
                pilot.choose(verb)
                pilot.step(24)
                topics = [t.strip() for t in pilot.items()]
                todo = sorted([t for t in topics if taken.get(t, 0) < rounds and norm(t) != norm(verb) and norm(t) not in avoid],
                              key=lambda t: taken.get(t, 0))
                if not todo:
                    pilot.press("b")           # back out of the topic list
                    log(f"{pilot.frame}: sweep {verb!r} done: {taken}")
                    break
                try:
                    pilot.choose(todo[0])
                except SystemExit as e:
                    log(f"{pilot.frame}: {e}; sweep {verb!r} over")
                    break
                taken[todo[0]] = taken.get(todo[0], 0) + 1
                parent = todo[0]
                log(f"{pilot.frame}: {verb} > {todo[0]}")
                wait_menu(pilot, every)


def main():
    global JAPANESE, SLOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--cue", default=PATCHED)
    ap.add_argument("--state", required=True)
    ap.add_argument("--route", required=True)
    ap.add_argument("--every", type=int, default=90)
    ap.add_argument("--out", default=os.path.join(WORK, "pce", "route"))
    ap.add_argument("--japanese", action="store_true", help="the pristine game: labels are Shift-JIS")
    ap.add_argument("--bram", action="store_true",
                    help="save the game and dump the backup RAM once per module (= PCESAVE=1)")
    ap.add_argument("--slot", type=int, default=SLOT, help="the game's save slot (1-4)")
    a = ap.parse_args()
    SLOT = a.slot
    JAPANESE = a.japanese
    pilot = Pilot(cue=a.cue)
    pilot.restore(a.state)
    route = json.load(open(a.route, encoding="utf-8"))
    run(pilot, route, every=a.every, outdir=a.out,
        bram=True if a.bram else None,
        route_name=os.path.splitext(os.path.basename(a.route))[0])
    pilot.emu.image().save(os.path.join(a.out, "final.png"))
    print(f"done at frame {pilot.frame}")


if __name__ == "__main__":
    main()
