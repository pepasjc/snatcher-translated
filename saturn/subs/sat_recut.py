"""Re-cut the Saturn's subtitle cards so each one is self-contained - the Saturn
twin of ps1/subs/consolidate.py, on the Saturn cue files themselves.

    python saturn/subs/sat_recut.py                # every bank, report only
    python saturn/subs/sat_recut.py --write        # rewrite saturn/translation/subs_*.json
    python saturn/subs/sat_recut.py B020 -v

A CHAIN is a run of consecutive enabled cards with the same speaker on the same
voice line (`line`) or reel (`reel`) whose byte windows touch (b1 == next b0). Its
text is joined and broken into cards by lib/cardplan.py (whole sentences a card,
then clause, phrase, word; no widow; a numbered item opens its card), a card being
whatever fits the band layout (the file's cols x rows) AND the plain box
(PLAIN_COLS x PLAIN_ROWS, one more row with no speaker). Timing: a new card starts
at the byte where its first character sat inside the original card that held it
(linear within that card), so the original cuts' timing survives. The other fields
(face, face_char, colour...) come from the original card the new one starts in;
ids are the chain's own, in order, with x, y... suffixes when the chain grows.

Hand edits that live only in the Saturn files are kept: a chain is re-cut only
when the result differs, and a single card is never touched.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/subs')]

import cardplan
import gen_subs as G

TR = os.path.join(ROOT, "saturn", "translation")


def chains(cues):
    out, cur = [], []
    for c in cues:
        if cur:
            a = cur[-1]
            same = (a.get("speaker") == c.get("speaker") and a.get("enabled", True) and c.get("enabled", True)
                    and a.get("line") == c.get("line") and a.get("reel") == c.get("reel")
                    and a["b1"] == c["b0"] and not a.get("chain") and not c.get("chain") and "t0" not in a)
            if not same:
                out.append(cur)
                cur = []
        cur.append(c)
    if cur:
        out.append(cur)
    return out


def recut(chain, pf, cols, rows):
    texts = [c["en"].strip() for c in chain]
    words = " ".join(texts).split()
    prow = G.PLAIN_ROWS if chain[0].get("speaker") else G.PLAIN_ROWS + 1

    def fits(a, b):
        t = " ".join(words[a:b])
        try:
            G.wrap(pf, t, cols, rows)
            G.wrap(pf, t, G.PLAIN_COLS, prow)
            return True
        except ValueError:
            return False

    cards = cardplan.plan(words, fits)
    pieces = [" ".join(words[a:b]) for a, b in cards]
    if pieces == texts:
        return None
    # character offset of every original card in the joined text
    starts, o = [], 0
    for t in texts:
        starts.append(o)
        o += len(t) + 1
    out, pos = [], 0
    ids = [c["id"] for c in chain]
    for n, (piece, (a, b)) in enumerate(zip(pieces, cards)):
        off = len(" ".join(words[:a])) + (1 if a else 0)
        k = max(i for i in range(len(chain)) if starts[i] <= off)
        src = chain[k]
        frac = (off - starts[k]) / max(1, len(texts[k]))
        b0 = chain[0]["b0"] if n == 0 else int(round(src["b0"] + frac * (src["b1"] - src["b0"])))
        c = {key: v for key, v in src.items()}
        c["id"] = ids[n] if n < len(ids) else ids[-1] + "xyzuvw"[n - len(ids)]
        c["en"] = piece
        c["rows"] = G.wrap(pf, piece, cols, rows)
        if "rows_plain" in src or "rows_plain" in chain[0]:
            c["rows_plain"] = G.wrap(pf, piece, G.PLAIN_COLS, prow)
        c["b0"] = b0
        out.append(c)
    for n in range(len(out) - 1):
        out[n]["b1"] = out[n + 1]["b0"]
    out[-1]["b1"] = chain[-1]["b1"]
    return out


def main():
    args = sys.argv[1:]
    write, verbose = "--write" in args, "-v" in args
    banks = [a for a in args if not a.startswith("-")]
    pf = G.pair_font()
    total = 0
    for name in sorted(os.listdir(TR)):
        if not (name.startswith("subs_") and name.endswith(".json")):
            continue
        scene = name[5:-5]
        if banks and scene not in banks:
            continue
        path = os.path.join(TR, name)
        raw = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in raw else "\n"
        doc = json.loads(raw)
        opts = doc.get("options", {})
        cols, rows = opts.get("cols", G.COLS), opts.get("rows", G.ROWS)
        new, n = [], 0
        for ch in chains(doc["cues"]):
            r = recut(ch, pf, cols, rows) if len(ch) > 1 else None
            if r is None:
                new += ch
                continue
            n += 1
            if verbose:
                print(f"  {'+'.join(c['id'] for c in ch)} -> " + " | ".join(repr(c["en"]) for c in r))
            new += r
        if n:
            print(f"{scene}: {len(doc['cues'])} -> {len(new)} cues ({n} chains re-cut)")
            total += n
            if write:
                doc["cues"] = new
                indent = 1 if raw.replace("\r\n", "\n").startswith('{\n "') else 2
                text = json.dumps(doc, ensure_ascii=False, indent=indent).replace("\n", nl)
                open(path, "w", encoding="utf-8", newline="").write(text + (nl if raw.endswith(nl) else ""))
    print(f"{total} chains re-cut" + ("" if write else " (dry run; --write to apply)"))


if __name__ == "__main__":
    main()
