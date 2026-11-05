"""Free space in the Saturn exec (MAIN_L.BIN) and the ledger the exec-side tools share.

MAIN_L.BIN is a C image: text, data, then BSS from 0x060EF480 to 0x060FF090
(the entry code at 0x060B002C zeroes exactly that range; the sbrk heap
starts at 0x060FF090 and runs to the end of high WRAM). There is no slack
after the file: appended bytes land in BSS and are cleared. Inside the
file every zero run over 64 bytes is live data - the tail 0x060EF194..
0x060EF478 is written at runtime (libc FILE structs), the runs around
0x060EEAF4 are the string allocator's free-list heads (0x060EEAFC..),
and unreferenced code comes in 90-byte scraps at most (2026-09-12 sweep:
1,456 rts-delimited blocks, 3,108 unreferenced bytes, none contiguous).

The one region that is provably unread: the SJIS -> glyph table
(0x060E6CF0, u16 per code from 0x8140, satfont.py) has its entries for
SJIS 0x83C0..0x889E - Greek lowercase, Cyrillic, box drawing, rows the
game never draws - at zero, 0x4DF entries = 2,494 bytes at 0x060E71F0..
0x060E7BAE (HOLE_LO..HOLE_HI, the outer bounds). Only the cell renderers
index it (0x060B4970 and the katakana keyboard's view from 0x8340, which
ends at 0x8396), and only with codes that are in the cells; the built
table (satglyphs.sjis_table_bytes) keeps every unused code at zero and
re-codes pairs onto free KANJI codes, never into this range.

A zero entry is not an unread one: any code the text carries is looked up,
and glyph 0 is the blank the game relies on for the Saturn-only code
0x7d2a (SJIS 0x83D6, textcodec's ω: 213 Japanese strings and 75 English
ones - the verbs `見るω`, `Multiple killers...?ω`), whose entry
0x060E721C sits INSIDE the range. The first builds handed that entry to
satnames' name bytes and every `Lookω` drew a scrap of them (2026-09-12).
So the usable hole is computed, not declared: `used_codes()` collects
every SJIS code a drawn text can contain - each bank string of
saturn/translation read the engine's way (the pristine bytes negated
and read as u16s from the start - the 70 `control` records, `<xx>` bytes
with no character in them, are engine data and skipped - AND the
English/`long` it gets: pair codes through work/saturn/pair_table_sat.json,
fullwidth fallbacks, the colour codes and symbols), names.json (en and jp), every subs_*.json cue
(rows, rows_plain, speaker), the exec's own SJIS strings (the name table,
the ＠colour table, every null-terminated run of 3+ characters) and every
code of the pair table - and `hole()` is the longest run of pristine-zero
entries whose codes are in none of that, aligned to 4: 0x060E7220..
0x060E7BAE with the data of 2026-09-12 (ω's entry and the one before it
excluded; nothing else in the range is used). Every `alloc` asserts its
range lies in that hole, that no code of it is used and that the bytes are
still zero; the ledger records the bounds and the used codes nearest each
end (`hole_reason`). `python saturn/tools/satexec.py` prints the hole,
the used codes inside the outer range and the ledger.

Allocation runs upward from the hole's start in this order: satnames.py
(the English speaker names that outgrow the original 1,048-byte table),
satlong.py (the remap stubs and their variables), satkeys.py, satsubs.py.
The ledger work/saturn/build/exec_alloc.json records each allocation with
the sha1 of the exec it produced; a tool whose input exec is not the
ledger's last output starts the ledger over (a fresh satapply.py output).
"""
import glob, hashlib, json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

MAIN_BASE = 0x060B0000
OUT_MAIN = os.path.join(ROOT, "patched", "saturn", "MAIN_L.BIN")
LEDGER = os.path.join(WORK, "saturn", "build", "exec_alloc.json")
HOLE_LO, HOLE_HI = 0x060E71F0, 0x060E7BAE     # the outer bounds: table entries 0x83C0..0x889E, zero in the pristine table
TABLE_ADDR, TABLE_LO = 0x060E6CF0, 0x8140
TABLE_N = 0x1734
TR = os.path.join(ROOT, "saturn", "translation")
PAIR_TABLE = os.path.join(WORK, "saturn", "pair_table_sat.json")
ALIGN = 4


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def code_to_sjis(code):
    """A PS1 2-byte font code as the Saturn converter makes it SJIS (each byte negated)."""
    return ((-(code >> 8)) & 0xFF) << 8 | ((-(code & 0xFF)) & 0xFF)


def _text_codes(s, table):
    """SJIS codes an English or Japanese string draws: letter pairs through
    `table` (pair -> [slot, code]; a pair without one = two fullwidth letters),
    everything non-ASCII through textcodec (colour codes, ￥, ▽, kana, kanji)."""
    from textcodec import char_to_code
    out = set()
    run = ""

    def flush(run):
        if len(run) % 2:
            run += " "
        for k in range(0, len(run), 2):
            pair = run[k:k + 2]
            if pair in table:
                out.add(code_to_sjis(table[pair][1]))
            else:
                for ch in pair:
                    fw = "　" if ch == " " else chr(0xFEE0 + ord(ch))
                    c = char_to_code(fw)
                    out.add(code_to_sjis(c if c is not None else char_to_code("？")))

    for ch in s:
        if ord(ch) < 0x80:
            run += ch
        else:
            flush(run)
            run = ""
            c = char_to_code(ch)
            if c is not None:                 # a dump's `<xx>`/`[xxxx]` markers are not text
                out.add(code_to_sjis(c))
    flush(run)
    return out


def _raw_codes(raw):
    """A bank string's bytes as the engine reads them: strlen, every byte
    negated, then u16s from the start (an odd tail pairs with the null)."""
    s = raw[:raw.index(b"\0")] if b"\0" in raw else raw
    if len(s) % 2:
        s = s + b"\0"
    return {code_to_sjis((s[i] << 8) | s[i + 1]) for i in range(0, len(s), 2)}


def _exec_codes(exe):
    """SJIS codes the exec itself draws: every null-terminated run of 3+ valid
    SJIS characters (the speaker names, the ＠colour table, system messages)."""
    def valid(b1, b2):
        return (0x81 <= b1 <= 0x9F or 0xE0 <= b1 <= 0xEF) and (0x40 <= b2 <= 0x7E or 0x80 <= b2 <= 0xFC)
    out = set()
    i, n = 0, len(exe)
    while i < n - 1:
        j, cnt = i, 0
        while j < n - 1 and valid(exe[j], exe[j + 1]):
            j += 2
            cnt += 1
        if cnt >= 3 and j < n and exe[j] == 0:
            out.update((exe[k] << 8) | exe[k + 1] for k in range(i, j, 2))
            i = j
        else:
            i += 1
    return out


def used_codes(exe=None, table=None):
    """Every SJIS code a drawn text can contain (the docstring's list). `exe`
    = the pristine exec by default (the built one keeps its strings; the
    English names are pair codes, in the table); `table` = the build's pair
    table (work/saturn/pair_table_sat.json)."""
    import satdata
    if table is None:
        table = json.load(open(PAIR_TABLE)) if os.path.exists(PAIR_TABLE) else {}
    if exe is None:
        exe = open(satdata.MAIN, "rb").read()
    used = set()
    data = open(satdata.DATA, "rb").read()
    ents = satdata.read_table()
    for path in sorted(glob.glob(os.path.join(TR, "SAT_*.json"))):
        spec = json.load(open(path, encoding="utf-8"))
        base = ents[spec["entry"]][0]
        for rec in spec["strings"]:
            if rec.get("carry") != "control":      # `<xx>`-only records are engine data, not text (an odd byte count)
                used |= _raw_codes(data[base + rec["off"]:base + rec["off"] + rec["budget"]])
            for key in ("en", "long"):
                if rec.get(key):
                    used |= _text_codes(rec[key], table)
    names = os.path.join(TR, "names.json")
    if os.path.exists(names):
        for n in json.load(open(names, encoding="utf-8"))["names"]:
            for key in ("en", "jp"):
                if n.get(key):
                    used |= _text_codes(n[key], table)
    for path in sorted(glob.glob(os.path.join(TR, "subs_*.json"))):
        for c in json.load(open(path, encoding="utf-8")).get("cues", []):
            for t in (c.get("rows") or []) + (c.get("rows_plain") or []) + [c.get("speaker") or "", c.get("en") or ""]:
                if t:
                    used |= _text_codes(t, table)
    used |= _exec_codes(exe)
    used |= {code_to_sjis(code) for slot, code in table.values()}
    return used


def hole(used=None):
    """(lo, hi, reason): the longest run of pristine-zero table entries whose
    codes are in `used_codes()`, as exec addresses (lo aligned up to ALIGN);
    `reason` names the used codes that bound it."""
    used = used_codes() if used is None else used
    import satdata
    exe = open(satdata.MAIN, "rb").read()
    o = TABLE_ADDR - MAIN_BASE
    free = [struct.unpack_from(">H", exe, o + 2 * i)[0] == 0 and (TABLE_LO + i) not in used
            for i in range(TABLE_N)]
    best = (0, 0)
    i = 0
    while i < TABLE_N:
        if free[i]:
            j = i
            while j < TABLE_N and free[j]:
                j += 1
            if j - i > best[1] - best[0]:
                best = (i, j)
            i = j
        else:
            i += 1
    lo_i, hi_i = best
    lo = (TABLE_ADDR + 2 * lo_i + ALIGN - 1) & ~(ALIGN - 1)
    hi = TABLE_ADDR + 2 * hi_i
    below = max((c for c in used if c < TABLE_LO + lo_i), default=None)
    above = min((c for c in used if c >= TABLE_LO + hi_i), default=None)
    reason = (f"SJIS {TABLE_LO + lo_i:#06x}..{TABLE_LO + hi_i - 1:#06x}; used below: "
              + (f"{below:#06x}" if below is not None else "none")
              + (f", above: {above:#06x}" if above is not None else ", none above"))
    return lo, hi, reason


def load_ledger(exe):
    """The ledger if it describes `exe` (its last output), else a fresh one
    with the hole computed from the current data."""
    if os.path.exists(LEDGER):
        led = json.load(open(LEDGER))
        if led.get("last_sha1") == sha1(exe) and "hole_lo" in led:
            return led
    lo, hi, reason = hole()
    assert HOLE_LO <= lo < hi <= HOLE_HI, (hex(lo), hex(hi))
    return {"next": lo, "hole_lo": lo, "hole_hi": hi, "hole_reason": reason,
            "allocations": [], "last_sha1": None}


def save_ledger(led, exe):
    led["last_sha1"] = sha1(exe)
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(led, open(LEDGER, "w"), indent=1)


def alloc(led, exe, who, size, align=4):
    """Reserve `size` bytes in the hole; returns the RAM address. The range
    must lie inside the computed hole, none of its table codes may be drawn
    by any text, and the bytes must still be zero in `exe` (bytearray)."""
    lo, hi = led.get("hole_lo", HOLE_LO), led.get("hole_hi", HOLE_HI)
    start = (led["next"] + align - 1) & ~(align - 1)
    end = start + size
    if end > hi:
        raise SystemExit(f"{who}: {size} bytes do not fit the exec hole "
                         f"({hi - start} left at {start:#x}; hole {lo:#x}..{hi:#x}: {led.get('hole_reason')})")
    assert lo <= start, (who, hex(start), hex(lo))
    seg = exe[start - MAIN_BASE:end - MAIN_BASE]
    if any(seg):
        raise SystemExit(f"{who}: exec bytes at {start:#x}..{end:#x} are not zero - "
                         f"a stale ledger, a double apply or another tool's data")
    used = used_codes()
    first = TABLE_LO + (start - TABLE_ADDR) // 2
    last = TABLE_LO + (end - 1 - TABLE_ADDR) // 2
    clash = sorted(c for c in used if first <= c <= last)
    if clash:
        raise SystemExit(f"{who}: table entries {start:#x}..{end:#x} (SJIS {first:#06x}..{last:#06x}) "
                         f"are drawn by text: {' '.join(f'{c:#06x}' for c in clash[:8])}")
    led["next"] = end
    led["allocations"].append({"who": who, "start": start, "end": end})
    return start


def sjis_range(led=None):
    """The SJIS codes whose table entries the hole covers: (first, last+1)."""
    lo = led["hole_lo"] if led else HOLE_LO
    hi = led["hole_hi"] if led else HOLE_HI
    return (lo - TABLE_ADDR) // 2 + TABLE_LO, (hi - TABLE_ADDR) // 2 + TABLE_LO


def main(argv):
    used = used_codes()
    lo, hi, reason = hole(used)
    print(f"hole {lo:#x}..{hi:#x} ({hi - lo} bytes): {reason}")
    outer = sjis_range()
    inrange = sorted(c for c in used if outer[0] <= c < outer[1])
    print(f"used codes inside the outer range {HOLE_LO:#x}..{HOLE_HI:#x} (SJIS {outer[0]:#06x}..{outer[1] - 1:#06x}): "
          f"{' '.join(f'{c:#06x}' for c in inrange)}")
    if os.path.exists(LEDGER):
        led = json.load(open(LEDGER))
        print(f"ledger: hole {led.get('hole_lo', 0):#x}..{led.get('hole_hi', 0):#x}, next {led['next']:#x}")
        for a in led["allocations"]:
            print(f"  {a['who']:14s} {a['start']:#x}..{a['end']:#x} ({a['end'] - a['start']} B)")


if __name__ == "__main__":
    main(sys.argv[1:])
