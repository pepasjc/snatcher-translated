"""Chunk 331 (0x14B): the OPTION MENU container - panel frame, Konami's English word
images, the pad-button icons. Layout report, a PNG sheet decoded from the chunk, and the
glyph inventory of the 6x7 row lettering.

Container (satgfx.py's format): type 3 sprite pixels (8 bpp), type 1 palettes, type 2
index. The index's offset tables are {u16 nA, u16 nB, 12 x 0}, then nA u32 anim offsets
and nB u32 list offsets, EACH TABLE PADDED TO A MULTIPLE OF 4 ENTRIES - the relocation in
op 0x18's registrar 0x060B2CF0 adds (n + 3) & ~3 words (`add #3; and #-4`). With nA = 14
the list table starts at +0x50, not +0x48 (satgfx.index reads it 8 bytes early).

Usage (repo root):
    python saturn/tools/satoptlabels.py [report|sheet|glyphs]     default: all three
Outputs work/saturn/optmenu/chunk331.txt, labels.png, glyphs.png.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import satgfx

CHUNK = 331
OUT = os.path.join(WORK, "saturn", "optmenu")
VDP1_DEST = 0x19000          # op 17 (0, 0, 0) -> 0x060E4C24[0] = 0x25C19000
VDP1_NEXT = 0x30000          # 0x060E4C24[1]: the title's own sprites
NAMES = {0: "OPTION MENU (title 'OPTION ME' + 'NU', rows image)", 1: "MESSAGE SPEED submenu", 2: "CONTROLLER submenu",
         3: "SOUND MODE submenu", 4: "panel frame (two 128x96 halves + right edge)",
         5: "icon A", 6: "icon B", 7: "icon C", 8: "icon X", 9: "icon Y", 10: "icon Z", 11: "icon d-pad",
         12: "icon L", 13: "icon R"}
# row lettering: (image offset in the decoded chunk, width, height, [(ink top row, text)])
# Letters and digits Konami's option lettering lacks, DRAWN BY HAND to match it (2026-09-30, for the
# WALLPAPER rows ACT 1-3 / TWINBEE / KONAMI / TOKIMEKI / BLACK): 6x7, one colour (index 9), thin one-pixel strokes on the
# top half and a doubled left stem on the bottom rows, as E/P/D/C/L have; B = R's bowl on top
# over D/C's heavy lower half, K = H's thin upper stem with X's doubled lower diagonal.
EXTRA_GLYPHS = {
    "B": ["#####.",
          "#...#.",
          "#...#.",
          "######",
          "##...#",
          "##...#",
          "######"],
    # digits for ACT 1/2/3: 1 = T's two-pixel stem with a flag and a foot; 2 and 3 = S's
    # full-width bars and one-pixel right side, heavy (two-pixel) strokes on the bottom rows
    "1": ["..##..",
          ".###..",
          "..##..",
          "..##..",
          "..##..",
          "..##..",
          ".####."],
    "2": ["######",
          ".....#",
          ".....#",
          "######",
          "##....",
          "##....",
          "######"],
    "3": ["######",
          ".....#",
          ".....#",
          ".#####",
          "....##",
          "....##",
          "######"],
    "K": ["#...#.",
          "#..#..",
          "#.#...",
          "###...",
          "##.##.",
          "##..##",
          "##...#"],
}

TEXTS = [(0x0C20, 128, 64, [(4, "MESSAGE SPEED"), (20, "CONTROL PAD"), (36, "SOUND MODE"), (52, "EXIT")]),
         (0x2FE0, 128, 72, [(1, "MESSAGE SPEED"), (28, "FAST"), (44, "NORMAL"), (60, "SLOW")]),
         (0x6B60, 72, 32, [(4, "STEREO"), (20, "MONO")]),
         (0x7460, 104, 8, [(1, "CONTROLLER")]), (0x6820, 104, 8, [(1, "SOUND MODE")]),
         (0x77A0, 64, 16, [(1, "CHOOSE")]), (0x7BA0, 64, 16, [(1, "CANCEL")]), (0x7FA0, 64, 16, [(1, "NEXT>")])]


def load():
    d = satgfx.load(CHUNK)
    secs = satgfx.parse(d)
    return d, secs


def index(d, o):
    nA, nB = struct.unpack_from(">HH", d, o)
    tA = o + 16
    tB = tA + 4 * ((nA + 3) & ~3)
    anims, lists = [], []
    for i in range(nA):
        a = o + struct.unpack_from(">I", d, tA + 4 * i)[0]
        n = struct.unpack_from(">H", d, a)[0]
        anims.append((a, [struct.unpack_from(">HH", d, a + 2 + 4 * k) for k in range(n)]))
    for i in range(nB):
        a = o + struct.unpack_from(">I", d, tB + 4 * i)[0]
        n = struct.unpack_from(">H", d, a)[0]
        recs = []
        for r in range(n):
            ra = a + 8 + 12 * r
            ctrl, sz, clut, srca, x, y = struct.unpack_from(">6H", d, ra)
            recs.append(dict(at=ra, ctrl=ctrl, w=sz >> 8, h=sz & 0xFF, clut=clut, srca=srca, x=x, y=y))
        lists.append((a, recs))
    return nA, nB, tA, tB, anims, lists


def report():
    d, secs = load()
    (t3, o3, s3), (t1, o1, s1), (t2, o2, s2) = secs
    nA, nB, tA, tB, anims, lists = index(d, o2)
    L = [f"chunk {CHUNK} (0x{CHUNK:X}), LZ3, decoded {len(d)} bytes (offsets below = decoded chunk offsets)",
         "header: " + d[:32].hex(" "),
         f"  sec 0 type 3 sprites  @0x{o3:05x} size 0x{s3:x} ({s3})  -> VDP1 VRAM 0x{VDP1_DEST:05x}..0x{VDP1_DEST + s3:05x} (op 17 0000 0000 0000)",
         f"  sec 1 type 1 palettes @0x{o1:05x} size 0x{s1:x}: 2 x 256 RGB555 -> CRAM work ptr 2/3 0x202BD400/0x202BD600 (op 15 0000 0000 0002 0000 0000),",
         "        fade records 2/3 (op 1d 0002 0002 0000, 1d 0003 0003 0001); sprites use clut 0x0000 (panel, palette 0) / 0x0100 (words + icons, palette 1)",
         f"  sec 2 type 2 index    @0x{o2:05x} size 0x{s2:x}: nA {nA} nB {nB}; anim table @0x{tA:05x}, list table @0x{tB:05x}",
         "        (op 18 0000 0000 0000 copies it to 0x060E4C00[0] = 0x202C8000 and relocates the offsets)",
         "", "anims (anim k = list k, 1 frame; op 05's second argument picks the anim):"]
    for i, (a, fr) in enumerate(anims):
        L.append(f"  anim {i:2d} @0x{a:05x}: {fr}")
    L.append("")
    L.append("lists (records: ctrl, w x h, clut, CMDSRCA-relative srca -> decoded offset / VDP1 addr, x, y relative to the object):")
    used = []
    for i, (a, recs) in enumerate(lists):
        L.append(f"  list {i:2d} @0x{a:05x} {NAMES.get(i, '')}")
        for r in recs:
            off = o3 + r["srca"] * 8
            used.append((off, off + r["w"] * r["h"]))
            L.append(f"     rec @0x{r['at']:05x}: ctrl {r['ctrl']:04x} {r['w']:3d}x{r['h']:<3d} 8bpp clut {r['clut']:04x} "
                     f"srca {r['srca']:04x} -> data @0x{off:05x}..0x{off + r['w'] * r['h']:05x}, VDP1 0x{VDP1_DEST + r['srca'] * 8:05x} "
                     f"(CMDSRCA 0x{(VDP1_DEST >> 3) + r['srca']:04x}), at ({r['x']},{r['y']})")
    used.sort()
    gaps, pos = [], o3
    for a, b in used:
        if a > pos:
            gaps.append((pos, a))
        pos = max(pos, b)
    if pos < o3 + s3:
        gaps.append((pos, o3 + s3))
    L += ["", "sprite bytes no list references: " + (", ".join(f"0x{a:05x}..0x{b:05x} ({b - a} B)" for a, b in gaps) or "none"),
          "", "all lettering: one colour, index 9 of palette 1 (clut 0x0100) on 0 (transparent); 6x7 glyphs on a 10-px pitch",
          "('I' 2 px wide centred in its cell), words centred in their image; rows 16 px apart, ink rows +4..+10 in the",
          "OPTION rows image (MESSAGE SPEED's rows: title ink 1..7, rows 28/44/60).",
          "", f"VDP1: the sprites end at 0x{VDP1_DEST + s3:05x}; the next upload target 0x060E4C24[1] = 0x{VDP1_NEXT:05x} (title sprites).",
          f"  -> 0x{VDP1_NEXT - VDP1_DEST - s3:x} ({VDP1_NEXT - VDP1_DEST - s3}) bytes between them; on the OPTION MENU no VDP1 command",
          "  reads that range (command list walked in o_menu.state) - room to append new word images to section 0."]
    txt = "\n".join(L) + "\n"
    open(os.path.join(OUT, "chunk331.txt"), "w", encoding="utf-8").write(txt)
    print(txt)
    return d, secs, lists


def sheet():
    from PIL import Image, ImageDraw
    d, secs = load()
    (t3, o3, s3), (t1, o1, s1), (t2, o2, s2) = secs
    pals = satgfx.palettes(d, secs)
    nA, nB, tA, tB, anims, lists = index(d, o2)
    tiles = []
    for i, (a, recs) in enumerate(lists):
        for r in recs:
            src = o3 + r["srca"] * 8
            pal = pals[1 if r["clut"] >= 0x100 else 0]
            im = satgfx.image_from(r["w"], r["h"], d[src:src + r["w"] * r["h"]], pal).convert("RGB")
            tiles.append((f"list {i} {r['w']}x{r['h']} @0x{src:05x} clut {r['clut']:04x} pos ({r['x']},{r['y']})", im))
    W = 300
    H = sum(t[1].height + 14 for t in tiles)
    s = Image.new("RGB", (W, H), (40, 0, 40))
    dr = ImageDraw.Draw(s)
    y = 0
    for lab, im in tiles:
        dr.text((0, y), lab, fill=(255, 255, 0))
        y += 12
        s.paste(im, (0, y))
        y += im.height + 2
    s = s.resize((W * 2, H * 2), Image.NEAREST)
    s.save(os.path.join(OUT, "labels.png"))
    print("labels.png", s.size)


def glyphs():
    from PIL import Image
    d, secs = load()
    found = {}
    for off, w, h, lines in TEXTS:
        for y0, txt in lines:
            cols = [x for x in range(w) if any(d[off + y * w + x] for y in range(y0, y0 + 7))]
            segs, s, prev = [], None, None
            for x in cols:
                if s is None:
                    s = x
                elif x != prev + 1:
                    segs.append((s, prev)); s = x
                prev = x
            segs.append((s, prev))
            letters = txt.replace(" ", "")
            assert len(segs) == len(letters), (txt, segs)
            for (a, b), ch in zip(segs, letters):
                if ch not in found:
                    found[ch] = (off, w, y0, a, b)
    chars = sorted(found)
    im = Image.new("RGB", (len(chars) * 10 * 4, 9 * 4), (0, 0, 0))
    px = im.load()
    for k, ch in enumerate(chars):
        off, w, y0, a, b = found[ch]
        for y in range(7):
            for x in range(a, b + 1):
                if d[off + (y0 + y) * w + x]:
                    for dy in range(4):
                        for dx in range(4):
                            px[(k * 10 + (x - a) + 1) * 4 + dx, (y + 1) * 4 + dy] = (0, 255, 64)
    im.save(os.path.join(OUT, "glyphs.png"))
    txt = ["", "glyphs (6x7, 10-px pitch) present: " + " ".join(chars),
           "missing: " + " ".join(c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" if c not in found),
           "source of each (decoded offset of the image, image width, ink top row, columns):"]
    txt += [f"  {c}: image 0x{v[0]:05x} w{v[1]} row {v[2]} x {v[3]}..{v[4]}" for c, v in sorted(found.items())]
    open(os.path.join(OUT, "chunk331.txt"), "a", encoding="utf-8").write("\n".join(txt) + "\n")
    print("\n".join(txt))


def main(argv):
    what = argv or ["report", "sheet", "glyphs"]
    for w in what:
        {"report": report, "sheet": sheet, "glyphs": glyphs}[w]()


if __name__ == "__main__":
    main(sys.argv[1:])
