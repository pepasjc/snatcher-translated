# -*- coding: utf-8 -*-
"""Static lint of the Saturn subtitle cards against Luiz's card rules and the geometry -
what the shipped JSON says, before any emulator runs. Part of the regression.

    python saturn/subs/satcardlint.py [BANK...] [-v]        exit 1 on an error

Errors (each one a card a player would see wrong):
  TEXT      `rows` (what the blob draws) do not carry the words of `en`
  GREEDY    `rows` are not the greedy fill of `en` at the band's cols (a row ends early)
  FIT       a row wider than the layout's cells, or more rows than the layout has
  CHAIN     a same-speaker chain is not cut the way lib/cardplan.py cuts it (whole
            sentences a card, the next sentence never starts at a card's end, balanced
            splits, no widow) - satsubs/sat_recut.py --write fixes these
  BULLET    a numbered item ("2.") that does not open its card
  DUPID     two cues with one id
  OVERLAP   two enabled cues of one line / reel whose byte windows overlap
  ORDER     b1 <= b0
  FALLBACK  a letter pair with no glyph slot (drawn as two fullwidth letters)
Warnings (listed, not failing):
  FAST      more than 25 characters a second over the time the card is up (its window,
            an adopted split's continuation, the payload's minimum hold: on_screen)
  COLON     a label colon standing in for a verb ("Her name: Catherine")
"""
import collections, glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/subs')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cardplan
import gen_subs as G
import sat_recut
import satsubs

TR = os.path.join(ROOT, "saturn", "translation")
MONO_BPS = 11025
COLON = re.compile(r"(?<![\"'])\b([A-Z][a-z]+(?: [a-z]+)?): (?![\"'])[A-Za-z]")


def reel_bps(c):
    return c["size"] / c["frames"] * c.get("rate", 22050) if c.get("frames") else 96000.0


def source(c):
    return ("reel", c["reel"]) if "reel" in c else ("line", c.get("line"), c.get("sector"))


def on_screen(cues, i):
    """Seconds the card of enabled cue i stays up, as the payload shows it: its byte window,
    run on through the next cues of the same line / reel that carry the same text (an adopted
    split: the opening's news_16/16b), then held to its reading time (satsubs.hold_frames)
    unless the next cue of the same line / reel takes the box at the window's end. A next
    cue on ANOTHER line is not known here (the gap between two lines is the script's): the
    hold is counted, and the runtime log's `subcue X down after N frames` tells the rest.
    None for the continuation of an adopted split (counted with its first cue)."""
    c = cues[i]
    bps = reel_bps(c) if "reel" in c else MONO_BPS
    prev = cues[i - 1] if i else None
    if prev and source(prev) == source(c) and prev["en"] == c["en"] and prev["b1"] == c["b0"]:
        return None
    b1, j = c["b1"], i + 1
    while j < len(cues) and source(cues[j]) == source(c) and cues[j]["en"] == c["en"] and cues[j]["b0"] == b1:
        b1, j = cues[j]["b1"], j + 1
    secs = (b1 - c["b0"]) / bps
    nxt = cues[j] if j < len(cues) else None
    if nxt and source(nxt) == source(c) and nxt["b0"] <= b1:
        return secs
    return max(secs, satsubs.hold_frames(c["en"]) / 60)


def lint(names=None, verbose=False):
    pf = G.pair_font()
    import satglyphs
    table = json.load(open(G.SAT_TABLE))
    table = table.get("table", table) if isinstance(table, dict) else table
    errors, warns = [], []
    ids = collections.Counter()
    for path in sorted(glob.glob(os.path.join(TR, "subs_*.json"))):
        name = os.path.basename(path)[5:-5]
        if names and name not in names:
            continue
        spec = json.load(open(path, encoding="utf-8"))
        o = spec.get("options", {})
        plain = o.get("layout") == "plain"
        cols, rows = o.get("cols", G.COLS), o.get("rows", G.ROWS)
        cues = spec["cues"]
        en_cues = [c for c in cues if c.get("enabled", True)]

        def err(kind, c, msg):
            errors.append(f"{kind:8} {name} {c['id'] if c else ''}: {msg}")

        def warn(kind, c, msg):
            warns.append(f"{kind:8} {name} {c['id']}: {msg}")
        for c in cues:
            ids[c["id"]] += 1
        for idx, c in enumerate(en_cues):
            r = c.get("rows") or []
            en = c.get("en", "")
            if " ".join(r).split() != en.split():
                err("TEXT", c, f"rows {r} != en {en!r}")
            ccols = c.get("cols", cols)
            try:
                want = G.wrap(pf, " ".join(r), ccols, 99)
            except ValueError as e:
                err("FIT", c, str(e)); continue
            if [x.strip() for x in r] != want and not c.get("hand_rows"):
                err("GREEDY", c, f"rows {r} - greedy at {ccols} cells: {want}")
            if len(r) > rows:
                err("FIT", c, f"{len(r)} rows, the layout has {rows}")
            for x in r:
                if G.cells(pf, x) > ccols:
                    err("FIT", c, f"row {x!r} is {G.cells(pf, x)} cells > {ccols}")
            fb = sorted({p for x in r for p in satglyphs.pairs_of(x) if p not in table})
            if fb:
                err("FALLBACK", c, f"pairs with no slot: {fb}")
            ws = en.split()
            for k, w in enumerate(ws):
                if k and cardplan.BULLET.match(w) and k > 0 and cardplan.sentence_end(ws[k - 1]):
                    err("BULLET", c, f"item {w!r} inside the card: {en!r}")
            if c["b1"] <= c["b0"]:
                err("ORDER", c, f"b0 {c['b0']} b1 {c['b1']}")
            shown = on_screen(en_cues, idx)
            if shown is not None and len(en) / shown > 25:
                warn("FAST", c, f"{len(en)} chars on screen {shown:.1f}s ({len(en) / shown:.0f}/s)")
            if COLON.search(en):
                warn("COLON", c, en)
        # overlaps within a line / reel
        groups = collections.defaultdict(list)
        for c in en_cues:
            k = ("reel", c["reel"]) if "reel" in c else ("line", c.get("sector"), c.get("offset"), c.get("act"))
            groups[k].append(c)
        for k, g in groups.items():
            g = sorted(g, key=lambda c: c["b0"])
            for a, b in zip(g, g[1:]):
                if b["b0"] < a["b1"] and not (a.get("chain") or b.get("chain")):
                    err("OVERLAP", b, f"{a['id']} {a['b0']}..{a['b1']} overlaps {b['b0']}..{b['b1']}")
        # chains against cardplan (sat_recut's own planner)
        for ch in sat_recut.chains(cues):
            if len(ch) < 2 or not all(c.get("enabled", True) for c in ch) or not ch[0].get("en"):
                continue
            try:
                new = sat_recut.recut(ch, pf, cols, rows)
            except Exception as e:
                if verbose:
                    print(f"  chain {ch[0]['id']}: {e}")
                continue
            if new is None:
                continue
            got = [" ".join(c["en"].split()) for c in ch]
            want = [" ".join(n["en"].split()) for n in new]
            if got != want:
                err("CHAIN", ch[0], f"cut {got} - cardplan cuts {want}")
    for i, n in ids.items():
        if n > 1:
            errors.append(f"DUPID    {i}: {n} cues")
    return errors, warns


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("-")]
    v = "-v" in sys.argv
    errors, warns = lint(a or None, v)
    for w in warns if v else []:
        print("warn " + w)
    for e in errors:
        print(e)
    kinds = collections.Counter(e.split()[0] for e in errors)
    wk = collections.Counter(w.split()[0] for w in warns)
    print(f"card lint: {len(errors)} error(s) {dict(kinds)}; {len(warns)} warning(s) {dict(wk)}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
