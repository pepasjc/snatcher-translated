"""The speaker's nameplate on a dialogue line's continuation page (Luiz,
2026-09-18: "whenever our text requires an extra card, the speaker name is
omitted").

The dialogue task's WAIT step (0x80047C30) handles a press by hiding the
nameplate sprite (ctx+0x2530), the cursor and the six rows, then looks at
the window word: row (bits 20-22) < rows (bits 17-19) means more text, and
the step goes straight back to type-on (0x800479D8) - the plate stays
hidden for the rest of the line. The engine's own lines never page (the
Japanese fits three rows), so Konami never saw it; the full-length English
pages often.

The nameplate step (0x80047978) is exactly "show the plate if the line has
a name (window-word bit 8), show row 0, step := type-on", so the fix is to
route the paging branch through it: the `addiu a1, a1, 0x79d8` at
0x80047D6C becomes 0x7978. One halfword in the exec.

    python ps1/tools/pageplate.py apply      # after apply_translation.py, before patch_disc.py
    python ps1/tools/pageplate.py check
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

EXE = os.path.join(ROOT, "patched", "SLPS_001.54")
SITE = 0x80047D6C                 # addiu a1, a1, imm  (a1 = the next step's address)
TYPEON = 0x79D8                   # 0x800479D8: the type-on step (what ships)
NAMEPLATE = 0x7978                # 0x80047978: the nameplate step (shows the plate, then type-on)


def fo(ram):
    return ram - 0x80028000 + 0x800


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    exe = bytearray(open(EXE, "rb").read())
    ins = struct.unpack_from("<I", exe, fo(SITE))[0]
    op, imm = ins >> 16, ins & 0xFFFF
    if op != 0x24A5:                                  # addiu a1, a1
        raise SystemExit(f"{SITE:#x} holds {ins:#010x}, not addiu a1,a1: exec layout changed?")
    if mode == "check":
        print(f"{SITE:#x}: addiu a1,a1,{imm:#x} -> "
              + {TYPEON: "type-on (plate hidden on a continuation page)",
                 NAMEPLATE: "nameplate step (plate shown)"}.get(imm, "?"))
        return
    if mode != "apply":
        raise SystemExit(__doc__)
    if imm == NAMEPLATE:
        print("pageplate: already applied")
        return
    if imm != TYPEON:
        raise SystemExit(f"{SITE:#x}: unexpected immediate {imm:#x}")
    struct.pack_into("<I", exe, fo(SITE), (op << 16) | NAMEPLATE)
    open(EXE, "wb").write(exe)
    print(f"pageplate: {SITE:#x} addiu a1,a1,{TYPEON:#x} -> {NAMEPLATE:#x} (the plate on every page)")


if __name__ == "__main__":
    main()
