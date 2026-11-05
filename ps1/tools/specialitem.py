"""A fifth OPTION MENU item, SPECIAL OPTIONS, that opens the hidden
SPECIAL MENU (GitHub #30) - no Konami code, no START.

Where the option menu lives (all found headless with cheat_probe.py):

- The labels are pre-rendered words in a 128x72 8bpp sheet, section 1
  item 0 of `DES/CPT/CPT_B090.BIN` (VRAM x=896 y=256, CLUT 0x7B00), eight
  pixels per letter, sixteen letters per row (MESSAGESPEEDEXIT,
  CONTROLLERMOUSEI, SOUNDMODENORMALJ, SLOWFASTSTEREOKL, MONOCANCELCHOOSE). The menu is a draw list in the same section's
  tail - the disclaimer's format: `u32 count<<24` (byte 3), then records
  `{u16 y, u16 x, u8 h, u8 w, u16 src}` with src = (v/8)<<4 | u/8 and
  (x, y) relative to the 208x96 panel at screen (24, 64). The list-pointer
  table after the lists (20 lists) indexes them; list 0 is OPTION MENU.
  The panel is one fixed 208x96 sprite, so a fifth row has to fit inside
  it: rows go from a 16-px pitch (y 27/43/59/75) to 12 (27/39/51/63/75),
  the pitch the wall-paper lists already use, and EXIT stays where it was.
- The sheet has no free cell, so the item grows by one row (v=72) holding
  SPECIAL and OPTIONS composed from the letters already on it; everything
  after the pixels (item table, lists, both pointer tables, descriptor)
  shifts, and every section-relative offset is bumped.
- The overlay `SXX_B000` drives the menu through per-menu tables and a few
  immediates: `0x800CE0B4[id]` is the last cursor index (menu id 2 = the
  option menu), `0x800CE11C` its highlight-bar (x, y) pairs - five already,
  at a 16-px pitch - the open step (0x800C102C) parks the cursor on EXIT
  and sizes the bar 200x16, cancel (0x800C1684) parks it on EXIT, and the
  confirm switch (0x800C1384..) sends cursor 3 to EXIT. Now cursor 4 is
  EXIT, and cursor 3 jumps into the START handler's body (0x800C17BC), the
  code that arms the cheat listener; with specialmenu.py's table patch the
  listener unlocks on the next frame and the SPECIAL MENU loads.

    python ps1/tools/specialitem.py preview   # work/gfx/special_item.png
    python ps1/tools/specialitem.py apply     # patched/CPT_B090.BIN, patched/SXX_B000.BIN, exec size
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

from lzss import decompress, compress
from gfxpages import resize

SRC = os.path.join(ROOT, "discs/extracted_ps1")
DST = os.path.join(ROOT, "patched")
CPT = "CPT_B090"
OVL = "SXX_B000"
OVL_BASE = 0x800B4000

# --- the container -----------------------------------------------------
ITEM_HDR = 0x5244             # packed size word of section 1 item 0
HW, ROWS = 64, 72             # 64 halfwords = 128 px at 8bpp
NEW_ROWS = 80
LIST0 = 0x764C                # `00 00 00 07` + 7 records; the item table word precedes it
ITEM_TABLE = 0x7648
LIST_PTRS = 0x78D4            # 20 u32, section-relative
ANIM_PTRS = 0x79C4            # 20 u32, section-relative
DESC = 0x7A14                 # f[2] tail size, f[3] anim ptrs, f[4] list ptrs, f[5] item table
SEC1 = 0x503C                 # section 1 start; u32 there = descriptor offset

# letters on the sheet, as (row, cell) of 8x8 cells: row 2 reads
# MESSAGESPEEDEXIT, row 3 CONTROLLERMOUSEI
GLYPH = {"S": (2, 2), "P": (2, 8), "E": (2, 1), "C": (3, 0), "I": (2, 14),
         "A": (2, 4), "L": (3, 6), "O": (3, 1), "T": (3, 3), "N": (3, 2)}
NEW_ROW = 9                   # v = 72
WORDS = [("SPECIAL", 0), ("OPTIONS", 7)]      # cell columns on the new row

# the rebuilt option menu, panel-relative: (y, x, h, w, src)
PITCH = 12
RECORDS = [
    (4, 40, 16, 128, 0x00),                      # OPTION MENU
    (27, 52, 8, 56, 0x20), (27, 116, 8, 40, 0x27),   # MESSAGE SPEED
    (27 + PITCH, 64, 8, 80, 0x30),               # CONTROLLER
    (27 + 2 * PITCH, 64, 8, 40, 0x40), (27 + 2 * PITCH, 112, 8, 32, 0x45),   # SOUND MODE
    (27 + 3 * PITCH, 44, 8, 56, (NEW_ROW << 4) | 0), (27 + 3 * PITCH, 108, 8, 56, (NEW_ROW << 4) | 7),  # SPECIAL OPTIONS
    (27 + 4 * PITCH, 88, 8, 32, 0x2C),           # EXIT
]
ORIGINAL = [(4, 40, 16, 128, 0), (27, 52, 8, 56, 0x20), (27, 116, 8, 40, 0x27), (75, 88, 8, 32, 0x2C),
            (43, 64, 8, 80, 0x30), (59, 64, 8, 40, 0x40), (59, 112, 8, 32, 0x45)]
# list 1 = the same menu with a mouse plugged in: MOUSE in CONTROLLER's row (#77)
LIST1 = LIST0 + 4 + 8 * len(ORIGINAL)
ORIGINAL1 = [(4, 40, 16, 128, 0), (27, 52, 8, 56, 0x20), (27, 116, 8, 40, 0x27), (75, 88, 8, 32, 0x2C),
             (59, 64, 8, 40, 0x40), (59, 112, 8, 32, 0x45), (43, 84, 8, 40, 0x3A)]
RECORDS1 = [r if r[4] != 0x30 else (27 + PITCH, 84, 8, 40, 0x3A) for r in RECORDS]

# --- the overlay: (file offset, expected bytes, new bytes) ----------------
def ovl(addr):
    return addr - OVL_BASE

J_START_BODY = 0x08000000 | ((0x800C17BC >> 2) & 0x3FFFFFF)


def W(word):
    return struct.pack("<I", word)


OVL_PATCHES = [
    (ovl(0x800CE0B4) + 2, b"\x03", b"\x04"),                       # menu 2: last cursor index
    (ovl(0x800CE11C), bytes.fromhex("1c581c681c781c881c98"),
     bytes.fromhex("1c581c641c701c7c1c88")),                       # bar (x, y) per row, 12-px pitch
    (ovl(0x800C10C0), W(0x34020003), W(0x34020004)),   # open: cursor on EXIT (ori $v0, $zero, 3)
    (ovl(0x800C1158), W(0x34060010), W(0x3406000C)),   # open: bar height (ori $a2, $zero, 16)
    (ovl(0x800C1684), W(0x34020003), W(0x34020004)),   # cancel: cursor on EXIT
    (ovl(0x800C13C0), W(0x34030003), W(0x34030004)),   # confirm: 4 -> EXIT
    (ovl(0x800C13CC), W(0x08030571), W(J_START_BODY)), # confirm: 3 -> START body (j 0x800C15C4 -> j 0x800C17BC)
    (ovl(0x800CE127), b"\x00", b"\x98"),                           # bar table: the fifth row's bottom = EXIT's old one (#77)
]

# The mouse hit test (#77): menu 2's case of the switch at 0x800CC7E4 picks
# row i when bar[i].y < y <= bar[i+1].y, unrolled for four rows (returns
# 0..3, or 0x3E8 for none). With five rows EXIT was out of reach and the
# old EXIT spot hit SPECIAL OPTIONS. Rewritten in place as a loop over five
# rows; the padding byte after the bar table carries the last row's bottom.
MOUSE_AT, MOUSE_END = 0x800CCBAC, 0x800CCD08   # MOUSE_END = the miss path (0x3E8)
MOUSE_RET = 0x800CD5E0


def mouse_rows():
    from mipsasm import Asm
    a = Asm(MOUSE_AT)
    a.lhu("$t0", 0x12, "$fp")                 # pointer y
    a.lui("$t1", 0x800D)
    a.addiu("$t1", "$t1", -0x1EE3)            # &bar[0].y (0x800CE11D)
    a.addu("$v0", "$zero", "$zero")
    a.label("loop")
    a.lbu("$t2", 0, "$t1")
    a.lbu("$t3", 2, "$t1")
    a.sltu("$t4", "$t2", "$t0")               # top < y
    a.beq("$t4", "$zero", "miss")
    a.nop()
    a.sltu("$t4", "$t3", "$t0")               # bottom < y: the next row
    a.beq("$t4", "$zero", "hit")
    a.nop()
    a.addiu("$v0", "$v0", 1)
    a.sltiu("$t4", "$v0", 5)
    a.bne("$t4", "$zero", "loop")
    a.addiu("$t1", "$t1", 2)
    a.label("miss")
    a.j(MOUSE_END)
    a.nop()
    a.label("hit")
    a.j(MOUSE_RET)
    a.nop()
    code = a.assemble()
    assert len(code) <= MOUSE_END - MOUSE_AT
    return code + b"\0" * (MOUSE_END - MOUSE_AT - len(code))


def pixels(dec, hdr, rows):
    import numpy as np
    return np.frombuffer(dec[hdr + 4:hdr + 4 + HW * 2 * rows], np.uint8).reshape(rows, HW * 2).copy()


def pack(px):
    return px.astype("uint8").tobytes()


def parse_list(dec, off):
    n = dec[off + 3]
    assert dec[off:off + 3] == b"\0\0\0", "list header"
    recs = [struct.unpack_from("<HHBBH", dec, off + 4 + 8 * i) for i in range(n)]
    return recs


def build():
    import numpy as np
    dec, _ = decompress(open(os.path.join(SRC, "DES/CPT", CPT + ".BIN"), "rb").read())
    dec = bytearray(dec)
    assert dec[ITEM_HDR:ITEM_HDR + 2] == b"\x80\x48", "item header"
    assert parse_list(dec, LIST0) == ORIGINAL, "option menu list"
    assert parse_list(dec, LIST1) == ORIGINAL1, "option menu list (mouse)"
    assert struct.unpack_from("<I", dec, ITEM_TABLE)[0] == ITEM_HDR - SEC1

    # the sheet, one row taller, the two new words composed from old letters
    px = pixels(dec, ITEM_HDR, ROWS)
    new = np.zeros((NEW_ROWS, HW * 2), np.uint8)
    new[:ROWS] = px
    for word, col in WORDS:
        for i, ch in enumerate(word):
            r, c = GLYPH[ch]
            new[NEW_ROW * 8:NEW_ROW * 8 + 8, (col + i) * 8:(col + i) * 8 + 8] = px[r * 8:r * 8 + 8, c * 8:c * 8 + 8]
    hdr = bytes([dec[ITEM_HDR], ((NEW_ROWS - 1) & 0x7F) + 1, 0, 0])
    d_pix = HW * 2 * (NEW_ROWS - ROWS)

    # the tail: item table, lists 0 and 1 rebuilt, the rest with its offsets bumped
    def packed_list(recs):
        return b"\0\0\0" + bytes([len(recs)]) + b"".join(struct.pack("<HHBBH", *r) for r in recs)
    list0, list1 = packed_list(RECORDS), packed_list(RECORDS1)
    old_list1_end = LIST1 + 4 + 8 * len(ORIGINAL1)
    d_list0 = len(list0) - (LIST1 - LIST0)
    d_list = len(list0) + len(list1) - (old_list1_end - LIST0)
    rest = bytearray(dec[old_list1_end:])

    def bump(file_off, delta):
        o = file_off - old_list1_end
        v = struct.unpack_from("<I", rest, o)[0]
        struct.pack_into("<I", rest, o, v + delta)

    for i in range(20):
        bump(LIST_PTRS + 4 * i, d_pix + (0 if i == 0 else d_list0 if i == 1 else d_list))
    for i in range(20):
        bump(ANIM_PTRS + 4 * i, d_pix + d_list)
    bump(DESC + 8, d_list)                 # tail size
    bump(DESC + 12, d_pix + d_list)        # anim pointer table
    bump(DESC + 16, d_pix + d_list)        # list pointer table
    bump(DESC + 20, d_pix)                 # item table

    out = bytearray(dec[:ITEM_HDR]) + hdr + pack(new) + dec[ITEM_TABLE:LIST0] + list0 + list1 + rest
    a, b = struct.unpack_from("<II", out, 0)
    struct.pack_into("<II", out, 0, a, b + d_pix + d_list)
    desc = struct.unpack_from("<I", out, SEC1)[0]
    struct.pack_into("<I", out, SEC1, desc + d_pix + d_list)
    return bytes(out), new


def preview():
    from PIL import Image
    _, px = build()
    img = Image.fromarray(((px != 0) * 255).astype("uint8")).resize((px.shape[1] * 4, px.shape[0] * 4), Image.NEAREST)
    os.makedirs(os.path.join(WORK, "gfx"), exist_ok=True)
    p = os.path.join(WORK, "gfx", "special_item.png")
    img.save(p)
    print(p)


def apply():
    os.makedirs(DST, exist_ok=True)
    dec, _ = build()
    packed = compress(dec)
    check, _ = decompress(packed)
    assert check == dec, "roundtrip"
    pristine = open(os.path.join(SRC, "SLPS_001.54"), "rb").read()
    exe_path = os.path.join(DST, "SLPS_001.54")
    exe = bytearray(open(exe_path, "rb").read())
    resize(exe, pristine, CPT, len(packed))
    open(exe_path, "wb").write(bytes(exe))
    open(os.path.join(DST, CPT + ".BIN"), "wb").write(packed)
    print(f"{CPT}: {len(packed)} bytes packed ({len(dec)} raw), file-table size updated")

    src = os.path.join(SRC, "PRG/SXM", OVL + ".BIN")
    dst = os.path.join(DST, OVL + ".BIN")
    ov = bytearray(open(dst if os.path.exists(dst) else src, "rb").read())
    for off, old, new in OVL_PATCHES:
        cur = bytes(ov[off:off + len(old)])
        if cur == new:
            continue
        assert cur == old, f"{OVL} {off + OVL_BASE:#x}: {cur.hex()} is neither the original nor patched"
        ov[off:off + len(new)] = new
    pristine_ov = open(src, "rb").read()
    lo, hi = ovl(MOUSE_AT), ovl(MOUSE_END)
    code = mouse_rows()
    assert bytes(ov[lo:hi]) in (pristine_ov[lo:hi], code), f"{OVL} mouse hit test is neither the original nor patched"
    ov[lo:hi] = code
    open(dst, "wb").write(bytes(ov))
    print(f"{OVL}: option menu has SPECIAL OPTIONS (cursor 3 -> START path, 4 -> EXIT, 12-px rows)")


if __name__ == "__main__":
    {"preview": preview, "apply": apply}[sys.argv[1] if len(sys.argv) > 1 else "preview"]()
