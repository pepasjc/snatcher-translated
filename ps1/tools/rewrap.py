"""Re-break translated strings for the box they are shown in (GitHub #14).

The engine wraps rows at `width` cells (ps1/tools/wordwrap.py gives it word
wrap), but a `￥` in the data is a hard break: text pre-wrapped for the
18-cell dialogue box shows ragged on Gaudi's 14-cell terminal (B030's
database and B040's person file - the strings that start with `＠緑`), and
a row over 18 cells in the box leaves its last word alone on a row. This
strips the soft `￥` of a string, re-wraps its words greedily at the target
width (cells counted the way pairfont packs them: two letters per cell per
run, one per fullwidth glyph, none for `＠x` codes) and puts `￥` back where
the rows end, so every row starts on a pair boundary and the runtime wrap
never has to indent a row by half a cell.

Hard breaks are kept: a `￥` before `▽` (the next paragraph) or before a
space (an indented line: `▽Videophone￥ 00966`), and one after a one-word
`▽` header (`▽Role￥ sound programming`).

  python ps1/tools/rewrap.py --scene B030 --width 14 --prefix ＠緑          # report
  python ps1/tools/rewrap.py --scene B030 --width 14 --prefix ＠緑 --write  # apply
  python ps1/tools/rewrap.py --all --width 18 --over --exclude-prefix ＠緑  # only strings
                                     # with a row over the width; not the terminal's
Pairs without a glyph slot count two cells, so run this again after
rebuild_pairs.py until nothing changes (the table depends on the text).
A string whose re-break no longer fits its byte budget is left alone and
listed (`OVER`); give it a `long` by hand or trim it. Run rebuild_pairs.py
and fit_report.py afterwards: new letter pairs appear across the old
breaks.
"""
import argparse, json, os, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from pairfont import PairFont

TR = os.path.join(ROOT, "ps1/translation")


TABLE = None                              # pair -> slot; a pair without one
                                          # falls back to two fullwidth cells


def _run_cells(run):
    if len(run) % 2:
        run += " "
    n = 0
    for k in range(0, len(run), 2):
        n += 1 if TABLE is None or run[k:k + 2] in TABLE else 2
    return n


def cells(s):
    """Cells of one row as the encoder packs it (no ￥ inside)."""
    n = 0
    run = ""
    i = 0
    while i < len(s):
        ch = s[i]
        if ord(ch) < 0x80:
            run += ch
        else:
            n += _run_cells(run)
            run = ""
            if ch == "＠":
                i += 1
            else:
                n += 1
        i += 1
    return n + _run_cells(run)


def rows_of(text):
    return text.split("￥")


def is_hard(before, after):
    """Keep the ￥ between `before` (the row it ends) and `after`."""
    if not after or after[0] in "▽　 ":
        return True
    body = before.replace("＠緑", "").replace("＠白", "").replace("＠赤", "").replace("＠黄", "")
    if body.startswith("▽") and " " not in body.strip():
        return True
    if body.rstrip().endswith((".", "!", "?", "…", "。", "．")):   # a sentence break
        return True
    return False


def rewrap(text, width):
    """Return the text re-broken at `width`, or None when nothing changes."""
    rows = rows_of(text)
    # group rows into segments between hard breaks
    segments, cur = [], [rows[0]]
    for k in range(1, len(rows)):
        if is_hard(rows[k - 1], rows[k]):
            segments.append(cur)
            cur = [rows[k]]
        else:
            cur.append(rows[k])
    segments.append(cur)
    out = []
    for seg in segments:
        joined = " ".join(r.strip() if i else r.rstrip() for i, r in enumerate(seg))
        # an indented line keeps its indent; only the first row keeps leading spaces
        lead = seg[0][:len(seg[0]) - len(seg[0].lstrip(" "))]
        words = joined.strip(" ").split(" ") if joined.strip(" ") else [""]
        lines, line = [], lead
        for w in words:
            cand = w if line == lead else line + " " + w
            if line == lead:
                cand = lead + w
            if cells(cand) <= width or line == lead:
                line = cand
            else:
                lines.append(line)
                line = w
        lines.append(line)
        out.append("￥".join(lines))
    new = "￥".join(out)
    return None if new == text else new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--prefix", default="", help="only strings starting with this")
    ap.add_argument("--over", action="store_true", help="only strings with a row over the width")
    ap.add_argument("--exclude-prefix", default=None, help="skip strings starting with this")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    pf = PairFont()
    global TABLE
    TABLE = pf.table
    scenes = a.scene or ([f[4:8] for f in sorted(os.listdir(TR)) if f.startswith("ISZ_")] if a.all else [])
    tot = changed = over = 0
    for scene in scenes:
        path = os.path.join(TR, f"ISZ_{scene}.json")
        spec = json.load(open(path, encoding="utf-8"))
        dirty = False
        for e in spec["strings"]:
            en = e.get("en", "")
            if not en or e.get("lock") or not en.startswith(a.prefix):
                continue
            if a.exclude_prefix and en.startswith(a.exclude_prefix):
                continue
            if "￥" in (e.get("long") or ""):
                continue                 # settled on a long by an earlier pass
            if a.over and max(cells(r) for r in rows_of(en)) <= a.width:
                continue
            tot += 1
            new = rewrap(en, a.width) or en
            size = len(pf.encode(new)) + 1
            note = ""
            if size > e["budget"]:
                # the breaks do not fit (a pair rebuild can take a slot away
                # from a string that fit before): hand the string to the
                # runtime wrap with only its hard breaks - never more bytes
                # than any ￥-form; a row may then start half a cell in
                soft = rewrap(new, 10 ** 6) or new
                size = len(pf.encode(soft)) + 1
                if size > e["budget"]:
                    over += 1
                    print(f"OVER  {scene} {e['off']} {size}/{e['budget']}: {new}")
                    continue
                # ...and the properly broken text rides a `long` (repoint.py
                # appends it to the bank and remaps the reference), so the
                # screen still gets rows on pair boundaries
                long = new if new != soft else None
                new, note = soft, f"  (long: {long})" if long else "  (runtime wrap)"
            else:
                long = None
            if new == en and e.get("long") == long:
                continue
            changed += 1
            print(f"{scene} {e['off']}: {en}\n   -> {new}{note}")
            if a.write:
                e["en"] = new
                if long:
                    e["long"] = long
                elif "long" in e and e["long"] and "￥" in e["long"]:
                    del e["long"]        # an earlier pass's long, no longer needed
                dirty = True
        if dirty:
            json.dump(spec, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"# {tot} candidates, {changed} re-broken{' (written)' if a.write else ''}, {over} over budget")


if __name__ == "__main__":
    main()
