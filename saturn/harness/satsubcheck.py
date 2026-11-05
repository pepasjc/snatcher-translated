# -*- coding: utf-8 -*-
"""Subtitle and integrity checks that ride along every satplay run (satplay.Play owns one).

What it watches, frame by frame, from the engine's and the payload's own words:

  voice lines   the live mono line (sector 0x060EA2C2, key 0x060EA2C4, decoded bytes
                0x060EA2BC) and the SDAIF reel (number 0x060EFE6A while 0x060EFE64 == 1,
                stream bytes 0x060EFF0C). Each play of a line is an INSTANCE; at its end
                the cues of the loaded bank that cover what was heard are checked against
                the cards satplay read back from the cells:
    MISSED-CUE  a cue whose byte window was heard for at least MIN_HEARD_S seconds, yet
                no card with its text was read while the line played (+ the linger)
    UNCARDED    a line heard for MIN_HEARD_S with no cue in the loaded bank's file while
                another bank's file cards it (the reel-under-the-live-bank rule, BUG-030)
  cards         every cue card satplay logs is checked against what is playing:
    DESYNC      a cue card on screen while its line / reel is not the one playing, or the
                line's position is outside the cue's byte window (+ slack)
    STUCK-CARD  the payload keeps a card up (blob+16 `cur` != 0) with no line or reel
                playing for STUCK_FRAMES frames
    INKLESS     the payload's card has been up and settled for INK_SETTLE frames but the
                text rows show no bright pixel at all (a card RAM says is there and the
                screen does not show - the pixel side of FROZEN/INVISIBLE for band cards)
  heap          every INTEGRITY_EVERY frames: the game allocator's arena (0x00200000 +
                0x48000, free-list head 0x060FF088 - issue #88): free bytes, the largest free
                block, the allocated block count, logged as `heap ...`; HEAP when the free list
                does not close or the largest block falls under HEAP_LOW bytes
  integrity     every INTEGRITY_EVERY frames (not during a movie): the VDP1 font against
                chunk 0 of the image (FONT) and the exec's SJIS->glyph table in RAM against
                the image (GLYPH_TABLE) - satstress.IntegrityWatch's comparison, reported
                once per run instead of stopping it.

Everything is logged (`voice ...`, `subcue ...`) so satcoverage.py can read coverage
from any run's log.txt, finished or not; `finish()` writes subwatch.json.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'saturn/tools', 'saturn/harness', 'saturn/subs')]

TRANS = os.path.join(ROOT, "saturn", "translation")
VOICE_SEC, VOICE_KEY, VOICE_DEC = 0x060EA2C2, 0x060EA2C4, 0x060EA2BC
REEL_NO, REEL_PLAYING, REEL_POS = 0x060EFE6A, 0x060EFE64, 0x060EFF0C
MONO_BPS = 11025                  # ADPCM bytes decoded per second (4-bit, 22050 Hz)
MIN_HEARD_S = float(os.environ.get("SUBCHECK_MIN_HEARD", "0.6"))   # a cue counts as heard past this much of its window
LINE_QUIET = 45                   # frames the decoded counter stands still = the line is over
REEL_QUIET = 20                   # frames the reel position stands still (or the reel stops) = over
GRACE = 90                        # frames after a line's end a card may still be read for it
STUCK_FRAMES = int(os.environ.get("SUBCHECK_STUCK", "1200"))
INK_SETTLE = 30
INTEGRITY_EVERY = int(os.environ.get("SUBCHECK_INTEGRITY", "1800"))
ARENA, ARENA_SIZE, FREE_HEAD = 0x00200000, 0x48000, 0x060FF088
HEAP_LOW = int(os.environ.get("SUBCHECK_HEAP_LOW", "4096"))


def heap_stats(mem):
    """The allocator's state from RAM: K&R headers {u32 next, u32 units of 8 bytes}."""
    low = mem.low()
    def w(a):
        a &= 0x1FFFFFFF
        if ARENA <= a < ARENA + 0x100000 - 4:
            return int.from_bytes(low[a - ARENA:a - ARENA + 4], "big")
        return mem.u32(a)
    start = w(FREE_HEAD) & 0x1FFFFFFF
    p, seen, free = start, set(), []
    while True:
        if p in seen or len(seen) > 20000 or not (ARENA <= p < ARENA + ARENA_SIZE or 0x06000000 <= p < 0x06100000):
            break
        seen.add(p)
        units = w(p + 4)
        free.append((p, units * 8))
        p = w(p) & 0x1FFFFFFF
    closed = p == start
    blocks, a = 0, ARENA
    while a < ARENA + ARENA_SIZE:
        units = w(a + 4)
        if units == 0 or a + units * 8 > ARENA + ARENA_SIZE:
            break
        blocks += 1
        a += units * 8
    fb = [n for q, n in free if ARENA <= q < ARENA + ARENA_SIZE]
    return dict(free=sum(fb), largest=max(fb or [0]), free_nodes=len(fb), blocks=blocks,
                allocated=blocks - len(fb), closed=closed, walked_to=a)


def squash(s):
    return "".join(ch for ch in s.lower() if ch.isalnum())


def cue_text(c):
    return squash("".join(c.get("rows") or [c.get("en", "")]))


def reel_bps(c):
    if c.get("frames") and c.get("size"):
        return c["size"] / c["frames"] * c.get("rate", 22050)
    return 96000.0


class SubWatch:
    def __init__(self, play):
        self.p = play
        self.layout = {}
        try:
            import satsubs
            self.layout = json.load(open(satsubs.LAYOUT_JSON, encoding="utf-8"))["scenes"]
        except Exception:
            pass
        # every enabled cue of every file: by mono key and by reel, with the file it lives in
        self.files = {}                 # file name (B010 / INTRO) -> [enabled cues] (the blob's order)
        self.by_key, self.by_reel = {}, {}
        import glob
        for path in sorted(glob.glob(os.path.join(TRANS, "subs_*.json"))):
            name = os.path.basename(path)[5:-5]
            cues = [c for c in json.load(open(path, encoding="utf-8"))["cues"] if c.get("enabled", True)]
            self.files[name] = cues
            for c in cues:
                if "reel" in c:
                    self.by_reel.setdefault(c["reel"], []).append((name, c))
                elif "sector" in c:
                    self.by_key.setdefault((c["sector"], (c["offset"] << 16) | (c["act"] << 8)), []).append((name, c))
        self.lines = {}
        try:
            for v in json.load(open(os.path.join(TRANS, "voice_map.json"), encoding="utf-8")):
                self.lines[(v["sector"], (v["offset"] << 16) | (v["act"] << 8))] = v["idx"]
        except Exception:
            pass
        self.inst = None                # the mono line playing: dict
        self.reel = None                # the reel playing: dict
        self.history = []               # finished instances (for the json)
        self.shown = {}                 # cue id -> [frames read]
        self.raised = {}                # cue id -> [frames the payload put it up]
        self.cur_id, self.cur_since = None, 0
        self.quiet_since = 0
        self.flagged = set()
        self.next_integrity = 0
        self.integrity = None
        self.integrity_failed = False
        self.heap_log = []

    # ---- the file the loaded bank's blob was built from ----------------------------
    def bank_name(self):
        import satplay
        return satplay.BANK_NAMES.get(self.p.bank, "")

    def cue_file(self):
        b = self.bank_name()
        return self.layout.get(b, {}).get("cue_file") or ("INTRO" if b == "B000" else b)

    def payload_cue(self):
        """The cue the payload shows (blob+16 `cur`), as a JSON record, or None."""
        p = self.p
        blob = p.blob_addr()
        if not blob:
            return None
        m = p.mem
        if m.u32(blob) != 0x53554253:
            return None
        cur = m.u32(blob + 16)
        if not cur:
            return None
        base, n = m.u32(blob + 8), m.u16(blob + 6)
        i = (cur - base) // 32
        cues = self.files.get(self.cue_file(), [])
        if 0 <= i < n and i < len(cues) and (cur - base) % 32 == 0:
            return cues[i]
        return None

    def exact(self, cue, band=False):
        """satplay matched a card's text to `cue`; when the payload shows a cue with the same
        text (a repeated line), that one is the card. A plain card while the payload shows
        nothing is the engine's own string that happens to read like a cue (Metal Gear's
        unvoiced "I'll analyze it." in B0C0): None, the bank's strings account for it."""
        pc = self.payload_cue()
        if pc is not None and cue is not None and cue_text(pc) == cue_text(cue):
            return pc
        if pc is None and not band and self.p.blob_addr():
            return None
        return cue

    # ---- per frame -------------------------------------------------------------------
    def step(self):
        p, m, f = self.p, self.p.mem, self.p.f
        # mono line
        sec, key, dec = m.u16(VOICE_SEC), m.u32(VOICE_KEY) & 0xFFFFFF00, m.u32(VOICE_DEC)
        i = self.inst
        if i is not None and (sec, key) == (i["sec"], i["key"]) and dec < i["dec"] and not i["started"]:
            i["dec"], i["moved"] = dec, f       # the counter resets some frames after the key changes
        elif i is not None and ((sec, key) != (i["sec"], i["key"]) or dec < i["dec"]):
            self.end_line(f)                    # another line, or this one again from the start
            i = None
        if i is None and (sec, key) != (0, 0) and self.last_mono is not None and self.last_mono != (sec, key, dec):
            i = self.inst = dict(kind="line", sec=sec, key=key, line=self.lines.get((sec, key)), start=f,
                                 dec=dec, moved=f, end=None, started=False, bank=self.bank_name(), file=self.cue_file())
            p.log(f"{f}: voice line {i['line']} (sector {sec}, key {key:#x}) in {i['bank']}")
        if i is not None:
            if dec != i["dec"]:
                i["started"] = i["started"] or dec > i["dec"]
                i["dec"], i["moved"] = dec, f
            elif not i["started"]:
                if f - i["start"] >= 300:        # the driver never started counting: no line after all
                    self.end_line(f)
            elif f - i["moved"] >= LINE_QUIET:
                self.end_line(f)
        self.last_mono = (sec, key, dec)
        # reel
        playing = m.u32(REEL_PLAYING) == 1
        rno, pos = m.u16(REEL_NO), m.u32(REEL_POS)
        r = self.reel
        if r is not None and (not playing or rno != r["reel"] or pos < r["pos"]):
            self.end_reel(f)
            r = None
        if r is None and playing:
            r = self.reel = dict(kind="reel", reel=rno, start=f, pos=pos, pos0=pos, moved=f, end=None,
                                 bank=self.bank_name(), file=self.cue_file())
            p.log(f"{f}: voice reel {rno} in {r['bank']}")
        if r is not None:
            if pos != r["pos"]:
                r["pos"], r["moved"] = pos, f
            elif f - r["moved"] >= REEL_QUIET and pos != r["pos0"]:
                self.end_reel(f)
        # the payload's card
        pc = self.payload_cue()
        pid = pc["id"] if pc else None
        if pid != self.cur_id:
            if self.cur_id:
                # how long the card was up (satcardlint's FAST judges the static window; the
                # gap to the next line is the script's)
                p.log(f"{f}: subcue {self.cur_id} down after {f - self.cur_since} frames")
            if pid:
                p.log(f"{f}: subcue {pid} up")
                self.raised.setdefault(pid, []).append(f)
                # a cue whose text is the card already on screen (the opening's news_16/16b split
                # at the diagram still, adopted without a retype): the cells never change, so
                # satplay reads no new card - the one up is this cue's
                prev = self.last_card
                if prev and prev[0] != pid and prev[1] == cue_text(pc) and p.card_key == prev[2]:
                    self.shown.setdefault(pid, []).append(f)
                    p.log(f"{f}: card {p._n} (same text, adopted) (cue {pid}, wait=0)")
            self.cur_id, self.cur_since = pid, f
            self.ink_checked = False
        active = (self.inst is not None) or (self.reel is not None)
        if active or not pid:
            self.quiet_since = f
        elif f - self.quiet_since == STUCK_FRAMES and ("stuck", pid) not in self.flagged:
            self.flagged.add(("stuck", pid))
            p.problem("STUCK-CARD", f"{self.bank_name()} cue {pid}",
                      f"our card has been up {f - self.cur_since} frames, no line or reel playing for {STUCK_FRAMES}",
                      p.capture("stuck"))
        if pid and not getattr(self, "ink_checked", True) and f - self.cur_since >= INK_SETTLE:
            self.ink_checked = True
            self.check_ink(pc)
        if INTEGRITY_EVERY and f >= self.next_integrity and not self.integrity_failed:
            self.next_integrity = f + INTEGRITY_EVERY
            self.check_integrity()

    last_mono = None
    _marker = None

    def _exec_marker(self):
        """16-byte spans of the image's exec the game never writes: the code every 8 KB from
        0x060B0600 to the tables, and the words just before and after the SJIS->glyph table
        (a sequential reload has the table in RAM once the span after it reads right)."""
        if self._marker is None:
            try:
                import satmem
                exe = satmem.image_exec(self.p.image)
                spans = list(range(0x600, 0x34000, 0x2000)) + [0x36C00, 0x39C00]
                self._marker = [(0x060B0000 + o, exe[o:o + 16]) for o in spans]
            except Exception:
                self._marker = []
        return self._marker

    def exec_is_games(self):
        """The game's exec is in RAM: after the ending's credits the attract loop's movies load
        the TrueMotion player over it (0x060B0000.., the glyph table with it) and reload it
        between movies - the allocator and the glyph table are not the game's then (the
        whole-game run's HEAP/FONT at 1649422, a black screen, 2026-11-06)."""
        spans = self._exec_marker()
        return bool(spans) and all(self.p.mem.read(a, 16) == b for a, b in spans)
    last_card = None

    # ---- line ends: what should have been read -----------------------------------------
    def heard(self, inst, c, upto):
        """Seconds of cue c's window the instance played."""
        b0, b1 = c["b0"], c["b1"]
        if inst["kind"] == "line":
            return max(0, min(b1, upto) - b0) / MONO_BPS
        return max(0, min(b1, upto) - max(b0, inst["pos0"])) / reel_bps(c)

    def judge(self, inst, cands, upto):
        here = [c for name, c in cands if name == inst["file"]]
        # another bank's cue counts only for what this play reached (a short reel shared by two
        # scenes plays its head in one and its carded tail in the other)
        elsewhere = sorted({name for name, c in cands if name != inst["file"] and self.heard(inst, c, upto) >= MIN_HEARD_S})
        heard = [c for c in here if self.heard(inst, c, upto) >= MIN_HEARD_S]
        # a cue shorter than MIN_HEARD_S played to its end must at least have been put up (B250's
        # 0.32 s 'Go!' never was: the plain box comes up ~0.3 s into a line)
        short = [c for c in here if c not in heard and inst["kind"] == "line" and upto >= c["b1"] > c["b0"]]
        inst["cues"] = [c["id"] for c in heard]
        inst["short"] = [c["id"] for c in short]
        missed = []
        for c in heard + short:
            seen = [fr for fr in self.shown.get(c["id"], []) + (self.raised.get(c["id"], []) if c in short else [])
                    if inst["start"] - 30 <= fr <= inst["end"] + GRACE]
            if not seen:
                missed.append(c["id"])
        inst["missed"] = missed
        what = f"line {inst.get('line')}" if inst["kind"] == "line" else f"reel {inst['reel']}"
        if missed:
            # a card may still be read during the grace period: judged once the grace is over
            inst["pending"] = missed
        if not here and elsewhere and inst.get("heard_s", 0) >= MIN_HEARD_S:
            k = ("uncarded", what, inst["file"])
            if k not in self.flagged:
                self.flagged.add(k)
                self.p.problem("UNCARDED", f"{inst['bank']} {what}",
                               f"heard {inst['heard_s']:.1f}s with no cue in subs_{inst['file']}.json; carded in {elsewhere}")

    def end_line(self, f):
        i, self.inst = self.inst, None
        if i is None:
            return
        i["end"] = f
        i["heard_s"] = i["dec"] / MONO_BPS
        cands = self.by_key.get((i["sec"], i["key"]), [])
        self.judge(i, cands, i["dec"])
        self.p.log(f"{f}: voice line {i['line']} over: {i['dec']} bytes ({i['heard_s']:.1f}s), cues {i['cues']}")
        self.history.append(i)

    def end_reel(self, f):
        r, self.reel = self.reel, None
        if r is None:
            return
        r["end"] = f
        cands = self.by_reel.get(r["reel"], [])
        bps = reel_bps(cands[0][1]) if cands else 96000.0
        r["heard_s"] = max(0, r["pos"] - r["pos0"]) / bps if r["pos"] != r["pos0"] else (f - r["start"]) / 60
        # a reel loaded whole into sound RAM has no moving position: nothing to judge by bytes
        if r["pos"] != r["pos0"]:
            self.judge(r, cands, r["pos"])
        else:
            r["cues"], r["missed"] = [], []
        self.p.log(f"{f}: voice reel {r['reel']} over ({r['heard_s']:.1f}s), cues {r.get('cues')}")
        self.history.append(r)

    def settle(self, final=False):
        """Pending misses whose grace period is over become problems."""
        f = self.p.f
        for i in self.history:
            pend = i.get("pending")
            if not pend or (not final and f < i["end"] + GRACE):
                continue
            still = [cid for cid in pend if not any(i["start"] - 30 <= fr <= i["end"] + GRACE
                                                    for fr in self.shown.get(cid, []) +
                                                    (self.raised.get(cid, []) if cid in i.get("short", []) else []))]
            i["pending"] = None
            i["missed"] = still
            what = f"line {i.get('line')}" if i["kind"] == "line" else f"reel {i['reel']}"
            for cid in still:
                self.p.problem("MISSED-CUE", f"{i['bank']} cue {cid}",
                               f"{what} played {i['heard_s']:.1f}s (frames {i['start']}..{i['end']}) and its card was never read")

    # ---- cards ---------------------------------------------------------------------
    def on_card(self, rec, cue):
        f = self.p.f
        self.shown.setdefault(cue["id"], []).append(f)
        rec["cue"] = cue["id"]
        self.last_card = (cue["id"], cue_text(cue), self.p.card_key)
        self.settle()
        ok, why = True, ""
        if "reel" in cue:
            r = self.reel or (self.history[-1] if self.history and self.history[-1]["kind"] == "reel"
                              and f - self.history[-1]["end"] <= GRACE else None)
            if r is None or r["reel"] != cue["reel"]:
                ok, why = False, f"reel {cue['reel']} card while {'reel ' + str(r['reel']) if r else 'no reel'} plays"
            elif r["pos"] != r["pos0"]:
                bps = reel_bps(cue)
                if not (cue["b0"] - 1.0 * bps <= r["pos"] <= cue["b1"] + 3.0 * bps):
                    ok, why = False, f"reel position {r['pos']} outside the cue's window {cue['b0']}..{cue['b1']}"
        elif "sector" in cue:
            key = (cue["sector"], (cue["offset"] << 16) | (cue["act"] << 8))
            i = self.inst
            if i is None and self.history:
                last = [h for h in self.history if h["kind"] == "line"]
                i = last[-1] if last and f - last[-1]["end"] <= GRACE + 60 else None
            if i is None or (i["sec"], i["key"]) != key:
                ok, why = False, (f"line {self.lines.get(key)} card while "
                                  f"{('line ' + str(i.get('line'))) if i else 'no line'} plays")
            elif not (cue["b0"] - 0.5 * MONO_BPS <= i["dec"] <= cue["b1"] + 3.0 * MONO_BPS):
                ok, why = False, f"line at byte {i['dec']}, outside the cue's window {cue['b0']}..{cue['b1']}"
        if not ok and ("desync", cue["id"]) not in self.flagged:
            self.flagged.add(("desync", cue["id"]))
            self.p.problem("DESYNC", f"{self.bank_name()} cue {cue['id']}", why, rec.get("shot"))
            rec["problems"].append("DESYNC")

    def check_ink(self, cue):
        """The card's rows on screen: at least a few bright pixels where the text goes."""
        p = self.p
        if not p.emu.frame:
            return
        import satsubs
        if p.mem.u16(satsubs.BOX_Y) != 0:
            return
        img = p.emu.image().convert("L")
        w, h = img.size
        box = img.crop((0, int(h * 150 / 240), w, int(h * 232 / 240)))
        bright = sum(1 for v in box.getdata() if v >= 200)
        if bright < 20 and ("ink", cue["id"]) not in self.flagged:
            self.flagged.add(("ink", cue["id"]))
            p.problem("INKLESS", f"{self.bank_name()} cue {cue['id']}",
                      f"our card is up {INK_SETTLE} frames but the text rows show {bright} bright pixels",
                      p.capture("inkless"))

    def check_heap(self):
        p = self.p
        try:
            h = heap_stats(p.mem)
        except Exception as e:
            p.log(f"{p.f}: heap walk failed: {e!r}")
            return
        p.log(f"{p.f}: heap free={h['free']} largest={h['largest']} allocated={h['allocated']} "
              f"blocks={h['blocks']} closed={int(h['closed'])} in {self.bank_name()}")
        self.heap_log.append(dict(f=p.f, bank=self.bank_name(), **h))
        bad = (not h["closed"]) or h["largest"] < HEAP_LOW
        if bad and "heap" not in self.flagged:
            self.flagged.add("heap")
            p.problem("HEAP", self.bank_name(), f"allocator: {h}", p.capture("heap"))

    def check_integrity(self):
        p = self.p
        if not self.exec_is_games():
            p.log(f"{p.f}: integrity: the exec in RAM is not the game's (a movie's player) - not checked")
            return
        self.check_heap()
        try:
            if self.integrity is None:
                import satstress
                self.integrity = satstress.IntegrityWatch(p.image, p.out or ".", 0, p.log)
                # the spare invalid-SJIS runs (satoptmenu.SPARE_RUNS) hold stub code and runtime
                # words (satlong's pool pointer, devtest's shot state): no text can draw their
                # codes, so a write there garbles nothing
                import satoptmenu, satfont
                self.integrity.runtime_table_ranges += [(lo - satfont.TABLE_ADDR, hi - satfont.TABLE_ADDR)
                                                        for lo, hi in satoptmenu.SPARE_RUNS]
            w = self.integrity
            w.next_frame = 0
            w.inspect(p, force=True)
            self.integrity_ok = True
        except Exception as e:
            name = type(e).__name__
            if name == "StressFailure" and not getattr(self, "integrity_ok", False) and getattr(p, "restored", False):
                # a bookmark keeps the VDP1 font and the table of the build it was made on (the
                # refresh rewrites the exec and the blob, not VRAM): a first check that differs
                # is the bookmark's build, not damage. Fresh boots (regress_saves, satwhole,
                # satstress) check from their first frame.
                self.integrity_failed = True
                p.log(f"{p.f}: integrity: the bookmark carries another build's font/table ({e}) - not checked in this run")
            elif name == "StressFailure":
                self.integrity_failed = True
                p.problem("FONT", self.bank_name(), str(e), p.capture("font"))
            elif not getattr(self, "_integrity_err", None):
                self._integrity_err = repr(e)
                p.log(f"{p.f}: integrity check unavailable: {e!r}")

    def finish(self):
        if self.inst:
            self.end_line(self.p.f)
        if self.reel:
            self.end_reel(self.p.f)
        self.settle(final=True)
        out = dict(instances=self.history, shown=self.shown, heap=self.heap_log)
        if self.p.out:
            json.dump(out, open(os.path.join(self.p.out, "subwatch.json"), "w", encoding="utf-8"), indent=1)
