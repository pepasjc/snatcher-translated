"""MIPS R3000 disassembly helpers for SLPS_001.54.

    ram = file - 0x800 + 0x80028000

The PS-EXE header gives t_addr = 0x80028000 with t_size = 0x78800, and
0x800 + 0x78800 is exactly the file length.

**Do not check this with `find_scene_var.load_ram`.** That function finds the
scene table in a savestate by content and then *assumes* it lives at its
`TABLE_RAM` constant to back-compute where RAM starts, so it can only ever
echo back the address it was given. It was carrying the old 0x80059E8C, which
made every address measured through it 0x18000 low, and made the wrong answer
look independently confirmed. `TABLE_RAM` is now 0x80071E8C.

Independent support for 0x80028000: the code materialises the scene buffer
0x8010D000 at five sites and 0x800F5000 at none, and under the old alignment a
savestate's exception vectors at 0x80000080 read as zero, which cannot happen on
a running machine.

Usage:
    python disasm.py at 0x80029a28 [count]     disassemble from a RAM address
    python disasm.py const 0x800F5000          find code materialising a constant
    python disasm.py xref 0x800F5000           same, plus the enclosing function
"""
import os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

EXE = os.path.join(ROOT, "discs/extracted_ps1", "SLPS_001.54")

HDR = 0x800
TEXT = 0x80028000          # from the PS-EXE header; see the note above
# DISASM_FILE=path DISASM_BASE=0x800B4000 disassembles an overlay (no header)
if os.environ.get("DISASM_FILE"):
    EXE, HDR, TEXT = os.environ["DISASM_FILE"], 0, int(os.environ.get("DISASM_BASE", "0x800B4000"), 16)

_d = open(EXE, "rb").read()


def ram(fileoff):
    return fileoff - HDR + TEXT


def foff(addr):
    return addr - TEXT + HDR


def word(addr):
    return struct.unpack_from("<I", _d, foff(addr))[0]


def dis(addr, count=32):
    """Yield (addr, mnemonic, operands) from a RAM address."""
    import capstone
    m = capstone.Cs(capstone.CS_ARCH_MIPS,
                    capstone.CS_MODE_MIPS32 | capstone.CS_MODE_LITTLE_ENDIAN)
    start = foff(addr)
    for ins in m.disasm(_d[start:start + count * 4], addr):
        yield ins.address, ins.mnemonic, ins.op_str


def show(addr, count=32):
    for a, mn, ops in dis(addr, count):
        print(f"{a:08x}  {word(a):08x}  {mn:<9s} {ops}")


def find_const(value):
    """Find lui + addiu/ori/load-store pairs that build `value` in one register.

    Returns [(lui_addr, second_addr, reg)]. The partner is looked for within 8
    instructions, which covers the compiler's delay-slot shuffling.
    """
    hi, lo = (value >> 16) & 0xFFFF, value & 0xFFFF
    # addiu sign-extends: if the low half is negative the lui must carry hi + 1,
    # so that ((hi+1) << 16) + (lo - 0x10000) == (hi << 16) + lo.
    hi_adj = (hi + 1) & 0xFFFF
    MEM = (0x23, 0x2B, 0x21, 0x25, 0x29, 0x28, 0x20, 0x24)
    out = []
    for off in range(0, len(_d) - HDR - 4, 4):
        w = struct.unpack_from("<I", _d, HDR + off)[0]
        if (w >> 26) != 0x0F:
            continue
        imm, reg = w & 0xFFFF, (w >> 16) & 0x1F
        if imm not in (hi, hi_adj):
            continue
        need_signed = imm == hi_adj
        for k in range(1, 9):
            p = HDR + off + 4 * k
            if p + 4 > len(_d):
                break
            w2 = struct.unpack_from("<I", _d, p)[0]
            op2, rs, imm2 = w2 >> 26, (w2 >> 21) & 0x1F, w2 & 0xFFFF
            if rs != reg:
                continue
            if op2 == 0x09 or op2 in MEM:
                if imm2 == lo and (imm2 >= 0x8000) == need_signed:
                    out.append((ram(HDR + off), ram(p), reg))
            elif op2 == 0x0D and not need_signed and imm2 == lo:
                out.append((ram(HDR + off), ram(p), reg))
            break
    return out


def func_start(addr, limit=0x600):
    """Walk back to a plausible entry (addiu sp, sp, -n)."""
    a = addr
    for _ in range(limit):
        a -= 4
        w = word(a)
        if (w >> 26) == 0x09 and ((w >> 21) & 0x1F) == 29 \
           and ((w >> 16) & 0x1F) == 29 and (w & 0xFFFF) >= 0x8000:
            return a
    return None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "at"
    if cmd == "at":
        show(int(sys.argv[2], 16), int(sys.argv[3]) if len(sys.argv) > 3 else 32)
    elif cmd in ("const", "xref"):
        v = int(sys.argv[2], 16)
        hits = find_const(v)
        print(f"{len(hits)} site(s) materialise {v:#010x}")
        for lui, second, reg in hits:
            fn = func_start(lui)
            print(f"  {lui:08x} + {second:08x}  reg=${reg}"
                  + (f"   in function {fn:08x}" if fn else "   (no prologue found)"))
            if cmd == "xref":
                show(lui, 6)
                print()
