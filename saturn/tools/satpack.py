"""Rebuild DATA.BIN densely from a chunk list: the build's last DATA.BIN step.

DATA.BIN is 639 chunks addressed by the exec's table at 0x060E62F4 ({u16
sector, u16 size/2} each, sectors relative to the file; satdata.py). Until
this tool the build patched chunks in place and appended what outgrew its
slot (the font chunk 0, six banks with longs, every subtitled bank), and
the track had 75 spare sectors after the last file for that growth - six
were left. Konami's packer also left ~3% on the table: lz3.encode packs
556 of the 561 LZ chunks smaller than the originals.

This tool re-lays the whole file: every chunk re-encoded (LZ chunks with
lz3.encode, raw chunks verbatim), each at the next free sector after the
previous one in table order, and the table rewritten. Nothing in the game
addresses DATA.BIN except through the table (both seek paths, 0x060B22EC
and the reader at 0x060B2620, take the sector from it; A.BIN never opens
the file), so the layout is free. Pristine: 5,355 sectors; dense with the
pristine contents: 5,218.

The chunk list, per chunk index, first match wins:
  1. `patched/saturn/chunks/NNN.bin` - THE OVERRIDE CONTRACT for other
     tools (the graphics repacker): the chunk's content in DECODED form
     for an LZ chunk (what lz3.decode gives, the bytes the engine copies
     out of its decode buffer) and RAW for a raw chunk (21-98 and any
     other whose pristine bytes lz3 cannot decode). NNN is the table
     index, three digits (`104.bin`). Size and compression are this
     tool's business: the file may be any length, and an LZ override is
     packed here. Chunks the pipeline writes itself (0 the font, 21-59
     the banks: satapply, satlong, satsubs) are refused as overrides -
     `--allow-any` lifts that for an experiment.
  2. the current `patched/saturn/DATA.BIN` as `patched/saturn/MAIN_L.BIN`'s
     table describes it - i.e. what satapply, satlong and satsubs wrote,
     in place or appended; an LZ chunk is decoded from there (a chunk
     that no longer decodes is an error, not a raw chunk).
  3. the pristine file.

Packing: an LZ chunk whose content equals the pristine's keeps the smaller
of Konami's bytes and ours (five chunks pack larger with lz3 at the default
chain depth); anything else is lz3.encode'd. Two constraints of the
engine's STREAMED loader (0x060B2620 -> the job at 0x060B29E2/0x060B2AB8)
are checked on every packed chunk, because the first dense build hung the
opening at frame 17,644 (chunk 387) - a re-encoded stream is not the same
thing as Konami's to that loader:
  * The chunk is decoded IN PLACE: the packed bytes are read to the top of
    a 256 KB high-WRAM region (`0x26048000 - ceil16(size)`, output from
    `0x26008000`; or `0x26088000 - size` -> `0x26048000`) and the output
    grows up towards them. For a big chunk (387: 220 KB out of 59 KB) the
    output reaches the bit stream before its last word is read - in
    Konami's stream too: the original game decodes a garbage tail there and
    stops on a stray 0 token by the luck of the data above. Our stream's
    garbage phase read on into the exec. `inplace_margin` simulates the
    decode at that placement and reports the smallest distance between the
    output pointer and the next UNREAD byte of each stream; a chunk whose
    margin is negative keeps Konami's bytes (identical behaviour), and an
    override with a negative margin is refused with the numbers (pack it
    smaller or split the picture).
  * The read is whole sectors from that base, so `ceil2048(size) -
    ceil16(size)` bytes spill past the region's end into the neighbouring
    slot's decoded data. Konami's sizes spill what they spill; ours must
    not spill MORE: the packed chunk is zero-padded (past the stream, never
    read) until its spill is <= the original's, which never costs a sector.
Packed bytes are cached in
work/saturn/pack_cache/ by the sha1 of the decoded content, so only the
chunks a build changed cost encode time (the first full pack: 561 chunks,
~20 s on 15 processes; a rebuild with three changed banks: seconds).
Every packed chunk is decoded back and compared with its intended content,
every raw chunk compared byte for byte, before anything is written; the
table is read back out of the written exec against the written file.

Order: after satapply, satnames, satlong, satsubs (the tools that assume
the pristine layout - satlong's `place` puts grown banks into pristine
sector slots - which satapply restores every build); before satdisc, which
takes the file as it is (padding a shrunken one to its pristine extent).
`--dry` reports the layout without writing; `--chain N` = lz3's maxchain;
`--no-overrides` ignores patched/saturn/chunks/ (to isolate a fault).

    python saturn/tools/satpack.py [--dry] [--chain 256] [--allow-any] [--no-overrides]
"""
import hashlib, json, os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import lz3, satdata

OUT = os.path.join(ROOT, "patched", "saturn")
OUT_DATA = os.path.join(OUT, "DATA.BIN")
OUT_MAIN = os.path.join(OUT, "MAIN_L.BIN")
CHUNK_DIR = os.path.join(OUT, "chunks")
CACHE = os.path.join(WORK, "saturn", "pack_cache")
BUILD = os.path.join(WORK, "saturn", "build")
MAIN_BASE = 0x060B0000
TABLE_ADDR = 0x060E62F4
TABLE_N = 639
SECTOR = 2048
PIPELINE_CHUNKS = {0} | set(range(satdata.FIRST_BANK, satdata.LAST_BANK + 1))
PRISTINE_SECTORS = 5355


def read_table(exe):
    o = TABLE_ADDR - MAIN_BASE
    return [(s, w * 2) for s, w in struct.iter_unpack(">HH", exe[o:o + 4 * TABLE_N])]


def write_table(exe, rows):
    exe = bytearray(exe)
    o = TABLE_ADDR - MAIN_BASE
    for i, (sec, size) in enumerate(rows):
        assert 0 <= sec < 0x10000 and size % 2 == 0 and size // 2 < 0x10000, (i, sec, size)
        struct.pack_into(">HH", exe, o + 4 * i, sec, size // 2)
    return bytes(exe)


def chunk_of(data, rows, i):
    sec, size = rows[i]
    return bytes(data[sec * SECTOR:sec * SECTOR + size])


def kinds(pristine_data, pristine_rows):
    """'lz' or 'raw' per chunk, decided on the pristine bytes; plus the pristine
    packed bytes and, for LZ chunks, the decoded content."""
    kind, packed, decoded = [], [], []
    for i in range(TABLE_N):
        src = chunk_of(pristine_data, pristine_rows, i)
        packed.append(src)
        try:
            decoded.append(lz3.decode(src))
            kind.append("lz")
        except lz3.BadChunk:
            decoded.append(None)
            kind.append("raw")
    return kind, packed, decoded


REGION = 0x40000            # the in-place decode regions: 0x06008000..0x06048000, 0x06048000..0x06088000


def inplace_margin(src):
    """The streamed loader's in-place decode: min over the decode of (next unread
    byte of a stream - output pointer), the input at (REGION - len - 15) & ~15,
    the output from 0. Negative = the output clobbers input still to be read."""
    base = (REGION - len(src) - 15) & ~15
    outsize, nw, nh = struct.unpack_from(">IHH", src, 0)
    bits = 8; tok = bits + 4 * nw; lit = tok + 2 * nh
    bp = bits + 4; word = struct.unpack_from(">I", src, bits)[0]; nb = 32; tp = tok; lp = lit; out = 0
    lo = 10**9

    def getbit():
        nonlocal word, nb, bp
        nb -= 1
        t = word & 1
        word >>= 1
        if nb == 0:
            nb = 32
            word = struct.unpack_from(">I", src, bp)[0] if bp + 4 <= tok else 0
            bp += 4
        return t
    while True:
        if bp < tok:
            lo = min(lo, base + bp - out)
        if tp < lit:
            lo = min(lo, base + tp - out)
        if lp < len(src):
            lo = min(lo, base + lp - out)
        if getbit() == 0:
            out += 1; lp += 1
            continue
        if getbit() == 1:
            lp += 1; n = getbit(); n = (n << 1) | getbit(); n += 2
        else:
            w = struct.unpack_from(">H", src, tp)[0]; tp += 2
            if w == 0:
                break
            n = w & 15
            if n:
                n += 2
            else:
                n = src[lp]; lp += 1
        out += n
    return lo


def spill(size):
    """Bytes the whole-sector read of a `size`-byte chunk writes past its region."""
    return -(-size // SECTOR) * SECTOR - -(-size // 16) * 16


def pad_spill(ours, konami_size):
    """Zero-pad `ours` (after its stream) until its spill is <= Konami's; stays in the sector."""
    while spill(len(ours)) > spill(konami_size):
        ours += b"\0\0"
    return ours


def cache_key(content, chain):
    return hashlib.sha1(content + b"|lz3 chain=%d" % chain).hexdigest()


def _encode_job(args):
    i, content, chain, key = args
    enc = lz3.encode(content, maxchain=chain)
    assert lz3.decode(enc) == content, i
    os.makedirs(CACHE, exist_ok=True)
    tmp = os.path.join(CACHE, key + ".tmp%d" % os.getpid())
    open(tmp, "wb").write(enc)
    os.replace(tmp, os.path.join(CACHE, key + ".bin"))
    return i, enc


def pack_all(contents, kind, pristine_packed, pristine_decoded, chain, log, jobs=None):
    """{i: packed bytes} for every chunk: raw ones verbatim, LZ ones from the
    cache / Konami's bytes / lz3.encode (in parallel)."""
    packed = {}
    todo = []
    for i in range(TABLE_N):
        c = contents[i]
        if kind[i] == "raw":
            packed[i] = c
            continue
        key = cache_key(c, chain)
        cp = os.path.join(CACHE, key + ".bin")
        ours = open(cp, "rb").read() if os.path.exists(cp) else None
        if ours is not None and lz3.decode(ours) != c:
            log(f"  cache entry {key} for chunk {i} does not decode to its key - ignored")
            ours = None
        if ours is None:
            todo.append((i, c, chain, key))
        else:
            packed[i] = ours
    if todo:
        log(f"  encoding {len(todo)} chunks ({sum(len(t[1]) for t in todo)} decoded bytes)...")
        t0 = time.time()
        jobs = jobs or max(1, (os.cpu_count() or 2) - 1)
        if jobs > 1 and len(todo) > 1:
            import multiprocessing
            with multiprocessing.Pool(jobs) as pool:
                for i, enc in pool.imap_unordered(_encode_job, sorted(todo, key=lambda t: -len(t[1])), chunksize=1):
                    packed[i] = enc
        else:
            for job in todo:
                i, enc = _encode_job(job)
                packed[i] = enc
        log(f"  encoded in {time.time() - t0:.0f} s")
    kept = unsafe = padded = 0
    for i in range(TABLE_N):
        if kind[i] != "lz":
            continue
        if len(packed[i]) % 2:
            packed[i] += b"\0"          # the table counts halfwords
        same = contents[i] == pristine_decoded[i]
        if same and len(pristine_packed[i]) <= len(packed[i]):
            packed[i] = pristine_packed[i]
            kept += 1
            continue
        m = inplace_margin(packed[i])
        if m < 0:
            if same:
                log(f"  chunk {i}: our stream's in-place margin is {m} (Konami's "
                    f"{inplace_margin(pristine_packed[i])}) - keeps Konami's bytes")
                packed[i] = pristine_packed[i]
                unsafe += 1
                continue
            sys.exit(f"chunk {i} (an override): the in-place decode would overwrite unread input "
                     f"(margin {m} bytes at {len(packed[i])} packed / {len(contents[i])} decoded); "
                     f"the streamed loader cannot take it - pack it smaller or split it")
        before = len(packed[i])
        packed[i] = pad_spill(packed[i], len(pristine_packed[i]))
        padded += len(packed[i]) != before
    if kept:
        log(f"  {kept} unchanged chunks keep Konami's bytes (not larger than ours)")
    if unsafe:
        log(f"  {unsafe} chunks keep Konami's bytes for the in-place decode")
    if padded:
        log(f"  {padded} chunks zero-padded so the whole-sector read spills no further than the original's")
    for i in range(TABLE_N):
        if len(packed[i]) % 2:
            packed[i] += b"\0"
    return packed


def layout(packed):
    """Dense: chunk i at the sector after chunk i-1's last. [(sector, size)]."""
    rows, sec = [], 0
    for i in range(TABLE_N):
        rows.append((sec, len(packed[i])))
        sec += (len(packed[i]) + SECTOR - 1) // SECTOR
    return rows, sec


def assemble(packed, rows, nsec):
    data = bytearray(nsec * SECTOR)
    for i, (sec, size) in enumerate(rows):
        data[sec * SECTOR:sec * SECTOR + size] = packed[i]
    return bytes(data)


def main(argv):
    dry = "--dry" in argv
    allow_any = "--allow-any" in argv
    chain = lz3.MAXCHAIN
    if "--chain" in argv:
        chain = int(argv[argv.index("--chain") + 1])
    lines = []

    def log(m=""):
        print(m, flush=True)
        lines.append(m)

    t0 = time.time()
    pristine_data = open(satdata.DATA, "rb").read()
    pristine_exe = open(satdata.MAIN, "rb").read()
    pristine_rows = read_table(pristine_exe)
    kind, pristine_packed, pristine_decoded = kinds(pristine_data, pristine_rows)
    log(f"pristine DATA.BIN: {len(pristine_data) // SECTOR} sectors, {kind.count('lz')} LZ chunks, {kind.count('raw')} raw")

    # 2. the current patched file (what the earlier tools wrote), else pristine
    contents = list(pristine_decoded)
    for i in range(TABLE_N):
        if kind[i] == "raw":
            contents[i] = pristine_packed[i]
    src = "pristine"
    cur_secs = len(pristine_data) // SECTOR
    changed = []
    if os.path.exists(OUT_DATA) and os.path.exists(OUT_MAIN):
        cur_data = open(OUT_DATA, "rb").read()
        cur_exe = open(OUT_MAIN, "rb").read()
        cur_rows = read_table(cur_exe)
        cur_secs = (len(cur_data) + SECTOR - 1) // SECTOR
        src = OUT_DATA
        for i in range(TABLE_N):
            sec, size = cur_rows[i]
            if sec * SECTOR + size > len(cur_data):
                sys.exit(f"chunk {i}'s table entry ({sec}, {size}) runs past {OUT_DATA}")
            c = chunk_of(cur_data, cur_rows, i)
            if kind[i] == "lz":
                try:
                    c = lz3.decode(c)
                except lz3.BadChunk as e:
                    sys.exit(f"chunk {i} in {OUT_DATA} is an LZ chunk that no longer decodes ({e})")
            if c != contents[i]:
                changed.append(i)
            contents[i] = c
    log(f"chunk contents from {src} ({cur_secs} sectors): {len(changed)} differ from pristine"
        + (f": {' '.join(map(str, changed))}" if changed else ""))

    # 1. overrides
    overrides = []
    if "--no-overrides" in argv:
        log(f"overrides from {CHUNK_DIR} skipped (--no-overrides)")
    elif os.path.isdir(CHUNK_DIR):
        for fn in sorted(os.listdir(CHUNK_DIR)):
            if not (fn.endswith(".bin") and fn[:-4].isdigit()):
                continue
            i = int(fn[:-4])
            if not 0 <= i < TABLE_N:
                sys.exit(f"{fn}: no chunk {i}")
            if i in PIPELINE_CHUNKS and not allow_any:
                sys.exit(f"{fn}: chunk {i} is written by the pipeline (the font, the banks) - "
                         f"not an override (--allow-any to force)")
            c = open(os.path.join(CHUNK_DIR, fn), "rb").read()
            if kind[i] == "raw" and len(c) % 2:
                c += b"\0"
            contents[i] = c
            overrides.append(i)
    if "--no-overrides" not in argv:
        log(f"overrides from {CHUNK_DIR}: {len(overrides)}" + (f": {' '.join(map(str, overrides))}" if overrides else ""))

    # pack, lay out, verify
    packed = pack_all(contents, kind, pristine_packed, pristine_decoded, chain, log)
    rows, nsec = layout(packed)
    data = assemble(packed, rows, nsec)
    for i in range(TABLE_N):
        got = chunk_of(data, rows, i)
        if kind[i] == "lz":
            assert lz3.decode(got) == contents[i], f"chunk {i} does not decode back"
        else:
            assert got == contents[i], f"chunk {i} raw bytes differ"
    lz_bytes = sum(len(packed[i]) for i in range(TABLE_N) if kind[i] == "lz")
    lz_pristine = sum(len(pristine_packed[i]) for i in range(TABLE_N) if kind[i] == "lz")
    log(f"packed: LZ chunks {lz_pristine} -> {lz_bytes} bytes ({lz_bytes / lz_pristine:.3f}); "
        f"layout {nsec} sectors (pristine {PRISTINE_SECTORS}, input {cur_secs}); "
        f"track slack after satdisc: {PRISTINE_SECTORS + 75 - nsec} sectors")
    log("verified: every LZ chunk decodes back to its content, every raw chunk byte-identical")
    os.makedirs(BUILD, exist_ok=True)
    json.dump({"sectors": nsec, "chain": chain, "overrides": overrides, "changed": changed,
               "table": [{"chunk": i, "sector": s, "size": z, "kind": kind[i]} for i, (s, z) in enumerate(rows)]},
              open(os.path.join(BUILD, "pack_layout.json"), "w"), indent=1)
    if dry:
        log("dry run: nothing written")
    else:
        exe = open(OUT_MAIN, "rb").read() if os.path.exists(OUT_MAIN) else pristine_exe
        exe = write_table(exe, rows)
        open(OUT_DATA, "wb").write(data)
        open(OUT_MAIN, "wb").write(exe)
        # read back
        back = read_table(open(OUT_MAIN, "rb").read())
        assert back == rows
        d2 = open(OUT_DATA, "rb").read()
        assert len(d2) == nsec * SECTOR
        for i in (0, 21, 22, 100, TABLE_N - 1):
            assert chunk_of(d2, back, i) == packed[i]
        log(f"wrote {OUT_DATA} ({nsec} sectors) and the table in {OUT_MAIN}; read back")
    log(f"done in {time.time() - t0:.0f} s")
    with open(os.path.join(BUILD, "pack_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1:])
