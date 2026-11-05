"""A minimal SH-2 assembler for the exec-side stubs (satlong.py, satnames.py).

The PS1 side has ps1/tools/mipsasm.py; this is its SH-2 twin, just the
opcodes the stubs need, two-pass, with labels and an automatic literal
pool. A program is a list of tuples:

    ("label", "name")
    ("mov.l", "=0x060fd164", "r1")      PC-relative load of a literal (pooled)
    ("mov.l", "=name", "r1")            ... of a label's address
    ("mov.l", "@r1", "r1")              mov.l @rm,rn
    ("mov.l", "@r3+", "r0")             post-increment
    ("mov.l", "r6", "@r2")              store
    ("mov.l", "r4", "@-r15")            pre-decrement (push)
    ("mov.w", "@(2,r3)", "r0")          mov.w @(disp,rm),r0
    ("mov", "#4", "r0") / ("mov", "r4", "r5")
    ("add", "#-4", "r3") / ("add", "r1", "r4") / ("sub", "r1", "r5")
    ("cmp/eq", "r6", "r0"), ("cmp/eq", "#19", "r0"), ("cmp/hs", ...), ("cmp/hi", ...), ("tst", "r7", "r7")
    ("extu.w", "r0", "r0"), ("extu.b", ...), ("shll2", "r4"), ("dt", "r7")
    ("bt", "label"), ("bf", ...), ("bra", ...), ("bt/s", ...), ("bf/s", ...)
    ("jmp", "@r0"), ("jsr", "@r1"), ("rts",), ("nop",)
    ("sts.l", "pr", "@-r15"), ("lds.l", "@r15+", "pr")
    ("pool",)                           where the literal pool goes (else: the end)
    (".word", 0x1234) / (".long", 0x12345678)

`asm(prog, org)` returns (bytes, labels). Delay slots are the caller's
business (write the nop). The pool is 4-aligned; every `=literal` must be
within 1020 bytes after its load. `check()` disassembles the result with
capstone (through sh2dis.Image) and prints it beside the source.
"""
import os, struct, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]


def _reg(s):
    s = s.strip()
    if s == "pc":
        return None
    assert s.startswith("r"), s
    n = int(s[1:])
    assert 0 <= n <= 15, s
    return n


def _imm(s):
    return int(s[1:], 0) if s.startswith("#") else int(s, 0)


class Asm:
    def __init__(self, prog, org):
        self.prog, self.org = prog, org
        self.labels = {}
        self.lits = []          # literal values in pool order
        self.lit_index = {}

    def _lit(self, spec):
        """`=value` or `=label` -> pool index."""
        key = spec[1:]
        if key not in self.lit_index:
            self.lit_index[key] = len(self.lits)
            self.lits.append(key)
        return self.lit_index[key]

    def _lit_value(self, key):
        if key in self.labels:
            return self.labels[key]
        return int(key, 0)

    def encode(self, ins, pc, pass2):
        op = ins[0]
        a = ins[1:]
        if op == "nop":
            return [0x0009]
        if op == "rts":
            return [0x000B]
        if op in (".word",):
            return [a[0] & 0xFFFF]
        if op in (".long",):
            return [(a[0] >> 16) & 0xFFFF, a[0] & 0xFFFF]
        if op == "mov":
            if a[0].startswith("#"):
                v = _imm(a[0])
                assert -128 <= v <= 127, ins
                return [0xE000 | _reg(a[1]) << 8 | (v & 0xFF)]
            return [0x6003 | _reg(a[1]) << 8 | _reg(a[0]) << 4]
        if op in ("mov.l", "mov.w", "mov.b"):
            sz = {"mov.b": 0, "mov.w": 1, "mov.l": 2}[op]
            src, dst = a
            if src.startswith("="):                      # PC-relative literal
                assert op == "mov.l"
                idx = self._lit(src)
                if not pass2:
                    return [0]
                target = self.pool_addr + 4 * idx
                disp = (target - ((pc + 4) & ~3)) // 4
                assert 0 <= disp <= 255, (ins, hex(pc), hex(target))
                return [0xD000 | _reg(dst) << 8 | disp]
            if src.startswith("@(") and dst == "r0":     # mov.w/l @(disp,rm),r0
                d, m = src[2:-1].split(",")
                d = int(d, 0)
                assert d % (1 << sz) == 0 and 0 <= d >> sz <= 15
                return [0x8400 | sz << 8 | _reg(m) << 4 | (d >> sz)]
            if src.startswith("@") and src.endswith("+"):  # post-increment load
                return [0x6004 | sz | _reg(dst) << 8 | _reg(src[1:-1]) << 4]
            if src.startswith("@"):                      # load
                return [0x6000 | sz | _reg(dst) << 8 | _reg(src[1:]) << 4]
            if dst.startswith("@-"):                     # push
                return [0x2004 | sz | _reg(dst[2:]) << 8 | _reg(src) << 4]
            if dst.startswith("@"):                      # store
                return [0x2000 | sz | _reg(dst[1:]) << 8 | _reg(src) << 4]
            raise ValueError(ins)
        if op == "add":
            if a[0].startswith("#"):
                v = _imm(a[0])
                assert -128 <= v <= 127
                return [0x7000 | _reg(a[1]) << 8 | (v & 0xFF)]
            return [0x300C | _reg(a[1]) << 8 | _reg(a[0]) << 4]
        if op == "sub":
            return [0x3008 | _reg(a[1]) << 8 | _reg(a[0]) << 4]
        if op == "cmp/eq" and a[0].startswith("#"):     # cmp/eq #imm,r0 (imm sign-extended)
            assert a[1] == "r0", ins
            v = _imm(a[0])
            assert -128 <= v <= 127, ins
            return [0x8800 | (v & 0xFF)]
        if op == "cmp/eq":
            return [0x3000 | _reg(a[1]) << 8 | _reg(a[0]) << 4]
        if op == "cmp/hs":
            return [0x3002 | _reg(a[1]) << 8 | _reg(a[0]) << 4]
        if op == "cmp/hi":
            return [0x3006 | _reg(a[1]) << 8 | _reg(a[0]) << 4]
        if op == "tst":
            return [0x2008 | _reg(a[1]) << 8 | _reg(a[0]) << 4]
        if op == "and":
            return [0x2009 | _reg(a[1]) << 8 | _reg(a[0]) << 4]
        if op == "or":
            return [0x200B | _reg(a[1]) << 8 | _reg(a[0]) << 4]
        if op == "extu.w":
            return [0x600D | _reg(a[1]) << 8 | _reg(a[0]) << 4]
        if op == "extu.b":
            return [0x600C | _reg(a[1]) << 8 | _reg(a[0]) << 4]
        if op == "shll2":
            return [0x4008 | _reg(a[0]) << 8]
        if op == "shlr8":
            return [0x4019 | _reg(a[0]) << 8]
        if op == "shll8":
            return [0x4018 | _reg(a[0]) << 8]
        if op == "shll16":
            return [0x4028 | _reg(a[0]) << 8]
        if op == "shll":
            return [0x4000 | _reg(a[0]) << 8]
        if op == "shlr":
            return [0x4001 | _reg(a[0]) << 8]
        if op == "dt":
            return [0x4010 | _reg(a[0]) << 8]
        if op in ("bt", "bf", "bt/s", "bf/s"):
            code = {"bt": 0x8900, "bf": 0x8B00, "bt/s": 0x8D00, "bf/s": 0x8F00}[op]
            if not pass2:
                return [0]
            disp = (self.labels[a[0]] - (pc + 4)) // 2
            assert -128 <= disp <= 127, ins
            return [code | (disp & 0xFF)]
        if op in ("bra", "bsr"):
            if not pass2:
                return [0]
            disp = (self.labels[a[0]] - (pc + 4)) // 2
            assert -2048 <= disp <= 2047, ins
            return [(0xA000 if op == "bra" else 0xB000) | (disp & 0xFFF)]
        if op == "jmp":
            return [0x402B | _reg(a[0][1:]) << 8]
        if op == "jsr":
            return [0x400B | _reg(a[0][1:]) << 8]
        if op == "sts.l":
            assert a[0] == "pr" and a[1].startswith("@-")
            return [0x4022 | _reg(a[1][2:]) << 8]
        if op == "lds.l":
            assert a[1] == "pr" and a[0].startswith("@") and a[0].endswith("+")
            return [0x4026 | _reg(a[0][1:-1]) << 8]
        raise ValueError(f"unknown op {ins}")

    def run(self):
        # pass 1: sizes and labels. A `pool` marker in the middle of the
        # program occupies 4 bytes per literal, and the literals are only
        # all known once pass 1 has seen every load, so pass 1 repeats until
        # the label map is stable (two rounds; satkeys.py puts its directory
        # words after the pool).
        prev = None
        for _ in range(4):
            pc = self.org
            pool_at = None
            nlits = len(self.lits)
            for ins in self.prog:
                if ins[0] == "label":
                    self.labels[ins[1]] = pc
                elif ins[0] == "pool":
                    pool_at = (pc + 3) & ~3
                    pc = pool_at + 4 * nlits
                else:
                    pc += 2 * len(self.encode(ins, pc, False))
            if pool_at is None:
                pool_at = (pc + 3) & ~3
            if (dict(self.labels), pool_at, len(self.lits)) == prev:
                break
            prev = (dict(self.labels), pool_at, len(self.lits))
        self.pool_addr = pool_at
        # pass 2 (labels known, pool address known)
        out = bytearray()
        pc = self.org
        for ins in self.prog:
            if ins[0] == "label":
                continue
            if ins[0] == "pool":
                while pc % 4:
                    out += b"\x00\x09"[::-1] if False else struct.pack(">H", 0x0009)
                    pc += 2
                for key in self.lits:
                    out += struct.pack(">I", self._lit_value(key))
                    pc += 4
                continue
            for w in self.encode(ins, pc, True):
                out += struct.pack(">H", w)
                pc += 2
        if pc <= self.pool_addr:
            while pc % 4:
                out += struct.pack(">H", 0x0009)
                pc += 2
            assert pc == self.pool_addr
            for key in self.lits:
                out += struct.pack(">I", self._lit_value(key))
                pc += 4
        self.end = pc
        return bytes(out)


def asm(prog, org):
    """Assemble; returns (bytes, labels dict)."""
    a = Asm(prog, org)
    code = a.run()
    return code, a.labels


def check(code, org, count=None):
    """Disassemble `code` at `org` with capstone via sh2dis (a listing string)."""
    import sh2dis
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(code)
        path = f.name
    try:
        img = sh2dis.Image(path, org)
        lines = []
        for a, op, mn, ops, note in img.dis(org, count or len(code) // 2):
            lines.append(f"{a:08x}  {op:04x}  {mn:8s} {ops:24s} {note}")
        return "\n".join(lines)
    finally:
        os.unlink(path)


if __name__ == "__main__":
    demo = [
        ("label", "start"),
        ("mov.l", "=0x060fd164", "r1"),
        ("mov.l", "@r1", "r1"),
        ("mov", "r4", "r5"),
        ("sub", "r1", "r5"),
        ("mov.w", "@(2,r3)", "r0"),
        ("extu.w", "r0", "r0"),
        ("cmp/eq", "r6", "r0"),
        ("bf", "miss"),
        ("mov.w", "@r3+", "r7"),
        ("dt", "r7"),
        ("bf", "start"),
        ("label", "miss"),
        ("mov.l", "=start", "r0"),
        ("jmp", "@r0"),
        ("nop",),
        ("sts.l", "pr", "@-r15"),
        ("lds.l", "@r15+", "pr"),
        ("rts",),
        ("nop",),
    ]
    code, labels = asm(demo, 0x060E7200)
    print(check(code, 0x060E7200))
