"""A small HuC6280 interpreter to run the engine stubs against real data.

Enough of the CPU for pceengine's code (the modes asm6280 emits; TAM/TMA keep
an MPR array). `Sim(mem)` takes a 64 KB bytearray with zero page at $2000;
`call(addr)` runs until the matching RTS. `sim.hook[addr] = fn` replaces a
subroutine at that address (fn(sim) does the work, the RTS is implied).
"""

LOADS = {0xA9: "imm", 0xA5: "zp", 0xB5: "zpx", 0xAD: "abs", 0xBD: "absx", 0xB9: "absy", 0xB2: "zpi", 0xB1: "zpiy"}
STORES = {0x85: "zp", 0x95: "zpx", 0x8D: "abs", 0x9D: "absx", 0x99: "absy", 0x92: "zpi", 0x91: "zpiy"}
RMW = {0x06: ("asl", "zp"), 0x0E: ("asl", "abs"), 0x46: ("lsr", "zp"), 0x4E: ("lsr", "abs"),
       0x26: ("rol", "zp"), 0x2E: ("rol", "abs"), 0x66: ("ror", "zp"), 0x6E: ("ror", "abs"),
       0xE6: ("inc", "zp"), 0xEE: ("inc", "abs"), 0xFE: ("inc", "absx"),
       0xC6: ("dec", "zp"), 0xCE: ("dec", "abs")}
ACC = {0x0A: "asl", 0x4A: "lsr", 0x2A: "rol", 0x6A: "ror", 0x1A: "inc", 0x3A: "dec"}
SIZE = {"imm": 2, "zp": 2, "zpx": 2, "zpi": 2, "zpiy": 2, "abs": 3, "absx": 3, "absy": 3}


class Sim:
    def __init__(self, mem):
        self.m = mem
        self.a = self.x = self.y = 0
        self.c = self.z = self.n = 0
        self.sp = 0xFF
        self.mpr = [0xFF, 0xF8, 0x68, 0x69, 0x7E, 0x7F, 0x80, 0]
        self.hook = {}
        self.steps = 0

    def nz(self, v):
        v &= 0xFF
        self.z = int(v == 0)
        self.n = v >> 7
        return v

    def push(self, v):
        self.m[0x2100 + self.sp] = v & 0xFF
        self.sp = (self.sp - 1) & 0xFF

    def pop(self):
        self.sp = (self.sp + 1) & 0xFF
        return self.m[0x2100 + self.sp]

    def rd16(self, a):
        return self.m[a] | (self.m[(a + 1) & 0xFFFF] << 8)

    def call(self, addr, limit=200000):
        self.push(0xFF)
        self.push(0xFE)                     # returns to $FFFF = done
        self.pc = addr
        while self.pc != 0xFFFF:
            self.step()
            self.steps += 1
            if self.steps > limit:
                raise RuntimeError("runaway")

    def alu(self, kind, v):
        if kind == "asl":
            self.c = v >> 7; v = (v << 1) & 0xFF
        elif kind == "lsr":
            self.c = v & 1; v >>= 1
        elif kind == "rol":
            c = self.c; self.c = v >> 7; v = ((v << 1) | c) & 0xFF
        elif kind == "ror":
            c = self.c; self.c = v & 1; v = (v >> 1) | (c << 7)
        elif kind == "inc":
            v = (v + 1) & 0xFF
        elif kind == "dec":
            v = (v - 1) & 0xFF
        return self.nz(v)

    def step(self):
        m, pc = self.m, self.pc
        if pc in self.hook:
            self.hook[pc](self)
            lo, hi = self.pop(), self.pop()
            self.pc = ((hi << 8) | lo) + 1
            return
        op = m[pc]
        b1 = m[(pc + 1) & 0xFFFF]
        w = b1 | (m[(pc + 2) & 0xFFFF] << 8)
        zp = 0x2000 + b1

        def ea(mode):
            return {"zp": zp, "zpx": 0x2000 + ((b1 + self.x) & 0xFF), "abs": w,
                    "absx": (w + self.x) & 0xFFFF, "absy": (w + self.y) & 0xFFFF,
                    "zpi": self.rd16(zp), "zpiy": (self.rd16(zp) + self.y) & 0xFFFF}[mode]

        def val(mode):
            return b1 if mode == "imm" else m[ea(mode)]

        n = 1
        if op == 0xEA:
            pass
        elif op in LOADS:
            mode = LOADS[op]; self.a = self.nz(val(mode)); n = SIZE[mode]
        elif op in STORES:
            mode = STORES[op]; m[ea(mode)] = self.a; n = SIZE[mode]
        elif op in (0xA2, 0xA6, 0xAE):
            mode = {0xA2: "imm", 0xA6: "zp", 0xAE: "abs"}[op]; self.x = self.nz(val(mode)); n = SIZE[mode]
        elif op in (0xA0, 0xA4, 0xAC, 0xBC):
            mode = {0xA0: "imm", 0xA4: "zp", 0xAC: "abs", 0xBC: "absx"}[op]; self.y = self.nz(val(mode)); n = SIZE[mode]
        elif op in (0x86, 0x8E):
            mode = "zp" if op == 0x86 else "abs"; m[ea(mode)] = self.x; n = SIZE[mode]
        elif op in (0x84, 0x8C):
            mode = "zp" if op == 0x84 else "abs"; m[ea(mode)] = self.y; n = SIZE[mode]
        elif op in (0x64, 0x9C, 0x9E):
            mode = {0x64: "zp", 0x9C: "abs", 0x9E: "absx"}[op]; m[ea(mode)] = 0; n = SIZE[mode]
        elif op in (0xC9, 0xC5, 0xCD, 0xE0, 0xC0):
            reg = self.y if op == 0xC0 else self.x if op == 0xE0 else self.a
            mode = {0xC9: "imm", 0xC5: "zp", 0xCD: "abs", 0xE0: "imm", 0xC0: "imm"}[op]
            v = val(mode); self.c = int(reg >= v); self.nz(reg - v); n = SIZE[mode]
        elif op in (0x69, 0x65, 0x6D, 0x7D):
            mode = {0x69: "imm", 0x65: "zp", 0x6D: "abs", 0x7D: "absx"}[op]
            r = self.a + val(mode) + self.c; self.c = int(r > 0xFF); self.a = self.nz(r); n = SIZE[mode]
        elif op in (0xE9, 0xE5, 0xED):
            mode = {0xE9: "imm", 0xE5: "zp", 0xED: "abs"}[op]
            r = self.a - val(mode) - (1 - self.c); self.c = int(r >= 0); self.a = self.nz(r); n = SIZE[mode]
        elif op in (0x29, 0x25, 0x2D):
            mode = {0x29: "imm", 0x25: "zp", 0x2D: "abs"}[op]; self.a = self.nz(self.a & val(mode)); n = SIZE[mode]
        elif op in (0x09, 0x05, 0x0D):
            mode = {0x09: "imm", 0x05: "zp", 0x0D: "abs"}[op]; self.a = self.nz(self.a | val(mode)); n = SIZE[mode]
        elif op in (0x49, 0x45, 0x4D):
            mode = {0x49: "imm", 0x45: "zp", 0x4D: "abs"}[op]; self.a = self.nz(self.a ^ val(mode)); n = SIZE[mode]
        elif op in ACC:
            self.a = self.alu(ACC[op], self.a)
        elif op in RMW:
            kind, mode = RMW[op]; a = ea(mode); m[a] = self.alu(kind, m[a]); n = SIZE[mode]
        elif op == 0x4C:
            self.pc = w; return
        elif op == 0x20:
            ret = pc + 2; self.push(ret >> 8); self.push(ret & 0xFF); self.pc = w; return
        elif op == 0x60:
            lo, hi = self.pop(), self.pop(); self.pc = ((hi << 8) | lo) + 1; return
        elif op in (0x90, 0xB0, 0xF0, 0xD0, 0x10, 0x30, 0x80):
            take = {0x90: not self.c, 0xB0: self.c, 0xF0: self.z, 0xD0: not self.z,
                    0x10: not self.n, 0x30: self.n, 0x80: True}[op]
            n = 2
            if take:
                self.pc = pc + 2 + (b1 - 256 if b1 > 127 else b1); return
        elif op == 0x53:                                  # TAM
            for i in range(8):
                if b1 & (1 << i):
                    self.mpr[i] = self.a
            n = 2
        elif op == 0x43:                                  # TMA
            for i in range(8):
                if b1 & (1 << i):
                    self.a = self.mpr[i]
            n = 2
        elif op in (0x38, 0x18):
            self.c = int(op == 0x38)
        elif op == 0xE8: self.x = self.nz(self.x + 1)
        elif op == 0xC8: self.y = self.nz(self.y + 1)
        elif op == 0xCA: self.x = self.nz(self.x - 1)
        elif op == 0x88: self.y = self.nz(self.y - 1)
        elif op == 0xAA: self.x = self.nz(self.a)
        elif op == 0x8A: self.a = self.nz(self.x)
        elif op == 0xA8: self.y = self.nz(self.a)
        elif op == 0x98: self.a = self.nz(self.y)
        elif op == 0x48: self.push(self.a)
        elif op == 0xDA: self.push(self.x)
        elif op == 0x5A: self.push(self.y)
        elif op == 0x68: self.a = self.nz(self.pop())
        elif op == 0xFA: self.x = self.nz(self.pop())
        elif op == 0x7A: self.y = self.nz(self.pop())
        elif op == 0x62: self.a = 0
        elif op == 0x82: self.x = 0
        elif op == 0xC2: self.y = 0
        else:
            raise NotImplementedError(f"opcode {op:02x} at {pc:04x}")
        self.pc = pc + n
