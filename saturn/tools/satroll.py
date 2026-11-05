"""Bake the English opening captions and credit roll into the Saturn's sprites.

What plays after New Game, once the SNATCHER logo has gone: "2042.12 / NEO
KOBE CITY" on black, the cast and staff over the Neo Kobe skyline, and at
the end "Konami Omni Building / JUNKER HQ" typed out under the tower. None
of it is text: both are VDP1 sprites (8 bpp) cut from DATA.BIN chunks.

  chunk 394  the credit roll, "2042.12 / ネオコウベシティ" included (the PS1's
             CXD_BX30), decoded at 0x06048000 (the second in-place decode
             region), 118,280 B. Konami's sections: palette, sprite index,
             the pixels (91,648 B, copied whole to VDP1 VRAM 0x65000), a
             second pixel section nothing uses. The index says 23 lists but
             its offset table holds nB + 2 entries: entry 0 is 0, list 23
             (制作・著作 コナミ株式会社) is the one past the count. The script
             plays anims 0..22; anim k's record names list j and draws
             table entry j + 1 (so the swapped anims 17..19 give the play
             order ..17, 19, 20, 18, 21..). One list per screen, a few 16-px
             pieces each (words cut from a shared strip), on 320-px screen
             coordinates. Pixels: 1-px outline index 20 (dark blue) around a
             fill running 1 (white, bottom-left of each glyph) to ~16
             (lavender, top-right); 0 is transparent.
             THE TRAP: after screen 10 the street scene streams chunk 387
             into the region below, and Konami's stream for 387 decodes a
             garbage tail (satpack.py: in-place margin -3688) that reads on
             into 394's bytes - [0x2E0, 0x7B40) and the 40-byte header, found
             by injecting ours into RAM at frame 17,600 and diffing (work/
             saturn/roll/window.py). Different bytes there sent the garbage
             decode elsewhere and wedged the opening at ~17,640 (the first
             build). So the rebuilt chunk keeps Konami's bytes at
             [0x228, 0x8000) where they are - as an unused second palette
             section - and puts the English after them: [palette][kept bytes,
             type 1][English pixels, type 3][index, type 2], the same 118,280
             B. Only the header differs inside the read range: it lands as 64
             bytes of garbage in the bottom row of 387's 480x256 background
             (0x34EE0.., off screen), the control flow unchanged. The second
             pixel section is dropped (never uploaded during the opening).
             The English: one piece per line (per column when a line has
             two), cropped to its ink, each line centred on x 160 on the
             original rows; identical runs share their pixels; the index is
             rebuilt in Konami's order (tables, lists, anims), the anims as
             they were.
  chunk 452  the opening's big sprite sheet (the tower, the city; VDP1 VRAM
             0x19000, no index of its own - chunk 453's lists 79..94 draw
             it). The JUNKER HQ caption is a type-on: 40x32 pieces, each
             holding the caption as far as it has typed within its 40
             columns, drawn over one another (line 1 at rows 3..12, line 2
             at 17..28; grey levels 59 shadow, 105/149/191 anti-alias, 255
             white; the last frame, list 94, adds 部). Every piece is
             rewritten in place: line 1 becomes
             "KONAMI OMNI BLDG", line 2 keeps Konami's JUNKER and 本部 becomes
             "HQ" in a matching serif; each piece shows the English up to
             the column its Japanese had typed to (snapped back to a whole
             letter), so the English types on in the same beats.

English: saturn/translation/staff_roll.json (screens in play order, the
caption). Output is the DECODED chunk in patched/saturn/chunks/NNN.bin
(satpack packs it); `apply` always starts from the pristine chunks
(work/saturn/data_bin, or DATA.BIN), so it can be re-run. Previews, before
and after, in work/saturn/gfx/roll/.

Usage (repo root):
  python saturn/tools/satroll.py preview [roll|caption]
  python saturn/tools/satroll.py apply   [roll|caption]
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

TEXT = os.path.join(ROOT, "saturn", "translation", "staff_roll.json")
PREVIEW_DIR = os.path.join(WORK, "saturn", "gfx", "roll")

# --- the roll (chunk 394) ----------------------------------------------------
ROLL_CHUNK = 394
SCREEN_W = 320
CELL_H = 16                   # piece height, as the Japanese
OUTLINE = 20
FILL_MIN, FILL_MAX = 1, 16
# (font, size, tracking, row of the capitals' top in the 16-px row)
BIG_STYLE = ("ARIALNB.TTF", 17, 0, 1)    # titles, roles, people: the Japanese 16-px glyphs
SMALL_STYLE = ("arialbd.ttf", 12, 3, 3)  # the cast screens' character names, set small as the Japanese
SMALL_LINES = {(L, 0) for L in range(3, 11)}   # (list, line)
GAP = 28                      # between two columns on one line
CTRL, CLUT = 0x2000, 256      # every Japanese piece's
KEEP = (0x228, 0x8000)        # Konami's bytes, kept where they are (see the docstring)


def list_offsets(dec, o):
    """A sprite index's list offsets. The table holds nB + 2 entries, not the
    nB satgfx.index reads: entry 0 is 0 (no list), and one past nB is a real
    list in 453 (94, the caption's last frame); 394's nB + 1 is the roll's
    last screen and its nB + 2 is 0."""
    nA, nB = struct.unpack_from(">HH", dec, o)
    return list(struct.unpack_from(f">{nB + 2}I", dec, o + 16 + 4 * nA))


def read_lists(dec, o, which=None):
    """{list: [(ctrl, w, h, clut, srca, x, y)]} of the index at `o` (x, y signed)."""
    out = {}
    for L, ob in enumerate(list_offsets(dec, o)):
        if ob == 0 or (which is not None and L not in which):
            continue
        cnt = struct.unpack_from(">H", dec, o + ob)[0]
        recs = []
        for k in range(cnt):
            c, sz, cl, sa, x, y = struct.unpack_from(">6H", dec, o + ob + 8 + 12 * k)
            recs.append((c, sz >> 8, sz & 255, cl, sa, x - 65536 if x & 0x8000 else x,
                         y - 65536 if y & 0x8000 else y))
        out[L] = recs
    return out


def section(secs, kind):
    """(offset, size) of the first section of a type."""
    return next((o, s) for t, o, s in secs if t == kind)


def roll_lists(dec, secs):
    return read_lists(dec, section(secs, 2)[0])


def line_rows(recs):
    """The distinct text rows of a screen (pieces within 2 px are one row)."""
    rows = []
    for y in sorted({r[6] for r in recs}):
        if rows and y - rows[-1] <= 2:
            continue
        rows.append(y)
    return rows


def _font(spec):
    from PIL import ImageFont
    return sysfont.truetype(spec[0], spec[1])


def _ink(font, ch):
    """First and last ink column of a letter drawn 1-bit at x 0."""
    import numpy as np
    from PIL import Image, ImageDraw
    img = Image.new("L", (64, 40), 0)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    d.text((8, 4), ch, fill=255, font=font)
    cols = np.nonzero(np.array(img).any(0))[0]
    return (int(cols.min()) - 8, int(cols.max()) - 8) if len(cols) else (0, 0)


def render_run(text, style):
    """A run drawn on the 16-px row as fill indices + outline (0 transparent),
    cropped to its ink (rows, and columns to a multiple of 8): (array, ink
    width, left padding, first row relative to the row's y)."""
    import numpy as np
    from PIL import Image, ImageDraw
    font, track, cap_row = _font(style[:2]), style[2], style[3]
    # `track` px between letters (the Japanese is set wide); with none the
    # run is drawn whole, which keeps the font's own spacing
    if track:
        # set by ink: every letter `track` px clear of the one before
        starts = [1.0]
        for ch in text:
            if ch == " ":
                starts.append(starts[-1] + font.getlength(ch) + track)
            else:
                l, r = _ink(font, ch)
                starts.append(starts[-1] + (r - l + 1) + track)
    else:
        starts = [1.0 + font.getlength(text[:i]) for i in range(len(text) + 1)]
    img = Image.new("L", (int(starts[-1]) + 8, CELL_H + 6), 0)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    cap_top = font.getbbox("H")[1]
    if track:
        for ch, x in zip(text, starts):
            d.text((round(x) - _ink(font, ch)[0], cap_row - cap_top), ch, fill=255, font=font)
    else:
        d.text((1, cap_row - cap_top), text, fill=255, font=font)
    mask = np.array(img) > 0
    out = np.zeros(mask.shape, np.uint8)
    grow = mask.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            grow |= np.roll(np.roll(mask, dy, 0), dx, 1)
    out[grow & ~mask] = OUTLINE
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys, xs):
        k = max(0, min(len(text) - 1, next((i for i in range(len(text)) if starts[i + 1] > x), len(text) - 1)))
        adv = max(4.0, starts[k + 1] - starts[k])
        xr = (x - starts[k]) * 16.0 / adv
        v = 1 + 0.6 * xr + 0.3 * (15 - y)
        out[y, x] = max(FILL_MIN, min(FILL_MAX, int(round(v))))
    cols = np.nonzero(out.any(0))[0]
    rows = np.nonzero(out.any(1))[0]
    top = int(rows.min())
    out = out[top:rows.max() + 1, cols.min():cols.max() + 1]
    w = (out.shape[1] + 7) & ~7            # VDP1 widths are multiples of 8
    pad = np.zeros((out.shape[0], w), np.uint8)
    lead = (w - out.shape[1]) // 2
    pad[:, lead:lead + out.shape[1]] = out
    return pad, out.shape[1], lead, top


def roll_anims(dec, o):
    """[[(list, frames)]] of the index at `o`: anim k's record names list j,
    and the list drawn is offset-table entry j + 1."""
    nA = struct.unpack_from(">H", dec, o)[0]
    out = []
    for k in range(nA):
        a = o + struct.unpack_from(">I", dec, o + 16 + 4 * k)[0]
        n = struct.unpack_from(">H", dec, a)[0]
        out.append([struct.unpack_from(">HH", dec, a + 2 + 4 * i) for i in range(n)])
    return out


def build_index(anims, lists, n_entries):
    """A sprite index as Konami lays it out: 16-byte head {nA, nB}, anim
    offsets, n_entries list offsets (entry 0 = 0), the lists (8-byte head,
    12-byte records), then the anims."""
    nA = len(anims)
    head = 16 + 4 * nA + 4 * n_entries
    body = bytearray()
    loffs = [0] * n_entries
    for L in sorted(lists):
        loffs[L] = head + len(body)
        recs = lists[L]
        body += struct.pack(">H6x", len(recs))
        for c, w, h, cl, sa, x, y in recs:
            body += struct.pack(">6H", c, (w << 8) | h, cl, sa, x & 0xFFFF, y & 0xFFFF)
    aoffs = []
    for a in anims:
        aoffs.append(head + len(body))
        body += struct.pack(">H", len(a)) + b"".join(struct.pack(">HH", j, f) for j, f in a)
    return struct.pack(">HH12x", nA, n_entries - 2) + b"".join(struct.pack(">I", a) for a in aoffs)         + b"".join(struct.pack(">I", l) for l in loffs) + bytes(body)


def build_roll():
    """(decoded chunk, report lines)."""
    spec = json.load(open(TEXT, encoding="utf-8"))["screens"]
    dec = satgfx.load(ROLL_CHUNK)
    secs = satgfx.parse(dec)
    (t0, o0, s0), (t1, o1, s1), (t2, o2, s2), (t3, o3, s3) = secs
    assert (t0, t1, t2, t3) == (1, 2, 3, 3) and o1 == KEEP[0]
    lists = roll_lists(dec, secs)
    anims = roll_anims(dec, o1)
    pixels = bytearray()
    cache = {}
    new_lists, report = {}, []

    def place(text, style):
        if (text, style) not in cache:
            arr, ink, lead, top = render_run(text, style)
            if arr.shape[1] > 255:
                raise SystemExit(f"{text!r} is {arr.shape[1]} px wide - a piece holds 255")
            cache[text, style] = (len(pixels) // 8, arr.shape[1], arr.shape[0], top, ink, lead)
            pixels.extend(arr.tobytes())
        return cache[text, style]

    seen = set()
    for scr in spec:
        L, lines = scr["list"], scr["lines"]
        if L not in lists or L in seen:
            raise SystemExit(f"screen list {L}: not a list of chunk {ROLL_CHUNK} (or twice)")
        seen.add(L)
        rows = line_rows(lists[L])
        if len(rows) != len(lines):
            raise SystemExit(f"list {L}: {len(lines)} lines of English, {len(rows)} rows on screen")
        recs = []
        for i, (y, line) in enumerate(zip(rows, lines)):
            style = SMALL_STYLE if (L, i) in SMALL_LINES else BIG_STYLE
            parts = [p.strip() for p in line.split("  ") if p.strip()]
            laid = [place(p, style) for p in parts]
            total = sum(p[4] for p in laid) + GAP * (len(parts) - 1)
            x = (SCREEN_W - total) // 2
            if x < 4:
                report.append(f"list {L}: {line!r} is {total} px - past the screen edge")
            for sa, w, h, top, ink, lead in laid:
                recs.append((CTRL, w, h, CLUT, sa, x - lead, y + top))
                x += ink + GAP
        new_lists[L] = recs
        report.append(f"list {L:2d}: " + " / ".join(lines))
    missing = set(lists) - seen
    if missing:
        raise SystemExit(f"lists with no English: {sorted(missing)}")
    index = build_index(anims, new_lists, len(list_offsets(dec, o1)))
    # [pal][the kept bytes as an unused palette section][English pixels][index],
    # the whole no longer than Konami's (the region after it is not ours)
    keep = dec[KEEP[0]:KEEP[1]]
    room = len(dec) - KEEP[1] - len(index)
    if len(pixels) > room:
        raise SystemExit(f"roll pixels {len(pixels)} B, room for {room} - shorten a line in {TEXT}")
    report.append(f"pixels {len(pixels)} B, {room - len(pixels)} to spare; {len(cache)} runs; index {len(index)} B")
    index += bytes(len(dec) - KEEP[1] - len(pixels) - len(index))
    out = satgfx.build([(1, dec[o0:o0 + s0]), (1, keep), (3, bytes(pixels)), (2, index)],
                       satgfx.terminator(dec))
    assert len(out) == len(dec), (len(out), len(dec))
    assert out[:o0] != dec[:o0] and out[o0:KEEP[1]] == dec[o0:KEEP[1]]
    return out, report


def roll_screen(dec, L, bg=(24, 24, 56)):
    """One list composed on a 320x160 screen strip, for the previews."""
    from PIL import Image
    secs = satgfx.parse(dec)
    pal = satgfx.palettes(dec, secs)[0]
    so = section(secs, 3)[0]
    im = Image.new("RGB", (SCREEN_W, 160), bg)
    px = im.load()
    for c, w, h, cl, sa, x, y in roll_lists(dec, secs)[L]:
        src = so + sa * 8
        for yy in range(h):
            for xx in range(w):
                v = dec[src + yy * w + xx]
                if v and 0 <= x + xx < SCREEN_W and 0 <= y + yy < 160:
                    px[x + xx, y + yy] = pal[v]
    return im


def preview_roll():
    from PIL import Image
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    before = satgfx.load(ROLL_CHUNK)
    after, report = build_roll()
    for line in report:
        print("  " + line)
    order = [s["list"] for s in json.load(open(TEXT, encoding="utf-8"))["screens"]]
    sheet = Image.new("RGB", (SCREEN_W * 2 + 8, 164 * len(order)), (255, 0, 255))
    for k, L in enumerate(order):
        sheet.paste(roll_screen(before, L), (0, k * 164))
        sheet.paste(roll_screen(after, L), (SCREEN_W + 8, k * 164))
    p = os.path.join(PREVIEW_DIR, "394_roll.png")
    sheet.save(p)
    print(f"roll: chunk {ROLL_CHUNK} -> {p}")


def apply_roll():
    dec, report = build_roll()
    for line in report:
        print("  " + line)
    p = satgfx.write_chunk(ROLL_CHUNK, dec)
    print(f"roll: chunk {ROLL_CHUNK} -> {p} ({len(dec)} bytes decoded)")


# --- the JUNKER HQ caption (chunk 452, drawn by chunk 453's lists) ------------
CAP_CHUNK, CAP_LISTS_CHUNK = 452, 453
CAP_LISTS = range(79, 95)            # the type-on, first frame to the last (94)
CAP_X0 = 58                          # the lists' leftmost piece
CAP_W, CAP_H = 160, 34               # canvas: list x 58..217, caption rows -1..32
CAP_Y0 = -1
BAND1 = (0, 16)                      # caption rows of line 1 / line 2
BAND2 = (16, 33)
SHADOW, WHITE = 59, 255              # (Konami's anti-alias greys 105/149/191 go unused)
LINE1 = (3, 5, 122)                  # the Japanese line 1: rows 3..12, columns 5..122
LINE2_TOP = 17                       # JUNKER: rows 17..28 (J 4 .. R 91)
HQ = (93, 100, 126)                  # 本部 at 94..124; (JUNKER kept below, HQ from, to)
LINE1_FONT = ("arial.ttf", 11)       # set as wide as the Japanese (tracking fitted)
HQ_FONT = ("times.ttf", 16)
SNAP = 4                             # a letter ending this far past what a piece had typed still shows


def cap_lists():
    dec = satgfx.load(CAP_LISTS_CHUNK)
    t, o, s = next(e for e in satgfx.parse(dec) if e[0] == 2)
    return read_lists(dec, o, set(CAP_LISTS))


def cap_pieces():
    """({offset into 452's pixels: (w, h, canvas x, caption row)} of every
    piece the type-on draws, the offsets the last frame draws)."""
    lists = cap_lists()
    pieces = {}
    for L in CAP_LISTS:
        for c, w, h, cl, sa, x, y in lists[L]:
            pieces[sa * 8] = (w, h, x - CAP_X0, y)
    last = {sa * 8 for c, w, h, cl, sa, x, y in lists[CAP_LISTS[-1]]}
    return pieces, last


def shadowed(q):
    """Konami's drop shadow: 59 right, below and below-right of the ink."""
    import numpy as np
    ink = q > 0
    sh = np.zeros_like(ink)
    sh[:, 1:] |= ink[:, :-1]
    sh[1:, :] |= ink[:-1, :]
    sh[1:, 1:] |= ink[:-1, :-1]
    out = q.copy()
    out[sh & ~ink] = SHADOW
    return out


def caption_text(text, spec, top, left, right):
    """The text 1-bit in white with its shadow on a canvas of CAP_H rows
    (canvas row = caption row - CAP_Y0), the capitals from caption row
    `top`, from column `left`, letters spaced as widely (up to 4 px clear)
    as still ends by `right`: (canvas, the right edge of every letter,
    shadow included)."""
    for track in range(4, -1, -1):
        out = _caption_text(text, spec, top, left, track)
        if out[1][-1] <= right:
            break
    return out


def _caption_text(text, spec, top, left, track):
    import numpy as np
    from PIL import Image, ImageDraw
    font = _font(spec)
    img = Image.new("L", (CAP_W + 64, CAP_H), 0)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    cap_top = font.getbbox("H")[1]
    x, edges = float(left), []
    for ch in text:
        if ch == " ":
            x += font.getlength(ch) + track
            continue
        l, r = _ink(font, ch)
        d.text((round(x) - l, top - CAP_Y0 - cap_top), ch, fill=255, font=font)
        edges.append(round(x) + (r - l) + 1)
        x += (r - l + 1) + track
    q = np.where(np.array(img) > 0, WHITE, 0).astype(np.uint8)
    return shadowed(q), edges


def build_caption():
    """(decoded chunk 452, report)."""
    import numpy as np
    cap = json.load(open(TEXT, encoding="utf-8"))["caption"]
    dec = bytearray(satgfx.load(CAP_CHUNK))
    t, so, ss = satgfx.parse(bytes(dec))[0]
    assert t == 3
    pieces, last = cap_pieces()
    report = []

    def piece(off):
        w, h, x, y = pieces[off]
        return np.frombuffer(bytes(dec[so + off:so + off + w * h]), np.uint8).reshape(h, w).copy()

    # the original last frame, to keep Konami's JUNKER from
    orig = np.zeros((CAP_H, CAP_W + 64), np.uint8)
    for off, (w, h, x, y) in pieces.items():
        a = piece(off)
        reg = orig[y - CAP_Y0:y - CAP_Y0 + h, x:x + w]
        reg[a > 0] = a[a > 0]

    l1, edges1 = caption_text(cap[0], LINE1_FONT, LINE1[0], LINE1[1], LINE1[2])
    l2, edges2 = caption_text(cap[1], HQ_FONT, LINE2_TOP, HQ[1], HQ[2])
    b2 = BAND2[0] - CAP_Y0
    eng = np.zeros_like(orig)
    eng[:b2] = l1[:b2]
    eng[b2:] = l2[b2:]
    eng[b2:, :HQ[0]] = orig[b2:, :HQ[0]]          # JUNKER stays Konami's

    # how far each piece had typed on each line; on each line the last
    # frame's furthest piece shows the English to its own right edge
    reach = {}
    for off, (w, h, x, y) in pieces.items():
        a = piece(off)
        for bi, (r0, r1) in enumerate((BAND1, BAND2)):
            rows = a[max(0, r0 - y):max(0, min(h, r1 - y))]
            cols = np.nonzero(rows.any(0))[0] if rows.size else []
            if len(cols):
                reach[off, bi] = x + int(cols.max())
    for bi, edges, text in ((0, edges1, cap[0]), (1, edges2, cap[1])):
        far = max((reach[k], k[0]) for k in reach if k[1] == bi and k[0] in last)[1]
        w, h, x, y = pieces[far]
        reach[far, bi] = x + w - 1
        if edges[-1] > x + w - 1:
            report.append(f"caption {text!r} ends at column {edges[-1]}, past the pieces' {x + w - 1}")
        report.append(f"caption line {bi + 1}: {text!r}, columns {min(e for e in edges) } .. {edges[-1]}")

    for off, (w, h, x, y) in pieces.items():
        a = piece(off)
        new = np.zeros_like(a)
        for bi, (r0, r1), edges, lo in ((0, BAND1, edges1, 0), (1, BAND2, edges2, HQ[0])):
            if (off, bi) not in reach:
                continue
            pr0, pr1 = max(0, r0 - y), max(0, min(h, r1 - y))
            if bi == 1:
                keep = (np.arange(w) + x < HQ[0])[None, :]
                new[pr0:pr1] = np.where(keep, a[pr0:pr1], new[pr0:pr1])
            got = reach[off, bi]
            if got < lo:
                continue
            far = got == x + w - 1
            cut = got if far else max([e for e in edges if e <= got + SNAP] or [-1])
            for cx in range(max(x, lo), min(x + w, cut + 1)):
                new[pr0:pr1, cx - x] = eng[pr0 + y - CAP_Y0:pr1 + y - CAP_Y0, cx]
        dec[so + off:so + off + w * h] = new.tobytes()
    return bytes(dec), report


def caption_frames(dec):
    """Each type-on frame (lists 79..94) composed, for the previews."""
    import numpy as np
    from PIL import Image
    lists = cap_lists()
    so = satgfx.parse(dec)[0][1]
    grey = np.full(256, 255, np.uint8)
    grey[0] = 0
    for v, g in ((SHADOW, 56), (105, 104), (149, 152), (191, 200), (WHITE, 248)):
        grey[v] = g
    frames = []
    for L in CAP_LISTS:
        can = np.zeros((CAP_H, CAP_W + 16), np.uint8)
        for c, w, h, cl, sa, x, y in lists[L]:
            a = np.frombuffer(dec[so + sa * 8:so + sa * 8 + w * h], np.uint8).reshape(h, w)
            reg = can[y - CAP_Y0:y - CAP_Y0 + h, x - CAP_X0:x - CAP_X0 + w]
            reg[a > 0] = a[a > 0]
        frames.append(Image.fromarray(grey[can]))
    return frames


def preview_caption():
    from PIL import Image
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    before = satgfx.load(CAP_CHUNK)
    after, report = build_caption()
    for line in report:
        print("  " + line)
    fb, fa = caption_frames(before), caption_frames(after)
    W = fb[0].width
    sheet = Image.new("L", (W * 2 + 8, (CAP_H + 4) * len(fb)), 90)
    for k, (b, a) in enumerate(zip(fb, fa)):
        sheet.paste(b, (0, k * (CAP_H + 4)))
        sheet.paste(a, (W + 8, k * (CAP_H + 4)))
    p = os.path.join(PREVIEW_DIR, "452_caption.png")
    sheet.resize((sheet.width * 3, sheet.height * 3), Image.NEAREST).save(p)
    print(f"caption: chunk {CAP_CHUNK} -> {p} ({len(fb)} type-on frames, before | after)")


def apply_caption():
    dec, report = build_caption()
    for line in report:
        print("  " + line)
    p = satgfx.write_chunk(CAP_CHUNK, dec)
    print(f"caption: chunk {CAP_CHUNK} -> {p} ({len(dec)} bytes decoded)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    which = sys.argv[2] if len(sys.argv) > 2 else "all"
    if cmd not in ("preview", "apply") or which not in ("all", "roll", "caption"):
        raise SystemExit(__doc__)
    if which in ("all", "roll"):
        {"preview": preview_roll, "apply": apply_roll}[cmd]()
    if which in ("all", "caption"):
        {"preview": preview_caption, "apply": apply_caption}[cmd]()
