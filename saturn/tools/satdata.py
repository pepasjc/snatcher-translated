"""DATA.BIN on the Saturn Snatcher: the entry table and the scene banks.

DATA.BIN (LBA 96, 10,967,040 bytes) is not one compressed blob: it is a
flat, sector-aligned pack of 639 entries addressed through a table in the
main executable MAIN_L.BIN (loaded at 0x060B0000; the table sits at RAM
0x060E62F4 = file offset 0x362F4). Each table entry is four bytes,
big-endian: {u16 sector within DATA.BIN, u16 size in 16-bit words}. The
loader at 0x060B22B4 opens "DATA.BIN" (GFS_NameToId / GFS_Open) and seeks
to the entry's sector; the scene loader at 0x060B2300 indexes the table by
scene number * 4 and reads size*2 bytes (see work/saturn/sh2dis.py for the
capstone helper that found it).

Entries 21..59 are the 39 scene banks, in the PS1's ISZ_B000..B260 order
(entry 21 = B000, 22 = B010, ... 59 = B260) with two differences: entry 42
(B150) also carries the PS1's B140 text, and entry 41 is a small extra
bank with no PS1 twin. A bank has the PS1 layout exactly - a BE16 offset of
the string region, byte-oriented bytecode, then null-terminated strings in
the PS1 font-index encoding (lib/textcodec.py: 2-byte big-endian codes,
`￥` line break, `＠`+colour). The text is NOT compressed: every long PS1
string searched hits raw (e.g. B010's 'わしのことは気にせんでくれ。' at
DATA.BIN 0x1FA17, in bank 22 = 0x1D000 + sbase 10770).

The other 600 entries (graphics, tables, sound-related data; most start
with a BE32 word and high-entropy data) are still undecoded - see the
report in the saturn-wip history. This tool does not touch them beyond
`dump`.

Usage (from the repo root):
    python saturn/tools/satdata.py list                 the table
    python saturn/tools/satdata.py dump [N...]          raw entries -> work/saturn/data/NNN.bin
    python saturn/tools/satdata.py script               banks -> work/saturn/ref/SAT_NNN_Bxxx.json
                                                        (same shape as work/ref/ISZ_*.json)
"""
import os, sys, json, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

from textcodec import decode_stream

EXTRACTED = os.path.join(ROOT, "discs", "extracted_saturn")
DATA = os.path.join(EXTRACTED, "DATA.BIN")
MAIN = os.path.join(EXTRACTED, "MAIN_L.BIN")
OUT_DATA = os.path.join(WORK, "saturn", "data")
OUT_REF = os.path.join(WORK, "saturn", "ref")

MAIN_BASE = 0x060B0000          # MAIN_L.BIN load address
TABLE_RAM = 0x060E62F4          # {u16 sector, u16 words} * N, N = 639
TABLE_OFF = TABLE_RAM - MAIN_BASE
SECTOR = 2048

# scene bank entries: table index -> PS1 bank name
FIRST_BANK, LAST_BANK = 21, 59
BANK_NAMES = {21 + i: f"B{i:02X}0" for i in range(39)}   # 21=B000 ... 59=B260
BANK_NAMES[41] = "B140x"       # extra small bank; the PS1's B140 text lives in entry 42 (B150)


def read_table(main=None):
    """The entry table as a list of (offset, size) into DATA.BIN."""
    m = main if main is not None else open(MAIN, "rb").read()
    data_len = os.path.getsize(DATA)
    ents = []
    o = TABLE_OFF
    while True:
        sec, words = struct.unpack(">HH", m[o:o + 4])
        if ents and sec < ents[-1][0] // SECTOR:
            break                       # the table is sector-monotonic; the next table follows it
        if sec * SECTOR > data_len:
            break
        ents.append((sec * SECTOR, words * 2))
        o += 4
    return ents


def entry(d, ents, i):
    off, size = ents[i]
    return d[off:off + size]


def bank_strings(bank):
    """Split a bank into its strings: [{off, budget, jp}], off = byte offset in the bank."""
    base = struct.unpack(">H", bank[0:2])[0]
    out = []
    i = base
    while i < len(bank):
        j = bank.find(b"\x00", i)
        if j < 0:
            j = len(bank)
        s = bank[i:j]
        if s:
            out.append({"off": i, "budget": (j - i) + 1, "jp": decode_stream(s)})
        i = j + 1
    return base, out


def cmd_list(d, ents):
    print(f"{len(ents)} entries; table at MAIN_L.BIN {TABLE_OFF:#x} (RAM {TABLE_RAM:#x})")
    for i, (off, size) in enumerate(ents):
        name = BANK_NAMES.get(i, "")
        head = d[off:off + 8].hex()
        print(f"{i:3d} off={off:#08x} sector={off // SECTOR:5d} size={size:7d} {head} {name}")


def cmd_dump(d, ents, which):
    os.makedirs(OUT_DATA, exist_ok=True)
    idx = [int(w) for w in which] if which else range(len(ents))
    for i in idx:
        off, size = ents[i]
        name = BANK_NAMES.get(i)
        fn = f"{i:03d}" + (f"_{name}" if name else "") + ".bin"
        with open(os.path.join(OUT_DATA, fn), "wb") as f:
            f.write(d[off:off + size])
    print(f"wrote {len(list(idx))} entries to {OUT_DATA}")


def cmd_script(d, ents):
    os.makedirs(OUT_REF, exist_ok=True)
    total = 0
    for i in range(FIRST_BANK, LAST_BANK + 1):
        bank = entry(d, ents, i)
        base, strings = bank_strings(bank)
        name = BANK_NAMES[i]
        rec = {"file": f"DATA.BIN[{i}]", "entry": i, "offset": ents[i][0], "size": len(bank),
               "text_base": base, "strings": strings}
        with open(os.path.join(OUT_REF, f"SAT_{i:03d}_{name}.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        unk = sum(s["jp"].count("[") for s in strings)
        total += len(strings)
        print(f"{i:3d} {name:6s} off={ents[i][0]:#08x} size={len(bank):6d} sbase={base:6d} "
              f"strings={len(strings):4d} unknown_codes={unk}")
    print(f"{total} strings -> {OUT_REF}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    d = open(DATA, "rb").read()
    ents = read_table()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        cmd_list(d, ents)
    elif cmd == "dump":
        cmd_dump(d, ents, sys.argv[2:])
    elif cmd == "script":
        cmd_script(d, ents)
    else:
        print(__doc__)
