"""Re-cut the opening's narration cards so each holds whole sentences, on all three ports.

    python lib/opening_recut.py            # report
    python lib/opening_recut.py --write    # rewrite the three opening cue files

The opening's cards are timed on one narration stream and carry where the band sits
under the picture (PS1/Saturn `y`, `pic_bottom`, `over`), so the scene re-cut tools
leave them alone. Here a RUN is a stretch of consecutive narration cards with the same
speaker on the same stream whose windows touch; its text is joined and broken into
cards by lib/cardplan.py, a card being what fits the port's opening box:

    PS1     ps1/translation/subs_INTRO.json      3 rows x 18 cells (subs_cue.wrap_only)
    Saturn  saturn/translation/subs_INTRO.json   options rows x cols (gen_subs.wrap)
    PCE     pce/translation/cdda_opening.json    pceopening.split pages a cue itself, so a
                                                  run joins into one cue per sentence group

A new card starts where its first character sat in the original card that held it
(linear inside that card). It takes the lowest band position of the cards it covers
(the largest `y`, `pic_bottom`; `over` if any was), so it still clears the picture. A
PS1 card marked `noband` (the diagram still) is never merged.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/subs')]

import cardplan

# port -> (path, time fields: (start, end, integer?) pairs, stream key)
PORTS = {
    "ps1": ("ps1/translation/subs_INTRO.json", [("start", "end", True)], ("file", "chan")),
    "saturn": ("saturn/translation/subs_INTRO.json", [("b0", "b1", True), ("t0", "t1", False)], ("reel",)),
    "pce": ("pce/translation/cdda_opening.json", [("start", "end", False)], ("track",)),
}


def fitter(port, doc):
    if port == "ps1":
        from subs_cue import wrap_only, CODES_PER_ROW
        rows = doc["options"].get("rows", 3)

        def fits(text):
            try:
                wrap_only(text, rows, CODES_PER_ROW)
                return True
            except SystemExit:
                return False
        return fits
    if port == "saturn":
        import gen_subs as G
        pf = G.pair_font()
        cols, rows = doc["options"].get("cols", 20), doc["options"].get("rows", 3)

        def fits(text):
            try:
                G.wrap(pf, text, cols, rows)
                return True
            except ValueError:
                return False
        return fits
    # PCE: a cue may hold several pages; a run is cut at sentence groups that fit a page
    import pceopening as O
    return lambda text: len(O.wrap(text)) <= O.ROWS


def runs(cues, port):
    s0, s1, _ = PORTS[port][1][0]
    key = PORTS[port][2]
    out, cur = [], []
    for c in cues:
        if cur:
            a = cur[-1]
            same = (all(a.get(k) == c.get(k) for k in key) and a.get("speaker") == c.get("speaker")
                    and abs(a[s1] - c[s0]) < 1e-6 and not a.get("noband") and not c.get("noband")
                    and not a.get("last"))
            if not same:
                out.append(cur)
                cur = []
        cur.append(c)
    if cur:
        out.append(cur)
    return out


def recut(run, port, fits):
    texts = [c["en"].strip() for c in run]
    words = " ".join(texts).split()
    cards = cardplan.plan(words, lambda a, b: fits(" ".join(words[a:b])))
    pieces = [" ".join(words[a:b]) for a, b in cards]
    if pieces == texts:
        return None
    starts, o = [], 0
    for t in texts:
        starts.append(o)
        o += len(t) + 1
    out = []
    for n, (piece, (a, b)) in enumerate(zip(pieces, cards)):
        off = len(" ".join(words[:a])) + (1 if a else 0)
        end_off = len(" ".join(words[:b]))
        k = max(i for i in range(len(run)) if starts[i] <= off)
        k_end = max(i for i in range(len(run)) if starts[i] <= max(off, end_off - 1))
        src = run[k]
        c = dict(src)
        c["en"] = piece
        frac = (off - starts[k]) / max(1, len(texts[k]))
        for f0, f1, integer in PORTS[port][1]:
            v = src[f0] + frac * (src[f1] - src[f0]) if n else run[0][f0]
            c[f0] = int(round(v)) if integer else round(v, 2)
        covered = run[k:k_end + 1]
        for f in ("y", "pic_bottom"):
            if f in src:
                c[f] = max(x.get(f, 0) for x in covered)
        if "over" in src:
            c["over"] = any(x.get("over") for x in covered)
        c.pop("last", None)
        if port == "ps1":
            c["id"] = run[n]["id"] if n < len(run) else run[-1]["id"] + "xyzuvw"[n - len(run)]
        if port == "pce":
            c["ps1"] = src.get("ps1")
            c.pop("cards", None)
        out.append(c)
    for n in range(len(out) - 1):
        for f0, f1, _ in PORTS[port][1]:
            out[n][f1] = out[n + 1][f0]
    for f0, f1, _ in PORTS[port][1]:
        out[-1][f1] = run[-1][f1]
    if any(x.get("last") for x in run):
        out[-1]["last"] = True
    if port == "ps1":
        for c, src in ((c, c) for c in out):
            span = c["end"] - c["start"]
            ref = run[0]
            rate = ref["dur"] / max(1, ref["end"] - ref["start"])
            c["dur"] = round(span * rate, 1)
    if port == "saturn":
        import gen_subs as G
        pf = G.pair_font()
        for c in out:
            c["rows"] = G.wrap(pf, c["en"], 20, 3)
    if port == "pce":
        import pceopening as O
        for c in out:
            c["cards"] = ["|".join(p) for p in O.split(c["en"])]
    return out


def main():
    write = "--write" in sys.argv
    for port, (path, _, _) in PORTS.items():
        full = os.path.join(ROOT, path)
        raw = open(full, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in raw else "\n"
        doc = json.loads(raw)
        cues = doc["cues"] if isinstance(doc, dict) else doc
        fits = fitter(port, doc if isinstance(doc, dict) else {"options": {}})
        new, n = [], 0
        for run in runs(cues, port):
            r = recut(run, port, fits) if len(run) > 1 else None
            if r is None:
                new += run
                continue
            n += 1
            print(f"{port}: " + " + ".join(repr(c["en"]) for c in run))
            print("   -> " + " | ".join(repr(c["en"]) for c in r))
            new += r
        print(f"{port}: {n} runs re-cut, {len(cues)} -> {len(new)} cards")
        if write and n:
            if isinstance(doc, dict):
                doc["cues"] = new
            else:
                doc = new
            indent = 1 if raw.replace("\r\n", "\n").lstrip().startswith(("{\n \"", "[\n {")) else 2
            text = json.dumps(doc, ensure_ascii=False, indent=indent).replace("\n", nl)
            open(full, "w", encoding="utf-8", newline="").write(text + (nl if raw.endswith(nl) else ""))


if __name__ == "__main__":
    main()
