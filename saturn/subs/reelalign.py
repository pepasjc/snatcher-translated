"""Align every Saturn reel (SDAIF_*.AIF) with its PS1 twin (an XAS_S000.XA stream) by audio.

The reel cue windows were laid over the Saturn file by PROPORTION of the PS1 stream's
sector span, but the two are different cuts of the same recording (the HQ arrival: 71.3 s
of PS1 sectors against a 65.0-s AIFF - every card ran 9 % early and drifted, 2026-09-16).
This fits, per reel, the map  saturn_t = a * ps1_t + b  from the two RMS envelopes: the
best lag by cross-correlation at a few scales (1.0 = same recording trimmed at an end,
71.3/65 = the whole span stretched), written into work/saturn/cat/reel_align.json as
{ps1 key: {a, b, corr, ...}}; gen_subs reads it for every reel cue.

    python saturn/subs/reelalign.py            all mapped reels
    python saturn/subs/reelalign.py 98 121     the SDAIF numbers given
"""
import os, sys, json, wave, math
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ("lib", "saturn/tools", "saturn/subs")]
import numpy as np
import xadec
if not os.path.exists(xadec.IMAGE):                      # this worktree has no PS1 disc: the main tree's
    for alt in (os.path.join(os.path.dirname(ROOT), "snatcher", "discs", "iso_ps1_jp", "Snatcher (Japan).bin"),):
        if os.path.exists(alt):
            xadec.IMAGE = alt

REEL_MAP = os.path.join(WORK, "saturn", "cat", "reel_map.json")
MASTER = os.path.join(WORK, "master_lines.json")
SDAIF_DIR = os.path.join(ROOT, "discs", "extracted_saturn")
OUT = os.path.join(WORK, "saturn", "cat", "reel_align.json")
FRAME = 0.02                      # envelope frame, seconds


def aiff_samples(path):
    """Mono float samples and the rate of a plain AIFF (16-bit BE)."""
    import aifc, warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        f = aifc.open(path, "rb")
        n, ch, rate = f.getnframes(), f.getnchannels(), f.getframerate()
        raw = f.readframes(n); f.close()
    a = np.frombuffer(raw, dtype=">i2").reshape(-1, ch).astype(np.float32).mean(axis=1)
    return a, rate


def wav_samples(path):
    with wave.open(path, "rb") as w:
        ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype="<i2").reshape(-1, ch).astype(np.float32).mean(axis=1)
    return a, rate


def envelope(a, rate):
    win = int(rate * FRAME)
    m = len(a) // win
    e = np.sqrt((a[:m * win].reshape(m, win) ** 2).mean(axis=1))
    e = np.log1p(e / (e.mean() + 1e-6))
    return e - e.mean()


def best_lag(x, y, max_lag):
    """Lag (in frames) that maximises the normalised cross-correlation of y against x:
    y[t] ~ x[t - lag]. Positive lag = y is later than x."""
    n = max(len(x), len(y)) + 2 * max_lag
    fx = np.fft.rfft(x, n); fy = np.fft.rfft(y, n)
    cc = np.fft.irfft(fy * np.conj(fx), n)
    cc = np.concatenate([cc[-max_lag:], cc[:max_lag + 1]])
    lag = int(np.argmax(cc)) - max_lag
    # the normalised correlation at that lag
    if lag >= 0:
        xa, ya = x[:len(y) - lag], y[lag:lag + len(x)]
    else:
        xa, ya = x[-lag:-lag + len(y)], y[:len(x) + lag]
    m = min(len(xa), len(ya))
    corr = float(np.corrcoef(xa[:m], ya[:m])[0, 1]) if m > 10 else -1.0
    return lag, corr


def align(entry, ml):
    """One reel: the map saturn_t = a * ps1_t + b (ps1_t from the stream's first sector)."""
    st = ml[entry["ps1"]]
    sat, srate = aiff_samples(os.path.join(SDAIF_DIR, entry["sdaif"]))
    wavp = xadec.cached_wav(st["file"], st["ch"], st["start"], st["end"], image=xadec.IMAGE)
    ps1, prate = wav_samples(wavp)
    es, ep = envelope(sat, srate), envelope(ps1, prate)
    ps1_dur, sat_dur = len(ps1) / prate, len(sat) / srate
    best = None
    for a in (1.0, sat_dur / ps1_dur):
        # resample the PS1 envelope by a: ps1 frame i -> saturn frame a*i
        idx = np.arange(int(len(ep) * a)) / a
        epa = np.interp(idx, np.arange(len(ep)), ep)
        lag, corr = best_lag(epa, es, int(15 / FRAME))
        cand = dict(a=round(a, 5), b=round(lag * FRAME, 3), corr=round(corr, 4))
        if best is None or corr > best["corr"]:
            best = cand
    best.update(ps1=entry["ps1"], sdaif=entry["sdaif"], n=entry["n"], ps1_dur=round(ps1_dur, 2), sat_dur=round(sat_dur, 2))
    return best


def main(argv):
    rm = json.load(open(REEL_MAP))
    ml = {m["key"]: m for m in json.load(open(MASTER, encoding="utf-8"))}
    want = {int(x) for x in argv if x.isdigit()}
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for e in rm:
        if want and e["n"] not in want:
            continue
        if e["ps1"] not in ml:
            continue
        try:
            r = align(e, ml)
        except Exception as ex:
            print(f"{e['sdaif']} <- {e['ps1']}: {ex}")
            continue
        out[e["ps1"]] = r
        print(f"{e['sdaif']:14} <- {e['ps1']:18} ps1 {r['ps1_dur']:6.1f}s sat {r['sat_dur']:6.1f}s  a {r['a']:.4f} b {r['b']:+6.2f}s corr {r['corr']:.3f}")
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"{len(out)} reels -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
