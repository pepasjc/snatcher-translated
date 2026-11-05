"""ACT1/2/3.CAT on the Saturn Snatcher: the 1,040 voice lines.

The three archives on track 2 are not directories of files: each is one
contiguous stream of IMA ADPCM (4-bit, mono, 22050 Hz, high nibble first)
holding the game's voice lines back to back, and the index that cuts it
into lines lives in the executable.  Track 2 is Mode 2 FORM 2 (submode
0x28), 2324 payload bytes per sector; `extract.py` copies only 2048 of
them, so the ACT*.CAT files under discs/extracted_saturn/ are lossy - this
tool reads the track image directly.

Voice table (MAIN_L.BIN at RAM 0x060EB5A8, file 0x3B5A8): 1,040 records
of 12 bytes, big-endian:
    u8  act        1/2/3 -> ACT1/2/3.CAT (name table 0x060EEA5C + 4*act)
    u8  pad
    u16 sector     sector within the archive (2324-byte payload units)
    u32 size       bytes of ADPCM
    u16 offset     byte offset within that sector (0..2323)
    u8  0x0A       constant (playback parameter)
    u8  pad
Lines are packed with no gaps: record N+1 starts where record N ends.
ACT1 = lines 0-254, ACT2 = 255-625, ACT3 = 626-1039.  The count is the
PS1's 1,040 mono XA streams exactly, and `match` proves every line is the
same recording (envelope correlation > 0.95 on 1,037, the other three are
the same line under noise); the Saturn order is roughly the PS1's
(channel, file) order but not exactly - use the map, not a formula.

Engine: sound id 0x700 + index is a voice line (dispatcher 0x060BB3CC:
0x500.. = the 16-byte BGM table at 0x060EE668, 0x600.. = ADPCM_xx.CAT
effects via 0x060BCDE0, 0x650-0x665 = 0x060BBD10, 0x700.. = voice via
0x060BD3AC(index)).  The scene bytecode carries the id as a BE16 word
(B010: `c0 04 e4 00 00 07 c6` = play line 198), every cue line of
ps1/translation/subs_B010.json is found that way.  0x060BD3AC(index) seeds
the streamer: [0x060EA2C0] = the line's sector, [0x060EA2C4] = offset<<16
| act<<8 | flags (low byte 0x0B at start; bits 2/3 toggle as the two
buffers fill), [0x060EA2BC] = 0 = ADPCM bytes decoded so far,
[0x060FABB4] = 0 = sectors read so far; 0x060BDCD0 (called from
0x060B165A each frame) opens ACTn.CAT, seeks sector + read-count and reads
4 form-2 sectors (0x2450 bytes) into the double buffer 0x060AB000 /
0x060AD450; the decoder 0x060BD940 (step table 0x060EA300, index table
0x060EA464, predictor 0x060EFE8C, step 0x060EFE90, index 0x060EFE94) turns
4,096 samples per call into the 1,024-entry PCM ring at 0x060FA350 for the
68000 driver.  A harness names the playing line by u16 0x060EA2C2 (sector)
+ u8 0x060EA2C5 (act) against this table, and its progress by
[0x060EA2BC] * 2 / 22050 s (the line is over when it reaches `size`).
Verified headless: at the JUNKER HQ entrance the engine played sectors
3715, 3729, 4190 of ACT1 = lines 198, 199, 227 = the PS1's B010_000,
B010_001, B010_035 (work/saturn/cat/probe_voice2.py).  The SDAIF streams
(the PS1's stereo reels, plain AIFF PCM, 171 files) are numbered by root-
directory order after SDAIF_00.AIF (0x060BCB84: n < 100 -> "%02d", else
letter A.. + digit: E0 = 140); the live stream number is u16 0x060EFE6A
(140 through the opening's newsreel = SDAIF_E0 = XAS_S000.XA[129]).
Beetle Saturn's RETRO_MEMORY_SYSTEM_RAM (id 2) is 2 MB: low work RAM
0x00200000.. at 0, high work RAM 0x06000000.. at 0x100000, halfwords
byte-swapped (read a BE u16 at A as LE u16 at A - 0x06000000 + 0x100000).

Usage (repo root; the track image is discs/iso_saturn_jp/... (Track 2).bin):
    python saturn/tools/satcat.py list [ACT]            the voice table
    python saturn/tools/satcat.py extract [IDX...]      lines -> work/saturn/voice/NNNN.wav (all by default)
    python saturn/tools/satcat.py raw                   ACT*.CAT full form-2 payloads -> work/saturn/cat/ACTn.f2
    python saturn/tools/satcat.py match PS1_WORK        envelope-match every line against the PS1 census
                                                        (PS1_WORK = a PS1 tree's work/ with master_lines.json
                                                        and xa_all/SND/XAS/*.wav) -> work/saturn/voice_map.json
"""
import os, sys, json, struct, wave
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

TRACK2 = os.path.join(ROOT, "discs", "iso_saturn_jp", "Snatcher (Japan) (Track 2).bin")
MAIN_L = os.path.join(ROOT, "discs", "extracted_saturn", "MAIN_L.BIN")
MAIN_BASE = 0x060B0000
TABLE_ADDR = 0x060EB5A8
TABLE_N = 1040
SEC = 2324                      # form-2 payload
RAW_SEC = 2352
RATE = 22050
OUT_WAV = os.path.join(WORK, "saturn", "voice")
OUT_CAT = os.path.join(WORK, "saturn", "cat")
MAP = os.path.join(WORK, "saturn", "voice_map.json")

# ACTn.CAT: (first sector within the track-2 image, sector count); from the
# track-1 ISO9660 root directory (LBA 203945/208788/217125 - 203720 track start,
# sizes 9918464/17073861/23243230 bytes in 2048-byte directory units).
ACTS = {1: (225, 4843), 2: (5068, 8337), 3: (13405, 11350)}

STEP = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73,
        80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494,
        544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499,
        2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487,
        12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767]
INDEX = [-1, -1, -1, -1, 2, 4, 6, 8]


def table(main=None):
    """The 1,040 voice records: [{idx, act, sector, size, offset}]."""
    m = main if main is not None else open(MAIN_L, "rb").read()
    o = TABLE_ADDR - MAIN_BASE
    out = []
    for i in range(TABLE_N):
        act, _, sec, size, off, _, _ = struct.unpack_from(">BBHIHBB", m, o + 12 * i)
        out.append({"idx": i, "act": act, "sector": sec, "size": size, "offset": off})
    return out


class Track2:
    def __init__(self, path=TRACK2):
        self.f = open(path, "rb")

    def payload(self, act, sector, nsec):
        """nsec form-2 payloads of ACTn.CAT starting at its sector `sector`."""
        first, count = ACTS[act]
        out = bytearray()
        for s in range(sector, min(sector + nsec, count)):
            self.f.seek((first + s) * RAW_SEC + 24)
            out += self.f.read(SEC)
        return bytes(out)

    def line(self, rec):
        nsec = (rec["offset"] + rec["size"] + SEC - 1) // SEC
        d = self.payload(rec["act"], rec["sector"], nsec)
        return d[rec["offset"]:rec["offset"] + rec["size"]]


def decode(data):
    """IMA ADPCM (the engine's 0x060BD940): high nibble first, 16-bit output."""
    try:
        import audioop                       # bit-exact with the SH-2 loop, and fast
        return audioop.adpcm2lin(data, 2, None)[0]
    except ImportError:
        pass
    pred = idx = 0
    out = bytearray()
    for b in data:
        for nib in (b >> 4, b & 15):
            step = STEP[idx]
            d = step >> 3
            if nib & 4:
                d += step
            if nib & 2:
                d += step >> 1
            if nib & 1:
                d += step >> 2
            pred = pred - d if nib & 8 else pred + d
            pred = max(-32768, min(32767, pred))
            idx = max(0, min(88, idx + INDEX[nib & 7]))
            out += struct.pack("<h", pred)
    return bytes(out)


def write_wav(path, pcm, rate=RATE):
    w = wave.open(path, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(pcm)
    w.close()


def cmd_list(recs, act=None):
    print(" idx act  sector  offset     size  samples    dur")
    for r in recs:
        if act and r["act"] != act:
            continue
        print(f"{r['idx']:4d}  {r['act']}  {r['sector']:6d}  {r['offset']:6d} {r['size']:8d} {r['size'] * 2:8d} {r['size'] * 2 / RATE:6.2f}")
    tot = sum(r["size"] for r in recs if not act or r["act"] == act)
    print(f"{tot} bytes, {tot * 2 / RATE / 60:.1f} min")


def cmd_extract(recs, idxs):
    os.makedirs(OUT_WAV, exist_ok=True)
    t = Track2()
    for i in idxs:
        r = recs[i]
        write_wav(os.path.join(OUT_WAV, f"{i:04d}.wav"), decode(t.line(r)))
    print(f"{len(idxs)} lines -> {OUT_WAV}")


def cmd_raw():
    os.makedirs(OUT_CAT, exist_ok=True)
    t = Track2()
    for act, (first, count) in ACTS.items():
        d = t.payload(act, 0, count)
        p = os.path.join(OUT_CAT, f"ACT{act}.f2")
        open(p, "wb").write(d)
        print(f"ACT{act}.CAT: {count} form-2 sectors, {len(d)} bytes -> {p}")


def envelope(x, rate, frame=0.05):
    import numpy as np
    n = int(rate * frame)
    m = len(x) // n
    if m == 0:
        return np.zeros(1)
    return np.sqrt((x[:m * n].astype(float).reshape(m, n) ** 2).mean(1))


def cmd_match(recs, ps1_work):
    """Match every Saturn line to a PS1 mono XA stream by RMS-envelope correlation."""
    import glob
    import numpy as np
    ml = json.load(open(os.path.join(ps1_work, "master_lines.json")))
    mono = [l for l in ml if l["xa"] == "M"]
    wavdir = os.path.join(ps1_work, "xa_all", "SND", "XAS")
    t = Track2()
    sat = [envelope(np.frombuffer(decode(t.line(r)), np.int16), RATE) for r in recs]
    ps = []
    for l in mono:
        w = wave.open(os.path.join(wavdir, l["key"] + ".wav"), "rb")
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16)
        if w.getnchannels() == 2:
            x = x[::2]
        ps.append(envelope(x, w.getframerate()))

    def score(a, b):
        best = -1.0
        for lag in range(-4, 5):
            x, y = (a[lag:], b) if lag >= 0 else (a, b[-lag:])
            m = min(len(x), len(y))
            if m < 4:
                continue
            x, y = x[:m], y[:m]
            if x.std() == 0 or y.std() == 0:
                continue
            best = max(best, float(np.corrcoef(x, y)[0, 1]))
        return best

    out = []
    for i, e in enumerate(sat):
        n = len(e)
        c = [(j, score(e, p)) for j, p in enumerate(ps) if abs(len(p) - n) <= max(6, n * 0.15)]
        c.sort(key=lambda z: -z[1])
        j, s = c[0] if c else (None, -1)
        r = dict(recs[i])
        if j is not None:
            r.update(ps1=mono[j]["key"], file=mono[j]["file"], chan=mono[j]["ch"], ps1_dur=mono[j]["dur"], corr=round(s, 4))
        out.append(r)
        if i % 100 == 0:
            print(i, r.get("ps1"), r.get("corr"))
    used = {}
    for r in out:
        used.setdefault(r.get("ps1"), []).append(r["idx"])
    dups = {k: v for k, v in used.items() if len(v) > 1}
    weak = [r["idx"] for r in out if r.get("corr", -1) < 0.9]
    json.dump(out, open(MAP, "w"), indent=0)
    print(f"{len(out)} lines -> {MAP}; distinct PS1 targets {len(used)}, duplicates {dups}, corr < 0.9: {weak}")


if __name__ == "__main__":
    recs = table()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        cmd_list(recs, int(sys.argv[2]) if len(sys.argv) > 2 else None)
    elif cmd == "extract":
        cmd_extract(recs, [int(a) for a in sys.argv[2:]] or list(range(TABLE_N)))
    elif cmd == "raw":
        cmd_raw()
    elif cmd == "match":
        cmd_match(recs, sys.argv[2])
    else:
        print(__doc__)
