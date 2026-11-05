"""A small HuC6280 assembler for the PCE engine stubs (pceengine.py).

`assemble(text, org, env0)` -> (bytes, labels); `env0` seeds the symbol
table, so a second block can call into the first. One instruction or `label:` per line, `;`
comments, `.byte` / `.word` / `.res n` data, `=` constants. Operands: `#imm`,
`zp`, `abs`, `abs,X`, `abs,Y`, `zp,X`, `(zp)`, `(zp),Y`, labels and
expressions Python can eval (`lo(x)`, `hi(x)` helpers). Only the addressing
modes the stubs use are implemented; an unsupported one raises.
"""
import re

# mnemonic -> {mode: opcode}
OPS = {
 "LDA": {"imm": 0xA9, "zp": 0xA5, "zpx": 0xB5, "abs": 0xAD, "absx": 0xBD, "absy": 0xB9, "zpi": 0xB2, "zpiy": 0xB1},
 "STA": {"zp": 0x85, "zpx": 0x95, "abs": 0x8D, "absx": 0x9D, "absy": 0x99, "zpi": 0x92, "zpiy": 0x91},
 "LDX": {"imm": 0xA2, "zp": 0xA6, "abs": 0xAE}, "STX": {"zp": 0x86, "abs": 0x8E},
 "LDY": {"imm": 0xA0, "zp": 0xA4, "abs": 0xAC, "absx": 0xBC}, "STY": {"zp": 0x84, "abs": 0x8C},
 "STZ": {"zp": 0x64, "abs": 0x9C, "absx": 0x9E},
 "CMP": {"imm": 0xC9, "zp": 0xC5, "abs": 0xCD, "absx": 0xDD, "absy": 0xD9}, "CPX": {"imm": 0xE0, "zp": 0xE4, "abs": 0xEC}, "CPY": {"imm": 0xC0, "zp": 0xC4, "abs": 0xCC},
 "ADC": {"imm": 0x69, "zp": 0x65, "abs": 0x6D, "absx": 0x7D, "absy": 0x79}, "SBC": {"imm": 0xE9, "zp": 0xE5, "abs": 0xED, "absx": 0xFD, "absy": 0xF9},
 "AND": {"imm": 0x29, "zp": 0x25, "abs": 0x2D, "absx": 0x3D, "absy": 0x39}, "ORA": {"imm": 0x09, "zp": 0x05, "abs": 0x0D, "absx": 0x1D, "absy": 0x19}, "EOR": {"imm": 0x49, "zp": 0x45, "abs": 0x4D},
 "ASL": {"acc": 0x0A, "zp": 0x06, "abs": 0x0E}, "LSR": {"acc": 0x4A, "zp": 0x46, "abs": 0x4E},
 "ROL": {"acc": 0x2A, "zp": 0x26, "abs": 0x2E}, "ROR": {"acc": 0x6A, "zp": 0x66, "abs": 0x6E},
 "INC": {"acc": 0x1A, "zp": 0xE6, "abs": 0xEE, "absx": 0xFE}, "DEC": {"acc": 0x3A, "zp": 0xC6, "abs": 0xCE},
 "JMP": {"abs": 0x4C}, "JSR": {"abs": 0x20},
 "BCC": {"rel": 0x90}, "BCS": {"rel": 0xB0}, "BEQ": {"rel": 0xF0}, "BNE": {"rel": 0xD0},
 "BPL": {"rel": 0x10}, "BMI": {"rel": 0x30}, "BRA": {"rel": 0x80},
 "TAM": {"imm": 0x53}, "TMA": {"imm": 0x43},
}
IMPLIED = {"RTS": 0x60, "SEC": 0x38, "CLC": 0x18, "INX": 0xE8, "INY": 0xC8, "DEX": 0xCA, "DEY": 0x88,
           "TAX": 0xAA, "TXA": 0x8A, "TAY": 0xA8, "TYA": 0x98, "PHA": 0x48, "PLA": 0x68,
           "PHX": 0xDA, "PLX": 0xFA, "PHY": 0x5A, "PLY": 0x7A, "CLA": 0x62, "CLX": 0x82, "CLY": 0xC2,
           "NOP": 0xEA, "SAX": 0x22, "SXY": 0x02, "PHP": 0x08, "PLP": 0x28, "SEI": 0x78, "CLI": 0x58}


def assemble(text, org, env0=None):
    env = {"lo": lambda v: v & 0xFF, "hi": lambda v: (v >> 8) & 0xFF}
    env.update(env0 or {})
    lines = []
    for raw in text.splitlines():
        line = raw.split(";")[0].strip()
        if line:
            lines.append(line)

    _pass = 0

    def ev(expr):
        try:
            return int(eval(expr, {}, env))
        except NameError:
            if _pass == 0:
                return 0x8000     # a forward reference, resolved on pass 2: taken as absolute
            raise

    out = None
    sizes = {}                    # each line's bytes on pass 1, checked on pass 2: a label used
    for _pass in range(2):        # before its definition must assemble to the same size
        pc, out = org, bytearray()
        for n, line in enumerate(lines):
            if "=" in line and not line.upper().startswith(("LDA", "STA")) and re.match(r"^\w+\s*=", line):
                k, v = line.split("=", 1)
                env[k.strip()] = ev(v)
                continue
            if re.match(r"^\w+:", line):
                label, _, line = line.partition(":")
                env[label] = pc
                line = line.strip()
                if not line:
                    continue
            parts = line.split(None, 1)
            op, arg = parts[0].upper(), (parts[1].strip() if len(parts) > 1 else "")
            if op == ".BYTE":
                data = bytes(ev(x) & 0xFF for x in arg.split(","))
            elif op == ".WORD":
                data = b"".join(ev(x).to_bytes(2, "little") for x in arg.split(","))
            elif op == ".RES":
                data = bytes(ev(arg))
            elif op in IMPLIED:
                data = bytes([IMPLIED[op]])
            else:
                modes = OPS[op]
                if not arg or arg.upper() == "A":
                    mode, val = "acc", None
                elif arg.startswith("#"):
                    mode, val = "imm", ev(arg[1:])
                elif arg.startswith("("):
                    inner, _, idx = arg.partition(")")
                    mode, val = ("zpiy" if idx.strip().upper() == ",Y" else "zpi"), ev(inner[1:])
                else:
                    base, _, idx = arg.partition(",")
                    # `a:` forces absolute addressing: the VDC ports live at
                    # $0000-$0003, below the zero page ($2000 on the HuC6280)
                    force_abs = base.strip().lower().startswith("a:")
                    val = ev(base.strip()[2:] if force_abs else base)
                    idx = idx.strip().upper()
                    if "rel" in modes:
                        mode = "rel"
                    elif not force_abs and val < 0x100 and idx == "" and "zp" in modes:
                        mode = "zp"
                    elif not force_abs and val < 0x100 and idx == "X" and "zpx" in modes:
                        mode = "zpx"
                    else:
                        mode = {"": "abs", "X": "absx", "Y": "absy"}[idx]
                if mode not in modes:
                    raise ValueError(f"{op} {arg}: no {mode} form")
                opc = modes[mode]
                if mode == "acc":
                    data = bytes([opc])
                elif mode in ("imm", "zp", "zpx", "zpi", "zpiy"):
                    data = bytes([opc, val & 0xFF])
                elif mode == "rel":
                    off = val - (pc + 2)
                    if _pass == 1 and not -128 <= off <= 127:
                        raise ValueError(f"branch out of range: {line}")
                    data = bytes([opc, off & 0xFF])
                else:
                    data = bytes([opc]) + (val & 0xFFFF).to_bytes(2, "little")
            if _pass == 0:
                sizes[n] = len(data)
            elif sizes[n] != len(data):
                raise ValueError(f"{line}: {len(data)} bytes on the second pass, {sizes[n]} on the first (a zero-page label defined after its use?)")
            out += data
            pc += len(data)
    return bytes(out), env
