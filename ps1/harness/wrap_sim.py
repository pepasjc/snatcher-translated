"""Run ps1/tools/wordwrap.py's resident stub on a string under a tiny R3000
interpreter (the opcode subset the stub uses), against the real exec font,
and print the rows it produces. A unit test for the MIPS, independent of
the emulator.

  python ps1/harness/wrap_sim.py B030 6945 14
  python ps1/harness/wrap_sim.py --sjis <hex> 14
"""
import json, os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import wordwrap
from textcodec import jis_to_code, code_to_jis
from pairfont import PairFont

EXE = os.path.join(ROOT, "patched", "SLPS_001.54")


class Mem:
    def __init__(self):
        self.ram = bytearray(0x200000)

    def off(self, a):
        return a & 0x1FFFFF

    def r8(self, a): return self.ram[self.off(a)]
    def r16(self, a): return struct.unpack_from("<H", self.ram, self.off(a))[0]
    def r32(self, a): return struct.unpack_from("<I", self.ram, self.off(a))[0]
    def w8(self, a, v): self.ram[self.off(a)] = v & 0xFF
    def w16(self, a, v): struct.pack_into("<H", self.ram, self.off(a), v & 0xFFFF)
    def w32(self, a, v): struct.pack_into("<I", self.ram, self.off(a), v & 0xFFFFFFFF)


def sx16(v):
    return v - 0x10000 if v & 0x8000 else v


def run(mem, pc, regs, stop_pc, max_steps=2000000):
    """Interpret from pc until pc == stop_pc. Branch delay slots honoured;
    load delay NOT modelled (the stub is written to survive it either way)."""
    steps = 0
    next_pc = pc + 4
    pending = None                       # (target) taken after the delay slot
    while True:
        if pc == stop_pc:
            return regs
        ins = mem.r32(pc)
        op = ins >> 26
        rs, rt, rd = (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31
        sh, fn, imm = (ins >> 6) & 31, ins & 63, ins & 0xFFFF
        target = None
        if op == 0:
            if fn == 0: regs[rd] = (regs[rt] << sh) & 0xFFFFFFFF
            elif fn == 2: regs[rd] = regs[rt] >> sh
            elif fn == 3: regs[rd] = ((regs[rt] ^ 0x80000000) - 0x80000000) >> sh & 0xFFFFFFFF
            elif fn == 8: target = regs[rs]
            elif fn == 9: regs[rd] = pc + 8; target = regs[rs]
            elif fn == 0x21: regs[rd] = (regs[rs] + regs[rt]) & 0xFFFFFFFF
            elif fn == 0x23: regs[rd] = (regs[rs] - regs[rt]) & 0xFFFFFFFF
            elif fn == 0x24: regs[rd] = regs[rs] & regs[rt]
            elif fn == 0x25: regs[rd] = regs[rs] | regs[rt]
            elif fn == 0x2a: regs[rd] = int(sx32(regs[rs]) < sx32(regs[rt]))
            elif fn == 0x2b: regs[rd] = int(regs[rs] < regs[rt])
            else: raise SystemExit(f"{pc:#x}: special fn {fn:#x} unsupported")
        elif op == 1:                     # bltz/bgez
            if (rt == 0 and regs[rs] & 0x80000000) or (rt == 1 and not regs[rs] & 0x80000000):
                target = pc + 4 + (sx16(imm) << 2)
        elif op == 2: target = (pc & 0xF0000000) | ((ins & 0x3FFFFFF) << 2)
        elif op == 3: regs[31] = pc + 8; target = (pc & 0xF0000000) | ((ins & 0x3FFFFFF) << 2)
        elif op == 4:
            if regs[rs] == regs[rt]: target = pc + 4 + (sx16(imm) << 2)
        elif op == 5:
            if regs[rs] != regs[rt]: target = pc + 4 + (sx16(imm) << 2)
        elif op == 9: regs[rt] = (regs[rs] + sx16(imm)) & 0xFFFFFFFF
        elif op == 0xb: regs[rt] = int(regs[rs] < (sx16(imm) & 0xFFFFFFFF))
        elif op == 0xc: regs[rt] = regs[rs] & imm
        elif op == 0xd: regs[rt] = regs[rs] | imm
        elif op == 0xe: regs[rt] = regs[rs] ^ imm
        elif op == 0xf: regs[rt] = imm << 16
        elif op == 0x23: regs[rt] = mem.r32(regs[rs] + sx16(imm))
        elif op == 0x24: regs[rt] = mem.r8(regs[rs] + sx16(imm))
        elif op == 0x25: regs[rt] = mem.r16(regs[rs] + sx16(imm))
        elif op == 0x28: mem.w8(regs[rs] + sx16(imm), regs[rt])
        elif op == 0x29: mem.w16(regs[rs] + sx16(imm), regs[rt])
        elif op == 0x2b: mem.w32(regs[rs] + sx16(imm), regs[rt])
        else: raise SystemExit(f"{pc:#x}: opcode {op:#x} unsupported")
        regs[0] = 0
        steps += 1
        if steps > max_steps:
            raise SystemExit("runaway")
        if target is not None:
            # execute the delay slot, then jump
            pc += 4
            if pc == stop_pc:
                return regs
            run_one = run(mem, pc, regs, pc + 4, 1)   # one instruction, no nesting of branches
            pc = target
        else:
            pc += 4


def sx32(v):
    return v - 0x100000000 if v & 0x80000000 else v


def sjis_of(code):
    """Game font code -> SJIS bytes, as the engine's upstream converter does."""
    ku, ten = code_to_jis(code)
    hi = (ku - 1) // 2
    lo = (ten - 1) + (0 if ku % 2 else 94)
    hi += 0x81 if hi < 0x1F else 0xC1
    lo += 0x40 if lo < 63 else 0x41
    return bytes([hi, lo])


def english_to_sjis(text, pf):
    out = bytearray()
    enc = pf.encode(text)
    for k in range(0, len(enc), 2):
        code = enc[k] << 8 | enc[k + 1]
        out += sjis_of(code)
    out += b"\0\0"
    return bytes(out)


def decode(sjis, pf, width=99):
    """Rows as the engine cuts them: at ￥ and at `width` cells."""
    inv = {}
    for pair, (slot, code) in pf.table.items():
        inv[sjis_of(code)] = pair
    rows, row, n = [], "", 0
    k = 0
    while k + 1 < len(sjis):
        b = sjis[k:k + 2]
        if b[0] == 0:
            break
        c = b[0] << 8 | b[1]
        if c == 0x818F:
            rows.append(row); row = ""; n = 0
        elif c == 0x8197:
            k += 2
        else:
            if n == width:
                rows.append(row); row = ""; n = 0
            row += inv.get(b, f"<{c:04x}>")
            n += 1
        k += 2
    rows.append(row)
    return rows


def main():
    args = sys.argv[1:]
    pf = PairFont()
    if args[0] == "--sjis":
        sjis = bytes.fromhex(args[1]) + b"\0\0"
        width = int(args[2])
    else:
        scene, off, width = args[0], int(args[1]), int(args[2])
        recs = json.load(open(os.path.join(ROOT, "ps1/translation", f"ISZ_{scene}.json"), encoding="utf-8"))["strings"]
        text = next(r["en"] for r in recs if r["off"] == off)
        print("text:", text)
        sjis = english_to_sjis(text, pf)
    mem = Mem()
    exe = open(EXE, "rb").read()
    mem.ram[0x28000:0x28000 + len(exe) - 0x800] = exe[0x800:]
    res = wordwrap.resident()
    mem.ram[mem.off(wordwrap.RESIDENT):mem.off(wordwrap.RESIDENT) + len(res)] = res
    STR, SP = 0x80100000, 0x801FF000
    mem.ram[mem.off(STR):mem.off(STR) + len(sjis)] = sjis
    regs = [0] * 32
    regs[29] = SP
    regs[19] = STR                       # s3, as the delay slot left it
    regs[31] = 0x80047678
    mem.w32(SP + wordwrap.WIDTH_OFF, width)
    mem.w32(SP + wordwrap.DEST_OFF, 0x80010000)
    labels = wordwrap.code().labels()
    run(mem, labels["wrap"], regs, wordwrap.RESUME)
    s3 = regs[19]
    print(f"s3 -> {s3:#x} ({'buffer' if s3 != STR else 'ORIGINAL'}), ra {regs[31]:#x}, a0 {regs[4]:#x}")
    out = bytes(mem.ram[mem.off(s3):mem.off(s3) + 0x400])
    for r in decode(out, pf, width):
        print(f"  |{r}|")
    print("python model:")
    if args[0] != "--sjis":
        for r in wordwrap.wrap_rows(text, width, pf):
            print(f"  |{r}|")


if __name__ == "__main__":
    main()
