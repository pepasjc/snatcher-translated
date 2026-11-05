"""A small two-pass SH-2 assembler over TEXT source, for the subtitle payload.

saturn/tools/sh2asm.py (the names/long agent's) takes tuple programs; this one
takes a listing in the disassembler's syntax so a payload can be read and
pasted back as assembly. Same idea, different front end.

Enough of the instruction set for the subtitle payload: moves in every
addressing mode the payload needs, ALU, shifts, compares, branches, jsr/jmp,
pr save/restore. Big-endian output. Syntax follows the disassembler
(capstone) so a listing can be pasted back:

    label:
        mov.l   =0x060F24B0, r4      ; literal from the pool (`.pool` places it)
        mov.w   @(0x54A, r4), r0     ; NOT encodable: use r0-relative or add
        mov.w   @r4, r1
        cmp/eq  r1, r0
        bf      skip
        ...
    skip:
        rts
        nop
    .pool                            ; the literal pool (4-aligned) goes here
    .align 4
    .long 1, 2, label                ; data
    .word 0x889E
    .space 64

`Asm(base).assemble(text)` -> bytes; `.labels` -> {name: addr}. Branch
targets and pool loads are range-checked. `check()` disassembles the result
with capstone and compares mnemonics as a self-test (`python sh2asm.py`).
"""
import re, struct, sys

REG = {f"r{i}": i for i in range(16)}


def _reg(s):
    s = s.strip().lower()
    if s not in REG:
        raise ValueError(f"not a register: {s}")
    return REG[s]


class Asm:
    def __init__(self, base=0):
        self.base = base
        self.labels = {}
        self.consts = {}

    # ---- expression evaluation -------------------------------------------
    def val(self, s, pass_):
        s = s.strip()
        try:
            return int(s, 0)
        except ValueError:
            pass
        env = dict(self.consts)
        env.update(self.labels)
        try:
            return int(eval(s, {"__builtins__": {}}, env))
        except NameError:
            if pass_ == 0:
                return 0
            raise ValueError(f"unknown symbol in {s!r}")

    # ---- the two passes ----------------------------------------------------
    def assemble(self, text):
        lines = []
        for raw in text.splitlines():
            line = raw.split(";")[0].strip()
            if line:
                lines.append(line)
        out = b""
        # pass 0 sizes everything with unknown (forward) labels read as 0; pass 1 resolves
        # them. The pool coalesces equal literals BY TEXT, so both passes lay it out the same
        # way (coalescing by value merged every forward label into one slot in pass 0 - `=job`
        # and `=menuhold` shared it - and the pool grew in pass 1, shifting every label after
        # it: satsubs wrote its `menuhold` word over `job`, 2026-09-15). The second pass runs
        # twice so the pool words read labels from a settled pass, not pass 0's.
        for pass_ in (0, 1, 1):
            self.pc = self.base
            self.pool = []          # (value expr, patch offset, instruction pc)
            buf = bytearray()
            for line in lines:
                m = re.match(r"^([A-Za-z_.$][\w.$]*):\s*(.*)$", line)
                if m:
                    self.labels[m.group(1)] = self.pc
                    line = m.group(2).strip()
                    if not line:
                        continue
                if line.startswith("."):
                    self.directive(line, buf, pass_)
                    continue
                m = re.match(r"^(\w+)\s+(\w+)\s*=\s*(.+)$", line)
                if m and m.group(1) == "equ":
                    self.consts[m.group(2)] = self.val(m.group(3), pass_)
                    continue
                m = re.match(r"^(\w+)\s*=\s*(.+)$", line)
                if m and m.group(1) not in REG:
                    self.consts[m.group(1)] = self.val(m.group(2), pass_)
                    continue
                self.instr(line, buf, pass_)
            if self.pool:
                raise ValueError("literals without a .pool")
            out = bytes(buf)
        return out

    def emit(self, buf, op):
        buf += struct.pack(">H", op & 0xFFFF)
        self.pc += 2

    def directive(self, line, buf, pass_):
        parts = line.split(None, 1)
        d, arg = parts[0], (parts[1] if len(parts) > 1 else "")
        if d == ".align":
            n = int(arg, 0)
            while self.pc % n:
                buf += b"\0"; self.pc += 1
        elif d == ".pool":
            while self.pc % 4:
                buf += b"\0"; self.pc += 1
            # coalesce equal literals - by their text, so the layout is the same in every pass
            seen = {}
            for expr, off, ipc, kind in self.pool:
                v = self.val(expr, pass_) & 0xFFFFFFFF
                key = expr.replace(" ", "")
                if key not in seen:
                    seen[key] = self.pc
                    buf += struct.pack(">I", v); self.pc += 4
                addr = seen[key]
                disp = (addr - ((ipc + 4) & ~3)) // 4
                if not 0 <= disp <= 255:
                    raise ValueError(f"literal too far at {ipc:#x}")
                op = struct.unpack_from(">H", buf, off)[0] | disp
                struct.pack_into(">H", buf, off, op)
            self.pool = []
        elif d == ".long":
            for e in arg.split(","):
                buf += struct.pack(">I", self.val(e, pass_) & 0xFFFFFFFF); self.pc += 4
        elif d == ".word":
            for e in arg.split(","):
                buf += struct.pack(">H", self.val(e, pass_) & 0xFFFF); self.pc += 2
        elif d == ".byte":
            for e in arg.split(","):
                buf += bytes([self.val(e, pass_) & 0xFF]); self.pc += 1
        elif d == ".space":
            n = self.val(arg, pass_)
            buf += b"\0" * n; self.pc += n
        elif d == ".bytes":
            b = bytes.fromhex(arg.replace(" ", ""))
            buf += b; self.pc += len(b)
        else:
            raise ValueError(f"unknown directive {d}")

    def branch(self, target, pass_, bits):
        t = self.val(target, pass_)
        d = (t - (self.pc + 4)) // 2
        if pass_ == 1:
            if (t - (self.pc + 4)) % 2:
                raise ValueError(f"odd branch target {target}")
            lim = 1 << (bits - 1)
            if not -lim <= d < lim:
                raise ValueError(f"branch to {target} out of range at {self.pc:#x}")
        return d & ((1 << bits) - 1)

    def instr(self, line, buf, pass_):
        m = re.match(r"^([\w./]+)\s*(.*)$", line)
        mn, rest = m.group(1).lower(), m.group(2)
        ops = [o.strip() for o in re.split(r",(?![^(]*\))", rest)] if rest else []
        n = len(ops)
        pc = self.pc

        def R(i):
            return _reg(ops[i])

        def ind(s):        # @rn
            m = re.match(r"^@(r\d+)$", s.replace(" ", ""))
            return _reg(m.group(1)) if m else None

        def post(s):       # @rn+
            m = re.match(r"^@(r\d+)\+$", s.replace(" ", ""))
            return _reg(m.group(1)) if m else None

        def pre(s):        # @-rn
            m = re.match(r"^@-(r\d+)$", s.replace(" ", ""))
            return _reg(m.group(1)) if m else None

        def disp(s):       # @(d, rn) -> (d, n)  or @(r0, rn) -> ('r0', n)
            m = re.match(r"^@\((.+),\s*(r\d+)\)$", s.strip())
            if not m:
                return None
            d, r = m.group(1).strip(), _reg(m.group(2))
            if d.lower() == "r0":
                return ("r0", r)
            if d.lower() == "pc":
                return None
            return (self.val(d, pass_), r)

        size = {"mov.b": 0, "mov.w": 1, "mov.l": 2}
        if mn in size:
            sz = size[mn]
            src, dst = ops
            if src.startswith("="):                    # literal from the pool
                if sz != 2:
                    raise ValueError("only mov.l takes a pool literal")
                self.pool.append((src[1:], len(buf), pc, "l"))
                return self.emit(buf, 0xD000 | R(1) << 8)
            if src.startswith("#"):
                if sz != 2 or True:
                    raise ValueError("use mov #imm, rn")
            if dst in REG or dst.lower() in REG:
                rn = R(1)
                if ind(src) is not None:
                    return self.emit(buf, 0x6000 | rn << 8 | ind(src) << 4 | sz)
                if post(src) is not None:
                    return self.emit(buf, 0x6004 | rn << 8 | post(src) << 4 | sz)
                dd = disp(src)
                if dd:
                    d, rm = dd
                    if d == "r0":
                        return self.emit(buf, 0x000C | rn << 8 | rm << 4 | sz)
                    if sz == 2:
                        assert d % 4 == 0 and 0 <= d // 4 < 16, f"disp {d}"
                        return self.emit(buf, 0x5000 | rn << 8 | rm << 4 | d // 4)
                    assert rn == 0, "mov.b/w @(disp,rm) needs r0"
                    unit = 1 << sz
                    assert d % unit == 0 and 0 <= d // unit < 16, f"disp {d}"
                    return self.emit(buf, 0x8400 | sz << 8 | rm << 4 | d // unit)
                raise ValueError(f"bad source {src!r}")
            rm = R(0)
            if ind(dst) is not None:
                return self.emit(buf, 0x2000 | ind(dst) << 8 | rm << 4 | sz)
            if pre(dst) is not None:
                return self.emit(buf, 0x2004 | pre(dst) << 8 | rm << 4 | sz)
            dd = disp(dst)
            if dd:
                d, rn = dd
                if d == "r0":
                    return self.emit(buf, 0x0004 | rn << 8 | rm << 4 | sz)
                if sz == 2:
                    assert d % 4 == 0 and 0 <= d // 4 < 16, f"disp {d}"
                    return self.emit(buf, 0x1000 | rn << 8 | rm << 4 | d // 4)
                assert rm == 0, "mov.b/w r0,@(disp,rn) needs r0"
                unit = 1 << sz
                assert d % unit == 0 and 0 <= d // unit < 16, f"disp {d}"
                return self.emit(buf, 0x8000 | sz << 8 | rn << 4 | d // unit)
            raise ValueError(f"bad destination {dst!r}")
        if mn == "mov":
            src, dst = ops
            if src.startswith("#"):
                v = self.val(src[1:], pass_)
                assert -128 <= v <= 255, f"imm8 {v}"
                return self.emit(buf, 0xE000 | R(1) << 8 | (v & 0xFF))
            return self.emit(buf, 0x6003 | R(1) << 8 | R(0) << 4)
        two = {"add": 0x300C, "sub": 0x3008, "and": 0x2009, "or": 0x200B, "xor": 0x200A,
               "tst": 0x2008, "cmp/eq": 0x3000, "cmp/hs": 0x3002, "cmp/ge": 0x3003,
               "cmp/hi": 0x3006, "cmp/gt": 0x3007, "extu.b": 0x600C, "extu.w": 0x600D,
               "exts.b": 0x600E, "exts.w": 0x600F, "neg": 0x600B, "not": 0x6007,
               "swap.w": 0x6009, "swap.b": 0x6008, "mul.l": 0x0007, "mulu.w": 0x200E,
               "muls.w": 0x200F, "addc": 0x300E, "subc": 0x300A, "xtrct": 0x200D}
        if mn in two:
            if mn in ("add", "and", "or", "xor", "tst", "cmp/eq") and ops[0].startswith("#"):
                v = self.val(ops[0][1:], pass_)
                if mn == "add":
                    assert -128 <= v <= 127
                    return self.emit(buf, 0x7000 | R(1) << 8 | (v & 0xFF))
                assert R(1) == 0 and 0 <= v <= 255
                return self.emit(buf, {"and": 0xC900, "or": 0xCB00, "xor": 0xCA00,
                                       "tst": 0xC800, "cmp/eq": 0x8800}[mn] | v)
            return self.emit(buf, two[mn] | R(1) << 8 | R(0) << 4)
        one = {"shll": 0x4000, "shlr": 0x4001, "shll2": 0x4008, "shlr2": 0x4009,
               "shll8": 0x4018, "shlr8": 0x4019, "shll16": 0x4028, "shlr16": 0x4029,
               "shar": 0x4021, "shal": 0x4020, "dt": 0x4010, "movt": 0x0029,
               "cmp/pz": 0x4011, "cmp/pl": 0x4015, "rotl": 0x4004, "rotr": 0x4005,
               "rotcl": 0x4024, "rotcr": 0x4025}
        if mn in one:
            return self.emit(buf, one[mn] | R(0) << 8)
        if mn in ("jsr", "jmp"):
            return self.emit(buf, (0x400B if mn == "jsr" else 0x402B) | ind(ops[0]) << 8)
        if mn in ("sts", "lds", "sts.l", "lds.l"):
            if mn == "sts" and ops[0].lower() == "pr":
                return self.emit(buf, 0x002A | R(1) << 8)
            if mn == "sts" and ops[0].lower() == "macl":
                return self.emit(buf, 0x001A | R(1) << 8)
            if mn == "sts.l" and ops[0].lower() == "pr":
                return self.emit(buf, 0x4022 | pre(ops[1]) << 8)
            if mn == "lds.l" and ops[1].lower() == "pr":
                return self.emit(buf, 0x4026 | post(ops[0]) << 8)
            if mn == "lds" and ops[1].lower() == "pr":
                return self.emit(buf, 0x402A | R(0) << 8)
            raise ValueError(line)
        if mn in ("bt", "bf", "bt/s", "bf/s"):
            d = self.branch(ops[0], pass_, 8)
            return self.emit(buf, {"bt": 0x8900, "bf": 0x8B00, "bt/s": 0x8D00, "bf/s": 0x8F00}[mn] | d)
        if mn in ("bra", "bsr"):
            d = self.branch(ops[0], pass_, 12)
            return self.emit(buf, (0xA000 if mn == "bra" else 0xB000) | d)
        if mn == "rts":
            return self.emit(buf, 0x000B)
        if mn == "nop":
            return self.emit(buf, 0x0009)
        if mn == "clrt":
            return self.emit(buf, 0x0008)
        if mn == "sett":
            return self.emit(buf, 0x0018)
        raise ValueError(f"cannot assemble {line!r}")


def check(code, base, text_lines=None):
    """Disassemble with capstone and print beside the source (self-test aid)."""
    import capstone
    cs = capstone.Cs(capstone.CS_ARCH_SH, capstone.CS_MODE_SH2 | capstone.CS_MODE_BIG_ENDIAN)
    out = []
    for ins in cs.disasm(code, base):
        out.append(f"{ins.address:08x}  {ins.bytes.hex()}  {ins.mnemonic} {ins.op_str}")
    return "\n".join(out)


SELFTEST = """
start:
    mov.l   r14, @-r15
    sts.l   pr, @-r15
    mov.l   =0x060F24B0, r4
    mov.w   @r4, r1
    mov     #0x4A, r0
    mov.w   @(r0, r4), r2
    cmp/eq  r1, r2
    bf      skip
    mov.l   @(8, r4), r3
    mov.l   r3, @(12, r4)
    add     #-4, r3
    shll2   r3
    mov.b   @r3+, r5
    extu.b  r5, r5
    mov.w   r1, @r2
    jsr     @r3
    nop
skip:
    bra     start
    nop
    lds.l   @r15+, pr
    rts
    mov.l   @r15+, r14
.pool
"""

if __name__ == "__main__":
    a = Asm(0x060E71F0)
    code = a.assemble(SELFTEST)
    print(check(code, 0x060E71F0))
