"""English speaker names in the Saturn exec (the PS1's translate_names.py).

The nameplate is row 0 of the text cells: the show-text-with-speaker op
(0x060B8390) takes the speaker index, reads the pointer table the init
routine 0x060C1CB8 copies out of its own literal pool (79 words at
0x060C1F18: '----' then the 78 names at 0x060C17F4..0x060C1CB8, 1,048
bytes), and lays the string out with 0x060B45C4(0, 0, sjis) - plain SJIS,
never through the negating converter 0x060C4D24 that the bank text goes
through. So the name table holds SJIS, and an English name is the PS1
pair-code stream turned into the SJIS the converter WOULD have produced:
satfont.code_to_sjis per 2-byte code (each byte negated - not
0x10000 - code), which is exactly the code the font table maps to the
pair glyph after satglyphs.py has run. The ＠colour wrapper of each
original name (＠青メタルギア＠白) is kept byte for byte around the English.

English names are longer than two or three kana, so the 78 wrapped names
need ~1,350 bytes against the original 1,048: the table is written into
the original region first, and the names that do not fit go to the exec
hole satexec.py describes; every pointer in the pool is rewritten, so the
split is invisible to the engine. Pair glyphs: the names' pairs are added
to satglyphs' ranking through its `extra_pairs()` hook (pairs_used()
below), so they get slots like the bank text's; a pair without one falls
back to two fullwidth letters (two cells) as in the banks.

Order: after satapply.py (which rebuilds MAIN_L.BIN from pristine and
writes the pair table), before satlong.py and satdisc.py.

    python saturn/tools/satnames.py apply [--dry]     names.json -> patched/saturn/MAIN_L.BIN
    python saturn/tools/satnames.py show              the table as the exec holds it now
"""
import json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import satdata, satfont, satexec

MAIN_BASE = 0x060B0000
NAMES_JSON = os.path.join(ROOT, "saturn", "translation", "names.json")
POOL = 0x060C1F1C            # 78 pool words, one per name (0x060C1F18 = '----')
NAME_LO, NAME_HI = 0x060C17F4, 0x060C1CB8    # the original strings (code follows at 0x060C1CB8)
N_NAMES = 78
AT = 0x8197                  # ＠
COLOURS = {"青": 0x90C2, "赤": 0x90D4, "紫": 0x8E87, "緑": 0x97CE, "水": 0x9085, "黄": 0x89A9, "白": 0x9492}
WHITE = COLOURS["白"]
PAIR_TABLE = os.path.join(WORK, "saturn", "pair_table_sat.json")
MAX_CELLS = 14               # the nameplate row is 20 cells, 14 in window mode 7


def pristine_names(exe=None):
    """[(pointer, raw SJIS bytes)] of the 78 original names from a pristine exec."""
    exe = exe if exe is not None else open(satdata.MAIN, "rb").read()
    out = []
    for i in range(N_NAMES):
        p = struct.unpack_from(">I", exe, POOL - MAIN_BASE + 4 * i)[0]
        assert NAME_LO <= p < NAME_HI, (i, hex(p))
        q = p - MAIN_BASE
        e = exe.index(b"\0", q)
        out.append((p, exe[q:e]))
    return out


def split_wrapper(raw):
    """SJIS name bytes -> (prefix, core, suffix): the leading ＠colour and a
    trailing ＠白 when present. Bytes up to the first null; the original
    table pads to 4, this tool to 2 (the layout 0x060B45C4 reads mov.w)."""
    raw = raw[:raw.index(b"\0")] if b"\0" in raw else raw
    pre = suf = b""
    core = raw
    if len(core) >= 4 and struct.unpack_from(">H", core, 0)[0] == AT:
        pre, core = core[:4], core[4:]
    if len(core) > 4 and core[-4:] == struct.pack(">HH", AT, WHITE):
        suf, core = core[-4:], core[:-4]
    return pre, core, suf


def load_spec():
    spec = json.load(open(NAMES_JSON, encoding="utf-8"))
    names = spec["names"]
    assert len(names) == N_NAMES and all(n["index"] == i for i, n in enumerate(names))
    return names


def pairs_used():
    """Every letter pair the English names would draw (satglyphs' ranking hook)."""
    import satglyphs
    out = []
    for n in load_spec():
        if n.get("en"):
            out += satglyphs.pairs_of(n["en"])
    return out


def encode_name(pf, en):
    """English -> SJIS bytes for the name table (pair codes negated per byte)."""
    codes = pf.encode(en)
    assert len(codes) % 2 == 0
    out = bytearray()
    for i in range(0, len(codes), 2):
        out += struct.pack(">H", satfont.code_to_sjis((codes[i] << 8) | codes[i + 1]))
    return bytes(out)


def decode_name(rev, sjis):
    """Name-table SJIS bytes back to text through the pair table (code -> pair)."""
    from textcodec import decode_stream
    out = []
    for i in range(0, len(sjis) - 1, 2):
        code = satfont.sjis_to_code(struct.unpack_from(">H", sjis, i)[0])
        if code in rev:
            out.append(rev[code])
        else:
            out.append(decode_stream(bytes([code >> 8, code & 0xFF])))
    return "".join(out)


def cells(rev, sjis):
    """Cells the name occupies: one per 2-byte code (a pair or a fullwidth letter)."""
    return len(sjis) // 2


def build(exe, pf, rev, names, log=print):
    """Write the English table into `exe` (bytearray) and repoint the pool.
    Returns (bytes in the original region, bytes in the hole, max cells)."""
    orig = pristine_names()
    blobs = []
    for n, (p, raw) in zip(names, orig):
        pre, core, suf = split_wrapper(raw)
        assert core.decode("cp932") == n["jp"], (n["index"], core.decode("cp932", "replace"), n["jp"])
        en = n.get("en")
        b = (pre + encode_name(pf, en) + suf if en else raw) + b"\0"
        blobs.append(b + b"\0" * (len(b) % 2))     # the layout reads mov.w: keep every pointer even
    # placement: the original region first, then the hole
    region = bytearray()
    overflow = []
    for i, b in enumerate(blobs):
        if len(region) + len(b) <= NAME_HI - NAME_LO:
            region += b
        else:
            overflow.append(i)
    led = satexec.load_ledger(bytes(exe))
    hole_addr = None
    hole = bytearray()
    for i in overflow:
        hole += blobs[i]
    if hole:
        hole_addr = satexec.alloc(led, exe, "satnames", len(hole), align=2)
    # write and repoint
    exe[NAME_LO - MAIN_BASE:NAME_HI - MAIN_BASE] = bytes(NAME_HI - NAME_LO)
    exe[NAME_LO - MAIN_BASE:NAME_LO - MAIN_BASE + len(region)] = region
    if hole:
        exe[hole_addr - MAIN_BASE:hole_addr - MAIN_BASE + len(hole)] = hole
    ra, ha = NAME_LO, hole_addr
    maxc = 0
    for i, b in enumerate(blobs):
        if i in overflow:
            addr, ha = ha, ha + len(b)
        else:
            addr, ra = ra, ra + len(b)
        struct.pack_into(">I", exe, POOL - MAIN_BASE + 4 * i, addr)
        pre, core, suf = split_wrapper(b[:b.index(b"\0")])
        c = cells(rev, core)
        maxc = max(maxc, c)
        n = names[i]
        log(f"  {i:2d} {addr:#x} {len(b):3d}B {c:2d} cells  {n['jp']:8s} -> {decode_name(rev, core)!r}"
            + ("  (hole)" if i in overflow else ""))
    return led, len(region), len(hole), maxc, hole_addr


def verify(exe, rev, names):
    """Read every pointer back and decode the name; returns the failures."""
    bad = []
    for i, n in enumerate(names):
        p = struct.unpack_from(">I", exe, POOL - MAIN_BASE + 4 * i)[0]
        q = p - MAIN_BASE
        raw = bytes(exe[q:exe.index(b"\0", q)])
        pre, core, suf = split_wrapper(raw)
        got = decode_name(rev, core).rstrip()     # an odd-length name ends in pairfont's pad space
        got = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in got)   # fallback letters
        want = n.get("en") or n["jp"]
        if got != want:
            bad.append((i, want, got))
    return bad


def main(argv):
    cmd = argv[0] if argv else "apply"
    dry = "--dry" in argv
    if cmd == "show":
        exe = open(satexec.OUT_MAIN if os.path.exists(satexec.OUT_MAIN) else satdata.MAIN, "rb").read()
        rev = {}
        if os.path.exists(PAIR_TABLE):
            rev = {code: pair for pair, (slot, code) in json.load(open(PAIR_TABLE)).items()}
        for i in range(N_NAMES):
            p = struct.unpack_from(">I", exe, POOL - MAIN_BASE + 4 * i)[0]
            q = p - MAIN_BASE
            raw = exe[q:exe.index(b"\0", q)]
            pre, core, suf = split_wrapper(raw)
            print(f"{i:2d} {p:#x} {raw.hex()}  {decode_name(rev, core)!r}")
        return
    if not os.path.exists(satexec.OUT_MAIN):
        sys.exit(f"{satexec.OUT_MAIN} missing: run satapply.py first")
    import satapply
    table = json.load(open(PAIR_TABLE))
    pf = satapply.SatPairFont(table)
    rev = {code: pair for pair, (slot, code) in table.items()}
    names = load_spec()
    exe = bytearray(open(satexec.OUT_MAIN, "rb").read())
    if pristine_names(bytes(exe))[0][1] != pristine_names()[0][1]:
        sys.exit("the name table in patched/saturn/MAIN_L.BIN is not pristine - double apply?")
    lines = []

    def log(m=""):
        print(m, flush=True)
        lines.append(m)

    led, in_region, in_hole, maxc, hole_addr = build(exe, pf, rev, names, log)
    bad = verify(exe, rev, names)
    for i, want, got in bad:
        log(f"VERIFY FAIL {i}: {want!r} -> {got!r}")
    import satglyphs
    fb = sum(1 for n in names if n.get("en") for p in satglyphs.pairs_of(n["en"]) if p not in table)
    log(f"names: {len(names)} written, {in_region} bytes in the original table (of {NAME_HI - NAME_LO}), "
        f"{in_hole} bytes in the hole" + (f" at {hole_addr:#x}" if hole_addr else "") +
        f"; widest {maxc} cells (row 0 holds 20, 14 in mode 7); {fb} pair uses without a glyph slot (fullwidth)")
    if bad:
        sys.exit("verification failed; nothing written")
    if maxc > MAX_CELLS:
        log(f"WARNING: a name is wider than {MAX_CELLS} cells")
    if dry:
        log("dry run: nothing written")
    else:
        open(satexec.OUT_MAIN, "wb").write(bytes(exe))
        satexec.save_ledger(led, bytes(exe))
        log(f"wrote {satexec.OUT_MAIN}")
    os.makedirs(os.path.join(WORK, "saturn", "build"), exist_ok=True)
    with open(os.path.join(WORK, "saturn", "build", "names_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1:])
