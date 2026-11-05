"""Build the patched Saturn disc: track 1 with the new DATA.BIN and MAIN_L.BIN.

The PS1's patch_disc.py for the Saturn's track 1 (MODE1/2352: 12-byte sync,
4-byte header {MM SS FF in BCD from LBA+150, mode 1}, 2048 data, 4-byte
EDC over bytes 0..2063, 8 zero, 276 ECC P/Q over 12..2075 with the header
INCLUDED - verified against the pristine sectors). ISO9660 layout: PVD at
16, path tables 18/19 (the root only), root directory sectors 20..25 with
226 files packed contiguously from A.BIN (LBA 26) to SDAIF_H0.AIF (ends at
203645); the track is 203720 sectors, so 75 empty ones trail it (track 2's
files start at disc LBA 203945 through the 225-sector pregap in its own
file and are not touched).

DATA.BIN (LBA 96, 5,355 sectors) is followed by MAIN_L.BIN at 5451 with no
slack, and its chunk table addresses chunks by a u16 sector RELATIVE to the
file, so a grown DATA.BIN cannot go anywhere but its own place: every file
after it shifts by the growth N (<= 75 sectors, the trailing gap absorbs
it; the track length and track 2 stay). Since satpack.py (the dense
re-layout, 5,237 sectors for the whole translation against the pristine
5,355) the file is usually SMALLER: it is written in place, the sectors up
to the pristine extent zeroed, nothing shifts, and the record carries the
real size. Every shifted sector gets a fresh header and EDC/ECC (numpy,
all 198,000 in ~20 s), every root directory record after DATA.BIN a new
extent, DATA.BIN's record the new size (both byte orders; GFS reads the
record, so a chunk past the old size is inside the file). A DATA.BIN the
same size as the original is written in place with nothing shifted.

**Growing track 1** (2026-09-28, the PS1's full-length text: every bank's
longs behind its bank took DATA.BIN 111 sectors past the gap). When the
shifted files run past the track's end, track 1 grows to hold them plus a
TAIL-sector gap (75, the pristine trailing gap) and the disc behind it
moves by `grow` sectors. Nothing addresses track 2/3 by
an absolute sector but the ISO directory (ACT1/2/3.CAT, WARNING.DA - no
FAD constant in A.BIN or MAIN_L.BIN) and the sector headers: their records
get +grow, the PVD's volume space size +grow, and track 2 is rewritten with
every sector header's MSF moved by grow (Mode 2: Form 1 ECC and Form 2 EDC
leave the header out, so only the header changes; the Mode 1 sectors of
its pregap are re-EDC'd). Track 3 (audio) and the cue (INDEX times are
per file) stay verbatim. `grow` 0 = the old behaviour, byte for byte.

The system area (sectors 0-15, the IP) is copied verbatim unless
`patched/saturn/IP.BIN` exists (saturn/tools/satsplash.py apply: the boot
screens' player in the IP; `satsplash.py off` removes it).

Outputs in patched/saturn/: `Snatcher (Japan) (Track 1).bin`, copies of
tracks 2 and 3 and the cue (the same names, so the cue is verbatim).
`SATURN_IMAGE="Snatcher (Japan) [dev]"` (the PS1's SNATCHER_IMAGE) writes
track 1 and the cue under that name instead - for a build while an
emulator holds the main image; the cue then names the shared tracks 2/3
(a grown track 1 writes that image's own track 2).

    python saturn/tools/satdisc.py [--dry]
"""
import os, sys, struct, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import numpy as np

SRC_DIR = os.path.join(ROOT, "discs", "iso_saturn_jp")
NAME = "Snatcher (Japan)"
SRC_T1 = os.path.join(SRC_DIR, f"{NAME} (Track 1).bin")
OUT_DIR = os.path.join(ROOT, "patched", "saturn")
OUT_NAME = os.environ.get("SATURN_IMAGE") or NAME
OUT_T1 = os.path.join(OUT_DIR, f"{OUT_NAME} (Track 1).bin")
PATCHED = {"DATA.BIN": os.path.join(OUT_DIR, "DATA.BIN"), "MAIN_L.BIN": os.path.join(OUT_DIR, "MAIN_L.BIN")}
RAW = 2352
DATA = 2048
ROOT_LBA, ROOT_SECTORS = 20, 6
T1_SECTORS = 203720
TAIL = 75                    # the pristine track 1's trailing empty sectors, kept when it grows
DISC_SECTORS = 232218        # the PVD's volume space size (tracks 1-3)
BATCH = 4096

# --- EDC/ECC (Neill Corlett's tables, as ps1/tools/patch_disc.py) ---------------
_edc = np.zeros(256, dtype=np.uint32)
for i in range(256):
    e = i
    for _ in range(8):
        e = (e >> 1) ^ (0xD8018001 if e & 1 else 0)
    _edc[i] = e
_ecc_f = np.zeros(256, dtype=np.uint8)
_ecc_b = np.zeros(256, dtype=np.uint8)
for i in range(256):
    j = ((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF
    _ecc_f[i] = j
    _ecc_b[i ^ j] = i


def _ecc_index(major_count, minor_count, major_mult, minor_inc):
    size = major_count * minor_count
    idx = np.zeros((major_count, minor_count), dtype=np.int32)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        for minor in range(minor_count):
            idx[major, minor] = index
            index += minor_inc
            if index >= size:
                index -= size
    return idx


_P_IDX = _ecc_index(86, 24, 2, 86)
_Q_IDX = _ecc_index(52, 43, 86, 88)


def _ecc_block(src, idx, major_count):
    """src (n, size) uint8 -> (n, 2*major_count) parity, vectorised over sectors."""
    n = src.shape[0]
    a = np.zeros((n, major_count), dtype=np.uint8)
    b = np.zeros((n, major_count), dtype=np.uint8)
    for minor in range(idx.shape[1]):
        t = src[:, idx[:, minor]]
        a ^= t
        b ^= t
        a = _ecc_f[a]
    a = _ecc_b[_ecc_f[a] ^ b]
    return np.concatenate([a, a ^ b], axis=1)


def fix_sectors(secs):
    """secs: (n, 2352) uint8 array with sync, header and data set; fills EDC, zero, ECC."""
    n = secs.shape[0]
    edc = np.zeros(n, dtype=np.uint32)
    for i in range(2064):
        edc = (edc >> 8) ^ _edc[(edc ^ secs[:, i]) & 0xFF]
    secs[:, 2064:2068] = edc.astype("<u4").view(np.uint8).reshape(n, 4)
    secs[:, 2068:2076] = 0
    block = secs[:, 12:2076]
    p = _ecc_block(block, _P_IDX, 86)
    secs[:, 2076:2248] = p
    q = _ecc_block(np.concatenate([block, p], axis=1), _Q_IDX, 52)
    secs[:, 2248:2352] = q
    return secs


def headers(lbas):
    """(n, 16) sync + BCD MSF header + mode 1 for an array of LBAs."""
    n = len(lbas)
    h = np.zeros((n, 16), dtype=np.uint8)
    h[:, 1:11] = 0xFF
    a = np.asarray(lbas) + 150
    m, rem = a // (75 * 60), a % (75 * 60)
    s, f = rem // 75, rem % 75
    bcd = lambda v: ((v // 10) << 4) | (v % 10)
    h[:, 12], h[:, 13], h[:, 14], h[:, 15] = bcd(m), bcd(s), bcd(f), 1
    return h


def make_sectors(lbas, data):
    """Raw sectors for `data` (bytes, a whole number of 2048-byte blocks) at `lbas`."""
    n = len(lbas)
    secs = np.zeros((n, RAW), dtype=np.uint8)
    secs[:, :16] = headers(lbas)
    secs[:, 16:2064] = np.frombuffer(data, dtype=np.uint8).reshape(n, DATA)
    return fix_sectors(secs)


# --- ISO9660 ------------------------------------------------------------------
def root_records(t1):
    """[(sector, offset, name, lba, size, flags)] of the root directory."""
    out = []
    for si in range(ROOT_SECTORS):
        t1.seek((ROOT_LBA + si) * RAW + 16)
        d = t1.read(DATA)
        i = 0
        while i < DATA and d[i]:
            lba = struct.unpack_from("<I", d, i + 2)[0]
            size = struct.unpack_from("<I", d, i + 10)[0]
            name = d[i + 33:i + 33 + d[i + 32]].decode("ascii", "replace").split(";")[0]
            out.append((ROOT_LBA + si, i, name, lba, size, d[i + 25]))
            i += d[i]
    return out


def root_size(t1, name):
    return next(r[4] for r in root_records(t1) if r[2] == name)


def layout(t1, sizes):
    """The output layout: {name: (old_lba, new_lba, size)} with DATA.BIN grown by
    `sizes['DATA.BIN']` and every later file shifted; returns (files, N, grow) -
    `grow` = the sectors track 1 grows by (the files moved past its TAIL gap)."""
    recs = [r for r in root_records(t1) if not r[5] & 2]
    recs.sort(key=lambda r: r[3])
    old = {r[2]: (r[3], r[4]) for r in recs}
    data_lba, data_size = old["DATA.BIN"]
    old_secs = (data_size + DATA - 1) // DATA
    new_size = sizes.get("DATA.BIN", data_size)
    new_secs = (new_size + DATA - 1) // DATA
    n = max(0, new_secs - old_secs)         # a smaller file (satpack's dense layout) stays in place, padded
    files = {}
    for name, (lba, size) in old.items():
        size = sizes.get(name, size)
        if name != "DATA.BIN":
            assert (size + DATA - 1) // DATA == (old[name][1] + DATA - 1) // DATA, f"{name} changed its sector count"
        # track 2's files (ACT*.CAT, WARNING.DA, disc LBA >= 203720) move only with a grown track 1
        files[name] = (lba, lba + n if data_lba < lba < T1_SECTORS else lba, size)
    last_end = max(nw + (s + DATA - 1) // DATA for o, nw, s in files.values() if o < T1_SECTORS)
    grow = last_end + TAIL - T1_SECTORS if last_end > T1_SECTORS else 0
    if grow:
        for name, (o, nw, s) in files.items():
            if o >= T1_SECTORS:
                files[name] = (o, nw + grow, s)
    return files, n, grow


def main(argv):
    dry = "--dry" in argv
    os.makedirs(OUT_DIR, exist_ok=True)
    t1 = open(SRC_T1, "rb")
    assert os.path.getsize(SRC_T1) == T1_SECTORS * RAW
    patched = {k: open(p, "rb").read() for k, p in PATCHED.items() if os.path.exists(p)}
    files, n, grow = layout(t1, {k: len(v) for k, v in patched.items()})
    T1 = T1_SECTORS + grow
    data_old, data_new, data_size = files["DATA.BIN"]
    old_secs = (root_size(t1, "DATA.BIN") + DATA - 1) // DATA
    print(f"DATA.BIN {data_size} bytes ({(data_size + DATA - 1) // DATA} sectors), grows by {n} sectors; "
          f"{len([1 for o, nw, _ in files.values() if o != nw])} files shift; "
          f"patched: {', '.join(patched) or 'nothing (a pristine rebuild)'}")
    tail = T1 - max(nw + (s + DATA - 1) // DATA for o, nw, s in files.values() if o < T1_SECTORS)
    print(f"trailing empty sectors after the shift: {tail}"
          + (f"; track 1 GROWS by {grow} sectors ({T1_SECTORS} -> {T1}), tracks 2/3 move with it" if grow else ""))
    if dry:
        for name, (o, nw, s) in sorted(files.items(), key=lambda kv: kv[1][1])[:6]:
            print(f"  {name:14s} {o:7d} -> {nw:7d}  {s} bytes")
        print("dry run: nothing written")
        return
    if os.path.exists(OUT_T1):
        try:
            open(OUT_T1, "r+b").close()
        except PermissionError:
            sys.exit("the image is open in an emulator - close it; image NOT touched")
    t0 = time.time()
    out = open(OUT_T1 + ".tmp", "wb")
    # 1. everything before DATA.BIN verbatim, the root directory rewritten
    t1.seek(0)
    out.write(t1.read(data_old * RAW))
    recs = root_records(t1)
    for si in range(ROOT_SECTORS):
        t1.seek((ROOT_LBA + si) * RAW)
        sec = bytearray(t1.read(RAW))
        for s, i, name, lba, size, flags in recs:
            if s != ROOT_LBA + si or flags & 2:
                continue
            o, nw, sz = files[name]
            struct.pack_into("<I", sec, 16 + i + 2, nw)
            struct.pack_into(">I", sec, 16 + i + 6, nw)
            struct.pack_into("<I", sec, 16 + i + 10, sz)
            struct.pack_into(">I", sec, 16 + i + 14, sz)
        arr = np.frombuffer(bytes(sec), dtype=np.uint8).reshape(1, RAW).copy()
        out.seek((ROOT_LBA + si) * RAW)
        out.write(fix_sectors(arr).tobytes())
    if grow:                                          # the PVD's volume space size
        t1.seek(16 * RAW)
        sec = bytearray(t1.read(RAW))
        assert sec[17:22] == b"CD001" and struct.unpack_from("<I", sec, 16 + 80)[0] == DISC_SECTORS
        struct.pack_into("<I", sec, 16 + 80, DISC_SECTORS + grow)
        struct.pack_into(">I", sec, 16 + 84, DISC_SECTORS + grow)
        arr = np.frombuffer(bytes(sec), dtype=np.uint8).reshape(1, RAW).copy()
        out.seek(16 * RAW)
        out.write(fix_sectors(arr).tobytes())
    ip_path = os.path.join(OUT_DIR, "IP.BIN")      # satsplash.py's IP: the boot screens (sectors 0-15)
    if os.path.exists(ip_path):
        ip = open(ip_path, "rb").read()
        assert len(ip) == 16 * DATA and ip[:16] == b"SEGA SEGASATURN ", ip_path
        out.seek(0)
        out.write(make_sectors(np.arange(16), ip).tobytes())
        print(f"IP from {ip_path} (satsplash)")
    out.seek(data_old * RAW)
    # 2. DATA.BIN's sectors from the patched file (or the pristine one)
    if "DATA.BIN" in patched:
        body = patched["DATA.BIN"]
    else:
        t1.seek(data_old * RAW)
        body = b"".join(t1.read(RAW)[16:16 + DATA] for _ in range((data_size + DATA - 1) // DATA))
    body += bytes(-len(body) % DATA)
    if len(body) < old_secs * DATA:
        body += bytes(old_secs * DATA - len(body))    # zero sectors up to the pristine extent: nothing shifts
    nsec = len(body) // DATA
    for s in range(0, nsec, BATCH):
        k = min(BATCH, nsec - s)
        out.write(make_sectors(np.arange(data_old + s, data_old + s + k), body[s * DATA:(s + k) * DATA]).tobytes())
    # 3. everything after: shifted by n with fresh headers; MAIN_L.BIN from the patched file
    first = data_old + nsec
    main_old, main_new, main_size = files["MAIN_L.BIN"]
    written = 0
    for lba in range(first, T1, BATCH):
        k = min(BATCH, T1 - lba)
        src_lba = lba - n
        t1.seek(src_lba * RAW)
        got = t1.read(max(0, min(k, T1_SECTORS - src_lba)) * RAW)
        raw = np.frombuffer(got, dtype=np.uint8).reshape(-1, RAW)
        data = np.zeros((k, DATA), dtype=np.uint8)
        data[:raw.shape[0]] = raw[:, 16:16 + DATA]     # past the pristine end: empty
        if "MAIN_L.BIN" in patched:
            lo, hi = max(lba, main_new), min(lba + k, main_new + (main_size + DATA - 1) // DATA)
            if lo < hi:
                m = patched["MAIN_L.BIN"]
                m += bytes(-len(m) % DATA)
                data[lo - lba:hi - lba] = np.frombuffer(m[(lo - main_new) * DATA:(hi - main_new) * DATA], dtype=np.uint8).reshape(-1, DATA)
        out.write(make_sectors(np.arange(lba, lba + k), data.tobytes()).tobytes())
        written += k
        if written % (BATCH * 12) == 0:
            print(f"  {lba + k}/{T1} sectors, {time.time() - t0:.0f}s", flush=True)
    out.close()
    assert os.path.getsize(OUT_T1 + ".tmp") == T1 * RAW
    if os.path.exists(OUT_T1):
        os.remove(OUT_T1)
    os.rename(OUT_T1 + ".tmp", OUT_T1)
    print(f"wrote {OUT_T1} in {time.time() - t0:.0f}s")
    t2name = f"{OUT_NAME if grow else NAME} (Track 2).bin"
    for t in ("2", "3"):
        src = os.path.join(SRC_DIR, f"{NAME} (Track {t}).bin")
        dst = os.path.join(OUT_DIR, f"{NAME} (Track {t}).bin")
        if t == "2" and grow:
            write_track2(src, os.path.join(OUT_DIR, t2name), grow)
            continue
        if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src) \
                or (t == "2" and not same_track2(src, dst)):
            shutil.copyfile(src, dst)
            print(f"copied track {t}")
    cue = open(os.path.join(SRC_DIR, f"{NAME}.cue"), encoding="utf-8").read()
    if OUT_NAME != NAME:
        cue = cue.replace(f"{NAME} (Track 1).bin", f"{OUT_NAME} (Track 1).bin")
        cue = cue.replace(f"{NAME} (Track 2).bin", t2name)
    open(os.path.join(OUT_DIR, f"{OUT_NAME}.cue"), "w", encoding="utf-8", newline="").write(cue)
    # read back: the directory, DATA.BIN's tail and MAIN_L.BIN's first sector
    with open(OUT_T1, "rb") as f:
        recs = {r[2]: r for r in root_records(f) if not r[5] & 2}
        for name in ("DATA.BIN", "MAIN_L.BIN", "LOGO.TRM", "SDAIF_H0.AIF", "ACT1.CAT", "WARNING.DA"):
            o, nw, sz = files[name]
            assert recs[name][3] == nw and recs[name][4] == sz, name
        f.seek(main_new * RAW)
        sec = f.read(RAW)
        if "MAIN_L.BIN" in patched:
            assert sec[16:16 + DATA] == patched["MAIN_L.BIN"][:DATA], "MAIN_L.BIN's first sector"
        assert sec[12:16] == bytes(headers([main_new])[0, 12:16]), "MAIN_L.BIN header"
    if grow:
        with open(os.path.join(OUT_DIR, t2name), "rb") as f:
            act1 = files["ACT1.CAT"][1]
            f.seek((act1 - T1) * RAW)
            assert f.read(16)[12:15] == bytes(headers([act1])[0, 12:15]), "ACT1.CAT's first sector header"
    print(f"read back: directory records, MAIN_L.BIN at {main_new}, DATA.BIN {data_size} bytes at {data_new}"
          + (f", track 2 from {T1} (ACT1.CAT at {files['ACT1.CAT'][1]})" if grow else ""))


def write_track2(src, dst, grow):
    """Track 2 with every sector header's MSF moved `grow` sectors on (the Mode 1
    pregap sectors re-EDC'd; Mode 2 checksums leave the header out)."""
    raw = np.fromfile(src, dtype=np.uint8).reshape(-1, RAW).copy()
    assert (raw[:, 1:11] == 0xFF).all(), "track 2: a sector without sync"
    bcd = lambda v: (v >> 4) * 10 + (v & 15)
    lba = (bcd(raw[:, 12].astype(np.int64)) * 60 + bcd(raw[:, 13].astype(np.int64))) * 75 \
        + bcd(raw[:, 14].astype(np.int64)) - 150
    assert (lba == np.arange(T1_SECTORS, T1_SECTORS + len(raw))).all(), "track 2's headers are not contiguous from track 1's end"
    raw[:, 12:15] = headers(lba + grow)[:, 12:15]
    m1 = raw[:, 15] == 1
    if m1.any():
        raw[m1] = fix_sectors(raw[m1])
    tmp = dst + ".tmp"
    raw.tofile(tmp)
    if os.path.exists(dst):
        os.remove(dst)
    os.rename(tmp, dst)
    print(f"wrote {dst}: {len(raw)} sectors moved {grow} on ({int(m1.sum())} Mode 1 re-EDC'd)")


def same_track2(src, dst):
    """A copied track 2 still carries the pristine headers (not a grown build's)."""
    with open(src, "rb") as a, open(dst, "rb") as b:
        return a.read(RAW * 2) == b.read(RAW * 2)


if __name__ == "__main__":
    main(sys.argv[1:])
