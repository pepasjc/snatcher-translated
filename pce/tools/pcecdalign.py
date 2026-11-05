"""CD-DA cues placed on their own voice: every cue's start, speech end and seams from the PCE
track's word stamps, character-aligned with the PS1 reel's transcript.

pcecdda placed the PS1's cards on the PCE tracks through a piecewise-linear warp between
matched whisper segments; where the two versions were cut differently the warp slid, and
a cue could open seconds from its line - Chin's "Our goal is to snatch the world's VIPs"
(606, track 10) came up at 225.3 s over Gillian's "Kremlin, Madnar..." and was said at
229.3 (Luiz, 2026-10-18: voices out of sync after the factory and at HQ). The takes are
the same recordings, so the Japanese of both transcripts runs character for character:
the PS1 reel's segments (work/ts_cache.json, its characters spread over each segment) are
aligned with the PCE track's words (pcecdreveal's words_NN.json, faster-whisper word
stamps) by difflib's matching blocks, and each cue's PS1 span - its card and the cards
folded into it (`ps1_more`) - maps to the PCE characters it covers: the first one's word
start is the cue's start, the last one's word end its `reveal_end`, each folded card's
first character its seam. A cue whose span maps fewer than MIN_HIT of its characters
keeps its times.

Starts move, ends follow: a cue's end is the next cue's start on the same track when the
two touched before (the page held to the next line), else its own speech end + HOLD, never
before its reveal_end.

  python pce/tools/pcecdalign.py report [rec ...]
  python pce/tools/pcecdalign.py write [rec ...]
  python pce/tools/pcecdalign.py apply [rec ...]     # work/pce/cdsync/out_<rec>.json, set by hand

The automatic alignment proved unsafe where whisper's word times are rough (low
probability inside long segments) or a short line's name repeats: the cues were finally
placed by reading the track's Japanese against the English, line by line, into
work/pce/cdsync/out_<rec>.json ({i, start, speech_end, seams, confidence}), and `apply`
takes those.
"""
import difflib, glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pcematch
from pcecdda import reel_time
from pcecdreveal import words_path, TDIR

MIN_HIT = 0.6                 # share of a cue's PS1 characters that must find their PCE twin
MIN_PROB = 0.3                # the mean probability whisper gave the PCE words matched
RATIO = (0.5, 2.0)            # the matched span's length against the PS1 card's
LEAD = 0.10                   # seconds a page comes up before its first word
HOLD = 1.0                    # seconds a page stays after its last word when nothing follows
JUNK = re.compile(r"[\s、。,.!?！？「」『』…・ー〜~-]")


def chars_pce(track):
    """[(char, start, end of its word)] for the PCE track."""
    out = []
    for s in json.load(open(words_path(track), encoding="utf-8")):
        for a, b, w, p in s["words"]:
            cs = JUNK.sub("", w)
            for k, ch in enumerate(cs):
                out.append((ch, a + (b - a) * k / max(1, len(cs)), b, p))
    return out


def chars_reel(stream):
    """[(char, reel seconds)] for a PS1 stream, each segment's characters spread over it."""
    out = []
    for s in stream["segments"]:
        cs = JUNK.sub("", s["text"])
        for k, ch in enumerate(cs):
            out.append((ch, s["start"] + (s["end"] - s["start"]) * k / max(1, len(cs))))
    return out


def ps1_index(streams):
    """{ps1 id: (stream key, cue)}."""
    idx = {}
    for key, s in streams.items():
        for c in s["cues"]:
            idx.setdefault(c["id"], (key, c))
    return idx


class Aligner:
    def __init__(self):
        self.streams = pcematch.ps1_data()
        self.idx = ps1_index(self.streams)
        self.pce, self.maps = {}, {}

    def mapping(self, track, key):
        """reel char index -> pce char index, for this track against this stream."""
        if (track, key) not in self.maps:
            if track not in self.pce:
                self.pce[track] = chars_pce(track)
            a = chars_reel(self.streams[key])
            b = self.pce[track]
            sm = difflib.SequenceMatcher(None, "".join(c for c, _ in a), "".join(x[0] for x in b), autojunk=False)
            m = {}
            for i, j, n in sm.get_matching_blocks():
                for k in range(n):
                    m[i + k] = j + k
            self.maps[(track, key)] = (a, m)
        return self.maps[(track, key)]

    def span(self, track, pid):
        """(start, end) on the PCE track for PS1 card `pid` when the match is sure, else None:
        MIN_HIT of its characters matched, their words' mean probability MIN_PROB, the span's
        length within RATIO of the card's (a short line whose name the track repeats -
        "Gillian!" - matches the wrong one otherwise)."""
        if pid not in self.idx:
            return None
        key, c = self.idx[pid]
        s = self.streams[key]
        a, m = self.mapping(track, key)
        r0, r1 = reel_time(s, c["start"]), reel_time(s, c["end"])
        inside = [i for i, (_, t) in enumerate(a) if r0 - 0.05 <= t < r1]
        hit = [m[i] for i in inside if i in m]
        if not inside or len(hit) < MIN_HIT * len(inside):
            return None
        b = self.pce[track]
        if sum(b[j][3] for j in hit) / len(hit) < MIN_PROB:
            return None
        st, en = b[min(hit)][1], max(b[j][2] for j in hit)
        if not RATIO[0] <= (en - st) / max(0.3, r1 - r0) <= RATIO[1]:
            return None
        return st, en


def plan(rec, al):
    """Per cue: its folded cards' spans, its start (aligned, or its neighbours' shift
    interpolated on the same track, or as it was) and its speech end."""
    path = os.path.join(TDIR, f"cdda_{rec}.json")
    cues = json.load(open(path, encoding="utf-8"))
    out = []
    for c in cues:
        ids = [c["ps1"]] + list(c.get("ps1_more", [])) if c.get("ps1") else []
        spans = [al.span(c["track"], pid) for pid in ids]
        first = spans[0] if spans else None
        good = [sp for sp in spans if sp]
        out.append({"cue": c, "spans": spans, "sure": first is not None,
                    "start": first[0] - LEAD if first else None,
                    "speech_end": max(b for a, b in good) if good else None})
    for i, r in enumerate(out):
        if r["sure"]:
            continue
        t, c0 = r["cue"]["track"], r["cue"]["start"]
        before = next((o for o in reversed(out[:i]) if o["sure"] and o["cue"]["track"] == t), None)
        after = next((o for o in out[i + 1:] if o["sure"] and o["cue"]["track"] == t), None)
        if before and after:
            sb, sa = before["start"] - before["cue"]["start"], after["start"] - after["cue"]["start"]
            k = (c0 - before["cue"]["start"]) / max(0.01, after["cue"]["start"] - before["cue"]["start"])
            r["start"] = c0 + sb + (sa - sb) * k
            if r["speech_end"] is None:
                r["speech_end"] = None
        elif before or after:
            o = before or after
            r["start"] = c0 + (o["start"] - o["cue"]["start"])
    return path, cues, out


def report(args):
    al = Aligner()
    for rec in args:
        _, _, rows = plan(rec, al)
        print(f"==== {rec}")
        for i, r in enumerate(rows):
            c = r["cue"]
            if r["start"] is None:
                print(f"[{i:2d}] t{c['track']:02d} {c['start']:7.2f}  KEPT             {c.get('speaker') or '-':10} {c['en'][:45]}")
                continue
            d = r["start"] - c["start"]
            flag = "  <<" if abs(d) > 0.5 else ""
            how = "" if r["sure"] else " (from its neighbours)"
            se = f"{r['speech_end']:7.2f}" if r["speech_end"] is not None else "      ?"
            print(f"[{i:2d}] t{c['track']:02d} {c['start']:7.2f} -> {r['start']:7.2f} ({d:+5.2f})  speech to {se}"
                  f"  {c.get('speaker') or '-':10} {c['en'][:45]}{flag}{how}")


def write(args):
    al = Aligner()
    for rec in args:
        path, cues, rows = plan(rec, al)
        raw = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in raw else "\n"
        touched = [cues[i]["end"] >= cues[i + 1]["start"] - 0.05 and cues[i]["track"] == cues[i + 1]["track"]
                   for i in range(len(cues) - 1)] + [False]
        for r in rows:
            c = r["cue"]
            if r["start"] is not None:
                c["start"] = round(max(0.0, r["start"]), 2)
            if r["speech_end"] is not None:
                c["reveal_end"] = round(r["speech_end"], 2)
            if c.get("seams") and r["start"] is not None:
                words = 0
                ids = [c["ps1"]] + list(c.get("ps1_more", []))
                # each seam's word index stays; its time from the folded card's first character
                spans = r["spans"]
                for seam, sp in zip(c["seams"], spans[1:]):
                    if sp:
                        seam[1] = round(sp[0], 2)
        for i, c in enumerate(cues):
            nxt = cues[i + 1] if i + 1 < len(cues) else None
            if touched[i] and nxt is not None:
                c["end"] = nxt["start"]
            elif c.get("reveal_end") is not None:
                c["end"] = round(max(c["end"] if c["end"] > c["start"] else 0, c["reveal_end"] + HOLD)
                                 if nxt is None or nxt["track"] != c["track"]
                                 else min(max(c["reveal_end"] + HOLD, c["end"]), nxt["start"]), 2)
            if c.get("reveal_end") is not None:
                c["reveal_end"] = round(min(c["reveal_end"], c["end"]), 2)
            if c["end"] <= c["start"]:
                c["end"] = round(c["start"] + 0.8, 2)
        text = json.dumps(cues, ensure_ascii=False, indent=1).replace("\n", nl) + (nl if raw.endswith(nl) else "")
        open(path, "w", encoding="utf-8", newline="").write(text)
        print(f"cdda_{rec}.json: {sum(1 for r in rows if r['start'] is not None)} of {len(rows)} cues aligned")


def retime(cues, rows):
    """Starts, reveal ends and seams from `rows` ({start, speech_end, seams} per cue, None to
    keep), then the ends: the next cue's start where the two touched, else speech end + HOLD."""
    touched = [cues[i]["end"] >= cues[i + 1]["start"] - 0.05 and cues[i]["track"] == cues[i + 1]["track"]
               for i in range(len(cues) - 1)] + [False]
    for c, r in zip(cues, rows):
        if r.get("start") is not None:
            c["start"] = round(max(0.0, r["start"]), 2)
        if r.get("speech_end") is not None:
            c["reveal_end"] = round(r["speech_end"], 2)
        if c.get("seams") and r.get("seams"):
            for seam, t in zip(c["seams"], r["seams"]):
                seam[1] = round(t, 2)
    for i, c in enumerate(cues):
        nxt = cues[i + 1] if i + 1 < len(cues) and cues[i + 1]["track"] == c["track"] else None
        if nxt is not None and touched[i]:
            c["end"] = nxt["start"]
        elif c.get("reveal_end") is not None:
            c["end"] = round(c["reveal_end"] + HOLD, 2) if nxt is None else round(min(c["reveal_end"] + HOLD, nxt["start"]), 2)
        if nxt is not None and c["end"] > nxt["start"]:
            c["end"] = nxt["start"]
        if c.get("reveal_end") is not None:
            c["reveal_end"] = round(min(c["reveal_end"], c["end"]), 2)
        if c["end"] <= c["start"]:
            c["end"] = round(c["start"] + 0.8, 2)


def apply(args):
    for rec in args:
        src = os.path.join(WORK, "pce", "cdsync", f"out_{rec}.json")
        if not os.path.exists(src):
            print(f"cdda_{rec}: no {src}")
            continue
        path = os.path.join(TDIR, f"cdda_{rec}.json")
        raw = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in raw else "\n"
        cues = json.loads(raw)
        got = {r["i"]: r for r in json.load(open(src, encoding="utf-8"))}
        if sorted(got) != list(range(len(cues))):
            raise SystemExit(f"{src}: {len(got)} rows for {len(cues)} cues")
        rows = [got[i] for i in range(len(cues))]
        for a, b in zip(rows, rows[1:]):
            if cues[rows.index(a)]["track"] == cues[rows.index(b)]["track"] and b["start"] < a["start"]:
                raise SystemExit(f"{src}: cue {b['i']} starts before cue {a['i']}")
        retime(cues, rows)
        text = json.dumps(cues, ensure_ascii=False, indent=1).replace("\n", nl) + (nl if raw.endswith(nl) else "")
        open(path, "w", encoding="utf-8", newline="").write(text)
        moved = sum(1 for r in rows if r.get("confidence") == "estimated")
        print(f"cdda_{rec}.json: {len(rows)} cues placed by hand ({moved} estimated)")


if __name__ == "__main__":
    cmd = sys.argv[1]
    args = [int(a) for a in sys.argv[2:]] or sorted(int(os.path.basename(p)[5:-5]) for p in glob.glob(os.path.join(TDIR, "cdda_[0-9]*.json")))
    {"report": report, "write": write, "apply": apply}[cmd](args)
