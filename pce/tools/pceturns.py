"""When each page of a voiced line should turn: `turns` in the PC Engine cue files.

    python pce/tools/pceturns.py words [rec ...]     # Japanese word timings (faster-whisper) -> work/pce/asr_words.json
    python pce/tools/pceturns.py turns [rec ...]     # report the turns
    python pce/tools/pceturns.py turns --write       # write them into pce/translation/subs_<rec>.json

A voiced line with several cards would otherwise turn its pages at one even pace over
the clip (pcesubs: frames-per-cell from the ADPCM record), so a line with pauses drifts.
Here each card break of the English is matched to the moment the Japanese says the
corresponding words:

- the clip is decoded from the disc (pcevoice) and transcribed with word timestamps
  (faster-whisper medium, Japanese, the same prompt as lib/asr; cached - never committed,
  it holds Japanese);
- the Japanese splits into sentences at 。？！?! and at gaps of 0.3 s or more between words;
- each English card break (a share of the English text) takes the start of the Japanese
  sentence nearest to the same share of the Japanese text when one is within MATCH; else
  the time of the Japanese word at that share;
- `turns` = the seconds from the clip's start at which cards 2, 3, ... come up.

The build (pcesubs._table) paces each card to its turn: the line's frames-per-cell is
set so every card's text fits its slot, and hold markers fill the rest of the slot.
Only numbers go into the cue files; a line without `turns` keeps the even pace.
pce/harness/sync_audit.py checks the result.
"""
import glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]

TR = os.path.join(ROOT, "pce", "translation")
WORDS = os.path.join(WORK, "pce", "asr_words.json")
VOICE = os.path.join(WORK, "pce", "voice")
MATCH = 0.15                    # share of the text within which a Japanese sentence start is taken
GAP = 0.3                       # seconds between words that also end a Japanese sentence
END = re.compile(r"[。？！?!]$")


def multi_card_lines(recs=None):
    """[(rec, key, spec)] for every voiced line with two cards or more."""
    out = []
    for p in sorted(glob.glob(os.path.join(TR, "subs_*.json"))):
        stem = os.path.basename(p)[5:-5]
        if not stem.isdigit() or (recs and int(stem) not in recs):
            continue
        for k, v in json.load(open(p, encoding="utf-8")).items():
            if k.startswith("_") or not isinstance(v, dict) or v.get("display") == "graphic":
                continue
            if len(v.get("cards") or []) >= 2:
                out.append((int(stem), k, v))
    return out


def clip(rec, key):
    import pcesubs as S
    import pcevoice as V
    act, nn = S.line_key(rec, key)
    path = os.path.join(VOICE, f"act{act}_{nn:02x}.wav")
    if not os.path.exists(path):
        os.makedirs(VOICE, exist_ok=True)
        V.wav(act, nn, path)
    return f"{act}_{nn:02x}", path


def cmd_words(recs):
    from faster_whisper import WhisperModel
    import numpy as np, wave
    cache = json.load(open(WORDS, encoding="utf-8")) if os.path.exists(WORDS) else {}
    prompt_path = os.path.join(ROOT, "lib", "asr", "asr_prompt.txt")
    prompt = open(prompt_path, encoding="utf-8").read().strip() if os.path.exists(prompt_path) else None
    model = None
    todo = {}
    for rec, key, _ in multi_card_lines(recs):
        cid, path = clip(rec, key)
        if cid not in cache:
            todo[cid] = path
    print(f"{len(todo)} clips to transcribe ({len(cache)} cached)", flush=True)
    for n, (cid, path) in enumerate(sorted(todo.items()), 1):
        if model is None:
            model = WhisperModel("medium", device="cpu", compute_type="int8")
        w = wave.open(path)
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        if w.getnchannels() > 1:
            a = a.reshape(-1, w.getnchannels()).mean(1)
        m = int(len(a) * 16000 / sr)
        a16 = np.interp(np.linspace(0, len(a) - 1, m), np.arange(len(a)), a).astype(np.float32)
        segs, _ = model.transcribe(a16, language="ja", vad_filter=False, word_timestamps=True,
                                   initial_prompt=prompt)
        cache[cid] = [[x.word, round(x.start, 2), round(x.end, 2)] for s in segs for x in (s.words or [])]
        if n % 10 == 0 or n == len(todo):
            json.dump(cache, open(WORDS, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  {n}/{len(todo)}", flush=True)
    json.dump(cache, open(WORDS, "w", encoding="utf-8"), ensure_ascii=False)


def reference(words, en, cards):
    """The seconds at which cards 2.. should come up, from the Japanese words; None when
    there are no words."""
    if not words:
        return None
    chars = [len(w[0].strip()) for w in words]
    total = max(1, sum(chars))
    starts = []                                         # (share of the Japanese before it, time)
    run = 0
    for i, w in enumerate(words):
        if i and (END.search(words[i - 1][0].strip()) or w[1] - words[i - 1][2] >= GAP):
            starts.append((run / total, w[1]))
        run += chars[i]
    en_words = en.replace("￥", " ").split()
    en_total = max(1, len(" ".join(en_words)))
    out, done = [], 0
    for card in cards[:-1]:
        done += len(" ".join(card.replace("|", " ").split())) + 1
        share = min(1.0, done / en_total)
        best = min(starts, key=lambda s: abs(s[0] - share)) if starts else None
        if best and abs(best[0] - share) <= MATCH and not (out and best[1] <= out[-1]):
            t = best[1]
        else:                                           # the word under that share (also when the
            # nearest sentence start is the last card's: two cards inside one Japanese sentence
            # took the same start and the second came up 0.4 s after the first)
            run, t = 0, words[-1][1]
            for i, w in enumerate(words):
                run += chars[i]
                if run / total >= share:
                    t = words[i + 1][1] if i + 1 < len(words) else w[2]
                    break
        if out and t <= out[-1] + 0.4:
            t = out[-1] + 0.4
        out.append(round(t, 2))
    return out


def cmd_turns(recs, write):
    cache = json.load(open(WORDS, encoding="utf-8")) if os.path.exists(WORDS) else {}
    by_file = {}
    for rec, key, spec in multi_card_lines(recs):
        cid, _ = clip(rec, key)
        t = reference(cache.get(cid), spec["en"], spec["cards"])
        if t is None:
            print(f"{rec} {key}: no words cached - run `words` first")
            continue
        print(f"{rec} {key:6} {t}  {' || '.join(spec['cards'])[:110]}")
        by_file.setdefault(rec, {})[key] = t
    if not write:
        return
    for rec, turns in by_file.items():
        path = os.path.join(TR, f"subs_{rec}.json")
        raw = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in raw else "\n"
        doc = json.loads(raw)
        for key, t in turns.items():
            if doc[key].get("turns_by") == "hand":      # read off the word timings by hand: kept
                continue
            doc[key]["turns"] = t
        text = json.dumps(doc, ensure_ascii=False, indent=1).replace("\n", nl)
        open(path, "w", encoding="utf-8", newline="").write(text + (nl if raw.endswith(nl) else ""))
    print(f"turns written for {sum(len(t) for t in by_file.values())} lines")


if __name__ == "__main__":
    args = sys.argv[1:]
    recs = [int(a) for a in args[1:] if a.isdigit()] or None
    if args and args[0] == "words":
        cmd_words(recs)
    elif args and args[0] == "turns":
        cmd_turns(recs, "--write" in args)
    else:
        print(__doc__)
