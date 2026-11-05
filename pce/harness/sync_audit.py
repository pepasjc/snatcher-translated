"""Offline sync audit of the PC Engine's voiced subtitles (ADPCM lines).

    python pce/harness/sync_audit.py                 # every module, table of the flagged lines
    python pce/harness/sync_audit.py 190 --all       # one module, every multi-page line
    python pce/harness/sync_audit.py --max 0.75      # the flag threshold in seconds (default 0.75)

A voiced line with several pages turns them by its cells' share of the clip's
`turns` (pceturns.py) when it has them, else evenly. This checks the result
without an emulator, with the same chunks, hold markers and pace the build
writes, against when the Japanese voice actually starts each card's words
(its word timings, pceturns.py words; the speech share of the decoded clip
where none are cached):
the clip is decoded from the disc (pcevoice.py, cached in work/pce/voice/),
speech is found from its energy (20 ms frames), and each page turn is compared
with the moment the same share of the SPEECH (silence left out) has been said.
The difference is the drift a player sees. Lines over the threshold are listed
and the exit status is 1, so the regression can fail on them.

CD-DA cues are not checked here: each has its own start and end, timed from
the voice (cdda_<rec>.json), and cannot drift inside itself.
"""
import glob, json, os, sys, wave
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]

import numpy as np

TR = os.path.join(ROOT, "pce", "translation")
VOICE = os.path.join(WORK, "pce", "voice")
_wpath = os.path.join(WORK, "pce", "asr_words.json")      # pceturns.py words (dev only: Japanese)
WORDS = json.load(open(_wpath, encoding="utf-8")) if os.path.exists(_wpath) else {}


def speech_curve(path):
    """(seconds, cumulative share of speech at each 20 ms frame)."""
    w = wave.open(path)
    sr, ch = w.getframerate(), w.getnchannels()
    a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
    if ch > 1:
        a = a.reshape(-1, ch).mean(1)
    hop = max(1, int(sr * 0.02))
    n = len(a) // hop
    if n == 0:
        return 0.0, None
    rms = np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1))
    floor = np.percentile(rms, 20)
    voiced = rms > max(floor * 3, rms.max() * 0.08)
    # bridge gaps shorter than 120 ms (consonants, the ADPCM's own dips)
    v = voiced.copy()
    gap = 0
    for i in range(n):
        if not voiced[i]:
            gap += 1
        else:
            if 0 < gap <= 6:
                v[i - gap:i] = True
            gap = 0
    cum = np.cumsum(v) / max(1, v.sum())
    return n * 0.02, cum


def audit(rec, show_all=False, limit=0.75):
    """The flagged (or, show_all, every) multi-page line of a module: its page turns as the
    stub paces them - the same chunks, pause markers and frames-per-cell the build writes
    (pcesubs.card_ranges / card_chunks / pause_marks) - against the voice's speech."""
    import pcesubs as S
    import pcevoice as V
    path = os.path.join(TR, f"subs_{rec}.json")
    lines = {k: v for k, v in json.load(open(path, encoding="utf-8")).items() if not k.startswith("_")}
    out = []
    four = rec not in S.NO_RESIDENT
    for key, spec in lines.items():
        if not spec.get("en") or spec.get("display") == "graphic":
            continue
        speaker = spec.get("speaker")
        plain = spec.get("layout", "face") == "plain"
        try:
            act, nn = S.line_key(rec, key)
            ranges = S.card_ranges(spec["en"], spec.get("cards"), speaker,
                                   break_before=S.PAGE_BREAKS.get((rec, key)), plain=plain, four=four)
        except SystemExit:
            continue
        if len(ranges) < 2:
            continue
        ch = S.card_chunks(spec["en"], ranges, four, speaker, plain=plain)
        total = sum(S.cost(t, c) for t, c in ch if t is not None) + S.paced_name(spec, ranges)
        ch, fpc = S.turn_marks(rec, key, spec, ch, ranges, S.name_cost(speaker) if speaker else 0)
        if not fpc:
            fpc = S.duration_frames(rec, key) / max(1, total)   # the even pace (no `turns`)
        wav = os.path.join(VOICE, f"act{act}_{nn:02x}.wav")
        if not os.path.exists(wav):
            os.makedirs(VOICE, exist_ok=True)
            V.wav(act, nn, wav)
        secs, cum = speech_curve(wav)
        if cum is None:
            continue
        import pceturns
        ref = pceturns.reference(WORDS.get(f"{act}_{nn:02x}"), spec["en"], spec.get("cards") or [])
        if spec.get("turns_by") == "hand" and spec.get("turns"):
            ref = spec["turns"]           # set by hand from the word timings: the stub must keep to them
        rows = [len(card) for card in ranges]              # a card's rows = its chunks (one a row)
        texts = [(t, c) for t, c in ch if t is not None]
        allchars = max(1, sum(len(t) for t, c in texts))
        name = S.name_cost(speaker) if speaker and plain else 0     # (drawn on a plain page only, every one)
        # a page's time is its cells and holds as one byte in the stub (pcells: 255 at most)
        t, k, chars, page_rows, turns, drift = 0.0, 0, 0, 0, [], []
        pc = name
        i = 0
        while i < len(ch) and k < len(rows) - 1:
            item, colour = ch[i]
            if item is None:
                if isinstance(colour, tuple):
                    pc += colour[1]
                i += 1
                continue
            pc += S.cost(item, colour)
            chars += len(item)
            page_rows += 1
            i += 1
            if page_rows == rows[k]:
                while i < len(ch) and ch[i][0] is None and isinstance(ch[i][1], tuple):
                    pc += ch[i][1][1]
                    i += 1
                t += min(255, pc) * fpc
                share = chars / allchars
                if ref and k < len(ref):                    # the Japanese words' own timing
                    t_speech = ref[k]
                else:                                       # no words: the speech share
                    idx = int(np.searchsorted(cum, share + 1e-6, side="right"))
                    t_speech = min(idx, len(cum) - 1) * 0.02
                turns.append((round(t / 60, 2), round(t_speech, 2)))
                drift.append(t / 60 - t_speech)
                k += 1
                page_rows = 0
                pc = name
        if not drift:
            continue
        worst = max(drift, key=abs)
        cards = spec.get("cards") or []
        if show_all or abs(worst) > limit:
            out.append((rec, key, speaker or "", round(S.duration_frames(rec, key) / 60, 2), round(worst, 2), turns, cards))
    return out


def main():
    args = sys.argv[1:]
    limit = float(args[args.index("--max") + 1]) if "--max" in args else 0.75
    recs = [int(a) for a in args if a.isdigit()]
    if not recs:
        recs = sorted(int(os.path.basename(p)[5:-5]) for p in glob.glob(os.path.join(TR, "subs_*.json"))
                      if os.path.basename(p)[5:-5].isdigit())
    flagged, checked = [], 0
    for rec in recs:
        rows = audit(rec, "--all" in args, limit)
        flagged += [r for r in rows if abs(r[4]) > limit]
        for rec_, key, sp, length, worst, turns, cards in rows:
            mark = "DRIFT" if abs(worst) > limit else "ok   "
            print(f"{mark} {rec_:3d} {key:6} {sp:11} {length:5.1f}s  worst {worst:+.2f}s  "
                  f"turns (as paced / as spoken): {turns}")
            print(f"        {' || '.join(cards)}")
    print(f"\n{len(flagged)} line(s) drift more than {limit:.2f} s")
    sys.exit(1 if flagged else 0)


if __name__ == "__main__":
    main()
