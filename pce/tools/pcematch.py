"""The PS1's English for the PCE's voice lines: a draft pce/translation/subs_<rec>.json.

Both versions carry the same voice takes, so a PCE line's whisper text
(work/pce/asr_cache.json, pceasr.py) is matched against the PS1 streams'
whisper texts (work/all_transcripts.json per stream, work/ts_cache.json
per segment for the stereo reels) by character-bigram Dice similarity;
the winning stream's cues (every ps1/translation/subs_*.json, linked by
file, channel and sector) give the English, joined in order, and the
speaker. A reel (stereo) match is one segment of it, and takes the cues
that overlap the segment's sectors.

The draft keeps the existing file's lines (hand work wins), adds the
matches at or above --min (0.5) with their `ps1` ids and a `score`, and
lists the rest under `_unmatched` (the PCE text stays in work/: the repo
carries English only). Review the draft in play, then drop `score`.

  python pce/tools/pcematch.py <rec> [--min 0.5] [--write]
  python pce/tools/pcematch.py check 318      # the matcher against a hand-made file
"""
import glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import pcevoice as V
import pceasr

STRIP = re.compile(r"[\s、。！？!?…「」『』（）()・,.\-—～~]+")
NOISE = ("ご視聴ありがとうございました", "チャンネル登録", "字幕")     # whisper over silence
BONUS = 0.15                 # for a candidate in one of the module's own banks


def bigrams(text):
    t = STRIP.sub("", text)
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t} if t else set()


def dice(a, b):
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def ps1_data():
    """Streams with their transcripts, segments and cues."""
    ml = json.load(open(os.path.join(WORK, "master_lines.json"), encoding="utf-8"))
    at = json.load(open(os.path.join(WORK, "all_transcripts.json"), encoding="utf-8"))
    ts = json.load(open(os.path.join(WORK, "ts_cache.json"), encoding="utf-8"))
    streams = {m["key"]: dict(m, text=at.get(m["key"], ""), segments=ts.get(m["key"], []), cues=[]) for m in ml}
    by_fc = {}
    for s in streams.values():
        by_fc.setdefault((s["file"], s["ch"]), []).append(s)
    ps1 = os.environ.get("PS1_ROOT", ROOT)        # another checkout's PS1 cue files (a newer branch's)
    for path in sorted(glob.glob(os.path.join(ps1, "ps1", "translation", "subs_*.json"))):
        bank = os.path.basename(path)[5:-5]
        for c in json.load(open(path, encoding="utf-8"))["cues"]:
            for s in by_fc.get((c["file"], c["chan"]), []):
                if s["start"] <= c["start"] <= s["end"]:
                    # the same take carded under two banks (the videophone's): once
                    if not any(o["start"] == c["start"] and o["en"] == c["en"] for o in s["cues"]):
                        s["cues"].append(dict(c, bank=bank))
                    break
    for s in streams.values():
        s["cues"].sort(key=lambda c: c["start"])
    return streams


def candidates(streams):
    """[(key, segment index or None, bigrams, text)]: a mono stream whole, a reel per segment."""
    out = []
    for key, s in streams.items():
        if not s["cues"]:
            continue
        if s["stereo"] and s["segments"]:
            for i, seg in enumerate(s["segments"]):
                out.append((key, i, bigrams(seg["text"]), seg["text"]))
        else:
            out.append((key, None, bigrams(s["text"]), s["text"]))
    return out


def english(s, seg=None):
    """The cues of a stream (or of a reel's segment, by sector overlap): (speaker, en, ids)."""
    cues = s["cues"]
    if seg is not None:
        span = s["end"] - s["start"]
        dur = s["dur"] or 1
        a = s["start"] + seg["start"] * span / dur
        b = s["start"] + seg["end"] * span / dur
        cues = [c for c in cues if c["start"] < b and c["end"] > a] or cues
    en = " ".join(c["en"].replace("￥", " ") for c in cues if c.get("enabled", True))
    speakers = [c["speaker"] for c in cues if c.get("speaker")]
    speaker = max(set(speakers), key=speakers.count) if speakers else None
    return speaker, " ".join(en.split()), [c["id"] for c in cues]


def match(rec, minimum=0.5):
    cache = pceasr.load()
    streams = ps1_data()
    cands = candidates(streams)
    n = [e["n"] for e in json.load(open(os.path.join(WORK, "pce", "filetable.json")))["1"] if e["rec"] == rec][0]
    out, unmatched, scored = {}, {}, {}
    voices = V.module_voices(rec, n)
    twice = {b for b in {b for a, b in voices} if sum(1 for a2, b2 in voices if b2 == b) > 1}
    for act, nn in voices:
        key = f"{act}_{nn:02x}"
        jkey = f"{nn:02x}.{act}" if nn in twice else f"{nn:02x}"       # (pcesubs.line_key)
        e = cache.get(key)
        if e is None:
            unmatched[jkey] = "not transcribed"
            continue
        if e.get("effect") or not e["text"].strip() or any(w in e["text"] for w in NOISE):
            continue
        segs = [x["text"] for x in e["segments"]]
        if len(segs) >= 3 and len(set(segs)) == 1:
            continue                    # whisper looping over a sound: no speech
        bg = bigrams(e["text"])
        ranked = sorted(((dice(bg, cb), k, i, t) for k, i, cb, t in cands), reverse=True)
        scored[jkey] = ranked[:8]
    # the module's banks: where its sure matches point; a candidate from one of them
    # gets a bonus over an equal line elsewhere (the same take is cued in several banks)
    banks = {}
    for nn, ranked in scored.items():
        score, k, i, t = ranked[0]
        if score >= 0.8:
            b = streams[k]["cues"][0]["bank"]
            banks[b] = banks.get(b, 0) + 1
    home = {b for b, c in banks.items() if c >= 2}
    for nn, ranked in scored.items():
        best = max(ranked, key=lambda r: r[0] + (BONUS if streams[r[1]]["cues"][0]["bank"] in home else 0))
        score, k, i, t = best
        if score < minimum:
            unmatched[nn] = f"{score:.2f} {k}"          # (no transcript text: the repo carries English only)
            continue
        s = streams[k]
        speaker, en, ids = english(s, s["segments"][i] if i is not None else None)
        out[nn] = {"speaker": speaker, "en": en, "ps1": ids, "score": round(score, 2), "stream": k, "bank": s["cues"][0]["bank"]}
    return out, unmatched


def main():
    args = sys.argv[1:]
    if args[0] == "check":
        rec = int(args[1])
        got, un = match(rec, 0.0)
        have = json.load(open(os.path.join(ROOT, "pce", "translation", f"subs_{rec}.json"), encoding="utf-8"))
        ok = bad = 0
        for nn, spec in sorted(have.items()):
            g = got.get(nn)
            same = g and set(g["ps1"]) & set(spec.get("ps1", []))
            ok += bool(same)
            bad += not same
            if not same:
                print(f"{nn}: hand {spec.get('ps1')} {spec['en'][:50]!r}\n    got  {g and g['ps1']} {g and g['score']} {g and g['en'][:50]!r}")
        print(f"{ok} agree, {bad} differ; scores of the agreeing: " + " ".join(f"{got[nn]['score']:.2f}" for nn in have if got.get(nn) and set(got[nn]['ps1']) & set(have[nn].get('ps1', []))))
        return
    rec = int(args[0])
    minimum = float(args[args.index("--min") + 1]) if "--min" in args else 0.5
    got, un = match(rec, minimum)
    path = os.path.join(ROOT, "pce", "translation", f"subs_{rec}.json")
    if "--out" in args:
        path = os.path.join(args[args.index("--out") + 1], f"subs_{rec}.json")
    have = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    banks = {}
    for nn, g in got.items():
        banks[g["bank"]] = banks.get(g["bank"], 0) + 1
    print(f"{rec}: {len(got)} matched, {len(un)} unmatched, {len(have)} already there; banks {banks}")
    for nn, g in sorted(got.items()):
        tag = "have" if nn in have else "new "
        print(f" {tag} {nn} {g['score']:.2f} {g['bank']} {str(g['speaker']):10} {g['en'][:70]}")
    for nn, why in sorted(un.items()):
        print(f" ---- {nn} {why}")
    if "--write" in args:
        new = dict(have)
        for nn, g in got.items():
            if nn not in new:
                new[nn] = {"speaker": g["speaker"], "en": g["en"], "ps1": g["ps1"], "score": g["score"]}
        new["_unmatched"] = {nn: why for nn, why in un.items() if nn not in have}
        new = dict(sorted(new.items(), key=lambda kv: (kv[0].startswith("_"), int(kv[0].split(".")[0], 16) if not kv[0].startswith("_") else 0)))
        json.dump(new, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{path} written")


if __name__ == "__main__":
    main()
