"""Parse and render the decompressed graphics containers (see lzss.py).

Container layout, reverse engineered from the parser at 0x8002CA58 (mode
word `01 00 00 00` -> decompress file+4 into the asset heap) and the two
section consumers at 0x8002CB60 / 0x8002CED4:

  u32 A, u32 B                  # byte sizes of the two sections
  section1 at 8      (A bytes)  # sprite/animation assets
  section2 at 8 + A  (B bytes)  # image directory

Each section begins with a u32 offset (relative to the section start) to a
descriptor struct. Its item-table offset and count live at different fields
per section: section 0 uses +0x0c / +0x14, section 1 uses +0x14 / +0x24.
Item table entries are u32 offsets relative to the section start. Each item
starts with a packed word:

  b0 = byte0: width  in VRAM halfwords = (((b0 >> 1) - 1) & 0x3F) + 1
  b1 = byte1: height in rows           = ((b1 - 1) & 0x7F) + 1

followed by the pixel data (width*2 bytes per row: 2 pixels/byte at 4bpp,
1 pixel/byte at 8bpp — bpp is a property of how the game uploads it, not
stored per item; backgrounds and portraits are 8bpp, tiles mostly 4bpp).

The first record of section1 usually carries the 256-colour palette:
{u32 0x210, u32 8} at offset 8, then 256 RGB555 colours at offset 16.

Usage:
  python gfx.py render <file.BIN>       # decompress + render items to PNG
  python gfx.py dump <file.BIN>         # list sections and items
"""
import os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from lzss import decompress


def rgb(c):
    return ((c & 31) << 3, ((c >> 5) & 31) << 3, ((c >> 10) & 31) << 3)


def sections(dec):
    a, b = struct.unpack_from("<II", dec, 0)
    return [(8, a), (8 + a, b)]


def palette(dec):
    """256-colour palette from the first record of section 1, if present."""
    if len(dec) < 528:
        return None
    size, flag = struct.unpack_from("<II", dec, 8)
    if size != 0x210 or flag != 8:
        return None
    return [rgb(struct.unpack_from("<H", dec, 16 + 2 * i)[0]) for i in range(256)]


def items(dec, base, size, kind=1):
    """Item list of one section: [(data_offset, width_halfwords, height)].

    `kind` picks the descriptor layout: 0 for the sprite section (item table
    offset at +0x0c, count at +0x14, per the consumer at 0x8002cbc8) and 1 for
    the image directory (+0x14 / +0x24, per 0x8002cf6c).
    """
    out = []
    if size < 8 or base + 4 > len(dec):
        return out
    rel = struct.unpack_from("<I", dec, base)[0]
    sp = base + rel
    if sp + 0x28 > len(dec):
        return out
    f = struct.unpack_from("<11I", dec, sp)
    count, tbl = (f[5], f[3]) if kind == 0 else (f[9], f[5])
    if not (0 < count < 512) or base + tbl + 4 * count > len(dec):
        return out
    for i in range(count):
        off = struct.unpack_from("<I", dec, base + tbl + 4 * i)[0]
        ip = base + off
        if ip + 4 > len(dec):
            continue
        w0 = struct.unpack_from("<I", dec, ip)[0]
        b0, b1 = w0 & 0xFF, (w0 >> 8) & 0xFF
        whw = (((b0 >> 1) - 1) & 0x3F) + 1
        h = ((b1 - 1) & 0x7F) + 1
        out.append((ip + 4, whw, h))
    return out


def render(path, outdir=None):
    from PIL import Image
    raw = open(path, "rb").read()
    dec, _ = decompress(raw)
    name = os.path.splitext(os.path.basename(path))[0]
    outdir = outdir or os.path.join(os.path.dirname(path), name + "_items")
    os.makedirs(outdir, exist_ok=True)
    pal = palette(dec) or [(i, i, i) for i in range(256)]
    pal4 = pal[:16]
    n = 0
    for gi, (base, size) in enumerate(sections(dec)):
        for k, (ip, whw, h) in enumerate(items(dec, base, size, gi)):
            W = whw * 2
            npix = W * h
            if ip + npix > len(dec) or h < 4:
                continue
            seg = dec[ip:ip + npix]
            im8 = Image.new("RGB", (W, h))
            p8 = im8.load()
            im4 = Image.new("RGB", (W * 2, h))
            p4 = im4.load()
            for y in range(h):
                for x in range(W):
                    b = seg[y * W + x]
                    p8[x, y] = pal[b]
                    p4[x * 2, y] = pal4[b & 0xF]
                    p4[x * 2 + 1, y] = pal4[(b >> 4) & 0xF]
            im8.save(os.path.join(outdir, f"{name}_g{gi}_{k:02d}_8bpp.png"))
            im4.save(os.path.join(outdir, f"{name}_g{gi}_{k:02d}_4bpp.png"))
            n += 1
    print(f"{name}: {n} items -> {outdir}")


def dump(path):
    raw = open(path, "rb").read()
    dec, end = decompress(raw)
    a, b = struct.unpack_from("<II", dec, 0)
    print(f"{os.path.basename(path)}: {len(raw)} -> {len(dec)} bytes, "
          f"sections {a:#x} + {b:#x}")
    for gi, (base, size) in enumerate(sections(dec)):
        lst = items(dec, base, size, gi)
        print(f"  section {gi}: {size:#x} bytes, {len(lst)} items")
        for k, (ip, whw, h) in enumerate(lst):
            print(f"    item {k:2d}: +{ip:#x} {whw} hw x {h} "
                  f"({whw*2}px 8bpp / {whw*4}px 4bpp)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, files = sys.argv[1], sys.argv[2:]
    for f in files:
        (render if cmd == "render" else dump)(f)
