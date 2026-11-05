"""Apply the Saturn translation: English into the banks, pair glyphs into the font.

The PS1's apply_translation.py, for DATA.BIN: every saturn/translation/
SAT_NNN_Bxxx.json string with a non-empty `en` (locked ones refused, `long`
ignored for now) is pair-encoded with ps1/tools/pairfont over the Saturn
pair table satglyphs.plan() derives from work/pair_table.json and written
at its `off` inside its `budget` (null-terminated, zero-padded); a string
over budget keeps its Japanese in place and is listed in over_budget.txt -
satlong.py then appends its `en` to the bank as a long and remaps the
string to it, so the player reads the English (the over-budget policy,
2026-09-12: satlong's docstring). Chunk 0 (the font) is rebuilt
with the pair glyphs, re-packed (lz3.encode, or a literal chunk), put back
in its 18-sector slot when it fits and otherwise appended past DATA.BIN's
end with the exec's chunk-table entry repointed; MAIN_L.BIN gets the new
SJIS table and, under the extended layout, the loader/renderer constants
(satglyphs.py has the whole story).

Outputs (patched/saturn/): DATA.BIN, MAIN_L.BIN; work/saturn/pair_table_sat.json
(the Saturn pair table: pair -> [slot, code]); work/saturn/build/
apply_report.txt, over_budget.txt, font.bin (the decoded built font),
chunk0.bin (the packed chunk). Every applied string is decoded back from
the written bank and compared with the encoder's output before anything is
written (verify_build's rule).

    python saturn/tools/satapply.py [--no-ext] [--dry] [SAT_022_B010 ...]
"""
import os, sys, json, glob, struct, collections
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import satdata, satfont, satglyphs, lz3
from pairfont import PairFont
from textcodec import decode_stream

TR = os.path.join(ROOT, "saturn", "translation")
OUT = os.path.join(ROOT, "patched", "saturn")
BUILD = os.path.join(WORK, "saturn", "build")
SECTOR = 2048
CHUNK0_SLOT = 18                  # sectors chunk 0 occupies in the pristine DATA.BIN


class SatPairFont(PairFont):
    """pairfont's encoder over the Saturn table: pairs without a slot fall back
    to fullwidth letters (no free list, so code_for raises and encode_pair_or_fallback
    takes the fullwidth branch)."""

    def __init__(self, table):
        self.table = {p: list(v) for p, v in table.items()}
        self.free = []
        self.next = 0


def decode_en(b, rev):
    """A written bank string back to text: pair codes through `rev` (code -> pair),
    everything else through textcodec (fullwidth fallbacks show as fullwidth)."""
    out = []
    i = 0
    while i + 1 < len(b):
        code = (b[i] << 8) | b[i + 1]
        if code in rev:
            out.append(rev[code])
        else:
            out.append(decode_stream(b[i:i + 2]))
        i += 2
    return "".join(out)


def main(argv):
    ext = "--no-ext" not in argv
    dry = "--dry" in argv
    wanted = [a for a in argv if not a.startswith("--")]
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)
    lines = []

    def log(m=""):
        print(m, flush=True)
        lines.append(m)

    data = bytearray(open(satdata.DATA, "rb").read())
    ents = satdata.read_table()
    exe = open(satdata.MAIN, "rb").read()
    paths = sorted(glob.glob(os.path.join(TR, "SAT_*.json")))
    if wanted:
        paths = [p for p in paths if os.path.basename(p)[:-5] in wanted]
    items = satglyphs.load_items(paths, bytes(data), ents)
    plan = satglyphs.plan(items, exe, ext=ext, log=log)
    st = plan["stats"]
    pf = SatPairFont(plan["table"])
    rev = {code: pair for pair, (slot, code) in plan["table"].items()}

    # --- the banks ---------------------------------------------------------
    per = collections.OrderedDict()
    over = []
    for it in items:
        b = per.setdefault(it.bank, collections.Counter())
        b["strings"] += 1
        if it.long:
            b["long_skipped"] += 1
        if it.lock and it.en:
            b["locked_refused"] += 1
        if not it.want:
            if not it.lock:
                b["no_en"] += 1
            continue
        eb = pf.encode(it.en) + b"\x00"
        if len(eb) > it.budget:
            b["over_budget"] += 1
            over.append(it)
            assert not it.applied, (it.bank, it.off)
            continue
        assert it.applied, (it.bank, it.off, len(eb), it.budget)
        base = ents[it.bank][0]
        data[base + it.off:base + it.off + it.budget] = eb + b"\x00" * (it.budget - len(eb))
        back = bytes(data[base + it.off:base + it.off + it.budget])
        assert back[:len(eb)] == eb and not any(back[len(eb):]), "write-back mismatch"
        assert back.index(b"\x00") == len(eb) - 1, "an early null inside the string"
        b["applied"] += 1
        b["fallback_pairs"] += sum(1 for p in it.pairs if p not in plan["table"])
    log()
    log(f"{'bank':10s} {'strings':>7s} {'applied':>7s} {'over':>5s} {'no_en':>6s} {'locked':>6s} {'long':>5s} {'fb':>4s}")
    tot = collections.Counter()
    for bank, c in per.items():
        tot.update(c)
        log(f"{bank:3d} {satdata.BANK_NAMES.get(bank, ''):6s} {c['strings']:7d} {c['applied']:7d} {c['over_budget']:5d} "
            f"{c['no_en']:6d} {c['locked_refused']:6d} {c['long_skipped']:5d} {c['fallback_pairs']:4d}")
    log(f"{'total':10s} {tot['strings']:7d} {tot['applied']:7d} {tot['over_budget']:5d} {tot['no_en']:6d} "
        f"{tot['locked_refused']:6d} {tot['long_skipped']:5d} {tot['fallback_pairs']:4d}")
    log(f"(long = strings with a `long` label, over = kept Japanese here: both go to the bank tail by satlong.py; "
        f"fb = pair occurrences written as fullwidth fallback)")

    # --- verify: decode every applied string back ------------------------------
    bad = 0
    for it in items:
        if not it.applied:
            continue
        base = ents[it.bank][0] + it.off
        raw = bytes(data[base:base + it.budget])
        s = raw[:raw.index(b"\x00")]
        if pf.encode(it.en) != s:
            bad += 1
            log(f"VERIFY FAIL bank {it.bank} off {it.off}: {it.en!r} -> {decode_en(s, rev)!r}")
    log(f"verify: {st['applied'] - bad} of {st['applied']} applied strings re-encode and decode back; {bad} bad")
    if bad:
        sys.exit("verification failed; nothing written")

    # --- the font ----------------------------------------------------------
    font0 = satfont.load_font()
    font = satglyphs.build_font(font0, plan)
    raw, how = satglyphs.pack_chunk(font)
    nsec = (len(raw) + SECTOR - 1) // SECTOR
    if nsec <= CHUNK0_SLOT:
        c0 = (0, len(raw))
        data[0:len(raw)] = raw
        data[len(raw):CHUNK0_SLOT * SECTOR] = bytes(CHUNK0_SLOT * SECTOR - len(raw))
        where = f"in place (sectors 0..{nsec - 1} of the 18)"
    else:
        sec = len(data) // SECTOR
        assert len(data) % SECTOR == 0
        data += raw + bytes(nsec * SECTOR - len(raw))
        c0 = (sec, len(raw))
        where = f"relocated to DATA.BIN sector {sec} ({nsec} sectors appended, {len(raw)} bytes)"
    if len(raw) % 2:
        raw += b"\0"                              # the table's size is in halfwords
        c0 = (c0[0], len(raw))
    log(f"font: {len(font)} bytes = {len(font) // satfont.BLOCK} blocks = {len(font) // satfont.BLOCK * 4} slots "
        f"({'0x4020' if ext else '0x8000'}..0x15000), packed {len(raw)} bytes by {how}; {where}")
    log(f"pairs: {st['slotted']} placed ({st['new_slots']} new slots, {st['spare']} spare, {st['freed']} freed kanji), "
        f"{len(st['unslotted'])} pairs without a slot (fallback), {st['recoded']} pairs re-coded away from a drawn kanji; "
        f"{st['kanji_drawn']} kanji still drawn")
    log(f"pairs without a slot: {' '.join(repr(p) for p in st['unslotted'])}")
    new_exe = satglyphs.patch_exec(exe, plan, chunk0=c0)
    # read the table back and check every pair code -> its slot, every kept kanji shifted
    tab = satfont.table(new_exe)
    for pair, (slot, code) in plan["table"].items():
        assert tab.get(satfont.code_to_sjis(code)) == slot, pair
    for sjis, g in plan["orig"].items():
        if sjis not in set(plan["freed"]):
            assert tab.get(sjis) == g + plan["shift"], hex(sjis)
    # and every pair cell in the built font against satpair's renderer (the full 16x14)
    for pair, (slot, code) in plan["table"].items():
        assert satfont.cell_rows(font, slot) == satglyphs.pair_cell(pair), pair
    log("exec: SJIS table rewritten and read back; every pair glyph read back from the font")

    if dry:
        log("dry run: nothing written")
    else:
        open(os.path.join(OUT, "DATA.BIN"), "wb").write(bytes(data))
        open(os.path.join(OUT, "MAIN_L.BIN"), "wb").write(new_exe)
        json.dump(plan["table"], open(satglyphs.SAT_TABLE, "w"), indent=0)
        open(os.path.join(BUILD, "font.bin"), "wb").write(font)
        open(os.path.join(BUILD, "chunk0.bin"), "wb").write(raw)
        with open(os.path.join(BUILD, "over_budget.txt"), "w", encoding="utf-8") as f:
            for it in over:
                f.write(f"{it.bank} {satdata.BANK_NAMES.get(it.bank, '')} off={it.off} budget={it.budget} "
                        f"need={it.enc_len(set(plan['table']))}: {it.en}\n")
        with open(os.path.join(BUILD, "freed_kanji.txt"), "w", encoding="utf-8") as f:
            f.write(" ".join(s.to_bytes(2, "big").decode("cp932", "replace") for s in plan["freed"]))
        log(f"wrote {OUT}/DATA.BIN ({len(data)} bytes), MAIN_L.BIN, {satglyphs.SAT_TABLE}, {BUILD}/")
    with open(os.path.join(BUILD, "apply_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1:])
