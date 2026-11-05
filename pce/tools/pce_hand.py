"""Fold hand-written English into pce/translation/dialogue_hand.json.

The lines the PS1 has no counterpart for (the PCE's save system, the
shooting range, the staff quiz, Jamie's calls...) are translated by hand in
`work/pce/todo.json` (`pce_reuse.py --todo` writes the stub: key, uses, jp,
en). This folds every filled `en` into the committed hand file, wrapping it
for the box - 18 cells a row, three rows a page - and keeping the tags:

  <nl> a row break, <end> a page break (the engine waits), <wait> a pause,
  <cmdN> a colour/face switch, which costs no cell.

A break in the text is honoured and the text between breaks is wrapped, so
a hand-written row that runs long is broken rather than rejected. Rows are
measured in CELLS (two Latin letters share one), so a row holds up to 36
letters.

  python pce/tools/pce_hand.py            # fold todo.json in, report
  python pce/tools/pce_hand.py --check    # only report what would change
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import pcepair
import pcescript as S
import pcetext as T

TODO = os.path.join(WORK, "pce", "todo.json")
TAG = re.compile(r"(<[^>]*>)")
BREAK = ("<end>", "<wait>", "<nl>")


def wrap(text, cols=S.WRAP):
    """Break `text` into rows of at most `cols` cells, tags kept.

    The breaks already in the text are honoured; the text between them is
    wrapped, so a hand-written row that runs long is still broken."""
    out, row = [], ""

    for chunk in re.split(r"(<end>|<wait>|<nl>)", text):
        if chunk in BREAK:
            out.append(row)
            if chunk != "<nl>":
                out.append(chunk)
            row = ""
            continue
        for word in re.findall(r"(?:<[^>]*>)*\S+|\s+", chunk):
            if word.isspace():
                continue
            cand = (row + " " + word) if row else word
            if row and S.width(cand) > cols:
                out.append(row)
                row = word
            else:
                row = cand
    out.append(row)
    rows, res = [r for r in out if r != ""], ""
    for i, r in enumerate(rows):
        if r in BREAK:
            res += r
            continue
        res += r
        if i + 1 < len(rows) and rows[i + 1] not in BREAK:
            res += "<nl>"
    return res


def main():
    todo = json.load(open(TODO, encoding="utf-8"))
    hand = json.load(open(S.HAND, encoding="utf-8")) if os.path.exists(S.HAND) else {}
    added, bad = 0, []
    for e in todo:
        en = e.get("en", "").strip()
        if not en:
            continue
        text = wrap(en)
        # measured before layout(): a row of exactly COLS becomes a <join>
        # there, and the engine's own wrap puts the rest on the next row
        rows = S.cells(text)
        if max(rows) > S.COLS:
            bad.append((max(rows), en))
            continue
        try:
            with pcepair.using(pcepair.PairTable()):        # any table: the codes are thrown away
                T.encode(S.layout(text), english=True)
        except (ValueError, KeyError) as err:
            bad.append((str(err), en))
            continue
        if hand.get(e["key"]) != text:
            added += 1
        hand[e["key"]] = text
    for why, en in bad:
        print(f"  rejected ({why}): {en}")
    if "--check" not in sys.argv:
        json.dump(hand, open(S.HAND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    done = sum(1 for e in todo if e.get("en", "").strip())
    print(f"{done}/{len(todo)} translated, {added} written, {len(hand)} in the hand file")


if __name__ == "__main__":
    main()
