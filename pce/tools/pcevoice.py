"""The PCE's voice lines: the per-act ADPCM tables, decoded to WAV for ASR.

Each act has a voice table (group 4 of the file table: recs 86, 90, 94,
98, 102, 106, three sectors each; the `1c f3 NN GG` opcode names record
NN of table GG). A record is eight bytes `{type, ch, 0, sec lo, sec hi,
count, 0, rate}`: the line is `count` sectors of OKI MSM5205 ADPCM from
track-relative sector `sec` in the disc's tail (rel 7858 on), played at
32000 / (16 - rate) Hz (rate 0x0E = 16 kHz). The engine's play code is in
the text bank: $6281 (AD_TRANS) / $62C2 (AD_PLAY), the record pointer
$5E/$5F, the table bank $1A + [$3F80] at MPR4 ($6140).

  python pce/tools/pcevoice.py <act> [NN ...]     # WAVs into work/pce/voice/act<act>_NN.wav
  python pce/tools/pcevoice.py module <rec>        # every voice line the module plays
"""
import os, struct, sys, json, re
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import pcescene as S

TABLES = {0: 86, 1: 90, 2: 94, 3: 98, 4: 102, 5: 106}     # act index (the opcode's 4th byte) -> table record
OUT = os.path.join(WORK, "pce", "voice")
VOICE = re.compile(rb"\x1c\xf3(.)(.)", re.S)

STEPS = [16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143,
         158, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
         1060, 1166, 1282, 1411, 1552]
ADJUST = [-1, -1, -1, -1, 2, 4, 6, 8]


def decode(data):
    """MSM5205 4-bit ADPCM -> 16-bit PCM samples (high nibble first)."""
    out, acc, step = [], 0, 0
    for b in data:
        for nib in (b >> 4, b & 15):
            st = STEPS[step]
            delta = st >> 3
            if nib & 1:
                delta += st >> 2
            if nib & 2:
                delta += st >> 1
            if nib & 4:
                delta += st
            if nib & 8:
                acc -= delta
            else:
                acc += delta
            acc = max(-2048, min(2047, acc))
            step = max(0, min(48, step + ADJUST[nib & 7]))
            out.append(acc * 16)
    return out


def record(act, nn):
    t = bytes(S.block(TABLES[act], 3))
    r = t[(nn - 1) * 8:nn * 8]
    return {"type": r[0], "ch": r[1], "sector": r[3] | r[4] << 8 | r[2] << 16, "count": r[5], "rate": r[7]}


def wav(act, nn, path=None):
    r = record(act, nn)
    data = bytes(S.block(r["sector"], r["count"]))
    pcm = decode(data)
    # the silence at a line's head is coded as zero nibbles, which the MSM5205
    # ramps to a DC offset: take the drift out before ASR
    k = 800
    import numpy as np
    x = np.array(pcm, float)
    x -= np.convolve(x, np.ones(k) / k, mode="same")
    pcm = np.clip(x, -32767, 32767).astype("<i2")
    hz = 32000 // (16 - r["rate"])
    path = path or os.path.join(OUT, f"act{act}_{nn:02x}.wav")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        body = pcm.tobytes()
        f.write(b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVEfmt " +
                struct.pack("<IHHIIHH", 16, 1, 1, hz, hz * 2, 2, 16) + b"data" + struct.pack("<I", len(body)) + body)
    return path, r, len(pcm) / hz


def module_voices(rec, n):
    """[(act, NN)] in bytecode order, the duplicates kept once."""
    import pcescript as PS
    mod = bytes(S.block(rec, n))
    strings, _ = PS.strings_of(mod)
    end = strings[0][0] if strings else len(mod)
    seen, out = set(), []
    for m in VOICE.finditer(mod[:end]):
        nn, act = m.group(1)[0], m.group(2)[0]
        if act in TABLES and (act, nn) not in seen:
            seen.add((act, nn))
            out.append((act, nn))
    return out


if __name__ == "__main__":
    if sys.argv[1] == "module":
        rec = int(sys.argv[2])
        n = [e["n"] for e in json.load(open(os.path.join(WORK, "pce", "filetable.json")))["1"] if e["rec"] == rec][0]
        for act, nn in module_voices(rec, n):
            path, r, secs = wav(act, nn)
            print(f"act {act} {nn:02x}: sector {r['sector']} x{r['count']} {secs:.1f}s -> {path}")
    else:
        act = int(sys.argv[1])
        for a in sys.argv[2:]:
            path, r, secs = wav(act, int(a, 16))
            print(f"act {act} {int(a, 16):02x}: sector {r['sector']} x{r['count']} {secs:.1f}s -> {path}")
