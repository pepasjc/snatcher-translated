"""Subtitle prototype v0: inject a flat red rectangle into the engine's OT
every frame, from a stub hooked into the per-frame service chain.

Proves: hook site runs per frame, OT insertion works, prim survives to the
GPU. No text, no texture yet.

  python ps1/subs/proto_sub.py         # patch patched/SLPS_001.54 in place

Layout:
  stub        0x8009D190 (256-byte zero region, zero across 5 savestates)
  prim bufs   0x800A4100 (free BSS, zero across savestates; 2 x 16 bytes,
              alternating on the double-buffer index at ctx+0x7A78)
  hook        0x8002AAD8: jal 0x8002E1CC -> jal stub (stub calls it first)

OT facts (savestate-verified): 16-entry table at ctx+0x7AAC / +0x7AEC,
current build target pointer at [0x800AEEA0]; entries are next|len<<24
words, bucket nodes have len 0.
"""
import os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

EXE = os.path.join(ROOT, "patched", "SLPS_001.54")

TEXT = 0x80028000
HDR = 0x800

STUB_RAM = 0x8009D190
STUB_LEN = 0x100
PRIM_RAM = 0x800A4100
HOOK_RAM = 0x8002AAD8
HOOK_OLD = 0x0C00B873          # jal 0x8002E1CC
ORIG_CALLEE = 0x8002E1CC

CTX_PTR_HI, CTX_PTR_LO = 0x800B, 0xBF64      # [0x800ABF64]
OT_PTR_HI, OT_PTR_LO = 0x800B, 0xEEA0        # [0x800AEEA0]
BUCKET = 1                                    # OT entry index to hook

REG = {f"$t{i}": 8 + i for i in range(8)}
REG.update({"$zero": 0, "$at": 1, "$v0": 2, "$v1": 3, "$a0": 4, "$a1": 5,
            "$a2": 6, "$a3": 7, "$s0": 16, "$s1": 17, "$s2": 18, "$ra": 31,
            "$sp": 29})


def asm(prog, org):
    labels, pc = {}, org
    for ins in prog:
        if ins[0] == "label":
            labels[ins[1]] = pc
        else:
            pc += 4
    out, pc = bytearray(), org
    for ins in prog:
        op = ins[0]
        if op == "label":
            continue
        if op == "lui":
            w = 0x3C000000 | REG[ins[1]] << 16 | (ins[2] & 0xFFFF)
        elif op == "ori":
            w = 0x34000000 | REG[ins[2]] << 21 | REG[ins[1]] << 16 | (ins[3] & 0xFFFF)
        elif op == "addiu":
            w = 0x24000000 | REG[ins[2]] << 21 | REG[ins[1]] << 16 | (ins[3] & 0xFFFF)
        elif op == "lw":
            w = 0x8C000000 | REG[ins[3]] << 21 | REG[ins[1]] << 16 | (ins[2] & 0xFFFF)
        elif op == "sw":
            w = 0xAC000000 | REG[ins[3]] << 21 | REG[ins[1]] << 16 | (ins[2] & 0xFFFF)
        elif op == "sll":
            w = REG[ins[2]] << 16 | REG[ins[1]] << 11 | (ins[3] & 0x1F) << 6
        elif op == "and":
            w = 0x24 | REG[ins[2]] << 21 | REG[ins[3]] << 16 | REG[ins[1]] << 11
        elif op == "or":
            w = 0x25 | REG[ins[2]] << 21 | REG[ins[3]] << 16 | REG[ins[1]] << 11
        elif op == "addu":
            w = 0x21 | REG[ins[2]] << 21 | REG[ins[3]] << 16 | REG[ins[1]] << 11
        elif op == "jal":
            w = 0x0C000000 | ((ins[1] >> 2) & 0x03FFFFFF)
        elif op in ("beq", "bne"):
            rel = (labels[ins[3]] - (pc + 4)) >> 2
            w = (0x10000000 if op == "beq" else 0x14000000) \
                | REG[ins[1]] << 21 | REG[ins[2]] << 16 | (rel & 0xFFFF)
        elif op == "jr":
            w = 0x08 | REG[ins[1]] << 21
        elif op == "nop":
            w = 0
        else:
            raise ValueError(op)
        out += struct.pack("<I", w)
        pc += 4
    return bytes(out)


def li(reg, val):
    hi = (val >> 16) & 0xFFFF
    lo = val & 0xFFFF
    if hi:
        if lo:
            return [("lui", reg, hi), ("ori", reg, reg, lo)]
        return [("lui", reg, hi)]
    return [("ori", reg, "$zero", lo)]


def stub_program(y, x, h, w, color):
    p = [
        ("addiu", "$sp", "$sp", -0x18),
        ("sw", "$ra", 0x14, "$sp"),
        ("jal", ORIG_CALLEE),
        ("nop",),
        # guards: ctx and OT pointers must be initialized
        ("lui", "$t0", CTX_PTR_HI),
        ("lw", "$t0", CTX_PTR_LO, "$t0"),
        ("beq", "$t0", "$zero", "out"),
        ("nop",),
        ("lui", "$t4", OT_PTR_HI),
        ("lw", "$t4", OT_PTR_LO, "$t4"),
        ("beq", "$t4", "$zero", "out"),
        ("nop",),
        # P = PRIM_RAM + bufidx*16
        ("lw", "$t1", 0x7A78, "$t0"),
        ("sll", "$t1", "$t1", 4),
    ]
    p += li("$t2", PRIM_RAM)
    p += [("addu", "$t2", "$t2", "$t1")]
    p += li("$t3", 0x60000000 | color)          # TILE cmd | BGR
    p += [("sw", "$t3", 4, "$t2")]
    p += li("$t3", (y << 16) | x)
    p += [("sw", "$t3", 8, "$t2")]
    p += li("$t3", (h << 16) | w)
    p += [("sw", "$t3", 12, "$t2")]
    p += [
        ("lw", "$t5", BUCKET * 4, "$t4"),
        ("lui", "$t6", 0x00FF),
        ("ori", "$t6", "$t6", 0xFFFF),
        ("and", "$t5", "$t5", "$t6"),           # old next
        ("lui", "$t7", 0x0300),                 # len 3
        ("or", "$t5", "$t5", "$t7"),
        ("sw", "$t5", 0, "$t2"),                # prim header
        ("and", "$t3", "$t2", "$t6"),
        ("sw", "$t3", BUCKET * 4, "$t4"),       # bucket -> prim
        ("label", "out"),
        ("lw", "$ra", 0x14, "$sp"),
        ("jr", "$ra"),
        ("addiu", "$sp", "$sp", 0x18),
    ]
    return p


def fo(ram):
    return ram - TEXT + HDR


def main():
    exe = bytearray(open(EXE, "rb").read())
    old = struct.unpack_from("<I", exe, fo(HOOK_RAM))[0]
    if old not in (HOOK_OLD, 0x0C000000 | ((STUB_RAM >> 2) & 0x03FFFFFF)):
        raise SystemExit(f"hook site holds {old:#010x}, expected {HOOK_OLD:#010x}")
    code = asm(stub_program(y=200, x=40, h=20, w=240, color=0x0000FF), STUB_RAM)
    assert len(code) <= STUB_LEN, len(code)
    exe[fo(STUB_RAM):fo(STUB_RAM) + len(code)] = code
    struct.pack_into("<I", exe, fo(HOOK_RAM),
                     0x0C000000 | ((STUB_RAM >> 2) & 0x03FFFFFF))
    open(EXE, "wb").write(exe)
    print(f"stub {len(code)}B at {STUB_RAM:#x}, hook at {HOOK_RAM:#x} patched")


if __name__ == "__main__":
    main()
