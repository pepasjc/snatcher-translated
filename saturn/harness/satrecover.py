# -*- coding: utf-8 -*-
"""Recover the pair table of the build a bookmark was made on.

    python saturn/harness/satrecover.py B010_start [out.json]

work/saturn/pair_table_sat.json is rewritten by every satapply run, so a
play-test on an older image (patched/saturn/play/) cannot trust it: a pair
re-coded since then reads back as a kanji, a dropped one as garbage. The
image's own table is recoverable from a savestate made on it: the SJIS ->
glyph table sits in work RAM (0x060E6CF0), the font in VDP1 VRAM as the
loader put it (0x4020.. with satglyphs' extension, 0x8000.. pristine), and
a pair glyph is satpair.pair_cell(pair) - so every ASCII pair is rendered
once and each table entry whose cell matches one names its pair. Output:
the same {pair: [slot, code]} shape, default
patched/saturn/play/pair_table_sat.json (what satplay reads first).
"""
import gzip, json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'ps1/tools', 'saturn/tools', 'saturn/harness')]

import satfont, satmem, satpair

STATES = os.path.join(WORK, "saturn", "states")
EXT_BASE = 0x4020


def recover(state_blob):
    ram = satmem.state_ram(state_blob, "WorkRAMH")
    o = satfont.TABLE_ADDR - 0x06000000
    table = struct.unpack_from(f">{satfont.TABLE_N}H", ram, o)
    vram = satfont.vdp1_vram(state_blob)
    # the font block array as loaded: extension present when 0x4020.. is non-zero
    base = EXT_BASE if any(vram[EXT_BASE:EXT_BASE + 0x1000]) else satfont.VDP1_FONT
    font = vram[base:satfont.VDP1_FONT + satfont.VDP1_BUDGET]
    cells = {}
    for a in range(32, 127):
        for b in range(32, 127):
            p = chr(a) + chr(b)
            cells.setdefault(tuple(satpair.pair_cell(p)), p)
    out, unknown = {}, 0
    for i, slot in enumerate(table):
        if not slot:
            continue
        sjis = satfont.TABLE_LO + i
        if (slot >> 2) * satfont.BLOCK + satfont.BLOCK > len(font):
            continue
        rows = tuple(satfont.cell_rows(font, slot))
        p = cells.get(rows)
        if p is not None:
            out[p] = [slot, satfont.code_to_sjis(sjis)]
    return out, base


def main():
    name = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "patched", "saturn", "play", "pair_table_sat.json")
    blob = gzip.decompress(open(os.path.join(STATES, name + ".state.gz"), "rb").read())
    table, base = recover(blob)
    json.dump(table, open(out, "w"), indent=0)
    cur = json.load(open(os.path.join(WORK, "saturn", "pair_table_sat.json")))
    same = sum(1 for p in table if p in cur and cur[p][1] == table[p][1])
    print(f"{len(table)} pairs recovered (font base {base:#x}); current work table {len(cur)}: "
          f"{same} same code, {len(set(table) - set(cur))} only in the image, {len(set(cur) - set(table))} only in the current table; -> {out}")


if __name__ == "__main__":
    main()
