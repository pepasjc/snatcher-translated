"""Undo the PS1-only censorship, using the uncensored art left on the disc.

HG101 records two things the Saturn port does not do: "the Playstation version
actually greys the screen to obscure some of the gore. It also puts a mosiac
over a maggot covered body later on." Both censored pictures were shipped
alongside the originals, which the game never loads.

## The factory-ruins corpse (ISZ_B020)

  CXK_B060  the severed head lying in its blood pool     shown as-is
  CXK_B061  the body, full colour, blood up the wall     never loaded
  CXK_B062  the same body, desaturated and dithered      what the game shows

CXK_B062 is the censored twin of CXK_B061 - HG101's "the Playstation version
actually greys the screen to obscure some of the gore" - and B061 is dead data
left on the disc. Both decompress to 25,148 bytes with the same two items
(128x128 + 64x128) and, crucially, byte-identical 256-colour palettes, so B060
and B061 can be cut against each other with no colour remapping.

Stacked, B061 over B060, the two are one continuous 192x256 painting: the same
floor, the same pool of blood across the join. The engine scrolls a 128-row
window over it, opens on the head and parks at the top - body only. The Sega CD
and PC Engine keep the head in frame for the whole conversation
(lparchive.org/Snatcher-(Screenshot)/Update 9).

So this writes B061 into B062's slot, uncensoring the scene and leaving the
framing alone. `--dy` re-cuts the window instead, taking rows DY..DY+127 of the
combined painting, which at DY=48 holds the torso, the severed head and the pool
in one frame the way the Sega CD does - but the engine still scrolls the full
128 rows first and then jumps, so it reads worse in motion than it looks as a
still. Default 0: faithful, uncensored, no re-framing.

11,224 bytes compressed against B062's 15,905-byte footprint, so it needs no
relocation; the tail is zero-padded because the loader reads the file-table size
(record 229, exec 0x4bfa0) rather than the file's own length.

## The maggot-covered body (the QUEEN hospital, CXQ)

  CXQ_B0A0  the skull clean, plus four sparse maggot overlays   never loaded
  CXQ_B0D0  the same four frames pre-composited AND mosaiced    what shows

Both decompress to 91,432 bytes with the same six items in the same places
(128x128 + 64x128 in section 0, four 128x128 in section 1) - B0D0 is B0A0 run
through a 4x4 averaging filter, mathematically block-constant. Their palettes
differ, so this one cannot be cut against anything; it is swapped whole.

B0A0 is 26,597 bytes against B0D0's 20,519, so it does not fit B0D0's sectors.
Rather than relocate it, the exec's file table is repointed: record 321 (file
0x4c3f0, `{lba, size, pad}` records from 0x4b4e4) is given B0A0's LBA and size,
so a load of file 321 reads the uncensored file already on the disc. Nothing is
written to the data area at all. This edits patched/SLPS_001.54, so it must run
after apply_translation.py rebuilds the exec and before patch_disc.py.

`--head` composites the severed head into the body picture the way the PC
Engine original frames it (work/pce/pce_b25_1.png, extracted with
pce/tools/pcescene.py): the PCE and PS1 pictures share the frame exactly, so
B060's head - same palette, same lighting, same angle - is scaled to the PCE
head's size and placed in front of the torso with a feathered edge, then
snapped back to the shared palette. PS1 art only; the PCE is the layout guide.

`--pack NAME PNG` puts any picture into any single-picture container: the
PNG (resized to the container's section-0 geometry, 192x128 for these) is
quantised to a fresh 256-colour palette - the container carries its own, so
nothing has to fit the old colours - the palette goes in as RGB555 at +16,
the indices into the items, and the result is recompressed; if it outgrows the
pristine file the colour count is halved until it fits. That is the door for
art made outside: the PCE picture restyled to the PS1 look, then packed.

## The female Snatcher's body (CXF_B080)

The PS1 keeps the PC Engine's picture of her on the locker-room floor pixel
for pixel - same 192x128 frame, same pose, same blood - and repaints one
thing: the dress, drawn back up over her chest. The PCE original is block 65
of the PCE disc (`pce/tools/pcescene.py export 65 0 0x7`). `--lisa` transplants
that region alone (LISA_BOX) from the PCE picture into the PS1 one, feathered,
quantised into CXF_B080's own palette; everything around it stays PS1 art.
Retired 2026-09-29 for `--lisa-saturn`: the Saturn ships the picture
uncensored (DATA.BIN chunk 433, 240x128), and the PS1's is that master
squeezed to 192 by dropping columns - so the same squeeze of the Saturn
original, with its own colours written into the container's palette, is
Konami's art whole, no transplant and no hand edit.

Usage:
  python ps1/tools/uncensor.py             # both fixes, original framing
  python ps1/tools/uncensor.py --lisa-saturn   # + the Snatcher's body, the Saturn original (the build)
  python ps1/tools/uncensor.py --lisa      # (retired) + the PCE chest transplant
  python ps1/tools/uncensor.py --lisa --lisa-png edit.png
                                       # same, and the composite as a PNG to edit
  python ps1/tools/uncensor.py --lisa-edit edit.png
                                       # store the hand edit as a pixel delta in
                                       # ps1/translation/uncensor_edits.json; from then on
                                       # --lisa regenerates composite + edit from the
                                       # source discs alone, no edited picture kept
  python ps1/tools/uncensor.py --pack CXG_B030 art/alice.png   # e.g. the dog
  python ps1/tools/uncensor.py --head      # + the head in frame (PCE composition)
  python ps1/tools/uncensor.py --dy 48     # experiment: re-cut to the Sega CD frame
  python ps1/tools/uncensor.py --skip-maggot
"""
import argparse, json, os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

from lzss import compress, decompress

SRC = os.path.join(ROOT, "discs/extracted_ps1", "DES", "CXK")
OUT = os.path.join(ROOT, "patched", "CXK_B062.BIN")
EXEC = os.path.join(ROOT, "patched", "SLPS_001.54")
LBA_MAP = os.path.join(ROOT, "work", "lba_map.json")
# pixel offsets and widths of the two items, as ps1/tools/gfx.items() reports them
ITEMS = [(568, 128), (16956, 64)]
ROWS = 128
FILE_TABLE = 0x4B4E4        # 12-byte {lba, size, pad} records, one per file
MAGGOT = (321, "CXQ_B0A0.BIN", "CXQ_B0D0.BIN")   # record, donor, censored


def recut(dy):
    """The 128 rows starting `dy` into the stacked body-over-head painting."""
    head, _ = decompress(open(os.path.join(SRC, "CXK_B060.BIN"), "rb").read())
    body, _ = decompress(open(os.path.join(SRC, "CXK_B061.BIN"), "rb").read())
    out = bytearray(body)
    for ip, w in ITEMS:
        rows = []
        for y in range(ROWS):
            s = y + dy
            src, s = (body, s) if s < ROWS else (head, s - ROWS)
            rows.append(src[ip + s * w:ip + (s + 1) * w])
        out[ip:ip + ROWS * w] = b"".join(rows)
    return bytes(out)


HEAD_CUT = (40, 0, 170, 64)     # the head and its pool in CXK_B060
HEAD_SCALE = 0.80
HEAD_POS = (40, 74)             # where the PCE lays the head in the frame
HEAD_MASK = (6, 0, 102, 50)     # ellipse inside the scaled cut
HEAD_FEATHER = 3


def as_rgb(dec, pal):
    """Section-0 picture of a decompressed container as an RGB image."""
    from PIL import Image
    import numpy as np
    a = np.zeros((ROWS, 192), dtype=np.uint8)
    for k, (ip, w) in enumerate(ITEMS):
        x0 = 0 if k == 0 else 128
        a[:, x0:x0 + w] = np.frombuffer(dec[ip:ip + ROWS * w], dtype=np.uint8).reshape(ROWS, w)
    return Image.fromarray(np.array(pal, dtype=np.uint8)[a])


def head_composite(dec_body, dec_head):
    """B061 with B060's head pasted in front of the torso; returns the
    modified decompressed buffer. Palettes are identical, so the paste is
    quantised back by nearest colour and only feathered pixels move."""
    from PIL import Image, ImageDraw, ImageFilter
    import numpy as np
    from gfx import palette
    pal = palette(dec_body)
    assert pal == palette(dec_head), "B060/B061 palettes differ"
    body, head = as_rgb(dec_body, pal), as_rgb(dec_head, pal)
    cut = head.crop(HEAD_CUT)
    w, h = int(cut.width * HEAD_SCALE), int(cut.height * HEAD_SCALE)
    cut = cut.resize((w, h), Image.LANCZOS)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse(HEAD_MASK, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(HEAD_FEATHER))
    body.paste(cut, HEAD_POS, mask)
    rgb = np.asarray(body, dtype=np.int32)
    P = np.array(pal, dtype=np.int32)
    idx = np.argmin(((rgb[:, :, None, :] - P[None, None, :, :]) ** 2).sum(-1), axis=2).astype(np.uint8)
    out = bytearray(dec_body)
    for k, (ip, wd) in enumerate(ITEMS):
        x0 = 0 if k == 0 else 128
        out[ip:ip + ROWS * wd] = idx[:, x0:x0 + wd].tobytes()
    return bytes(out)


def pack(name, png):
    """Quantise `png` into the pristine container `name` (DES/<fam>/<name>.BIN)
    and write patched/<name>.BIN in the original footprint."""
    from PIL import Image
    import numpy as np
    from gfx import items, sections
    fam = name.split("_")[0]
    src = os.path.join(ROOT, "discs/extracted_ps1", "DES", fam, name + ".BIN")
    raw = open(src, "rb").read()
    dec, _ = decompress(raw)
    base, size = sections(dec)[0]
    its = items(dec, base, size, 0)
    W, H = sum(w * 2 for _, w, _ in its), max(h for _, _, h in its)
    im = Image.open(png).convert("RGB")
    if im.size != (W, H):
        im = im.resize((W, H), Image.LANCZOS)
    for ncol in (256, 192, 128, 96, 64):
        q = im.quantize(colors=ncol, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        pal = (q.getpalette() or [])[:ncol * 3]
        pal += [0] * (ncol * 3 - len(pal))          # fewer colours than asked
        idx = np.asarray(q, dtype=np.uint8)
        out = bytearray(dec)
        for i in range(256):
            r, g, b = (pal[3 * i:3 * i + 3] if i < ncol else (0, 0, 0))
            struct.pack_into("<H", out, 16 + 2 * i, (r >> 3) | (g >> 3) << 5 | (b >> 3) << 10)
        x0 = 0
        for ip, whw, h in its:
            w = whw * 2
            out[ip:ip + w * h] = idx[:h, x0:x0 + w].tobytes()
            x0 += w
        comp = compress(bytes(out))
        back, _ = decompress(comp)
        if back != bytes(out):
            sys.exit("lzss round-trip failed - refusing to write")
        if len(comp) <= len(raw) or ncol == 128:
            break
        print(f"  {ncol} colours: {len(comp)} > {len(raw)} bytes, reducing")
    dst = os.path.join(ROOT, "patched", name + ".BIN")
    if len(comp) <= len(raw):
        open(dst, "wb").write(comp + bytes(len(raw) - len(comp)))
        print(f"{name}.BIN <- {png}: {W}x{H}, {ncol} colours, {len(comp)} bytes padded to {len(raw)}")
    else:
        # painted art compresses worse than the flat original: give the file
        # a slot past the image end and point its file-table record there
        open(dst, "wb").write(comp)
        lba = relocate(name + ".BIN", len(comp))
        print(f"{name}.BIN <- {png}: {W}x{H}, {ncol} colours, {len(comp)} bytes "
              f"(> {len(raw)}), relocated to LBA {lba}")


RELOC = os.path.join(ROOT, "work", "relocations.json")
SRC_IMG = os.path.join(ROOT, "discs/iso_ps1_jp", "Snatcher (Japan).bin")


def relocate(fname, size):
    """As introdiagram.relocate: a slot past the image end that no other
    relocated file overlaps, recorded in work/relocations.json, and the
    exec's file-table record (found by the pristine LBA/size) repointed."""
    lba_map = json.load(open(LBA_MAP))
    lba0, size0 = lba_map[fname][:2]
    exe = bytearray(open(EXEC, "rb").read())
    rec = exe.find(struct.pack("<II", lba0, size0))
    if rec < 0:
        rec = exe.find(struct.pack("<II", *json.load(open(RELOC)).get(fname, (0,)), size0)) if os.path.exists(RELOC) else -1
    assert rec >= 0, f"file-table record for {fname} not found in the exec"
    rel = json.load(open(RELOC)) if os.path.exists(RELOC) else {}
    need = (size + 2047) // 2048
    patched = os.path.join(ROOT, "patched")
    taken = [(at, (os.path.getsize(os.path.join(patched, f)) + 2047) // 2048)
             for f, at in rel.items() if f != fname and os.path.exists(os.path.join(patched, f))]
    lba = rel.get(fname)
    if lba is None or any(at < lba + need and lba < at + n for at, n in taken):
        lba = os.path.getsize(SRC_IMG) // 2352
        for at, n in taken:
            lba = max(lba, at + n)
    rel[fname] = lba
    json.dump(rel, open(RELOC, "w"))
    exe[rec:rec + 8] = struct.pack("<II", lba, size)
    open(EXEC, "wb").write(exe)
    return lba


LISA = ("CXF_B080", os.path.join(ROOT, "work", "pce", "pce_b65_0.png"))
LISA_BOX = (44, 56, 96, 90)
LISA_FEATHER, LISA_BLUR = 1.5, 0.6


def pce_picture(png, block, lst, pal_rec):
    """The PCE source picture, exported from the disc if it is not there yet."""
    if os.path.exists(png):
        return png
    try:
        import pcescene
    except Exception as e:
        sys.exit(f"{png} missing and pce/tools/pcescene.py unavailable ({e}); "
                 f"extract the PCE disc first (see pce/tools/tilescan.py)")
    pcescene.colour_screen(block, lst, out=png, pal_rec=pal_rec)
    return png


# The Saturn keeps the same locker-room picture uncensored, as Konami drew it:
# DATA.BIN chunk 433, a 240x128 VDP2 background. The PS1's is that master
# squeezed to 192 by dropping columns (nearest-neighbour 240 -> 192 matches
# the pristine CXF_B080 outside the chest to palette rounding), so the same
# squeeze gives the picture an uncensored PS1 release would have had.
SATURN_LISA = 433
SATURN_LISA_PNG = os.path.join(ROOT, "work", "saturn", "sat_433.png")


def saturn_picture():
    """Saturn chunk 433 as a 240x128 RGB PNG, rendered once by the Saturn
    tree's own satgfx.py (SNATCHER_SATURN, default this tree: the Saturn port
    lives in saturn/ beside the PS1's, and needs discs/extracted_saturn)."""
    if os.path.exists(SATURN_LISA_PNG):
        return SATURN_LISA_PNG
    import shutil, subprocess
    sat = os.environ.get("SNATCHER_SATURN", ROOT)
    tool = os.path.join(sat, "saturn", "tools", "satgfx.py")
    if not os.path.exists(tool):
        sys.exit(f"{SATURN_LISA_PNG} missing and no Saturn tree at {sat} "
                 f"(set SNATCHER_SATURN to a checkout with discs/extracted_saturn)")
    subprocess.run([sys.executable, tool, "render", str(SATURN_LISA)], cwd=sat, check=True,
                   stdout=subprocess.DEVNULL)
    src = os.path.join(sat, "work", "saturn", "gfx", f"{SATURN_LISA:03d}",
                       f"{SATURN_LISA:03d}_s1_bg_p0.png")
    os.makedirs(os.path.dirname(SATURN_LISA_PNG), exist_ok=True)
    shutil.copy(src, SATURN_LISA_PNG)
    return SATURN_LISA_PNG


def lisa_saturn(png_out=None):
    """CXF_B080 from the Saturn original: squeezed 240 -> 192 like Konami's
    PS1 art, its own colours written into the container's palette (no
    quantising - the Saturn picture has at most 256)."""
    from PIL import Image
    import numpy as np
    from gfx import items, sections
    name = LISA[0]
    im = Image.open(saturn_picture()).convert("RGB")
    assert im.size == (240, 128), im.size
    im = im.resize((192, 128), Image.NEAREST)
    rgb = np.asarray(im)
    cols, idx = np.unique(rgb.reshape(-1, 3), axis=0, return_inverse=True)
    assert len(cols) <= 256, len(cols)
    idx = idx.reshape(128, 192).astype(np.uint8)
    if png_out:
        im.save(png_out)
        print(f"{png_out} <- Saturn chunk {SATURN_LISA}, 192x128")
    src = os.path.join(ROOT, "discs/extracted_ps1", "DES", name[:3], name + ".BIN")
    raw = open(src, "rb").read()
    dec, _ = decompress(raw)
    base, size = sections(dec)[0]
    its = items(dec, base, size, 0)
    out = bytearray(dec)
    for i in range(256):
        r, g, b = (int(c) for c in cols[i]) if i < len(cols) else (0, 0, 0)
        struct.pack_into("<H", out, 16 + 2 * i, (r >> 3) | (g >> 3) << 5 | (b >> 3) << 10)
    x0 = 0
    for ip, whw, h in its:
        w = whw * 2
        out[ip:ip + w * h] = idx[:h, x0:x0 + w].tobytes()
        x0 += w
    comp = compress(bytes(out))
    back, _ = decompress(comp)
    if back != bytes(out):
        sys.exit("lzss round-trip failed - refusing to write")
    dst = os.path.join(ROOT, "patched", name + ".BIN")
    if len(comp) <= len(raw):
        open(dst, "wb").write(comp + bytes(len(raw) - len(comp)))
        print(f"{name}.BIN <- Saturn chunk {SATURN_LISA}: {len(cols)} colours, "
              f"{len(comp)} bytes padded to {len(raw)}")
    else:
        open(dst, "wb").write(comp)
        lba = relocate(name + ".BIN", len(comp))
        print(f"{name}.BIN <- Saturn chunk {SATURN_LISA}: {len(cols)} colours, "
              f"{len(comp)} bytes (> {len(raw)}), relocated to LBA {lba}")


EDITS = os.path.join(ROOT, "ps1/translation", "uncensor_edits.json")


def load_edits(name):
    """Hand edits kept as pixel deltas ({name: [[x, y, r, g, b], ...]}) so no
    edited picture has to live in the repo - only the change."""
    if not os.path.exists(EDITS):
        return []
    return json.load(open(EDITS)).get(name, [])


def apply_edits(img, name):
    px = img.load()
    for x, y, r, g, b in load_edits(name):
        px[x, y] = (r, g, b)
    return img


def make_edit(name, edited_png, generated_png):
    """Record edited-vs-generated as a delta in ps1/translation/uncensor_edits.json."""
    from PIL import Image
    import numpy as np
    a = np.asarray(Image.open(generated_png).convert("RGB"))
    b = np.asarray(Image.open(edited_png).convert("RGB"))
    if a.shape != b.shape:
        sys.exit(f"{edited_png} is {b.shape[1]}x{b.shape[0]}, expected {a.shape[1]}x{a.shape[0]}")
    ys, xs = np.nonzero((a != b).any(axis=2))
    delta = [[int(x), int(y)] + [int(v) for v in b[y, x]] for y, x in zip(ys, xs)]
    edits = json.load(open(EDITS)) if os.path.exists(EDITS) else {}
    edits[name] = delta
    json.dump(edits, open(EDITS, "w"), separators=(",", ":"))
    print(f"{EDITS}: {name} <- {len(delta)} pixel edits from {edited_png}")


def lisa_composite(png_out=None):
    """CXF_B080 with the PCE's chest region pasted in; writes patched/CXF_B080.BIN
    and, with `png_out`, the composite as a true-colour PNG to edit by hand."""
    from PIL import Image, ImageDraw, ImageFilter
    import numpy as np
    from gfx import items, palette, sections
    name, png = LISA
    pce_picture(png, 65, 0, 0x7)
    src = os.path.join(ROOT, "discs/extracted_ps1", "DES", name[:3], name + ".BIN")
    raw = open(src, "rb").read()
    dec, _ = decompress(raw)
    pal = palette(dec)
    base, size = sections(dec)[0]
    its = items(dec, base, size, 0)
    ps1 = as_rgb(dec, pal)
    pce = Image.open(png).convert("RGB")
    cut = pce.crop(LISA_BOX).filter(ImageFilter.GaussianBlur(LISA_BLUR))
    mask = Image.new("L", cut.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, cut.width - 1, cut.height - 1), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(LISA_FEATHER))
    ps1.paste(cut, LISA_BOX[:2], mask)
    apply_edits(ps1, name)
    rgb = np.asarray(ps1, dtype=np.int32)
    P = np.array(pal, dtype=np.int32)
    idx = np.argmin(((rgb[:, :, None, :] - P[None, None, :, :]) ** 2).sum(-1), axis=2).astype(np.uint8)
    if png_out:
        os.makedirs(os.path.dirname(png_out) or ".", exist_ok=True)
        Image.fromarray(np.array(pal, dtype=np.uint8)[idx]).save(png_out)
        print(f"{png_out} <- composite, palette-exact, 192x128")
    out = bytearray(dec)
    x0 = 0
    for ip, whw, h in its:
        w = whw * 2
        out[ip:ip + w * h] = idx[:h, x0:x0 + w].tobytes()
        x0 += w
    comp = compress(bytes(out))
    back, _ = decompress(comp)
    if back != bytes(out):
        sys.exit("lzss round-trip failed - refusing to write")
    dst = os.path.join(ROOT, "patched", name + ".BIN")
    if len(comp) <= len(raw):
        open(dst, "wb").write(comp + bytes(len(raw) - len(comp)))
        print(f"{name}.BIN <- PCE chest transplant: {len(comp)} bytes padded to {len(raw)}")
    else:
        open(dst, "wb").write(comp)
        lba = relocate(name + ".BIN", len(comp))
        print(f"{name}.BIN <- PCE chest transplant: {len(comp)} bytes (> {len(raw)}), relocated to LBA {lba}")


def repoint(record, donor, censored):
    """Give `record` the donor file's LBA and size, so loading it reads the
    uncensored file instead. The record is verified against the censored file's
    own LBA/size first, so a changed build fails loudly rather than silently."""
    lba = json.load(open(LBA_MAP))
    exe = bytearray(open(EXEC, "rb").read())
    off = FILE_TABLE + 12 * record
    have = struct.unpack_from("<II", exe, off)
    want = tuple(lba[censored][:2])
    if have != want and have != tuple(lba[donor][:2]):
        sys.exit(f"file-table record {record} is {have}, expected {want} "
                 f"({censored}) - refusing to write")
    struct.pack_into("<II", exe, off, *lba[donor][:2])
    open(EXEC, "wb").write(exe)
    print(f"file table record {record} -> {donor} "
          f"lba {lba[donor][0]} size {lba[donor][1]} (was {censored})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dy", type=int, default=0,
                    help="re-cut: scroll offset into the 192x256 painting (0-128)")
    ap.add_argument("--skip-maggot", action="store_true",
                    help="leave the QUEEN hospital mosaic alone")
    ap.add_argument("--head", action="store_true",
                    help="composite the severed head into the body picture")
    ap.add_argument("--preview", help="also write the body picture as PNG")
    ap.add_argument("--lisa", action="store_true",
                    help="transplant the PCE chest region into CXF_B080")
    ap.add_argument("--lisa-png", metavar="PNG",
                    help="with --lisa: also write the composite as an editable PNG")
    ap.add_argument("--lisa-edit", metavar="EDITED_PNG",
                    help="store EDITED_PNG minus the generated composite as a pixel "
                         "delta in ps1/translation/uncensor_edits.json, then rebuild")
    ap.add_argument("--lisa-saturn", metavar="PNG", nargs="?", const="",
                    help="CXF_B080 from the Saturn's uncensored original (chunk 433); "
                         "optional PNG = also write the squeezed picture")
    ap.add_argument("--pack", nargs=2, metavar=("NAME", "PNG"),
                    help="put a picture into a single-picture container")
    a = ap.parse_args()
    if a.pack:
        pack(*a.pack)
        return
    if not 0 <= a.dy <= ROWS:
        sys.exit(f"--dy must be 0..{ROWS}")
    dec = recut(a.dy)
    if a.head:
        head, _ = decompress(open(os.path.join(SRC, "CXK_B060.BIN"), "rb").read())
        dec = head_composite(dec, head)
    if a.preview:
        from gfx import palette
        as_rgb(dec, palette(dec)).save(a.preview)
    comp = compress(dec)
    back, _ = decompress(comp)
    if back != dec:
        sys.exit("lzss round-trip failed - refusing to write")
    budget = os.path.getsize(os.path.join(SRC, "CXK_B062.BIN"))
    if len(comp) > budget:
        sys.exit(f"{len(comp)} bytes over CXK_B062's {budget}-byte footprint - "
                 f"relocate it (work/relocations.json)")
    open(OUT, "wb").write(comp + b"\0" * (budget - len(comp)))
    print(f"CXK_B062.BIN <- CXK_B061 re-cut at dy={a.dy}: "
          f"{len(comp)} bytes padded to {budget}")
    if not a.skip_maggot:
        repoint(*MAGGOT)
    if a.lisa_edit:
        import tempfile
        gen = os.path.join(tempfile.gettempdir(), "lisa_generated.png")
        saved = load_edits(LISA[0])
        if saved:                              # delta against the clean composite
            edits = json.load(open(EDITS)); edits.pop(LISA[0]); json.dump(edits, open(EDITS, "w"))
        lisa_composite(gen)
        make_edit(LISA[0], a.lisa_edit, gen)
        a.lisa = True
    if a.lisa_saturn is not None:
        lisa_saturn(a.lisa_saturn or None)
    elif a.lisa:
        lisa_composite(a.lisa_png)


if __name__ == "__main__":
    main()
