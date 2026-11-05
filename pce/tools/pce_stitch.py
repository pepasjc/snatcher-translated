"""Assemble a long PCE line out of the PS1's English pieces.

The Gaudi database articles are one long string per topic on the PCE, while
the PS1 keeps the same article split one screen per string. So a PCE line
that no single PS1 line matches is often covered exactly by a RUN of them:
walk the Japanese, take the longest PS1 line that matches at this point,
keep its English, and go on. A line is only accepted when the pieces cover
nearly all of it (`--cover`, 0.9 by default) - a partial cover would drop
sentences, and dropping text is not translating it.

Tags (<end>, <nl>, <cmdN>) are kept where the PCE put them: the Japanese is
split on them first and each part is covered on its own.

  python pce/tools/pce_stitch.py            # fill work/pce/todo.json entries
  python pce/tools/pce_stitch.py --show 12  # print what the first 12 become
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import pce_reuse as R
import pce_hand as H
import pcescript as S

TODO = os.path.join(WORK, "pce", "todo.json")
TAG = re.compile(r"(<[^>]*>)")
MINRUN = 6              # characters: shorter matches are coincidence


def index():
    """loose Japanese -> English; where several PS1 lines share a key the
    longest English wins (a database article's title also exists as a short
    menu label, and the label is not the article)."""
    loose = {}
    for k, v in R.ps1_map().items():
        key = R.loose_key(k)
        if key and len(v) > len(loose.get(key, "")):
            loose[key] = v
    return loose


def cover(jp, loose):
    """(english pieces, covered fraction) for one Japanese segment.

    A whole segment that is itself a PS1 line is taken at any length (the
    database article titles are two or three characters); inside a segment
    only runs of MINRUN or more count, so a short line cannot match by
    coincidence in the middle of a sentence."""
    text = R.loose_key(R.norm(jp))
    if not text:
        return [], 1.0, 0
    if text in loose:
        return [loose[text]], 1.0, 0
    out, i, hit, gap, worst = [], 0, 0, 0, 0
    while i < len(text):
        # a short PS1 line (an article title) counts only at a boundary
        floor = 2 if (i == 0 or text[i - 1] in "▽。？！") else MINRUN
        for L in range(min(120, len(text) - i), floor - 1, -1):
            seg = text[i:i + L]
            if seg in loose:
                out.append(loose[seg])
                i += L
                hit += L
                worst = max(worst, gap)
                gap = 0
                break
        else:
            i += 1
            gap += 1
    worst = max(worst, gap)
    return out, (hit / len(text) if text else 1.0), worst


def stitch(jp, loose, need=0.9):
    """The whole line's English, or None when the pieces don't cover it.

    The PS1 splits these articles at its own points, which do not line up
    with the PCE's pages, so the cover runs over the whole line with the
    tags taken out; the PCE's <end> pages are dropped (the engine pages by
    itself every three rows) and the line's first colour is kept."""
    colour = ""
    for m in TAG.finditer(jp):
        if m.group().startswith("<cmd"):
            colour = m.group()
            break
    pieces, frac, gap = cover(TAG.sub("", jp), loose)
    # a run of characters no piece covers is a dropped sentence, not a
    # translation: only stray particles and punctuation may fall out
    if frac < need or gap > 2 or not pieces:
        return None
    out, cur = [], None
    for p in pieces:
        for tok in TAG.split(R.wrap(p, cols=10 ** 6)):
            if tok.startswith("<cmd"):
                if tok == cur:
                    continue
                cur = tok
            out.append(tok)
        out.append(" ")
    text = " ".join("".join(out).split())
    if colour and not text.startswith("<cmd"):
        text = colour + text
    return H.wrap(text)


def main():
    loose = index()
    todo = json.load(open(TODO, encoding="utf-8"))
    show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 0
    done = 0
    for e in todo:
        if e.get("en"):
            continue
        text = stitch(e["jp"], loose)
        if not text:
            continue
        rows = S.cells(text)
        if max(rows) > S.COLS:
            continue
        if show and done < show:
            print(e["jp"][:120])
            print("  ->", text[:300])
        e["en"] = text
        done += 1
    if "--show" not in sys.argv:
        json.dump(todo, open(TODO, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{done} lines stitched from PS1 pieces")


if __name__ == "__main__":
    main()
