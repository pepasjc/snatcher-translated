"""Redraw small Japanese labels baked into graphics containers.

The memo pages have their own tool (gfxpages.py); this one handles the
one-off pictures: the videophone's NOT IN SERVICE / NO VIDEO cards
(CMC_B000 / CMC_B010, BUG-009), the joke-number pictures and anything
else that carries a line or two of Japanese on a flat background.

Each entry in `ps1/translation/gfx_labels.json` names a container, the
section and items that form one picture (side-by-side items are joined
into one canvas, as gfxpages does with the memo halves) and a list of
edits applied in order, all in canvas coordinates and palette INDICES
(the CMC pictures carry no palette of their own; the videophone CLUT is
loaded elsewhere):

  {"erase": [x0, y0, x1, y1], "fill": 19}           inclusive rectangle
  {"move": [x0, y0, x1, y1], "dx": 0, "dy": -8, "fill": 19}
  {"copy": [x0, y0, x1, y1], "to": [x, y]}         e.g. a glyph Konami drew;
   "source": "original" reads the unedited picture, "only": [2, 4] copies
   just those indices (lettering lifted off one background onto another)
  {"pixels": ["#..", ...], "x": 8 | "center", "span": [x0, x1], "y": 9,
   "ink": 2, "drop": 4}                             hand-set letters in a
                                                    picture's own lettering,
                                                    shadow one row under
  {"stamp": "CXC_B050", "src": [x0, y0, x1, y1], "to": [x, y]}
                                                    another entry's result
  {"remap": [x0, y0, x1, y1], "map": {"5": 18}}    lighten a texture under text
  {"inpaint": [x0, y0, x1, y1], "values": [125, 79]}   text over a photo:
                                                    each listed index takes the
                                                    commonest non-listed index
                                                    around it, nearest first
  {"text": "...", "y": 28, "x": 8 | "center", "span": [x0, x1],
   "ink": 20, "shadow": 18, "font": "6x13", "scale": 1,
   "proportional": false}                           shadow at +1,+1

`y` is the top of the font's cell (TRIM_TOP applied). `span` bounds the
centring and the overrun check.

Usage:
  python ps1/tools/gfxlabels.py preview [--text FILE] [--out DIR]
  python ps1/tools/gfxlabels.py apply   [--text FILE]

Preview colours: the container's palette, else `"preview_cap": [png, ox, oy]`
(a harness capture with the canvas's top-left at ox, oy), else
`"preview_lut": "grey"`, else the census's false-colour map.
"""
import argparse, json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

from lzss import decompress, compress
from gfx import sections, items, palette
from gfxpages import resize

TEXT = os.path.join(ROOT, "ps1/translation", "gfx_labels.json")
SRC_DIR = os.path.join(ROOT, "discs/extracted_ps1", "DES")
DST_DIR = os.path.join(ROOT, "patched")


def source_bytes(name):
    return open(os.path.join(SRC_DIR, name[:3], name + ".BIN"), "rb").read()


class Canvas:
    """Items of one section joined left to right, addressed as one image."""

    def __init__(self, name, dec, section, idx):
        self.name, self.dec = name, bytearray(dec)
        base, size = sections(dec)[section]
        table = items(dec, base, size, section)
        self.parts = [(table[i][0], table[i][1] * 2, table[i][2]) for i in idx]
        self.width = sum(w for _, w, _ in self.parts)
        self.height = max(h for _, _, h in self.parts)

    def array(self):
        out = np.zeros((self.height, self.width), np.uint8)
        x = 0
        for ip, w, h in self.parts:
            out[:h, x:x + w] = np.frombuffer(bytes(self.dec[ip:ip + w * h]), np.uint8).reshape(h, w)
            x += w
        return out

    def store(self, a):
        x = 0
        for ip, w, h in self.parts:
            self.dec[ip:ip + w * h] = a[:h, x:x + w].tobytes()
            x += w


def draw(a, ed, name):
    import bdffont
    font = bdffont.load(ed.get("font", bdffont.DIALOGUE))
    m = (font.render(ed["text"], proportional=True, gap=1, space=3)
         if ed.get("proportional") else font.render(ed["text"]))
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
        print(f"  {name}: {ed['text']!r} overruns [{x0}, {x1}] "
              f"({m.shape[1]} px at x={x})")
    y = ed["y"]
    h = min(m.shape[0], a.shape[0] - y)
    ys, xs = np.nonzero(m[:h])
    if ed.get("shadow") is not None:
        for yy, xx in zip(ys, xs):
            if y + yy + 1 < a.shape[0] and x + xx + 1 < a.shape[1]:
                a[y + yy + 1, x + xx + 1] = ed["shadow"]
    a[y + ys, x + xs] = ed["ink"]


def inpaint(a, box, values):
    """Fill the listed indices inside `box` from their surroundings, growing
    inwards a ring at a time so wide strokes take the colours at their edge."""
    from collections import Counter
    x0, y0, x1, y1 = box
    todo = {(y, x) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
            if a[y, x] in values}
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


def stamp(a, before, ed):
    """Paste a region of another entry's finished picture - one note drawn
    once, then stamped into every sheet that carries a copy. Only pixels
    where this sheet showed the same original as the source are written,
    so a copy cut at a sheet edge takes just its visible part."""
    _, src_before, src_after = build(ed["stamp"], ENTRIES[ed["stamp"]])
    x0, y0, x1, y1 = ed["src"]
    tx, ty = ed["to"]
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            yy, xx = ty + y - y0, tx + x - x0
            if 0 <= yy < a.shape[0] and 0 <= xx < a.shape[1]                     and before[yy, xx] == src_before[y, x]:
                a[yy, xx] = src_after[y, x]


ENTRIES = {}


def build(name, spec):
    dec, _ = decompress(source_bytes(name))
    c = Canvas(name, dec, spec.get("section", 0), spec.get("items", [0]))
    a = c.array()
    before = a.copy()
    for ed in spec["edits"]:
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
            y0 = ed["y"]
            for dy, row in enumerate(rows):
                for dx, ch in enumerate(row):
                    if ch == "#":
                        a[y0 + dy, x0 + dx] = ed["ink"]
                        below = rows[dy + 1][dx] if dy + 1 < len(rows) and dx < len(rows[dy + 1]) else "."
                        if ed.get("drop") is not None and below != "#":
                            a[y0 + dy + 1, x0 + dx] = ed["drop"]
        elif "stamp" in ed:
            stamp(a, before, ed)
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
    c.store(a)
    return c, before, a


def entries(path):
    data = json.load(open(path, encoding="utf-8"))
    out = {k: v for k, v in data.items() if not k.startswith("_")}
    ENTRIES.update(out)
    return out


def lut(dec):
    """The container's palette when it has one, else a fixed false-colour map
    (the census crops' map, so previews match work/gfxcensus/crops)."""
    pal = palette(dec)
    if pal:
        return np.array(pal, np.uint8)
    t = np.random.RandomState(1).randint(0, 255, (256, 3)).astype(np.uint8)
    t[0] = 0
    return t


def cap_lut(a, png, ox, oy):
    """Index -> colour from a capture showing this canvas with its top-left
    at (ox, oy): the modal capture colour of each index. Indices the capture
    does not show stay grey."""
    from PIL import Image
    cap = np.asarray(Image.open(os.path.join(ROOT, png)).convert("RGB"))
    t = np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, 1)
    y0, x0 = max(0, -oy), max(0, -ox)
    y1 = min(a.shape[0], cap.shape[0] - oy)
    x1 = min(a.shape[1], cap.shape[1] - ox)
    sub = a[y0:y1, x0:x1]
    c = cap[y0 + oy:y1 + oy, x0 + ox:x1 + ox]
    for i in np.unique(sub):
        vals, n = np.unique(c[sub == i], axis=0, return_counts=True)
        t[i] = vals[n.argmax()]
    return t


def preview(path, out, scale=3):
    from PIL import Image
    os.makedirs(out, exist_ok=True)
    for name, spec in entries(path).items():
        c, before, after = build(name, spec)
        t = lut(c.dec)
        if spec.get("preview_cap"):
            t = cap_lut(before, *spec["preview_cap"])
        elif spec.get("preview_lut") == "grey":
            lo, hi = np.percentile(before, 1), np.percentile(before, 99)
            v = np.clip((np.arange(256) - lo) / max(hi - lo, 1) * 255, 0, 255)
            t = np.repeat(v.astype(np.uint8)[:, None], 3, 1)
        crop = spec.get("crop")
        if crop:
            x0, y0, x1, y1 = crop
            before, after = before[y0:y1 + 1, x0:x1 + 1], after[y0:y1 + 1, x0:x1 + 1]
        gap = np.full((before.shape[0], 4, 3), 40, np.uint8)
        im = Image.fromarray(np.hstack([t[before], gap, t[after]]))
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
        dst = os.path.join(out, f"{spec.get('tag', name)}.png")
        im.save(dst)
        print(dst)


def apply(path):
    os.makedirs(DST_DIR, exist_ok=True)
    pristine = open(os.path.join(ROOT, "discs/extracted_ps1", "SLPS_001.54"), "rb").read()
    exe_path = os.path.join(DST_DIR, "SLPS_001.54")
    exe = bytearray(open(exe_path, "rb").read())
    for name, spec in entries(path).items():
        c, _, _ = build(name, spec)
        packed = compress(bytes(c.dec))
        assert decompress(packed)[0] == bytes(c.dec), f"{name}: roundtrip mismatch"
        resize(exe, pristine, name, len(packed))
        original = len(source_bytes(name))
        print(f"{name}: {len(packed)} bytes (original {original}, {len(packed) - original:+d})")
        open(os.path.join(DST_DIR, name + ".BIN"), "wb").write(packed)
    open(exe_path, "wb").write(bytes(exe))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preview", "apply"])
    ap.add_argument("--text", default=TEXT)
    ap.add_argument("--out", default=os.path.join(WORK, "gfx", "labels"))
    a = ap.parse_args()
    preview(a.text, a.out) if a.cmd == "preview" else apply(a.text)
