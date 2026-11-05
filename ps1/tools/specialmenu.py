"""Open the hidden SPECIAL MENU (wall paper, cursor colour, target pointer)
from the options screen with START alone - no Konami code (GitHub #30).

How the game does it: the pad handler (0x8002B4E8) keeps a listener in the
context's pad block - ctx+0x111 armed, ctx+0x112 unlocked, ctx+0x113 the
position in the sequence, ctx+0x114 a 60-frame timeout between presses.
Pressing START on the OPTION MENU runs script variable 0x50A, whose read
(0x8004ADDC) arms the listener and clears the unlock; the listener then
walks the halfword table at RAM 0x80070930 (file 0x49130):

    UP UP DOWN DOWN LEFT RIGHT LEFT RIGHT CROSS CIRCLE 0xFFFF

and on reaching the 0xFFFF end marker sets ctx+0x112 = 1, which the title
overlay polls for and answers with the SPECIAL MENU (poking that byte alone
opens it; that is how the flag was confirmed). Writing the end marker over
the table's FIRST entry makes the listener unlock on the frame after it is
armed, so OPTION MENU -> START goes straight to the SPECIAL MENU. Nothing
else reads the table, and the listener is disarmed everywhere but there.

    python ps1/tools/specialmenu.py apply     patch patched/SLPS_001.54
    python ps1/tools/specialmenu.py check     report the table's state
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

EXE = os.path.join(ROOT, "patched", "SLPS_001.54")
TABLE = 0x49130                       # RAM 0x80070930
PRISTINE = bytes.fromhex("0010" "0010" "0040" "0040" "0080" "0020" "0080" "0020"
                         "4000" "2000" "ffff")
PATCHED = b"\xff\xff" + PRISTINE[2:]


def state(data):
    t = bytes(data[TABLE:TABLE + len(PRISTINE)])
    return {PRISTINE: "pristine", PATCHED: "patched"}.get(t, "unknown: " + t.hex())


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    data = bytearray(open(EXE, "rb").read())
    s = state(data)
    if cmd == "check":
        print(f"special-menu table: {s}")
        return
    if cmd != "apply":
        sys.exit(__doc__)
    if s.startswith("unknown"):
        sys.exit(f"specialmenu: the pad-sequence table at {TABLE:#x} is not the game's ({s})")
    data[TABLE:TABLE + 2] = b"\xff\xff"
    open(EXE, "wb").write(data)
    print(f"special-menu: OPTION MENU -> START opens it ({s} -> patched)")


if __name__ == "__main__":
    main()
