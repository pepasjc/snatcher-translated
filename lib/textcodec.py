"""Snatcher PS1/Saturn text codec.

2-byte big-endian font codes, descending vs JIS:
  pair  = (ku+1)//2            # JIS rows grouped in pairs
  high  = 0x80 - pair
  pos   = (0 if ku odd else 94) + (ten - 1)   # position within pair (odd row first)
  low   = 0xC0 - pos ; if low <= 0x80: low -= 1   # 0x80 reserved
Verified: ACT1/ACT2 menu text, speaker names vs Saturn SJIS table.
"""

def jis_to_code(ku, ten):
    pair = (ku + 1) // 2
    high = 0x80 - pair
    pos = (0 if ku % 2 == 1 else 94) + (ten - 1)
    low = 0xC0 - pos
    if low <= 0x80:
        low -= 1
    if low < 0:
        return None
    return (high << 8) | low

def code_to_jis(code):
    high, low = code >> 8, code & 0xFF
    pair = 0x80 - high
    if pair < 1 or pair > 47:
        return None
    if low <= 0x7F:
        low += 1  # undo reserved-0x80 skip
    pos = 0xC0 - low
    if pos < 0 or pos >= 188:
        return None
    ku = (pair - 1) * 2 + (1 if pos < 94 else 2)
    ten = (pos % 94) + 1
    return ku, ten

def code_to_char(code):
    j = code_to_jis(code)
    if not j:
        return None
    ku, ten = j
    try:
        return bytes([0x80 | (0x20 + ku), 0x80 | (0x20 + ten)]).decode("euc_jp")
    except UnicodeDecodeError:
        return None

def char_to_code(ch):
    try:
        e = ch.encode("euc_jp")
    except UnicodeEncodeError:
        return None
    if len(e) != 2:
        return None
    ku, ten = (e[0] & 0x7F) - 0x20, (e[1] & 0x7F) - 0x20
    return jis_to_code(ku, ten)

def encode_string(s):
    out = bytearray()
    for ch in s:
        c = char_to_code(ch)
        if c is None:
            raise ValueError(f"cannot encode {ch!r}")
        out += bytes([c >> 8, c & 0xFF])
    return bytes(out)

def decode_stream(d, lo=0x55, hi=0x7F):
    """Decode byte stream: 2-byte codes (first byte in [lo,hi]) else control byte."""
    out = []
    i = 0
    while i < len(d):
        b = d[i]
        if lo <= b <= hi and i + 1 < len(d):
            code = (b << 8) | d[i+1]
            ch = code_to_char(code)
            out.append(ch if ch else f"[{code:04x}]")
            i += 2
        else:
            out.append(f"<{b:02x}>")
            i += 1
    return "".join(out)
