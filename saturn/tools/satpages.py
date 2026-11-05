"""Bake the PS1's English into the Saturn's text-bearing background pictures.

The Saturn keeps the pages the PS1 port had to redraw as plain VDP2
backgrounds (satgfx.py type 0: 8-bpp 16x16 characters), so the port is a
pixel edit of the decoded chunk, no draw list, no atlas:

  chunk 369  the red New Game disclaimer (PS1 CXD_B000): 480x256, the screen
             shows its top-left 320x240; five 16-px lines at pitch 20 from
             y 68, x 18..294, white index 6 on red 1/2 (the JP glyphs are
             anti-aliased with 3/4/5; the English is drawn 1-bit, each line
             centred on the screen and the block centred vertically)
  268..280   Gibson's thirteen memo pages (PS1 CPC_B000..B0C0, in order):
             240x128 (279 is a 480x256 chunk with the page in its top-left),
             lines on the PS1's own grid - 9-px glyph band on a 12-px pitch
             from y 25, text column x 21..228 (the PS1's is 17..183, so
             every PS1 line fits) - ink 7 on background 2; 274 and 275 carry
             a photograph (150..210 x 50..97 / 148..207 x 30..111, palettes of
             their own: ink 255 on 17 / 15).

English comes straight from the PS1 data (ps1/translation/gfx_pages.json,
disclaimer.json) and is rendered with MS Gothic - 12 px on the pages as
ps1/tools/gfxpages.py does, 16 px on the disclaimer to match the Saturn's
16-px Japanese there.  Output is the DECODED chunk in
patched/saturn/chunks/NNN.bin (the satdisc chunk-list rebuild packs it);
previews (before/after, 3x) in work/saturn/gfx/pages/.

  chunk 267  Gibson's diary as the COMPUTER draws it (Gibson's study and the
             Act 2 recap; Luiz 2026-09-16, #46 - the VDP2 pages above are
             not what that screen shows): ten sprite lists (3..12 = the PS1's
             CPC_B000..B090; the Saturn's diary stops at page 10) of 8-bpp
             text pieces cropped to the writing, plus a photograph on lists 9
             and 10, three palettes (list 9 the second, 10 the third: ink
             255 on 17 / 15; the rest ink 7 on 2). Rebuilt as one text block
             per page at the page's own origin ((16, 24); 9 and 10 at
             (16, 16)), cropped to the writing (8-px width steps), the
             photographs kept and drawn last; the pixel section keeps its
             150,912 bytes (it is copied to VDP1 VRAM whole).

Usage (repo root):
  python saturn/tools/satpages.py preview [disclaimer|memo|diary]
  python saturn/tools/satpages.py apply   [disclaimer|memo|diary]
"""
import os, sys, json, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]
import sysfont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import satgfx

PAGES_JSON = os.path.join(ROOT, "ps1", "translation", "gfx_pages.json")
DISCLAIMER_JSON = os.path.join(ROOT, "ps1", "translation", "disclaimer.json")
PREVIEW_DIR = os.path.join(WORK, "saturn", "gfx", "pages")
FONT = "msgothic.ttc"

# memo pages: PS1 name -> chunk
MEMO = {f"CPC_B{i:02X}0": 268 + i for i in range(13)}
MEMO_LEFT, MEMO_RIGHT = 21, 228
MEMO_TOP, MEMO_PITCH, MEMO_BAND = 25, 12, 9
MEMO_CLEAR = (20, 10, 231, 118)          # x0, y0, x1, y1 inclusive
MEMO_PAGE = (240, 128)
PHOTOS = {274: (150, 210, 50, 97), 275: (148, 207, 30, 111)}   # x0, x1, y0, y1 inclusive

DISC_CHUNK = 369
DISC_CLEAR = (16, 64, 295, 167)
DISC_LEFT, DISC_TOP, DISC_PITCH, DISC_PX = 18, 68, 20, 16
DISC_INK, DISC_BG = 6, 2
DISC_RIGHT = 296
DISC_SCREEN = (320, 240)


class Bitmap:
    """A type-0 section as a row-major 8-bpp canvas."""

    def __init__(self, idx):
        self.idx = idx
        self.dec = satgfx.load(idx)
        self.secs = satgfx.parse(self.dec)
        self.k, (t, o, s) = next((k, e) for k, e in enumerate(self.secs) if e[0] == 0)
        self.off, self.size = o, s
        self.W, self.H, pix = satgfx.bg_pixels(self.dec, o, s)
        self.pix = bytearray(pix)
        self.pal = satgfx.palettes(self.dec, self.secs)[0]

    def get(self, x, y):
        return self.pix[y * self.W + x]

    def set(self, x, y, v):
        self.pix[y * self.W + x] = v

    def fill(self, rect, v, keep=None):
        x0, y0, x1, y1 = rect
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if keep and keep[0] <= x <= keep[1] and keep[2] <= y <= keep[3]:
                    continue
                self.set(x, y, v)

    def draw_line(self, text, x, y, ink, px, limit, thresh=96, band=None):
        """Render `text` at (x, y) with MS Gothic `px`; returns the ink width
        (pixels past `limit` are dropped and reported by the caller)."""
        from PIL import Image, ImageDraw, ImageFont
        font = sysfont.truetype(FONT, px)
        h = band or px + 4
        img = Image.new("L", (self.W, h), 0)
        ImageDraw.Draw(img).text((0, -1 if px == 12 else 0), text, fill=255, font=font)
        p = img.load()
        wide = 0
        for yy in range(h):
            for xx in range(img.width):
                if p[xx, yy] > thresh:
                    wide = max(wide, xx + 1)
                    if x + xx <= limit and y + yy < self.H:
                        self.set(x + xx, y + yy, ink)
        return wide

    def image(self):
        return satgfx.image_from(self.W, self.H, bytes(self.pix), self.pal)

    def packed(self):
        new = satgfx.bg_pack(self.W, self.H, bytes(self.pix))
        parts = [(t, self.dec[o:o + s]) for t, o, s in self.secs]
        parts[self.k] = (0, new)
        out = satgfx.build(parts, satgfx.terminator(self.dec))
        assert satgfx.parse(out) == self.secs
        return out


def colours(bm, rect, keep=None):
    """(background, ink) of a page: the commonest index in the text column
    and the brightest of the next few, as ps1/tools/gfxpages.py measures."""
    counts = {}
    x0, y0, x1, y1 = rect
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if keep and keep[0] <= x <= keep[1] and keep[2] <= y <= keep[3]:
                continue
            v = bm.get(x, y)
            counts[v] = counts.get(v, 0) + 1
    order = sorted(counts, key=counts.get, reverse=True)
    bg = order[0]
    ink = max(order[1:4], key=lambda k: sum(bm.pal[k]))
    return bg, ink


def build_memo(name, lines):
    idx = MEMO[name]
    bm = Bitmap(idx)
    photo = PHOTOS.get(idx)
    bg, ink = colours(bm, MEMO_CLEAR, photo)
    bm.fill(MEMO_CLEAR, bg, photo)
    over = []
    for i, text in enumerate(lines):
        if not text:
            continue
        y = MEMO_TOP + MEMO_PITCH * i
        right = MEMO_RIGHT
        if photo and photo[2] <= y + MEMO_BAND - 1 and y <= photo[3]:
            right = photo[0] - 3
        wide = bm.draw_line(text, MEMO_LEFT, y, ink, 12, right, band=MEMO_BAND + 2)
        if MEMO_LEFT + wide - 1 > right:
            over.append((i, MEMO_LEFT + wide - 1 - right, text))
    return bm, over


def build_disclaimer(lines):
    """Each line centred on the 320-px screen and the block centred in its
    240 rows, as ps1/tools/disclaimer.py lays the PS1's out (the chunk's
    x 0..319 is the screen's)."""
    bm = Bitmap(DISC_CHUNK)
    bm.fill(DISC_CLEAR, DISC_BG)
    over = []
    top = (DISC_SCREEN[1] - ((len(lines) - 1) * DISC_PITCH + DISC_PX)) // 2
    for i, text in enumerate(lines):
        y = top + DISC_PITCH * i
        wide = bm.draw_line(text, 0, y, DISC_INK, DISC_PX, -1, band=DISC_PITCH)
        left = max(DISC_LEFT, (DISC_SCREEN[0] - wide) // 2)
        bm.draw_line(text, left, y, DISC_INK, DISC_PX, DISC_RIGHT, band=DISC_PITCH)
        if left + wide - 1 > DISC_RIGHT:
            over.append((i, left + wide - 1 - DISC_RIGHT, text))
    return bm, over


# --- the diary sprites (chunk 267) ------------------------------------------
DIARY_CHUNK = 267
DIARY_PAGES = {3 + i: f"CPC_B{i:02X}0" for i in range(10)}       # list -> PS1 page
DIARY_ORIGIN = {9: (16, 16), 10: (16, 16)}                     # the rest (16, 24)
DIARY_INK = {512: (17, 255), 768: (15, 255)}                   # clut -> (bg, ink); 256 -> (2, 7)
DIARY_PHOTOS = {9: [2], 10: [5]}                               # list -> piece indices kept
DIARY_RIGHT, DIARY_BOTTOM = 232, 120                           # the page area
DIARY_PITCH, DIARY_BAND = 12, 9


def diary_lists(dec, secs):
    """(anims, lists) of the sprite index: anims as [(list, frames)], lists as
    [6-tuple records] (None for the three lists whose offset is 0: unused)."""
    t, o, s = secs[2]
    nA, nB = struct.unpack_from(">HH", dec, o)
    offA = [struct.unpack_from(">I", dec, o + 16 + 4 * i)[0] for i in range(nA)]
    offB = [struct.unpack_from(">I", dec, o + 16 + 4 * nA + 4 * i)[0] for i in range(nB)]
    anims = []
    for a in offA:
        n = struct.unpack_from(">H", dec, o + a)[0]
        anims.append([struct.unpack_from(">HH", dec, o + a + 2 + 4 * k) for k in range(n)])
    lists = []
    for ob in offB:
        if ob == 0:
            lists.append(None)
            continue
        cnt = struct.unpack_from(">H", dec, o + ob)[0]
        lists.append([struct.unpack_from(">6H", dec, o + ob + 8 + 12 * k) for k in range(cnt)])
    return anims, lists


def render_block(lines, W, H, bg, ink, right, photo=None, x0=0, y0=0):
    """The page's lines on a W x H canvas of `bg` at 12-px pitch (MS Gothic 12),
    the writing from (x0, y0); lines on the photograph's rows stop 3 px short
    of it. Returns (pixels, over-wide lines)."""
    from PIL import Image, ImageDraw, ImageFont
    font = sysfont.truetype(FONT, 12)
    pix = bytearray([bg]) * (W * H)
    over = []
    for i, text in enumerate(lines):
        if not text:
            continue
        y = y0 + DIARY_PITCH * i
        limit = right
        if photo and photo[2] <= y + DIARY_BAND - 1 and y <= photo[3]:
            limit = photo[0] - 3
        img = Image.new("L", (W, DIARY_BAND + 2), 0)
        ImageDraw.Draw(img).text((0, -1), text, fill=255, font=font)
        p = img.load()
        wide = 0
        for yy in range(img.height):
            for xx in range(W):
                if p[xx, yy] > 96:
                    wide = max(wide, xx + 1)
                    if x0 + xx <= limit and y + yy < H:
                        pix[(y + yy) * W + x0 + xx] = ink
        if x0 + wide - 1 > limit:
            over.append((i, x0 + wide - 1 - limit, text))
    return pix, over


def crop_block(pix, W, H, bg, x0, y0):
    """The block from (x0, y0) to the writing's extent, its width in 8-px steps."""
    x1 = y1 = 0
    for y in range(H):
        for x in range(W):
            if pix[y * W + x] != bg:
                x1, y1 = max(x1, x), max(y1, y)
    w = max(8, ((x1 - x0 + 1) + 7) // 8 * 8)
    h = max(1, y1 - y0 + 1)
    out = bytearray()
    for y in range(y0, y0 + h):
        out += pix[y * W + x0:y * W + x0 + w]
    return bytes(out), w, h


def build_diary():
    """The decoded chunk 267 with the English pages: (dec, over-wide lines, report)."""
    data = json.load(open(PAGES_JSON, encoding="utf-8"))
    dec = satgfx.load(DIARY_CHUNK)
    secs = satgfx.parse(dec)
    (t0, o0, s0), (t1, o1, s1), (t2, o2, s2) = secs
    anims, lists = diary_lists(dec, secs)
    pixels = bytearray()
    new_lists = list(lists)
    over, report = [], []
    for li, page in DIARY_PAGES.items():
        recs = lists[li]
        clut = recs[0][2]
        bg, ink = DIARY_INK.get(clut, (2, 7))
        x0, y0 = DIARY_ORIGIN.get(li, (16, 24))
        photos = []
        for k in DIARY_PHOTOS.get(li, []):
            c, sz, cl, sr, x, y = recs[k]
            w, h = sz >> 8, sz & 255
            photos.append((c, w, h, cl, x, y, dec[o0 + sr * 8:o0 + sr * 8 + w * h]))
        photo = None
        if photos:
            c, w, h, cl, x, y, _ = photos[0]
            photo = (x, x + w - 1, y, y + h - 1)
        W, H = DIARY_RIGHT, DIARY_BOTTOM
        pix, ov = render_block(data[page], W, H, bg, ink, DIARY_RIGHT - 1, photo, x0, y0)
        over += [(page, i, px, text) for i, px, text in ov]
        block, w, h = crop_block(pix, W, H, bg, x0, y0)
        out = []
        while len(pixels) & 7:
            pixels.append(0)
        out.append((0x2000, (w << 8) | h, clut, len(pixels) // 8, x0, y0))
        pixels += block
        for c, pw, ph, cl, x, y, pb in photos:
            while len(pixels) & 7:
                pixels.append(0)
            out.append((c, (pw << 8) | ph, cl, len(pixels) // 8, x, y))
            pixels += pb
        new_lists[li] = out
        report.append(f"list {li} {page}: text {w}x{h} at ({x0},{y0}) ink {ink} on {bg}, "
                      f"{len(photos)} photo(s), {len(block)} B")
    assert len(pixels) <= s0, (len(pixels), s0)
    report.append(f"pixels {len(pixels)} of {s0} bytes")
    pixels += bytes(s0 - len(pixels))
    # The index keeps its bytes and every list its offset: anims 0-2 name lists 0-2,
    # whose offset is 0 - the HEADER read as records, and the game draws that "list"
    # (the object's frame before a page is picked). In the original those records
    # are the offA/offB tables: zero-sized or off-screen (y 872..944) pieces, so
    # nothing shows; a re-laid table put them on screen as 250-px garbage (the first
    # build, 2026-09-16). Each new list is shorter than the original's, so it is
    # written over it in place, the rest of the old records zeroed.
    index = bytearray(dec[o2:o2 + s2])
    nA, nB = struct.unpack_from(">HH", index, 0)
    offB = [struct.unpack_from(">I", index, 16 + 4 * nA + 4 * i)[0] for i in range(nB)]
    for li, L in enumerate(new_lists):
        if li not in DIARY_PAGES:
            continue
        ob = offB[li]
        old_n = len(lists[li])
        assert len(L) <= old_n, (li, len(L), old_n)
        struct.pack_into(">H", index, ob, len(L))
        for k in range(old_n):
            rec = L[k] if k < len(L) else (0, 0, 0, 0, 0, 0)
            struct.pack_into(">6H", index, ob + 8 + 12 * k, *rec)
    out = satgfx.build([(3, bytes(pixels)), (1, dec[o1:o1 + s1]), (2, bytes(index))], satgfx.terminator(dec))
    assert len(out) == len(dec), (len(out), len(dec))
    return out, over, report


def diary_image(dec, li):
    """A list of the diary composed on the page area, for the previews."""
    from PIL import Image
    secs = satgfx.parse(dec)
    (t0, o0, s0), (t1, o1, s1), (t2, o2, s2) = secs
    pals = [[struct.unpack_from(">H", dec, o1 + 512 * p + 2 * i)[0] for i in range(256)] for p in range(s1 // 512)]
    anims, lists = diary_lists(dec, secs)
    img = Image.new("RGB", (240, 128), (40, 40, 40))
    for c, sz, cl, sr, x, y in lists[li]:
        w, h = sz >> 8, sz & 255
        pal = pals[cl // 256 - 1]
        im = Image.new("RGB", (w, h))
        im.putdata([satgfx.rgb555(pal[b]) for b in dec[o0 + sr * 8:o0 + sr * 8 + w * h]])
        img.paste(im, (x, y))
    return img


def preview_diary():
    from PIL import Image
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    before = satgfx.load(DIARY_CHUNK)
    after, over, report = build_diary()
    for line in report:
        print("  " + line)
    for page, i, px, text in over:
        print(f"  diary {page} line {i}: {px}px too wide - {text!r}")
    sheet = Image.new("RGB", (240 * 2 + 8, 132 * 10), (255, 0, 255))
    for k, li in enumerate(DIARY_PAGES):
        sheet.paste(diary_image(before, li), (0, k * 132))
        sheet.paste(diary_image(after, li), (248, k * 132))
    sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(os.path.join(PREVIEW_DIR, "267_diary.png"))
    print(f"diary: chunk {DIARY_CHUNK} -> {PREVIEW_DIR}/267_diary.png")


def apply_diary():
    dec, over, report = build_diary()
    for line in report:
        print("  " + line)
    for page, i, px, text in over:
        print(f"  diary {page} line {i}: {px}px too wide - {text!r}")
    p = satgfx.write_chunk(DIARY_CHUNK, dec)
    print(f"diary: chunk {DIARY_CHUNK} -> {p} ({len(dec)} bytes decoded)")


def jobs(which):
    out = []
    if which in ("all", "disclaimer"):
        dlines = json.load(open(DISCLAIMER_JSON, encoding="utf-8"))["lines"]
        out.append(("disclaimer", DISC_CHUNK, lambda l=dlines: build_disclaimer(l)))
    if which in ("all", "memo"):
        data = json.load(open(PAGES_JSON, encoding="utf-8"))
        for name, lines in data.items():
            if name.startswith("_"):
                continue
            out.append((name, MEMO[name], (lambda n=name, l=lines: build_memo(n, l))))
    return out


def preview(which="all"):
    from PIL import Image
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    for name, idx, fn in jobs(which):
        before = Bitmap(idx).image().convert("RGB")
        bm, over = fn()
        for i, px, text in over:
            print(f"  {name} ({idx}) line {i}: {px}px too wide - {text!r}")
        after = bm.image().convert("RGB")
        W, H = before.size
        if idx == 279:
            before, after = before.crop((0, 0, 240, 128)), after.crop((0, 0, 240, 128))
            W, H = 240, 128
        if idx == DISC_CHUNK:
            before, after = before.crop((0, 0, 320, 240)), after.crop((0, 0, 320, 240))
            W, H = 320, 240
        sheet = Image.new("RGB", (W * 2 + 8, H), (255, 0, 255))
        sheet.paste(before, (0, 0))
        sheet.paste(after, (W + 8, 0))
        sheet.resize((sheet.width * 3, sheet.height * 3), Image.NEAREST).save(
            os.path.join(PREVIEW_DIR, f"{idx:03d}_{name}.png"))
        print(f"{name}: chunk {idx} -> {PREVIEW_DIR}/{idx:03d}_{name}.png")


def apply(which="all"):
    for name, idx, fn in jobs(which):
        bm, over = fn()
        for i, px, text in over:
            print(f"  {name} ({idx}) line {i}: {px}px too wide - {text!r}")
        dec = bm.packed()
        assert len(dec) == len(bm.dec), (len(dec), len(bm.dec))
        p = satgfx.write_chunk(idx, dec)
        print(f"{name}: chunk {idx} -> {p} ({len(dec)} bytes decoded)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    which = sys.argv[2] if len(sys.argv) > 2 else "all"
    if which in ("diary", "all"):
        {"preview": preview_diary, "apply": apply_diary}[cmd]()
    if which != "diary":
        {"preview": preview, "apply": apply}[cmd](which)
