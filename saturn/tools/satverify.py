# -*- coding: utf-8 -*-
"""Verify a built Saturn image's letter-pair glyphs - the Saturn twin of the PS1's
verify_build: what the game will draw for every pair the text uses, read back from the
IMAGE (its MAIN_L.BIN and its DATA.BIN chunk 0), against what the pair should look like.

    python saturn/tools/satverify.py [IMAGE.cue] [--table PAIR_TABLE.json]

For each pair of the build's pair table (work/saturn/pair_table_sat.json, or the
`<image>.pair_table.json` beside a side image): its code -> SJIS -> the exec's SJIS->glyph
table entry -> the glyph cell in chunk 0, compared bit for bit with satpair.pair_cell.
Also: the exec's table sends each code to the slot the pair table names, two pairs never
share a glyph slot, no pair code lands on slot 0 (blank), and every non-ASCII character of
the English (bank strings, longs, cues) has a glyph. Exit 1 on any mismatch - a garbled glyph would ship.
"""
import collections, json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'ps1/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IMAGE = os.path.join(ROOT, "patched", "saturn", "Snatcher (Japan).cue")


def verify(image=IMAGE, table_path=None, log=print):
    import satfont, satpair, satmem, fontwatch
    side = os.path.splitext(image)[0] + ".pair_table.json"
    table_path = table_path or (side if os.path.exists(side) else os.path.join(WORK, "saturn", "pair_table_sat.json"))
    pairs = json.load(open(table_path, encoding="utf-8"))
    exe = satmem.image_exec(image)
    base, font = fontwatch.expected_font(image)
    tab = satfont.table(exe)
    bad, slots = [], collections.defaultdict(list)
    for pair, (slot, code) in pairs.items():
        sjis = satfont.code_to_sjis(code)
        g = tab.get(sjis, 0)
        if g and g != slot:
            bad.append(f"{pair!r}: code {code:#x} -> glyph {g}, the pair table says slot {slot}")
        if not g:
            bad.append(f"{pair!r}: code {code:#x} (SJIS {sjis:#x}) has no glyph (slot 0)")
            continue
        slots[g].append(pair)
        if (g >> 2) * satfont.BLOCK + satfont.BLOCK > len(font):
            bad.append(f"{pair!r}: slot {g} past the font ({len(font) // satfont.BLOCK} blocks)")
            continue
        got = satfont.cell_rows(font, g)
        want = satpair.pair_cell(pair)
        if got != want:
            bad.append(f"{pair!r}: slot {g} draws something else")
    for g, ps in slots.items():
        if len(ps) > 1:
            bad.append(f"slot {g} shared by {ps}")
    # every character the English uses outside ASCII must have a glyph in this exec's table: a
    # curly apostrophe in a `long` (B010's 'you’d', 2026-11-06) is SJIS 0x8166, glyph 0 - a blank cell
    import glob
    SKIP = set("￥＠赤白黄緑青水紫桃Ｃω▽　")
    texts = []
    for path in sorted(glob.glob(os.path.join(ROOT, "saturn", "translation", "SAT_*.json"))):
        for x in json.load(open(path, encoding="utf-8"))["strings"]:
            if not x.get("lock"):
                texts += [(os.path.basename(path)[8:12], x["off"], x.get(k)) for k in ("en", "long") if x.get(k)]
    for path in sorted(glob.glob(os.path.join(ROOT, "saturn", "translation", "subs_*.json"))):
        for c in json.load(open(path, encoding="utf-8"))["cues"]:
            texts.append((os.path.basename(path)[5:-5], c["id"], c.get("en", "")))
    for where, key, text in texts:
        for ch in sorted(set(text)):
            if ord(ch) < 0x80 or ch in SKIP:
                continue
            try:
                sj = int.from_bytes(ch.encode("cp932"), "big")
            except UnicodeEncodeError:
                bad.append(f"{where} {key}: {ch!r} is not Shift-JIS"); continue
            if not tab.get(sj):
                bad.append(f"{where} {key}: {ch!r} (SJIS {sj:#x}) has no glyph - it draws a blank cell")
    log(f"satverify: {len(pairs)} pairs, {len(slots)} slots, font {len(font)} B at VDP1 {base:#x}, "
        f"{len(texts)} texts: {len(bad)} problem(s)")
    for b in bad[:50]:
        log("  " + b)
    return bad


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    table = None
    if "--table" in sys.argv:
        table = sys.argv[sys.argv.index("--table") + 1]
        args = [a for a in args if a != table]
    bad = verify(args[0] if args else IMAGE, table)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
