"""Small Japanese labels baked into PCE pictures, redrawn in English - the
PCE twin of the PS1's ps1/tools/gfxlabels.py and the Saturn's satlabels.py
(same edit operations, same approved wording; pce/translation/gfx_labels.json).

Runs in Build-PCE.bat after pcecards.py. The videophone cards are
pcecards.py's (Luiz kept that wording); this tool owns Gibson's note, the
reception's JUNKER poster and the opening newspaper's boxed headline
(`*_parked` entries in gfx_labels.json are skipped).

Three kinds of picture:

  "screen"  one display list's tile picture (block, list): type-0 tile
            streams + a column-run BAT stream. Edits act on palette*16 +
            index. Each changed 8x8 cell takes an identical tile the picture
            keeps, else a tile id the edit freed that no other list's BAT in
            the block names; the touched tile streams and the BAT are
            re-encoded in place, padded to their old lengths, and the result
            is re-composed and compared with the intended picture (and the
            rest of the screen with the original). The newspaper (rec 858
            list 0x2dd): its tiles are also drawn by the BAT patches at
            0x7cd..0x8d1, so ids those name are never reused.
  "sprite"  an item close-up in rec 750 (resident all game, banks $6B/$6C):
            an item record `{bank, 0, 00 18, ptr} ff 02 0e 0f x x y y
            frames(2) anim(2) bank ...` - the stream holds 16x16 sprite cells
            (128 B, VRAM $1800 = pattern 0x60), the anim table names a frame,
            the frame table (`frames`, LE16 offsets) gives `N` x `{size, dy,
            dx, pattern*2 lo, attr}` (size bit 0 = 32 wide, bits 4-5 = 32/64
            tall; attr & 15 = sprite palette, 12-14 from the item's palette
            record at VCE 0x1C0). Edits act on the assembled sprite canvas;
            the result is written back into the cells it came from and the
            stream re-encoded in place, padded to its old length (it must not
            grow: stream 4 ends at $6C:0CF4, where module 478's LONGS blob
            lands). `also_at` = byte-identical copies to rewrite too: rec 750
            has an older 8-sector twin at track sector 722 that no file-table
            record names; it carries the note's stream at +0x28cf and gets the
            same bytes.

  "object"  a sprite object whose cells are part of a scene picture's own tile
            streams (the reception's Look > Poster close-up, block 5 list 0x70,
            frame 4 of the object table at 0xab54; the same cells again in
            blocks 13 and 33 - `also`). Pattern = 0x100 + lo / 2; the touched
            streams are re-encoded in place, padded to their old lengths.

Edit operations (canvas coordinates, palette indices, inclusive boxes), as
gfxlabels.py: erase / move / copy (`"source": "original"`, `"only"`) /
pixels (`drop`: a shadow colour one row under) / remap / inpaint / text
(`font` 6x13 | 5x7, `scale`, `shadow` at +1,+1, `x` "center" within `span`). `keep`: a box that must come out
pixel-identical (checked; Gibson's !? mark).

  python pce/tools/pcelabels.py preview [--out DIR]   before|after PNGs, 3x, real palette + _all.png
  python pce/tools/pcelabels.py fit                   stream sizes before/after (unpadded)
  python pce/tools/pcelabels.py dump NAME             a sprite canvas as index characters
  python pce/tools/pcelabels.py apply                 into patched/pce/snatcher_pce.bin
"""
import argparse, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import patch_pce as P
import pcecodec as C
import pcescene as S
import tilescan as T
import titlemenu as M

TEXT = os.path.join(ROOT, "pce", "translation", "gfx_labels.json")
OUT_DIR = os.path.join(WORK, "gfxcensus", "preview")


def palette_at(blk, o):
    """A palette record's data -> [(r, g, b)] (9-bit GGGRRRBBB)."""
    ng = blk[o] + 1
    cols = []
    for g in range(ng):
        grp = blk[o + 1 + 9 * g:o + 10 + 9 * g]
        for k in range(8):
            w = grp[1 + k] | (((grp[0] << k) & 0x80) >> 7) << 8
            cols.append(((w >> 3 & 7) * 36, (w >> 6 & 7) * 36, (w & 7) * 36))
    return cols


# --- sprite pictures (rec 750's item close-ups) -------------------------------

class Sprite:
    def __init__(self, spec):
        self.spec = spec
        self.rec, n, self.bank0 = spec["block"]
        self.blk = S.block(self.rec, n)
        i = int(spec["list"], 16)
        b, t, vl, vh, pl, ph = self.blk[i:i + 6]
        self.stream = self.off(b, pl | ph << 8)
        j = i + 7
        assert self.blk[j] == 2, f"{spec['tag']}: no sprite command after the stream record"
        frames = self.blk[j + 7] | self.blk[j + 8] << 8
        anim = self.off(self.blk[j + 11], self.blk[j + 9] | self.blk[j + 10] << 8)
        self.ft = self.off(self.blk[j + 11], frames)
        self.pal_off = None
        for k in range(j + 12, j + 34):
            if (self.blk[k + 1] == 1 and self.blk[k] == 0xC0 and 0x80 <= self.blk[k + 3] < 0xE0):
                self.pal_off = self.off(self.blk[k + 4], self.blk[k + 2] | self.blk[k + 3] << 8)
                break
        if "palette" in spec:
            self.pal_off = int(spec["palette"], 16)
        k = 0
        while self.blk[anim + k] in (0xEF, 0xF3):
            k += 4
        self.frame = self.blk[anim + k]
        data, self.end, ok = C.decode(self.blk, self.stream + 1)
        assert ok
        self.data = data
        self.cells = M.cells_of(data)
        self.compose()

    def off(self, bank, ptr):
        return (bank - self.bank0) * C.BANK + ptr - 0x8000

    def entries(self):
        o = self.ft + (self.blk[self.ft + 2 * self.frame] | self.blk[self.ft + 2 * self.frame + 1] << 8)
        out = []
        for i in range(self.blk[o]):
            s, dy, dx, lo, at = self.blk[o + 1 + 5 * i:o + 6 + 5 * i]
            out.append((s, dy - 256 if dy > 127 else dy, dx - 256 if dx > 127 else dx, lo, at))
        return out

    def compose(self):
        """Canvas of palette indices (0 = transparent), the owner (cell, y, x)
        of every canvas pixel, and each pixel's sprite palette."""
        boxes = []
        for s, dy, dx, lo, at in self.entries():
            w = 32 if s & 1 else 16
            h = {0: 16, 1: 32, 3: 64}[s >> 4 & 3]
            p = (lo - 0xC0) // 2
            if w == 32:
                p &= ~1
            for cy in range(h // 16):
                for cx in range(w // 16):
                    boxes.append((dx + cx * 16, dy + cy * 16, p + cy * 2 + cx, at & 15))
        x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
        x1 = max(b[0] for b in boxes) + 16; y1 = max(b[1] for b in boxes) + 16
        self.canvas = np.zeros((y1 - y0, x1 - x0), np.uint8)
        self.owner = {}
        self.palid = np.zeros_like(self.canvas)
        for bx, by, c, pal in reversed(boxes):         # first entry on top
            X, Y = bx - x0, by - y0
            self.canvas[Y:Y + 16, X:X + 16] = self.cells[c]
            self.palid[Y:Y + 16, X:X + 16] = pal
            for yy in range(16):
                for xx in range(16):
                    self.owner[Y + yy, X + xx] = (c, yy, xx)
        self.cellset = sorted({b[2] for b in boxes})

    def lut(self):
        cols = palette_at(self.blk, self.pal_off)
        pals = sorted(set(self.palid.ravel().tolist()))
        assert len(pals) == 1, "one sprite palette per picture"
        base = (pals[0] - 12) * 16
        t = np.zeros((16, 3), np.uint8)
        for v in range(16):
            t[v] = cols[base + v] if base + v < len(cols) else (255, 0, 255)
        t[0] = (24, 24, 24)                            # transparent
        return t

    def store(self, a):
        cells = self.cells.copy()
        for (y, x), (c, yy, xx) in self.owner.items():
            cells[c, yy, xx] = a[y, x]
        return cells

    def body(self, a):
        cells = self.store(a)
        self.changed = sorted(int(c) for c in np.nonzero((cells != self.cells).any(axis=(1, 2)))[0])
        return M.bytes_of(cells) + self.data[len(cells) * 128:]

    def fit(self, a):
        old = self.end - (self.stream + 1)
        new = len(M.encode(self.body(a)))
        return [dict(what=f"sprite stream @{self.stream:#x} ({len(self.cells)} cells, changed {self.changed})",
                     old=old, new=new)]

    def writes(self, a):
        """[(image user-data offset, old, new, what)]: the stream re-encoded in
        place, padded to its old length (it ends where the next data starts -
        for the note $6C:0CF4, module 478's LONGS blob), proved to decode to
        the edited cells; the same bytes again at every `also_at` copy."""
        at = self.stream + 1
        old = bytes(self.blk[at:self.end])
        body = self.body(a)
        new = M.encode(body, limit=len(old))
        back, end, ok = C.decode(new, 0)
        assert ok and end == len(new) and back == body, "the re-encoded stream does not decode back"
        out = [((S.T2 + self.rec) * P.DATA + at, old, new, f"rec {self.rec} sprite stream @{at:#x}")]
        for rec, off in self.spec.get("also_at", []):
            out.append(((S.T2 + rec) * P.DATA + int(off, 16), old, new,
                        f"copy at rec {rec} +{off} (no file-table record names it)"))
        return out


# --- sprite objects drawn from a scene picture's own tile streams ------------------

class Object(Sprite):
    """A sprite object whose cells come with a scene picture (the reception's
    JUNKER poster close-up): the display list `list` of block `block` (an
    index into the file table's class 2) loads plain tile streams, those at
    VRAM >= `patterns` * 64 hold sprite cells; the object's frame table
    (`frames`, LE16 offsets) names `frame`, whose entries are `{size, dy, dx,
    lo, attr}` with pattern = `patterns` + lo / 2. Colours: the palette record
    at `palette` (VCE 0x100 = sprite palette 0), `attr` & 15 picks the 16.
    Every touched stream is re-encoded in place, padded to its old length.
    `also`: [[block, list], ...] other pictures carrying the same cells in
    streams at the same VRAM (the HQ blocks of later acts); their cells are
    checked equal to this one's before they get the same edit."""

    def __init__(self, spec):
        self.spec = spec
        self.base = int(spec.get("patterns", "0x100"), 16)
        self.src = self.load(spec["block"], spec["list"])
        self.rec, self.blk = self.src["rec"], self.src["blk"]
        self.ft = int(spec["frames"], 16)
        self.frame = spec["frame"]
        self.pal_off = int(spec["palette"], 16)
        self.cells = self.src["cells"]
        self.compose()

    def load(self, bi, lst):
        r = S.TABLES["2"][bi]
        blk = S.block(r["rec"], r["n"])
        nb = (len(blk) + C.BANK - 1) // C.BANK
        recs = dict(C.find_lists(blk, r["bank"], nb))[int(lst, 16)]
        streams, cells = [], {}
        for b, t, va, ptr, o in recs:
            if va < self.base * 64:
                continue
            sp, flags, rowlen = C.image_stream(blk, o, t)
            assert t == 0 and flags & 0x7F == 0, "plain tile streams only"
            data, end, ok = C.decode(blk, sp)
            assert ok
            st = dict(vram=va, stream=sp, end=end, data=data)
            streams.append(st)
            for i, c in enumerate(M.cells_of(data)):
                cells[(va - self.base * 64) // 64 + i] = c
        return dict(rec=r["rec"], blk=blk, streams=streams, cells=cells, block=bi)

    def cell_of(self, lo, at):
        return lo // 2

    def compose(self):
        boxes = []
        for s, dy, dx, lo, at in self.entries():
            w = 32 if s & 1 else 16
            h = {0: 16, 1: 32, 3: 64}[s >> 4 & 3]
            p = self.cell_of(lo, at)
            if w == 32:
                p &= ~1
            for cy in range(h // 16):
                for cx in range(w // 16):
                    boxes.append((dx + cx * 16, dy + cy * 16, p + cy * 2 + cx, at & 15))
        x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
        x1 = max(b[0] for b in boxes) + 16; y1 = max(b[1] for b in boxes) + 16
        self.canvas = np.zeros((y1 - y0, x1 - x0), np.uint8)
        self.palid = np.zeros_like(self.canvas)
        self.owner = {}
        for bx, by, c, pal in reversed(boxes):
            X, Y = bx - x0, by - y0
            self.canvas[Y:Y + 16, X:X + 16] = self.cells[c]
            self.palid[Y:Y + 16, X:X + 16] = pal
            for yy in range(16):
                for xx in range(16):
                    self.owner[Y + yy, X + xx] = (c, yy, xx)
        self.cellset = sorted({b[2] for b in boxes})

    def lut(self):
        cols = palette_at(self.blk, self.pal_off)
        pals = sorted(set(self.palid.ravel().tolist()))
        assert len(pals) == 1, "one sprite palette per picture"
        t = np.zeros((16, 3), np.uint8)
        for v in range(16):
            t[v] = cols[pals[0] * 16 + v]
        t[0] = (24, 24, 24)
        return t

    def edited(self, a):
        """{cell: new 16x16} for every cell the edit changed."""
        new = {}
        for (y, x), (c, yy, xx) in self.owner.items():
            if a[y, x] != self.cells[c][yy, xx]:
                new.setdefault(c, self.cells[c].copy())[yy, xx] = a[y, x]
        return new

    def patches(self, src, new):
        out = []
        for st in src["streams"]:
            first = (st["vram"] - self.base * 64) // 64
            n = len(st["data"]) // 128
            mine = {c - first: v for c, v in new.items() if first <= c < first + n}
            if not mine:
                continue
            cells = M.cells_of(st["data"])
            for k, v in mine.items():
                assert (src["cells"][first + k] == self.cells[first + k]).all(), \
                    f"block {src['block']}: cell {self.base + first + k:#x} differs from block {self.spec['block']}'s"
                cells[k] = v
            body = M.bytes_of(cells) + st["data"][len(cells) * 128:]
            old = bytes(src["blk"][st["stream"]:st["end"]])
            enc = M.encode(body, limit=len(old))
            back, end, ok = C.decode(enc, 0)
            assert ok and back == body, "the re-encoded stream does not decode back"
            out.append((src, st["stream"], old, enc, len(M.encode(body)),
                        f"tile stream @{st['stream']:#x} (VRAM {st['vram']:#x}, cells {[hex(self.base + first + k) for k in sorted(mine)]})"))
        return out

    def all_patches(self, a):
        new = self.edited(a)
        out = self.patches(self.src, new)
        for bi, lst in self.spec.get("also", []):
            out += self.patches(self.load(bi, lst), new)
        return out

    def fit(self, a):
        return [dict(what=f"block {src['block']} {w}", old=len(o), new=raw)
                for src, _, o, n, raw, w in self.all_patches(a)]

    def writes(self, a):
        return [((S.T2 + src["rec"]) * P.DATA + at, o, n, f"rec {src['rec']} {w}")
                for src, at, o, n, _, w in self.all_patches(a)]


# --- tile pictures (a whole display-list screen) ---------------------------------

class Screen:
    """One display list's picture: type-0 tile streams + one direct-mode BAT
    stream (pcescene.build_vram + screen). Canvas values are palette*16 +
    index, colours from pcescene.colour_screen's palette choice. An edited
    cell takes an identical tile the picture keeps, else a tile id the edit
    freed - one no unedited cell of this picture and no BAT of any other list
    in the block names (the opening's BAT patches at 0x7cd..0x8d1 draw with
    the newspaper's tiles, so 0x11b-0x11e stay as they are)."""

    def __init__(self, spec):
        bi, li = spec["screen"]
        r = S.TABLES["2"][bi]
        self.rec, self.n, self.bank0 = r["rec"], r["n"], r["bank"]
        self.blk = S.block(self.rec, self.n)
        nb = (len(self.blk) + C.BANK - 1) // C.BANK
        self.all_lists = dict(C.find_lists(self.blk, self.bank0, nb))
        lists = [(off, recs) for off, recs in self.all_lists.items() if len(recs) >= 2]
        self.list, self.recs = lists[li]
        if "list" in spec:
            assert self.list == int(spec["list"], 16), f"screen {bi}.{li} is list {self.list:#x}"
        self.tiles, self.bat = [], None
        for b, t, va, ptr, o in self.recs:
            sp, flags, rowlen = C.image_stream(self.blk, o, t)
            data, end, ok = C.decode(self.blk, sp)
            assert ok
            rr = dict(type=t, vram=va, stream=sp, end=end, flags=flags, rowlen=rowlen, data=data)
            if t in (4, 8) and flags & 0x40:
                assert self.bat is None and flags & 0x20, "one column-run BAT stream"
                self.bat = rr
            else:
                assert t == 0 and flags & 0x7F == 0, "plain tile streams only"
                rr["n"] = len(data) // 32
                self.tiles.append(rr)
        self.vram = S.build_vram(self.blk, self.recs)
        img, palid = S.screen(self.vram)
        full = palid.repeat(8, 0).repeat(8, 1).astype(np.uint16) * 16 + img
        from PIL import Image
        import contextlib, io
        tmp = os.path.join(WORK, "gfxcensus", "_screen_tmp.png")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with contextlib.redirect_stdout(io.StringIO()):
            rgb = np.asarray(S.colour_screen(bi, li, out=tmp).convert("RGB"))
        self.x0, self.y0, x1, y1 = Image.fromarray(img).getbbox()
        assert self.x0 % 8 == 0 and self.y0 % 8 == 0
        self.canvas = full[self.y0:y1, self.x0:x1].astype(np.uint8)
        self.t = np.zeros((256, 3), np.uint8)
        for v in np.unique(self.canvas):
            vals, n = np.unique(rgb[self.canvas == v], axis=0, return_counts=True)
            self.t[v] = vals[n.argmax()]
        self.palid = np.zeros_like(self.canvas)

    def lut(self):
        return self.t

    def bat_index(self):
        """BAT word address -> index of the word in the BAT stream (column runs)."""
        per = self.bat["rowlen"] // 2
        nwords = len(self.bat["data"]) // 2
        return {self.bat["vram"] + (k // per) + (k % per) * S.BAT_W: k for k in range(nwords)}

    def pool(self):
        tl = {}
        for r in self.tiles:
            px = T.decode(np.frombuffer(r["data"][:r["n"] * 32], np.uint8).reshape(-1, 32))
            for i, t in enumerate(px):
                tl[r["vram"] // 16 + i] = t.copy()
        return tl

    def foreign(self):
        """Tile ids a BAT of another list in the block names without loading
        them itself - it draws with whatever VRAM holds, i.e. our tiles."""
        out = set()
        for off, recs in self.all_lists.items():
            if off == self.list:
                continue
            loaded, named = set(), set()
            for b, t, va, ptr, o in recs:
                sp, flags, rowlen = C.image_stream(self.blk, o, t)
                data, _, ok = C.decode(self.blk, sp)
                if t in (4, 8) and flags & 0x40:
                    if va < 0x800:
                        w = np.frombuffer(data[:len(data) // 2 * 2], "<u2") & 0xFFF
                        named |= set(int(x) for x in w)
                else:
                    loaded |= set(range(va // 16, va // 16 + len(data) // 32))
            out |= named - loaded
        return out

    def plan(self, a):
        idx = self.bat_index()
        words = np.frombuffer(self.bat["data"][:len(self.bat["data"]) // 2 * 2], "<u2").copy()
        tl = self.pool()
        h, w = a.shape
        cells = [(cy, cx) for cy in range(h // 8) for cx in range(w // 8)
                 if (a[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8] != self.canvas[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8]).any()]
        addr = {c: (c[0] + self.y0 // 8) * S.BAT_W + c[1] + self.x0 // 8 for c in cells}
        for c in cells:
            assert addr[c] in idx, f"cell {c} is not in the BAT stream"
        refs = {}
        for A, k in idx.items():
            refs.setdefault(int(words[k]) & 0xFFF, set()).add(A)
        edited = set(addr.values())
        freed = sorted(k for k in {int(words[idx[A]]) & 0xFFF for A in edited}
                       if refs[k] <= edited and k in tl)
        foreign = self.foreign()
        avail = [k for k in freed if k not in foreign]
        keep = {k: tl[k] for k in tl if k not in freed}
        changed = set()
        for c in cells:
            cy, cx = c
            k = idx[addr[c]]
            pal = int(words[k]) >> 12
            sub = a[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8]
            assert (sub >> 4 == pal).all(), f"cell {c}: ink outside the cell's palette {pal}"
            tile = (sub & 15).astype(np.uint8)
            hit = next((i for i, t in keep.items() if (t == tile).all()), None)
            if hit is None:
                hit = next((i for i in changed if (tl[i] == tile).all()), None)
            if hit is None:
                if not avail:
                    sys.exit(f"rec {self.rec} list {self.list:#x}: out of freed tile ids "
                             f"({len(freed)} freed, {len([k for k in freed if k not in foreign])} usable)")
                hit = avail.pop(0)
                tl[hit] = tile
                changed.add(hit)
            words[k] = (pal << 12) | hit
        self.summary = (f"{len(cells)} cells, {len(changed)} new tiles in {len(freed)} freed ids "
                        f"({len(freed) - len([k for k in freed if k not in foreign])} kept for other lists)")
        return tl, words, changed

    def patches(self, a):
        """[(block offset, old bytes, new bytes padded to the old length, raw
        length, what)], after proving the rewritten streams draw `a` and
        nothing else on the screen."""
        tl, words, changed = self.plan(a)
        out = []
        for r in self.tiles:
            base = r["vram"] // 16
            if not any(base <= k < base + r["n"] for k in changed):
                continue
            body = S.encode_tiles(np.array([tl[base + i] for i in range(r["n"])], np.uint8)) + r["data"][r["n"] * 32:]
            old = bytes(self.blk[r["stream"]:r["end"]])
            out.append((r["stream"], old, M.encode(body, limit=len(old)), len(M.encode(body)),
                        f"tile stream @{r['stream']:#x} ({r['n']} tiles)"))
        body = words.tobytes() + self.bat["data"][len(words) * 2:]
        old = bytes(self.blk[self.bat["stream"]:self.bat["end"]])
        out.append((self.bat["stream"], old, M.encode(body, limit=len(old)), len(M.encode(body)),
                    f"BAT stream @{self.bat['stream']:#x}"))
        new_blk = bytearray(self.blk)
        for at, o, n, _, _ in out:
            assert len(n) == len(o)
            new_blk[at:at + len(n)] = n
        img, palid = S.screen(S.build_vram(bytes(new_blk), self.recs))
        full = palid.repeat(8, 0).repeat(8, 1).astype(np.uint16) * 16 + img
        h, w = a.shape
        assert (full[self.y0:self.y0 + h, self.x0:self.x0 + w] == a).all(), \
            "the rewritten streams do not draw the edited picture"
        before, _ = S.screen(self.vram)
        rest = np.ones(img.shape, bool)
        rest[self.y0:self.y0 + h, self.x0:self.x0 + w] = False
        assert (img[rest] == before[rest]).all(), "pixels outside the picture moved"
        return out

    def fit(self, a):
        return [dict(what=f"{w} ({self.summary})", old=len(o), new=raw) for _, o, n, raw, w in self.patches(a)]

    def writes(self, a):
        """[(image user-data offset, old, new, what)]."""
        return [((S.T2 + self.rec) * P.DATA + at, o, n, f"rec {self.rec} {w}")
                for at, o, n, _, w in self.patches(a)]


# --- edits ----------------------------------------------------------------------

def draw(a, ed, name, palid=None):
    import bdffont
    font = bdffont.load(ed.get("font", bdffont.DIALOGUE))
    m = font.render(ed["text"])
    k = ed.get("scale", 1)
    if k > 1:
        m = m.repeat(k, 0).repeat(k, 1)
    cols = np.nonzero(m.any(0))[0]
    m = m[:, :cols.max() + 1] if len(cols) else m
    x0, x1 = ed.get("span", [0, a.shape[1] - 1])
    x = ed.get("x", "center")
    if x == "center":
        x = x0 + (x1 - x0 + 1 - m.shape[1]) // 2
    if x < x0 or x + m.shape[1] - 1 > x1:
        print(f"  {name}: {ed['text']!r} overruns [{x0}, {x1}] ({m.shape[1]} px at x={x})")
    y = ed["y"]
    h = min(m.shape[0], a.shape[0] - y)
    ys, xs = np.nonzero(m[:h])
    if ed.get("shadow") is not None:
        for yy, xx in zip(ys, xs):
            if y + yy + 1 < a.shape[0] and x + xx + 1 < a.shape[1]:
                a[y + yy + 1, x + xx + 1] = ed["shadow"]
    a[y + ys, x + xs] = ed["ink"]


def inpaint(a, box, values):
    from collections import Counter
    x0, y0, x1, y1 = box
    todo = {(y, x) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if a[y, x] in values}
    while todo:
        done = {}
        for y, x in todo:
            near = Counter(int(a[yy, xx])
                           for yy in range(max(0, y - 2), min(a.shape[0], y + 3))
                           for xx in range(max(0, x - 2), min(a.shape[1], x + 3))
                           if (yy, xx) not in todo)
            if near:
                done[y, x] = near.most_common(1)[0][0]
        if not done:
            break
        for (y, x), v in done.items():
            a[y, x] = v
        todo -= set(done)


def edit(a, spec, name):
    before = a.copy()
    for ed in spec["edits"]:
        if "erase" in ed:
            x0, y0, x1, y1 = ed["erase"]
            sub = a[y0:y1 + 1, x0:x1 + 1]
            if "only" in ed:
                sub[np.isin(sub, ed["only"])] = ed["fill"]
            else:
                sub[:] = ed["fill"]
        elif "move" in ed:
            x0, y0, x1, y1 = ed["move"]
            block = a[y0:y1 + 1, x0:x1 + 1].copy()
            a[y0:y1 + 1, x0:x1 + 1] = ed["fill"]
            dx, dy = ed.get("dx", 0), ed.get("dy", 0)
            a[y0 + dy:y1 + 1 + dy, x0 + dx:x1 + 1 + dx] = block
        elif "copy" in ed:
            x0, y0, x1, y1 = ed["copy"]
            src = before if ed.get("source") == "original" else a
            block = src[y0:y1 + 1, x0:x1 + 1].copy()
            tx, ty = ed["to"]
            dst = a[ty:ty + block.shape[0], tx:tx + block.shape[1]]
            if "only" in ed:
                keep = np.isin(block, ed["only"])
                dst[keep] = block[keep]
            else:
                dst[:] = block
        elif "pixels" in ed:
            rows = ed["pixels"]
            x0 = ed["x"]
            if x0 == "center":
                lo, hi = ed["span"]
                x0 = lo + (hi - lo + 1 - max(map(len, rows))) // 2
            if ed.get("drop") is not None:             # shadow one row under, ink on top
                for dy, row in enumerate(rows):
                    for dx, ch in enumerate(row):
                        if ch == "#":
                            a[ed["y"] + dy + 1, x0 + dx] = ed["drop"]
            for dy, row in enumerate(rows):
                for dx, ch in enumerate(row):
                    if ch == "#":
                        a[ed["y"] + dy, x0 + dx] = ed["ink"]
        elif "remap" in ed:
            x0, y0, x1, y1 = ed["remap"]
            sub = a[y0:y1 + 1, x0:x1 + 1]
            src = sub.copy()
            for k, v in ed["map"].items():
                sub[src == int(k)] = v
        elif "inpaint" in ed:
            inpaint(a, ed["inpaint"], set(ed["values"]))
        elif "text" in ed:
            draw(a, ed, name)
    for x0, y0, x1, y1 in spec.get("keep", []):
        assert (a[y0:y1 + 1, x0:x1 + 1] == before[y0:y1 + 1, x0:x1 + 1]).all(), \
            f"{name}: kept box {[x0, y0, x1, y1]} changed"
    return a


def entries(path=TEXT):
    data = json.load(open(path, encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_") and not k.endswith("_parked")}


def build(name, spec):
    pic = {"sprite": Sprite, "screen": Screen, "object": Object}[spec["kind"]](spec)
    before = pic.canvas.copy()
    after = edit(pic.canvas.copy(), spec, name)
    return pic, before, after


def preview(path, out, scale=3):
    from PIL import Image, ImageDraw
    os.makedirs(out, exist_ok=True)
    sheets = []
    for name, spec in entries(path).items():
        pic, before, after = build(name, spec)
        t = pic.lut()
        crop = spec.get("crop")
        if crop:
            x0, y0, x1, y1 = crop
            before, after = before[y0:y1 + 1, x0:x1 + 1], after[y0:y1 + 1, x0:x1 + 1]
        gap = np.full((before.shape[0], 4, 3), 40, np.uint8)
        im = Image.fromarray(np.hstack([t[before], gap, t[after]]))
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
        dst = os.path.join(out, f"{spec.get('tag', name)}.png")
        im.save(dst)
        sheets.append((spec.get("tag", name) + "", im))
        print(dst)
    w = max(im.width for _, im in sheets) + 16
    h = sum(im.height + 24 for _, im in sheets) + 8
    sh = Image.new("RGB", (w, h), (30, 30, 30))
    d = ImageDraw.Draw(sh)
    y = 8
    for label, im in sheets:
        d.text((8, y), label, fill=(255, 255, 0))
        sh.paste(im, (8, y + 14))
        y += im.height + 24
    dst = os.path.join(out, "_all.png")
    sh.save(dst)
    print(dst)


def fit(path):
    ok = True
    for name, spec in entries(path).items():
        pic, before, after = build(name, spec)
        for r in pic.fit(after):
            good = r["new"] <= r["old"]
            ok &= good
            print(f"{spec.get('tag', name):14} {r['what']:52} {r['old']:6} -> {r['new']:6}  {'fits' if good else 'GROWS'}")
    return ok


def dump(path, name):
    spec = entries(path)[name]
    pic, before, after = build(name, spec)
    chars = ".123456789abcdef"
    print("     " + "".join(str(x // 10 % 10) for x in range(before.shape[1])))
    print("     " + "".join(str(x % 10) for x in range(before.shape[1])))
    for y in range(before.shape[0]):
        print(f"{y:4} " + "".join(chars[v] for v in before[y]) + "   " + "".join(chars[v] for v in after[y]))


def apply(path, out_path=P.OUT):
    """Every entry into the built image. Refuses a stream that is not the
    pristine one (run on a fresh Build-PCE.bat image, after pcecards)."""
    if not os.path.exists(out_path):
        sys.exit(f"{out_path} missing: run the build from pcescript.py apply")
    img = P.Image(out_path, P.T3 + P.RESERVE)
    for name, spec in entries(path).items():
        pic, before, after = build(name, spec)
        for at, old, new, what in pic.writes(after):
            if bytes(img.data[at:at + len(old)]) != old:
                sys.exit(f"{spec.get('tag', name)}: {what} is not pristine")
            assert len(new) == len(old)
            img.write(at, new)
            print(f"{spec.get('tag', name)}: {what}, {len(old)} B rewritten in place")
    print(f"{img.flush()} sectors written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preview", "fit", "dump", "apply"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("--text", default=TEXT)
    ap.add_argument("--out", default=OUT_DIR)
    a = ap.parse_args()
    if a.cmd == "preview":
        preview(a.text, a.out)
    elif a.cmd == "fit":
        sys.exit(0 if fit(a.text) else 1)
    elif a.cmd == "dump":
        dump(a.text, a.name)
    else:
        apply(a.text)
