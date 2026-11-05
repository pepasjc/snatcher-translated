# -*- coding: utf-8 -*-
"""Decode an XA-ADPCM voice line straight out of the disc image.

    python lib/xadec.py 48 2 28874 29322 out.wav     # file chan start end

The subtitle cues name their audio as {file, chan, start, end} - absolute
sectors of the interleaved XA file (SND/XAS/XAS_M000.XA, XAS_S000.XA) and
the subheader's file/channel bytes. Nothing on disk holds the wavs (they
were jPSXdec output under work/ and went with the 2026-09-12 wipe), so
this reads the Mode 2 Form 2 sectors of the pristine image, keeps the
ones whose subheader matches, and decodes them (psx-spx "CDROM XA Audio
ADPCM Compression"): 18 blocks of 128 bytes per sector, 16 bytes of
sound parameters (bytes 4..11 = one per unit) then 112 bytes of samples,
4-bit units of 28 samples, shift in the low nibble, filter in the high.
Stereo puts the left channel in the even units.

decode(image, lba0, lba1, file, chan) -> (rate, channels, samples)
wav(...)                               -> the same as WAV bytes
cached_wav(...)                        -> path under work/wav_cache/
"""
import io, os, struct, sys, wave
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

SECTOR = 2352
IMAGE = os.path.join(ROOT, "discs", "iso_ps1_jp", "Snatcher (Japan).bin")
CACHE = os.path.join(WORK, "wav_cache")

K0 = (0, 60, 115, 98)
K1 = (0, 0, -52, -55)


def _units(block, is_8bit):
    """Yield (param, [28 raw sample values as signed 16-bit-shifted ints]) per unit."""
    if is_8bit:
        for u in range(4):
            p = block[4 + u]
            raw = [block[16 + i * 4 + u] for i in range(28)]
            yield p, [((b ^ 0x80) - 0x80) << 8 for b in raw]
    else:
        for u in range(8):
            p = block[4 + u]
            byte_off = 16 + (u >> 1)
            if u & 1:
                raw = [block[byte_off + i * 4] >> 4 for i in range(28)]
            else:
                raw = [block[byte_off + i * 4] & 0xF for i in range(28)]
            yield p, [((n ^ 8) - 8) << 12 for n in raw]


def decode(image=IMAGE, lba0=0, lba1=0, file=0, chan=0):
    """Return (sample_rate, channels, list of int16) for sectors lba0..lba1
    (inclusive) whose subheader names `file`/`chan` and carries audio."""
    rate, channels = 37800, 1
    out = [[], []]
    state = [[0, 0], [0, 0]]          # per channel: old, older
    with open(image, "rb") as f:
        f.seek(lba0 * SECTOR)
        data = f.read((lba1 - lba0 + 1) * SECTOR)
    for s in range(0, len(data) - SECTOR + 1, SECTOR):
        sub = data[s + 16:s + 24]
        if sub[0] != file or sub[1] != chan or not (sub[2] & 0x04):
            continue
        ci = sub[3]
        channels = 2 if ci & 0x01 else 1
        rate = 18900 if ci & 0x04 else 37800
        is_8bit = bool(ci & 0x10)
        base = s + 24
        for b in range(18):
            block = data[base + b * 128: base + (b + 1) * 128]
            for u, (p, raw) in enumerate(_units(block, is_8bit)):
                ch = (u & 1) if channels == 2 else 0
                shift = p & 0x0F
                if shift > 12:
                    shift = 9
                flt = (p >> 4) & 0x03
                k0, k1 = K0[flt], K1[flt]
                old, older = state[ch]
                dst = out[ch]
                for v in raw:
                    smp = (v >> shift) + ((old * k0 + older * k1 + 32) >> 6)
                    if smp > 32767:
                        smp = 32767
                    elif smp < -32768:
                        smp = -32768
                    dst.append(smp)
                    older, old = old, smp
                state[ch] = [old, older]
    if channels == 2:
        n = min(len(out[0]), len(out[1]))
        samples = [0] * (2 * n)
        samples[0::2] = out[0][:n]
        samples[1::2] = out[1][:n]
    else:
        samples = out[0]
    return rate, channels, samples


def wav(image=IMAGE, lba0=0, lba1=0, file=0, chan=0):
    rate, channels, samples = decode(image, lba0, lba1, file, chan)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % len(samples), *samples))
    return buf.getvalue()


def cached_wav(file, chan, lba0, lba1, image=IMAGE):
    """Decode once, keep under work/wav_cache/ (scratch, never committed)."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"f{file}_c{chan}_{lba0}_{lba1}.wav")
    if not os.path.exists(path) or os.path.getsize(path) <= 44:
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(wav(image, lba0, lba1, file, chan))
        os.replace(tmp, path)
    return path


if __name__ == "__main__":
    if len(sys.argv) < 6:
        sys.exit(__doc__)
    file, chan, a, b = (int(x) for x in sys.argv[1:5])
    rate, channels, samples = decode(IMAGE, a, b, file, chan)
    with open(sys.argv[5], "wb") as fh:
        fh.write(wav(IMAGE, a, b, file, chan))
    print(f"{sys.argv[5]}: {rate} Hz x{channels}, {len(samples) // channels} frames, "
          f"{len(samples) / channels / rate:.2f} s")
