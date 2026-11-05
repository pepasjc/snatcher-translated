"""The PS1's cards for the PCE's CD-DA dialogue tracks: drafts of pce/translation/cdda_<rec>.json.

Eighteen of the disc's audio tracks carry dialogue mixed with the music
(the recap, the montage, the bike ride, the Act 2 finale, the Chief,
the epilogue...): the same takes the PS1 converted to its stereo XA reels
and carded in ps1/translation/subs_*.json. A track's whisper transcript
(work/pce/cdda/scan.json, from work/pce/cdda_scan.py) is matched segment
by segment against the PS1 reels' segments (work/ts_cache.json) by
character-bigram Dice similarity; the reel with the most weight is the
track's. The takes are the same but the reels were cut again for the
PS1 (a pause longer here, a line moved there: the offsets between the
two clocks drift by seconds along a track), so the matched pairs become
anchors of a piecewise-linear warp from the reel's clock to the track's
(the longest monotonic run of pairs, each segment's start and end), and
every card of the reel is mapped through it - the PS1's text, speaker
and cuts, reviewed in play there, at the PCE's time. A track's draft
lists the anchors and their offsets for the eye.

  python pce/tools/pcecdda.py report              # every speech track: reel, anchors, offsets
  python pce/tools/pcecdda.py draft <track> <rec> # work/pce/cdda_drafts/<rec>_<track>.json (and the English into pce/translation/cdda_<rec>.json with --write)
"""
import json, os, statistics, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import pcematch

SCAN = os.path.join(WORK, "pce", "cdda", "scan.json")
DRAFTS = os.path.join(WORK, "pce", "cdda_drafts")
MIN = 0.45


def tracks():
    return {int(k): v for k, v in json.load(open(SCAN, encoding="utf-8")).items() if v.get("segments")}


def reel_time(s, sector):
    """A reel's sector -> seconds on its transcript's clock."""
    return (sector - s["start"]) * s["dur"] / (s["end"] - s["start"])


def align(track, streams, cands):
    """The reel and the warp for a track: (stream key, anchors [(reel s, track s)], pairs)."""
    segs = tracks()[track]["segments"]
    votes, pairs = {}, {}
    for seg in segs:
        bg = pcematch.bigrams(seg["text"])
        if not bg:
            continue
        ranked = sorted(((pcematch.dice(bg, cb), k, i) for k, i, cb, t in cands if i is not None), reverse=True)
        score, k, i = ranked[0]
        if score < MIN:
            continue
        votes[k] = votes.get(k, 0) + score
        pairs.setdefault(k, []).append((seg, streams[k]["segments"][i], score))
    if not votes:
        return None, [], []
    key = max(votes, key=votes.get)
    good = sorted([p for p in pairs[key] if p[2] >= 0.6], key=lambda p: p[1]["start"])
    # the longest run of pairs whose track times rise with their reel times
    best, ends = [], []
    n = len(good)
    lis = [1] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if good[j][0]["start"] < good[i][0]["start"] and lis[j] + 1 > lis[i]:
                lis[i], prev[i] = lis[j] + 1, j
    if n:
        i = max(range(n), key=lambda i: lis[i])
        while i >= 0:
            best.append(good[i])
            i = prev[i]
        best.reverse()
    # whisper's timestamps on the track drift here and there (a line stamped ten seconds
    # early, a segment swallowing the sixteen seconds after it): the anchors are each pair's
    # start and end, a pair whose two segments differ over threefold in length keeps its
    # end only, and a run of fewer than three anchors at an offset of their own is a
    # spike and goes (a longer one is a step - the versions cut differently there - and
    # stays: the cards inside the cut squeeze into what the track keeps)
    cand = []
    for p, q, sc in best:
        dp, dq = max(0.1, p["end"] - p["start"]), max(0.1, q["end"] - q["start"])
        if max(dp, dq) / min(dp, dq) <= 3:
            cand.append((q["start"], p["start"]))
        cand.append((q["end"], p["end"]))
    cand.sort()
    # runs of anchors whose offsets agree within 2.5 s of the previous one's; a run shorter
    # than three anchors is whisper's, not a cut
    runs, run = [], []
    for a in cand:
        if run and abs((a[1] - a[0]) - (run[-1][1] - run[-1][0])) > 2.5:
            runs.append(run)
            run = []
        run.append(a)
    if run:
        runs.append(run)
    anchors = []
    for a in (a for run in runs if len(run) >= 3 for a in run):
        if anchors and not (a[0] > anchors[-1][0] + 0.2 and a[1] > anchors[-1][1] + 0.2):
            continue
        anchors.append(a)
    if len(anchors) < 2 and best:            # too few to warp: one offset, the pairs' median
        off = statistics.median(p["start"] - q["start"] for p, q, sc in best)
        anchors = [(0.0, off)]
    return key, anchors, best


def warp(anchors, t):
    """A reel time -> the track's, linearly between the anchors, by the nearest offset outside them."""
    if not anchors:
        return t
    if t <= anchors[0][0]:
        return t + anchors[0][1] - anchors[0][0]
    if t >= anchors[-1][0]:
        return t + anchors[-1][1] - anchors[-1][0]
    for (a0, b0), (a1, b1) in zip(anchors, anchors[1:]):
        if a0 <= t <= a1:
            return b0 + (t - a0) * (b1 - b0) / (a1 - a0)
    return t


def cues_for(track, streams, cands):
    key, anchors, pairs = align(track, streams, cands)
    if key is None:
        return None, [], [], []
    s = streams[key]
    out = []
    for c in s["cues"]:
        if not c.get("enabled", True):
            continue
        a = max(0.0, warp(anchors, reel_time(s, c["start"])))
        b = warp(anchors, reel_time(s, c["end"]))
        if b - a < 0.3:
            b = a + 0.3
        out.append({"track": track, "start": round(a, 2), "end": round(b, 2), "speaker": c.get("speaker"),
                    "en": " ".join(c["en"].replace("￥", " ").split()), "ps1": c["id"]})
    return key, anchors, pairs, out


def main():
    streams = pcematch.ps1_data()
    cands = pcematch.candidates(streams)
    if sys.argv[1] == "report":
        for track in sorted(tracks()):
            key, anchors, pairs = align(track, streams, cands)
            if key is None:
                print(f"track {track:2}: no reel matched")
                continue
            s = streams[key]
            bank = s["cues"][0]["bank"] if s["cues"] else "-"
            offs = [b - a for a, b in anchors]
            print(f"track {track:2}: {key:18} {bank:5} {len(s['cues']):3} cards  {len(pairs):2} of {len(tracks()[track]['segments']):2} segments anchored"
                  f"  offsets {min(offs):+6.1f}..{max(offs):+6.1f} s" if offs else "")
        return
    if sys.argv[1] == "draft":
        track, rec = int(sys.argv[2]), int(sys.argv[3])
        key, anchors, pairs, cues = cues_for(track, streams, cands)
        if key is None:
            raise SystemExit(f"track {track}: no reel matched")
        os.makedirs(DRAFTS, exist_ok=True)
        path = os.path.join(DRAFTS, f"{rec}_{track:02d}.json")
        segs = tracks()[track]["segments"]
        json.dump({"track": track, "reel": key, "anchors": anchors,
                   "pairs": [{"pce": p["start"], "ps1": q["start"], "score": sc, "jp": p["text"], "ps1_jp": q["text"]} for p, q, sc in pairs],
                   "segments": segs, "cues": cues}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{path}: {len(cues)} cues from {key}, {len(pairs)} anchored segments")
        if "--write" in sys.argv:
            out = os.path.join(ROOT, "pce", "translation", f"cdda_{rec}.json")
            have = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
            have = [c for c in have if c["track"] != track] + cues
            have.sort(key=lambda c: (c["track"], c["start"]))
            json.dump(have, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"{out}: {len(have)} cues")


if __name__ == "__main__":
    main()
