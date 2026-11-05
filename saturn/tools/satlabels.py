"""Redraw the small Japanese labels baked into Saturn sprite pictures.

The Saturn twin of ps1/tools/gfxlabels.py. The memo pages, the diary, the
disclaimer, the roll and the key faces have their own tools (satpages,
satroll, satkeys); this one handles one-off pictures: the videophone's NOT
IN SERVICE / NO VIDEO cards (chunks 237 / 238), the "search the house" note
among the item close-ups (362..366), the JUNKER recruitment poster (489) and
the B180 phone-book jokes (250, 252, 253, 261). Census:
work/gfxcensus/saturn_census.md.

A picture is one sprite list of a container (satgfx.py's format): the
list's pieces {w, h, srca, x, y} are composed into one canvas (offset so the
leftmost/topmost piece sits at 0, 0), edited, and written back piece by
piece into the type-3 section. The index is read with each offset table
padded to a multiple of four entries (op 0x18's registrar, see
satoptlabels.py) - satgfx.index reads the list table 8 bytes early when
nA % 4 != 0. Pieces that share pixels (same srca) are written in list order;
`build` warns when an edit leaves two such pieces disagreeing.

Each entry in `saturn/translation/gfx_labels.json` (not sat_*.json: satapply
globs SAT_*.json, case-blind on Windows) names `chunk` and
`list` (or `bg`: a type-0 section number) and a list of edits applied in
order, in canvas coordinates and palette INDICES:

  {"erase": [x0, y0, x1, y1], "fill": 19}           inclusive rectangle
  {"move": [x0, y0, x1, y1], "dx": 0, "dy": -8, "fill": 19}
  {"copy": [x0, y0, x1, y1], "to": [x, y]}         e.g. a glyph Konami drew;
   "source": "original" reads the unedited picture, "only": [2, 4] copies
   just those indices (lettering lifted off one background onto another)
  {"pixels": ["#..", ...], "x": 8 | "center", "span": [x0, x1], "y": 9,
   "ink": 2, "drop": 4}                             hand-set letters in a picture's
                                                    own lettering, shadow one row under
  {"remap": [x0, y0, x1, y1], "map": {"5": 18}}    lighten a texture under text
  {"inpaint": [x0, y0, x1, y1], "values": [125, 79]}   each listed index takes
                                                    the commonest non-listed
                                                    index around it
  {"text": "...", "y": 28, "x": 8 | "center", "span": [x0, x1],
   "ink": 20, "shadow": 18, "font": "6x13", "scale": 1,
   "proportional": false, "gap": 1, "space": 3,
   "outline": 12}                                   shadow at +1,+1; outline = 8-neighbour ring

`y` is the top of the font's cell (TRIM_TOP applied); `span` bounds the
centring and the overrun check (default: the whole canvas).

`"store": [6, 7]` writes back only those records of the list (by index
among the list's non-empty records): for lists whose pieces overlap (261's
caption bar drawn over the city strip), the composed canvas is what the
screen shows, but only the caption pieces may take it back.

Usage (repo root):
  python saturn/tools/satlabels.py preview [NAME...]   before|after PNGs at 3x -> work/saturn/labels/
  python saturn/tools/satlabels.py sheet               work/saturn/labels/_all.png (every preview, labelled)
  python saturn/tools/satlabels.py dump NAME           the canvas's indices at 6x with an 8-px grid + histogram
  python saturn/tools/satlabels.py size [NAME...]      decoded size check + LZ3 re-pack size against the original
  python saturn/tools/satlabels.py apply               decoded overrides -> patched/saturn/chunks/NNN.bin
                                                       (as satpages.py does; both run in the build chain)

Preview colours: the palette the list's CLUT selects ((clut >> 8) - 1,
clamped), else `"preview_cap": [png, ox, oy]` (a capture with the canvas's
top-left at ox, oy).
"""
import argparse, json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

import satgfx

TEXT = os.path.join(ROOT, "saturn", "translation", "gfx_labels.json")
OUT = os.path.join(WORK, "saturn", "labels")


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def lists(dec, o):
    """The type-2 index's sprite lists, each table padded to 4 entries."""
    nA, nB = struct.unpack_from(">HH", dec, o)
    tB = o + 16 + 4 * ((nA + 3) & ~3)
    out = []
    for i in range(nB):
        a = o + struct.unpack_from(">I", dec, tB + 4 * i)[0]
        n = struct.unpack_from(">H", dec, a)[0]
        recs = []
        for r in range(n):
            ctrl, sz, clut, srca, x, y = struct.unpack_from(">6H", dec, a + 8 + 12 * r)
            recs.append(dict(ctrl=ctrl, w=sz >> 8, h=sz & 0xFF, clut=clut, srca=srca, x=s16(x), y=s16(y)))
        out.append(recs)
    return out


class Canvas:
    """One sprite list (or one type-0 background) as an editable index image."""

    def __init__(self, idx, spec, dec=None):
        self.idx = idx
        self.dec = bytearray(dec if dec is not None else satgfx.load(idx))
        self.secs = satgfx.parse(bytes(self.dec))
        pals = satgfx.palettes(bytes(self.dec), self.secs)
        self.bg = spec.get("bg")
        if self.bg is not None:
            t, o, s = self.secs[self.bg]
            assert t == 0, f"chunk {idx} section {self.bg} is not a background"
            self.bgo, self.bgs = o, s
            self.width, self.height, _ = satgfx.bg_pixels(bytes(self.dec), o, s)
            self.pal = pals[spec.get("palette", 0)] if pals else None
            return
        spr = [(o, s) for t, o, s in self.secs if t == 3]
        self.so, self.ss = spr[spec.get("sprites", 0)]
        io = [o for t, o, s in self.secs if t == 2][0]
        recs = [r for r in lists(bytes(self.dec), io)[spec["list"]] if r["w"] and r["h"]]
        self.x0 = min(r["x"] for r in recs)
        self.y0 = min(r["y"] for r in recs)
        self.width = max(r["x"] + r["w"] for r in recs) - self.x0
        self.height = max(r["y"] + r["h"] for r in recs) - self.y0
        self.recs = recs
        self.store_only = spec.get("store")
        if pals:
            k = (recs[0]["clut"] >> 8) - 1 if spec.get("palette") is None else spec["palette"]
            self.pal = pals[max(0, min(len(pals) - 1, k))]
        else:
            self.pal = None

    def array(self):
        if self.bg is not None:
            W, H, pix = satgfx.bg_pixels(bytes(self.dec), self.bgo, self.bgs)
            return np.frombuffer(pix, np.uint8).reshape(H, W).copy()
        a = np.zeros((self.height, self.width), np.uint8)
        for r in self.recs:
            src = self.so + r["srca"] * 8
            blk = np.frombuffer(bytes(self.dec[src:src + r["w"] * r["h"]]), np.uint8).reshape(r["h"], r["w"])
            X, Y = r["x"] - self.x0, r["y"] - self.y0
            a[Y:Y + r["h"], X:X + r["w"]] = blk
        return a

    def store(self, a):
        if self.bg is not None:
            self.dec[self.bgo:self.bgo + self.bgs] = satgfx.bg_pack(self.width, self.height, a.tobytes())
            return []
        seen, clash = {}, []
        for k, r in enumerate(self.recs):
            if self.store_only is not None and k not in self.store_only:
                continue
            X, Y = r["x"] - self.x0, r["y"] - self.y0
            blk = a[Y:Y + r["h"], X:X + r["w"]].tobytes()
            src = self.so + r["srca"] * 8
            key = (r["srca"], r["w"], r["h"])
            if key in seen and seen[key] != blk:
                clash.append(key)
            seen[key] = blk
            self.dec[src:src + len(blk)] = blk
        return clash


def draw(a, ed, name):
    import bdffont
    font = bdffont.load(ed.get("font", bdffont.DIALOGUE))
    if ed.get("proportional"):
        m = font.render(ed["text"], proportional=True, gap=ed.get("gap", 1), space=ed.get("space", 3))
    else:
        m = font.render(ed["text"], spacing=ed.get("spacing", 0))
    k = ed.get("scale", 1)
    if k > 1:
        m = m.repeat(k, 0).repeat(k, 1)
    cols = np.nonzero(m.any(0))[0]
    m = m[:, cols.min():cols.max() + 1] if len(cols) else m
    x0, x1 = ed.get("span", [0, a.shape[1] - 1])
    x = ed.get("x", "center")
    if x == "center":
        x = x0 + (x1 - x0 + 1 - m.shape[1]) // 2
    warn = None
    if x < x0 or x + m.shape[1] - 1 > x1:
        warn = f"{name}: {ed['text']!r} overruns [{x0}, {x1}] ({m.shape[1]} px at x={x})"
        print("  " + warn)
    y = ed["y"]
    ys, xs = np.nonzero(m)
    ok = (y + ys >= 0) & (y + ys < a.shape[0]) & (x + xs >= 0) & (x + xs < a.shape[1])
    if not ok.all():
        warn = f"{name}: {ed['text']!r} leaves the canvas"
        print("  " + warn)
    ys, xs = ys[ok], xs[ok]
    if ed.get("outline") is not None:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                oy, ox = y + ys + dy, x + xs + dx
                k2 = (oy >= 0) & (oy < a.shape[0]) & (ox >= 0) & (ox < a.shape[1])
                a[oy[k2], ox[k2]] = ed["outline"]
    if ed.get("shadow") is not None:
        sy, sx = y + ys + 1, x + xs + 1
        k2 = (sy < a.shape[0]) & (sx < a.shape[1])
        a[sy[k2], sx[k2]] = ed["shadow"]
    a[y + ys, x + xs] = ed["ink"]
    return warn


def inpaint(a, box, values):
    """Fill the listed indices inside `box` from their surroundings, a ring at
    a time, so wide strokes take the colours at their edge."""
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


def edit(a, before, edits, name):
    warns = []
    for ed in edits:
        if "erase" in ed:
            x0, y0, x1, y1 = ed["erase"]
            a[y0:y1 + 1, x0:x1 + 1] = ed["fill"]
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
            block = block[:dst.shape[0], :dst.shape[1]]
            if "only" in ed:
                keep = np.isin(block, ed["only"])
                dst[keep] = block[keep]
            else:
                dst[:] = block
        elif "pixels" in ed:
            rows = ed["pixels"]
            px = ed["x"]
            if px == "center":
                lo, hi = ed["span"]
                px = lo + (hi - lo + 1 - max(map(len, rows))) // 2
            py = ed["y"]
            for dy, row in enumerate(rows):
                for dx, ch in enumerate(row):
                    if ch == "#":
                        a[py + dy, px + dx] = ed["ink"]
                        below = rows[dy + 1][dx] if dy + 1 < len(rows) and dx < len(rows[dy + 1]) else "."
                        if ed.get("drop") is not None and below != "#":
                            a[py + dy + 1, px + dx] = ed["drop"]
        elif "remap" in ed:
            x0, y0, x1, y1 = ed["remap"]
            sub = a[y0:y1 + 1, x0:x1 + 1]
            src = sub.copy()
            for k, v in ed["map"].items():
                sub[src == int(k)] = v
        elif "inpaint" in ed:
            inpaint(a, ed["inpaint"], set(ed["values"]))
        elif "text" in ed:
            w = draw(a, ed, name)
            if w:
                warns.append(w)
    return warns


def entries(path=TEXT):
    data = json.load(open(path, encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def build(name, spec, dec=None):
    """(canvas, before, after, warnings); the canvas's dec carries the edit."""
    c = Canvas(spec["chunk"], spec, dec)
    a = c.array()
    before = a.copy()
    warns = edit(a, before, spec["edits"], name)
    clash = c.store(a)
    if clash:
        warns.append(f"{name}: shared pieces now differ {clash}")
        print("  " + warns[-1])
    return c, before, a, warns


def build_chunks(path=TEXT, only=None):
    """{chunk: decoded bytes} with every entry for that chunk applied in order."""
    out = {}
    for name, spec in entries(path).items():
        if only and name not in only:
            continue
        idx = spec["chunk"]
        c, _, _, _ = build(name, spec, out.get(idx))
        out[idx] = bytes(c.dec)
    return out


def lut_of(c, spec, before):
    if spec.get("preview_cap"):
        from PIL import Image
        png, ox, oy = spec["preview_cap"]
        cap = np.asarray(Image.open(os.path.join(ROOT, png)).convert("RGB"))
        t = np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, 1)
        sub = before[max(0, -oy):, max(0, -ox):]
        cc = cap[oy:oy + sub.shape[0], ox:ox + sub.shape[1]]
        sub = sub[:cc.shape[0], :cc.shape[1]]
        for i in np.unique(sub):
            vals, n = np.unique(cc[sub == i], axis=0, return_counts=True)
            t[i] = vals[n.argmax()]
        return t
    if c.pal:
        return np.array(c.pal, np.uint8)
    return np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, 1)


def preview(only=None, scale=3):
    from PIL import Image
    os.makedirs(OUT, exist_ok=True)
    done = {}
    for name, spec in entries().items():
        if only and name not in only:
            continue
        idx = spec["chunk"]
        c, before, after, warns = build(name, spec, done.get(idx))
        done[idx] = bytes(c.dec)
        t = lut_of(c, spec, before)
        crop = spec.get("crop")
        b, a = before, after
        if crop:
            x0, y0, x1, y1 = crop
            b, a = b[y0:y1 + 1, x0:x1 + 1], a[y0:y1 + 1, x0:x1 + 1]
        gap = np.full((b.shape[0], 4, 3), 40, np.uint8)
        im = Image.fromarray(np.hstack([t[b], gap, t[a]]))
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
        dst = os.path.join(OUT, f"{name}.png")
        im.save(dst)
        print(dst + ("  [" + "; ".join(warns) + "]" if warns else ""))


def sheet():
    from PIL import Image, ImageDraw
    names = [n for n in entries()] + [n for n in ("375_mockup",)]
    rows = []
    for n in names:
        p = os.path.join(OUT, f"{n}.png")
        if os.path.exists(p):
            rows.append((n, Image.open(p).convert("RGB")))
    W = max(im.width for _, im in rows) + 8
    H = sum(im.height + 22 for _, im in rows) + 4
    out = Image.new("RGB", (W, H), (30, 30, 30))
    d = ImageDraw.Draw(out)
    y = 4
    for n, im in rows:
        d.text((4, y), n + ("   (MOCKUP - not a game asset)" if "mockup" in n else "   before | after"), fill=(255, 255, 0))
        out.paste(im, (4, y + 16))
        y += im.height + 22
    dst = os.path.join(OUT, "_all.png")
    out.save(dst)
    print(dst, out.size)


def dump(name, scale=6):
    from PIL import Image, ImageDraw
    from collections import Counter
    spec = entries()[name]
    c = Canvas(spec["chunk"], spec)
    a = c.array()
    t = lut_of(c, spec, a)
    im = Image.fromarray(t[a]).resize((a.shape[1] * scale, a.shape[0] * scale), Image.NEAREST)
    d = ImageDraw.Draw(im)
    for x in range(0, a.shape[1], 8):
        d.line([(x * scale, 0), (x * scale, im.height)], fill=(255, 0, 255) if x % 32 == 0 else (90, 0, 90))
    for y in range(0, a.shape[0], 8):
        d.line([(0, y * scale), (im.width, y * scale)], fill=(255, 0, 255) if y % 32 == 0 else (90, 0, 90))
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"_dump_{name}.png")
    im.save(dst)
    print(dst, a.shape[::-1])
    for i, n in Counter(a.ravel().tolist()).most_common(24):
        print(f"  index {i:3d} x{n:5d}  rgb {tuple(int(v) for v in t[i])}")


def size(only=None):
    """Decoded size must stay; report the LZ3 re-pack against the original."""
    import lz3
    rows = lz3.table()
    for idx, dec in sorted(build_chunks(only=only).items()):
        orig = satgfx.load(idx)
        assert len(dec) == len(orig), f"chunk {idx}: decoded size {len(dec)} != {len(orig)}"
        packed = lz3.encode(dec)
        assert lz3.decode(packed) == dec, f"chunk {idx}: LZ3 round trip"
        old = rows[idx][1]
        slot = -(-old // 2048) * 2048
        print(f"chunk {idx}: decoded {len(dec)} (unchanged); LZ3 {old} -> {len(packed)} "
              f"({len(packed) - old:+d}); sectors {slot // 2048} -> {-(-len(packed) // 2048)}")


def apply():
    """Decoded overrides into patched/saturn/chunks/NNN.bin (satpack picks them
    up). Part of the build chain (build.py, Build-Saturn.bat, build_saturn.sh)."""
    for idx, dec in sorted(build_chunks().items()):
        assert len(dec) == len(satgfx.load(idx)), f"chunk {idx}: decoded size changed"
        print(f"chunk {idx}: -> {satgfx.write_chunk(idx, dec)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preview", "sheet", "dump", "size", "apply"])
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    if a.cmd == "preview":
        preview(a.names or None)
    elif a.cmd == "sheet":
        sheet()
    elif a.cmd == "dump":
        for n in a.names:
            dump(n)
    elif a.cmd == "size":
        size(a.names or None)
    else:
        apply()
