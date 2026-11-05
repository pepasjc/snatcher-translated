"""A small MIPS R3000 assembler with labels, for the subtitle payload.

Only the handful of instructions the payload needs. Two passes, so labels can
be referenced before they are defined. Every load is followed by an explicit
`nop` in the caller's code - the R3000 load-delay slot is real on this
hardware and silently returns the stale register otherwise.
"""
import struct

REG = {"$zero": 0, "$at": 1, "$v0": 2, "$v1": 3, "$a0": 4, "$a1": 5, "$a2": 6,
       "$a3": 7, "$s0": 16, "$s1": 17, "$s2": 18, "$s3": 19, "$ra": 31,
       "$sp": 29, "$gp": 28, "$fp": 30, "$k0": 26, "$k1": 27}
REG.update({f"$t{i}": 8 + i for i in range(8)})
REG["$t8"] = 24
REG["$t9"] = 25


class Asm:
    def __init__(self, org):
        self.org = org
        self.items = []          # (kind, payload)

    # --- structure ---------------------------------------------------------
    def label(self, name):
        self.items.append(("label", name))

    def word(self, value):
        self.items.append(("word", value))

    def blob(self, data):
        assert len(data) % 4 == 0
        for i in range(0, len(data), 4):
            self.items.append(("word", struct.unpack_from("<I", data, i)[0]))

    # --- instructions ------------------------------------------------------
    def _i(self, fn):
        self.items.append(("ins", fn))

    def lui(self, rt, imm):
        self._i(lambda pc, L: 0x3C000000 | REG[rt] << 16 | (imm & 0xFFFF))

    def ori(self, rt, rs, imm):
        self._i(lambda pc, L: 0x34000000 | REG[rs] << 21 | REG[rt] << 16 | (imm & 0xFFFF))

    def xori(self, rt, rs, imm):
        self._i(lambda pc, L: 0x38000000 | REG[rs] << 21 | REG[rt] << 16 | (imm & 0xFFFF))

    def andi(self, rt, rs, imm):
        self._i(lambda pc, L: 0x30000000 | REG[rs] << 21 | REG[rt] << 16 | (imm & 0xFFFF))

    def addiu(self, rt, rs, imm):
        self._i(lambda pc, L: 0x24000000 | REG[rs] << 21 | REG[rt] << 16 | (imm & 0xFFFF))

    def sltiu(self, rt, rs, imm):
        self._i(lambda pc, L: 0x2C000000 | REG[rs] << 21 | REG[rt] << 16 | (imm & 0xFFFF))

    def slt(self, rd, rs, rt):
        self._i(lambda pc, L: 0x2A | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)

    def sltu(self, rd, rs, rt):
        self._i(lambda pc, L: 0x2B | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)

    def addu(self, rd, rs, rt):
        self._i(lambda pc, L: 0x21 | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)

    def subu(self, rd, rs, rt):
        self._i(lambda pc, L: 0x23 | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)

    def and_(self, rd, rs, rt):
        self._i(lambda pc, L: 0x24 | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)

    def or_(self, rd, rs, rt):
        self._i(lambda pc, L: 0x25 | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11)

    def sll(self, rd, rt, sh):
        self._i(lambda pc, L: REG[rt] << 16 | REG[rd] << 11 | (sh & 0x1F) << 6)

    def srl(self, rd, rt, sh):
        self._i(lambda pc, L: 0x02 | REG[rt] << 16 | REG[rd] << 11 | (sh & 0x1F) << 6)

    def lw(self, rt, off, base):
        self._i(lambda pc, L: 0x8C000000 | REG[base] << 21 | REG[rt] << 16 | (off & 0xFFFF))

    def lb(self, rt, off, base):
        self._i(lambda pc, L: 0x80000000 | REG[base] << 21 | REG[rt] << 16 | (off & 0xFFFF))

    def lbu(self, rt, off, base):
        self._i(lambda pc, L: 0x90000000 | REG[base] << 21 | REG[rt] << 16 | (off & 0xFFFF))

    def lhu(self, rt, off, base):
        self._i(lambda pc, L: 0x94000000 | REG[base] << 21 | REG[rt] << 16 | (off & 0xFFFF))

    def lh(self, rt, off, base):
        self._i(lambda pc, L: 0x84000000 | REG[base] << 21 | REG[rt] << 16 | (off & 0xFFFF))

    def sh(self, rt, off, base):
        self._i(lambda pc, L: 0xA4000000 | REG[base] << 21 | REG[rt] << 16 | (off & 0xFFFF))

    def sb(self, rt, off, base):
        self._i(lambda pc, L: 0xA0000000 | REG[base] << 21 | REG[rt] << 16 | (off & 0xFFFF))

    def sw(self, rt, off, base):
        self._i(lambda pc, L: 0xAC000000 | REG[base] << 21 | REG[rt] << 16 | (off & 0xFFFF))

    def beq(self, rs, rt, target):
        self._i(lambda pc, L: 0x10000000 | REG[rs] << 21 | REG[rt] << 16
                | (((L[target] - (pc + 4)) >> 2) & 0xFFFF))

    def bne(self, rs, rt, target):
        self._i(lambda pc, L: 0x14000000 | REG[rs] << 21 | REG[rt] << 16
                | (((L[target] - (pc + 4)) >> 2) & 0xFFFF))

    def bgez(self, rs, target):
        self._i(lambda pc, L: 0x04010000 | REG[rs] << 21
                | (((L[target] - (pc + 4)) >> 2) & 0xFFFF))

    def bltz(self, rs, target):
        self._i(lambda pc, L: 0x04000000 | REG[rs] << 21
                | (((L[target] - (pc + 4)) >> 2) & 0xFFFF))

    def b(self, target):
        self._i(lambda pc, L: 0x10000000 | (((L[target] - (pc + 4)) >> 2) & 0xFFFF))

    def j(self, target):
        self._i(lambda pc, L: 0x08000000
                | (((L[target] if isinstance(target, str) else target) >> 2) & 0x03FFFFFF))

    def jal(self, target):
        self._i(lambda pc, L: 0x0C000000
                | (((L[target] if isinstance(target, str) else target) >> 2) & 0x03FFFFFF))

    def jalr(self, rs):
        self._i(lambda pc, L: 0x09 | REG[rs] << 21 | 31 << 11)

    def jr(self, rs):
        self._i(lambda pc, L: 0x08 | REG[rs] << 21)

    def nop(self):
        self._i(lambda pc, L: 0)

    # --- output ------------------------------------------------------------
    def labels(self):
        out, pc = {}, self.org
        for kind, payload in self.items:
            if kind == "label":
                out[payload] = pc
            else:
                pc += 4
        return out

    def assemble(self):
        L = self.labels()
        out, pc = bytearray(), self.org
        for kind, payload in self.items:
            if kind == "label":
                continue
            w = payload if kind == "word" else payload(pc, L)
            out += struct.pack("<I", w & 0xFFFFFFFF)
            pc += 4
        return bytes(out)

    def size(self):
        return sum(1 for k, _ in self.items if k != "label") * 4
