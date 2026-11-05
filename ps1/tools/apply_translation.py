"""Apply translation JSONs: pair-encode EN strings, patch ISZ files in place,
write pair glyphs into exec, report any string over budget.

Also rebuilds the speaker name table, because every patched file must be
encoded against the *same* pair table — rebuild_pairs.py reassigns slots, so a
file left over from an earlier table decodes as different pairs (see CLAUDE.md).
Rebuilding it here means no sequence of commands can ship a stale one.

Usage: python apply_translation.py [ISZ_B010 ...]   (default: all with EN text)
"""
import sys, os, json, glob
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
from pairfont import PairFont
import translate_names

SRC = os.path.join(ROOT, "discs/extracted_ps1/PLN/ISZ")
TR = os.path.join(ROOT, r"ps1/translation")
OUT = os.path.join(ROOT, r"patched")
EXE_SRC = os.path.join(ROOT, "discs/extracted_ps1/SLPS_001.54")

def resize_name_table(exe, size, orig):
    """The name-table converter (0x8003D198, at every scene load) walks the
    NSZ's length-prefixed records for as many BYTES as the file-table record
    says (`[0x80071E84]` -> the class-1 record {ram, lba, size}, `lw $a0, 8`),
    and the record still said the pristine 439: the "full"-length English
    table (487 B) lost its last six names - Konami, Oume, Customer, Petrovich,
    Randam, Driver drew an EMPTY name row over their lines (GitHub #66, the
    Oleen hospital's customer; 2026-09-17). The file sits alone in its sector,
    so the read itself was never short - only the walk."""
    import struct
    lba, old = json.load(open(os.path.join(WORK, "lba_map.json")))["NSZ_B000.BIN"]
    assert old == orig, (old, orig)
    rec = exe.find(struct.pack("<II", lba, old))
    if rec < 0:
        raise SystemExit("NSZ_B000: no file-table record for lba %d" % lba)
    if size > ((old + 2047) // 2048) * 2048:
        raise SystemExit("NSZ_B000: %d bytes overruns its sector" % size)
    exe[rec + 4:rec + 8] = struct.pack("<I", size)
    print(f"NSZ_B000: file-table size {old} -> {size} (record at exec {rec:#x})")


if __name__ == "__main__":
    wanted = sys.argv[1:]
    pf = PairFont()
    os.makedirs(OUT, exist_ok=True)
    patched_files = []
    for jpath in sorted(glob.glob(os.path.join(TR, "ISZ_*.json"))):
        name = os.path.basename(jpath).replace(".json", "")
        if wanted and name not in wanted:
            continue
        spec = json.load(open(jpath, encoding="utf-8"))
        # "lock" marks engine data (the videophone dial table), which must keep
        # its original bytes or the game cannot match what the player dials.
        blocked = [e for e in spec["strings"] if e.get("lock") and e.get("en")]
        for e in blocked:
            print(f"{name} off={e['off']:#x}: REFUSED, engine data is locked: {e['en']!r}")
        todo = [e for e in spec["strings"] if e.get("en") and not e.get("lock")]
        if not todo:
            continue
        d = bytearray(open(os.path.join(SRC, spec["file"]), "rb").read())
        ok = over = 0
        for e in todo:
            try:
                eb = pf.encode(e["en"]) + b"\x00"
            except ValueError as ex:
                print(f"{name} off={e['off']:#x}: ENCODE FAIL {ex}")
                over += 1
                continue
            if len(eb) > e["budget"]:
                print(f"{name} off={e['off']:#x}: OVER by {len(eb)-e['budget']}B: {e['en'][:40]}")
                over += 1
                continue
            d[e["off"]:e["off"]+e["budget"]] = eb + b"\x00" * (e["budget"] - len(eb))
            ok += 1
        open(os.path.join(OUT, spec["file"]), "wb").write(bytes(d))
        patched_files.append(spec["file"])
        print(f"{name}: {ok} applied, {over} problems, of {len(todo)} provided")
    names, orig = translate_names.build(pf, "full")
    open(os.path.join(OUT, "NSZ_B000.BIN"), "wb").write(names)
    print(f"NSZ_B000: {len(names)} bytes (orig {orig}), {len(translate_names.NAMES)} names")

    exe_path = os.path.join(OUT, "SLPS_001.54")
    exe = bytearray(open(EXE_SRC, "rb").read())
    pf.write_glyphs(exe)
    resize_name_table(exe, len(names), orig)
    open(exe_path, "wb").write(exe)
    pf.save()
    print(f"pair glyphs: {len(pf.table)} used / {pf.capacity()} capacity")
