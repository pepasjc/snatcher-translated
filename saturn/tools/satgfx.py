"""The Saturn Snatcher graphics containers (DATA.BIN chunks 100+, LZ3-packed).

Format (read out of the section dispatcher 0x060B2788 and checked against
VDP1/VDP2/CRAM in a Beetle savestate at the Junker HQ reception,
work/saturn/gfx/vram/):

  header: a list of {u8 type, u8[3] 0, u32 BE size}, ended by FF FF FF FF
          FF FF FF FF (twenty chunks end it FF..FE instead: the loader's
          `cmp/eq #-2` branch at 0x060B2A5A hands them to 0x060B2624 - e.g.
          452, whose type-3 data is found whole in VDP1 VRAM at 0x19000
          during the opening's JUNKER HQ caption); then the sections back
          to back, each advanced by (size + 3) & ~3.  The loader (0x060B28xx, after the LZ3 decode)
          scans the words for the -1, points `data` past it and calls the
          dispatcher, which files each section's (pointer, size) into the
          scene object's per-type arrays (counts at obj+24..27, pointer
          pairs at obj+0x1C / 0x5C / 0x9C / 0xDC).  Nothing is uploaded at
          load: the scene script picks entries by index later.
  type 0  VDP2 background: 8-bpp 16x16 characters (four 8x8 cells in
          TL, TR, BL, BR order, 256 bytes each) in row-major order,
          15 x 8 chars = 240x128 (30,720 bytes: the scene picture) or
          30 x 16 = 480x256 (122,880: the scrolling wall behind the box;
          chunk 301's copy sat at VDP2 VRAM 0x22000 at the reception,
          chunk 458's picture at 0x44000).
  type 1  palettes: 512 bytes = 256 x RGB555 BE (bit 15 set) per palette,
          uploaded to CRAM by index (chunk 301's at CRAM 0xE00 = slot 7).
  type 2  sprite index: {u16 nA, u16 nB, 12 x 0}, nA u32 offsets to
          animation sequences {u16 n, n x {u16 list, u16 frames}}, nB u32
          offsets to sprite lists {u16 count, 6 x 0, count x {u16 ctrl,
          u16 size (w << 8 | h, pixels), u16 clut, u16 srca (bytes / 8 into
          the type-3 data), u16 x, u16 y}} - the same record the engine's
          resident lists use (the dialogue box list at 0x060E5350).
  type 3  VDP1 sprite pixels, 8 bpp, addressed by the lists above
          (chunk 453's went to VDP1 VRAM 0x47080 whole).

Usage (repo root):
  python saturn/tools/satgfx.py dump IDX...            sections, palettes, lists
  python saturn/tools/satgfx.py render IDX...          PNGs per background / palette / sprite list -> work/saturn/gfx/NNN/
  python saturn/tools/satgfx.py sheet [IDX...]         one contact sheet per chunk -> work/saturn/gfx/sheets/NNN.png (all by default)
  python saturn/tools/satgfx.py pack IDX SEC PNG|BIN   replace section SEC of chunk IDX (type 0 from an indexed PNG of the
                                                       right size, or raw bytes) -> patched/saturn/chunks/NNN.bin (decoded form)
  python saturn/tools/satgfx.py packbin IDX FILE       write a whole decoded chunk file into patched/saturn/chunks/NNN.bin
Chunks are read decoded from work/saturn/data_bin/NNN.bin (lz3.py extract),
or straight from DATA.BIN when that file is missing.
"""
import os, sys, struct, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import lz3

DEC_DIR = os.path.join(WORK, "saturn", "data_bin")
OUT_DIR = os.path.join(WORK, "saturn", "gfx")
CHUNK_OUT = os.path.join(ROOT, "patched", "saturn", "chunks")
TERM = b"\xff" * 8
TERM2 = b"\xff" * 7 + b"\xfe"      # 20 chunks (196, 352, 376.., 452..): the loader's `cmp/eq #-2`
                                    # branch (0x060B2A5A) - the same sections, another consumer
TYPE_NAMES = {0: "bg", 1: "pal", 2: "index", 3: "sprites"}
CELL = 8
CHAR = 16


class NotContainer(Exception):
    pass


def load(idx):
    """Decoded chunk bytes."""
    p = os.path.join(DEC_DIR, f"{idx:03d}.bin")
    if os.path.exists(p):
        return open(p, "rb").read()
    with open(lz3.DATA_BIN, "rb") as f:
        return lz3.decode(lz3.read_chunk(f, idx))


def parse(dec):
    """[(type, offset, size)] of a container, or NotContainer."""
    ents = []
    o = 0
    while o + 8 <= len(dec):
        if dec[o:o + 8] in (TERM, TERM2):
            o += 8
            break
        t = dec[o]
        if dec[o + 1:o + 4] != b"\0\0\0" or t > 3:
            raise NotContainer(f"bad header word at {o:#x}")
        s = struct.unpack_from(">I", dec, o + 4)[0]
        ents.append((t, s))
        o += 8
    else:
        raise NotContainer("no terminator")
    if not ents:
        raise NotContainer("empty header")
    out = []
    for t, s in ents:
        if o + s > len(dec):
            raise NotContainer("section past end")
        out.append((t, o, s))
        o += (s + 3) & ~3
    return out


def terminator(dec):
    """The chunk's own header terminator (TERM or TERM2)."""
    o = 0
    while o + 8 <= len(dec):
        if dec[o:o + 8] in (TERM, TERM2):
            return dec[o:o + 8]
        o += 8
    raise NotContainer("no terminator")


def build(sections, term=TERM):
    """Inverse of parse: [(type, bytes)] -> decoded chunk bytes."""
    out = bytearray()
    for t, b in sections:
        out += struct.pack(">BBBBI", t, 0, 0, 0, len(b))
    out += term
    for t, b in sections:
        out += b
        while len(out) & 3:
            out.append(0)
    return bytes(out)


def rgb555(c):
    return ((c & 31) << 3, ((c >> 5) & 31) << 3, ((c >> 10) & 31) << 3)


def palettes(dec, secs):
    """Every 256-colour palette in the container, in order."""
    out = []
    for t, o, s in secs:
        if t == 1:
            for k in range(s // 512):
                out.append([rgb555(c) for c in struct.unpack_from(">256H", dec, o + 512 * k)])
    return out


def bg_geometry(size):
    n = size // 256
    if n == 120:
        return 15, 8
    if n == 480:
        return 30, 16
    w = 15 if n % 15 == 0 else 16
    return w, (n + w - 1) // w


def bg_pixels(dec, o, s):
    """Type 0 section -> (w, h, bytes of 8-bpp indices, row-major)."""
    cw, ch = bg_geometry(s)
    W, H = cw * CHAR, ch * CHAR
    out = bytearray(W * H)
    n = s // 256
    for c in range(n):
        cx, cy = (c % cw) * CHAR, (c // cw) * CHAR
        if cy >= H:
            break
        base = o + c * 256
        for cell in range(4):
            ox, oy = (cell & 1) * CELL, (cell >> 1) * CELL
            cb = base + cell * 64
            for y in range(CELL):
                row = (cy + oy + y) * W + cx + ox
                out[row:row + CELL] = dec[cb + y * CELL:cb + y * CELL + CELL]
    return W, H, bytes(out)


def bg_pack(W, H, pix):
    """Inverse of bg_pixels: row-major 8-bpp indices -> character data."""
    cw, ch = W // CHAR, H // CHAR
    out = bytearray(cw * ch * 256)
    for c in range(cw * ch):
        cx, cy = (c % cw) * CHAR, (c // cw) * CHAR
        base = c * 256
        for cell in range(4):
            ox, oy = (cell & 1) * CELL, (cell >> 1) * CELL
            cb = base + cell * 64
            for y in range(CELL):
                row = (cy + oy + y) * W + cx + ox
                out[cb + y * CELL:cb + y * CELL + CELL] = pix[row:row + CELL]
    return bytes(out)


def index(dec, o, s):
    """Type 2 section -> (anims, lists); a list = [(ctrl, w, h, clut, srca, x, y)]."""
    nA, nB = struct.unpack_from(">HH", dec, o)
    offA = struct.unpack_from(f">{nA}I", dec, o + 16)
    offB = struct.unpack_from(f">{nB}I", dec, o + 16 + 4 * nA)
    anims = []
    for oa in offA:
        n = struct.unpack_from(">H", dec, o + oa)[0]
        anims.append([struct.unpack_from(">HH", dec, o + oa + 2 + 4 * k) for k in range(n)])
    lists = []
    for ob in offB:
        cnt = struct.unpack_from(">H", dec, o + ob)[0]
        recs = []
        for r in range(cnt):
            ctrl, sz, clut, srca, x, y = struct.unpack_from(">6H", dec, o + ob + 8 + 12 * r)
            recs.append((ctrl, sz >> 8, sz & 0xFF, clut, srca, x, y))
        lists.append(recs)
    return anims, lists


def image_from(W, H, pix, pal):
    from PIL import Image
    im = Image.new("P", (W, H))
    flat = []
    for r, g, b in pal:
        flat += [r, g, b]
    im.putpalette(flat + [0] * (768 - len(flat)))
    im.putdata(pix)
    return im


def compose(dec, sprites_off, sprites_size, recs, pal):
    """Draw a sprite list into a palette image sized to its extent."""
    from PIL import Image
    if not recs:
        return None
    W = max(x + w for _, w, h, _, _, x, y in recs)
    H = max(y + h for _, w, h, _, _, x, y in recs)
    if W <= 0 or H <= 0 or W > 1024 or H > 1024:
        return None
    im = image_from(W, H, bytes(W * H), pal)
    px = im.load()
    for ctrl, w, h, clut, srca, x, y in recs:
        src = sprites_off + srca * 8
        if w == 0 or h == 0 or src + w * h > sprites_off + sprites_size:
            continue
        for yy in range(h):
            row = dec[src + yy * w:src + yy * w + w]
            for xx in range(w):
                px[x + xx, y + yy] = row[xx]
    return im


def describe(idx, dec=None):
    dec = dec if dec is not None else load(idx)
    secs = parse(dec)
    lines = [f"chunk {idx}: {len(dec)} bytes, {len(secs)} sections"]
    for k, (t, o, s) in enumerate(secs):
        extra = ""
        if t == 0:
            cw, ch = bg_geometry(s)
            extra = f"{cw * CHAR}x{ch * CHAR} ({cw}x{ch} chars)"
        elif t == 1:
            extra = f"{s // 512} palettes"
        elif t == 2:
            anims, lists = index(dec, o, s)
            extra = f"{len(anims)} anims, {len(lists)} lists: " + ", ".join(
                f"[{len(l)} pcs {max((x + w for _, w, h, _, _, x, y in l), default=0)}x"
                f"{max((y + h for _, w, h, _, _, x, y in l), default=0)}]" for l in lists[:12])
            if len(lists) > 12:
                extra += " ..."
        lines.append(f"  sec {k}: type {t} {TYPE_NAMES[t]:8s} @{o:#7x} {s:7d}  {extra}")
    return "\n".join(lines)


def render(idx, outdir=None, dec=None):
    """Every background (with every palette), palette swatch and sprite list as PNGs."""
    from PIL import Image
    dec = dec if dec is not None else load(idx)
    secs = parse(dec)
    outdir = outdir or os.path.join(OUT_DIR, f"{idx:03d}")
    os.makedirs(outdir, exist_ok=True)
    pals = palettes(dec, secs) or [[(i, i, i) for i in range(256)]]
    n = 0
    spr = [(o, s) for t, o, s in secs if t == 3]
    for k, (t, o, s) in enumerate(secs):
        if t == 0:
            W, H, pix = bg_pixels(dec, o, s)
            for pi, pal in enumerate(pals):
                image_from(W, H, pix, pal).save(os.path.join(outdir, f"{idx:03d}_s{k}_bg_p{pi}.png"))
                n += 1
        elif t == 1:
            for pi in range(s // 512):
                pal = [rgb555(c) for c in struct.unpack_from(">256H", dec, o + 512 * pi)]
                im = Image.new("RGB", (16 * 8, 16 * 8))
                px = im.load()
                for i, c in enumerate(pal):
                    for yy in range(8):
                        for xx in range(8):
                            px[(i % 16) * 8 + xx, (i // 16) * 8 + yy] = c
                im.save(os.path.join(outdir, f"{idx:03d}_s{k}_pal{pi}.png"))
                n += 1
        elif t == 2 and spr:
            so, ss = spr[0]
            anims, lists = index(dec, o, s)
            for li, recs in enumerate(lists):
                im = compose(dec, so, ss, recs, pals[0])
                if im:
                    im.save(os.path.join(outdir, f"{idx:03d}_s{k}_list{li:02d}.png"))
                    n += 1
    return n


def sheet(idx, dec=None, scale=1):
    """A labelled contact sheet of everything renderable in one chunk."""
    from PIL import Image, ImageDraw
    dec = dec if dec is not None else load(idx)
    secs = parse(dec)
    pals = palettes(dec, secs) or [[(i, i, i) for i in range(256)]]
    tiles = []
    spr = [(o, s) for t, o, s in secs if t == 3]
    for k, (t, o, s) in enumerate(secs):
        if t == 0:
            W, H, pix = bg_pixels(dec, o, s)
            for pi, pal in enumerate(pals[:4]):
                tiles.append((f"s{k} bg p{pi}", image_from(W, H, pix, pal).convert("RGB")))
        elif t == 2 and spr:
            so, ss = spr[0]
            anims, lists = index(dec, o, s)
            for li, recs in enumerate(lists):
                im = compose(dec, so, ss, recs, pals[0])
                if im:
                    tiles.append((f"s{k} list{li}", im.convert("RGB")))
        elif t == 3 and not any(tt == 2 for tt, _, _ in secs):
            # no index: show the raw bytes 8-bpp at 64 wide so something is visible
            W = 128
            H = min(s // W, 512)
            tiles.append((f"s{k} raw8 {W}w", image_from(W, H, dec[o:o + W * H], pals[0]).convert("RGB")))
    if not tiles:
        return None
    pad, label = 4, 12
    maxw = 1024
    rows, cur, cw, ch = [], [], 0, 0
    for name, im in tiles:
        w, h = im.width * scale, im.height * scale + label
        if cur and cw + w + pad > maxw:
            rows.append((cur, ch))
            cur, cw, ch = [], 0, 0
        cur.append((name, im, cw))
        cw += w + pad
        ch = max(ch, h)
    if cur:
        rows.append((cur, ch))
    H = sum(h + pad for _, h in rows) + label
    W = min(maxw, max(sum(im.width * scale + pad for _, im, _ in r) for r, _ in rows))
    out = Image.new("RGB", (W, H), (40, 0, 40))
    d = ImageDraw.Draw(out)
    d.text((2, 0), f"chunk {idx}  {len(dec)} B  " + " ".join(f"{TYPE_NAMES[t]}:{s}" for t, _, s in secs), fill=(255, 255, 0))
    y = label
    for r, h in rows:
        for name, im, x in r:
            d.text((x + 1, y), name, fill=(0, 255, 255))
            if scale != 1:
                im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
            out.paste(im, (x, y + label))
        y += h + pad
    return out


def sheets(idxs=None):
    os.makedirs(os.path.join(OUT_DIR, "sheets"), exist_ok=True)
    rows = lz3.table()
    idxs = list(idxs) if idxs else range(len(rows))
    done = skipped = 0
    for i in idxs:
        p = os.path.join(DEC_DIR, f"{i:03d}.bin")
        if not os.path.exists(p):
            skipped += 1
            continue
        dec = open(p, "rb").read()
        try:
            im = sheet(i, dec)
        except NotContainer as e:
            skipped += 1
            continue
        if im is None:
            skipped += 1
            continue
        im.save(os.path.join(OUT_DIR, "sheets", f"{i:03d}.png"))
        done += 1
    print(f"{done} sheets, {skipped} skipped -> {OUT_DIR}/sheets")


def pack(idx, sec_no, path):
    """Replace one section of a chunk from a PNG (type 0: an indexed image
    of the section's exact size) or raw bytes, write the decoded chunk to
    patched/saturn/chunks/NNN.bin and return its path."""
    dec = load(idx)
    secs = parse(dec)
    t, o, s = secs[sec_no]
    if path.lower().endswith(".png"):
        from PIL import Image
        im = Image.open(path)
        if im.mode != "P":
            raise SystemExit("pack: PNG must be palette-indexed (mode P)")
        if t != 0:
            raise SystemExit("pack: only type 0 sections take a PNG")
        W, H, _ = bg_pixels(dec, o, s)
        if im.size != (W, H):
            raise SystemExit(f"pack: PNG is {im.size}, section is {(W, H)}")
        new = bg_pack(W, H, bytes(im.getdata()))
    else:
        new = open(path, "rb").read()
    if len(new) != s:
        raise SystemExit(f"pack: section {sec_no} is {s} bytes, got {len(new)}")
    parts = [(tt, dec[oo:oo + ss]) for tt, oo, ss in secs]
    parts[sec_no] = (t, new)
    out = build(parts, terminator(dec))
    assert parse(out) == secs, "rebuilt header differs"
    return write_chunk(idx, out)


def write_chunk(idx, dec):
    os.makedirs(CHUNK_OUT, exist_ok=True)
    p = os.path.join(CHUNK_OUT, f"{idx:03d}.bin")
    open(p, "wb").write(dec)
    return p


def main(argv):
    cmd = argv[0] if argv else "help"
    if cmd == "dump":
        for a in argv[1:]:
            print(describe(int(a)))
    elif cmd == "render":
        for a in argv[1:]:
            n = render(int(a))
            print(f"chunk {a}: {n} images -> {OUT_DIR}/{int(a):03d}")
    elif cmd == "sheet":
        sheets([int(a) for a in argv[1:]])
    elif cmd == "pack":
        print(pack(int(argv[1]), int(argv[2]), argv[3]))
    elif cmd == "packbin":
        dec = open(argv[2], "rb").read()
        parse(dec)
        print(write_chunk(int(argv[1]), dec))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
