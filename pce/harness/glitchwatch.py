"""Watch a pilot run for display glitches, not only for text: the PCE subtitle stub works on
the sprite table, the window's raster sections and the face regions, and a mistake there
shows as flicker, a vanished sprite or a hang that a text check never sees.

Attach to a Pilot (pcemenu) before running a route; every frame it samples:

  hang      the vblank counter ($1B, the game's own) stops for HANG frames - a crash or a
            wedge (Jamie's Act 2 call froze the game)
  relayout  the same subtitle page laid out again within RELAYOUT frames - the text
            blinks while it is drawn again (the kobe-yaki stall)
  window    the window flag ($39BF) going hidden/shown more than WINDOW times inside
            one line (logged, not a failure: with the rows blank a hidden window and a shown
            one look alike - `blink` is what the player sees)
  blink     the text band's words (lit pixels of y 152-216 outside every sprite, no list or
            message of the game's up) gone dark and back THE SAME within BLINK_GAP frames:
            a page drawn again, or the last line's words shown again between two lines (the
            linger's window put back over the game's mapping of the old tiles)
  sprite    a sprite position (x, y on the screen, patterns of any frame) that comes and
            goes: present, gone, present within FLICKER frames, FLICKER_N times in a
            window - a face or a frame vanishing every few frames (Harry, the videophone)
  screen    8x8 screen blocks going A -> B -> A over three samples SCREEN_EVERY frames
            apart, more than SCREEN_BLOCKS at once (big flicker anywhere on the screen)
  garbled   rendered_text's finding: the message buffer holds pair codes the module's table
            lacks (a string read from a wrong offset)
  band      the window shown and the text band lit in colours no text uses (picture or face
            tiles mapped through the rows: the bike ride's band of scraps), every BAND_EVERY;
            sprites left out, the ending (670) not checked (its pictures fill the screen)
  invisible a subtitle page laid out and, INVISIBLE frames on, the window shown with its text
            band dark (the dark rooms whose blank BAT hid Metal Gear's lines - kbat's case)
  dupe      one line shown both ways: a plain card ("Name: ...") and a face page with the same
            words within DUPE_SPAN frames (a voice line and a CD-DA card on the same speech)
  text      text_integrity's check at a menu (the module's longs blob in RAM against the
            disc) logged instead of stopping the run

and logs (not as glitches) every change to the game's flag bits ($3595-$35FF) and per-object
2-bit counters ($3728-$37FF) as `state $addr old -> new`: two builds playing one route should
change them alike, so a diff of those lines finds where a run's game state split off (a press
that took a menu item the log never named).

Each event is logged once per kind and second, with the frame saved, into <out>/events.json
and <out>/ev_<frame>_<kind>.png.

  python pce/harness/glitchwatch.py <state.mdf> <route.json> <out> [cue]   # a run with the watch
"""
import collections, hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]

HANG = 120             # frames with the vblank counter still
RELAYOUT = 240         # the same page drawn again within this many frames
WINDOW = 4             # window flag changes within one line
FLICKER = 10           # present-absent-present within this many frames ...
FLICKER_N = 3          # ... this many times within FLICKER_SPAN frames
FLICKER_SPAN = 120
SCREEN_EVERY = 2       # frames between screen samples
SCREEN_BLOCKS = 16     # 8x8 blocks (of the picture area, 32x18) going A-B-A at once
BAND_EVERY = 8         # frames between band checks
BAND_JUNK = 20         # distinct scrap cells (band_junk) that make a band garbled: the gold frame 9, scraps 44+
INVISIBLE = 30         # frames after a page's layout its text must be lit
BLINK_GAP = 45         # frames dark between two sights of the same words that make a blink
BLINK_LIT = 24         # lit pixels that make words in the band (a dark band: 2 or fewer)
DUPE_SPAN = 600        # frames a page's words stay remembered for the dupe check (one line:
                       # two lines saying "All right." a minute apart are no double)



def sprite_boxes(sat):
    """The screen rectangles (x0, y0, x1, y1) of the sprites drawing patterns 0x100 up (faces,
    figures): what the band check leaves out - the garbage it looks for is background tiles."""
    out = []
    for y, x, pt, a in sat:
        if (pt & 0x7FF) < 0x100 or not y:
            continue
        w = 32 if a & 0x100 else 16
        h = {0: 16, 1: 32, 2: 64, 3: 64}[(a >> 12) & 3]
        out.append((x - 32, y - 64, x - 32 + w, y - 64 + h))
    return out


def band_junk(img, boxes=()):
    """8x8 cells of the text band (y 152-216, the face's box and every sprite in `boxes` left
    out) holding scraps: four colours or more, half the cell lit - text and the life bar use
    two or three -, each distinct cell counted once (the terminal's gold frame repeats a few
    cells along its bars; scraps hardly repeat). 0 when the picture itself runs down into the
    band (a full-screen picture: row 148, the black gap above the window, lit)."""
    im = img.convert("RGB")
    w, h = im.size
    if h < 220:
        return 0
    px = im.load()
    gap = sum(1 for x in range(0, w, 2) if max(px[x, 148]) > 40)
    if gap > w // 4:
        return 0
    n = set()
    for cy in range(152, 216, 8):
        for cx in range(0, w - 7, 8):
            if 24 <= cx <= 100 or any(x0 <= cx + 4 < x1 and y0 <= cy + 4 < y1 for x0, y0, x1, y1 in boxes):
                continue
            cols, lit, cell = set(), 0, []
            for y in range(cy, cy + 8):
                for x in range(cx, cx + 8):
                    c = px[x, y]
                    cell.append(c)
                    if max(c) > 40:
                        lit += 1
                        cols.add((c[0] >> 5, c[1] >> 5, c[2] >> 5))
            if len(cols) >= 4 and lit >= 32:
                n.add(tuple(cell))
    if n and not scrappy(im):
        return 0
    return len(n)


def scrappy(im):
    """Tile scraps change colour as sharply inside a tile as across its edges (each 8x8 cell
    a random piece: interior change 200+, edge / interior ~1.1); a portrait or a picture is
    smoother inside its tiles (interior 25-170, edges 1.5-3x sharper) - the portraits drawn
    beside the text, which the sprite boxes miss where a scene moves the display."""
    import numpy as np
    band = np.array(im).astype(int)[152:216]
    dx = np.abs(np.diff(band, axis=1)).sum(axis=2)
    lit = band.max(axis=2) > 40
    act = lit[:, :-1] | lit[:, 1:]
    edge = (np.arange(band.shape[1] - 1) % 8) == 7
    if not act[:, edge].any() or not act[:, ~edge].any():
        return False
    e = dx[:, edge][act[:, edge]].mean()
    i = dx[:, ~edge][act[:, ~edge]].mean()
    return i >= 180 and e / (i + 1) < 1.4


def band_text(img, boxes=()):
    """(lit pixels, a hash of them) of the text band, y 152-216, every sprite box left out:
    the words on the window's rows as the player sees them."""
    import numpy as np
    rgb = np.asarray(img.convert("RGB")).astype(np.int32)
    a = rgb.max(axis=2)
    if a.shape[0] < 216:
        return 0, None, None
    band = a[152:216] > 120
    # cells of four colours or more are a portrait or a picture, never words (text: its colour,
    # a second at a name's colon, black) - a face the SAT read missed for a frame stays out
    q = rgb[152:216] >> 5
    key = (q[..., 0] << 6) | (q[..., 1] << 3) | q[..., 2]
    w = key.shape[1] // 8 * 8
    cells = key[:, :w].reshape(8, 8, w // 8, 8).transpose(0, 2, 1, 3).reshape(8, w // 8, 64)
    for cy in range(8):
        for cx in range(w // 8):
            c = band[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8]
            if (len(np.unique(cells[cy, cx])) >= 4 or c.sum() > 40      # (mostly lit: a portrait's
                    or c.all(axis=0).any() or c.all(axis=1).any()):    # backdrop; a full line:
                                                  # its frame - a letter does neither)
                band[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8] = False
    for x0, y0, x1, y1 in boxes:
        y0, y1 = max(y0, 152) - 152, min(y1, 216) - 152
        if y1 > y0:
            band[y0:y1, max(x0, 0):max(x1, 0)] = False
    lit = int(band.sum())
    pic = a[20:140:4, ::4] // 32                     # the picture, coarse: a fade is dark, a cut
    return lit, hash(np.packbits(band).tobytes()) if lit else None, pic   # changes it


def page_words(page):
    """(plain?, the page's words) - a plain card opens with its speaker's name and a colon."""
    import re
    body = page.split("<fb")[0]
    body = re.sub(".", " ", body)
    body = re.sub(r"<[^>]*>", " ", body)
    body = " ".join(body.split())
    m = re.match(r"^([A-Z][\w .'-]{1,20}): (.*)$", body)
    if m:
        return True, m.group(2).lower()
    return False, body.lower()

class GlitchWatch:
    def __init__(self, pilot, out):
        self.p, self.out = pilot, out
        os.makedirs(out, exist_ok=True)
        self.events = []
        self.last_vb, self.vb_since = None, 0
        self.pages = {}                       # page text -> last frame laid out
        self.last_page_frame = None
        self.win_changes, self.last_win, self.line_frame = 0, None, None
        self.present = {}                     # sprite key -> deque of (frame, present)
        self.patterns = {}                    # sprite key -> the patterns seen there
        self.flicks = collections.defaultdict(collections.deque)
        self.shots = collections.deque(maxlen=3)
        self.logged = {}                      # (kind, second) -> True
        self.game = None                      # the flags and counters as last seen
        self.seen_pages = {}                  # page words -> (plain?, frame)
        self.bl_fade = False
        orig = pilot.watch
        try:
            import text_integrity
            check = text_integrity.check

            def logged(pl):
                try:
                    check(pl)
                except RuntimeError as e:
                    self.event("text", str(e)[:160])
            text_integrity.check = logged
        except ImportError:
            pass

        def watch():
            orig()
            self.sample()
        pilot.watch = watch

    def event(self, kind, detail):
        key = (kind, self.p.frame // 60)
        if key in self.logged:
            return
        self.logged[key] = True
        path = os.path.join(self.out, f"ev_{self.p.frame:06d}_{kind}.png")
        try:
            self.p.emu.image().save(path)
        except Exception:
            path = None
        module = None
        try:
            module = self.p.module()
        except Exception:
            pass
        e = {"frame": self.p.frame, "kind": kind, "module": module, "detail": detail, "shot": path}
        self.events.append(e)
        print(f"{self.p.frame}: GLITCH {kind} {detail}", flush=True)

    def band_module(self):
        """Whether the band check applies: not in the ending (670, or its overwritten header:
        no module), whose full-screen pictures and right-hand portraits run through the band."""
        try:
            m = self.p.module()
        except Exception:
            return False
        return m not in (670, None, "?")

    def sample(self):
        p = self.p
        r = p.ram()
        # garbled: rendered_text's review of the message buffer (pair codes the module's table
        # does not hold - room 301's door drew a string from the Japanese offset)
        tm = getattr(p, "text_monitor", None)
        if tm is not None and len(tm.findings) > getattr(self, "garbled_seen", 0):
            for item in tm.findings[getattr(self, "garbled_seen", 0):]:
                self.event("garbled", f"module {item.get('module')}: {item.get('errors', [])[:2]}")
            self.garbled_seen = len(tm.findings)
        game =bytes(r[0x1595:0x1600]) + bytes(r[0x1728:0x1800])
        if self.game is not None and game != self.game:
            for i, (a, b) in enumerate(zip(self.game, game)):
                if a != b and not 0x2D <= i <= 0x30:     # ($35C2-$35C5: the script's scratch)
                    addr = 0x3595 + i if i < 0x6B else 0x3728 + i - 0x6B
                    print(f"{p.frame}: state ${addr:04X} {a:02x} -> {b:02x}", flush=True)
        self.game = game
        # hang: the game's own vblank counter
        vb = r[0x1B]
        if vb == self.last_vb and p.frame > 6000:       # (the System Card's boot keeps it still)
            self.vb_since += 1
            if self.vb_since == HANG:
                self.event("hang", f"vblank counter still for {HANG} frames")
        else:
            self.vb_since = 0
        self.last_vb = vb
        # band: picture or face tiles in the shown window's text rows
        if p.frame % BAND_EVERY == 0 and r[0x19BF] == 0x56 and self.band_module():
            try:
                boxes = sprite_boxes(p.sat())
            except Exception:
                boxes = ()
            n = band_junk(p.emu.image(), boxes)
            if n > BAND_JUNK:
                self.event("band", f"{n} cells of scraps in the text band")
        # dupe: the same words as a plain card and as a face page
        if getattr(p, "page_frame", None) == p.frame and p.page:
            self.dupe_due = (p.frame + 3, p.page)     # judged once it stood 3 frames: a page read
        due = getattr(self, "dupe_due", None)         # half rewritten at a turn is no face page
        if due and p.frame == due[0] and getattr(p, "page", None) == due[1]:
            self.dupe_due = None
            plain, words = page_words(due[1])
            if len(words) >= 12 and " " in words:     # (a name alone, a short reply: not one line twice)
                for k, (pl, fr) in list(self.seen_pages.items()):
                    if p.frame - fr > DUPE_SPAN:
                        del self.seen_pages[k]
                    elif pl != plain and (k.startswith(words) or words.startswith(k)):
                        self.event("dupe", f"{words[:40]!r} shown as a plain card and a face page")
                self.seen_pages[words] = (plain, p.frame)
        # invisible: a page with words, the window up, nothing lit in the band
        if (getattr(p, "page_frame", None) == p.frame and p.page and len(page_words(p.page)[1]) >= 12
                and " " in page_words(p.page)[1]):            # (a name alone: the game's own label)
            self.invis_due = (p.frame + INVISIBLE, p.page, r[0x1518], getattr(p, "cdda", 0))
        due = getattr(self, "invis_due", None)
        if due and p.frame == due[0]:
            self.invis_due = None
            if (r[0x19BF] == 0x56 and r[0x1518] == due[2] and getattr(p, "page", None) == due[1]
                    and (due[3] or r[0x6F2])):    # (an ADPCM line over by then - a short one, its
                                                  # rows unmapped for the linger - is no dark page)
                im = p.emu.image().convert("L")
                w = im.size[0]
                lit = sum(1 for y in range(156, 214, 2) for x in range(0, w, 2) if im.getpixel((x, y)) > 120)
                pic = sum(1 for y in range(20, 140, 8) for x in range(0, w, 8) if im.getpixel((x, y)) > 40)
                if lit < 12 and pic > 20:                   # (a black screen: a scene changing, not a line)
                    self.event("invisible", f"{page_words(due[1])[1][:40]!r} laid out, the band dark")
        # relayout: the pilot notes each subtitle page it sees laid out (LINELOG)
        if (getattr(p, "page_frame", None) == p.frame and p.page
                and len(page_words(p.page)[1]) >= 12 and " " in page_words(p.page)[1]):
            text = p.page                     # (a blank page between two cards, a name alone: no relayout)
            prev = self.pages.get(text)
            if prev is not None and p.frame - prev < RELAYOUT:
                self.event("relayout", f"{text[:40]!r} again after {p.frame - prev} frames")
            self.pages[text] = p.frame
        # window flag changes inside a line
        if getattr(p, "due", None) and p.due[0] != self.line_frame:
            self.line_frame, self.win_changes, self.line_sub = p.due[0], 0, False
        if getattr(p, "page_frame", None) == p.frame and p.page and len(page_words(p.page)[1]) >= 4:
            self.line_sub = True              # (a line with a subtitle up: the game's own window opening
        win = r[0x19BF]                       # and closing round its menus is no blink)
        if (self.last_win is not None and (win == 0x56) != (self.last_win == 0x56)
                and getattr(self, "line_sub", False) and not r[0x1518]):
            self.win_changes += 1
            if (self.line_frame is not None and p.frame - self.line_frame < 600
                    and self.win_changes == WINDOW):
                self.event("window", f"window flag changed {WINDOW} times in a line")
        self.last_win = win
        # sprites: positions on the screen, any pattern (an animated mouth stays present)
        try:
            sat = p.sat()
        except Exception:
            sat = []
        # blink: the same words back in the band after a short dark gap
        if self.band_module() and not r[0x1518] and not r[0x1478]:
            lit, h, pic = band_text(p.emu.image(), sprite_boxes(sat))
            prev = getattr(self, "bl_prev", None)
            if lit >= BLINK_LIT:
                # the same words back after a short dark gap, the scene the same throughout (a
                # fade or a new picture between: the game's own scene change, its sections off
                # while it decodes - the stub does not run in that pass)
                cut = self.bl_fade or (prev is not None and (pic != prev[2]).mean() > 0.2)
                if (prev and prev[0] == h and getattr(self, "bl_dark", False) and not cut
                        and 2 <= p.frame - prev[1] <= BLINK_GAP):
                    self.event("blink", f"the band's words gone and back after {p.frame - prev[1]} frames")
                self.bl_prev, self.bl_dark, self.bl_fade = (h, p.frame, pic), False, False
            elif lit <= 2 and prev:
                self.bl_dark = True
                self.bl_fade = self.bl_fade or (pic > 1).sum() <= 20 or (pic != prev[2]).mean() > 0.2
        else:
            self.bl_prev, self.bl_dark, self.bl_fade = None, False, False
        cur = {(x, y): pt & 0x7FF for y, x, pt, a in sat if 0 < x < 32 + 256 and 0 < y < 64 + 240 and 0x300 <= (pt & 0x7FF) < 0x400}   # (the face patterns: the only sprites the stub moves or hides - a scene's own animations, the cylinders' bubbles, are the game's)
        now = set(cur)
        for k, pt in cur.items():                 # an animation: a mouth cycles its patterns, one
            self.patterns.setdefault(k, set()).add(pt)   # of them no sprite at all - not a flicker
        for k in set(self.present) | now:
            hist = self.present.setdefault(k, collections.deque(maxlen=FLICKER * 2))
            hist.append((p.frame, k in now))
            states = [s for _, s in hist]
            # present, absent, present inside FLICKER frames
            if (len(states) >= 3 and states[-1] and not states[-2] and any(states[:-2][-FLICKER:])
                    and len(self.patterns.get(k, ())) < 2):
                q = self.flicks[k]
                q.append(p.frame)
                while q and p.frame - q[0] > FLICKER_SPAN:
                    q.popleft()
                if len(q) == FLICKER_N:
                    self.event("sprite", f"sprite at x {k[0] - 32} y {k[1] - 64} comes and goes")
        for k in [k for k, h in self.present.items() if not any(s for _, s in h)]:
            del self.present[k]
        # the screen in 8x8 blocks: A -> B -> A
        if p.frame % SCREEN_EVERY == 0:
            img = p.emu.image().convert("L").crop((0, 0, 256, 140)).resize((32, 18))   # the picture:
                                                  # the band below is menus opening and closing
            self.shots.append(img.tobytes())
            if len(self.shots) == 3:
                a, b, c = self.shots
                n = sum(1 for i in range(len(a)) if a[i] == c[i] and abs(a[i] - b[i]) > 24)
                if n >= SCREEN_BLOCKS:
                    self.event("screen", f"{n} blocks flicked")

    def save(self):
        json.dump(self.events, open(os.path.join(self.out, "events.json"), "w"), indent=1)
        kinds = collections.Counter(e["kind"] for e in self.events)
        return kinds


def main():
    state, route, out = sys.argv[1:4]
    os.environ["LINELOG"] = "1"
    import pcemenu as M
    p = M.Pilot(cue=sys.argv[4]) if len(sys.argv) > 4 else M.Pilot()
    p.restore(state)
    gw = GlitchWatch(p, out)
    try:
        M.run(p, json.load(open(route, encoding="utf-8")), outdir=out + "_run")
    finally:
        kinds = gw.save()
        print("glitches:", dict(kinds) or "none", flush=True)


if __name__ == "__main__":
    main()
