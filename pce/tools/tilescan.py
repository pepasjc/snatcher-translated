"""Find PC Engine graphics in Snatcher CD-ROMantic's data tracks by shape.

The PCE disc has no filesystem: the IPL at track-relative sector 1 points at a
22-sector boot program (load 0x3000, exec 0x3000) and everything after that is
found by loaders written in HuC6280. Rather than trace them, this decodes the
whole data track AS IF it were VDC background tiles and scores each window on
how picture-like it looks.

VDC tile format: 8x8, 4bpp planar, 32 bytes per tile. Bytes 0..15 are rows of
plane0/plane1 interleaved (row0 p0, row0 p1, row1 p0, ...), bytes 16..31 the
same for plane2/plane3. Pixel = p0 | p1<<1 | p2<<2 | p3<<3, MSB is the leftmost
column.

A full-screen PCE picture is 32x28 tiles = 28,672 bytes, so any window of that
order that holds real art shows strong horizontal coherence between adjacent
pixels, while code, tables and ADPCM do not. Score = mean |dx| over the window,
lower is more picture-like; blank/near-constant windows are rejected by a
variance floor.

Usage:
  python pce/tools/tilescan.py scan  [track]   # rank windows, write scan.json
  python pce/tools/tilescan.py dump  <offset>  # render one window to PNG
"""
import json, os, sys
import numpy as np
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

BIN = os.path.join(WORK, "pce", "snatcher_pce.bin")
# track-relative LBA of each MODE1_RAW track, from the extracted cue
TRACKS = {2: (4174, 34345), 24: (235149, 34198)}
TILE = 32
WIN_TILES = 32 * 32          # 32 tiles wide, 32 rows -> 256x256 px, 32 KB
STEP_TILES = 32 * 8          # slide 8 tile-rows at a time


def read_track(lba, sectors):
    """User data of a MODE1/2352 run, concatenated."""
    out = bytearray()
    with open(BIN, "rb") as f:
        f.seek(lba * 2352)
        for _ in range(sectors):
            s = f.read(2352)
            if len(s) < 2352:
                break
            out += s[16:16 + 2048]
    return np.frombuffer(bytes(out), dtype=np.uint8)


def decode(tiles):
    """(N,32) tile bytes -> (N,8,8) pixel values."""
    b = np.unpackbits(tiles, axis=1).reshape(-1, 32, 8)
    p0 = b[:, 0:16:2]                      # (N,8,8) rows of plane 0
    p1 = b[:, 1:16:2]
    p2 = b[:, 16:32:2]
    p3 = b[:, 17:32:2]
    return (p0 | (p1 << 1) | (p2 << 2) | (p3 << 3)).astype(np.uint8)


def as_image(px, tiles_wide=32):
    """(N,8,8) tiles laid out left to right, top to bottom."""
    n = (len(px) // tiles_wide) * tiles_wide
    px = px[:n].reshape(-1, tiles_wide, 8, 8)
    return px.transpose(0, 2, 1, 3).reshape(-1, tiles_wide * 8)


def score(img):
    """Mean absolute horizontal gradient; low = coherent = picture-like."""
    d = np.abs(np.diff(img.astype(np.int16), axis=1))
    return float(d.mean()), float(img.std())


def scan(track):
    lba, sectors = TRACKS[track]
    data = read_track(lba, sectors)
    ntiles = len(data) // TILE
    tiles = data[:ntiles * TILE].reshape(ntiles, TILE)
    px = decode(tiles)
    out = []
    for start in range(0, ntiles - WIN_TILES, STEP_TILES):
        img = as_image(px[start:start + WIN_TILES])
        g, sd = score(img)
        if sd > 1.5:
            out.append({"tile": int(start), "byte": int(start * TILE),
                        "grad": round(g, 3), "std": round(sd, 2)})
    out.sort(key=lambda r: r["grad"])
    json.dump(out, open(os.path.join(WORK, "pce", f"scan_t{track}.json"), "w"), indent=0)
    print(f"track {track}: {ntiles} tiles, {len(out)} windows, best:")
    for r in out[:15]:
        print("  ", r)


def dump(byte_off, track=2, tiles_wide=32, rows=32, name=None):
    from PIL import Image
    lba, sectors = TRACKS[track]
    data = read_track(lba, sectors)
    n = tiles_wide * rows
    tiles = data[byte_off:byte_off + n * TILE]
    tiles = tiles[:(len(tiles) // TILE) * TILE].reshape(-1, TILE)
    img = as_image(decode(tiles), tiles_wide)
    im = Image.fromarray((img * 17).astype(np.uint8), "L")
    p = os.path.join(WORK, "pce", name or f"win_{track}_{byte_off:08x}.png")
    im.resize((im.width * 2, im.height * 2), Image.NEAREST).save(p)
    print(p, im.size)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "scan":
        scan(int(sys.argv[2]) if len(sys.argv) > 2 else 2)
    else:
        dump(int(sys.argv[2], 0), *(int(x, 0) for x in sys.argv[3:]))
