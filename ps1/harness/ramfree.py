"""Free-RAM census: which bytes of the 2 MB no run ever wrote.

`scripted.py` with `RAMTOUCH=N[,path]` samples RAM every N frames and saves a
mask (1 = the byte changed between two samples) as `ramtouch.npy` in its
out dir. This ORs the masks of several runs and prints the untouched runs
of at least `--min` bytes above `--from` (default 0x80100000: the scene
slot and everything over it), with the known regions named, so a blob
loaded beside the bank can be placed by measurement rather than hope.

  python ps1/harness/ramfree.py work/regress/*/ramtouch.npy [--min 4096]
"""
import argparse, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")

KNOWN = [
    (0x8010D000, 0x80118000, "scene slot (ISZ)"),
    (0x80118000, 0x8011C000, "B050 resident"),
    (0x80135000, 0x80135000 + 9 * 0x4800, "face buffers (9 x 0x4800)"),
    (0x801A6800, 0x801DA000, "asset heap (seen; B220's tunnel to 0x801D9989)"),
    (0x801E1000, 0x801EC000, "LONGS: long strings + remap group"),
    (0x801F0000, 0x801FC000, "HIRAM: subtitle blob (48 KB cap)"),
    (0x801FC000, 0x801FC800, "SCRATCH"),
    (0x801FC800, 0x801FD000, "DISPATCH"),
    (0x801FD000, 0x801FE000, "SLIDELOG/NAMETRACE rings"),
    (0x801FE000, 0x801FF000, "RESIDENT (word wrap)"),
    (0x801FF000, 0x80200000, "stack page"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("masks", nargs="+")
    ap.add_argument("--min", type=int, default=4096)
    ap.add_argument("--from", dest="lo", type=lambda x: int(x, 0), default=0x80100000)
    a = ap.parse_args()
    mask = np.zeros(0x200000, dtype=np.uint8)
    for m in a.masks:
        x = np.load(m)
        print(f"{m}: {int(x.sum()):8d} bytes touched")
        mask |= x
    print(f"union: {int(mask.sum())} of {len(mask)} touched ({100 * mask.sum() / len(mask):.1f}%)")
    lo = a.lo & 0x1FFFFF
    untouched = mask[lo:] == 0
    # runs of untouched bytes
    d = np.diff(np.concatenate([[0], untouched.astype(np.int8), [0]]))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    total = 0
    print(f"\nuntouched runs >= {a.min} bytes above {a.lo:#x}:")
    for s, e in zip(starts, ends):
        if e - s < a.min:
            continue
        total += e - s
        ra, rb = 0x80000000 + lo + s, 0x80000000 + lo + e
        names = [n for (ka, kb, n) in KNOWN if ka < rb and kb > ra]
        print(f"  {ra:#010x}..{rb:#010x}  {(e - s) // 1024:5d} KB  {'; '.join(names)}")
    print(f"total untouched in runs >= {a.min}: {total // 1024} KB")


if __name__ == "__main__":
    main()
