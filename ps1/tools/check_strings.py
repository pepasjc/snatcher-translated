"""Lint the bank strings after a review pass: the line breaks and the colour
codes (Luiz, 2026-09-22).

A reviewer's proposal is plain prose; the engine's text is not. Every
accepted line has to come back with the `＠` colour codes the Japanese
carried, the `<xx>` control bytes it carried, and rows the box can draw -
and an LLM drops a colour code or lengthens a row without noticing. The
review server re-breaks what it saves (`rebreak`), but a text it could not
re-break (over budget, control bytes inside) is written as typed, and no
tool looked at the codes at all.

    python ps1/tools/check_strings.py --all
    python ps1/tools/check_strings.py --scene B010 B020
    python ps1/tools/check_strings.py --all --decided     # only the lines decided
                                                          # in work/trpass/<S>/decisions.json
    python ps1/tools/check_strings.py --all --fix         # re-break what is over its row width
    python ps1/tools/check_strings.py --all --quiet       # counts and errors only

What it reports, per string, against the Japanese in `work/ref/ISZ_<S>.json`
(the SHIPPED text is checked: the `long` where there is one, else the `en`):

  CODE-LOST   the Japanese colours the line and ours does not            error
  CODE-BAD    `＠` on a character that is not a colour code               error
  CODE-CTL    `＠Ｃ` (the timed close) is not carried over                 error
  CTRL        a `<xx>` control byte of the Japanese is gone              error
  ROW-OVER    a row wider than the box (18 cells, 14 on B030/B040's      error
              `＠緑` terminal), trailing padding not counted
  BUDGET      the `en` does not fit its slot and there is no `long`      error
  CODE-EXTRA  ours colours more than the Japanese (an added emphasis)    warning
  CODE-ORDER  the same codes in another order                            warning
  MARK        a different number of `▽` list marks than the Japanese     warning
  TERM-SCROLL a terminal entry over 4 rows: its first row scrolls away   warning
  LONG-DROPPED  an accepted `en` replaced a full-length `long` with      warning
              less than 80% of its text (--decided)

`--fix` re-lays ROW-OVER lines with `rewrap.rewrap` (the same call the
review server makes) and writes them back; an `en` whose breaks no longer
fit its slot gets them as a `long` instead. Nothing else is rewritten:
a missing colour code is a translation decision, not a layout one.

Exit status is non-zero when anything is reported as an error.
"""
import argparse, glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import rewrap
from pairfont import PairFont

TR = os.path.join(ROOT, "ps1/translation")
REF = os.path.join(WORK, "ref")
TRPASS = os.path.join(WORK, "trpass")

COLOURS = "＠青赤紫緑水黄白桃"        # ＠ + one of these paints the rest of the line: the
                                      # engine's own table (Saturn 0x060E4DA8, parsed at
                                      # 0x060B4604 - the second character is looked up in
                                      # the SAME table, so `＠＠` is colour 0, the default
                                      # the Japanese goes back to after a coloured word)
CLOSE = "Ｃ"                          # ＠Ｃ closes the box on a timer
VALID = COLOURS + CLOSE
CODE = re.compile(r"＠(.)")
CTRL = re.compile(r"<[0-9a-f]{2}>")
TERMINAL_SCENES = ("B030", "B040")    # Gaudi's database and the person file: 14-cell rows
TERM_ROWS = 4                         # a fifth row scrolls the first away
PAD = " 　"                       # a row padded out to clear the one under it


def width_of(sid, text):
    return 14 if sid in TERMINAL_SCENES and text.startswith("＠緑") else 18


def rows_of(text):
    return text.split("￥")


def row_cells(row):
    """Cells of a row, trailing padding not counted (a card pads its last row
    with fullwidth spaces to wipe the row under it, the `＠Ｃ` after the
    padding - B020's Insector card)."""
    while True:
        stripped = row.rstrip(PAD)
        if CODE.fullmatch(stripped[-2:] or "  "):
            stripped = stripped[:-2]
        if stripped == row:
            return rewrap.cells(row)
        row = stripped


def codes(text):
    return CODE.findall(text)


def _minus(a, b):
    """The codes of `a` that `b` has no copy of, in order."""
    rest = list(b)
    out = []
    for c in a:
        if c in rest:
            rest.remove(c)
        else:
            out.append(c)
    return out


def check_string(sid, rec, jp, decision=None):
    """[(level, tag, detail), ...] for one string record."""
    out = []
    en = rec.get("en") or ""
    long = rec.get("long") or ""
    ship = long or en
    if not ship or rec.get("lock"):
        return out

    jc = [c for c in codes(jp) if c in COLOURS]
    sc = [c for c in codes(ship) if c in COLOURS]
    bad = [c for c in codes(ship) if c not in VALID]
    if bad or ship.endswith("＠"):
        out.append(("error", "CODE-BAD", "＠" + "".join(bad) if bad else "trailing ＠"))
    missing = _minus(jc, sc)
    if missing:
        out.append(("error", "CODE-LOST", ("the line is painted ＠" + "＠".join(missing)
                                           + " in the Japanese") if not sc else
                                          f"jp ＠{'＠'.join(jc)} vs ours ＠{'＠'.join(sc)}"))
    elif sorted(jc) != sorted(sc):
        out.append(("warn", "CODE-EXTRA", f"ours colours more: ＠{'＠'.join(_minus(sc, jc))}"))
    elif jc != sc:
        out.append(("warn", "CODE-ORDER", f"jp ＠{'＠'.join(jc)} vs ours ＠{'＠'.join(sc)}"))
    for code in CLOSE:                  # the timed close: counts must match
        if jp.count("＠" + code) != ship.count("＠" + code):
            out.append(("error", "CODE-CTL", f"jp {jp.count('＠' + code)} ＠{code}, ours {ship.count('＠' + code)}"))
    if CTRL.findall(jp) != CTRL.findall(ship):
        out.append(("error", "CTRL", f"jp {''.join(CTRL.findall(jp)) or '-'} vs ours {''.join(CTRL.findall(ship)) or '-'}"))

    width = width_of(sid, ship)
    rows = rows_of(ship)
    over = [(i, row_cells(r)) for i, r in enumerate(rows) if row_cells(r) > width]
    if over:
        out.append(("error", "ROW-OVER", f"row {over[0][0]} is {over[0][1]} cells of {width}"
                                         + (f" (+{len(over) - 1} more)" if len(over) > 1 else "")))
    if width == 14 and len(rows) > TERM_ROWS:
        out.append(("warn", "TERM-SCROLL", f"{len(rows)} rows: the first {len(rows) - TERM_ROWS} scroll away"))
    if jp.count("▽") != ship.count("▽"):
        out.append(("warn", "MARK", f"jp {jp.count('▽')} ▽, ours {ship.count('▽')}"))

    if en and not long:
        size = string_size(en)
        if size is not None and size > rec["budget"]:
            out.append(("error", "BUDGET", f"{size} bytes of {rec['budget']}, no long"))

    if decision and decision.get("decision") == "accept" and decision.get("was_long"):
        was = len(decision["was_long"].replace("￥", ""))
        now = len(ship.replace("￥", ""))
        if was and now < 0.8 * was:
            out.append(("warn", "LONG-DROPPED", f"{now} characters where the long had {was}"))
    return out


_pf = None


def pf():
    global _pf
    if _pf is None:
        _pf = PairFont()
        rewrap.TABLE = _pf.table
    return _pf


def string_size(text):
    try:
        return len(pf().encode(text)) + 1
    except Exception:
        return None                       # control bytes the encoder does not take


def fix_breaks(sid, rec):
    """Re-lay the shipped text at its row width; True when it changed. The
    `long` is re-laid in place; an `en` too, unless the breaks overflow its slot."""
    field = "long" if rec.get("long") else "en"
    text = rec[field]
    new = rewrap.rewrap(text, width_of(sid, text))
    if new is None:
        return False
    if field == "en":
        size = string_size(new)
        if size is None or size > rec["budget"]:
            # the breaks cost the bytes the slot lacks: the broken text rides a `long`
            # (repoint carries it) and the `en` stays as the slot's fallback
            rec["long"] = new
            return True
    rec[field] = new
    return True


def decisions(sid):
    path = os.path.join(TRPASS, sid, "decisions.json")
    if not os.path.exists(path):
        return {}
    return json.load(open(path, encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", nargs="*", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--decided", action="store_true", help="only the lines with a decision recorded")
    ap.add_argument("--fix", action="store_true", help="re-break the ROW-OVER lines and write")
    ap.add_argument("--quiet", action="store_true", help="errors only")
    a = ap.parse_args()
    scenes = a.scene or ([os.path.basename(p)[4:8] for p in sorted(glob.glob(os.path.join(TR, "ISZ_*.json")))]
                         if a.all else [])
    if not scenes:
        ap.error("give --scene B010 [...] or --all")
    pf()
    totals = {"error": 0, "warn": 0, "strings": 0, "fixed": 0}
    tags = {}
    for sid in scenes:
        path = os.path.join(TR, f"ISZ_{sid}.json")
        spec = json.load(open(path, encoding="utf-8"))
        ref = json.load(open(os.path.join(REF, f"ISZ_{sid}.json"), encoding="utf-8")) \
            if os.path.exists(os.path.join(REF, f"ISZ_{sid}.json")) else {"strings": []}
        jp_by_off = {s["off"]: s.get("jp", "") for s in ref["strings"]}
        dec = decisions(sid)              # for --decided, and for LONG-DROPPED
        dirty = False
        for i, rec in enumerate(spec["strings"]):
            if a.decided and f"s:{i}" not in dec:
                continue
            if not (rec.get("en") or rec.get("long")) or rec.get("lock"):
                continue
            totals["strings"] += 1
            found = check_string(sid, rec, jp_by_off.get(rec["off"], ""), dec.get(f"s:{i}"))
            if a.fix and any(t == "ROW-OVER" for _, t, _ in found):
                if fix_breaks(sid, rec):
                    dirty = True
                    totals["fixed"] += 1
                    found = check_string(sid, rec, jp_by_off.get(rec["off"], ""), dec.get(f"s:{i}"))
            for level, tag, detail in found:
                totals[level] += 1
                tags[tag] = tags.get(tag, 0) + 1
                if a.quiet and level != "error":
                    continue
                ship = rec.get("long") or rec.get("en")
                who = f"{sid} s:{i} @{rec['off']}"
                print(f"{level.upper():5} {tag:12} {who}: {detail}")
                print(f"      {ship}")
        if dirty:
            with open(path, "w", encoding="utf-8", newline="\n") as f:   # the translation JSON is LF
                json.dump(spec, f, ensure_ascii=False, indent=1)
    print(f"# {totals['strings']} strings checked, {totals['error']} errors, {totals['warn']} warnings"
          + (f", {totals['fixed']} re-broken (written)" if a.fix else ""))
    if tags:
        print("# " + ", ".join(f"{t} {n}" for t, n in sorted(tags.items(), key=lambda kv: -kv[1])))
    return 1 if totals["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
