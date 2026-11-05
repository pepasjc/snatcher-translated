"""The Saturn Snatcher font: where it lives, how a code becomes a glyph, dump/render.

Found 2026-09-12 from a RAM/VRAM dump at the first Junker HQ dialogue box
(work/saturn/font/): the font never sits in work RAM as 1-bpp glyphs - it is
DATA.BIN **chunk 0** (LZ3, 35,276 -> 52,640 bytes; lz3.py decodes it), loaded
by 0x060B4530 = load_chunk(0, VDP1 VRAM 0x25C08000, budget 0xD000) straight
in the form VDP1 draws it:

  * 112-byte blocks = one 16x14 4-bpp sprite each, FOUR glyphs per block, one
    per bit-plane (a 1 in plane p at (x, y) is ink for glyph 4*block + p).
    The 12x12 glyph sits at (1, 1) of the 16x14 cell; rows 0 and 13, columns
    0 and 13-15 are blank. 470 blocks in the file (1,880 glyph slots), the
    game uses indices 0 (blank) and 1..1872 (1512 unused), so 7 slots are
    spare and the VDP1 budget of 0xD000 = 475 blocks allows 1,900.
  * glyph index g -> block g >> 2 at VDP1 0x8000 + 112*(g >> 2), plane g & 3.
    The cell renderer 0x060B4970 turns the 4x20 text cells (ctx 0x060F24B0 +
    0x3FA, {u16 sjis, u8 colour, pad}) into 80 sprite records at 0x060E5358
    (12 bytes each: +4 CMDCOLR, +6 CMDSRCA): CMDSRCA = 0x1000 + 14*(g >> 2)
    (units of 8 bytes), CMDCOLR = 0x2A00 + 16*colour + 4*(g & 3), so the
    CLUT at VDP1 0x15000 + 128*colour + 32*plane picks the plane. The CLUTs
    (0x440 bytes) are copied from exec 0x060E5BE6 by the same loader. The
    draw command is CMDCTRL 0, CMDPMOD 0x08C8, CMDSIZE 0x020E (16x14).
  * SJIS -> glyph index: a BE u16 table at exec 0x060E6CF0 indexed by
    (sjis - 0x8140), 0x1734 entries (SJIS 0x8140..0x9873 - the PS1's own
    range test), read through the biased pool constant 0x060D6A70 + 2*sjis.
    No range check: a code outside it reads exec bytes as an index. 1,872
    codes are non-zero, assigned in SJIS order; 0 = blank. Every code the
    game does not use maps to 0 (blank), so unlike the PS1 there is no
    "unused kanji slot" per JIS row: the font is exactly the used set, and
    a pair glyph must take over a glyph the English no longer draws - but
    ANY of the 5,940 table codes (valid SJIS or not) can name any glyph, so
    the PS1's pair codes can be kept verbatim.
  * bank text -> SJIS: 0x060C4D24(src) = strlen, xmalloc, then every byte
    NEGATED until the null (`neg`). The PS1 "descending JIS" codec is the
    same thing seen from the other side: code = (-sjis_hi, -sjis_lo).
    Dialogue path: 0x060B82A8(off) -> src = [0x060FD164] + off (the bank's
    string region, loaded at 0x002E8000; bytecode at 0x002F8000) ->
    0x060C4D24 -> layout 0x060B45C4 / show 0x060B8224 (SJIS from here on,
    like the name table at 0x060C17F4).

The PS1 reference (the same glyph art: 1,603 of the 1,610 kanji equal the
PS1's 12x12 bitmap, 7 are pixel touch-ups - 員 既 断 鎮 認 癒 腕; kana and
symbols are not compared, the PS1 keeps those outside its kanji slot formula)
is read from PS1_EXEC, default
discs/extracted_ps1/SLPS_001.54 (the PS1 extraction), read-only.

Usage (repo root):
    python saturn/tools/satfont.py dump              chunk 0 -> work/saturn/font/font_chunk0.bin, table.json
    python saturn/tools/satfont.py sheet [out.png]   the whole font, 2x, 32 glyphs per row (work/saturn/font/sheet.png)
    python saturn/tools/satfont.py show <text>       print glyphs for SJIS text (from the table)
    python saturn/tools/satfont.py compare           every glyph against the PS1 exec's bitmap
    python saturn/tools/satfont.py table             the SJIS -> index table, one line per code
    --state <mednafen state>  before the command: take the font from that state's VDP1 VRAM instead of chunk 0
"""
import os, sys, struct, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import lz3

MAIN_L = lz3.MAIN_L
MAIN_BASE = 0x060B0000
FONT_CHUNK = 0
BLOCK = 112                    # bytes per 16x14 4-bpp block
CELL_W, CELL_H = 16, 14
GLYPH = 12                     # 12x12 at (1, 1) inside the cell
VDP1_FONT = 0x8000             # VDP1 VRAM offset of block 0 (CMDSRCA 0x1000)
VDP1_BUDGET = 0xD000           # the loader's size argument: 475 blocks
CMDSRCA_BASE = 0x1000
TABLE_ADDR = 0x060E6CF0        # u16 BE per SJIS code from 0x8140
TABLE_LO = 0x8140
TABLE_N = 0x1734               # to 0x9873 inclusive
CLUT_ADDR = 0x060E5BE6         # 0x440 bytes -> VDP1 0x15000
LOADER = 0x060B4530
RENDERER = 0x060B4970
CONVERTER = 0x060C4D24
OUT = os.path.join(WORK, "saturn", "font")

PS1_EXEC = os.environ.get("PS1_EXEC") or os.path.join(ROOT, "discs", "extracted_ps1", "SLPS_001.54")
PS1_FONT = 0x4CB80


def code_to_sjis(code):
    """Bank text code (2 bytes, BE) -> SJIS: the engine negates each byte."""
    return (((-(code >> 8)) & 0xFF) << 8) | ((-(code & 0xFF)) & 0xFF)


def sjis_to_code(sjis):
    return code_to_sjis(sjis)          # negation is its own inverse


def load_font(path=None):
    """The font as the 52,640-byte block array (chunk 0 decoded, or a raw dump)."""
    if path:
        return open(path, "rb").read()
    with open(lz3.DATA_BIN, "rb") as f:
        return lz3.decode(lz3.read_chunk(f, FONT_CHUNK))


def n_blocks(font):
    return len(font) // BLOCK


def vdp1_vram(state):
    """VDP1 VRAM (512 KB, CPU byte order) out of a Beetle Saturn savestate.

    Same MDFNSVST walk as saturn/harness/satmem.state_ram, for the VDP1
    section's `VRAM` variable (Mednafen keeps it as host uint16 too). The
    live font is vdp1_vram(state)[VDP1_FONT:VDP1_FONT + VDP1_BUDGET]."""
    off = 32
    while off + 36 <= len(state):
        name = state[off:off + 32].split(b"\0")[0]
        size = struct.unpack_from("<I", state, off + 32)[0]
        if name == b"VDP1":
            p, end = off + 36, off + 36 + size
            while p < end:
                nl = state[p]; nm = state[p + 1:p + 1 + nl]
                vs = struct.unpack_from("<I", state, p + 1 + nl)[0]
                p += 1 + nl + 4
                if nm == b"VRAM":
                    b = bytearray(state[p:p + vs])
                    b[0::2], b[1::2] = state[p + 1:p + vs:2], state[p:p + vs:2]
                    return bytes(b)
                p += vs
        off += 36 + size
    raise ValueError("VDP1/VRAM not in state")


def table(exe=None):
    """{sjis: glyph index} for every non-zero entry."""
    d = exe or open(MAIN_L, "rb").read()
    off = TABLE_ADDR - MAIN_BASE
    out = {}
    for i in range(TABLE_N):
        v = struct.unpack_from(">H", d, off + 2 * i)[0]
        if v:
            out[TABLE_LO + i] = v
    return out


def glyph_index(sjis, tab):
    return tab.get(sjis, 0) if TABLE_LO <= sjis < TABLE_LO + TABLE_N else None


def cell_rows(font, index):
    """The 16x14 cell of glyph `index` as 14 ints, bit 15 = leftmost pixel."""
    blk, plane = index >> 2, index & 3
    data = font[blk * BLOCK:(blk + 1) * BLOCK]
    rows = []
    for y in range(CELL_H):
        v = 0
        for x in range(CELL_W):
            b = data[y * 8 + x // 2]
            nib = b >> 4 if x % 2 == 0 else b & 15
            if nib & (1 << plane):
                v |= 0x8000 >> x
        rows.append(v)
    return rows


def glyph_rows(font, index):
    """The 12x12 glyph as 12 ints, bit 11 = leftmost (the PS1 pairfont row form)."""
    return [(r >> 3) & 0xFFF for r in cell_rows(font, index)[1:1 + GLYPH]]


def set_glyph(font, index, rows12):
    """Write a 12-row glyph into a block array (bytearray) at `index`."""
    blk, plane = index >> 2, index & 3
    base = blk * BLOCK
    for y in range(CELL_H):
        r = rows12[y - 1] if 1 <= y <= GLYPH else 0
        for x in range(CELL_W):
            on = 1 <= x <= GLYPH and (r >> (GLYPH - x)) & 1
            i = base + y * 8 + x // 2
            shift = 4 if x % 2 == 0 else 0
            nib = (font[i] >> shift) & 15
            nib = (nib | (1 << plane)) if on else (nib & ~(1 << plane))
            font[i] = (font[i] & ~(15 << shift)) | (nib << shift)


def ps1_glyph(ch, exe=None):
    """The PS1 exec's 12x12 bitmap for a JIS level-1 character (rows as glyph_rows)."""
    d = exe or open(PS1_EXEC, "rb").read()
    b = ch.encode("iso2022_jp")[3:5]
    ku, ten = b[0] - 0x20, b[1] - 0x20
    slot = (ku - 1) * 94 + (ten - 1) - 845
    if slot < 0:
        return None
    g = d[PS1_FONT + 18 * slot:PS1_FONT + 18 * slot + 18]
    out = []
    for i in range(6):
        w = (g[3 * i] << 16) | (g[3 * i + 1] << 8) | g[3 * i + 2]
        out += [w >> 12, w & 0xFFF]
    return out


def ascii_rows(rows, w=GLYPH):
    return ["".join("#" if r & (1 << (w - 1 - x)) else "." for x in range(w)) for r in rows]


def sheet(font, out, per_row=32, scale=2, first=0, last=None):
    from PIL import Image, ImageDraw
    last = n_blocks(font) * 4 if last is None else last
    n = last - first
    rows = (n + per_row - 1) // per_row
    cw, ch = (CELL_W + 1) * scale, (CELL_H + 1) * scale
    lab = 40
    im = Image.new("RGB", (lab + per_row * cw, rows * ch), (24, 24, 32))
    dr = ImageDraw.Draw(im)
    for k in range(n):
        g = first + k
        cx, cy = lab + (k % per_row) * cw, (k // per_row) * ch
        if k % per_row == 0:
            dr.text((2, cy + 2), str(g), fill=(160, 160, 160))
        for y, r in enumerate(cell_rows(font, g)):
            for x in range(CELL_W):
                if r & (0x8000 >> x):
                    dr.rectangle((cx + x * scale, cy + y * scale, cx + x * scale + scale - 1, cy + y * scale + scale - 1),
                                 fill=(255, 255, 255))
        dr.rectangle((cx, cy, cx + CELL_W * scale, cy + CELL_H * scale), outline=(60, 60, 80))
    im.save(out)
    return out


def main(argv):
    font = None
    if argv[:1] == ["--state"]:
        font = vdp1_vram(open(argv[1], "rb").read())[VDP1_FONT:VDP1_FONT + VDP1_BUDGET]
        argv = argv[2:]
    cmd = argv[0] if argv else "sheet"
    os.makedirs(OUT, exist_ok=True)
    font = load_font() if font is None else font
    tab = table()
    if cmd == "dump":
        p = os.path.join(OUT, "font_chunk0.bin")
        open(p, "wb").write(font)
        json.dump({f"{k:04X}": v for k, v in sorted(tab.items())}, open(os.path.join(OUT, "table.json"), "w"), indent=0)
        used = sorted(set(tab.values()))
        print(f"{p}: {len(font)} bytes = {n_blocks(font)} blocks = {n_blocks(font) * 4} glyph slots; "
              f"table: {len(tab)} codes, indices 1..{max(used)}, unused below max "
              f"{sorted(set(range(1, max(used) + 1)) - set(used))}, budget {VDP1_BUDGET // BLOCK} blocks")
    elif cmd == "sheet":
        out = argv[1] if len(argv) > 1 else os.path.join(OUT, "sheet.png")
        print(sheet(font, out))
    elif cmd == "show":
        for ch in " ".join(argv[1:]):
            sj = int.from_bytes(ch.encode("sjis", "replace"), "big")
            g = glyph_index(sj, tab)
            print(f"{ch} sjis {sj:04X} code {sjis_to_code(sj):04X} glyph {g} "
                  f"(block {g >> 2 if g else '-'} plane {g & 3 if g else '-'})")
            if g:
                print("\n".join(ascii_rows(glyph_rows(font, g))))
    elif cmd == "compare":
        exe = open(PS1_EXEC, "rb").read()
        same = diff = nops1 = 0
        for sj, g in sorted(tab.items()):
            try:
                ch = sj.to_bytes(2, "big").decode("sjis")
                p = ps1_glyph(ch, exe)
            except Exception:
                p = None
            if p is None:
                nops1 += 1
                continue
            if p == glyph_rows(font, g):
                same += 1
            else:
                diff += 1
                print(f"differs: {ch} sjis {sj:04X} glyph {g}")
        print(f"identical {same}, different {diff}, no PS1 kanji slot (ku < 16, the PS1 keeps those elsewhere) {nops1}")
    elif cmd == "table":
        for sj, g in sorted(tab.items()):
            try:
                ch = sj.to_bytes(2, "big").decode("sjis")
            except Exception:
                ch = "?"
            print(f"{sj:04X} {sjis_to_code(sj):04X} {g:5d} {ch}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
