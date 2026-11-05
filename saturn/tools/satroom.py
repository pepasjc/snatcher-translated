"""Room-script disassembler (DATA.BIN chunks 60..98, the second u16-opcode interpreter).

The room interpreter 0x060B81B0 reads a u16 opcode at the PC, calls
table[op] (0x060E4DF0, 108 words; op < 0 or > 0x6B -> table[0]) with
r4 = PC + 2 and takes r0 as the next PC; 0x00FF ends the run, a non-zero
ctx+0x554 yields (the PC is saved at ctx+0x58C). Every op's argument length
is DERIVED here from its handler: `oplens()` runs a small symbolic SH-2
interpreter over every path of the handler (r4 = the argument pointer,
registers tracked as `arg + k`, argument halfwords, `(hi << 16) | lo` long
targets, the stack frame; a jsr with a known target is followed into the
callee) and collects what r0 holds at each rts:
    arg + k      falls through, the op is k + 2 bytes
    arg - 2      the op repeats (waits) - no length information
    L(k)         jumps to the 32-bit address at argument word k
Variable-length ops (lists) and anything the walker cannot resolve are
listed by `ops`; `OVERRIDE` holds the few decided by hand (with the reason).

Usage (from the repo root):
    python saturn/tools/satroom.py ops                     the derived table
    python saturn/tools/satroom.py dis 60 [start [end]]    linear walk (hex offsets)
    python saturn/tools/satroom.py flow 60                 recursive descent from 0; desync check
Scripts load at 0x002A0000 (addresses in the script are 0x002Axxxx).
`--data PATH` reads another DATA.BIN; `--chunk FILE` a raw chunk file.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import satdata

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

MAIN_BASE = 0x060B0000
OPTAB = 0x060E4DF0
NOPS = 0x6C
BASE = 0x002A0000
END = 0x00FF

_main = None


def main_img():
    global _main
    if _main is None:
        _main = open(satdata.MAIN, "rb").read()
    return _main


def mu16(a):
    return struct.unpack_from(">H", main_img(), a - MAIN_BASE)[0]


def mu32(a):
    return struct.unpack_from(">I", main_img(), a - MAIN_BASE)[0]


def handler(op):
    return mu32(OPTAB + 4 * (op if 0 <= op < NOPS else 0))


# ---------------------------------------------------------------- symbolic SH-2
# values: ('p', k) = arg + k; ('c', v); ('w', k) = u16 at arg + k; ('h', k) = w << 16;
# ('L', k) = (w_k << 16) | w_{k+2}; ('sp', k); None = unknown

def s8(x):
    return x - 256 if x & 0x80 else x


def s12(x):
    return x - 4096 if x & 0x800 else x


def add(v, n):
    if v is None:
        return None
    if v[0] in ('p', 'sp'):
        return (v[0], v[1] + n)
    if v[0] == 'c':
        return ('c', (v[1] + n) & 0xFFFFFFFF)
    return None


def addv(a, b):
    if a is None or b is None:
        return None
    if b[0] == 'c':
        return add(a, b[1] if b[1] < 0x80000000 else b[1] - 0x100000000)
    if a[0] == 'c':
        return addv(b, a)
    return None


class St:
    __slots__ = ("r", "stk", "pr")

    def __init__(self, r=None, stk=None):
        self.r = list(r) if r else [None] * 16
        self.stk = dict(stk) if stk else {}

    def copy(self):
        return St(self.r, self.stk)


def load(st, addr_v, size):
    """A load through a symbolic address."""
    if addr_v is None:
        return None
    if addr_v[0] == 'p' and size == 2:
        return ('w', addr_v[1])
    if addr_v[0] == 'sp' and size == 4:
        return st.stk.get(addr_v[1])
    if addr_v[0] == 'c' and size == 4 and MAIN_BASE <= addr_v[1] < MAIN_BASE + len(main_img()) - 3:
        return None
    return None


def store(st, addr_v, size, val):
    if addr_v is not None and addr_v[0] == 'sp' and size == 4:
        st.stk[addr_v[1]] = val


def step(pc, st, results, depth, trace):
    """Execute from pc on st; append r0 values at rts to results. Paths fork on branches."""
    work = [(pc, st, 0, {})]
    nsteps = 0
    while work:
        pc, st, n, seen = work.pop()
        while True:
            nsteps += 1
            if nsteps > 20000 or n > 600:
                results.append(('?', 'too long'))
                break
            seen[pc] = seen.get(pc, 0) + 1
            if seen[pc] > 3:
                break                                   # a loop: this path adds nothing new
            op = mu16(pc)
            r = st.r
            nn = (op >> 8) & 15
            m = (op >> 4) & 15
            hi = op >> 12
            lo = op & 15
            n += 1

            def delay():
                exec1(pc + 2, mu16(pc + 2), st)

            if op == 0x000B:                               # rts
                delay()
                results.append(st.r[0])
                break
            if hi == 0x4 and (op & 0xFF) in (0x0B, 0x2B):  # jsr / jmp @rn
                tgt = r[nn]
                delay()
                if (op & 0xFF) == 0x2B:
                    if tgt and tgt[0] == 'c':
                        pc = tgt[1]
                        continue
                    results.append(('?', 'jmp unknown'))
                    break
                sub = None
                if tgt and tgt[0] == 'c' and depth < 2:
                    res = []
                    step(tgt[1], St([None] * 4 + st.r[4:8] + [None] * 7 + [('sp', 0)]), res, depth + 1, None)
                    vals = {v for v in res if v is not None and v[0] != '?'}
                    if len(vals) == 1 and all(v is not None for v in res):
                        sub = vals.pop()
                for i in range(8):
                    st.r[i] = None
                st.r[0] = sub
                pc += 4
                continue
            if hi == 0xA or hi == 0xB:                     # bra / bsr
                tgt = pc + 4 + 2 * s12(op & 0xFFF)
                delay()
                if hi == 0xB:
                    for i in range(8):
                        st.r[i] = None
                    pc += 4
                    continue
                pc = tgt
                continue
            if hi == 0x8 and nn in (0x9, 0xB, 0xD, 0xF):   # bt bf bt/s bf/s
                tgt = pc + 4 + 2 * s8(op & 0xFF)
                if nn in (0xD, 0xF):
                    delay()
                    work.append((tgt, st.copy(), n, dict(seen)))
                    pc += 4
                else:
                    work.append((tgt, st.copy(), n, dict(seen)))
                    pc += 2
                continue
            if op == 0x0023 or (op & 0xF0FF) in (0x0023, 0x0003):   # braf/bsrf
                results.append(('?', 'braf'))
                break
            exec1(pc, op, st)
            pc += 2
    return results


def exec1(pc, op, st):
    r = st.r
    n = (op >> 8) & 15
    m = (op >> 4) & 15
    hi = op >> 12
    lo = op & 15
    if hi == 0xE:
        r[n] = ('c', s8(op & 0xFF) & 0xFFFFFFFF)
    elif hi == 0x9:
        a = pc + 4 + 2 * (op & 0xFF)
        v = mu16(a)
        r[n] = ('c', (v - 0x10000 if v & 0x8000 else v) & 0xFFFFFFFF)
    elif hi == 0xD:
        a = (pc & ~3) + 4 + 4 * (op & 0xFF)
        r[n] = ('c', mu32(a))
    elif hi == 0x7:
        r[n] = add(r[n], s8(op & 0xFF))
    elif hi == 0x6:
        if lo == 3:
            r[n] = r[m]
        elif lo in (0, 1, 2, 4, 5, 6):
            size = (1, 2, 4)[lo % 4 if lo < 3 else lo - 4]
            v = load(st, r[m], size)
            if lo >= 4 and n != m:
                r[m] = add(r[m], size)
            r[n] = v
        elif lo in (0xC,):
            r[n] = None if r[m] is None or r[m][0] not in ('c',) else ('c', r[m][1] & 0xFF)
        elif lo == 0xD:
            v = r[m]
            r[n] = v if v and v[0] == 'w' else (('c', v[1] & 0xFFFF) if v and v[0] == 'c' else None)
        elif lo == 0xF:
            v = r[m]
            r[n] = v if v and v[0] == 'w' else None
        else:
            r[n] = None
    elif hi == 0x3:
        if lo == 0xC:
            r[n] = addv(r[n], r[m])
        elif lo == 0x8:
            b = r[m]
            r[n] = add(r[n], -(b[1] if b[1] < 0x80000000 else b[1] - 0x100000000)) if b and b[0] == 'c' else None
        elif lo in (0, 2, 3, 6, 7):
            pass                                            # compares
        else:
            r[n] = None
    elif hi == 0x2:
        if lo in (0, 1, 2):
            store(st, r[n], (1, 2, 4)[lo], r[m])
        elif lo in (4, 5, 6):
            size = (1, 2, 4)[lo - 4]
            r[n] = add(r[n], -size)
            store(st, r[n], size, r[m])
        elif lo == 8:
            pass
        elif lo == 0xB:
            a, b = r[n], r[m]
            if a and b and a[0] == 'h' and b[0] == 'w' and b[1] == a[1] + 2:
                r[n] = ('L', a[1])
            elif a and b and b[0] == 'h' and a[0] == 'w' and a[1] == b[1] + 2:
                r[n] = ('L', b[1])
            elif a and b and a[0] == 'c' and b[0] == 'c':
                r[n] = ('c', a[1] | b[1])
            else:
                r[n] = None
        else:
            r[n] = None
    elif hi == 0x4:
        low8 = op & 0xFF
        if low8 == 0x28:
            v = r[n]
            r[n] = ('h', v[1]) if v and v[0] == 'w' else (('c', (v[1] << 16) & 0xFFFFFFFF) if v and v[0] == 'c' else None)
        elif low8 == 0x26:
            r[n] = add(r[n], 4)                              # lds.l @rn+,pr
        elif low8 == 0x22:
            r[n] = add(r[n], -4)
        elif low8 in (0x11, 0x15, 0x10) and low8 != 0x10:
            pass
        elif low8 in (0x0E, 0x1E, 0x2E, 0x06, 0x16, 0x07, 0x17, 0x0A, 0x1A, 0x2A):
            if low8 in (0x06, 0x16, 0x07, 0x17):
                r[n] = add(r[n], 4)
        else:
            r[n] = None
    elif hi == 0x5:
        v = load(st, add(r[m], 4 * lo), 4)
        r[n] = v
    elif hi == 0x1:
        store(st, add(r[n], 4 * lo), 4, r[m])
    elif hi == 0x0:
        if lo == 0xC or lo == 0xD or lo == 0xE:
            size = {0xC: 1, 0xD: 2, 0xE: 4}[lo]
            r[n] = load(st, addv(r[m], r[0]), size)
        elif lo in (4, 5, 6):
            store(st, addv(r[n], r[0]), (1, 2, 4)[lo - 4], r[m])
        elif op in (0x0009, 0x0008, 0x0018, 0x0019, 0x0028, 0x002B, 0x0048):
            pass
        elif (op & 0xFF) in (0x02, 0x12, 0x22, 0x0A, 0x1A, 0x2A, 0x29, 0x07, 0x0F):
            if (op & 0xFF) != 0x07:
                r[n] = None
        else:
            pass
    elif hi == 0x8:
        sub = n
        if sub in (4, 5):
            r[0] = load(st, add(r[m], (op & 15) * (1 if sub == 4 else 2)), 1 if sub == 4 else 2)
        elif sub in (0, 1):
            pass
        elif sub == 8:
            pass
    elif hi == 0xC:
        sub = n
        if sub in (4, 5, 6, 7, 9, 0xB, 0xA, 0xD, 0xE, 0xF):
            if sub in (9, 0xB, 0xA):
                v = r[0]
                imm = op & 0xFF
                if v and v[0] == 'c':
                    r[0] = ('c', v[1] & imm if sub == 9 else (v[1] | imm if sub == 0xB else v[1] ^ imm))
                else:
                    r[0] = None
            elif sub in (4, 5, 6, 7):
                r[0] = None
    elif hi == 0xF:
        pass


def analyse(op):
    res = []
    st = St()
    st.r[4] = ('p', 0)
    st.r[15] = ('sp', 0)
    step(handler(op), st, res, 0, None)
    return res


def classify(res):
    """-> (length or None, flags) from the r0 values at the handler's returns."""
    falls, jumps, other, rep = set(), set(), [], False
    for v in res:
        if v is None:
            other.append('unknown')
        elif v[0] == 'p':
            if v[1] == -2:
                rep = True
            else:
                falls.add(v[1] + 2)
        elif v[0] == 'L':
            jumps.add(v[1])
        else:
            other.append(str(v))
    return falls, jumps, rep, other


# Decided by hand where the walker cannot resolve the handler (reason).
OVERRIDE = {
    0x00: {"len": 2, "stop": True, "note": "  (halt: sets 0x060F2A06 and returns arg-2 - repeats for ever)"},
    0x29: {"len": 2, "stop": True, "note": "  (return: pops the call stack ctx+0x594[--0x060F2A0C])"},
    0x3c: {"call": True, "note": "  (call: pushes arg+6 on ctx+0x594[0x060F2A0C++], jumps to L(2))"},
    0x45: {"len": 2, "stop": True, "note": "  (waits for ever: pad poll 0x060B2228, returns arg-2)"},
    0x34: {"note": "  (empty handler, r0 not set: never used)"},
    0x35: {"note": "  (empty handler, r0 not set: never used)"},
}


# What the ops seen on the title / option screens do (read from their handlers; a = arguments).
NAMES = {
    0x00: "halt", 0x05: "sprite obj 12+a0 := anim a1 (a2 prio band: obj+4 = 16*a2+16; a3 -> obj+1; a4 -> obj+3; a5,a6) via 0x060B5428",
    0x08: "?", 0x09: "wait/tick a0 frames (0x060F2A04 := a0)", 0x0D: "jump", 0x0E: "?",
    0x0F: "load chunk a0 into container slot a1 (loader 0x060B2624; slot k decodes below 0x26048000 + 0x40000*k)",
    0x10: "wait until the load is done", 0x13: "hide obj 12+a0 (type byte := 0)",
    0x15: "palette: slot a0 type-1 section a1 -> CRAM work ptr 0x060E4C78[a2] (+a3 colours, a4 colours; 0 = whole section)",
    0x16: "background: slot a0 type-0 section a1 -> VDP2 VRAM 0x060E4C48[a2] (8 = 0x25E22000, NBG1)",
    0x17: "sprites: slot a0 type-3 section a1 -> VDP1 VRAM 0x060E4C24[a2] (0x80 = running pointer 0x060EF484)",
    0x18: "sprite index: slot a0 type-2 section a1 -> index set 0x060E4C00[a2] (copied + relocated)",
    0x1B: "polygon (0x060B56A0): a0 mode, a1 colour, 4 x (x, y), 4 Gouraud colours",
    0x1C: "obj 12+a0 position := (a1, a2) + scroll (ctx+0x274/0x278)",
    0x1D: "fade record a0 (0x060E5A8C + 8*a0) source := CRAM work ptr 0x060E4C78[a1] (a2)",
    0x1E: "set bit 15 on colours a1..a2 of CRAM work ptr a0",
    0x29: "return", 0x2F: "sound effect a0", 0x32: "?", 0x33: "obj 12+a0 motion: a1 frames, a2..a5 (dy per frame = a4)",
    0x39: "?", 0x3C: "call", 0x47: "?", 0x4A: "?",
    0x50: "flag a0 := 0 (ctx+0x5DA + a0)", 0x51: "flag a0 := 1", 0x52: "clear flags 0..31",
    0x53: "if flag a0: jump", 0x54: "if not flag a0: jump", 0x55: "if flag a0: call", 0x56: "if not flag a0: call",
    0x59: "if voice id [0x060F2A10] == a0: jump", 0x67: "jump", 0x68: "?", 0x69: "?",
}

_TABLE = None


def optable():
    """op -> dict(len, jumps (arg word offsets holding a 32-bit target), repeat, note)."""
    global _TABLE
    if _TABLE is not None:
        return _TABLE
    t = {}
    for op in range(NOPS):
        falls, jumps, rep, other = classify(analyse(op))
        e = {"h": handler(op), "falls": sorted(falls), "jumps": sorted(jumps), "repeat": rep,
             "other": sorted(set(other))}
        if len(falls) == 1:
            e["len"] = next(iter(falls))
        elif jumps and not falls:
            e["len"] = max(jumps) + 6                      # an unconditional jump: its argument
        if op in OVERRIDE:
            e.update(OVERRIDE[op])
        if e.get("call"):
            e["len"] = 8
        t[op] = e
    _TABLE = t
    return t


def cmd_ops():
    for op, e in optable().items():
        flag = "" if "len" in e and not e["other"] else "   <-- " + ("no length" if "len" not in e else "partial")
        print(f"{op:02x}  {e['h']:08x}  len={e.get('len', '?')!s:>3}  falls={e['falls']} "
              f"jumps={e['jumps']} rep={int(e['repeat'])} other={e['other']}{e.get('note', '')}{flag}")


# ---------------------------------------------------------------- room scripts

def chunk(n, data=None):
    ents = satdata.read_table()
    d = open(data or satdata.DATA, "rb").read()
    return satdata.entry(d, ents, n)


def u16(d, o):
    return struct.unpack_from(">H", d, o)[0]


def decode(d, o):
    """-> (op, length, [args], [jump target offsets]) or None when unknown."""
    if o + 2 > len(d):
        return None
    op = u16(d, o)
    e = optable().get(op)
    if op == END:
        return op, 2, [], []
    if e is None or "len" not in e:
        return None
    ln = e["len"]
    if o + ln > len(d):
        return None
    args = [u16(d, o + 2 + 2 * i) for i in range((ln - 2) // 2)]
    tg = []
    for k in e["jumps"]:
        a = (u16(d, o + 2 + k) << 16) | u16(d, o + 4 + k)
        tg.append(a - BASE)
    return op, ln, args, tg


def fmt(d, o, dec):
    op, ln, args, tg = dec
    s = f"{o:05x}  {op:02x}  " + " ".join(f"{a:04x}" for a in args)
    if tg:
        s += "   -> " + ", ".join(f"{t:05x}" for t in tg)
    nm = NAMES.get(op, "")
    if nm and nm != "?":
        s = f"{s:<78} ; {nm.split(' (')[0] if len(nm) > 60 else nm}"
    return s


def cmd_dis(d, start=0, end=None):
    end = len(d) if end is None else end
    o = start
    while o < end:
        dec = decode(d, o)
        if dec is None:
            print(f"{o:05x}  ??  {u16(d, o):04x}   (unknown op - stopping)")
            return
        print(fmt(d, o, dec))
        o += dec[1]


def flow(d, entries=(0,)):
    """Recursive descent: -> (ops {off: dec}, problems)."""
    seen, probs, todo = {}, [], list(entries)
    uncond = {op for op, e in optable().items()
              if (e["jumps"] and not e["falls"] and not e.get("call")) or e.get("stop")}
    while todo:
        o = todo.pop()
        while True:
            if o in seen:
                break
            if not (0 <= o < len(d)):
                probs.append(f"target {o:x} outside the chunk")
                break
            dec = decode(d, o)
            if dec is None:
                probs.append(f"{o:05x}: unknown op {u16(d, o):04x}")
                break
            seen[o] = dec
            op, ln, args, tg = dec
            todo += [t for t in tg if 0 <= t < len(d) and t not in seen]
            probs += [f"{o:05x}: target {t:x} outside" for t in tg if not 0 <= t < len(d)]
            if op == END or op in uncond:
                break
            o += ln
    # overlap check: no walked op may start inside another
    starts = sorted(seen)
    for a, b in zip(starts, starts[1:]):
        if a + seen[a][1] > b:
            probs.append(f"overlap: {a:05x} (len {seen[a][1]}) runs into {b:05x}")
    return seen, probs


def cmd_flow(d):
    seen, probs = flow(d)
    cov = sum(v[1] for v in seen.values())
    ops = sorted({v[0] for v in seen.values()})
    print(f"{len(seen)} ops reached from 0, {cov} of {len(d)} bytes; ops used: " + " ".join(f"{x:02x}" for x in ops))
    # gaps
    starts = sorted(seen)
    gaps, pos = [], 0
    for s in starts:
        if s > pos:
            gaps.append((pos, s))
        pos = max(pos, s + seen[s][1])
    if pos < len(d):
        gaps.append((pos, len(d)))
    print("unreached ranges: " + ", ".join(f"{a:x}..{b:x}" for a, b in gaps))
    print("problems:", probs or "none")


def main(argv):
    data = None
    if "--data" in argv:
        i = argv.index("--data"); data = argv[i + 1]; del argv[i:i + 2]
    raw = None
    if "--chunk" in argv:
        i = argv.index("--chunk"); raw = open(argv[i + 1], "rb").read(); del argv[i:i + 2]
    if not argv or argv[0] == "ops":
        return cmd_ops()
    d = raw if raw is not None else chunk(int(argv[1]), data)
    if argv[0] == "dis":
        s = int(argv[2], 16) if len(argv) > 2 else 0
        e = int(argv[3], 16) if len(argv) > 3 else None
        return cmd_dis(d, s, e)
    if argv[0] == "flow":
        return cmd_flow(d)
    print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
