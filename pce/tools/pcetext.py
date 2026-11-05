"""Snatcher CD-ROMantic's dialogue codec (decoder $7272 in the scene module).

Dialogue is not stored as Shift-JIS. The script is a stream of 12-bit codes,
nibble-packed (two codes per three bytes), read by the routine the game keeps
at $7272 (SysCardRAM module offset 0x5272 in the reception scene's state):

  code = n:b   (n = 4 bits, b = 8 bits)
  b >= 0x40    JIS level-1 kanji, SJIS lead byte from n:
                 n < 8 -> 0x90+n ; n == 8 -> 0x98 if b < 0x9F else 0x88 ;
                 n > 8 -> 0x80+n            (rows 0x88-0x98) ; trail byte b
  b <  0x40    n == 0    end of string (a raw 0x00 byte at a byte boundary
                         is also the end)
               n == 1,2  a RUN of b one-byte characters follows:
                         byte < 0x40 -> 0x81, byte+0x40   (punctuation)
                         byte >= 0x9F -> 0x82, byte       (hiragana)
                         else n==1 -> 0x83 (katakana), n==2 -> 0x82 (alnum)
               n >= 3    SJIS 0x81+(n&3), ((n&0xC)<<4)|b  (rows 0x81-0x84)

Characters 0x82F2-0x82FF are in-text commands, not glyphs:
  82F2/F3 line end, 82F4/F5 page/wait, 82F6/F7 message end,
  82F8-FF  emitted as {FE, lo&7} (colour/face switch).

`decode(buf, pos)` returns (text, next_pos) with commands as <...> tags;
`encode(text)` is the inverse (a run for every maximal one-byte stretch).
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

CMD = {0xF2: "<nl>", 0xF3: "<nl>", 0xF4: "<wait>", 0xF5: "<wait>",
       0xF6: "<end>", 0xF7: "<end>"}


class Reader:
    def __init__(self, buf, pos):
        self.buf, self.pos, self.phase = buf, pos, 0

    def raw_byte_aligned(self):
        return self.phase == 0 and self.buf[self.pos] == 0

    def byte(self):
        """One 8-bit unit at the current nibble phase."""
        b = self.buf
        if self.phase == 0:
            v = b[self.pos]
            self.pos += 1
        else:
            v = ((b[self.pos] & 0xF) << 4) | (b[self.pos + 1] >> 4)
            self.pos += 1
        return v

    def code(self):
        """One 12-bit code (n, b)."""
        b = self.buf
        if self.phase == 0:
            n = b[self.pos] >> 4
            v = ((b[self.pos] & 0xF) << 4) | (b[self.pos + 1] >> 4)
            self.pos += 1
            self.phase = 1
        else:
            n = b[self.pos] & 0xF
            v = b[self.pos + 1]
            self.pos += 2
            self.phase = 0
        return n, v

    def run_byte(self):
        """An 8-bit unit inside a run, keeping the nibble phase."""
        b = self.buf
        if self.phase == 0:
            v = b[self.pos]
            self.pos += 1
        else:
            v = ((b[self.pos] & 0xF) << 4) | (b[self.pos + 1] >> 4)
            self.pos += 1
        return v


def sjis_char(hi, lo):
    if hi == 0x82 and lo >= 0xF2:
        return CMD.get(lo, f"<cmd{lo & 7}>")
    try:
        return bytes([hi, lo]).decode("cp932")
    except UnicodeDecodeError:
        return f"<{hi:02x}{lo:02x}>"


def decode_codes(buf, pos):
    """Decode one string starting at `pos` (phase 0) -> ([(hi, lo)], next_pos).
    A run's one-byte characters come out as their SJIS codes too."""
    r = Reader(buf, pos)
    out = []
    while r.pos < len(buf) - 1:
        if r.raw_byte_aligned():
            r.pos += 1
            break
        n, b = r.code()
        if b >= 0x40:
            if n < 8:
                hi = 0x90 | n
            elif n == 8:
                hi = 0x98 if b < 0x9F else 0x88
            else:
                hi = 0x80 | n
            out.append((hi, b))
            continue
        if n == 0:
            break
        if n in (1, 2):
            for _ in range(b):
                v = r.run_byte()
                if v < 0x40:
                    out.append((0x81, v + 0x40))
                elif v >= 0x9F:
                    out.append((0x82, v))
                else:
                    out.append((0x83 if n == 1 else 0x82, v))
            continue
        out.append((0x81 + (n & 3), ((n & 0xC) << 4) | b))
    if r.phase == 1:
        r.pos += 1
    return out, r.pos


def decode(buf, pos, stop_at_end=True):
    """Decode one string starting at `pos` (phase 0). -> (text, next_pos)."""
    codes, nxt = decode_codes(buf, pos)
    return "".join(sjis_char(hi, lo) for hi, lo in codes), nxt


if __name__ == "__main__":
    path, start = sys.argv[1], int(sys.argv[2], 16)
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    buf = open(path, "rb").read()
    pos = start
    for _ in range(count):
        text, nxt = decode(buf, pos)
        print(f"{pos:06x} {text}")
        pos = nxt


# --- encoder ---------------------------------------------------------------
TAGS = {"<nl>": 0xF2, "<wait>": 0xF4, "<end>": 0xF6}
FULLWIDTH = {i: i + 0xFEE0 for i in range(0x21, 0x7F)}
FULLWIDTH[0x20] = 0x3000
# ASCII quotes would become NEC extension codes (EEFB...) the font lacks
FULLWIDTH[0x27] = 0x2019
FULLWIDTH[0x22] = 0x201D
FULLWIDTH[0x7E] = 0x301C
FULLWIDTH[0x5C] = 0xA5


def tokens(text, pairs=True):
    """Split a string into SJIS (hi, lo) codes.

    ASCII stretches become pair codes (two letters a cell, pcepair) with the
    leftovers as fullwidth singles; `pairs=False` keeps every letter fullwidth
    (raw-SJIS places such as names, where no English flag is up)."""
    import pcepair
    i = 0
    while i < len(text):
        if pairs and ord(text[i]) < 0x80 and text[i] != "<":
            j = i
            while j < len(text) and ord(text[j]) < 0x80 and text[j] != "<":
                j += 1
            for t in pcepair.split(text[i:j]):
                if isinstance(t, tuple):
                    yield pcepair.pair_code(*t)
                else:                     # a control character: its fullwidth form
                    yield tuple(chr(FULLWIDTH[ord(t)]).encode("cp932"))
            i = j
            continue
        if text[i] == "<":
            j = text.index(">", i)
            tag = text[i:j + 1]
            if tag == "<join>":
                pass                      # no code: only ends an ASCII stretch
            elif tag.startswith("<d:"):   # dictionary entry (pcedict)
                import pcedict
                yield 0x84, pcedict.lo_of(int(tag[3:-1]))
            elif tag in TAGS:
                yield 0x82, TAGS[tag]
            elif tag.startswith("<cmd"):
                yield 0x82, 0xF8 + int(tag[4:-1])
            elif len(tag) == 6:           # <hhhh>: a raw code with no glyph
                yield int(tag[1:3], 16), int(tag[3:5], 16)
            else:
                raise ValueError(f"unknown tag {tag}")
            i = j + 1
            continue
        ch = text[i]
        i += 1
        if ord(ch) < 0x80:
            ch = chr(FULLWIDTH[ord(ch)])
        hi, lo = ch.encode("cp932")
        yield hi, lo


def run_byte(hi, lo):
    """(run kind, byte) if this character can sit in a run, else None."""
    if hi == 0x81 and lo < 0x80:
        return None, lo - 0x40          # either run kind
    if hi == 0x82 and lo >= 0x9F:
        return None, lo                 # hiragana and the F2+ commands, either kind
    if hi == 0x82 and lo < 0x9F:
        return 2, lo
    if hi == 0x83 and lo < 0x9F:
        return 1, lo
    return None


def code_of(hi, lo):
    """The 12-bit (n, b) for one character outside a run."""
    if 0x88 <= hi <= 0x98 and lo >= 0x40:
        if 0x90 <= hi <= 0x97:
            return hi - 0x90, lo
        if hi == 0x98 and lo < 0x9F or hi == 0x88 and lo >= 0x9F:
            return 8, lo
        if 0x89 <= hi <= 0x8F:
            return hi - 0x80, lo
    if 0x81 <= hi <= 0x84:
        return (hi - 0x81) | ((lo & 0xC0) >> 4), lo & 0x3F
    raise ValueError(f"cannot encode {hi:02x}{lo:02x}")


def encode(text, min_run=3, english=False, pairs=True):
    """Text with <nl>/<wait>/<end>/<cmdN> tags -> the nibble-packed bytes.

    Maximal stretches of run-able characters (fullwidth Latin, hiragana,
    punctuation; or katakana) of `min_run` or more go out as runs of at most
    63; the string ends with the n=0 code and a pad nibble if needed.
    `english` puts the pcepair.MARK code first: the engine stub raises the
    English flag on it, and only then are rows 0x89-0x94 pairs."""
    import pcepair
    toks = list(tokens(text, pairs))
    if english:
        toks.insert(0, pcepair.MARK)
    return encode_tokens(toks, min_run)


def encode_tokens(toks, min_run=3):
    """The nibble stream for a list of (hi, lo) codes (see encode)."""
    toks = list(toks)
    if not toks or toks[-1] != (0, 0):
        toks.append((0, 0))
    nib = []
    i = 0
    while i < len(toks):
        # gather a run: consecutive run-able chars with a compatible kind
        kind, j = None, i
        while j < len(toks):
            r = run_byte(*toks[j])
            if r is None:
                break
            k, _ = r
            if k is not None:
                if kind is not None and k != kind:
                    break
                kind = k
            j += 1
            if j - i == 63:
                break
        if j - i >= min_run:
            nib += [kind or 1, (j - i) >> 4, (j - i) & 0xF]
            for t in toks[i:j]:
                _, b = run_byte(*t)
                nib += [b >> 4, b & 0xF]
            i = j
            continue
        hi, lo = toks[i]
        i += 1
        if (hi, lo) == (0, 0):
            # a raw 0x00 byte ends the string at a byte boundary; mid-byte
            # the n=0 code does (its b must be < 0x40)
            nib += [0] if len(nib) % 2 == 0 else [0, 0, 0]
            break
        n, b = code_of(hi, lo)
        nib += [n, b >> 4, b & 0xF]
    if len(nib) % 2:
        nib.append(0)
    return bytes((nib[k] << 4) | nib[k + 1] for k in range(0, len(nib), 2))


def encode_raw(text):
    """Plain Shift-JIS for the raw places (names, menus): ASCII as fullwidth."""
    return b"".join(bytes(t) for t in tokens(text, pairs=False))
