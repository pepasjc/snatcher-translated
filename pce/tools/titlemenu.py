"""The title menu in English: NEW GAME / CONTINUE drawn into the sprite cells.

The title's two menu lines (初めから, セーブした所から) are not text: they are
16x16 sprite cells in the title block (rec 958, group 2 index 4), decoded
from two RLE streams by the display list at block offset 0x1b - stream A
(0x9542, 32 cells -> VRAM $6000) and stream B (0xa272, 28 cells -> $6800).
The sprite table places 32x32 sprites over them (line 1 at y=144: cells
A28 A29 / A30 A31, B0 B1 / B2 B3 and a 16x32 at x=144: B25 / B27 - a
tall sprite keeps its lower cell two slots on, as a 32-wide one would; line 2
at y=176: B4 B5 / B6 B7, B8 B9 / B10 B11, B20 B21 / B22 B23, a 32x16 at
x=176: A26 A27, and B24 under it), so each line is a band 32 rows tall,
80 (line 1) or 128 (line 2) pixels wide, with the glyphs straddling the
two cell rows. Palette 3: 12 white, 13 light blue, 15 mid blue, 14 blue,
2-5 the browns of the drop shadow; line 1 draws 13/14, line 2 12/15 (the
game recolours the selected line through the palette).

Both streams exist twice on the disc (the title block and the copy the
game returns to after a game over): every copy is replaced. The new stream
must not outgrow the old one; it is padded with empty literal runs.

  python pce/tools/titlemenu.py render      # masks from a bold font -> title_menu.json
  python pce/tools/titlemenu.py apply       # into patched/pce/snatcher_pce.bin
  python pce/tools/titlemenu.py show        # preview both lines as PNG
"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
import sysfont

import patch_pce as P
import pcecodec as C
import pcescene as S

BLOCK = (958, 23)
# display-list record data offsets (flags byte first), kind, copies on the disc
STREAMS = {"A": (0x9542, "sprite", 2), "B": (0xa272, "sprite", 2),
           "U": (0x6bfa, "tile", 1)}          # bank 7 -> VRAM $7000: the load screen's panel art
MASKS = os.path.join(ROOT, "pce", "translation", "title_menu.json")
LINES = [
    # text, cells left->right as (stream, index) for the top row and the bottom row, glyph top row
    {"label": "NEW GAME", "top": [("A", 28), ("A", 29), ("B", 0), ("B", 1), ("B", 25)],
     "bottom": [("A", 30), ("A", 31), ("B", 2), ("B", 3), ("B", 27)],
     "y": 15, "hi": 13, "fill": 14},
    {"label": "CONTINUE", "top": [("B", 4), ("B", 5), ("B", 8), ("B", 9), ("B", 20), ("B", 21), ("A", 26), ("A", 27)],
     "bottom": [("B", 6), ("B", 7), ("B", 10), ("B", 11), ("B", 22), ("B", 23), ("B", 24), None],
     "y": 3, "hi": 12, "fill": 15},
]
SHADOW = (3, 2)                # near, far
# the load screen (CONTINUE): its header bar reads 捜査ファイル in tiles $701-$724
# (18 x 2, palette 6: 1 white, 5 the dark green shadow, 3 the pale bar, 2 the
# panel), and the save counter's unit 回 is the 8x16 tile pair $79D/$79E
HEADER = {"label": "CASE FILES", "tile": 1, "cols": 18, "rows": 2, "ink": 1, "shadow": 5, "bar": 3, "panel": 2}
UNIT = (0x9D, 0x9E)
UNIT_BG, UNIT_EDGE = 5, 5
FONT = "arialbd.ttf"                     # found by lib/sysfont.py
FONT_PX = 15


def cells_of(data):
    """128-byte sprite cells -> (N, 16, 16) palette indices."""
    n = len(data) // 128
    w = np.frombuffer(data[:n * 128], dtype="<u2").reshape(n, 4, 16)
    out = np.zeros((n, 16, 16), dtype=np.uint8)
    for p in range(4):
        for x in range(16):
            out[:, :, x] |= (((w[:, p, :] >> (15 - x)) & 1) << p).astype(np.uint8)
    return out


def bytes_of(cells):
    """(N, 16, 16) -> the sprite cell bytes."""
    n = len(cells)
    w = np.zeros((n, 4, 16), dtype="<u2")
    for p in range(4):
        for x in range(16):
            w[:, p, :] |= (((cells[:, :, x] >> p) & 1).astype("<u2") << (15 - x))
    return w.tobytes()


def _codes(data, i):
    """Every non-literal code that can start at `i`: (length, cost, code)."""
    n = len(data)
    b = data[i]
    run = 1
    while i + run < n and data[i + run] == b and run < 0xFFFF:
        run += 1
    if b == 0:
        for k in range(2, min(run, 63) + 1):
            yield k, 1, bytes([0x40 | k])
    for k in range(3, min(run, 63) + 1):
        yield k, 2, bytes([k, b])
    if run > 63:
        yield run, 4, bytes([0x01, run & 0xFF, run >> 8, b])
    k = 1
    while i + 2 * k + 1 < n and data[i + 2 * k] == b and data[i + 2 * k + 1] == data[i + 1] and k < 255:
        k += 1
    for j in range(3, k + 1):
        yield 2 * j, 4, bytes([0x02, j, b, data[i + 1]])
    k = 1
    while i + 4 * k + 3 < n and data[i + 4 * k:i + 4 * k + 4] == data[i:i + 4] and k < 255:
        k += 1
    for j in range(2, k + 1):
        yield 4 * j, 6, bytes([0xFE, j]) + bytes(data[i:i + 4])
    k = 0
    while i + 2 * k + 1 < n and data[i + 2 * k] == b and k < 255:
        k += 1
    if b == 0:
        for j in range(2, min(k, 61) + 1):
            yield 2 * j, 1 + j, bytes([0xC0 | j]) + bytes(data[i + 1:i + 2 * j:2])
    for j in range(3, k + 1):
        yield 2 * j, 3 + j, bytes([0x00, j, b]) + bytes(data[i + 1:i + 2 * j:2])


def _parse(data):
    """Optimal parse: the cheapest code sequence for `data` (literals as
    runs of up to 63; adjacent runs are merged into long literals after)."""
    n = len(data)
    best = [0] * (n + 1)
    pick = [None] * (n + 1)
    for i in range(n - 1, -1, -1):
        c, ch = 1 + 1 + best[i + 1], (1, None)                # a one-byte literal run
        for k in range(2, min(63, n - i) + 1):
            v = 1 + k + best[i + k]
            if v < c:
                c, ch = v, (k, None)
        for L, cost, code in _codes(data, i):
            v = cost + best[i + L]
            if v < c:
                c, ch = v, (L, code)
        best[i], pick[i] = c, ch
    out, lit, i = bytearray(), bytearray(), 0
    while i < n:
        L, code = pick[i]
        if code is None:
            lit += data[i:i + L]
        else:
            out += _literal(lit)
            lit = bytearray()
            out += code
        i += L
    out += _literal(lit)
    return out


def _literal(chunk):
    """A literal run: 0x80 lo hi for long ones, 0x81..0xBF chained otherwise."""
    out = bytearray()
    chunk = bytes(chunk)
    if len(chunk) > 189:                                    # beyond three 63-byte headers
        return bytes([0x80, len(chunk) & 0xFF, len(chunk) >> 8]) + chunk
    while chunk:
        take = min(63, len(chunk))
        out += bytes([0x80 | take]) + chunk[:take]
        chunk = chunk[take:]
    return bytes(out)


def encode(data, limit=None):
    """The codec's byte RLE, pcecodec.decode's inverse, parsed optimally;
    padded with empty literals up to `limit` bytes when given."""
    out = _parse(data)
    out.append(0xFF)
    if limit is not None:
        if len(out) > limit:
            sys.exit(f"stream grew: {len(out)} > {limit}")
        pad = limit - len(out)
        # empty literal runs are three bytes; one or two spare bytes split a
        # literal or zero run instead (one byte more for the same output)
        body = out[:-1]
        while (limit - 1 - len(body)) % 3:
            body = _split_one(body)
            if len(body) > limit - 1:
                sys.exit(f"stream cannot be padded to {limit}")
        pad = limit - 1 - len(body)
        out = body + b"\x80\x00\x00" * (pad // 3) + b"\xff"
    return bytes(out)


def _split_one(body):
    """The stream a byte longer, same output - or two bytes longer when no
    one-byte split exists. One byte: the first literal run of two or more
    bytes becomes two runs, else the first zero run of two or more zeros, else
    a long zero run. Two bytes: a long run of a non-zero byte, a long literal
    or a one-byte literal in the long form."""
    codes = []
    i = 0
    while i < len(body):
        c = body[i]
        codes.append((i, c))
        if c == 0x80:
            i += 3 + (body[i + 1] | body[i + 2] << 8)
        elif c == 0xFE:
            i += 6
        elif c >= 0xC0:
            i += 1 + (c & 0x3F)
        elif c > 0x80:
            i += 1 + (c & 0x7F)
        elif c == 0:
            i += 3 + (body[i + 1] or 256)
        elif c in (1, 2):
            i += 4
        elif c < 0x40:
            i += 2
        else:
            i += 1
    for i, c in codes:
        if 0x82 <= c <= 0xBF:
            cnt = c & 0x3F
            return body[:i] + bytes([0x81, body[i + 1], 0x80 | (cnt - 1)]) + body[i + 2:]
        if 0x42 <= c <= 0x7F:
            n = c & 0x3F
            return body[:i] + bytes([0x40 | (n - 1), 0x41]) + body[i + 1:]
        if c == 1 and body[i + 3] == 0 and (body[i + 1] | body[i + 2] << 8) > 1:
            n = body[i + 1] | body[i + 2] << 8
            return body[:i] + bytes([1, (n - 1) & 0xFF, (n - 1) >> 8, 0, 0x41]) + body[i + 4:]
    for i, c in codes:
        if c == 1 and (body[i + 1] | body[i + 2] << 8) > 3:
            n, v = body[i + 1] | body[i + 2] << 8, body[i + 3]
            return body[:i] + bytes([1, (n - 3) & 0xFF, (n - 3) >> 8, v, 3, v]) + body[i + 4:]
        if c == 0x80 and (body[i + 1] | body[i + 2] << 8) > 1:
            n = body[i + 1] | body[i + 2] << 8
            return body[:i] + bytes([0x80, (n - 1) & 0xFF, (n - 1) >> 8]) + body[i + 3:i + 2 + n] + bytes([0x81, body[i + 2 + n]]) + body[i + 3 + n:]
        if c == 0x81:
            return body[:i] + bytes([0x80, 1, 0, body[i + 1]]) + body[i + 2:]
    sys.exit("nothing to split for padding")


def render_label(text, font=FONT, px=FONT_PX, gap=1, space=4):
    """A 1-bit mask of `text`, letters packed `gap` apart."""
    from PIL import Image, ImageDraw, ImageFont
    f = sysfont.truetype(font, px)
    parts = []
    for ch in text:
        if ch == " ":
            parts.append(None)
            continue
        im = Image.new("1", (48, 32), 0)
        ImageDraw.Draw(im).text((4, 4), ch, font=f, fill=1)
        a = np.array(im).astype(np.uint8)
        ys, xs = np.nonzero(a)
        parts.append((a[:, xs.min():xs.max() + 1], ys.min(), ys.max()))
    top = min(p[1] for p in parts if p)
    bot = max(p[2] for p in parts if p)
    w = sum(space if p is None else p[0].shape[1] + gap for p in parts) - gap
    out = np.zeros((bot - top + 1, w), np.uint8)
    x = 0
    for p in parts:
        if p is None:
            x += space
            continue
        a, y0, y1 = p
        out[:, x:x + a.shape[1]] |= a[top:bot + 1]
        x += a.shape[1] + gap
    return out


def paint(mask, hi, fill, shadow=SHADOW):
    """Mask -> palette indices in the title's style: a lighter edge on the
    top and left of every stroke, a two-step drop shadow down and right."""
    h, w = mask.shape
    out = np.zeros((h + len(shadow), w + len(shadow)), np.uint8)
    m = np.zeros_like(out)
    m[:h, :w] = mask
    for k, idx in enumerate(shadow, 1):
        sh = np.zeros_like(out)
        sh[k:, k:] = m[:-k, :-k]
        out[(sh > 0) & (out == 0)] = idx
    up = np.zeros_like(m)
    up[1:, :] = m[:-1, :]
    left = np.zeros_like(m)
    left[:, 1:] = m[:, :-1]
    out[m > 0] = fill
    out[(m > 0) & ((up == 0) | (left == 0))] = hi
    return out


def header(tiles, masks):
    """The load screen's header bar with the English label centred on it."""
    import tilescan as T
    h = HEADER
    sheet = np.vstack([np.hstack([tiles[h["tile"] + r * h["cols"] + c] for c in range(h["cols"])])
                       for r in range(h["rows"])])
    bar = np.nonzero((sheet == h["bar"]).any(axis=0))[0]
    x0, x1 = int(bar.min()), int(bar.max())
    rows = np.nonzero((sheet == h["bar"]).any(axis=1))[0]
    y0, y1 = int(rows.min()), int(rows.max())
    # wipe the glyphs: everything above the outer panel's top edge (the last row)
    # is panel, the bar keeps its extent
    text = (sheet == h["ink"]) | (sheet == h["shadow"])
    sheet[text] = h["panel"]
    sheet[y0:y1 + 1, x0:x1 + 1] = h["bar"]
    m = masks[h["label"]]
    art = paint(m, h["ink"], h["ink"], shadow=(h["shadow"],))
    ty = (y0 + y1) // 2 - m.shape[0] // 2
    tx = (x0 + x1) // 2 - m.shape[1] // 2
    if art.shape[0] + ty > sheet.shape[0] or art.shape[1] > x1 - x0:
        sys.exit(f"{h['label']}: {art.shape[1]}x{art.shape[0]} does not fit the bar")
    win = sheet[ty:ty + art.shape[0], tx:tx + art.shape[1]]
    win[art > 0] = art[art > 0]
    for r in range(h["rows"]):
        for c in range(h["cols"]):
            tiles[h["tile"] + r * h["cols"] + c] = sheet[r * 8:r * 8 + 8, c * 8:c * 8 + 8]
    # the unit: panel colour over the glyph; the lower tile's last three rows
    # are the panel's bottom border and stay
    tiles[UNIT[0]][:] = UNIT_BG
    tiles[UNIT[1]][:UNIT_EDGE] = UNIT_BG
    return tiles


def load_masks():
    d = json.load(open(MASKS, encoding="utf-8"))
    return {k: np.array([[1 if c == "#" else 0 for c in row] for row in v], np.uint8) for k, v in d.items()}


def compose(masks):
    """{stream: cells} with the English lines painted in."""
    blk = S.block(*BLOCK)
    cells = {}
    for name, (off, kind, copies) in STREAMS.items():
        sp, flags, _ = C.image_stream(blk, off, 0)
        data, end, clean = C.decode(blk, sp)
        assert clean and flags & 0x7F == 0
        if kind == "tile":
            import tilescan as T
            cells[name] = header(T.decode(np.frombuffer(data, np.uint8).reshape(-1, 32)).copy(), masks)
        else:
            cells[name] = cells_of(data).copy()
    for line in LINES:
        band = np.zeros((32, 16 * len(line["top"])), np.uint8)
        art = paint(masks[line["label"]], line["hi"], line["fill"])
        y, w = line["y"], band.shape[1]
        if art.shape[1] > w or y + art.shape[0] > 32:
            sys.exit(f"{line['label']}: {art.shape[1]}x{art.shape[0]} does not fit {w}x{32 - y}")
        band[y:y + art.shape[0], :art.shape[1]] = art
        for row, key in ((0, "top"), (16, "bottom")):
            for k, ref in enumerate(line[key]):
                piece = band[row:row + 16, 16 * k:16 * k + 16]
                if ref is None:
                    assert not piece.any(), f"{line['label']}: ink where no cell is"
                    continue
                cells[ref[0]][ref[1]] = piece
    return cells


def streams(cells):
    """{stream: (old bytes, new bytes)} for every copy on the disc."""
    blk = S.block(*BLOCK)
    out = {}
    for name, (off, kind, copies) in STREAMS.items():
        sp, flags, _ = C.image_stream(blk, off, 0)
        data, end, clean = C.decode(blk, sp)
        old = bytes(blk[sp:end])
        raw = S.encode_tiles(cells[name]) if kind == "tile" else bytes_of(cells[name])
        new = encode(raw, limit=len(old))
        back, _, ok = C.decode(new, 0)
        assert ok and back == raw, name
        out[name] = (old, new, copies)
    return out


def apply(out_path=P.OUT):
    img = P.Image(out_path, P.T3 + P.RESERVE)
    for name, (old, new, copies) in streams(compose(load_masks())).items():
        hits, i = [], img.data.find(old)
        while i >= 0:
            hits.append(i)
            img.write(i, new)
            i = img.data.find(old, i + 1)
        if len(hits) != copies:
            sys.exit(f"stream {name}: {len(hits)} copies found, expected {copies}")
        print(f"stream {name}: {len(old)} B -> {len(new)} B at " + ", ".join(f"sector {h // P.DATA - P.T2}+{h % P.DATA}" for h in hits))
    print(f"{img.flush()} sectors written")


def show(path=os.path.join(WORK, "pce", "title_menu.png")):
    from PIL import Image
    cells = compose(load_masks())
    rows = []
    for line in LINES:
        band = np.zeros((32, 16 * len(line["top"])), np.uint8)
        for row, key in ((0, "top"), (16, "bottom")):
            for k, ref in enumerate(line[key]):
                if ref:
                    band[row:row + 16, 16 * k:16 * k + 16] = cells[ref[0]][ref[1]]
        rows.append(np.pad(band, ((0, 0), (0, 128 - band.shape[1]))))
    h = HEADER
    sheet = np.vstack([np.hstack([cells["U"][h["tile"] + r * h["cols"] + c] for c in range(h["cols"])])
                       for r in range(h["rows"])])
    rows.append(np.pad(sheet, ((0, 0), (0, 128 - sheet.shape[1]))) if sheet.shape[1] <= 128 else sheet[:, :128])
    rows.append(np.pad(np.vstack([cells["U"][UNIT[0]], cells["U"][UNIT[1]]]), ((0, 0), (0, 120))))
    img = np.vstack(rows) * 17
    Image.fromarray(img).resize((img.shape[1] * 4, img.shape[0] * 4), Image.NEAREST).save(path)
    print(path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    if cmd == "render":
        d = {}
        for line in LINES + [HEADER]:
            m = render_label(line["label"])
            d[line["label"]] = ["".join("#" if v else "." for v in row) for row in m]
            print(f"{line['label']}: {m.shape[1]}x{m.shape[0]}")
        json.dump(d, open(MASKS, "w", encoding="utf-8"), indent=1)
    elif cmd == "show":
        show()
    else:
        apply()


if __name__ == "__main__":
    main()
