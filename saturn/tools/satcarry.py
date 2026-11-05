"""Carry the finished PS1 English over to the Saturn scene banks.

The Saturn's DATA.BIN chunks 21..59 are the PS1's 39 ISZ banks in the same
layout and the same font-index encoding (saturn/tools/satdata.py). Their
Japanese differs from the PS1's mostly in `￥` placement (the Saturn box is
4 rows x 20 cells, the PS1's 3 x 18), plus a few reworded or extra lines.
This tool does not translate: it matches every Saturn string to a PS1 one
and copies the reviewed English across, re-breaking only rows that would
overflow the Saturn row.

Inputs:
  work/saturn/ref/SAT_NNN_Bxxx.json   the Saturn dump (satdata.py script):
                                       {off, budget, jp}
  work/ref/ISZ_*.json                  the PS1 Japanese (dump_strings.py, or a
                                       copy of the PS1 tree's work/ref)
  ps1/translation/ISZ_*.json           the PS1 English {off, budget, en, long?, lock?}
  work/pair_table.json                 the PS1 pair glyph table (cells/bytes)

Outputs (`run`):
  saturn/translation/SAT_NNN_Bxxx.json   the English data, one record per
      Saturn string: {off, budget, en, long?, lock?, src, carry, note?,
      en_candidate?, sim?}. `src` = "Bxxx:off" of the PS1 string the English came
      from. `carry` = how it was matched (see below). As on the PS1, the
      Japanese stays OUT of the committed file (repository policy: no script
      dumps) - it sits at the same index in work/saturn/ref/.
  work/saturn/carry/SAT_NNN_Bxxx.json    the same records WITH the Saturn jp,
      the PS1 jp and, for candidates, the character diff (scratch).
  work/saturn/carry_report.txt           per-bank counts, samples, the
      unmatched strings with their Japanese.
  work/saturn/carry_fit.txt              every over-budget line (bank|idx|budget|bytes|en).

Matching, per Saturn bank against its PS1 twin (21=B000 ... 59=B260;
chunk 42 = B150 followed by B140; chunk 41 has no twin):
  1. positional alignment (difflib on the `￥`-stripped jp): equal blocks
     pair the strings in order - `exact` when the jp is identical,
     `rebroken` when only the `￥` placement differs;
  2. the rest look their jp up in the twin bank, then in every PS1 bank
     (reuse_fill's idea; a hit that fits the budget is preferred) - the same
     two classes, `src` tells the bank;
  3. what is left inside a replaced block gets the best-ratio PS1 line of
     that block as `en_candidate` (never as `en`) with the jp diff in the
     scratch copy - `candidate`;
  4. pure control records (`<xx>` bytes only) are `control`; anything else
     is unmatched (`carry` absent, `en` empty).

The English is carried verbatim, `￥` breaks included (a PS1 row is <= 18
cells and fits the Saturn's 20). A row over the Saturn width (the PS1 relied
on its runtime word wrap; the Saturn has none) is word-wrapped at 20 cells
and noted. `long` rides over as-is (a runtime remap is the Saturn engine's
job). `lock` follows lock_data_strings.is_data on the Saturn jp plus every
locked PS1 jp. Bytes are counted the PS1 way (pairfont.encode: each ASCII
run between fullwidth codes rounds up to even, 2 bytes per pair with a
glyph slot, 4 for one without, 2 per fullwidth code, 1 null) against the
Saturn budget. A string over budget is still written with its full `en`:
satlong.py carries it to the bank tail and remaps it (the over-budget
policy, 2026-09-12), so nothing here shortens or drops a line.

**Gaudi's terminal** (window mode 7: 14 cells x 4 rows; the `＠緑` strings
of B030/B040 and the `▽`-headed dossier rows) has no runtime wrap either,
so every terminal string is re-flowed at TERM_COLS = **14** cells with
ps1/tools/rewrap's rules: the soft `￥` go, the words re-break greedily,
and a `￥` stays where it is a hard one (before `▽`, before a
space-indented row, after a one-word `▽` header, after a sentence end).
(Until satwrap.py fixed the layout's row accounting - 2026-09-12 - a row
of exactly 14 cells followed by `￥` cost two rows and two such rows with
two after them wedged the machine, so the pass ran at 13; with satwrap in
the build chain a full 14-cell row is one row again.) What remains a data
matter is an entry over 4 rows / 56 cells: the terminal pages the fifth
row (satplay --lint lists them as SCROLL; work/saturn/tighten5.py's hand
tightening is kept in the data - the pass re-flows the current `en`, so
a re-run never undoes it).
`run` does it as it carries; `terminal` does it again over the written
files (the reproducible pass: `--width` to change the rule, `--write` to
save), and both list the entries that come to five rows. A terminal
`long` is re-flowed the same way: since the PS1's full-length pass it is
the full translation satlong shows (until 2026-09-28 a multi-row one was
dropped as a stale re-broken copy of `en`); one past 4 rows scrolls.

Usage (from the repo root):
    python saturn/tools/satcarry.py run          write everything above
    python saturn/tools/satcarry.py fit [NNN..]  over-budget lines from saturn/translation
    python saturn/tools/satcarry.py show NNN     one bank, record by record
    python saturn/tools/satcarry.py terminal [--width 14] [--write]
                                                 re-flow the terminal strings of B030/B040
"""
import os, sys, json, glob, re, difflib, collections
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from textcodec import char_to_code
from lock_data_strings import is_data
import pairfont
import rewrap as _rewrap

SAT_REF = os.path.join(WORK, "saturn", "ref")
PS1_REF = os.path.join(WORK, "ref")
PS1_TR = os.path.join(ROOT, "ps1", "translation")
OUT_TR = os.path.join(ROOT, "saturn", "translation")
OUT_SCRATCH = os.path.join(WORK, "saturn", "carry")
REPORT = os.path.join(WORK, "saturn", "carry_report.txt")
FIT = os.path.join(WORK, "saturn", "carry_fit.txt")

ROWS, COLS = 4, 20                           # the Saturn box
TERM_COLS = 14                               # Gaudi's terminal: 14 cells (13 while the WEDGE was unfixed; satwrap.py fixed the engine 2026-09-12)
TERM_BANKS = ("B030", "B040")                # where `＠緑` text is terminal text
TERM_ENTRIES = (24, 25)
TERM_PREFIX = "＠緑"
CAND_RATIO = 0.5                             # difflib ratio for an en_candidate
FIRST_BANK, LAST_BANK = 21, 59
BANK_NAMES = {21 + i: f"B{i:02X}0" for i in range(39)}
BANK_NAMES[41] = "B140x"
# the PS1 banks behind each chunk, in the order their strings appear
TWINS = {n: [name] for n, name in BANK_NAMES.items()}
TWINS[42] = ["B150", "B140"]
TWINS[41] = []

OMEGA_CODE = 0x7d2a                          # a code the Saturn uses and the PS1
OMEGA = "ω"                                  # never does; textcodec decodes it as ω
CONTROL = re.compile(r"(<[0-9a-f]{2}>|\[[0-9a-f]{4}\])+")

PAIRS = set(json.load(open(pairfont.TABLE, encoding="utf-8")))
_rewrap.TABLE = PAIRS
cells = _rewrap.cells


def strip(jp):
    return jp.replace("￥", "")


PUNCT = "￥　 、。，．・！？!?「」『』（）()…ー〜～"


def plain(jp):
    """jp without breaks, spaces and punctuation - the words alone."""
    return "".join(ch for ch in jp if ch not in PUNCT)


def nbytes(text):
    """Encoded size incl. the null, counted as pairfont.encode packs it."""
    n, run = 0, ""

    def flush(run):
        if len(run) % 2:
            run += " "
        return sum(2 if run[k:k + 2] in PAIRS else 4 for k in range(0, len(run), 2))

    for ch in text:
        if ord(ch) < 0x80:
            run += ch
        else:
            n += flush(run)
            run = ""
            if char_to_code(ch) is None:
                raise ValueError(f"cannot encode {ch!r}")
            n += 2
    return n + flush(run) + 1


def visible(row):
    """The row without its trailing fullwidth padding and `＠Ｃ` - what the
    player sees; the padding only stretches the type-on before a timed close."""
    if row.endswith("＠Ｃ"):
        row = row[:-2]
    return row.rstrip("　")


def wrap_row(row, width):
    """Word-wrap one row (no ￥ inside) at `width` visible cells; keeps its indent."""
    lead = row[:len(row) - len(row.lstrip(" "))]
    words = row.strip(" ").split(" ")
    lines, line = [], None
    for w in words:
        cand = lead + w if line is None else line + " " + w
        if line is None or cells(visible(cand)) <= width:
            line = cand
        else:
            lines.append(line)
            line = w
    lines.append(line)
    return lines


def fit_rows(text, width):
    """Re-break only the rows over `width`; returns (text, [row numbers re-wrapped])."""
    out, changed = [], []
    for k, row in enumerate(text.split("￥")):
        if cells(visible(row)) > width:
            new = wrap_row(row, width)
            if len(new) > 1:
                changed.append(k + 1)
            out.extend(new)
        else:
            out.append(row)
    return "￥".join(out), changed


def is_terminal(bank, en):
    """Terminal text: the `＠緑` entries (a few start with an indent) and the
    `▽`-headed dossier rows of B030/B040 - satplay's rule."""
    return bank in TERM_BANKS and (TERM_PREFIX in en[:6] or "▽" in en)


def width_for(bank, en):
    return TERM_COLS if is_terminal(bank, en) else COLS


def terminal_rebreak(en, width=None):
    """A terminal string re-flowed at `width` (TERM_COLS) with rewrap's rules;
    the text unchanged when every row already fits and no soft break moves."""
    return _rewrap.rewrap(en, width or TERM_COLS) or en


def known_pairs():
    """The pairs that count one cell: the PS1 table's and the Saturn build's."""
    sat = os.path.join(WORK, "saturn", "pair_table_sat.json")
    out = set(PAIRS)
    if os.path.exists(sat):
        out |= set(json.load(open(sat, encoding="utf-8")))
    return out


def load(path):
    return json.load(open(path, encoding="utf-8"))


def load_ps1():
    """{bank: [{jp, en, long, lock, off, budget}]} for every PS1 bank."""
    banks = {}
    for tp in sorted(glob.glob(os.path.join(PS1_TR, "ISZ_*.json"))):
        name = os.path.basename(tp)[4:8]
        rp = os.path.join(PS1_REF, f"ISZ_{name}.json")
        if not os.path.exists(rp):
            sys.exit(f"missing {rp}: dump the PS1 Japanese first (ps1/tools/dump_strings.py)")
        ref, tr = load(rp), load(tp)
        assert len(ref["strings"]) == len(tr["strings"]), name
        recs = []
        for r, e in zip(ref["strings"], tr["strings"]):
            assert r["off"] == e["off"], (name, r, e)
            recs.append({"bank": name, "off": r["off"], "budget": r["budget"], "jp": r["jp"],
                         "en": e.get("en", ""), "long": e.get("long", ""),
                         "lock": bool(e.get("lock"))})
        banks[name] = recs
    return banks


def sat_files():
    out = {}
    for p in sorted(glob.glob(os.path.join(SAT_REF, "SAT_*.json"))):
        out[int(os.path.basename(p)[4:7])] = p
    return out


class Corpus:
    """Global lookups: jp -> PS1 records, raw and ￥-stripped."""

    def __init__(self, ps1):
        self.raw = collections.defaultdict(list)
        self.stripped = collections.defaultdict(list)
        self.locked = set()
        for recs in ps1.values():
            for r in recs:
                self.raw[r["jp"]].append(r)
                self.stripped[strip(r["jp"])].append(r)
                if r["lock"]:
                    self.locked.add(r["jp"])

    @staticmethod
    def pick(cands, budget):
        """The most common English among `cands`, preferring one that fits."""
        by_en = collections.Counter((r["en"], r["long"]) for r in cands if r["en"] or r["long"])
        if not by_en:
            return cands[0]
        ranked = by_en.most_common()
        for (en, lng), _ in ranked:
            if nbytes(en) <= budget:
                return next(r for r in cands if (r["en"], r["long"]) == (en, lng))
        en, lng = ranked[0][0]
        return next(r for r in cands if (r["en"], r["long"]) == (en, lng))


def char_diff(a, b):
    """A compact character diff of two jp strings: -removed +added, = kept runs."""
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            seg = a[i1:i2]
            out.append(seg if len(seg) <= 6 else seg[:3] + "…" + seg[-2:])
        else:
            if i2 > i1:
                out.append("[-" + a[i1:i2] + "]")
            if j2 > j1:
                out.append("[+" + b[j1:j2] + "]")
    return "".join(out)


def carry_bank(n, sat, ps1, corpus):
    """Match one Saturn bank; returns (records, stats)."""
    name = BANK_NAMES[n]
    twin = [r for tn in TWINS[n] for r in ps1[tn]]
    twin_raw = collections.defaultdict(list)
    twin_strip = collections.defaultdict(list)
    for j, r in enumerate(twin):
        twin_raw[r["jp"]].append(j)
        twin_strip[strip(r["jp"])].append(j)
    sat_keys = [strip(s["jp"]) for s in sat]
    twin_keys = [strip(r["jp"]) for r in twin]
    sm = difflib.SequenceMatcher(None, sat_keys, twin_keys, autojunk=False)
    assign = {}                        # sat index -> (twin record, how)
    replace_blocks = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                how = "exact" if sat[i]["jp"] == twin[j]["jp"] else "rebroken"
                assign[i] = (twin[j], how)
        elif tag == "replace":
            replace_blocks.append((i1, i2, j1, j2))
    used = {id(r) for r, _ in assign.values()}

    def nearest(idxs, i):
        free = [j for j in idxs if id(twin[j]) not in used] or list(idxs)
        return min(free, key=lambda j: abs(j - i))

    for i, s in enumerate(sat):
        if i in assign:
            continue
        jp, key = s["jp"], sat_keys[i]
        if CONTROL.fullmatch(jp):
            assign[i] = (None, "control")
            continue
        if jp in twin_raw:
            assign[i] = (twin[nearest(twin_raw[jp], i)], "exact")
        elif key in twin_strip:
            assign[i] = (twin[nearest(twin_strip[key], i)], "rebroken")
        elif jp in corpus.raw:
            assign[i] = (corpus.pick(corpus.raw[jp], s["budget"]), "exact")
        elif key in corpus.stripped:
            assign[i] = (corpus.pick(corpus.stripped[key], s["budget"]), "rebroken")
    # a Saturn-only code (0x7d2a, decoded as ω: `見るω`, `４ωＡＣＴ１`) after or
    # inside an otherwise known line: the known line's English as a candidate
    omega = {}
    for i, s in enumerate(sat):
        if i in assign or OMEGA not in s["jp"]:
            continue
        jp = s["jp"].replace(OMEGA, "")
        key = strip(jp)
        hit = None
        if jp in twin_raw:
            hit = twin[nearest(twin_raw[jp], i)]
        elif key in twin_strip:
            hit = twin[nearest(twin_strip[key], i)]
        elif jp in corpus.raw:
            hit = corpus.pick(corpus.raw[jp], s["budget"])
        elif key in corpus.stripped:
            hit = corpus.pick(corpus.stripped[key], s["budget"])
        if hit is not None and (hit["en"] or hit["long"]):
            assign[i] = (hit, "candidate")
            omega[i] = True
    # candidates: the best PS1 line of the replaced block for what is still open
    for i1, i2, j1, j2 in replace_blocks:
        for i in range(i1, i2):
            if i in assign:
                continue
            best, best_r = None, CAND_RATIO
            for j in range(j1, j2):
                if not (twin[j]["en"] or twin[j]["long"]):
                    continue
                ratio = difflib.SequenceMatcher(None, sat_keys[i], twin_keys[j], autojunk=False).ratio()
                if ratio > best_r:
                    best, best_r = twin[j], ratio
            if best is not None:
                assign[i] = (best, "candidate")

    recs, full, st = [], [], collections.Counter()
    for i, s in enumerate(sat):
        rec = {"off": s["off"], "budget": s["budget"], "en": ""}
        fr = {"off": s["off"], "budget": s["budget"], "jp": s["jp"]}
        src, how = assign.get(i, (None, None))
        notes = []
        if how == "control":
            rec["carry"] = "control"
            st["control"] += 1
        elif how in ("exact", "rebroken"):
            rec["src"] = f"{src['bank']}:{src['off']}"
            rec["carry"] = how
            st[how] += 1
            if not (src["en"] or src["long"] or src["lock"]):
                st["no PS1 English"] += 1
            if src["bank"] not in TWINS[n]:
                st["from other bank"] += 1
                notes.append(f"from {src['bank']}")
            en = src["en"]
            if how == "rebroken":
                d = s["jp"].count("￥") - src["jp"].count("￥")
                if d:
                    notes.append(f"Saturn jp has {abs(d)} {'more' if d > 0 else 'fewer'} break{'s' if abs(d) > 1 else ''}")
            if en:
                width = width_for(name, en)
                if is_terminal(name, en):
                    en2 = terminal_rebreak(en, width)
                    changed = [k + 1 for k, (a, b) in enumerate(zip(en.split("￥"), en2.split("￥"))) if a != b] \
                        if en2 != en else []
                else:
                    en2, changed = fit_rows(en, width)
                if changed:
                    st["rows re-wrapped"] += 1
                    notes.append("row " + ",".join(map(str, changed)) + f" re-wrapped at {width}")
                    fr["en_ps1"] = en
                en = en2
                nrows = en.count("￥") + 1
                if nrows > ROWS:
                    st["over 4 rows"] += 1
                    notes.append(f"{nrows} rows (box has {ROWS})")
            rec["en"] = en
            if src["long"]:
                # since the PS1's full-length pass (100f8eb) a terminal `long` is the
                # full translation, not a re-broken copy of `en`: carried, re-flowed at
                # 14 like `en` (until 2026-09-28 every multi-row one was dropped)
                rec["long"] = (terminal_rebreak(src["long"]) if is_terminal(name, en or src["long"])
                               else src["long"])
            if src["lock"]:
                rec["lock"] = True
            fr["jp_ps1"] = src["jp"]
        elif how == "candidate":
            rec["src"] = f"{src['bank']}:{src['off']}"
            rec["carry"] = "candidate"
            rec["en_candidate"] = src["en"] or src["long"]
            rec["sim"] = round(difflib.SequenceMatcher(None, strip(s["jp"]), strip(src["jp"]), autojunk=False).ratio(), 2)
            fr["jp_ps1"] = src["jp"]
            fr["jp_diff"] = char_diff(s["jp"], src["jp"])
            st["candidate"] += 1
            a, b = plain(s["jp"]), plain(src["jp"])
            if omega.get(i):
                st["omega"] += 1
                notes.append(f"the PS1 line plus the Saturn-only code {OMEGA} ({OMEGA_CODE:#x})")
            elif a == b:
                st["trivial"] += 1
                notes.append("differs only in punctuation/spacing")
            elif a in b:
                st["fragment"] += 1
                notes.append("part of the PS1 line")
            elif b in a:
                st["fragment"] += 1
                notes.append("the PS1 line is part of this one")
        else:
            st["unmatched"] += 1
        # engine data stays original whatever matched
        if is_data(s["jp"]) or s["jp"] in corpus.locked:
            if rec.get("en") or rec.get("long"):
                notes.append("engine data: English dropped")
            rec["en"] = ""
            rec.pop("long", None)
            rec.pop("en_candidate", None)
            rec["lock"] = True
            if rec.get("carry") not in ("exact", "rebroken"):
                rec["carry"] = rec.get("carry") or "lock"
                if how is None:
                    st["unmatched"] -= 1
            st["lock"] += 1
        if rec["en"]:
            size = nbytes(rec["en"])
            if size > s["budget"]:
                st["over budget"] += 1
                fr["over"] = size - s["budget"]        # scratch only: goes stale when en is edited
            # letter pairs the PS1 table has no glyph for (a new pair across a re-wrap)
            miss = missing_pairs(rec["en"])
            if miss:
                st["missing pairs"] += 1
                fr["missing_pairs"] = sorted(miss)
        if notes:
            rec["note"] = "; ".join(notes)
        recs.append(rec)
        fr.update({k: v for k, v in rec.items() if k not in fr})
        full.append(fr)
    return recs, full, st


def missing_pairs(text):
    miss, run = set(), ""

    def flush(run):
        if len(run) % 2:
            run += " "
        return {run[k:k + 2] for k in range(0, len(run), 2) if run[k:k + 2] not in PAIRS}

    for ch in text:
        if ord(ch) < 0x80:
            run += ch
        else:
            miss |= flush(run)
            run = ""
    return miss | flush(run)


def cmd_run():
    ps1 = load_ps1()
    corpus = Corpus(ps1)
    os.makedirs(OUT_TR, exist_ok=True)
    os.makedirs(OUT_SCRATCH, exist_ok=True)
    files = sat_files()
    total = collections.Counter()
    lines, unmatched, fit, samples = [], [], [], []
    keys = ["exact", "rebroken", "candidate", "trivial", "fragment", "omega", "control", "unmatched", "lock",
            "no PS1 English", "from other bank", "rows re-wrapped", "over 4 rows", "over budget", "missing pairs"]
    hdr = f"{'chunk':>5} {'bank':6} {'n':>5} " + " ".join(f"{k[:8]:>8}" for k in keys)
    lines.append("columns: " + ", ".join(keys))
    lines.append(hdr)
    for n in range(FIRST_BANK, LAST_BANK + 1):
        name = BANK_NAMES[n]
        ref = load(files[n])
        sat = ref["strings"]
        recs, full, st = carry_bank(n, sat, ps1, corpus)
        total += st
        total["n"] += len(sat)
        out = {"file": ref["file"], "entry": n, "text_base": ref["text_base"],
               "twins": TWINS[n], "strings": recs}
        with open(os.path.join(OUT_TR, f"SAT_{n:03d}_{name}.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        with open(os.path.join(OUT_SCRATCH, f"SAT_{n:03d}_{name}.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"entry": n, "twins": TWINS[n], "strings": full}, f, ensure_ascii=False, indent=1)
        lines.append(f"{n:5d} {name:6} {len(sat):5d} " + " ".join(f"{st[k]:8d}" for k in keys))
        for i, (s, r) in enumerate(zip(sat, recs)):
            if "carry" not in r:
                unmatched.append(f"{n:3d} {name:6} {i:4d} off={s['off']:6d} budget={s['budget']:3d} {s['jp']}")
            if full[i].get("over"):
                fit.append(f"{name}|{i}|{s['budget']}|{s['budget'] + full[i]['over']}|{r['en']}")
            if r.get("carry") == "rebroken" and r["en"]:
                samples.append((n, name, i, s, r, full[i]))
        print(lines[-1])
    lines.append(f"{'total':>12} {total['n']:5d} " + " ".join(f"{total[k]:8d}" for k in keys))
    print(lines[-1])
    covered = total["exact"] + total["rebroken"]
    summary = [
        "", f"{total['n']} Saturn strings; {covered} carried outright (exact {total['exact']}, "
        f"rebroken {total['rebroken']}; {total['no PS1 English']} of them carry no English on the PS1 either), "
        f"{total['candidate']} with a candidate ({total['trivial']} differ only in punctuation/spacing, "
        f"{total['fragment']} are a part/whole of the PS1 line, {total['omega']} a known line plus the "
        f"Saturn-only {OMEGA} code), "
        f"{total['control']} control records, {total['unmatched']} unmatched, "
        f"{total['lock']} locked; {total['over budget']} over budget, "
        f"{total['rows re-wrapped']} with a row re-wrapped, {total['over 4 rows']} over 4 rows, "
        f"{total['missing pairs']} with a letter pair the pair table lacks.",
    ]
    # samples: rows re-wrapped first (the wrap to judge), then plain rebroken
    rew = [x for x in samples if "re-wrapped" in x[4].get("note", "")]
    plain = [x for x in samples if "re-wrapped" not in x[4].get("note", "")]
    picks = rew[:: max(1, len(rew) // 5)][:5] + plain[:: max(1, len(plain) // 5)][:5]
    sample_lines = ["", "Rebroken samples (Saturn jp / PS1 jp / English rows):"]
    for n, name, i, s, r, fr in picks:
        sample_lines.append(f"- {name}[{i}] budget {s['budget']} ({r.get('note', '')})")
        sample_lines.append(f"    sat: {s['jp']}")
        sample_lines.append(f"    ps1: {fr.get('jp_ps1', '')}")
        for row in r["en"].split("￥"):
            sample_lines.append(f"    | {row:<20}| {cells(row):2d} cells")
    with open(REPORT, "w", encoding="utf-8", newline="\n") as f:
        f.write("Saturn carry-over of the PS1 English (saturn/tools/satcarry.py run)\n\n")
        f.write("\n".join(lines + summary + sample_lines))
        f.write(f"\n\nUnmatched Saturn strings ({len(unmatched)}):\n")
        f.write("\n".join(unmatched) + "\n")
    with open(FIT, "w", encoding="utf-8", newline="\n") as f:
        f.write("bank|idx|budget|bytes|en\n" + "\n".join(fit) + "\n")
    print("\n".join(summary))
    print(f"-> {os.path.relpath(REPORT, ROOT)}, {os.path.relpath(FIT, ROOT)}, "
          f"{len(files)} files under {os.path.relpath(OUT_TR, ROOT)}")


def cmd_fit(which):
    for p in sorted(glob.glob(os.path.join(OUT_TR, "SAT_*.json"))):
        n = int(os.path.basename(p)[4:7])
        if which and n not in which:
            continue
        bad = 0
        for i, e in enumerate(load(p)["strings"]):
            if not e.get("en"):
                continue
            size = nbytes(e["en"])
            if size > e["budget"]:
                bad += 1
                print(f"{i}|{e['budget']}|{size}|{e['en']}")
        if bad:
            print(f"# {os.path.basename(p)}: {bad} over budget")


def cmd_terminal(width, write):
    """Re-flow every terminal string of B030/B040 at `width`; list what changes,
    what no longer fits its budget (satlong carries it) and what runs to five rows."""
    _rewrap.TABLE = known_pairs()
    changed = over = 0
    five = []
    for n in TERM_ENTRIES:
        name = BANK_NAMES[n]
        path = os.path.join(OUT_TR, f"SAT_{n:03d}_{name}.json")
        spec = load(path)
        dirty = False
        for i, e in enumerate(spec["strings"]):
            if e.get("lock") or e.get("key") or not is_terminal(name, e.get("en") or e.get("long") or ""):
                continue
            # `en` and the `long` - since the PS1's full-length pass the full
            # translation, which satlong shows in place of `en` - both re-flowed
            for field in ("en", "long"):
                en = e.get(field) or ""
                if not en:
                    continue
                new = terminal_rebreak(en, width)
                rows = new.split("￥")
                widths = [cells(visible(r)) for r in rows]
                assert max(widths) <= width or any(" " not in visible(r).strip() and cells(visible(r)) > width for r in rows), (name, e["off"], widths)
                if (field == "long" or not e.get("long")) and len([r for r in rows if visible(r).strip()]) > ROWS:
                    five.append((name, e["off"], len(rows), new))
                if new == en:
                    continue
                changed += 1
                size = nbytes(new)
                note = ""
                if field == "en" and size > e["budget"]:
                    over += 1
                    note = f"  ({size} > budget {e['budget']}: satlong carries it)"
                print(f"{name} {e['off']} {field}: {en}\n   -> {new}{note}")
                if write:
                    e[field] = new
                    dirty = True
        if dirty:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(spec, f, ensure_ascii=False, indent=1)
    print(f"# terminal width {width}: {changed} strings re-broken{' (written)' if write else ''}, "
          f"{over} of them over budget (carried as longs), "
          f"{len(five)} run to {ROWS + 1}+ rows (the terminal pages the last):")
    for name, off, n, text in five:
        print(f"  {name} {off}: {n} rows: {text}")


def cmd_show(n):
    name = BANK_NAMES[n]
    full = load(os.path.join(OUT_SCRATCH, f"SAT_{n:03d}_{name}.json"))["strings"]
    for i, r in enumerate(full):
        tag = r.get("carry", "-")
        print(f"{i:4d} {r['budget']:3d} {tag:9} {r['jp']}")
        if r.get("en"):
            print(f"{'':17}{r['en']}  [{nbytes(r['en'])}B]" + (f" over {r['over']}" if r.get("over") else ""))
        if r.get("en_candidate"):
            print(f"{'':17}? {r['en_candidate']}   diff {r.get('jp_diff', '')}")
        if r.get("note"):
            print(f"{'':17}({r['note']})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        cmd_run()
    elif cmd == "fit":
        cmd_fit([int(x) for x in sys.argv[2:]])
    elif cmd == "show":
        cmd_show(int(sys.argv[2]))
    elif cmd == "terminal":
        args = sys.argv[2:]
        width = int(args[args.index("--width") + 1]) if "--width" in args else TERM_COLS
        cmd_terminal(width, "--write" in args)
    else:
        print(__doc__)
