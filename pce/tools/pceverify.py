"""Read the BUILT PCE image back and prove every English line is in it.

The build is not trusted until this passes: a byte the encoder got wrong
is a line the player never sees, and a menu record one byte off makes
every later label draw from the middle of its neighbour. For every module
the stage-2 file table names, this decodes each string with the Python
decoder (dictionary references expanded from the module's own table,
pair and single codes rendered back to letters) and compares it with the
English that was meant; checks every menu label and speaker name the same
way; and measures every row against the box.

  python pce/tools/pceverify.py            # exit 1 on any problem
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import patch_pce as P
import pcescript as S

LIST_COLS = 8                 # the list menu's highlight box, in cells
import pcetext as T
import pcepair
import pceengine
import pcedict


def render(codes, english=True):
    """Codes -> the text a player reads (pairs as letters, tags as tags);
    a Japanese line's kanji share the pair rows, so it renders as SJIS."""
    out = []
    for hi, lo in codes:
        if english and pcepair.is_pair(hi, lo) and not (hi == 0x98 and lo >= 0x9F):
            p = pcepair.pair_of(hi, lo)          # the module's table (pcepair.use)
            out.append("".join(p) if p else f"<slot {pcepair.slot_of_code(hi, lo)}?>")
        else:
            out.append(T.sjis_char(hi, lo))
    return "".join(out)


def expand(built, pos, dict_ptr):
    """Decode a built string, following dictionary references."""
    codes, nxt = T.decode_codes(built, pos)
    out = []
    for hi, lo in codes:
        if hi == 0x84 and lo == 0x40:
            continue                                  # the English marker
        if hi == 0x84 and lo >= 0x41 and dict_ptr:
            slot = lo - 0x41                     # the table is indexed by lo, 0x7F's slot empty
            off = int.from_bytes(built[dict_ptr + 2 * slot:dict_ptr + 2 * slot + 2], "little")
            entry, _ = T.decode_codes(built, off)
            out += entry
            continue
        out.append((hi, lo))
    return out, nxt


def expected(en):
    """The text the English should read as once drawn: cells rendered (a pair the
    module's table lacks reads as a KeyError's message - a problem)."""
    text = S.layout(en)
    try:
        return render(list(T.tokens(text)))
    except KeyError as e:
        return f"<{e}>"


def raw_text(en):
    """A label or name as drawn (no layout)."""
    try:
        return render(list(T.tokens(en)))
    except KeyError as e:
        return f"<{e}>"


def main():
    english = S.load_english()
    menu = json.load(open(S.WORDS, encoding="utf-8")) if os.path.exists(S.WORDS) else {}
    en_names = json.load(open(S.NAMES, encoding="utf-8")) if os.path.exists(S.NAMES) else {}
    src = P.Image(P.SRC, 12000)
    out = P.Image(P.OUT, P.T3 + P.RESERVE)
    names = S.speaker_names(src)
    placed = json.load(open(os.path.join(WORK, "pce", "build_map.json")))
    base = (S.T2 + P.STAGE2) * P.DATA
    table = bytes(out.data[base:base + 15 * P.DATA])
    bad, modules, lines, labels = [], 0, 0, 0

    def all_english(built):
        return built[pceengine.ALL_EN] == 1
    for rec, n in S.records():
        if n > S.MAX_SECTORS:
            continue
        mod = S.read_file(src, rec, n)
        strings, flag = S.strings_of(mod)
        if not strings and not flag and str(rec) in placed:
            # a text-less module (670, the ending) carries the font and the
            # English flag for the credit roll's pair codes
            new_rec, new_n = placed[str(rec)]
            built = S.read_file(out, new_rec, new_n)
            if built[pceengine.ALL_EN] != 1:
                bad.append(f"rec {rec}: the English flag is down")
            font = pcepair.modfont()
            if built[pcepair.FONT_OFF:pcepair.FONT_OFF + len(font)] != font:
                bad.append(f"rec {rec}: no font at {pcepair.FONT_OFF:#x}")
            if pcepair.PairTable.from_module(built) is None:
                bad.append(f"rec {rec}: no pair table")
            if built[:len(mod)] != mod:
                bad.append(f"rec {rec}: the module's own bytes changed")
            modules += 1
            continue
        if len(strings) < 8 or flag:
            continue
        if str(rec) not in placed:
            bad.append(f"rec {rec}: not in the build map")
            continue
        new_rec, new_n = placed[str(rec)]
        # the stage-2 record must point there too
        want_rec = bytes([new_rec >> 16, new_rec & 0xFF, (new_rec >> 8) & 0xFF])
        if not any(table[i:i + 3] == want_rec and table[i + 3] == 4 and table[i + 6] == new_n
                   for i in range(len(table) - 8)):
            bad.append(f"rec {rec}: the file table does not name rec {new_rec} x{new_n}")
        built = S.read_file(out, new_rec, new_n)
        modules += 1
        font = pcepair.modfont()
        if built[pcepair.FONT_OFF:pcepair.FONT_OFF + len(font)] != font:
            bad.append(f"rec {rec}: the font at {pcepair.FONT_OFF:#x} is not the module font")
        tbl = pcepair.PairTable.from_module(built)
        if tbl is None:
            bad.append(f"rec {rec}: no pair table")
            continue
        pcepair.use(tbl)                    # every decode and every expected text below
        dict_ptr = int.from_bytes(built[pceengine.DICT_PTR:pceengine.DICT_PTR + 2], "little") or None
        # every string, in order, from the built text block: the encoder writes
        # them back to back, so one bad terminator would desync all that follow
        starts = {o for o, _ in strings}
        # the references live in the bytecode, which keeps its length; the
        # word list behind it does not, and label bytes can look like refs
        code_end = S.word_list(mod, strings[0][0])[0] or strings[0][0]
        pairs = [(int.from_bytes(a.group(1), "little"), int.from_bytes(built[a.start(1):a.start(1) + 2], "little"))
                 for a in S.text_refs(mod[:code_end], strings)]      # same position in the built code
        remap = {o: n for o, n in pairs if o in starts}
        pos = pos0 = remap.get(strings[0][0])
        if pos is None:
            bad.append(f"rec {rec}: the first string's reference was not remapped")
            continue
        # the module's longs blob (pcelongs), if any, at its place as the fetch sees it
        import pcelongs
        d = pcelongs.parse(built[pcelongs.DESC:pcelongs.DESC + 9])
        space = bytes(built)
        if d:
            at = pcelongs.WINDOW + (d["bank"] - 0x6B) * 0x2000 + d["off"]
            blob = bytes(S.read_file(out, d["rec"], (d["nbytes"] + 2047) // 2048))[:d["nbytes"]]
            space += bytes(at - len(space)) + blob
            longs_at = at
        for o_ref, jp in strings:
            want = english.get(S.key(jp))
            if remap.get(o_ref, 0) >= pcelongs.WINDOW:
                # an evicted string: at its reference in the blob, back to back like the block -
                # or right after a hole (pcelongs.HOLES: 750's own bytes the module's scenes read,
                # carried unchanged; checked against the source record)
                for a, b, keep in pcelongs.holes(rec) if d else ():
                    if longs_at <= at + a and remap[o_ref] == at + b:
                        if space[at + a:at + b] != keep:
                            bad.append(f"rec {rec}: the longs hole {a:#x}..{b:#x} is not rec 750's bytes")
                        longs_at = at + b
                if remap[o_ref] != longs_at:
                    bad.append(f"rec {rec} {o_ref:#06x}: referenced at {remap[o_ref]:#06x} in the longs, stored at {longs_at:#06x}")
                codes, longs_at = expand(space, remap[o_ref], dict_ptr)
                got = render(codes, want is not None)
                lines += 1
                exp = expected(want) if want is not None else jp
                if got != exp:
                    bad.append(f"rec {rec} {o_ref:#06x}: built longs text differs | want {exp[:70]!r} | got {got[:70]!r}")
                continue
            codes, nxt = expand(space, pos, dict_ptr)
            got = render(codes, want is not None)
            lines += 1
            if o_ref in remap and remap[o_ref] != pos:
                bad.append(f"rec {rec} {o_ref:#06x}: referenced at {remap[o_ref]:#06x}, stored at {pos:#06x}")
            if want is None:
                if got != jp:
                    bad.append(f"rec {rec} {o_ref:#06x}: Japanese line changed: {got[:40]!r}")
            else:
                exp = expected(want)
                if got != exp:
                    bad.append(f"rec {rec} {o_ref:#06x}: built text differs"
                               f" | want {exp[:70]!r} | got {got[:70]!r}")
                rows = S.cells(S.layout(want))
                if max(rows) > S.COLS:
                    bad.append(f"rec {rec} {o_ref:#06x}: a row of {max(rows)} cells: {want[:60]!r}")
            pos = nxt
        # menu labels: same count, English where meant, data untouched, and
        # every `f1` reference into the list still lands on its record
        wstart, wend, wrecs = S.word_list(mod, strings[0][0])
        if wrecs:
            # the bytecode before the list and the bytes between the list and
            # the text keep their lengths, so the built list is bounded by them
            bwstart, bwend = wstart, pos0 - (strings[0][0] - wend)
            lead = 1 if mod[wstart] == 0xFF else 0            # (a first record without its 0xFF)
            raw = built[bwstart + lead:bwend - 1].split(bytes([0xFF]))
            if len(raw) != len(wrecs):
                bad.append(f"rec {rec}: word list has {len(raw)} records, expected {len(wrecs)}")
            else:
                for jp, b in zip(wrecs, raw):
                    en = menu.get(f"{rec}:{jp}", menu.get(jp))
                    if en:
                        labels += 1
                        text = render([(b[k], b[k + 1]) for k in range(0, len(b), 2)]).rstrip()
                        if text != raw_text(en).rstrip():
                            bad.append(f"rec {rec}: label {jp!r} reads {text!r}, wanted {en!r}")
                        # the list box is LIST_COLS cells wide and cuts the rest
                        # ("Continue the gam" after a save)
                        if len(b) // 2 > LIST_COLS and all(ord(c) < 0x80 for c in en):   # typed keys are not drawn as items
                            bad.append(f"rec {rec}: label {en!r} is {len(b) // 2} cells, the box holds {LIST_COLS}")
                    elif b != jp.encode("cp932"):
                        bad.append(f"rec {rec}: data label {jp!r} changed")
                    elif all_english(built) and "★" not in jp and "☆" not in jp and any(0x89 <= b[k] <= 0x98 for k in range(0, len(b) - 1, 2)):
                        # a kanji left in an all-English module draws as a pair glyph
                        bad.append(f"rec {rec}: Japanese label {jp!r} would draw as pair glyphs")
                old_offs = S.record_offsets(mod, wstart, wrecs)
                # the built list's record starts, from its own bytes
                starts, p = [], bwstart + lead
                for b in raw:
                    starts.append(p)
                    p += len(b) + 1
                index = {o: k for k, o in enumerate(old_offs)}
                for m in S.LABEL_REF.finditer(mod[:wstart]):
                    o = int.from_bytes(m.group(1), "little")
                    if o in index:
                        got = int.from_bytes(built[m.start(1):m.start(1) + 2], "little")
                        if got != starts[index[o]]:
                            bad.append(f"rec {rec}: label ref at {m.start():#06x} -> {got:#06x}, record {index[o]} is at {starts[index[o]]:#06x}")
        # speaker names
        ptr = int.from_bytes(built[pceengine.NAMES_PTR:pceengine.NAMES_PTR + 2], "little")
        for k, (attr, jp) in enumerate(names):
            en = en_names.get(str(k))
            if not en:
                continue
            off = int.from_bytes(built[ptr + 2 * (k + 1):ptr + 2 * (k + 1) + 2], "little")
            ent = built[off + 1:built.index(0xFF, off + 1)]
            text = render([(ent[j], ent[j + 1]) for j in range(0, len(ent), 2)]).rstrip()
            if text != raw_text(en).rstrip():
                bad.append(f"rec {rec}: name {k} reads {text!r}, wanted {en!r}")
                break
    for b in bad[:40]:
        print("  " + b)
    print(f"{modules} modules, {lines} strings, {labels} labels checked: {len(bad)} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
