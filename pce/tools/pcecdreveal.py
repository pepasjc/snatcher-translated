"""CD-DA cues reveal their words with the voice: each cue's `reveal_end` from the track's
own word stamps.

A CD-DA cue's page comes up at its start and stays to its end, its words appearing one
by one at a single rate (the entry's fpc). The ends run on to the next cue so the words
stay up between lines, and the rate came from that whole span: "You're the only one who
can fight the Snatchers now" (350, track 3) is said in 2.4 s and its words trickled in
over 15, the last one 12 s after the voice (Luiz, 2026-10-18: subtitles out of sync after
the factory). So every cue gets `reveal_end`: the end of the last word spoken inside it,
from faster-whisper's word timestamps on the track (Japanese, medium); the build takes
the rate from start..reveal_end and leaves the end where it was, so a page turns as its
words are said and the last one stays until the next cue.

A word counts when whisper gives it probability >= MIN_PROB and its segment is not a
repeat (whisper fills silence and music with the last name it heard: "ギリアン、ギリアン、
ギリアン"). A cue with no word in it keeps its span. reveal_end never comes before
start + MIN_SPAN.

  python pce/tools/pcecdreveal.py words [track ...]     # work/pce/cdda/words_NN.json (GPU)
  python pce/tools/pcecdreveal.py report [rec ...]      # cue, span, speech, the words' lag
  python pce/tools/pcecdreveal.py write [rec ...]       # reveal_end into cdda_<rec>.json
"""
import glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDDA = os.path.join(WORK, "pce", "cdda")
TDIR = os.path.join(ROOT, "pce", "translation")
MIN_PROB = 0.35
MIN_SPAN = 0.8               # seconds: a cue's words never all come up at once
SLACK = 0.25                 # seconds a cue's span is widened by when its words are looked for


def words_path(track):
    return os.path.join(CDDA, f"words_{track:02d}.json")


def transcribe(tracks):
    import pceasr
    m = pceasr.model()
    prompt = open(os.path.join(ROOT, "lib", "asr", "asr_prompt.txt"), encoding="utf-8").read()
    for t in tracks:
        wav = os.path.join(CDDA, f"t{t:02d}.wav")
        segs, _ = m.transcribe(wav, language="ja", word_timestamps=True, vad_filter=False,
                               initial_prompt=prompt)
        out = [{"start": s.start, "end": s.end, "text": s.text, "no_speech": s.no_speech_prob,
                "words": [[w.start, w.end, w.word, w.probability] for w in s.words]} for s in segs]
        json.dump(out, open(words_path(t), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"track {t}: {len(out)} segments")


def spoken(track):
    """[(start, end)] of every word worth trusting on the track."""
    segs = json.load(open(words_path(track), encoding="utf-8"))
    out, prev = [], None
    for s in segs:
        text = re.sub(r"[、。!?！？\s]", "", s["text"])
        if prev is not None and text and text in prev:           # whisper repeating itself
            continue
        prev = text * 2
        for a, b, w, p in s["words"]:
            if p >= MIN_PROB and b > a:
                out.append((a, b))
    return out


def cues(rec):
    path = os.path.join(TDIR, f"cdda_{rec}.json")
    return path, json.load(open(path, encoding="utf-8"))


def reveal(cue, words):
    """(first word's start, last word's end) inside the cue, or None."""
    inside = [(a, b) for a, b in words if cue["start"] - SLACK <= a < cue["end"]]
    if not inside:
        return None
    return inside[0][0], max(b for a, b in inside)


def recs(args):
    return [int(a) for a in args] or sorted(int(os.path.basename(p)[5:-5]) for p in glob.glob(os.path.join(TDIR, "cdda_[0-9]*.json")))


def report(args):
    for rec in recs(args):
        _, cs = cues(rec)
        print(f"==== {rec}")
        cache = {}
        for i, c in enumerate(cs):
            t = c["track"]
            if t not in cache:
                cache[t] = spoken(t) if os.path.exists(words_path(t)) else None
            r = reveal(c, cache[t]) if cache[t] is not None else None
            lag = f"speech {r[0]:6.2f}-{r[1]:6.2f}  tail {c['end'] - r[1]:5.1f} s" if r else "no words"
            print(f"[{i:2d}] t{t:02d} {c['start']:6.2f}-{c['end']:6.2f}  {lag}  {c.get('speaker') or '-':10} {c['en'][:40]}")


def write(args):
    for rec in recs(args):
        path, cs = cues(rec)
        raw = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in raw else "\n"
        cache, n = {}, 0
        for c in cs:
            t = c["track"]
            if t not in cache:
                cache[t] = spoken(t) if os.path.exists(words_path(t)) else None
            r = reveal(c, cache[t]) if cache[t] is not None else None
            if r is None:
                c.pop("reveal_end", None)
                continue
            end = round(min(c["end"], max(c["start"] + MIN_SPAN, r[1])), 2)
            if c.get("reveal_end") != end:
                c["reveal_end"] = end
                n += 1
        text = json.dumps(cs, ensure_ascii=False, indent=1).replace("\n", nl) + (nl if raw.endswith(nl) else "")
        open(path, "w", encoding="utf-8", newline="").write(text)
        print(f"cdda_{rec}.json: {n} cues timed to their words")


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "words":
        transcribe([int(a) for a in args] or sorted({c["track"] for p in glob.glob(os.path.join(TDIR, "cdda_[0-9]*.json"))
                                                    for c in json.load(open(p, encoding="utf-8"))}))
    else:
        {"report": report, "write": write}[cmd](args)
