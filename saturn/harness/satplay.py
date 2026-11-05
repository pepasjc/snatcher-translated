# -*- coding: utf-8 -*-
"""The Saturn scripted play-test: run a route, read every card and menu back
out of the text cells, and report what a player would see.

    python saturn/harness/satplay.py --route saturn/harness/routes/B010.json --state B010_start --frames 200000
    python saturn/harness/satplay.py --route ... --new                 (New Game, through the opening)
    python saturn/harness/satplay.py --lint B010 B020                  (static: the data against the geometry)

The PS1's ps1/harness/scripted.py is the design: a route is a list of menu
paths in our own labels, `sweep` opens each verb and picks every item it
offers (Luiz's method, `rounds` times over), `each` sweeps a room on arrival,
and every decision is closed-loop on the ENGINE's cursor (satmem.py). The
difference is validation: the PS1 harness finds text in screenshots by FFT
correlation; the Saturn engine lays every card and menu out in a cell
array (ctx+0x3FA: 4 rows x 20 {u16 sjis, colour}), so the text is read
BACK from RAM - each cell through the build's pair table
(work/saturn/pair_table_sat.json: pair -> code, cell = negated code) or as
the SJIS character it is - and compared exactly.

What is flagged (per card / menu, in log.txt and problems.txt):
    JP        a Japanese character in a card whose string has `en` (a glyph
              the build missed) - a string with no `en` is `untranslated`
    BLANK     a non-blank cell whose SJIS->glyph table entry is 0 (draws nothing)
    GARBAGE   a cell that decodes to nothing known (not a pair, not cp932)
    WIDE      a source row past the box width (20 cells; 14 on Gaudi's
              terminal, ctx+0x56A == 7): the Saturn has no runtime wrap, the
              row runs into the next one
    LABEL     a list-menu label past 10 cells (its tail lands on the item
              beside it: the two-column geometry, 10 cells per item)
    FALLBACK  fullwidth letters (a pair with no glyph slot): readable but
              spaced - counted, listed once per string
    UNMATCHED a card no bank string accounts for (engine text, or a string
              the matcher could not follow)

Route actions (saturn/harness/routes/*.json):
    {"new": true}                    boot to NEW GAME and sit through the opening
    {"wait_menu": true}              advance cards until a menu is live
    {"path": ["Look", "Door"]}       descend menus by label ("A|B" = first offered)
    {"path": [...], "reps": 2, "optional": true, "patience": 3000}
    {"sweep": ["Look", "Check"], "rounds": 2, "avoid": [...]}
    {"sweep": ["Move"], "each": ["Look", "Check"], "each_rounds": 2, "rounds": 2}
    {"menu": 1}                      pick an index
    {"press": "a"}, {"cancel": true}, {"idle": 300}, {"save": "NAME"}
    {"phone": "393444", "then": [[...]]}   call a number on the videophone, then the paths given
    {"bsave": "NAME"}                the game's own Use Metal Gear > Save from here, the
                                     backup RAM into work/saturn/saves/NAME.bkr (satsave.py)
    {"fight": "body"}                (aim, once the Saturn's shootout is driven)

Every bank the run passes through gets a bookmark at its first live verb
menu: work/saturn/states/<bank>_auto (the previous one kept as .prev).
Captures: work/saturn/play/<bank>/card_NNNN_fFFFFFF.png (the settled frame
of every card), menu_NNNN_*.png (each distinct menu), and every frame with
a problem. Log: work/saturn/play/<run>/log.txt, problems.txt, cards.json.
"""
import argparse, collections, glob, gzip, hashlib, json, os, re, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import satmem, satpilot, satrun, satfont
RAMTOUCH = os.environ.get('RAMTOUCH', '')
RAMTOUCH_N = int(RAMTOUCH.split(',')[0]) if RAMTOUCH else 0
import satsubs

STATES = satpilot.STATES
PLAY = os.path.join(WORK, "saturn", "play")
PLAY_IMAGE = os.path.join(ROOT, "patched", "saturn", "play", "Snatcher (Japan).cue")
TRANS = os.path.join(ROOT, "saturn", "translation")
REF = os.path.join(WORK, "saturn", "ref")
# the pair table of the image being played: satrecover.py's copy beside the play
# image first (work/'s is rewritten by every build), then the build's own
SAT_TABLE = next((p for p in (os.path.join(ROOT, "patched", "saturn", "play", "pair_table_sat.json"),
                              os.path.join(WORK, "saturn", "pair_table_sat.json")) if os.path.exists(p)), None)
BAND = 0x060F2A08            # u16, 2 while the voice band (face at the left) is up
WINDOW_MODE = satmem.CTX + 0x56A   # u8, 7 = Gaudi's terminal (14 cells)
TICK = 0x060F5640            # a free-running vblank counter
VOICE_DEC = 0x060EA2BC       # u32 ADPCM bytes decoded of the live voice line (11,025 B/s); still = no voice
VOICE_SECTOR = 0x060EA2C2    # u16 the live line's sector
BAND_DONE = 45               # frames the decoder must sit still under an open band before A
TABLE_ADDR, TABLE_LO, TABLE_N = satfont.TABLE_ADDR, satfont.TABLE_LO, satfont.TABLE_N
BOX_W, TERM_W, LABEL_W = 20, 14, 10
MAX_SLOT = 1880 + 584        # the font (1,880 slots) plus satglyphs' VRAM extension; raised to the table's max
PRESS, STEP_GAP, MENU_SETTLE, ADVANCE = satpilot.PRESS, satpilot.STEP_GAP, satpilot.MENU_SETTLE, satpilot.ADVANCE
PATIENCE = 3000
MAX_DEATHS = int(os.environ.get("MAX_DEATHS", "6"))    # Continue after a death this many times, then give up
CARD_SETTLE = 12             # frames the cells must hold still before a card is read
HOLD_CARD = int(os.environ.get("HOLD_CARD", 40))     # frames a waiting card stays up before A
NUDGE = 900                  # frames with nothing to do before A is pressed blind
START_NUDGE = 400            # frames with nothing to do (A presses included) before START is tried (the Blaster prompt)
IDLE_PAGE = 150              # frames a flagless screen sits still before A
WEDGE_FRAMES = 300           # frames of a stopped vblank counter = the machine is hung
OK, BACK = "a", "b"
VERBS = {'look', 'check', 'move', 'item', 'use metal gear', 'enter', 'get in', 'get out', 'hear',
         'talk', 'ask', 'smell', 'sniff', 'eat', 'buy', 'go out', 'use gaudi', 'call', 'knock',
         'investigate', 'go inside', 'listen', 'board tricycle', 'exit tricycle', 'train', 'exit',   # the 2026-09-15 re-carry's labels
         '見る', '調べる', '話す', '聞く', '移動', '入る', 'アイテム', '中に入る', '出る'}
SUBMENU_VERBS = {'look', 'check', 'ask', 'move', 'item', 'use metal gear', 'go out'}
AVOID = {'go out', 'get in', 'get out', 'leave', 'exit', 'save', 'videophone', 'home', 'junker hq',
         'ruins', 'factory ruins', 'load', 'quit'}
BANK_NAMES = {21 + i: "B%03X" % (i * 0x10) for i in range(39)}     # 22 -> B010 ... 59 -> B260
BANK_OF = {v: k for k, v in BANK_NAMES.items()}
FULLW_ASCII = {0x8140: " "}
for i in range(26):
    FULLW_ASCII[0x8260 + i] = chr(65 + i)
    FULLW_ASCII[0x8281 + i] = chr(97 + i)
for i in range(10):
    FULLW_ASCII[0x824F + i] = str(i)
for fw, a in (("！", "!"), ("？", "?"), ("，", ","), ("．", "."), ("：", ":"), ("；", ";"), ("’", "'"),
              ("（", "("), ("）", ")"), ("－", "-"), ("／", "/"), ("＆", "&"), ("＃", "#"), ("％", "%")):
    FULLW_ASCII[int.from_bytes(fw.encode("cp932"), "big")] = a
COLOUR_RE = re.compile("＠.")
SYMBOLS = set("▽△▼▲○●◎☆★→←↑↓♪※")     # markers the English keeps (the terminal's ▽ headers)
OMEGA_SJIS = 0x83D6          # code 0x7d2a, textcodec's ω: the Saturn's invisible marker on verbs (`Lookω`); its
                             # table entry is zero in the pristine exec and satexec keeps it out of the hole


BANK_CODE = 0x002F8000       # a loaded bank's bytecode (file offset 4 on); strings at 0x002E8000
_BANK_HEADS = {}


def bank_in_ram(mem):
    """Which DATA.BIN entry (21 = B000 ... 59 = B260) is loaded, by its bytecode
    head at BANK_CODE (satmem.bank_in_ram names an undefined BANK_CODE)."""
    if not _BANK_HEADS:
        for p in glob.glob(os.path.join(WORK, "saturn", "data", "0*_B*.bin")):
            _BANK_HEADS[int(os.path.basename(p)[:3])] = open(p, "rb").read()[4:68]
    head = mem.read(BANK_CODE, 64)
    return next((n for n, h in _BANK_HEADS.items() if h == head), None)


# ---- the cells, decoded ------------------------------------------------------
class Decoder:
    """cell SJIS -> (text, kind); kind in pair / fw / jp / blank / garbage."""

    def __init__(self, mem=None, table_bytes=None):
        t = json.load(open(SAT_TABLE))
        self.rev = {satfont.code_to_sjis(code): pair for pair, (slot, code) in t.items()}
        global MAX_SLOT
        MAX_SLOT = max(MAX_SLOT, max(slot for slot, code in t.values()) + 8)
        self.table = table_bytes        # the SJIS->glyph table, read from RAM
        self.mem = mem

    def load_table(self):
        self.table = self.mem.read(TABLE_ADDR, 2 * TABLE_N)

    def slot(self, sjis):
        i = sjis - TABLE_LO
        if self.table is None or not 0 <= i < TABLE_N:
            return None
        return struct.unpack_from(">H", self.table, 2 * i)[0]

    def cell(self, sjis):
        if sjis in (0, satmem.BLANK_CELL, 0x8140):     # 0x8140 = fullwidth space (the payload's clear)
            return " ", "blank"
        if sjis == OMEGA_SJIS:                          # the game's own invisible code (`見るω`): slot 0 by design
            return "", "omega"                          # row() checks the entry really is 0
        if sjis in self.rev:
            return self.rev[sjis], "pair"
        if sjis in FULLW_ASCII:
            return FULLW_ASCII[sjis], "fw"
        try:
            ch = sjis.to_bytes(2, "big").decode("cp932")
        except UnicodeDecodeError:
            return "?", "garbage"
        if ch == "￥":
            return "/", "jp"
        if ch in SYMBOLS:
            return ch, "sym"
        return ch, "jp"

    def row(self, raw, cols=20):
        """One cell row (raw bytes) -> (text, cells) where cells = [(sjis, text, kind, slot)]."""
        out, txt = [], ""
        for c in range(cols):
            sjis = struct.unpack_from(">H", raw, c * 4)[0]
            t, k = self.cell(sjis)
            s = self.slot(sjis)
            if k == "omega":
                k = "blank" if s == 0 else "garbage"   # a stub's bytes in the omega entry drew junk once (satexec)
            elif k != "blank" and s == 0:
                k = "blank0"                 # a real code whose glyph is slot 0: draws nothing
            elif k != "blank" and (s is None or s > MAX_SLOT):
                k = "garbage"                # no table entry, or one past the font (the exec hole's bytes)
            out.append((sjis, t, k, s))
            txt += t
        return txt, out


def read_cells(mem, dec, rows=4, cols=20):
    raw = mem.read(satmem.TEXT_CELLS, rows * satmem.TEXT_ROW)
    return [dec.row(raw[r * satmem.TEXT_ROW:(r + 1) * satmem.TEXT_ROW], cols) for r in range(rows)]


def fold(s):
    """Fullwidth ASCII (Ａ, ！) -> ASCII; the data uses it for coloured initials."""
    return "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in s)


def squash(s):
    """Text -> comparison key: no spaces, no colour codes, fullwidth folded."""
    return fold(COLOUR_RE.sub("", s)).replace(" ", "").replace("　", "").replace("￥", "").replace("/", "").replace("ω", "")


# ---- the bank's strings, for matching -------------------------------------------
class Bank:
    """Every string of a bank (translation + jp ref), keyed for the cards."""

    def __init__(self, entry, pf=None):
        self.entry, self.name = entry, BANK_NAMES.get(entry, str(entry))
        self.strings = []
        tpath = glob.glob(os.path.join(TRANS, f"SAT_{entry:03d}_*.json"))
        rpath = glob.glob(os.path.join(REF, f"SAT_{entry:03d}_*.json"))
        ref = {}
        if rpath:
            r = json.load(open(rpath[0], encoding="utf-8"))
            for s in (r["strings"] if isinstance(r, dict) else r):
                ref[s["off"]] = s.get("jp", "")
        over = set()
        ob = os.path.join(WORK, "saturn", "build", "over_budget.txt")
        if os.path.exists(ob):
            for line in open(ob, encoding="utf-8"):
                m = re.match(r"(\d+) \S+ off=(\d+) ", line)
                if m and int(m.group(1)) == entry:
                    over.add(int(m.group(2)))
        if tpath:
            t = json.load(open(tpath[0], encoding="utf-8"))
            for s in t["strings"]:
                jp = ref.get(s["off"], "")
                en = s.get("en") or ""
                # an over-budget string keeps its Japanese in the slot, but satlong remaps it
                # to a tail copy of the `en` (the over-budget policy), so the card reads English
                text = en if en and not s.get("lock") else jp
                rows = [COLOUR_RE.sub("", x) for x in text.split("￥")] if text else []
                self.strings.append(dict(off=s["off"], en=en, jp=jp, lock=s.get("lock", False),
                                         long=s.get("long"), rows=rows, key=squash(text),
                                         raw_rows=text.split("￥") if text else [],
                                         has_en=bool(en) and not s.get("lock")))
        self.over = over
        self.by_key = {}
        for s in self.strings:
            if s["key"]:
                self.by_key.setdefault(s["key"], s)
        # the long labels: the remap shows the `long` text where the short en sits
        for s in self.strings:
            if s.get("long"):
                self.by_key.setdefault(squash(s["long"]), dict(s, en=s["long"], key=squash(s["long"]),
                                                               raw_rows=s["long"].split("￥"),
                                                               rows=[COLOUR_RE.sub("", x) for x in s["long"].split("￥")]))
        self.keys_sorted = sorted(self.by_key, key=len, reverse=True)
        self.pf = pf

    def width(self, row):
        """Cells a source row takes, through the pair font (fallbacks = 2 cells)."""
        if self.pf is None:
            return len(row)
        # a colour code takes no cell, but it ends the pair run before it: each run is
        # encoded (and padded) on its own, as satapply wrote it
        try:
            return sum(len(self.pf.encode(run)) // 2 for run in COLOUR_RE.split(row) if run)
        except Exception:
            return len(COLOUR_RE.sub("", row))

    def match(self, rows):
        """The string(s) behind a card's text rows. Returns a list of strings
        (one, or a chain the box printed back to back), or []."""
        key = squash("".join(rows))
        if not key:
            return []
        if key in self.by_key:
            return [self.by_key[key]]
        # a scrolled or partial card: one string containing the card
        if len(key) >= 8:
            cands = [s for k, s in self.by_key.items() if key in k]
            if cands:
                return [min(cands, key=lambda s: len(s["key"]))]
        # a chain of whole strings printed into one box
        out, rest = [], key
        while rest:
            hit = next((k for k in self.keys_sorted if rest.startswith(k) and len(k) >= 2), None)
            if hit is None:
                break
            out.append(self.by_key[hit]); rest = rest[len(hit):]
        if out and (not rest or len(rest) <= 2):
            return out
        # the card's first rows match a string's beginning (typing cut short)
        if len(key) >= 12:
            cands = [s for k, s in self.by_key.items() if k.startswith(key[:12])]
            if cands:
                return [min(cands, key=lambda s: len(s["key"]))]
        return []


PAD_RE = re.compile("((?:^|[^\x00-\x7f])([\x00-\x7f]+))(＠.)(?=[\x21-\x7e])")


def pads(en):
    """Where the pair encoder's pad shows: an odd-length ASCII run closed by a
    colour code with a letter right after it ('Gaudi＠白.' draws 'Gaudi .',
    'civilian ＠赤bounty' a double space) - a whole blank cell on the Saturn."""
    out = []
    for m in PAD_RE.finditer(en):
        run = m.group(2)
        if len(run) % 2 == 1:
            out.append(run[-8:] + "|" + en[m.end():m.end() + 6])
    return out


def load_names():
    p = os.path.join(TRANS, "names.json")
    if not os.path.exists(p):
        return set()
    d = json.load(open(p, encoding="utf-8"))
    names = d.get("names", []) if isinstance(d, dict) else d
    out = {squash(n["en"]) for n in names if isinstance(n, dict) and n.get("en")}
    return out | {squash(n["jp"]) for n in names if isinstance(n, dict) and n.get("jp")}


def load_cues(bank_name):
    p = os.path.join(TRANS, f"subs_{'INTRO' if bank_name == 'B000' else bank_name}.json")
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))
    out = {}
    for c in d.get("cues", []):
        rows = c.get("rows") or [c.get("en", "")]
        out[squash("".join(rows))] = c
    return out


class Wedged(Exception):
    """The vblank counter stopped: the SH-2 is hung (Gaudi's 'Witch hunts' entry)."""

class GaveUp(Wedged):
    """Too many deaths at one shootout: the route ends (run_route)."""


# ---- the runner -------------------------------------------------------------------
class Play(satpilot.Pilot):
    def __init__(self, emu, out, log, image, autosave=True):
        super().__init__(emu, log)
        self.out, self.image, self.autosave = out, image, autosave
        self.dec = Decoder(self.mem)
        self.pf = None
        try:
            from satapply import SatPairFont
            self.pf = SatPairFont(json.load(open(SAT_TABLE)))
        except Exception as e:
            log(f"no pair font for width checks: {e}")
        self.names = load_names()
        self.banks = {}
        self.cues = {}
        self.bank = None            # entry number of the bank in RAM
        self.bank_since = 0
        self.bank_frames = collections.Counter()
        self.bank_cards = collections.Counter()
        self.bank_menus = collections.Counter()
        self.auto_pending = None
        self.auto_done = set()
        self.saved = []
        self.cards = []             # every card read: dict
        self.menus = []             # every distinct menu
        self.problems = []
        self.last_cells = None
        self.pre_card = None
        self.stable_since = 0
        self.card_key = None        # key of the card last logged (cells)
        self.face_watch = None      # (card rec, cue, bplain) of the band card up, judged frame by frame
        self._bplain_addr = {}      # bank -> the payload's `bplain` word (0 = none)
        self.card_logged_at = -1
        self.menu_key = None
        self.menus_seen = set()
        self.top_labels = []
        self.band_seen = False
        self.last_menu_live = False
        self.live_since = None
        self.last_press_f = -1000
        self.last_activity = 0
        self.nudges = 0
        self.start_nudged = -100000
        self.idle_presses = 0
        self.tick, self.tick_at, self.last_pick = None, 0, None
        self.last_state = None
        self.last_nudge = -100000
        self.width_flagged = set()
        self.fallback_flagged = set()
        self.wall0 = time.time()
        self.fight_state = None
        self.in_fight, self.fight_since, self.fights, self.fight_view = False, 0, 0, None
        self.deaths = 0
        self.in_death = False
        self.death_counted = False
        self.voice_dec, self.voice_changed_at, self.band_since = None, 0, None
        self.voice_end_at = None
        self.voice_lines = 0
        self._n = 0
        import satsubcheck
        self.subwatch = satsubcheck.SubWatch(self)

    # ---- per-frame tracking ------------------------------------------------------
    def run(self, n=1, hook=None):
        for _ in range(n):
            if self.f == self.held_until:
                self.emu.held = set()
            self.emu.run(); self.f += 1
            self.track()
            if RAMTOUCH and self.f % RAMTOUCH_N == 0:
                self.ramtouch_sample()
            if hook:
                hook(self.f)

    # RAMTOUCH=N[,path]: every N frames OR the bytes that changed since the
    # last sample into a 2 MB mask (CPU byte order: block offset 0 = low WRAM
    # 0x00200000, 1 MB = high WRAM 0x06000000; 1 = written at least once),
    # saved at exit - the free-RAM census (ramfree_sat.py), as the PS1's.
    def ramtouch_sample(self):
        import numpy as np
        raw = np.frombuffer(self.mem.raw(0, 2 * satmem.WRAM), dtype=np.uint8).copy()
        cur = raw.reshape(-1, 2)[:, ::-1].reshape(-1)          # un-swap the halfwords
        prev = getattr(self, '_rt_prev', None)
        if prev is None:
            self._rt_mask = np.zeros(2 * satmem.WRAM, dtype=np.uint8)
            import atexit
            atexit.register(self.ramtouch_save)
        else:
            self._rt_mask |= (cur != prev)
        self._rt_prev = cur

    def ramtouch_save(self):
        import numpy as np
        path = RAMTOUCH.split(',', 1)[1] if ',' in RAMTOUCH else os.path.join(self.out or '.', 'ramtouch.npy')
        np.save(path, self._rt_mask)
        print(f'ramtouch: {int(self._rt_mask.sum())} of 2 MB bytes changed across samples -> {path}')

    def bank_of(self, entry):
        if entry not in self.banks:
            self.banks[entry] = Bank(entry, self.pf)
            self.cues[entry] = load_cues(BANK_NAMES.get(entry, ""))
        return self.banks[entry]

    def track(self):
        f, m = self.f, self.mem
        if f % 15 == 0:
            b = bank_in_ram(m)
            if b is not None and b != self.bank:
                if self.bank is not None:
                    self.bank_frames[self.bank] += f - self.bank_since
                self.log(f"{f}: bank {b} ({BANK_NAMES.get(b, '?')}) in RAM  scene={m.u16(satmem.SCENE_INDEX)}  "
                         f"[{time.time() - self.wall0:.0f}s wall]")
                self.bank, self.bank_since = b, f
                self.bank_of(b)
                if self.dec.table is None:
                    self.dec.load_table()
                if self.autosave and b not in self.auto_done:
                    self.auto_pending = (b, f)
                if os.environ.get("DUMP_LOADS"):          # a state the frame a bank is first seen (the arrival reels)
                    self.save(f"load_{BANK_NAMES.get(b, b)}_{f}")
        if self.bank is None:
            return
        self.subwatch.step()
        if f % 30 == 0:
            t = m.u32(TICK)
            if t != self.tick:
                self.tick, self.tick_at = t, f
            elif f - self.tick_at >= WEDGE_FRAMES:
                shot = self.capture("wedge")
                self.problem("WEDGE", f"{BANK_NAMES.get(self.bank)} after {self.last_pick!r}",
                             f"vblank counter stuck at {t} for {f - self.tick_at} frames; cells {[r for r in satmem.cells(m) if r]}", shot)
                self.tick_at = f
                raise Wedged()
        live = m.u8(satmem.MENU_LIVE) == 1
        # FROZEN: a menu live while object 0 still shows the payload's plain list - that list
        # draws its own glyphs, so the screen keeps our card over the engine's menu (the
        # navigator reel's last card into the Mechanic room, 2026-10-01; the cells read fine)
        blob = self.blob_addr()
        if live and blob and m.u32(satsubs.OBJ0_LIST) == m.u32(blob + 20):
            self.frozen = getattr(self, "frozen", 0) + 1
            if self.frozen == 30:
                self.problem("FROZEN", f"{BANK_NAMES.get(self.bank)} after {self.last_pick!r}",
                             "a menu is live but object 0 still draws our plain card", self.capture("frozen"))
        else:
            self.frozen = 0
        band = m.u16(BAND) == 2
        waiting = m.u8(satmem.BOX_WAIT) == 1
        cells = read_cells(m, self.dec)
        sig = tuple(tuple(c[0] for c in row[1]) for row in cells)
        if sig != self.last_cells:
            if f - self.stable_since >= CARD_SETTLE:
                self.pre_card = self.last_cells        # what the cells held before this burst
            self.last_cells, self.stable_since = sig, f
            self.last_activity = f
        stable = f - self.stable_since
        # INVISIBLE: the cells settled on new text (a card or a menu) with the box open, yet the
        # box's pixels are the same as at the previous settle - what RAM says is not on screen.
        # The cells alone read fine through the 2026-10-01 freeze (our card's sprites over the
        # Mechanic room's menu, every press running Harry's dialogue unseen).
        if stable == CARD_SETTLE and not band and any(any(c[0] for c in row[1]) for row in cells) \
                and self.emu.frame and m.u16(satsubs.BOX_Y) == 0:
            pix = hashlib.sha1(self.emu.image().crop((0, 150, 320, 232)).tobytes()).hexdigest()
            prev = getattr(self, "settle_prev", None)
            if prev and prev[0] != sig and prev[1] == pix:
                self.problem("INVISIBLE", f"{BANK_NAMES.get(self.bank)} after {self.last_pick!r}",
                             f"cells changed to {[r for r in satmem.cells(m) if r][:3]} but the box shows the same picture",
                             self.capture("invisible"))
            self.settle_prev = (sig, pix)
        if live and not band:
            if self.live_since is None:
                self.live_since = f
            if f - self.live_since >= MENU_SETTLE:
                self.on_menu(cells)
                if self.auto_pending and f - self.auto_pending[1] >= 30 and (
                        self.is_top(self.labels_now()) or f - self.auto_pending[1] > 2500):
                    self.auto_bookmark(self.auto_pending[0])
        else:
            self.live_since = None
        if not live or band:
            self.on_card(cells, stable, waiting, band)
        if self.face_watch and not self.our_card_up():
            self.face_judge()                         # our card ended (the engine's layout is back)
        elif band:
            self.face_sample()
        elif self.face_watch:
            self.face_judge()                         # the band closed: the card is over
        if band and not self.band_seen:
            self.band_seen = True
        if band and self.band_since is None:
            self.band_since = f
        elif not band:
            self.band_since = None
        dec = m.u32(VOICE_DEC)
        if dec != self.voice_dec:
            if self.voice_dec == 0 and dec:
                self.voice_lines += 1
            self.voice_dec, self.voice_changed_at = dec, f
        elif dec and f - self.voice_changed_at == BAND_DONE:
            self.voice_end_at = f               # a voice line just ended

    def auto_bookmark(self, b):
        name = f"{BANK_NAMES.get(b, str(b))}_auto"
        path = self.save(name)
        self.auto_done.add(b); self.auto_pending = None
        self.saved.append(name)

    def save(self, name):
        os.makedirs(STATES, exist_ok=True)
        path = os.path.join(STATES, f"{name}.state.gz")
        if os.path.exists(path):
            os.replace(path, path[:-9] + ".prev.state.gz")
        open(path, "wb").write(gzip.compress(self.emu.state()))
        self.last_state = path
        live, idx, cnt, labels = self.menu()
        json.dump({"frame": self.f, "menu": labels, "cells": satmem.cells(self.mem), "bank": self.bank,
                   "image": os.path.basename(self.image), "run": self.out},
                  open(path[:-9] + ".json", "w", encoding="utf-8"), ensure_ascii=False)
        self.log(f"{self.f}: saved state {name} at {labels}")
        if name not in self.saved:
            self.saved.append(name)
        return path

    # ---- the game's own save (backup RAM) ------------------------------------------
    def backup_ram(self):
        """The internal backup RAM (32,768 B, plain) out of a fresh savestate:
        Beetle Saturn exposes no SAVE_RAM (retro_get_memory_size(0) == 0) and
        writes its .bkr only at unload, but the state's MAIN/BackupRAM is live."""
        return satmem.state_ram(self.emu.state(), "BackupRAM", swap=False)

    def game_save(self, slot=1, hook=None):
        """Save through Use Metal Gear > Save from a live verb menu and come
        back to it. Closed-loop on the menus (the PS1 scripted.py's game_save),
        the flow probed from B020_auto (2026-09-15): Use Metal Gear > Save >
        'Saving your progress so far.' > B050 loads > 'Saving to internal RAM.'
        (a cart would ask Internal RAM / Cartridge RAM first) > the slot list
        '1 NO DATA' .. '4 NO DATA' / "Don't save" (a used slot shows its
        label) > 'Create a new save with this data?' or 'Erase the old data...'
        > Save / Don't save > 'Save complete. Resuming the case.' > the verb
        menu. The verdict is the backup RAM changing, never the menus.
        Returns (ok, frames, labels)."""
        before = self.backup_ram()
        f0, phase, idle, last_press, live_at, labels = self.f, "top", 0, -ADVANCE, None, []
        seen, backs = [], 0
        while self.f - f0 < 9000:
            live, idx, cnt, labels = self.menu()
            if not live:
                live_at = None
                self.run(1, hook)
                up, waiting, rows = self.box()
                if waiting and self.f - last_press >= ADVANCE:
                    self.log(f"{self.f}: bsave: card {[r for r in rows if r]} - A")
                    self.press(OK); last_press = self.f
                elif phase == "written" and not up and self.f - last_press >= IDLE_PAGE:
                    # back in the room after 'Save complete': the redrawn scene
                    # waits on the pad with no card and no menu (the B020 probe
                    # sat 9,000 frames on the ruins with the menu gone)
                    self.press(OK); last_press = self.f
                continue
            if live_at is None:
                live_at = self.f
            if self.f - live_at < MENU_SETTLE:
                self.run(1, hook)
                continue
            labels = self.labels_now()
            low = [x.lower() for x in labels]
            if labels != (seen[-1] if seen else None):
                seen.append(labels)
                self.log(f"{self.f}: bsave: menu {labels} (phase {phase})")
            if phase == "top":
                if "use metal gear" in low:
                    self.pick(low.index("use metal gear"), hook); phase = "sub"
                elif "save" in low:
                    self.pick(low.index("save"), hook); phase = "flow"
                elif backs < 2 and not any(v in low for v in ("look", "investigate", "move", "go out", "talk", "ask")):
                    # a bookmark on a submenu (a Look list, a topic list): back out to the verbs first
                    self.log(f"{self.f}: bsave: {labels} is a submenu - B")
                    self.press("b"); self.run(30, hook); backs += 1; live_at = None; seen = []
                else:
                    self.log(f"{self.f}: bsave: no Save in {labels}")
                    return False, self.f - f0, labels
            elif phase == "sub":
                if "save" in low:
                    self.pick(low.index("save"), hook); phase = "flow"
                else:
                    self.log(f"{self.f}: bsave: no Save under Use Metal Gear here ({labels})")
                    self.press(BACK); self.run(STEP_GAP, hook)
                    return False, self.f - f0, labels
            elif phase == "flow":
                if self.is_top(labels):
                    break
                if cnt == 2 and low[0] == "save":               # Save / Don't save
                    self.pick(0, hook); phase = "written"
                elif cnt >= 4 and all(x[:1] == str(i + 1) for i, x in enumerate(low[:4])):
                    self.log(f"{self.f}: bsave: slot {slot} of {labels}")
                    self.pick(slot - 1, hook)
                elif any(x.startswith("internal") for x in low):
                    self.pick(next(i for i, x in enumerate(low) if x.startswith("internal")), hook)
                elif "save" in low:
                    self.pick(low.index("save"), hook)
                else:
                    self.log(f"{self.f}: bsave: unexpected list {labels}, backing out")
                    self.press(BACK); self.run(STEP_GAP, hook)
                    return False, self.f - f0, labels
            else:
                if self.is_top(labels):
                    break
                if cnt == 2 and low[0] == "save":               # 'The save failed. Try again?'
                    self.pick(0, hook)
                else:
                    self.press(BACK); self.run(STEP_GAP, hook)
            self.run(1, hook)
        after = self.backup_ram()
        ok = after != before
        self.last_press_f = self.f
        self.log(f"{self.f}: bsave: backup RAM {'changed' if ok else 'UNCHANGED'} after {self.f - f0} frames, menu {labels}")
        return ok, self.f - f0, labels

    def bsave(self, name, slot=1, hook=None):
        """{"bsave": name, "slot": n}: the game's save from here and the backup
        RAM into the library (satsave.add). Returns the index entry."""
        import satsave
        ok, n, labels = self.game_save(slot, hook)
        raw = self.backup_ram()
        bank = BANK_NAMES.get(self.bank, str(self.bank))
        entry = satsave.add(name, raw, desc=f"harness: {bank} f{self.f}", source=self.out,
                            extra={"bank": bank, "frame": self.f, "saved": ok, "slot": slot,
                                   "image": os.path.basename(self.image)})
        self.log(f"{self.f}: bsave {entry['path']}: {len(entry['files'])} file(s) {[x['name'] for x in entry['files']]}, saved={ok}")
        return entry

    def capture(self, tag):
        d = os.path.join(PLAY, BANK_NAMES.get(self.bank, str(self.bank)))
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f"{tag}_f{self.f:06d}.png")
        if self.emu.frame:
            self.emu.image().save(p)
        return p

    def problem(self, kind, where, detail, shot=None):
        rec = dict(kind=kind, frame=self.f, bank=BANK_NAMES.get(self.bank, str(self.bank)), where=where, detail=detail, shot=shot)
        self.problems.append(rec)
        self.log(f"{self.f}: PROBLEM {kind} {where}: {detail}")

    # ---- cards ------------------------------------------------------------------------
    def bplain_addr(self):
        """The payload's `bplain` word for the loaded bank (its blob address from
        work/saturn/build/subs_layout.json; 0 when the bank has no blob)."""
        b = self.bank
        if b not in self._bplain_addr:
            addr = 0
            try:
                lay = json.load(open(satsubs.LAYOUT_JSON, encoding="utf-8"))
                blob = lay["scenes"].get(BANK_NAMES.get(b, ""), {}).get("blob")
                if blob:
                    from sh2s import Asm
                    a = Asm(blob + 0x20); a.assemble(satsubs.payload_asm(blob))
                    addr = a.labels["bplain"]
            except Exception as e:           # an older build without the layout file
                self.log(f"bplain: {e}")
            self._bplain_addr[b] = addr
        return self._bplain_addr[b]

    def bplain_now(self):
        a = self.bplain_addr()
        return bool(a) and self.mem.u32(a) == 1

    def blob_addr(self):
        """The loaded bank's blob address (0 = none), from the layout file."""
        b = self.bank
        if ("blob", b) not in self._bplain_addr:
            try:
                lay = json.load(open(satsubs.LAYOUT_JSON, encoding="utf-8"))
                self._bplain_addr[("blob", b)] = lay["scenes"].get(BANK_NAMES.get(b, ""), {}).get("blob", 0) or 0
            except Exception:
                self._bplain_addr[("blob", b)] = 0
        return self._bplain_addr[("blob", b)]

    def text_visible(self):
        """The band/box is up on screen with ink where the rows go (a ghost read of stale
        cells after the band has closed draws nothing)."""
        m = self.mem
        if m.u16(satsubs.BOX_Y) != 0 or m.u16(satsubs.BAND_STATE) != 2 or not self.emu.frame:
            return False
        img = self.emu.image().convert("L").crop((0, 150, 320, 232))
        return sum(1 for v in img.getdata() if v >= 200) >= 20

    def our_card_up(self):
        """The payload's `cur` word (blob+16): a cue pointer while our card is up."""
        a = self.blob_addr()
        return bool(a) and self.mem.u32(a + 16) != 0

    def columns(self):
        """The three face columns' base cels: (act, x, CMDSRCA base, structure buffer)."""
        out = []
        for c in range(3):
            o = satsubs.CTX + 0x830 + 76 * (1 + 3 * c)
            out.append((self.mem.u8(o), self.mem.u16(o + 8), self.mem.u16(o + 28), self.mem.u32(o + 32)))
        return out

    def vdp1_sig(self, srca):
        """Who is in the VDP1 slot a column shows: the 16 bytes at facechunks.SIG_OFF into the
        slot (CMDSRCA base * 8), read out of a savestate (the emulator maps no VRAM), named
        through the portrait chunks' signature table. None = no portrait chunk has them."""
        import facechunks
        blob = self.emu.state()
        off = 32
        vram = None
        while off + 36 <= len(blob) and vram is None:
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
                        vram = satmem.unswap(blob[p + (a & ~1):p + (a & ~1) + facechunks.SIG_LEN + 2])[a & 1:][:facechunks.SIG_LEN]
                        break
                    p += vs
            off += 36 + size
        return facechunks.char_of(vram) if vram else None

    def exown_addr(self):
        """The payload's `exown` table for the loaded bank (extras: per object 10..EX_LAST its
        column + 1), 0 when the bank has no blob or the build predates it."""
        b = self.bank
        if ("exown", b) not in self._bplain_addr:
            addr = 0
            try:
                blob = self.blob_addr()
                if blob:
                    from sh2s import Asm
                    a = Asm(blob + 0x20); a.assemble(satsubs.payload_asm(blob))
                    addr = a.labels.get("exown", 0)
            except Exception as e:
                self.log(f"exown: {e}")
            self._bplain_addr[("exown", b)] = addr
        return self._bplain_addr[("exown", b)]

    def face_sprites(self):
        """Live sprite objects past the nine face cels on a column's row or the band row (the
        room script's op 0x05 animations: the Teller's trance, Metal Gear looking left, the
        sneeze, the Cook at the bowl; #48/#55/#57/#59) and room sprites standing on the band
        (#45): [(object, off window?)] - satsubs.band_sprite_off against the owning column."""
        cols = []
        for c in range(3):
            o = satsubs.CTX + 0x830 + 76 * (1 + 3 * c)
            cols.append((self.mem.u8(o), self.mem.u16(o + 8), self.mem.u16(o + 12)))
        rows = {y for act, x, y in cols if act == 1} | {160}
        own = self.exown_addr()
        out = []
        for n in range(10, 0x85):
            o = satsubs.CTX + 0x830 + 76 * n
            if self.mem.u8(o) != 1 or self.mem.u16(o + 12) not in rows:
                continue
            owner = self.mem.u8(own + n - 10) if own and n <= satsubs.EX_LAST else 0
            out.append((n, satsubs.band_sprite_off(self.mem.u16(o + 8), self.mem.u16(o + 12), owner, cols)))
        return out

    def face_sample(self):
        """Every frame a band card with a cue is up: which columns show where, and WHO each
        one is (the slot's pixels, read once per column per card - the same slot holds
        another character in the next room)."""
        w = self.face_watch
        if not w:
            return
        rec, cue, bplain = w
        rec["frames"] = rec.get("frames", 0) + 1
        for n, off in self.face_sprites():
            d = rec.setdefault("sprites", {})                 # band sprites live under the card: {object: frames}
            d[n] = d.get(n, 0) + 1
            if off:
                d = rec.setdefault("sprites_off", {})
                d[n] = d.get(n, 0) + 1
        if bplain and not self.bplain_now():
            rec["upgraded"] = True                    # the portrait landed late: plain-in-band no more
            self.face_watch = (rec, cue, False)
        who = rec.setdefault("who", {})
        for act, x, srca, buf in self.columns():
            if act != 1:
                continue
            k = f"{srca},{buf}"                       # str keys: the record goes to cards.json
            if k not in who:
                who[k] = self.vdp1_sig(srca)
            x = satsubs.shown_x(x)                    # a column extras hid under its replacement sprite
            if x == satsubs.FACE_X:
                d = rec.setdefault("in_window", {})
                d[k] = d.get(k, 0) + 1
            elif 90 <= x <= 340:
                rec["overlap"] = rec.get("overlap", 0) + 1
                d = rec.setdefault("others", {})
                d[k] = d.get(k, 0) + 1
            else:
                d = rec.setdefault("parked", {})
                d[k] = d.get(k, 0) + 1

    def face_judge(self):
        """The band card that just ended: the portrait rule of the PS1's face-left layout -
        exactly the speaker's column in the window, or none at all for a plain-in-band
        card; never a column under the text (x 90..340)."""
        w = self.face_watch
        self.face_watch = None
        if not w:
            return
        rec, cue, bplain = w
        import facechunks
        want = facechunks.CHARS.get(cue.get("speaker") or "")     # the speaker, when a portrait chunk of theirs exists
        if not want and not cue.get("speaker"):
            want = cue.get("face_char")                            # a narrator's portrait (gen_subs.NARRATOR_FACES, #101)
        who = rec.get("who", {})
        # a column counts when it sat there for a share of the card: the next speaker's column
        # reaches the window (and the old one leaves) a few frames before the card change registers
        n = rec.get("frames", 1)
        keep = max(3, n // 5)
        name = lambda k: who.get(k) or k                           # the character in that slot, or the raw key
        # (a character set up in two columns - Harry's two B080 slots - is one portrait in the window)
        got = sorted({name(k) for k, v in rec.get("in_window", {}).items() if v >= keep})
        others = sorted(name(k) for k, v in rec.get("others", {}).items() if v >= keep)
        parked = sorted(name(k) for k, v in rec.get("parked", {}).items() if v >= keep)
        overlap = rec.get("overlap", 0) if rec.get("overlap", 0) >= keep else 0
        wantname = next((k for k, v in facechunks.CHARS.items() if v == want), None)
        if bplain:
            verdict = "plain-in-band"
        elif rec.get("upgraded") and wantname and got == [wantname]:
            verdict = "face-ok (late portrait)"
        elif wantname and got == [wantname]:
            verdict = "face-ok"
        elif not got:
            verdict = "noface"
        elif wantname and wantname not in got:
            verdict = "WRONG-FACE"
        else:
            verdict = "face?"
        # wrong: a column under the text; a plain-in-band card while a column shows (or while the
        # speaker's portrait sits parked - it should be in the window); the speaker known and
        # another face in the window, or none at all
        bad = bool(overlap) or (bplain and (got or (wantname and wantname in parked)))             or (wantname and got and got != [wantname]) or (not got and not bplain)
        off = {n: v for n, v in rec.get("sprites_off", {}).items() if v >= keep}   # a face-buffer sprite neither in the window nor away (#48)
        if off:
            verdict += " SPRITE-OFF-WINDOW"
            bad = True
        detail = (f"{verdict} want={wantname} in_window={got} others={others} parked={parked} text-over-face={overlap} frames"
                  + (f" sprites={rec['sprites']}" if rec.get("sprites") else "") + (f" sprites_off={off}" if off else ""))
        rec["face"] = detail
        where = f"{BANK_NAMES.get(self.bank)} cue {cue['id']} card {rec['n']}"
        self.log(f"{self.f}: face {cue['id']}: {detail}")
        if bad:
            self.problem("FACE", where, detail, rec.get("shot"))
            rec["problems"].append("FACE")

    def face_layout(self, cells):
        """The engine's face-band text (portrait at the left, text from col 6):
        no flag marks it, but cols 0-5 keep whatever was there (labels, an
        older card - hidden behind the portrait) while the text lands at
        col 6. True when every text row's cols 0-5 are blank or the
        pre-card residue and some row has new text past col 6."""
        pre = self.pre_card
        new6, plain = False, False
        for r, row in enumerate(cells):
            cl = row[1]
            if not any(c[2] != "blank" for c in cl):
                continue
            prev = pre[r] if pre else None
            for c in range(6):
                if cl[c][2] != "blank" and (prev is None or cl[c][0] != prev[c]):
                    plain = True
            if any(cl[c][2] != "blank" and (prev is None or cl[c][0] != prev[c]) for c in range(6, len(cl))):
                new6 = True
        return new6 and not plain

    def on_card(self, cells, stable, waiting, band):
        band = band or self.face_layout(cells)
        rows = [r[0] for r in cells]
        if band:
            # the band keeps the verb labels (or an older card) in cols 0-5 behind
            # the portrait; the text is cols 6-19, rows 0-2
            cellrows = [r[1][6:] for r in cells[satsubs.ROW0:satsubs.ROW0 + satsubs.ROWS]]
            if self.bplain_now():          # plain-in-band: nameplate + rows from column 0
                cellrows = [r[1] for r in cells]
            rows = ["".join(c[1] for c in r) for r in cellrows]
        else:
            cellrows = [r[1] for r in cells]
        rows = [r.rstrip() for r in rows]
        if not any(rows):
            return
        key = tuple(rows)
        if key == self.card_key:
            if self.card_logged_at < self.stable_since:
                # the same text typed on again (Mika's 'not finished yet' twice
                # over): a card in its own right, or the pilot never presses
                self.card_logged_at = self.stable_since
                self.log(f"{self.f}: card (repeat) {[r for r in rows if r]}")
            return
        if stable < CARD_SETTLE and not waiting:
            return
        if not band and rows[0] and not any(rows[1:]) and squash(rows[0]) in self.names and not waiting:
            return                          # the nameplate lands first; the text follows
        pre = self.pre_card
        if pre and not waiting and all(c[2] == "blank" or c[0] == pre[r][i] for r, row in enumerate(cells) for i, c in enumerate(row[1])):
            return                          # nothing new was written (a partial clear)
        self.face_judge()                         # the card before this one
        self.card_key, self.card_logged_at = key, self.f
        self._n += 1
        n = self._n
        bank = self.bank_of(self.bank)
        self.bank_cards[self.bank] += 1
        name = None
        text_rows = [r for r in rows if r]
        if not band and rows[0] and squash(rows[0]) in self.names:
            name, text_rows = rows[0].strip(), [r for r in rows[1:] if r]
        elif not band and rows[0] and squash(rows[0]) in bank.by_key and len(rows[0].strip()) <= 12 and \
                any(r for r in rows[1:]) and squash("".join(rows[1:])) in bank.by_key:
            name, text_rows = rows[0].strip(), [r for r in rows[1:] if r]
        cues_here = self.cues.get(self.bank, {})
        cue = cues_here.get(squash("".join(text_rows))) if band else None
        if not cue and text_rows:
            # our plain box and plain-in-band cards: a nameplate row, then the cue's rows
            cue = cues_here.get(squash("".join(text_rows)))
            if not cue and len(text_rows) > 1:
                cue = cues_here.get(squash("".join(text_rows[1:])))
                if cue:
                    name, text_rows = text_rows[0].strip(), text_rows[1:]
        if cue:
            cue = self.subwatch.exact(cue, band)
        hits = [] if cue else bank.match(text_rows)
        if band and not cue and not hits:
            prev = self.cards[-1]["rows"] if self.cards else []
            labs = list(self.menu_key or ())
            if len(squash("".join(text_rows))) <= 3 or all(any(squash(r) and squash(r) in squash(p) for p in prev) for r in text_rows if r)                     or all(any(squash(r) and squash(r) in squash(l) for l in labs) for r in text_rows if r):
                return                      # the previous card's tail left beside a fresh band
        shot = self.capture(f"card{n:04d}")
        tag = f"card {n}"
        src = (f"cue {cue['id']}" if cue else
               ("off " + "+".join(str(s["off"]) for s in hits) if hits else "UNMATCHED"))
        self.log(f"{self.f}: {tag} {'[band] ' if band else ''}{('<' + name + '> ') if name else ''}{text_rows}  ({src}, wait={int(waiting)}, "
                 f"mode={self.mem.u8(WINDOW_MODE)})")
        rec = dict(n=n, frame=self.f, bank=BANK_NAMES.get(self.bank), name=name, rows=text_rows, band=band,
                   src=src, shot=os.path.relpath(shot, ROOT), problems=[])
        self.cards.append(rec)
        if cue:
            self.subwatch.on_card(rec, cue)
        if band and cue:
            self.face_watch = (rec, cue, self.bplain_now())
        # ---- checks on the cells ----
        kinds = collections.Counter(c[2] for row in cellrows for c in row)
        jp = [c[1] for row in cellrows for c in row if c[2] == "jp"]
        blank0 = [f"{c[0]:04x}" for row in cellrows for c in row if c[2] == "blank0"]
        garbage = [f"{c[0]:04x}" for row in cellrows for c in row if c[2] == "garbage"]
        has_en = any(s["has_en"] for s in hits) if hits else None
        where = f"{BANK_NAMES.get(self.bank)} {src} {tag}"
        if jp:
            if cue or has_en:
                self.problem("JP", where, f"Japanese in a translated string: {''.join(jp)!r} in {text_rows}", shot); rec["problems"].append("JP")
            elif hits:
                why = "over budget (satapply kept the Japanese)" if any(s["off"] in bank.over for s in hits) else "no en"
                self.problem("untranslated", where, f"{why}: {text_rows}", shot); rec["problems"].append("untranslated")
            else:
                self.problem("JP?", where, f"Japanese, no string matched: {text_rows}", shot); rec["problems"].append("JP?")
        if blank0:
            self.problem("BLANK", where, f"codes {blank0} draw slot 0 (blank) in {text_rows}", shot); rec["problems"].append("BLANK")
        if garbage:
            self.problem("GARBAGE", where, f"undecodable codes {garbage} in {text_rows}", shot); rec["problems"].append("GARBAGE")
        if not hits and not cue and not name and any(k == "pair" for k in kinds):
            # in the band only the payload writes text: a band card no cue accounts for is ours, drawn wrong
            if band and not self.text_visible():
                # cells read while the band is off screen: B130_r_08, where the script slides the
                # band out and back in at the speaker change (the pristine game too) and the
                # payload's plain re-wrap of the card sat in the cells for the frames the box was
                # parked - nothing of it on screen (the capture shows no box)
                self.log(f"{self.f}: card {n} is stale cells under a closed band (not on screen) - not flagged")
            else:
                kind = "UNMATCHED-BAND" if band and not self.bplain_now() and self.text_visible() else "UNMATCHED"
                self.problem(kind, where, f"{text_rows}", shot); rec["problems"].append(kind)
        # width: the source rows through the pair font against the box
        width = TERM_W if self.mem.u8(WINDOW_MODE) == 7 else BOX_W
        for s in hits:
            if s["off"] in self.width_flagged:
                continue
            wide = [(COLOUR_RE.sub("", r), bank.width(r)) for r in s["raw_rows"] if bank.width(r.rstrip(" 　")) > width]
            if wide:
                self.width_flagged.add(s["off"])
                self.problem("WIDE", where, f"row(s) over {width} cells: {wide}", shot); rec["problems"].append("WIDE")
            if s["has_en"] and len([r for r in s["rows"] if r]) > (3 if name else 4) and width == BOX_W:
                pass   # the engine scrolls row 4; not a defect by itself
        # a row full to the last cell with no space at the end: the source ran past the box
        # (not a subtitle card: satsubs wrapped it to fit - the 20-cell wide rows fill the box)
        for r in ([] if cue else cellrows):
            if r and r[-1][2] not in ("blank",) and len(r) >= width:
                last = r[-1][1]
                if not last.endswith((" ", ".", "!", "?", ",")) and r[-1][2] == "pair":
                    self.problem("FULL", where, f"row fills all {width} cells: {''.join(c[1] for c in r)!r}", shot); rec["problems"].append("FULL")
                    break
        for s in hits:
            if s["has_en"] and ("pad", s["off"]) not in self.width_flagged:
                pd = pads(s["en"])
                if pd:
                    self.width_flagged.add(("pad", s["off"]))
                    self.problem("PAD", where, f"pad space before a colour code: {pd} in {s['en']!r}", shot); rec["problems"].append("PAD")
        fb = kinds.get("fw", 0)
        if fb:
            k2 = tuple(s["off"] for s in hits) or squash("".join(text_rows))
            if k2 not in self.fallback_flagged:
                self.fallback_flagged.add(k2)
                fbs = "".join(c[1] for row in cellrows for c in row if c[2] == "fw")
                self.log(f"{self.f}: fallback letters ({fb}) {fbs!r} in {text_rows}")
                rec["fallback"] = fbs

    # ---- menus ----------------------------------------------------------------------
    def on_menu(self, cells):
        live, idx, cnt, _ = self.menu()
        if not cnt:
            return
        flat = [c for row in cells for c in row[1]]
        labels = []
        for i in range(min(cnt, 8)):
            s = satmem.MENU_STARTS[i]
            labels.append("".join(c[1] for c in flat[s:s + LABEL_W]).rstrip())
        key = tuple(labels)
        if key == self.menu_key:
            return
        self.menu_key = key
        self.bank_menus[self.bank] += 1
        if (self.bank, key) in self.menus_seen:
            self.log(f"{self.f}: menu {labels} (seen)")
            return
        self.menus_seen.add((self.bank, key))
        n = len(self.menus) + 1
        shot = self.capture(f"menu{n:04d}")
        self.menus.append(dict(n=n, frame=self.f, bank=BANK_NAMES.get(self.bank), labels=labels, shot=os.path.relpath(shot, ROOT)))
        self.log(f"{self.f}: menu {n} {labels}")
        bank = self.bank_of(self.bank)
        where = f"{BANK_NAMES.get(self.bank)} menu {n}"
        for i, lab in enumerate(labels):
            s = satmem.MENU_STARTS[i]
            cl = flat[s:s + LABEL_W]
            jp = [c[1] for c in cl if c[2] == "jp"]
            if jp:
                hit = bank.by_key.get(squash(lab))
                kind = "untranslated" if hit and not hit["has_en"] else "JP"
                self.problem(kind, where, f"label {i} {lab!r}", shot)
            if any(c[2] == "blank0" for c in cl):
                self.problem("BLANK", where, f"label {i} {lab!r} has a slot-0 code", shot)
            if any(c[2] == "garbage" for c in cl):
                self.problem("GARBAGE", where, f"label {i} {lab!r}", shot)
            # the label's full text: a string whose key starts with what the 10 cells hold
            k = squash(lab)
            full = bank.by_key.get(k)
            if full is None and len(k) >= 6:
                cands = [s2 for k2, s2 in bank.by_key.items() if k2.startswith(k) and len(s2["rows"]) == 1]
                full = min(cands, key=lambda s2: len(s2["key"])) if cands else None
            if full and full["rows"]:
                w = bank.width(full["rows"][0])
                if w > LABEL_W:
                    self.problem("LABEL", where, f"label {i} {full['rows'][0]!r} is {w} cells (10 per item); cells show {lab!r}"
                                 + (f"; item {i + 4} slot reads {labels[i + 4]!r}" if i + 4 < len(labels) else ""), shot)
            elif cl[-1][2] != "blank":
                nxt = flat[s + LABEL_W:s + LABEL_W + 4] if s + LABEL_W + 4 <= len(flat) else []
                spill = "".join(c[1] for c in nxt).rstrip()
                if i < 4 and i + 4 >= cnt and spill:      # the right slot is empty, yet something sits there
                    self.problem("LABEL", where, f"label {i} {lab!r} fills its 10 cells and {spill!r} follows", shot)

    # ---- closed-loop steps ------------------------------------------------------------
    def menu(self):
        live, idx, cnt, labels = super().menu()
        if live and self.mem.u16(BAND) == 2:
            return False, idx, 0, []           # the band keeps the byte at 1
        return live, idx, cnt, labels

    def labels_now(self):
        live, idx, cnt, _ = self.menu()
        if not live:
            return []
        flat = [c for row in read_cells(self.mem, self.dec) for c in row[1]]
        return ["".join(c[1] for c in flat[s:s + LABEL_W]).rstrip() for s in satmem.MENU_STARTS[:min(cnt, 8)]]

    def wait_menu(self, patience=PATIENCE, hook=None, hold_after_card=None):
        """Run until a menu is live and settled; A advances a card once it has
        been read (the settled frame captured). Returns (live, idx, count,
        labels) or None on timeout; a long idle gets a blind A (a screen that
        waits on the pad with no card)."""
        hold = HOLD_CARD if hold_after_card is None else hold_after_card
        start, wait_since = self.f, None
        while self.f - start < patience:
            self.run(1, hook)
            live, idx, cnt, labels = self.menu()
            if live:
                if self.live_since is not None and self.f - self.live_since >= MENU_SETTLE:
                    labels = self.labels_now()
                    if labels[:2] == ["Continue", "Quit game"] and not self.in_death:
                        # Gillian died: the retry replays the same shootout, so the
                        # per-fight aim list must not advance (five deaths at the
                        # morgue's snatcher walked the list to 'cell6' for its head)
                        # The native retry list can remain live after confirmation.
                        # Count it once until another shootout actually begins.
                        if not self.death_counted:
                            self.death_counted = True
                            self.deaths += 1
                            self.fights = max(self.fights - 1, 0)
                            self.log(f"{self.f}: DEATH {self.deaths} - Continue (fight {self.fights + 1} again)")
                            self.problem("DEATH", f"shootout {self.fights + 1}", f"death {self.deaths}", self.capture("death"))
                        if self.deaths > MAX_DEATHS:
                            self.log(f"{self.f}: {self.deaths} deaths - giving the shootout up")
                            raise GaveUp(f"{self.deaths} deaths at shootout {self.fights + 1}")
                        self.in_death = True            # pick() waits on wait_menu itself: no re-entry
                        try:
                            self.pick(0)
                            gone = 0
                            for _ in range(600):        # the pick takes ~30 frames; the list must go
                                self.run(1, hook)
                                gone = gone + 1 if self.mem.u8(satmem.MENU_LIVE) != 1 else 0
                                if gone >= 30:
                                    break
                        finally:
                            self.in_death = False
                        self.live_since = None
                        start = self.f
                        continue
                    return live, idx, cnt, labels
                continue
            waiting = self.mem.u8(satmem.BOX_WAIT) == 1
            if (self.f % 5 == 0 or self.in_fight) and self.fight_step():
                start = self.f
                continue
            if waiting:
                wait_since = wait_since if wait_since is not None else self.f
                if (self.f - wait_since >= hold and self.f - self.last_press_f >= ADVANCE
                        and self.card_logged_at >= self.stable_since - 1):
                    self.press(OK); self.last_press_f = self.f; wait_since = None
                    self.last_activity = self.f
                    start = self.f              # a card advanced is progress: patience restarts
            else:
                wait_since = None
                if (self.f - self.stable_since >= IDLE_PAGE and self.f - self.voice_changed_at >= IDLE_PAGE
                        and self.f - self.last_press_f >= IDLE_PAGE and self.card_logged_at >= self.stable_since - 1
                        and self.f - self.start_nudged > 60):
                    # Gaudi's terminal pages, Metal Gear's analysis screens, a
                    # picture with the faces up: they wait on the pad with no
                    # flag. A press after the settled capture is what a player does.
                    self.idle_presses += 1
                    if self.idle_presses % 5 == 1:
                        self.log(f"{self.f}: idle {IDLE_PAGE} frames (band={self.mem.u16(BAND)}) - A")
                    self.press(OK); self.last_press_f = self.f
                    start = self.f
                    continue
                if (self.voice_end_at is not None and self.voice_end_at > self.last_press_f
                        and self.f - self.last_press_f >= ADVANCE and self.f - self.stable_since >= CARD_SETTLE
                        and self.card_logged_at >= self.stable_since - 1):
                    # a voiced line (under the band, or Gibson on the videophone)
                    # shows no text and sets no wait flag: once the decoder sits
                    # still the line is over and the engine waits for a press
                    self.log(f"{self.f}: voice line over (dec {self.voice_dec}, band={int(self.band_since is not None)}) - A")
                    self.press(OK); self.last_press_f = self.f; self.last_activity = self.f
                    self.voice_end_at = None
                    start = self.f
                    continue
                if (self.f - self.last_activity > START_NUDGE and self.f - self.start_nudged > NUDGE * 4
                        and self.f - self.last_press_f >= ADVANCE):
                    # a screen that waits on the pad with no card and no voice:
                    # the shootout's "press START to draw the Blaster" is the one
                    # the game names, so START goes first (A/C confirm only)
                    self.start_nudged = self.f
                    self.log(f"{self.f}: nothing for {START_NUDGE} frames (band={self.mem.u16(BAND)}, cells={[r for r in satmem.cells(self.mem) if r]}) - START")
                    self.capture("start")
                    self.save(f"start_{BANK_NAMES.get(self.bank, 'x')}_{self.f}")
                    self.press("start"); self.last_press_f = self.f
                    continue
                if self.f - self.last_activity > NUDGE and self.f - self.last_nudge > NUDGE:
                    self.last_nudge = self.f
                    self.nudges += 1
                    self.log(f"{self.f}: nothing for {NUDGE} frames (band={self.mem.u16(BAND)}, cells={[r for r in satmem.cells(self.mem) if r]}) - A")
                    self.capture("idle")
                    if self.nudges <= 3:
                        self.save(f"stall_{BANK_NAMES.get(self.bank, 'x')}_{self.f}")
                    self.press(OK); self.last_press_f = self.f; self.last_activity = self.f
        return None

    # ---- the shootout ----------------------------------------------------------------
    # The Saturn fight is the PS1's: a 3x3 grid over the picture (x 48..284,
    # y 18..142 in the 330x240 frame), the crosshair (a green ring) parks in a
    # cell while a direction is HELD, the insector is the yellow blob, a LIFE
    # bar sits below (its yellow label at x < 70, y 150..180 is the fight
    # signal - up from the "press START" prompt on). START draws the Blaster
    # (the grid and the crosshair appear), A fires. Measured on
    # work/saturn/play/probe_fight/*.png (2026-09-12).
    GRID_X, GRID_Y = (48, 126, 204, 284), (18, 59, 100, 142)

    def fight_step(self):
        """Drive the shootout from the picture; True while one is on."""
        import numpy as np
        if self.f % 5 == 0 or self.fight_view is None:
            a = np.asarray(self.emu.image().convert("RGB")).astype(int)
            R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
            label = int(((R > 150) & (G > 120) & (B < 90))[150:180, 0:70].sum())
            gy0, gy1, gx0, gx1 = self.GRID_Y[0], self.GRID_Y[-1], self.GRID_X[0], self.GRID_X[-1]
            # the Blaster drawn = its 3x3 grid, dark green lines (0, 108, 43) on columns
            # 125/126 and 203/204 and rows 60/61 and 100/101 (measured 2026-09-17 with
            # START pressed at the morgue's snatcher); a count of any green in the picture
            # read the morgue's green walls as the grid and never drew it (five deaths)
            line = (G > 70) & (R < 50) & (B < 90)
            g = (line[gy0:gy1, 125:127].sum() + line[gy0:gy1, 203:205].sum()
                 + line[60:62, gx0:gx1].sum() + line[100:102, gx0:gx1].sum())
            g = np.zeros((1, 1), bool) if g < 250 else np.ones((100, 1), bool)
            y = ((R > 150) & (G > 100) & (B < 90) & (R >= G))[gy0:gy1, gx0:gx1]
            ys, xs = np.nonzero(y)
            enemy = (int(xs.mean()) + gx0, int(ys.mean()) + gy0) if len(xs) >= 8 else None
            # the church's super insectors are olive green (96, 126, 45), not yellow: the
            # cell holding most of them is the target (188 px each, 0 on an empty frame;
            # measured 2026-09-17, work/saturn/auto/church_fight3.png)
            ins = (G > 100) & (G > R + 20) & (G > B + 40) & (R > 60)
            best, bestn = None, 40
            for r in range(3):
                for c in range(3):
                    n = int(ins[self.GRID_Y[r]:self.GRID_Y[r + 1], self.GRID_X[c]:self.GRID_X[c + 1]].sum())
                    if n > bestn:
                        best, bestn = (r, c), n
            if best is not None:
                r, c = best
                enemy = ((self.GRID_X[c] + self.GRID_X[c + 1]) // 2, (self.GRID_Y[r] + self.GRID_Y[r + 1]) // 2)
            # the Act 2 finale: the snatcher holds Mika (pink, centre) and its brown head
            # peeks into a CORNER cell - brown pixels per corner (516 at the top right when
            # it shows, 0 otherwise; measured 2026-09-17, work/saturn/auto/final_fight.png)
            brown = (R > 90) & (R < 210) & (G > 55) & (G < 160) & (B < 110) & (R > G + 15) & (G > B)
            corners = {}
            for (r, c) in ((0, 0), (0, 2), (2, 0), (2, 2)):
                corners[(r, c)] = int(brown[self.GRID_Y[r]:self.GRID_Y[r + 1], self.GRID_X[c]:self.GRID_X[c + 1]].sum())
            # the church's snatcher horde: grey bodies (R~G~B, 110..230) on the dark blue;
            # the head is the topmost grey cell - per cell counts (the left one's head 171
            # in the middle-left cell over its body's 103; measured 2026-09-17)
            grey = (np.abs(R - G) < 28) & (np.abs(G - B) < 28) & (R > 110) & (R < 230)
            greys = {}
            for r in range(3):
                for c in range(3):
                    greys[(r, c)] = int(grey[self.GRID_Y[r]:self.GRID_Y[r + 1], self.GRID_X[c]:self.GRID_X[c + 1]].sum())
            self.fight_view = (label, int(g.sum()), enemy, corners, greys)
        label, green, enemy, corners, greys = self.fight_view
        if label < 500:
            if self.in_fight:
                self.log(f"{self.f}: shootout over")
                self.in_fight = False; self.emu.held = set(); self.held_until = -1
                self.capture("fight_end")
            return False
        if not self.in_fight:
            self.death_counted = False
            self.in_fight, self.fight_since, self.fights = True, self.f, self.fights + 1
            self.log(f"{self.f}: shootout {self.fights}")
            self.capture("fight_start")
            self.save(f"{BANK_NAMES.get(self.bank)}_fight")
        if green < 100:
            # the Blaster is holstered: START draws it (the game's own prompt)
            if self.f - self.last_press_f > 40:
                self.press("start"); self.last_press_f = self.f
            return True
        aim0 = self.fight_state
        if isinstance(aim0, list):
            aim0 = aim0[min(self.fights - 1, len(aim0) - 1)]
        if aim0 == "hold":
            # the church's last battle: never fire (guides/ps1.txt: 'don't fire at all')
            self.emu.held = set(); self.held_until = -1
            return True
        if aim0 == "horde":
            # snatchers take head shots: the topmost row holding a grey cell, its fullest cell
            # Small, distant heads contain only 21..80 bright grey pixels.
            # Waiting for 80 aimed at their brighter bodies and missed them.
            cand = [(rc, n) for rc, n in greys.items() if n > 20]
            if not cand:
                self.emu.held = set(); self.held_until = -1
                return True
            top = min(rc[0] for rc, n in cand)
            (r, c), n = max(((rc, n) for rc, n in cand if rc[0] == top), key=lambda kv: kv[1])
            dirs = set()
            if r == 0: dirs.add("up")
            if r == 2: dirs.add("down")
            if c == 0: dirs.add("left")
            if c == 2: dirs.add("right")
            fire = (self.f // 3) % 2 == 0
            self.emu.held = {satrun.BTN[d] for d in dirs} | ({satrun.BTN[OK]} if fire else set())
            self.held_until = -1
            if (self.f - self.fight_since) % 100 == 0:
                self.log(f"{self.f}: fight: horde head {(r, c)} grey {n} hold {sorted(dirs)}")
            return True
        if aim0 == "corners":
            # fire only at a corner the snatcher's head is in; hitting Mika loses the game
            cell, n = max(corners.items(), key=lambda kv: kv[1])
            if n < 80:
                self.emu.held = set(); self.held_until = -1
                return True
            r, c = cell
            dirs = set()
            if r == 0: dirs.add("up")
            if r == 2: dirs.add("down")
            if c == 0: dirs.add("left")
            if c == 2: dirs.add("right")
            fire = (self.f // 3) % 2 == 0
            self.emu.held = {satrun.BTN[d] for d in dirs} | ({satrun.BTN[OK]} if fire else set())
            self.held_until = -1
            if (self.f - self.fight_since) % 100 == 0:
                self.log(f"{self.f}: fight: corner {cell} brown {n} hold {sorted(dirs)}")
            return True
        if enemy is None:
            self.emu.held = set(); self.held_until = -1
            return True
        ex, ey = enemy
        c = next((i for i in range(3) if ex < self.GRID_X[i + 1]), 2)
        r = next((i for i in range(3) if ey < self.GRID_Y[i + 1]), 2)
        aim = self.fight_state or "body"
        if isinstance(aim, list):
            # one aim per shootout, in order (the PS1's B200: the snatcher takes the
            # head first and the abdomen in its second fight); the last covers the rest
            aim = aim[min(self.fights - 1, len(aim) - 1)]
        if isinstance(aim, str) and aim.startswith("cell"):
            r, c = divmod(int(aim[4:]), 3)
        elif aim == "head":
            r = max(r - 1, 0)               # the cell above the body's centroid
        elif aim == "top-middle":
            r, c = 0, 1
        dirs = set()
        if r == 0: dirs.add("up")
        if r == 2: dirs.add("down")
        if c == 0: dirs.add("left")
        if c == 2: dirs.add("right")
        fire = (self.f // 3) % 2 == 0
        self.emu.held = {satrun.BTN[d] for d in dirs} | ({satrun.BTN[OK]} if fire else set())
        self.held_until = -1                    # held across frames, not a tap
        if (self.f - self.fight_since) % 100 == 0:
            self.log(f"{self.f}: fight: enemy at ({ex},{ey}) cell {r},{c} hold {sorted(dirs)}")
        return True

    def find(self, labels, want):
        w = want.strip().lower()
        for alt in [x.strip().lower() for x in w.split("|")]:
            for i, lab in enumerate(labels):
                if lab.lower() == alt:
                    return i
            for i, lab in enumerate(labels):
                low = lab.lower()
                if low and (alt.startswith(low) or low.startswith(alt)):
                    return i
        return None

    def is_top(self, labels):
        n = sum(x.lower() in VERBS for x in labels)
        lower = {x.lower() for x in labels}
        stairs_root = {"peek", "investigate", "use metal gear"}.issubset(lower)
        tunnel_root = {"investigate", "move"}.issubset(lower) and lower <= {"investigate", "move", "press button"}
        fork_root = len(lower) >= 2 and lower <= {"go straight", "turn right", "turn left", "back"}
        return n >= 3 or stairs_root or tunnel_root or fork_root or (bool(labels) and labels == self.top_labels)

    def ensure_top(self, hook=None, tries=2):
        """Back out (B) of a submenu left live - a bookmark saved on an Ask topic list
        (B010_toured, 2026-09-16: every verb 'not offered' in ['Navigator', 'Blaster',
        'Snatchers', 'Wall photo'] and the route fell through) - until a verb menu is up."""
        for _ in range(tries):
            got = self.wait_menu(hook=hook)
            if got is None or self.is_top(got[3]) or any(x.lower() in VERBS for x in got[3]):
                return
            self.log(f"{self.f}: {got[3]} is a submenu - B")
            self.press(BACK); self.run(STEP_GAP, hook)

    def pick(self, want, hook=None):
        """Move the cursor to the label (or index) and confirm; True when the
        menu changed. Returns (ok, labels_before)."""
        got = self.wait_menu(hook=hook)
        if got is None:
            return False, []
        live, idx, cnt, labels = got
        ti = want if isinstance(want, int) else self.find(labels, want)
        if ti is None or ti >= cnt:
            return False, labels
        steps = 0
        while idx != ti:
            down = (ti - idx) % cnt
            self.press("down" if down <= cnt - down else "up")
            self.run(STEP_GAP, hook)
            live, idx, cnt, _ = self.menu()
            steps += 1
            if not live or steps > 3 * cnt + 4:
                self.log(f"{self.f}: cursor stuck at {idx}, wanted {ti} ({want!r})")
                return False, labels
        for attempt in range(3):
            self.press(OK); self.last_press_f = self.f
            for _ in range(90):
                self.run(1, hook)
                live, idx2, cnt2, _ = self.menu()
                if not live or (self.live_since is not None and self.f - self.live_since >= MENU_SETTLE and self.labels_now() != labels):
                    self.log(f"{self.f}: picked {labels[ti]!r} (index {ti})")
                    self.last_pick = labels[ti]
                    return True, labels
        self.log(f"{self.f}: confirm on {labels[ti]!r} never took")
        return False, labels

    def do_path(self, path, optional=False, patience=PATIENCE, hook=None):
        """Descend menus by label. Returns True when every step took."""
        start = self.f
        depth = 0
        while depth < len(path):
            got = self.wait_menu(patience=patience, hook=hook)
            if got is None:
                self.log(f"{self.f}: {path[depth]!r} never offered - {path} {'skipped' if optional else 'MISSED'}")
                return False
            labels = got[3]
            top = self.is_top(labels)
            if top and depth == 0:
                self.top_labels = labels
            ti = self.find(labels, path[depth])
            if ti is None:
                ahead = next((d for d in range(depth + 1, len(path)) if self.find(labels, path[d]) is not None), None)
                if ahead is not None and not top:
                    depth = ahead; continue       # a persistent menu (the room list, Gaudi's entries): the steps before are behind us
                if depth > 0 and top:
                    self.log(f"{self.f}: {path[depth - 1]!r} needed no submenu; {path[depth:]} not applicable ({labels})")
                    return True
                if self.f - start < patience:
                    if not top:
                        back = self.find(labels, "Back to menu")
                        if back is not None and self.find(labels, path[depth]) is None:
                            self.pick(back, hook)          # Gaudi's lists leave only by their own item
                        else:
                            self.press(BACK); self.run(STEP_GAP, hook)
                    else:
                        self.run(30, hook)
                    continue
                self.log(f"{self.f}: MISS {path[depth]!r} in {labels} ({path})")
                return False
            ok, before = self.pick(ti, hook)
            if not ok:
                if self.f - start < patience:
                    continue
                self.log(f"{self.f}: MISS confirm {path[depth]!r} ({path})")
                return False
            depth += 1
        return True

    def sweep(self, verbs, rounds=1, avoid=(), each=None, each_rounds=1, hook=None, depth_limit=3):
        """Luiz's method: open each verb and pick every item it offers, `rounds`
        times; items that appear later are caught by later rounds. A pick that
        opens a further submenu is swept the same way (Item > Use > Key)."""
        avoid = AVOID | {x.lower() for x in avoid}
        self.log(f"{self.f}: sweep {verbs} x{rounds}")
        for rnd in range(rounds):
            seen = {}
            for verb in verbs:
                self.sweep_path([verb], seen, avoid, each, each_rounds, hook, depth_limit)

    def sweep_path(self, prefix, seen, avoid, each, each_rounds, hook, depth_limit):
        got = self.wait_menu(patience=PATIENCE, hook=hook)
        if got is None:
            self.log(f"{self.f}: no menu for sweep step {prefix}"); return
        labels = got[3]
        for attempt in range(3):
            if self.find(labels, prefix[-1]) is not None or len(prefix) > 1 or self.is_top(labels):
                break
            # a submenu left open (Item > Use > Key's one-item list): back out first
            back = self.find(labels, "Back to menu")
            if back is not None:
                self.pick(back, hook)
            else:
                self.press(BACK); self.run(STEP_GAP, hook)
            got = self.wait_menu(patience=PATIENCE, hook=hook)
            if got is None:
                return
            labels = got[3]
        if self.find(labels, prefix[-1]) is None and len(prefix) == 1:
            self.log(f"{self.f}: {prefix[0]!r} not offered in {labels}"); return
        top_before = self.top_labels or labels
        pre = self.emu.state()
        try:
            if not self.do_path(prefix, optional=True, patience=PATIENCE if len(prefix) == 1 else 900, hook=hook):
                return
            got = self.wait_menu(patience=PATIENCE, hook=hook)
        except Wedged:
            self.log(f"{self.f}: WEDGED after {prefix} - restoring the state before the pick")
            self.emu.restore(pre); self.emu.held = set(); self.held_until = -1
            self.tick = None; self.last_cells = None
            self.run(2, hook)
            return
        if got is None:
            return
        labels = got[3]
        if self.is_top(labels) or len(prefix) >= depth_limit:
            if each and len(prefix) > 1 and self.is_top(labels):
                # a room was entered: sweep it before the next
                self.sweep(each, each_rounds, avoid, None, 1, hook)
            return
        known = seen.setdefault(tuple(prefix), set())
        new = [x for x in labels if x and x not in known and x.lower() not in avoid]
        known.update(new)
        self.log(f"{self.f}: {prefix} offers {labels} -> {len(new)} picks")
        self.press(BACK); self.run(STEP_GAP, hook)
        for item in new:
            self.sweep_path(prefix + [item], seen, avoid, each, each_rounds, hook, depth_limit)

    # ---- the report -----------------------------------------------------------------
    def finish(self, t0):
        if self.bank is not None:
            self.bank_frames[self.bank] += self.f - self.bank_since
        dt = time.time() - t0
        self.subwatch.finish()
        self.log(f"---- summary: {self.f} frames, {dt:.0f}s wall, {self.f / max(dt, 1):.0f} fps overall ----")
        for b in sorted(self.bank_frames):
            self.log(f"  {BANK_NAMES.get(b)}: {self.bank_frames[b]} frames, {self.bank_cards[b]} cards, {self.bank_menus[b]} menus, "
                     f"{sum(1 for p in self.problems if p['bank'] == BANK_NAMES.get(b))} problems")
        kinds = collections.Counter(p["kind"] for p in self.problems)
        self.log(f"  problems: {dict(kinds)}; bookmarks: {self.saved}; nudges {self.nudges}")
        json.dump(dict(cards=self.cards, menus=self.menus, problems=self.problems, saved=self.saved,
                       frames=self.f, wall=dt, bank_frames={BANK_NAMES.get(b): n for b, n in self.bank_frames.items()}),
                  open(os.path.join(self.out, "cards.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        with open(os.path.join(self.out, "problems.txt"), "w", encoding="utf-8") as fh:
            for p in self.problems:
                fh.write(f"{p['frame']} {p['bank']} {p['kind']} {p['where']}: {p['detail']}  [{p['shot']}]\n")


def run_route(route, play, frames, log, state=None, new=False):
    actions = list(route["actions"])
    if state:
        path = os.path.join(STATES, f"{state}.state.gz")
        play.emu.restore(gzip.decompress(open(path, "rb").read()))
        play.restored = True
        meta = json.load(open(path[:-9] + ".json", encoding="utf-8")) if os.path.exists(path[:-9] + ".json") else {}
        play.f = meta.get("frame", 0)
        log(f"{play.f}: restored {state} ({meta.get('image', '?')})")
        if satmem.refresh_chunk_table(play.mem, image=play.image):
            log(f"{play.f}: chunk table refreshed from the image's MAIN_L.BIN (the bookmark's build differs)")
        play.run(2)
        for _ in range(60):                    # track() reads the bank every 15 frames
            if play.bank is not None:
                break
            play.run(1)
        play.auto_done.add(play.bank)          # the bookmark's bank was reached before this run
        if play.bank is not None and not os.environ.get("NO_INJECT"):
            try:                                # the current build's subtitle blob into the resumed bank
                satsubs.inject_blob(play.mem, BANK_NAMES.get(play.bank, ""), lambda t: log(f"{play.f}: {t}"))
            except Exception as e:
                log(f"{play.f}: blob injection failed: {e}")
    frames += play.f                           # the budget counts from here
    if new and not (actions and actions[0].get("new")):
        actions.insert(0, {"new": True})
    for i, act in enumerate(actions):
        if play.f >= frames:
            log(f"{play.f}: frame budget spent before action {i} {act}"); break
        try:
            run_action(act, play, frames, log)
        except GaveUp as e:
            log(f"{play.f}: GAVE UP during action {i} {act}: {e} - the route ends here")
            break
        except Wedged:
            log(f"{play.f}: WEDGED during action {i} {act} - restoring the last bookmark, skipping it")
            if play.last_state:
                play.emu.restore(gzip.decompress(open(play.last_state, "rb").read()))
                play.emu.held = set(); play.held_until = -1; play.tick = None; play.last_cells = None
                play.run(2)
            else:
                break
    if play.emu.frame:
        play.emu.image().save(os.path.join(play.out, "final.png"))


def run_action(act, play, frames, log):
    if True:
        if act.get("new"):
            title, newgame = satpilot.presses(play.emu)
            play.run(title - play.f); play.press(OK)
            play.run(newgame - play.f); play.press("c")
            log(f"{play.f}: NEW GAME confirmed; the opening runs untouched")
            while play.f < frames and not play.box()[1]:
                play.run(1)
            log(f"{play.f}: first card waits: {[r for r in play.box()[2] if r]}")
        elif act.get("wait_menu"):
            got = play.wait_menu(act.get("patience", PATIENCE), hold_after_card=act.get("hold"))
            log(f"{play.f}: menu {got[3] if got else 'never came'}")
        elif "path" in act:
            play.ensure_top()
            for _ in range(act.get("reps", 1)):
                ok = play.do_path(act["path"], act.get("optional", False), act.get("patience", PATIENCE))
                if not ok:
                    break
        elif "sweep" in act:
            play.ensure_top()
            play.sweep(act["sweep"], act.get("rounds", 1), act.get("avoid", ()), act.get("each"), act.get("each_rounds", 1))
        elif "menu" in act:
            play.pick(int(act["menu"]))
        elif "press" in act:
            play.press(act["press"]); play.run(PRESS + 2); play.last_press_f = play.f
            log(f"{play.f}: press {act['press']}")
        elif "cancel" in act:
            play.press(BACK); play.run(STEP_GAP)
        elif "idle" in act:
            log(f"{play.f}: idle {act['idle']}")
            play.run(int(act["idle"]))
        elif "save" in act:
            play.wait_menu()
            name = act["save"]
            m = re.match(r"^(B[0-9A-F]{3})_", name)
            here = BANK_NAMES.get(play.bank, "")
            if m and m.group(1) != here:
                # a route's saves are positional: B020_end's B080_* saves landed in B020 when the
                # exit never happened and overwrote the real B080 bookmarks (2026-09-16)
                log(f"{play.f}: save {name!r} while {here or '?'} is loaded, not {m.group(1)}: kept as {name}.misplaced")
                name += ".misplaced"
            play.save(name)
        elif "bsave" in act:
            play.wait_menu()
            play.bsave(act["bsave"], int(act.get("slot", os.environ.get("BSAVE_SLOT", 1))))
        elif "fight" in act:
            play.fight_state = act["fight"]; log(f"{play.f}: aim {act['fight']}")
        elif "dial" in act:
            play.dial(str(act["dial"]))
        elif "phone" in act:
            # the videophone: Use Metal Gear > Videophone > Call, the number on the keypad
            # (satjourney.dial_phone), then the call's cards; `then` = a path afterwards
            import satjourney
            if play.do_path(["Use Metal Gear", "Videophone", "Call"], optional=True):
                try:
                    satjourney.dial_phone(play, str(act["phone"]))
                except Exception as e:
                    log(f"{play.f}: phone {act['phone']}: {e}")
                for p in act.get("then", []):
                    play.do_path(p, optional=True)
                play.do_path(["Hang up"], optional=True)
                play.do_path(["Don't call"], optional=True)
        elif "light_to" in act:
            play.light_to(*act["light_to"])
        elif "light" in act:
            play.light(act["light"])
        else:
            log(f"{play.f}: unknown action {act}")


# The numeric pads: the keyboard routine 0x060B9A74 in modes 0/1/3 keeps its cursor in
# the same {u16, u16} word at 0x060F2C00 as the katakana keyboard and appends one code per
# press to the typed buffer 0x060EF6B4 (digit d = 0x0F + d). Two pads, mapped empirically
# (work/saturn/subs_b0c0/probe_pad.py map2, 2026-09-16): Catherine's questions (B0C0,
# behind Metal Gear's 'Choose digits with the arrow keys' card; OK submits) and the
# videophone (behind 'What number?', which swallows a SECOND press before the pad takes
# input; '0' sits where the other pad's OK is, the number connects by itself). The cursor
# word is not the picture's (col, row).
PAD_CURSOR, PAD_TYPED = 0x060F2C00, 0x060EF6B4
DIGIT_CELLS = {"1": (2, 1), "2": (0, 1), "3": (1, 1), "4": (2, 2), "5": (0, 2),
               "6": (1, 2), "7": (2, 3), "8": (0, 3), "9": (1, 3)}
PAD_CELLS = dict(DIGIT_CELLS, **{"0": (2, 0), "OK": (0, 0)})
PHONE_CELLS = dict(DIGIT_CELLS, **{"0": (0, 0)})


# Queen Hospital's dark room (B1E0, Door 3): Metal Gear's light moves while B is held
# with a direction ('Hold the B button; direction keys move it') - the verb menu stays
# up. The light's rectangle is in RAM: u16 x, y at ctx+0x3EE/0x3F0 (picture coordinates,
# x 0..243, y 0..143; ctx+0x3F2/0x3F4 = x+72, y+60, the far corner), 2 px per frame
# (found 2026-09-17 by diffing WRAM while holding B+right: 0x060F289E climbed 67 -> 243).
# The picture's centroid of lit pixels was the first try and is biased by what the light
# reveals - kept as `light_pos` for the record. Right after a card the engine ignores
# B + direction for ~120 frames ('plain' never moved, 'wait120' did).
LIGHT_ROWS, LIGHT_COLS, LIGHT_THR = (18, 142), (48, 284), 60
LIGHT_X, LIGHT_Y = satmem.CTX + 0x3EE, satmem.CTX + 0x3F0


def _light_pos(self):
    import numpy as np
    a = np.asarray(self.emu.image().convert("RGB")).astype(int)
    a = a[LIGHT_ROWS[0]:LIGHT_ROWS[1], LIGHT_COLS[0]:LIGHT_COLS[1]].max(axis=2)
    ys, xs = np.nonzero(a > LIGHT_THR)
    if len(xs) < 50:
        return None
    return int(xs.mean()) + LIGHT_COLS[0], int(ys.mean()) + LIGHT_ROWS[0]


def _light_xy(self):
    return self.mem.u16(LIGHT_X), self.mem.u16(LIGHT_Y)


def _light_to(self, tx, ty, patience=3000):
    """{"light_to": [x, y]}: move the light's rectangle to (x, y) - its top-left in
    the picture's coordinates, x 0..243, y 0..143 - within 2 px; B + the direction that
    closes the larger gap, held. Starts with a rest (the engine's guard after a card)
    and rests again whenever 300 frames pass without the light moving."""
    self.emu.held = set(); self.held_until = -1
    self.run(120)
    start, last, since = self.f, None, self.f
    while self.f - start < patience:
        pos = self.light_xy()
        if pos != last:
            last, since = pos, self.f
        elif self.f - since > 300:
            self.emu.held = set(); self.held_until = -1
            self.run(120); since = self.f
            continue
        x, y = pos
        dx, dy = tx - x, ty - y
        if abs(dx) <= 2 and abs(dy) <= 2:
            self.emu.held = set(); self.held_until = -1
            self.run(20)
            self.log(f"{self.f}: light at ({x},{y}) for ({tx},{ty})")
            return True
        d = ("right" if dx > 0 else "left") if abs(dx) >= abs(dy) else ("down" if dy > 0 else "up")
        self.emu.held = {satrun.BTN[BACK], satrun.BTN[d]}
        self.held_until = -1
        self.run(4)
    self.emu.held = set(); self.held_until = -1
    self.run(20)
    self.log(f"{self.f}: light stuck at {self.light_xy()}, wanted ({tx},{ty})")
    return False


def _light(self, moves):
    """{"light": [["right", 60], ["down", 30]]}: hold B + each direction for n frames."""
    for d, n in moves:
        self.emu.held = {satrun.BTN[BACK], satrun.BTN[d]}
        self.held_until = -1
        self.run(int(n))
        self.emu.held = set(); self.held_until = -1
        self.run(20)
    self.log(f"{self.f}: light moved {moves} -> {self.light_xy()}")


Play.light_pos, Play.light_xy, Play.light_to, Play.light = _light_pos, _light_xy, _light_to, _light


def _dial(self, digits):
    """Type `digits` on whichever numeric pad comes up and submit (OK on Catherine's
    pad; the videophone dials when the number is complete). The pad's prompt card keeps
    ctx+0xB74 set, so the digits are walked on the cursor word, never on the flag."""
    m = self.mem
    cur = lambda: (m.u16(PAD_CURSOR), m.u16(PAD_CURSOR + 2))
    typed = lambda: m.read(PAD_TYPED, 14).split(b"\0")[0]
    cells = None
    for _ in range(80):                       # the question's cards, then the pad's prompt
        while not m.u8(satsubs.CTX + 0xB74):
            self.run(1)
            if self.f - self.last_press_f > 1500:
                break
        text = "".join(t for t, _ in read_cells(m, self.dec))
        if "What number" in text:
            cells = PHONE_CELLS
            self.press(OK); self.run(60); self.press(OK); self.run(40)
        elif any(k in text for k in ("Choose digits", "arrow keys", "directional buttons", "choose numbers")):   # the pad's prompt (two wordings since the 2026-09-28 carry)
            cells = PAD_CELLS
            self.press(OK); self.run(60)
        else:
            self.press(OK); self.run(30)
        self.last_press_f = self.f
        if cells:
            break
    if not cells:
        self.log(f"{self.f}: dial {digits!r}: no pad came up"); return
    self.log(f"{self.f}: dial {digits!r} on the {'phone' if cells is PHONE_CELLS else 'pad'}: cursor {cur()}, typed {typed().hex()}")
    def goto(cell):
        for _ in range(30):
            c, r = cur()
            if (c, r) == cell:
                return True
            self.press("down" if r < cell[1] else "up" if r > cell[1] else "right" if c < cell[0] else "left")
            self.run(12)
        self.log(f"{self.f}: pad cursor stuck at {cur()}, wanted {cell}")
        return False
    for d in digits:
        if goto(cells[d]):
            self.press(OK); self.run(20)
    self.log(f"{self.f}: typed {typed().hex()} for {digits!r}")
    if "OK" in cells and goto(cells["OK"]):
        self.press(OK); self.run(60)
    else:
        self.run(60)
    self.last_press_f = self.f


Play.dial = _dial


def lint(bank_names, log=print):
    """Static: every en row of the named banks through the pair font against
    the box (20 / 14 for ＠緑 in B030/B040) and every short label against 10."""
    from satapply import SatPairFont
    pf = SatPairFont(json.load(open(SAT_TABLE)))
    for name in bank_names:
        b = Bank(BANK_OF[name], pf)
        wide = []
        for s in b.strings:
            if not s["has_en"]:
                continue
            width = TERM_W if (name in ("B030", "B040") and ("＠緑" in s["en"][:6] or "▽" in s["en"])) else BOX_W
            for r in s["raw_rows"]:
                w = b.width(r.rstrip(" 　"))       # the timed-close pads (＠Ｃ) trail fullwidth spaces in the JP too
                if w > width:
                    wide.append((s["off"], w, width, COLOUR_RE.sub("", r)))
        # Gaudi's terminal (14 cells). The pristine layout 0x060B45C4 advances the
        # row twice for a row that fills the width and ends in ￥ (the auto-advance
        # at the last column, then the ￥), and its row-4 scroll leaves the row index
        # at 4, so a sixth advance writes the cells over ctx+0x58A - the script PC
        # at ctx+0x58C - and the machine WEDGES (B030 off 8105 'Witch hunts' and
        # three more, 2026-09-12; work/saturn/play/probe_hang.py, probe_wrapfix.py).
        # saturn/tools/satwrap.py fixes the engine (a full row's ￥ is consumed,
        # a page past row 3 scrolls); what remains a data matter is a terminal
        # entry over 4 rows, which scrolls its first row away. Both are counted.
        hang, full14, over4 = [], [], []
        if name in ("B030", "B040"):
            for s in b.strings:
                if not s["has_en"] or not ("＠緑" in s["en"][:6] or "▽" in s["en"]):
                    continue                 # the terminal's text: ＠緑 entries and the ▽ headers
                w = [b.width(r) for r in s["raw_rows"]]
                if any(x == 14 for x in w):
                    full14.append(s["off"])
                rows = sum((x + 13) // 14 or 1 for x in w)          # with satwrap
                pristine = rows + sum(1 for x in w[:-1] if x and x % 14 == 0)   # the double advance
                if rows > 4:
                    over4.append((s["off"], w, s["en"]))
                if pristine > 5:
                    hang.append((s["off"], w, s["en"]))
            log(f"{name}: {len(full14)} terminal strings with a row of exactly 14 cells; "
                f"{len(hang)} would wedge the pristine layout (6+ advances); "
                f"{len(over4)} run past 4 rows and scroll under satwrap")
            for off, w, en in hang:
                log(f"  HANG (pristine layout) off {off}: widths {w}: {en!r}")
            for off, w, en in over4:
                log(f"  SCROLL off {off}: widths {w}: {en!r}")
        padded = [(s["off"], pads(s["en"])) for s in b.strings if s["has_en"] and pads(s["en"])]
        omega = [s["off"] for s in b.strings if s["has_en"] and "ω" in s["en"]]
        if omega:
            log(f"{name}: {len(omega)} en strings carry the Saturn-only ω code (slot 0 = invisible in the pristine table; the build's table entry for SJIS 0x83D6 lies in the exec hole satexec allocates and draws garbage): offs {omega[:30]}")
        log(f"{name}: {len(b.strings)} strings, {sum(s['has_en'] for s in b.strings)} en, {len(wide)} rows over the box, "
            f"{len(padded)} strings with a visible pad before a colour code")
        for off, w, width, r in wide[:40]:
            log(f"  off {off}: {w} > {width}: {r!r}")
        for off, pd in padded[:60]:
            log(f"  off {off}: pad {pd}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--route")
    ap.add_argument("--state", help="resume from work/saturn/states/<name>.state.gz")
    ap.add_argument("--new", action="store_true", help="New Game first (through the opening)")
    ap.add_argument("--frames", type=int, default=200000)
    ap.add_argument("--image", default=PLAY_IMAGE)
    ap.add_argument("--out")
    ap.add_argument("--no-autosave", action="store_true")
    ap.add_argument("--lint", nargs="*")
    a = ap.parse_args()
    # a side image's own pair table (`<image stem>.pair_table.json` beside its cue: a
    # build copies work/saturn/pair_table_sat.json there) decodes its cells, not the play image's
    side = os.path.splitext(a.image)[0] + ".pair_table.json"
    if os.path.exists(side):
        global SAT_TABLE
        SAT_TABLE = side
    if a.lint is not None:
        lint(a.lint or list(BANK_OF)); return
    route = json.load(open(a.route, encoding="utf-8"))
    tag = os.path.splitext(os.path.basename(a.route))[0]
    out = a.out or os.path.join(PLAY, f"run_{tag}")
    os.makedirs(out, exist_ok=True)
    logf = open(os.path.join(out, "log.txt"), "w", encoding="utf-8")

    def log(m):
        logf.write(m + "\n"); logf.flush(); print(m, flush=True)

    log(f"image {a.image} sha1(cue) {hashlib.sha1(open(a.image, 'rb').read()).hexdigest()[:8]}; route {a.route}")
    emu = satrun.SaturnEmu()
    emu.load(a.image)
    play = Play(emu, out, log, a.image, autosave=not a.no_autosave)
    t0 = time.time()
    try:
        run_route(route, play, a.frames, log, a.state, a.new)
    except KeyboardInterrupt:
        log(f"{play.f}: interrupted")
    finally:
        play.finish(t0)
        log(f"done at frame {play.f} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
