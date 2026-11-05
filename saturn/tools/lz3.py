"""DATA.BIN chunk table and the Saturn Snatcher decompressor (MAIN_L.BIN 0x060CB548).

Read out of the SH-2 code and verified: every chunk in DATA.BIN whose header
is in this format decodes to exactly its declared size with all three
streams consumed (561 of 639; chunks 21-98 are something else).

Container layout (all big-endian):
    u32 outsize          decompressed size
    u16 nwords           number of 32-bit words in the BIT stream
    u16 nhalf            number of 16-bit words in the TOKEN stream
    bits   = src + 8                       nwords x u32
    tokens = bits + 4*nwords               nhalf  x u16
    bytes  = tokens + 2*nhalf              literals, short offsets, long lengths
Bits are consumed LSB-first out of each 32-bit word (shlr), 32 per word.

Decode loop (the engine steps it in time slices; the algorithm is):
    bit 0                 -> literal: out += bytes[i++]
    bit 1, bit 1          -> short match: off = bytes[i++]; n = 2 bits MSB-first + 2 (2..5)
                             copy n from out[-(off+1)]                (distance 1..256)
    bit 1, bit 0          -> w = tokens[j++]; w == 0 ends the stream
                             n = w & 15; off = w >> 4
                             n != 0: n += 2 (3..17), copy from out[-(off+1)]  (distance 1..4096)
                             n == 0: n = bytes[i++] (raw byte), copy from out[-off]
    copies are byte-by-byte forward (overlap allowed).
No ring buffer: matches address the output directly.  The engine keeps
its state in 0x060FEAEC..0x060FEB08 (setup at 0x060CB6FC, step at
0x060CB548, done flag 0x060FEAFC) and load_chunk (0x060B2F8C) reads the raw
chunk to low RAM 0x00248000 and decodes to 0x00258000 before copying out.

What the SH-2 step (0x060CB548) really requires - read for the encoder:
  * It ends ONLY on the 0 token.  The setup stores outsize at 0x060FEAF0
    but the step never reads it, so a chunk without the terminating
    `1,0` bits + 0x0000 token decodes on into garbage.  outsize is what
    load_chunk copies out afterwards; it must still be exact.
  * The step runs until the vblank tick counter 0x060F5640 (zeroed on
    entry, bumped by the frame handler 0x060B1608) reaches its argument
    (load_chunk passes 0x96): a time slice, not a byte slice.  State
    (bit counter, bit word, out/bit/token/byte pointers) is saved between
    whole tokens, so nothing about the interleaving can break a resume.
  * The bit word is reloaded (`mov.l @r4+`) when its 32nd bit is consumed,
    so a stream whose bits fill the last word exactly makes the step read
    one word into the token stream - harmless, and 26 of the 561 original
    chunks do it: nwords = ceil(bits / 32), no padding word.
  * Long form (token low nibble 0): the length is the raw byte, counted
    down with `dt`, so 0 would copy 2^32 bytes - lengths are 1..255 (the
    originals use 18..255); distance = off (1..4095, 0 copies garbage).
    Token form: distance off+1, so 4096 is expressible but the originals
    never use it; the encoder's window is 4095 for both.
  * The token stream is read with mov.w: it starts at 8 + 4*nwords, always
    even.  Chunks are padded to an even length (the table stores size/2);
    the original encoder leaves 0 or 1 pad byte after the literal stream.

Encoder (`encode(data) -> bytes`): an optimal parse over the four forms -
literal 1 bit + 1 byte, short match 4 bits + 1 byte (dist <= 256, len
2-5), token match 2 bits + 2 bytes (dist <= 4095, len 3-17), long match
2 bits + 3 bytes (len 18-255) - with a hash-chain match finder; because
the cost of a suffix never rises, only the longest match of each form is
a candidate at a position.  `verify` round-trips every chunk and writes
the size table to work/saturn/lz3_ratio.txt: at the default chain depth
(256) 556 of 561 chunks come out smaller than Konami's (total 0.968, the
font chunk 0 33,946 vs 35,276 in a 36,864-byte slot); the five that grow
(by 4-18 bytes, highly repetitive data) all beat it with
`encode(data, maxchain=4096)` - the whole window, seconds to a minute per
chunk on such data - so pass that when a rebuilt chunk must fit its slot.

The chunk table sits in the exec at 0x060E62F4: 639 x {u16 sector, u16
size/2}, sectors relative to DATA.BIN's start, contiguous; opened through
0x060B22EC(idx) -> 0x060B22B4 ("DATA.BIN" seek) and read with the 2 KB
sector cache in 0x060B23C8.

Usage (repo root):
    python saturn/tools/lz3.py table                 print the chunk table
    python saturn/tools/lz3.py extract [idx ...]     decode chunks to work/saturn/data_bin/NNN.bin (all by default)
    python saturn/tools/lz3.py decode IN OUT         decode one raw chunk file
    python saturn/tools/lz3.py encode IN OUT [--chain N]   compress a file into a chunk (N = match candidates per position, 256)
    python saturn/tools/lz3.py verify [idx ...]      round-trip every decodable chunk, sizes to work/saturn/lz3_ratio.txt
"""
import os, struct, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

EXTRACTED = os.path.join(ROOT, "discs", "extracted_saturn")
DATA_BIN = os.path.join(EXTRACTED, "DATA.BIN")
MAIN_L = os.path.join(EXTRACTED, "MAIN_L.BIN")
MAIN_BASE = 0x060B0000
TABLE_ADDR = 0x060E62F4
TABLE_N = 639
OUT_DIR = os.path.join(WORK, "saturn", "data_bin")


class BadChunk(Exception):
    pass


def decode(src, strict=True):
    """Decode one chunk. Returns bytes; raises BadChunk on a size/stream mismatch."""
    if len(src) < 8:
        raise BadChunk("too short")
    outsize, nw, nh = struct.unpack_from(">IHH", src, 0)
    bits = 8
    tok = bits + 4 * nw
    lit = tok + 2 * nh
    if lit > len(src):
        raise BadChunk("streams exceed chunk")
    out = bytearray()
    bp = bits
    if nw == 0:
        raise BadChunk("no bit words")
    word = struct.unpack_from(">I", src, bp)[0]
    bp += 4
    nb = 32
    tp = tok
    lp = lit

    def getbit():
        nonlocal word, nb, bp
        nb -= 1
        t = word & 1
        word >>= 1
        if nb == 0:
            nb = 32
            if bp + 4 <= tok:
                word = struct.unpack_from(">I", src, bp)[0]
            else:
                word = 0          # the engine would read past; only legal at the very end
            bp += 4
        return t

    try:
        while True:
            if getbit() == 0:
                out.append(src[lp])
                lp += 1
                continue
            if getbit() == 1:
                off = src[lp]
                lp += 1
                n = getbit()
                n = (n << 1) | getbit()
                n += 2
                dist = off + 1
            else:
                w = struct.unpack_from(">H", src, tp)[0]
                tp += 2
                if w == 0:
                    break
                n = w & 15
                off = w >> 4
                if n:
                    n += 2
                    dist = off + 1
                else:
                    n = src[lp]
                    lp += 1
                    dist = off
            s = len(out) - dist
            if s < 0:
                raise BadChunk("match before start")
            for k in range(n):
                out.append(out[s + k])
            if len(out) > outsize:
                raise BadChunk("output overrun")
    except (IndexError, struct.error) as e:
        raise BadChunk(f"stream overrun: {e}")
    if strict:
        if len(out) != outsize:
            raise BadChunk(f"size {len(out)} != header {outsize}")
        if tp != lit:
            raise BadChunk("token stream not fully consumed")
        if not (lit <= lp <= len(src)):
            raise BadChunk("literal stream mismatch")
    return bytes(out)


# ---------------------------------------------------------------- encoder

WINDOW = 4095        # longest distance either token form reaches in the originals
NEAR = 256           # short-form distance limit (byte + 1)
SHORT_MAX = 5        # short-form length limit (2 bits + 2)
TOKEN_MAX = 17       # token-form length limit (nibble + 2)
LONG_MAX = 255       # long-form length limit (raw byte; 0 would never end)
LONG_MIN = 18
MAXCHAIN = 256       # hash-chain candidates examined per position (64: 3x faster, ~0.5% bigger)

COST_LIT, COST_SHORT, COST_TOKEN, COST_LONG = 9, 12, 18, 26   # bits


def _find_matches(data, maxchain=MAXCHAIN):
    """Per position: (longest match <= WINDOW, its distance, longest match
    <= NEAR capped at SHORT_MAX, its distance).  A match found at i is
    carried to i+1 one byte shorter, so the candidate set at i+1 dominates
    the trimmed set at i and the parse cost is monotone in the suffix."""
    n = len(data)
    lfar = [0] * n
    dfar = [0] * n
    lnear = [0] * n
    dnear = [0] * n
    head = {}
    prev = [-1] * n
    last2 = {}
    cf = cn = 0          # carried far / near lengths
    cdf = cdn = 0
    for i in range(n):
        rem = n - i
        maxl = LONG_MAX if rem > LONG_MAX else rem
        bf, df = (cf, cdf) if cf >= 3 else (0, 0)
        bn, dn = (cn, cdn) if cn >= 2 else (0, 0)
        if rem >= 2:
            pair = (data[i] << 8) | data[i + 1]
            c = last2.get(pair)
            if c is not None and i - c <= NEAR and bn < SHORT_MAX:
                lim = SHORT_MAX if rem > SHORT_MAX else rem
                l = 2
                while l < lim and data[c + l] == data[i + l]:
                    l += 1
                if l > bn:
                    bn, dn = l, i - c
            last2[pair] = i
        if rem >= 3:
            key = (pair << 8) | data[i + 2]
            cand = head.get(key, -1)
            prev[i] = cand
            head[key] = i
            steps = 0
            while cand >= 0 and steps < maxchain:
                d = i - cand
                if d > WINDOW:
                    break
                steps += 1
                want_far = bf < maxl and data[cand + bf] == data[i + bf]
                want_near = d <= NEAR and bn < SHORT_MAX
                if want_far or want_near:
                    l = 3
                    while l + 8 <= maxl and data[cand + l:cand + l + 8] == data[i + l:i + l + 8]:
                        l += 8
                    while l < maxl and data[cand + l] == data[i + l]:
                        l += 1
                    if l > bf:
                        bf, df = l, d
                    if want_near:
                        ln = l if l < SHORT_MAX else SHORT_MAX
                        if ln > bn:
                            bn, dn = ln, d
                if bf == maxl and (bn == SHORT_MAX or not want_near):
                    break
                cand = prev[cand]
        lfar[i] = bf
        dfar[i] = df
        lnear[i] = bn
        dnear[i] = dn
        cf, cdf = bf - 1, df
        cn, cdn = bn - 1, dn
        if df and df <= NEAR:
            t = cf if cf < SHORT_MAX else SHORT_MAX
            if t > cn:
                cn, cdn = t, df
    return lfar, dfar, lnear, dnear


def encode(data, maxchain=MAXCHAIN):
    """Compress `data` into a chunk the SH-2 decoder at 0x060CB548 consumes.

    Header u32 outsize, u16 nwords, u16 nhalf; bit stream (LSB-first in BE
    u32 words, exactly ceil(bits/32) of them), BE u16 tokens ending with
    0x0000, the byte stream; padded to an even length."""
    data = bytes(data)
    n = len(data)
    lfar, dfar, lnear, dnear = _find_matches(data, maxchain)

    # optimal parse, backwards: cost[i] = bits to encode data[i:]
    cost = [0] * (n + 1)
    choice = [0] * n          # form << 8 | length; form 0 lit, 1 short, 2 token, 3 long
    for i in range(n - 1, -1, -1):
        c = COST_LIT + cost[i + 1]
        ch = 1
        ln = lnear[i]
        if ln >= 2:
            L = ln if ln < SHORT_MAX else SHORT_MAX
            t = COST_SHORT + cost[i + L]
            if t < c:
                c, ch = t, (1 << 8) | L
        lf = lfar[i]
        if lf >= 3:
            L = lf if lf < TOKEN_MAX else TOKEN_MAX
            t = COST_TOKEN + cost[i + L]
            if t < c:
                c, ch = t, (2 << 8) | L
            if lf >= LONG_MIN:
                t = COST_LONG + cost[i + lf]
                if t < c:
                    c, ch = t, (3 << 8) | lf
        cost[i] = c
        choice[i] = ch

    # emit
    words = []
    acc = 0
    nb = 0

    def putbits(v, cnt):          # cnt bits of v, MSB of the group first
        nonlocal acc, nb
        for k in range(cnt - 1, -1, -1):
            acc |= ((v >> k) & 1) << nb
            nb += 1
            if nb == 32:
                words.append(acc)
                acc = 0
                nb = 0

    tokens = []
    lits = bytearray()
    i = 0
    while i < n:
        ch = choice[i]
        form, L = ch >> 8, ch & 0xFF
        if form == 0:
            putbits(0, 1)
            lits.append(data[i])
        elif form == 1:
            d = dnear[i]
            assert 1 <= d <= NEAR and 2 <= L <= SHORT_MAX
            putbits(0b11, 2)
            lits.append(d - 1)
            putbits(L - 2, 2)
        elif form == 2:
            d = dfar[i]
            assert 1 <= d <= WINDOW and 3 <= L <= TOKEN_MAX
            putbits(0b10, 2)
            tokens.append(((d - 1) << 4) | (L - 2))
        else:
            d = dfar[i]
            assert 1 <= d <= WINDOW and LONG_MIN <= L <= LONG_MAX
            putbits(0b10, 2)
            tokens.append(d << 4)
            lits.append(L)
        i += L
    assert i == n
    putbits(0b10, 2)
    tokens.append(0)
    if nb:
        words.append(acc)
    if len(words) > 0xFFFF or len(tokens) > 0xFFFF:
        raise ValueError("chunk too big for the u16 stream counts")
    out = bytearray(struct.pack(">IHH", n, len(words), len(tokens)))
    out += struct.pack(">%dI" % len(words), *words)
    out += struct.pack(">%dH" % len(tokens), *tokens)
    out += lits
    if len(out) & 1:
        out.append(0)
    return bytes(out)


def _verify_one(args):
    i, src = args
    try:
        dec = decode(src)
    except BadChunk as e:
        return (i, None, len(src), 0, str(e))
    enc = encode(dec)
    ok = decode(enc) == dec
    return (i, len(dec), len(src), len(enc), "ok" if ok else "MISMATCH")


def verify(idxs=None, report=None, jobs=None):
    """Round-trip every decodable chunk through encode/decode; table of sizes."""
    rows = table()
    idxs = list(idxs) if idxs else list(range(len(rows)))
    with open(DATA_BIN, "rb") as f:
        srcs = [(i, read_chunk(f, i, rows)) for i in idxs]
    import multiprocessing
    jobs = jobs or max(1, (os.cpu_count() or 2) - 1)
    if jobs > 1 and len(srcs) > 1:
        with multiprocessing.Pool(jobs) as pool:
            res = pool.map(_verify_one, srcs, chunksize=1)
    else:
        res = [_verify_one(a) for a in srcs]
    res.sort()
    lines = ["idx  outsize  original    ours   ratio  result"]
    ok = bad = skipped = 0
    tot_o = tot_n = 0
    ratios = []
    for i, dec, orig, ours, verdict in res:
        if dec is None:
            skipped += 1
            continue
        if verdict == "ok":
            ok += 1
        else:
            bad += 1
        tot_o += orig
        tot_n += ours
        ratio = ours / orig if orig else 0
        ratios.append((ratio, i))
        lines.append(f"{i:3d}  {dec:7d}  {orig:8d}  {ours:8d}  {ratio:6.3f}  {verdict}")
    if tot_o:
        lines.append(f"{ok} round-trip ok, {bad} mismatched, {skipped} not this format; "
                     f"packed total original {tot_o} ours {tot_n} ({tot_n / tot_o:.3f})")
        bigger = sorted(r for r in ratios if r[0] > 1.0)
        lines.append(f"{len(bigger)} chunks larger than the original" +
                     (": " + ", ".join(f"{i} ({r:.3f})" for r, i in bigger[-10:]) if bigger else ""))
    else:
        lines.append("nothing decodable")
    text = "\n".join(lines) + "\n"
    report = report or os.path.join(WORK, "saturn", "lz3_ratio.txt")
    os.makedirs(os.path.dirname(report), exist_ok=True)
    open(report, "w").write(text)
    return text, ok, bad


def table():
    """[(sector, size)] from the exec's table at 0x060E62F4."""
    d = open(MAIN_L, "rb").read()
    off = TABLE_ADDR - MAIN_BASE
    rows = []
    for i in range(TABLE_N):
        sec, half = struct.unpack_from(">HH", d, off + 4 * i)
        rows.append((sec, half * 2))
    return rows


def read_chunk(f, idx, rows=None):
    rows = rows or table()
    sec, size = rows[idx]
    f.seek(sec * 2048)
    return f.read(size)


def main(argv):
    cmd = argv[0] if argv else "table"
    if cmd == "table":
        rows = table()
        for i, (sec, size) in enumerate(rows):
            print(f"{i:3d}  sector {sec:5d}  size {size:6d}")
        print(f"{len(rows)} chunks; last ends at sector {rows[-1][0] + (rows[-1][1] + 2047) // 2048}")
    elif cmd == "extract":
        rows = table()
        idxs = [int(a) for a in argv[1:]] or range(len(rows))
        os.makedirs(OUT_DIR, exist_ok=True)
        ok = bad = 0
        with open(DATA_BIN, "rb") as f:
            for i in idxs:
                src = read_chunk(f, i, rows)
                try:
                    out = decode(src)
                except BadChunk as e:
                    bad += 1
                    print(f"{i:3d}  not this format ({e}); head {src[:8].hex()}")
                    continue
                ok += 1
                open(os.path.join(OUT_DIR, f"{i:03d}.bin"), "wb").write(out)
        print(f"{ok} decoded, {bad} skipped -> {OUT_DIR}")
    elif cmd == "decode":
        out = decode(open(argv[1], "rb").read())
        open(argv[2], "wb").write(out)
        print(f"{len(out)} bytes -> {argv[2]}")
    elif cmd == "encode":
        chain = MAXCHAIN
        if "--chain" in argv:
            k = argv.index("--chain")
            chain = int(argv[k + 1])
            del argv[k:k + 2]
        data = open(argv[1], "rb").read()
        enc = encode(data, maxchain=chain)
        assert decode(enc) == data
        open(argv[2], "wb").write(enc)
        print(f"{len(data)} -> {len(enc)} bytes ({len(enc) / max(1, len(data)):.3f}) -> {argv[2]}")
    elif cmd == "verify":
        idxs = [int(a) for a in argv[1:]]
        text, ok, bad = verify(idxs or None)
        print(text)
        sys.exit(1 if bad else 0)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
