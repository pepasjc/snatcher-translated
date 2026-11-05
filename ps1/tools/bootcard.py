"""A translation card drawn by code, first thing after the BIOS.

The old card was baked into the Konami boot movie and hung the BIOS memory
card poll on RetroArch (BUG-033). This one never touches a movie: the exec
grows by a small stub and a 1-bpp bitmap of the card, the PS-EXE header's
entry point is redirected to the stub, and the stub

  1. resets the GPU (GP1) and sets 320x240 NTSC 15-bit,
  2. uploads the card to VRAM with one CPU->VRAM transfer (GP0 A0),
     expanding the bitmap two pixels per word (no per-word flow control:
     a CPU store cannot outrun the transfer),
  3. enables the display and holds on timer 1 counting h-blanks (HOLD_S
     seconds at 15.7 kHz), then
  4. jumps to ps1/tools/bootsplash.py's player (the Snatcher and the
     disclaimer), appended after the resident payloads, which ends at the
     original entry point.

The grown exec no longer fits its 242 sectors (the three that follow hold
data), so it is relocated past the image end like the banks and the blobs:
`work/relocations.json` gets an SLPS_001.54 entry, patch_disc writes the
sectors there and repoints the ISO9660 directory record (LBA and size),
which is what the BIOS - and DuckStation's fast boot - read. The BIOS loads
`t_size` bytes from the header, raised to cover the tail. The tail lands in
the game's BSS (0x800A0800..), which the entry code itself clears
(0x80029a38 zeroes 0x800A00A4..0x800B063C), so nothing survives the jump -
which is why the stub's first job is to copy the resident payloads that
must (ps1/tools/wordwrap.py's stub, 4 KB after the card) into high RAM at
0x801FE000 before anything else runs.

Runs after every other exec patch (subs_cue rewrites the shared exec) and
before patch_disc:

  python ps1/tools/bootcard.py apply      # patched/SLPS_001.54 + relocation entry
  python ps1/tools/bootcard.py preview    # work/bootcard_preview.png
"""
import json, os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

from mipsasm import Asm

EXE = os.path.join(ROOT, "patched", "SLPS_001.54")
SRC_IMG = os.path.join(ROOT, "discs/iso_ps1_jp", "Snatcher (Japan).bin")
RELOC = os.path.join(ROOT, "work", "relocations.json")
NAME = "SLPS_001.54"

EXEC_RAM, HDR = 0x80028000, 0x800
W, H = 320, 240
HOLD_S = 3.0
ROUNDS = 2                               # timer rounds; each under 32768 h-blanks
HBLANKS = int(HOLD_S / ROUNDS * 15734)   # NTSC line rate
assert HBLANKS < 0x8000
IO = 0x1F80                              # lui half of the I/O page


def card_bits():
    """The card as 1 bpp rows, MSB first, 1 = ink. Reuses splash.card()."""
    from splash import card
    im = card().convert("L")
    assert im.size == (W, H)
    px = im.load()
    out = bytearray()
    for y in range(H):
        acc = 0
        for x in range(W):
            acc = (acc << 1) | (1 if px[x, y] < 128 else 0)
            if x % 8 == 7:
                out.append(acc)
                acc = 0
    return bytes(out)


def stub(org, next_pc, data_at, data_len, residents=()):
    a = Asm(org)
    # resident payloads first: word copies from the exec tail into high RAM
    # (wordwrap.py's stub at 0x801FE000), before the BSS clear wipes the tail
    for src, dst, n in residents:
        a.lui("$t2", src >> 16)
        a.ori("$t2", "$t2", src & 0xFFFF)
        a.addiu("$t3", "$t2", n)
        a.lui("$t4", dst >> 16)
        a.ori("$t4", "$t4", dst & 0xFFFF)
        a.label(f"copy{dst:x}")
        a.lw("$t5", 0, "$t2")
        a.addiu("$t2", "$t2", 4)
        a.sw("$t5", 0, "$t4")
        a.bne("$t2", "$t3", f"copy{dst:x}")
        a.addiu("$t4", "$t4", 4)
    a.lui("$t0", IO)
    # GP1: reset, 320x240 NTSC 15-bit, display start 0, h/v ranges
    a.sw("$zero", 0x1814, "$t0")
    for hi, lo in ((0x0800, 0x0001), (0x0500, 0x0000), (0x06C6, 0x0260),
                   (0x0704, 0x0010)):
        a.lui("$t1", hi)
        a.ori("$t1", "$t1", lo)
        a.sw("$t1", 0x1814, "$t0")
    a.label("ready")                     # GPUSTAT bit 28: ready for a command
    a.lw("$t9", 0x1814, "$t0")
    a.nop()
    a.srl("$t9", "$t9", 28)
    a.andi("$t9", "$t9", 1)
    a.beq("$t9", "$zero", "ready")
    a.nop()
    # GP0: CPU->VRAM rectangle (0,0) 320x240. No flow control on the pixel
    # words: a CPU store cannot outrun an A0 transfer, and GPUSTAT bit 25
    # (FIFO state) never read 1 under Beetle - the first build spun on it.
    a.lui("$t1", 0xA000)
    a.sw("$t1", 0x1810, "$t0")
    a.sw("$zero", 0x1810, "$t0")
    a.lui("$t1", H)
    a.ori("$t1", "$t1", W)
    a.sw("$t1", 0x1810, "$t0")
    a.lui("$t2", data_at >> 16)
    a.ori("$t2", "$t2", data_at & 0xFFFF)
    a.addiu("$t3", "$t2", data_len)
    a.label("byte")
    a.lbu("$t4", 0, "$t2")
    a.nop()
    a.ori("$t5", "$zero", 4)             # four words (eight pixels) per byte
    a.label("word")
    a.andi("$t6", "$t4", 0x80)           # pixel 0 = bit 7: ink -> 0, else white
    a.sltiu("$t6", "$t6", 1)
    a.sll("$t7", "$t6", 15)
    a.subu("$t6", "$t7", "$t6")          # 1 -> 0x7FFF, 0 -> 0
    a.andi("$t7", "$t4", 0x40)           # pixel 1 = bit 6, into the high half
    a.sltiu("$t7", "$t7", 1)
    a.sll("$t8", "$t7", 15)
    a.subu("$t7", "$t8", "$t7")
    a.sll("$t7", "$t7", 16)
    a.or_("$t6", "$t6", "$t7")
    a.sw("$t6", 0x1810, "$t0")
    a.sll("$t4", "$t4", 2)
    a.addiu("$t5", "$t5", -1)
    a.bne("$t5", "$zero", "word")
    a.nop()
    a.addiu("$t2", "$t2", 1)
    a.bne("$t2", "$t3", "byte")
    a.nop()
    # display on, then hold on timer 1 counting h-blanks
    a.lui("$t1", 0x0300)
    a.sw("$t1", 0x1814, "$t0")
    a.ori("$t8", "$zero", ROUNDS)
    a.label("round")
    a.ori("$t1", "$zero", 0x0100)        # timer 1 mode: source = h-blank (resets count)
    a.sw("$t1", 0x1114, "$t0")
    a.label("hold")
    a.lhu("$t9", 0x1110, "$t0")
    a.nop()
    a.sltiu("$t9", "$t9", HBLANKS)       # sltiu sign-extends: keep this under 32768
    a.bne("$t9", "$zero", "hold")
    a.nop()
    a.addiu("$t8", "$t8", -1)
    a.bne("$t8", "$zero", "round")
    a.nop()
    a.j(next_pc)                         # bootsplash.py's player; it jumps to the entry
    a.nop()
    return a.assemble()


def next_free_lba():
    lba = os.path.getsize(SRC_IMG) // 2352
    rel = json.load(open(RELOC)) if os.path.exists(RELOC) else {}
    for fname, start in rel.items():
        size = os.path.getsize(os.path.join(ROOT, "patched", fname))
        lba = max(lba, start + (size + 2047) // 2048)
    return lba


def apply():
    exe = bytearray(open(EXE, "rb").read())
    pc, t_addr, t_size = struct.unpack_from("<I", exe, 0x10)[0], *struct.unpack_from("<II", exe, 0x18)
    assert t_addr == EXEC_RAM and len(exe) == HDR + t_size, "exec already grown?"
    assert pc == 0x80029A28, f"entry {pc:#x} is not the original - bootcard applied twice?"
    org = EXEC_RAM + t_size
    bits = card_bits()
    import wordwrap, bootsplash
    res = wordwrap.resident()
    res += b"\0" * (-len(res) % 4)
    bits += b"\0" * (-len(bits) % 4)
    res_at = org + 0x200 + len(bits)
    splash_at = res_at + len(res)
    splash = bootsplash.build(splash_at, pc)
    code = stub(org, splash_at, org + 0x200, len(bits), [(res_at, wordwrap.RESIDENT, len(res))])
    assert len(code) <= 0x200
    tail = code + b"\0" * (0x200 - len(code)) + bits + res + splash
    tail += b"\0" * (-len(tail) % 2048)
    exe += tail
    struct.pack_into("<I", exe, 0x10, org)
    struct.pack_into("<I", exe, 0x1C, t_size + len(tail))
    open(EXE, "wb").write(exe)
    rel = json.load(open(RELOC)) if os.path.exists(RELOC) else {}
    rel.pop(NAME, None)
    rel[NAME] = next_free_lba()
    json.dump(rel, open(RELOC, "w"), indent=1)
    print(f"{NAME}: +{len(tail)} bytes, stub at {org:#x} ({len(code)} B), card {len(bits)} B, "
          f"wordwrap resident {len(res)} B at {res_at:#x} -> {wordwrap.RESIDENT:#x}, "
          f"splash {len(splash)} B at {splash_at:#x}, entry {pc:#x} -> {org:#x}; relocated to LBA {rel[NAME]} ({len(exe) // 2048} sectors)")


def preview():
    from PIL import Image
    bits = card_bits()
    im = Image.frombytes("1", (W, H), bytes(b ^ 0xFF for b in bits))
    im.save(os.path.join(ROOT, "work", "bootcard_preview.png"))
    print("work/bootcard_preview.png")


if __name__ == "__main__":
    {"apply": apply, "preview": preview}[sys.argv[1]]()
