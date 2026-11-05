"""Free-RAM census for the Saturn: which bytes of the 2 MB no run ever wrote.

`satplay.py` with `RAMTOUCH=N[,path]` samples RAM every N frames and saves a
mask (1 = the byte changed between two samples; CPU byte order, block 0 =
low WRAM 0x00200000, block 1 MB = high WRAM 0x06000000) as `ramtouch.npy`
in its out dir. This ORs the masks of several runs and prints the
untouched runs of at least `--min` bytes, with the known regions named, so
a blob loaded beside the bank can be placed by measurement.

  python saturn/harness/ramfree_sat.py work/saturn/regress/*/ramtouch.npy [--min 4096]
"""
import argparse, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")

WRAM = 0x100000
KNOWN = [
    (0x002A0000, 0x002E8000, "room script (chunk 60+N)"),
    (0x002E8000, 0x002F8000, "bank string region (64 KB window; subs blob at its end)"),
    (0x002F8000, 0x00300000, "bank bytecode"),
    (0x06010000, 0x060B0000, "A.BIN boot shell / FMV player"),
    (0x060B0000, 0x060F5000, "MAIN_L.BIN text+data"),
    (0x060EF480, 0x060FF090, "MAIN_L BSS"),
    (0x060F24B0, 0x060F24B0 + 0x5000, "game ctx"),
    (0x060FF090, 0x06100000, "sbrk heap"),
    (0x06048000 - 0x40000, 0x06088000, "streamed-load decode window (256 KB, top of high WRAM per note)"),
]


def addr_of(off):
    return 0x00200000 + off if off < WRAM else 0x06000000 + (off - WRAM)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("masks", nargs="+")
    ap.add_argument("--min", type=int, default=4096)
    a = ap.parse_args()
    mask = np.zeros(2 * WRAM, dtype=np.uint8)
    for m in a.masks:
        x = np.load(m)
        print(f"{m}: {int(x.sum()):8d} bytes touched")
        mask |= x
    print(f"union: {int(mask.sum())} of {len(mask)} touched ({100 * mask.sum() / len(mask):.1f}%)")
    untouched = mask == 0
    d = np.diff(np.concatenate([[0], untouched.astype(np.int8), [0]]))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    total = 0
    print(f"\nuntouched runs >= {a.min} bytes:")
    for s, e in zip(starts, ends):
        if e - s < a.min:
            continue
        if s < WRAM <= e:                       # never span the two blocks
            continue
        total += e - s
        ra, rb = addr_of(s), addr_of(e - 1) + 1
        names = [n for (ka, kb, n) in KNOWN if ka < rb and kb > ra]
        print(f"  {ra:#010x}..{rb:#010x}  {(e - s) // 1024:5d} KB  {'; '.join(names)}")
    print(f"total untouched in runs >= {a.min}: {total // 1024} KB")


if __name__ == "__main__":
    main()
