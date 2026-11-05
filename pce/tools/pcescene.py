"""Rebuild PCE Snatcher screens from a scene block: display lists -> VRAM,
BAT -> picture, palette records -> colours.

Per display-list record (pcecodec.find_lists):
  type 8 / 4    header {flags, rowlen}; flags bit6 = direct mode ($7294):
                `rowlen`-byte runs of BAT words. With bit5 the VDC increment
                is 0x40, so a run is a COLUMN of the 64-wide map and the next
                run starts one word right; without it runs are rows 0x40
                apart. Without bit6 the stream is tiles.
  other types   header {flags, remap[flags & 0x7F]}, tiles through $71B0,
                each pixel index replaced by remap[index] when flags & 0x7F.
Palette records ($6B94): {vce_lo, vce_hi, ptr_lo, ptr_hi, bank}; data is
{ngroups-1, then 9-byte groups: hibits (MSB first), 8 low bytes}; a VCE
colour is 9-bit GGGRRRBBB.

Usage:
  python pce/tools/pcescene.py sheet <block_index>       # grayscale screens
  python pce/tools/pcescene.py all                       # every block -> sheets
"""
import json, os, sys
import numpy as np
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import tilescan as T
import pcecodec as C

BIN = os.path.join(WORK, "pce", "snatcher_pce.bin")
T2 = 4174
TABLES = json.load(open(os.path.join(WORK, "pce", "filetable.json")))
BAT_W = 64


def block(rec, n):
    out = bytearray()
    with open(BIN, "rb") as f:
        for i in range(n):
            f.seek((T2 + rec + i) * 2352)
            out += f.read(2352)[16:16 + 2048]
    return bytes(out)


def build_vram(blk, recs):
    """Play one display list into a 64 KB VRAM image; returns (vram, remaps)."""
    vram = bytearray(0x10000)
    for b, t, va, ptr, o in recs:
        sp, flags, rowlen = C.image_stream(blk, o, t)
        data, end, clean = C.decode(blk, sp)
        if t in (4, 8) and flags & 0x40 and rowlen:
            # bit5: the VDC auto-increment is 0x40 (a column of the 64-wide
            # BAT) and each `rowlen`-byte run starts one word to the right;
            # otherwise runs are rows, one BAT line apart
            step, run = (BAT_W, 1) if flags & 0x20 else (1, BAT_W)
            words = np.frombuffer(data[:len(data) // 2 * 2], dtype="<u2")
            per = rowlen // 2
            for k, w in enumerate(words):
                a = va + (k // per) * run + (k % per) * step
                if a < 0x8000:
                    vram[a * 2:a * 2 + 2] = int(w).to_bytes(2, "little")
        else:
            if t not in (4, 8) and flags & 0x7F:
                table = blk[o + 1:o + 1 + (flags & 0x7F)]
                # remap through $71B0: every 4-bit pixel index -> table[index]
                px = T.decode(np.frombuffer(data[:len(data) // 32 * 32],
                                            dtype=np.uint8).reshape(-1, 32))
                lut = np.array(list(table) + [0] * (16 - len(table)), dtype=np.uint8)
                data = encode_tiles(lut[px])
            a = va * 2
            seg = data[:max(0, 0x10000 - a)]
            vram[a:a + len(seg)] = seg
    return vram


def encode_tiles(px):
    """(N,8,8) pixel indices -> VDC planar bytes (inverse of tilescan.decode)."""
    n = len(px)
    out = np.zeros((n, 32), dtype=np.uint8)
    for p in range(4):
        bits = ((px >> p) & 1).astype(np.uint8)          # (N,8,8)
        packed = np.packbits(bits, axis=2).reshape(n, 8)  # (N,8) one byte per row
        base = 0 if p < 2 else 16
        out[:, base + (p & 1):base + 16:2] = packed
    return out.tobytes()


def screen(vram, rows=28, cols=32, bat_base=0):
    """Compose the picture the BAT describes; returns (pixels, palette ids)."""
    bat = np.frombuffer(bytes(vram[bat_base:bat_base + BAT_W * 32 * 2]), dtype="<u2").reshape(32, BAT_W)
    tiles = T.decode(np.frombuffer(bytes(vram), dtype=np.uint8).reshape(-1, 32))
    img = np.zeros((rows * 8, cols * 8), dtype=np.uint8)
    pal = np.zeros((rows, cols), dtype=np.uint8)
    for y in range(rows):
        for x in range(cols):
            e = int(bat[y, x])
            tn = (e & 0xFFF) % len(tiles)
            img[y * 8:y * 8 + 8, x * 8:x * 8 + 8] = tiles[tn]
            pal[y, x] = e >> 12
    return img, pal


def find_palettes(blk, bank0, nbanks):
    """Palette records anywhere in the block -> {vce_index: [(r,g,b)]*8k}."""
    pals = {}
    n = len(blk)
    for i in range(n - 5):
        lo, hi, pl, ph, b = blk[i:i + 5]
        if hi > 1 or not (0x80 <= ph < 0xE0) or not (bank0 <= b < bank0 + nbanks):
            continue
        vce = lo | hi << 8
        if vce & 7:
            continue
        off = (b - bank0) * C.BANK + ((pl | ph << 8) - 0x8000)
        if off + 10 > n:
            continue
        ng = blk[off] + 1
        if ng > 32 or off + 1 + 9 * ng > n:
            continue
        cols = []
        for g in range(ng):
            grp = blk[off + 1 + 9 * g:off + 10 + 9 * g]
            hib = grp[0]
            for k in range(8):
                w = grp[1 + k] | (((hib << k) & 0x80) >> 7) << 8
                cols.append(((w >> 3 & 7) * 36, (w >> 6 & 7) * 36, (w & 7) * 36))
        pals.setdefault(vce, []).append((i, off, cols))
    return pals


def sheet(bi, out=None):
    from PIL import Image, ImageDraw
    r = TABLES["2"][bi]
    blk = block(r["rec"], r["n"])
    nb = (len(blk) + C.BANK - 1) // C.BANK
    lists = [(off, recs) for off, recs in C.find_lists(blk, r["bank"], nb) if len(recs) >= 2]
    shots = []
    for off, recs in lists:
        vram = build_vram(blk, recs)
        img, pal = screen(vram)
        if img.std() < 1.0:
            continue
        shots.append((off, img))
    if not shots:
        print(f"block {bi}: no screens")
        return
    COLS = 4
    W, H = 256, 224
    rows = (len(shots) + COLS - 1) // COLS
    sh = Image.new("L", (COLS * (W + 8), rows * (H + 16)), 20)
    d = ImageDraw.Draw(sh)
    for i, (off, img) in enumerate(shots):
        x, y = (i % COLS) * (W + 8), (i // COLS) * (H + 16)
        sh.paste(Image.fromarray(img * 17, "L"), (x, y + 14))
        d.text((x + 2, y + 2), f"b{bi} rec{r['rec']} list@{off:#x}", fill=255)
    p = out or os.path.join(WORK, "pce", f"scene_{bi:02d}.png")
    sh.save(p)
    print(f"block {bi} (rec {r['rec']}, {r['n']} sectors): {len(shots)} screens -> {p}")


def colour_screen(bi, li, out=None, pal_rec=None):
    """Export display list `li` of block `bi` as an RGB PNG, coloured with the
    palette record nearest the list in the block (the scene script sets the
    palette right beside the picture it draws)."""
    from PIL import Image
    r = TABLES["2"][bi]
    blk = block(r["rec"], r["n"])
    nb = (len(blk) + C.BANK - 1) // C.BANK
    lists = [(off, recs) for off, recs in C.find_lists(blk, r["bank"], nb) if len(recs) >= 2]
    off, recs = lists[li]
    vram = build_vram(blk, recs)
    img, palid = screen(vram)
    pals = find_palettes(blk, r["bank"], nb)
    cands = sorted((abs(ri - off), ri, do, vce, cols)
                   for vce, ents in pals.items() for ri, do, cols in ents
                   if vce < 0x100 and len(cols) >= 16)
    used = sorted(set(palid.ravel().tolist()))
    # the scene script also parks fade states beside the picture; of the
    # nearest records, take the one that lights the palettes the BAT uses
    def brightness(c):
        dist, ri, do, vce, cols = c
        seg = np.array(cols, dtype=np.int32)
        tot = 0
        for p in used:
            lo, hi = p * 16 - vce, p * 16 + 16 - vce
            if 0 <= lo and hi <= len(seg):
                tot += int(seg[lo:hi].sum())
        return tot
    def lit(c):
        # a real palette: not faded to black, not a flat tint
        dist, ri, do, vce, cols = c
        seg = np.array(cols, dtype=np.int32)
        sel = []
        for p in used:
            lo, hi = p * 16 - vce, p * 16 + 16 - vce
            if 0 <= lo and hi <= len(seg):
                sel.append(seg[lo:hi])
        if not sel:
            return False
        a = np.concatenate(sel)
        return 30 < a.mean() < 200 and a.std(axis=0).mean() > 40
    near = [c for c in cands[:8] if lit(c)] or cands[:6]
    if pal_rec is not None:                 # explicit record offset wins
        near = [c for c in cands if c[1] == pal_rec] + near
    pal = np.zeros((256, 3), dtype=np.uint8)
    for dist, ri, do, vce, cols in near:               # brightest first, fill gaps
        seg = np.array(cols[:256 - vce], dtype=np.uint8)
        blank = pal[vce:vce + len(seg)].sum(1) == 0
        pal[vce:vce + len(seg)][blank] = seg[blank]
    cands = near
    rgb = np.zeros((img.shape[0], img.shape[1], 3), dtype=np.uint8)
    for y in range(palid.shape[0]):
        for x in range(palid.shape[1]):
            bp = img[y * 8:y * 8 + 8, x * 8:x * 8 + 8]
            rgb[y * 8:y * 8 + 8, x * 8:x * 8 + 8] = pal[palid[y, x] * 16 + bp]
    im = Image.fromarray(rgb)
    bbox = Image.fromarray(img).getbbox()
    if bbox:
        im = im.crop(bbox)
    p = out or os.path.join(WORK, "pce", f"pce_b{bi}_{li}.png")
    im.save(p)
    print(f"b{bi}.{li} list@{off:#x} palettes used {used} nearest rec@{cands[0][1]:#x} -> {p} {im.size}")
    return im


def dump_assets(outdir, min_bytes=512):
    """Every record of every display list in every block, decoded and rendered
    as a tile strip (16 tiles wide, grayscale index*17) - sprites, partial
    updates and BAT blobs included. Names: b<block>_l<list>_r<rec>_v<vram>.png"""
    from PIL import Image
    os.makedirs(outdir, exist_ok=True)
    n = 0
    seen = set()
    for bi in range(len(TABLES["2"])):
        r = TABLES["2"][bi]
        blk = block(r["rec"], r["n"])
        nb = (len(blk) + C.BANK - 1) // C.BANK
        for off, recs in C.find_lists(blk, r["bank"], nb):
            for k, (b, t, va, ptr, o) in enumerate(recs):
                sp, flags, rowlen = C.image_stream(blk, o, t)
                data, end, clean = C.decode(blk, sp)
                if not clean or len(data) < min_bytes or (r["rec"], o) in seen:
                    continue
                seen.add((r["rec"], o))
                tiles = len(data) // 32
                if tiles < 16:
                    continue
                px = T.decode(np.frombuffer(data[:tiles * 32], dtype=np.uint8).reshape(-1, 32))
                img = T.as_image(px, 16)
                Image.fromarray(img * 17, "L").save(
                    os.path.join(outdir, f"b{bi:02d}_l{off:05x}_r{k:02d}_v{va:04x}_t{t}.png"))
                n += 1
    print(f"{n} streams -> {outdir}")


def export_all(outdir):
    """Every screen of every scene block as a colour PNG: pce_b<block>_<list>.png"""
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for bi in range(len(TABLES["2"])):
        r = TABLES["2"][bi]
        blk = block(r["rec"], r["n"])
        nb = (len(blk) + C.BANK - 1) // C.BANK
        lists = [(off, recs) for off, recs in C.find_lists(blk, r["bank"], nb) if len(recs) >= 2]
        for li in range(len(lists)):
            try:
                colour_screen(bi, li, out=os.path.join(outdir, f"pce_b{bi}_{li}.png"))
                n += 1
            except Exception as e:
                print(f"b{bi}.{li}: {e}")
    print(f"{n} screens -> {outdir}")


USAGE = """
  python pce/tools/pcescene.py sheet <block>              grayscale contact sheet of one block
  python pce/tools/pcescene.py all                        grayscale sheets for all 64 blocks
  python pce/tools/pcescene.py export <block> <list> [pal_rec_hex]
                                                          one screen, colour, native size
  python pce/tools/pcescene.py export-all <dir>           every screen, colour
  python pce/tools/pcescene.py assets <dir>               every decodable stream as a tile strip
Palettes come from the record nearest the display list; when a fade state wins
(tinted or dark output) pass the offset of a lit record - `export 49 0 0xa53d`.
Needs work/pce/snatcher_pce.bin (chdman extractcd of the CHD) and filetable.json.
"""

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__ + USAGE)
    cmd = sys.argv[1]
    if cmd == "all":
        for bi in range(len(TABLES["2"])):
            sheet(bi)
    elif cmd == "sheet":
        sheet(int(sys.argv[2]))
    elif cmd == "export":
        rec = int(sys.argv[4], 0) if len(sys.argv) > 4 else None
        colour_screen(int(sys.argv[2]), int(sys.argv[3]), pal_rec=rec)
    elif cmd == "export-all":
        export_all(sys.argv[2])
    elif cmd == "assets":
        dump_assets(sys.argv[2])
    else:
        sys.exit(USAGE)
