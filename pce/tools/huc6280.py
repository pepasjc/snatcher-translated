"""HuC6280 disassembler (6502 + 65C02 + Hudson extensions) for the PCE loader.

Addressing-mode lengths:
  imp/acc 1, imm/zp/zpx/zpy/zpi/zpxi/zpiy/rel 2, abs/absx/absy/absi/absxi/zprel
  3, tst: immzp 3, immzpx 3, immabs 4, immabsx 4, blk (TII etc) 7.

The System Card CD-ROM BIOS is reached through the jump table at $E000
(`JSR $E009` = CD_READ and so on); NAMES labels those calls so a listing of
the loader reads at a glance. Zero-page $F8-$FF are the BIOS argument bytes
_al _ah _bl _bh _cl _ch _dl _dh.

Usage:
  python pce/tools/huc6280.py <file> <base_hex> [start_hex] [count]
"""
import sys

# fmt: off
OPS = {
 0x00:("BRK","imp"),0x01:("ORA","zpxi"),0x02:("SXY","imp"),0x03:("ST0","imm"),0x04:("TSB","zp"),0x05:("ORA","zp"),0x06:("ASL","zp"),0x07:("RMB0","zp"),
 0x08:("PHP","imp"),0x09:("ORA","imm"),0x0A:("ASL","acc"),0x0B:("NOP","imp"),0x0C:("TSB","abs"),0x0D:("ORA","abs"),0x0E:("ASL","abs"),0x0F:("BBR0","zprel"),
 0x10:("BPL","rel"),0x11:("ORA","zpiy"),0x12:("ORA","zpi"),0x13:("ST1","imm"),0x14:("TRB","zp"),0x15:("ORA","zpx"),0x16:("ASL","zpx"),0x17:("RMB1","zp"),
 0x18:("CLC","imp"),0x19:("ORA","absy"),0x1A:("INC","acc"),0x1B:("NOP","imp"),0x1C:("TRB","abs"),0x1D:("ORA","absx"),0x1E:("ASL","absx"),0x1F:("BBR1","zprel"),
 0x20:("JSR","abs"),0x21:("AND","zpxi"),0x22:("SAX","imp"),0x23:("ST2","imm"),0x24:("BIT","zp"),0x25:("AND","zp"),0x26:("ROL","zp"),0x27:("RMB2","zp"),
 0x28:("PLP","imp"),0x29:("AND","imm"),0x2A:("ROL","acc"),0x2B:("NOP","imp"),0x2C:("BIT","abs"),0x2D:("AND","abs"),0x2E:("ROL","abs"),0x2F:("BBR2","zprel"),
 0x30:("BMI","rel"),0x31:("AND","zpiy"),0x32:("AND","zpi"),0x33:("NOP","imp"),0x34:("BIT","zpx"),0x35:("AND","zpx"),0x36:("ROL","zpx"),0x37:("RMB3","zp"),
 0x38:("SEC","imp"),0x39:("AND","absy"),0x3A:("DEC","acc"),0x3B:("NOP","imp"),0x3C:("BIT","absx"),0x3D:("AND","absx"),0x3E:("ROL","absx"),0x3F:("BBR3","zprel"),
 0x40:("RTI","imp"),0x41:("EOR","zpxi"),0x42:("SAY","imp"),0x43:("TMA","imm"),0x44:("BSR","rel"),0x45:("EOR","zp"),0x46:("LSR","zp"),0x47:("RMB4","zp"),
 0x48:("PHA","imp"),0x49:("EOR","imm"),0x4A:("LSR","acc"),0x4B:("NOP","imp"),0x4C:("JMP","abs"),0x4D:("EOR","abs"),0x4E:("LSR","abs"),0x4F:("BBR4","zprel"),
 0x50:("BVC","rel"),0x51:("EOR","zpiy"),0x52:("EOR","zpi"),0x53:("TAM","imm"),0x54:("CSL","imp"),0x55:("EOR","zpx"),0x56:("LSR","zpx"),0x57:("RMB5","zp"),
 0x58:("CLI","imp"),0x59:("EOR","absy"),0x5A:("PHY","imp"),0x5B:("NOP","imp"),0x5C:("NOP","imp"),0x5D:("EOR","absx"),0x5E:("LSR","absx"),0x5F:("BBR5","zprel"),
 0x60:("RTS","imp"),0x61:("ADC","zpxi"),0x62:("CLA","imp"),0x63:("NOP","imp"),0x64:("STZ","zp"),0x65:("ADC","zp"),0x66:("ROR","zp"),0x67:("RMB6","zp"),
 0x68:("PLA","imp"),0x69:("ADC","imm"),0x6A:("ROR","acc"),0x6B:("NOP","imp"),0x6C:("JMP","absi"),0x6D:("ADC","abs"),0x6E:("ROR","abs"),0x6F:("BBR6","zprel"),
 0x70:("BVS","rel"),0x71:("ADC","zpiy"),0x72:("ADC","zpi"),0x73:("TII","blk"),0x74:("STZ","zpx"),0x75:("ADC","zpx"),0x76:("ROR","zpx"),0x77:("RMB7","zp"),
 0x78:("SEI","imp"),0x79:("ADC","absy"),0x7A:("PLY","imp"),0x7B:("NOP","imp"),0x7C:("JMP","absxi"),0x7D:("ADC","absx"),0x7E:("ROR","absx"),0x7F:("BBR7","zprel"),
 0x80:("BRA","rel"),0x81:("STA","zpxi"),0x82:("CLX","imp"),0x83:("TST","immzp"),0x84:("STY","zp"),0x85:("STA","zp"),0x86:("STX","zp"),0x87:("SMB0","zp"),
 0x88:("DEY","imp"),0x89:("BIT","imm"),0x8A:("TXA","imp"),0x8B:("NOP","imp"),0x8C:("STY","abs"),0x8D:("STA","abs"),0x8E:("STX","abs"),0x8F:("BBS0","zprel"),
 0x90:("BCC","rel"),0x91:("STA","zpiy"),0x92:("STA","zpi"),0x93:("TST","immabs"),0x94:("STY","zpx"),0x95:("STA","zpx"),0x96:("STX","zpy"),0x97:("SMB1","zp"),
 0x98:("TYA","imp"),0x99:("STA","absy"),0x9A:("TXS","imp"),0x9B:("NOP","imp"),0x9C:("STZ","abs"),0x9D:("STA","absx"),0x9E:("STZ","absx"),0x9F:("BBS1","zprel"),
 0xA0:("LDY","imm"),0xA1:("LDA","zpxi"),0xA2:("LDX","imm"),0xA3:("TST","immzpx"),0xA4:("LDY","zp"),0xA5:("LDA","zp"),0xA6:("LDX","zp"),0xA7:("SMB2","zp"),
 0xA8:("TAY","imp"),0xA9:("LDA","imm"),0xAA:("TAX","imp"),0xAB:("NOP","imp"),0xAC:("LDY","abs"),0xAD:("LDA","abs"),0xAE:("LDX","abs"),0xAF:("BBS2","zprel"),
 0xB0:("BCS","rel"),0xB1:("LDA","zpiy"),0xB2:("LDA","zpi"),0xB3:("TST","immabsx"),0xB4:("LDY","zpx"),0xB5:("LDA","zpx"),0xB6:("LDX","zpy"),0xB7:("SMB3","zp"),
 0xB8:("CLV","imp"),0xB9:("LDA","absy"),0xBA:("TSX","imp"),0xBB:("NOP","imp"),0xBC:("LDY","absx"),0xBD:("LDA","absx"),0xBE:("LDX","absy"),0xBF:("BBS3","zprel"),
 0xC0:("CPY","imm"),0xC1:("CMP","zpxi"),0xC2:("CLY","imp"),0xC3:("TDD","blk"),0xC4:("CPY","zp"),0xC5:("CMP","zp"),0xC6:("DEC","zp"),0xC7:("SMB4","zp"),
 0xC8:("INY","imp"),0xC9:("CMP","imm"),0xCA:("DEX","imp"),0xCB:("NOP","imp"),0xCC:("CPY","abs"),0xCD:("CMP","abs"),0xCE:("DEC","abs"),0xCF:("BBS4","zprel"),
 0xD0:("BNE","rel"),0xD1:("CMP","zpiy"),0xD2:("CMP","zpi"),0xD3:("TIN","blk"),0xD4:("CSH","imp"),0xD5:("CMP","zpx"),0xD6:("DEC","zpx"),0xD7:("SMB5","zp"),
 0xD8:("CLD","imp"),0xD9:("CMP","absy"),0xDA:("PHX","imp"),0xDB:("NOP","imp"),0xDC:("NOP","imp"),0xDD:("CMP","absx"),0xDE:("DEC","absx"),0xDF:("BBS5","zprel"),
 0xE0:("CPX","imm"),0xE1:("SBC","zpxi"),0xE2:("NOP","imp"),0xE3:("TIA","blk"),0xE4:("CPX","zp"),0xE5:("SBC","zp"),0xE6:("INC","zp"),0xE7:("SMB6","zp"),
 0xE8:("INX","imp"),0xE9:("SBC","imm"),0xEA:("NOP","imp"),0xEB:("NOP","imp"),0xEC:("CPX","abs"),0xED:("SBC","abs"),0xEE:("INC","abs"),0xEF:("BBS6","zprel"),
 0xF0:("BEQ","rel"),0xF1:("SBC","zpiy"),0xF2:("SBC","zpi"),0xF3:("TAI","blk"),0xF4:("SET","imp"),0xF5:("SBC","zpx"),0xF6:("INC","zpx"),0xF7:("SMB7","zp"),
 0xF8:("SED","imp"),0xF9:("SBC","absy"),0xFA:("PLX","imp"),0xFB:("NOP","imp"),0xFC:("NOP","imp"),0xFD:("SBC","absx"),0xFE:("INC","absx"),0xFF:("BBS7","zprel"),
}
# fmt: on
LEN = {"imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "zpi": 2,
       "zpxi": 2, "zpiy": 2, "rel": 2, "abs": 3, "absx": 3, "absy": 3,
       "absi": 3, "absxi": 3, "zprel": 3, "immzp": 3, "immzpx": 3,
       "immabs": 4, "immabsx": 4, "blk": 7}

NAMES = {0xE000: "CD_BOOT", 0xE003: "CD_RESET", 0xE006: "CD_BASE",
         0xE009: "CD_READ", 0xE00C: "CD_SEEK", 0xE00F: "CD_EXEC",
         0xE012: "CD_PLAY", 0xE015: "CD_SEARCH", 0xE018: "CD_PAUSE",
         0xE01B: "CD_STAT", 0xE01E: "CD_SUBQ", 0xE021: "CD_DINFO",
         0xE024: "CD_CONTNTS", 0xE027: "CD_SUBRD", 0xE02A: "CD_PCMRD",
         0xE02D: "CD_FADE", 0xE030: "AD_RESET", 0xE033: "AD_TRANS",
         0xE036: "AD_READ", 0xE039: "AD_WRITE", 0xE03C: "AD_PLAY",
         0xE03F: "AD_CPLAY", 0xE042: "AD_STOP", 0xE045: "AD_STAT",
         0xE048: "EX_GETVER", 0xE04B: "EX_SETVEC", 0xE04E: "EX_GETFNT",
         0xE051: "EX_JOYSNS", 0xE054: "EX_JOYREP", 0xE057: "EX_SCRSIZ",
         0xE05A: "EX_DOTMOD", 0xE05D: "EX_SCRMOD", 0xE060: "EX_IMODE",
         0xE063: "EX_VMODE", 0xE066: "EX_HMODE", 0xE069: "EX_VSYNC",
         0xE06C: "EX_RCRON", 0xE06F: "EX_RCROFF", 0xE072: "EX_IRQON",
         0xE075: "EX_IRQOFF", 0xE078: "EX_BGON", 0xE07B: "EX_BGOFF",
         0xE07E: "EX_SPRON", 0xE081: "EX_SPROFF", 0xE084: "EX_DSPON",
         0xE087: "EX_DSPOFF", 0xE08A: "EX_DMAMOD", 0xE08D: "EX_SPRDMA",
         0xE090: "EX_SATCLR", 0xE093: "EX_SPRPUT", 0xE096: "EX_SETRCR",
         0xE099: "EX_SETRED", 0xE09C: "EX_SETWRT", 0xE09F: "EX_SETDMA",
         0xE0A2: "EX_BINBCD", 0xE0A5: "EX_BCDBIN", 0xE0A8: "EX_RND",
         0xE0AB: "MA_MUL8U", 0xE0AE: "MA_MUL8S", 0xE0B1: "MA_MUL16U",
         0xE0B4: "MA_DIV16S", 0xE0B7: "MA_DIV16U", 0xE0BA: "MA_SQRT",
         0xE0BD: "MA_SIN", 0xE0C0: "MA_COS", 0xE0C3: "MA_ATNI",
         0xE0C6: "PSG_BIOS", 0xE0C9: "GRP_BIOS", 0xE0CC: "EX_COLORCMD",
         0xE0D5: "MAX_MAPPING"}
ZP = {0xF8: "_al", 0xF9: "_ah", 0xFA: "_bl", 0xFB: "_bh", 0xFC: "_cl",
      0xFD: "_ch", 0xFE: "_dl", 0xFF: "_dh"}


def fmt_zp(z):
    return ZP.get(z, f"${z:02X}")


def decode(mem, base, pc):
    """One instruction at `pc` (absolute address); returns (text, length)."""
    i = pc - base
    op = mem[i]
    name, mode = OPS[op]
    n = LEN[mode]
    b = mem[i:i + n]
    if len(b) < n:
        return f".byte ${op:02X}", 1
    a1 = b[1] if n > 1 else 0
    w = (b[2] << 8 | b[1]) if n > 2 else 0
    if mode in ("imp", "acc"):
        s = name
    elif mode == "imm":
        s = f"{name} #${a1:02X}"
    elif mode == "zp":
        s = f"{name} {fmt_zp(a1)}"
    elif mode == "zpx":
        s = f"{name} {fmt_zp(a1)},X"
    elif mode == "zpy":
        s = f"{name} {fmt_zp(a1)},Y"
    elif mode == "zpi":
        s = f"{name} ({fmt_zp(a1)})"
    elif mode == "zpxi":
        s = f"{name} ({fmt_zp(a1)},X)"
    elif mode == "zpiy":
        s = f"{name} ({fmt_zp(a1)}),Y"
    elif mode == "rel":
        t = (pc + 2 + (a1 - 256 if a1 > 127 else a1)) & 0xFFFF
        s = f"{name} ${t:04X}"
    elif mode == "abs":
        s = f"{name} ${w:04X}" + (f"  ; {NAMES[w]}" if w in NAMES else "")
    elif mode == "absx":
        s = f"{name} ${w:04X},X"
    elif mode == "absy":
        s = f"{name} ${w:04X},Y"
    elif mode == "absi":
        s = f"{name} (${w:04X})"
    elif mode == "absxi":
        s = f"{name} (${w:04X},X)"
    elif mode == "zprel":
        t = (pc + 3 + (b[2] - 256 if b[2] > 127 else b[2])) & 0xFFFF
        s = f"{name} {fmt_zp(a1)},${t:04X}"
    elif mode == "immzp":
        s = f"{name} #${a1:02X},{fmt_zp(b[2])}"
    elif mode == "immzpx":
        s = f"{name} #${a1:02X},{fmt_zp(b[2])},X"
    elif mode == "immabs":
        s = f"{name} #${a1:02X},${b[3] << 8 | b[2]:04X}"
    elif mode == "immabsx":
        s = f"{name} #${a1:02X},${b[3] << 8 | b[2]:04X},X"
    elif mode == "blk":
        src, dst, ln = b[2] << 8 | b[1], b[4] << 8 | b[3], b[6] << 8 | b[5]
        s = f"{name} ${src:04X},${dst:04X},${ln:04X}"
    return s, n


def listing(mem, base, start=None, count=None, end=None):
    pc = start if start is not None else base
    out = []
    lim = end if end is not None else base + len(mem)
    while pc < lim and (count is None or len(out) < count):
        s, n = decode(mem, base, pc)
        raw = mem[pc - base:pc - base + n].hex(" ")
        out.append(f"{pc:04X}  {raw:<21} {s}")
        pc += n
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    mem = open(sys.argv[1], "rb").read()
    base = int(sys.argv[2], 16)
    start = int(sys.argv[3], 16) if len(sys.argv) > 3 else base
    count = int(sys.argv[4]) if len(sys.argv) > 4 else None
    print("\n".join(listing(mem, base, start, count)))
