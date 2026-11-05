"""Turn Gaudi's katakana input keyboard into a Latin one.

The layout is a Shift-JIS table in the executable at 0x49DB8, stored as
null-separated groups (mostly five cells, but the サ row carries a sixth
cell for ＋), followed by the dakuten/handakuten conversion rows used by
the ゛ and ゜ keys.

Only kana cells are replaced, and only with characters Shift-JIS can encode.
Functional keys (＋ ／ ． ！ ？ ー ゜ ゛ ← →) keep their positions so any
special handling still applies.

Usage: python patch_keyboard.py
"""
import os, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

EXE = os.path.join(ROOT, "patched", "SLPS_001.54")
TABLE = 0x49DB8
NGROUPS = 11                     # displayed rows; later groups are conversions

# Per layout group: replacement for each cell, None keeps the original.
#
# A group is one on-screen block of five keys, and the panel shows three
# blocks side by side, so group g sits at screen row g % 4, columns
# (g // 4) * 5 .. + 4. The order below therefore reads across the keyboard:
#
#   A B C D E   F G H I J   K L M N O
#   P Q R S T   U V W X Y   Z . . ! ?
#   0 1 2 3 4   5 6 7 8 9   - ゜ ゛ ← →
#   . . . . .   . / . . .         O K
#
# `kbdfaces.py` draws the key faces from this same table, so the two stay
# in step; before it existed the faces were unreadable katakana and the
# order here did not matter.
ROWS = [
    ["A", "B", "C", "D", "E"],
    ["P", "Q", "R", "S", "T"],
    ["0", "1", "2", "3", "4", None],     # trailing ＋ kept
    [" ", " ", " ", " ", " "],
    ["F", "G", "H", "I", "J"],
    ["U", "V", "W", "X", "Y"],
    ["5", "6", "7", "8", "9"],
    [" ", None, " ", None, " "],         # ／ and ． kept
    ["K", "L", "M", "N", "O"],
    ["Z", " ", " ", None, None],         # ！ ？ kept
    [None, None, None, None, None],      # ー ゜ ゛ ← → kept
]

def groups(data):
    """Null-separated cell groups from the layout table."""
    out, o = [], TABLE
    while len(out) < NGROUPS:
        while data[o:o+2] == b"\x00\x00":
            o += 2
        cells = []
        while data[o:o+2] != b"\x00\x00":
            cells.append(o)
            o += 2
        out.append(cells)
    return out

def show(data, gs):
    return " | ".join(
        "".join(data[o:o+2].decode("shift_jis", "replace") for o in g) for g in gs)

if __name__ == "__main__":
    data = bytearray(open(EXE, "rb").read())
    gs = groups(data)
    print("before:", show(data, gs))

    changed = 0
    for row, cells in zip(ROWS, gs):
        for ch, off in zip(row, cells):
            if ch is None:
                continue
            fw = "　" if ch == " " else chr(0xFEE0 + ord(ch))
            data[off:off+2] = fw.encode("shift_jis")
            changed += 1

    print("after: ", show(data, gs))
    open(EXE, "wb").write(bytes(data))
    print(f"rewrote {changed} cells in {os.path.basename(EXE)}")
