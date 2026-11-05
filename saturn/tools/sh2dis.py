"""SH-2 disassembly helpers for the Saturn Snatcher executables.

The BIOS loads the first root-directory file, A.BIN (LBA 26), at the
IP.BIN "1st read address" 0x06010000 (header +0xF0) and jumps there.  A.BIN
is the boot shell: it GFS-loads MAIN_L.BIN to 0x060B0000 (routine
0x06010280, name pointer 0x0602F320 -> "MAIN_L.BIN"), plays LOGO.TRM /
MX0.TRM / MX1.TRM by the halfword at 0x06010024, restores MAIN_L from its
low-RAM backup 0x002B0000 (0x06010378) and `jmp 0x060B0000` (0x06010080).
At base 0x060B0000, 3,626 of MAIN_L.BIN's 4,506 in-image literal-pool
pointers land on a function prologue or just after an rts; at any other
base under 10 do.  Override with --file / --base or SH2_FILE / SH2_BASE.

Usage (from the repo root):
    python saturn/tools/sh2dis.py at 0x060B0000 [count]      disassemble from an address
    python saturn/tools/sh2dis.py xref 0x060babcd            literal-pool words, branches, bsr/bra to an address
    python saturn/tools/sh2dis.py const 0x0FFF               literal-pool words / immediates equal to a value
    python saturn/tools/sh2dis.py func 0x060babcd            enclosing function start (last rts+slot before)
    python saturn/tools/sh2dis.py full [out.txt]             numbered full listing to work/saturn/dis_<name>.txt
    python saturn/tools/sh2dis.py strings [minlen]           ASCII runs with their addresses
    python saturn/tools/sh2dis.py --file A.BIN --base 0x06010000 at 0x06010000

Decoding is capstone's CS_ARCH_SH (5.x) in SH2 big-endian mode.  Every
`mov.l/mov.w @(disp,PC)` is annotated with the constant it loads
(`; =0x060b0000`), and a `jsr @rN` / `jmp @rN` whose register was set by a
PC-relative load within the previous 8 instructions is annotated with the
target (`; -> 0x060bxxxx`), so xref finds indirect calls too.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

EXTRACTED = os.path.join(ROOT, "discs", "extracted_saturn")
BASES = {"MAIN_L.BIN": 0x060B0000, "A.BIN": 0x06010000, "DSP.EXB": 0}


class Image:
    def __init__(self, path, base):
        self.path = path
        self.name = os.path.basename(path)
        self.base = base
        self.d = open(path, "rb").read()
        self.end = base + len(self.d)
        self._cs = None

    def has(self, addr, n=1):
        return self.base <= addr and addr + n <= self.end

    def foff(self, addr):
        return addr - self.base

    def u8(self, addr):
        return self.d[addr - self.base]

    def u16(self, addr):
        return struct.unpack_from(">H", self.d, addr - self.base)[0]

    def u32(self, addr):
        return struct.unpack_from(">I", self.d, addr - self.base)[0]

    @property
    def cs(self):
        if self._cs is None:
            import capstone
            self._cs = capstone.Cs(capstone.CS_ARCH_SH,
                                   capstone.CS_MODE_SH2 | capstone.CS_MODE_BIG_ENDIAN)
        return self._cs

    def decode(self, addr):
        """Decode one instruction; returns (mnemonic, operands) or ('.word', hex)."""
        ins = next(self.cs.disasm(self.d[addr - self.base:addr - self.base + 2], addr), None)
        if ins is None:
            return ".word", f"0x{self.u16(addr):04x}"
        return ins.mnemonic, ins.op_str

    def dis(self, addr, count=32):
        """Yield (addr, opcode, mnemonic, operands, note) for `count` instructions.

        note: the literal value of a PC-relative load, the resolved target of
        an indirect jsr/jmp, or ''.
        """
        recent = {}       # reg -> value from a recent PC-relative load
        addr &= ~1
        for _ in range(count):
            if not self.has(addr, 2):
                return
            op = self.u16(addr)
            mn, ops = self.decode(addr)
            note = ""
            lit = self.literal(addr, op)
            if lit is not None:
                reg, val = lit
                note = f"=0x{val:08x}" if (op >> 12) == 0xD else f"=0x{val:04x}"
                if (op >> 12) == 0xD and self.has(val) and val & 1 == 0:
                    s = self.ascii_at(val)
                    if s:
                        note += f" '{s}'"
                recent[reg] = (val, addr)
            elif (op & 0xF0FF) in (0x400B, 0x402B):        # jsr @rn / jmp @rn
                n = (op >> 8) & 0xF
                if n in recent and addr - recent[n][1] <= 16:
                    note = f"-> 0x{recent[n][0]:08x}"
            elif (op >> 12) in (0xB, 0xA):                 # bsr / bra
                pass
            # a write to the register invalidates the tracked literal (cheap check)
            if (op >> 12) in (0x6, 0xE, 0x7, 0x9, 0x5, 0xC) and lit is None:
                recent.pop((op >> 8) & 0xF, None)
            yield addr, op, mn, ops, note
            addr += 2

    def literal(self, addr, op=None):
        """(reg, value) for mov.l/mov.w @(disp,PC),Rn at addr, else None."""
        if op is None:
            op = self.u16(addr)
        hi = op >> 12
        if hi == 0xD:        # mov.l @(disp*4 + (PC&~3) + 4), Rn
            src = ((addr + 4) & ~3) + (op & 0xFF) * 4
            if self.has(src, 4):
                return (op >> 8) & 0xF, self.u32(src)
        elif hi == 0x9:      # mov.w @(disp*2 + PC + 4), Rn
            src = addr + 4 + (op & 0xFF) * 2
            if self.has(src, 2):
                return (op >> 8) & 0xF, self.u16(src)
        return None

    def branch_target(self, addr, op=None):
        """Target of bra/bsr/bt/bf/bt.s/bf.s at addr, else None."""
        if op is None:
            op = self.u16(addr)
        hi = op >> 12
        if hi in (0xA, 0xB):
            d = op & 0xFFF
            if d & 0x800:
                d -= 0x1000
            return addr + 4 + d * 2
        if hi == 0x8 and ((op >> 8) & 0xF) in (0x9, 0xB, 0xD, 0xF):
            d = op & 0xFF
            if d & 0x80:
                d -= 0x100
            return addr + 4 + d * 2
        return None

    def ascii_at(self, addr, maxlen=24):
        s = bytearray()
        a = addr
        while self.has(a) and 0x20 <= self.u8(a) < 0x7F and len(s) < maxlen:
            s.append(self.u8(a))
            a += 1
        if len(s) >= 4 and (not self.has(a) or self.u8(a) == 0):
            return s.decode()
        return None

    def fmt(self, addr, op, mn, ops, note):
        line = f"{addr:08x}  {op:04x}  {mn:<8s} {ops}"
        if note:
            line = f"{line:<44s}; {note}"
        return line

    def show(self, addr, count=32, out=sys.stdout):
        for row in self.dis(addr, count):
            print(self.fmt(*row), file=out)

    def func_start(self, addr, limit=0x2000):
        """Walk back to the instruction after the previous `rts` + delay slot."""
        a = addr & ~1
        lo = max(self.base, a - limit)
        while a > lo:
            a -= 2
            if self.u16(a) == 0x000B:          # rts
                return a + 4
        return lo

    def xrefs(self, target):
        """Every place the image mentions `target`: literal-pool words (with the
        loads that read them), direct branches, and the halfword/word itself."""
        hits = []
        # 32-bit words anywhere (4-aligned: literal pools are)
        for off in range(0, len(self.d) - 3, 4):
            if struct.unpack_from(">I", self.d, off)[0] == target:
                pool = self.base + off
                loads = [a for a in self.pool_loaders(pool)]
                hits.append(("pool", pool, loads))
        # direct branches
        for off in range(0, len(self.d) - 1, 2):
            a = self.base + off
            op = struct.unpack_from(">H", self.d, off)[0]
            if self.branch_target(a, op) == target:
                hits.append(("branch", a, []))
        return hits

    def pool_loaders(self, pool):
        """Addresses of mov.l @(disp,PC) that read the word at `pool`."""
        # disp in 0..255 words: the load lies within 1024 bytes before pool
        lo = max(self.base, pool - 1024 - 4)
        for a in range(lo, pool, 2):
            op = self.u16(a)
            if (op >> 12) == 0xD and ((a + 4) & ~3) + (op & 0xFF) * 4 == pool:
                yield a

    def consts(self, value):
        """Literal pool words and `mov #imm` / `add #imm` immediates equal to value."""
        hits = []
        for off in range(0, len(self.d) - 3, 4):
            if struct.unpack_from(">I", self.d, off)[0] == value:
                pool = self.base + off
                hits.append(("pool.l", pool, list(self.pool_loaders(pool))))
        if value < 0x10000:
            for off in range(0, len(self.d) - 1, 2):
                a = self.base + off
                op = self.u16(a)
                if (op >> 12) == 0x9 and self.literal(a, op) and self.literal(a, op)[1] == value:
                    hits.append(("pool.w", a, []))
                if value < 0x100 and (op >> 12) in (0xE, 0x7) and (op & 0xFF) == value:
                    hits.append(("imm", a, []))
        return hits

    def full_listing(self, out_path):
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"; {self.name} at 0x{self.base:08x}..0x{self.end:08x} ({len(self.d)} bytes)\n")
            n = 0
            for row in self.dis(self.base, len(self.d) // 2):
                addr, op = row[0], row[1]
                # mark branch targets and pool words a little
                f.write(f"{n:6d}  {self.fmt(*row)}\n")
                n += 1
        return n


def load(path=None, base=None):
    path = path or os.environ.get("SH2_FILE") or "MAIN_L.BIN"
    if not os.path.isabs(path) and not os.path.exists(path):
        path = os.path.join(EXTRACTED, path)
    if base is None:
        b = os.environ.get("SH2_BASE")
        base = int(b, 16) if b else BASES.get(os.path.basename(path).upper(), 0x060B0000)
    return Image(path, base)


def main(argv):
    path = base = None
    while argv and argv[0].startswith("--"):
        if argv[0] == "--file":
            path = argv[1]
        elif argv[0] == "--base":
            base = int(argv[1], 16)
        argv = argv[2:]
    img = load(path, base)
    cmd = argv[0] if argv else "at"
    if cmd == "at":
        img.show(int(argv[1], 16), int(argv[2]) if len(argv) > 2 else 32)
    elif cmd == "xref":
        t = int(argv[1], 16)
        for kind, a, loads in img.xrefs(t):
            if kind == "pool":
                print(f"pool  {a:08x}  read by " + (", ".join(f"{l:08x} (fn {img.func_start(l):08x})" for l in loads) or "nothing"))
            else:
                mn, ops = img.decode(a)
                print(f"branch {a:08x}  {mn} {ops}   (fn {img.func_start(a):08x})")
    elif cmd == "const":
        v = int(argv[1], 16)
        for kind, a, loads in img.consts(v):
            extra = ", ".join(f"{l:08x}" for l in loads)
            print(f"{kind:6s} {a:08x}  {extra}")
    elif cmd == "func":
        a = int(argv[1], 16)
        print(f"{img.func_start(a):08x}")
    elif cmd == "full":
        out = argv[1] if len(argv) > 1 else os.path.join(WORK, "saturn", f"dis_{img.name.split('.')[0].lower()}.txt")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        n = img.full_listing(out)
        print(f"{n} instructions -> {out}")
    elif cmd == "strings":
        minlen = int(argv[1]) if len(argv) > 1 else 5
        d = img.d
        i = 0
        while i < len(d):
            j = i
            while j < len(d) and 0x20 <= d[j] < 0x7F:
                j += 1
            if j - i >= minlen:
                print(f"{img.base + i:08x}  {d[i:j].decode()}")
            i = j + 1
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
