"""The candidate records brought up to the PS1's current English (Luiz,
2026-09-30: "the saturn is not aligned with the PS1 translation, it is still
using the old translation").

A `candidate` record is a Saturn string whose Japanese differs from its PS1
twin (punctuation, a fragment, the Saturn's own number...). satcarry offered
the PS1 `en` as `en_candidate` and a person resolved it on 2026-09-17:
`candidate_ok` (taken as is) or `candidate_edit` (adapted). Two things kept
912 of them on the 09-17 English after the PS1's full-length review:
satcarry never carried the PS1 `long` for a candidate (only its short `en`),
and the 2026-09-28 three-way merge re-applied the 09-17 resolutions as hand
edits over the new carry.

    python saturn/tools/satcandidates.py report     # counts per class, nothing written
    python saturn/tools/satcandidates.py apply      # the mechanical classes into saturn/translation/
    python saturn/tools/satcandidates.py review     # work/saturn/recarry/review.json: the rest, with context

Mechanical (the Japanese difference changes nothing a translation says):
  ok-same     candidate_ok, "differs only in punctuation/spacing" or no note
  edit-same   candidate_edit, "differs only in punctuation/spacing" (edited
              for length before the full-length pass; the `long` carries it now)
  omega       a label that is the PS1 label plus the Saturn-only code ω at
              its end - the new label, ω kept
Each takes the PS1's current `en` fitted to the Saturn's rows as satcarry does
for an exact record (fit_rows at 20, terminal_rebreak at 14) and the PS1's
`long` (re-flowed on the terminal). Everything else - a fragment of a PS1 line,
the Saturn's own numbers and answers, a reworded adaptation - goes to the
review list for re-adaptation from the new PS1 English.
"""
import glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import satcarry

TR = os.path.join(ROOT, "saturn", "translation")
REF = os.path.join(WORK, "saturn", "ref")
OUT = os.path.join(WORK, "saturn", "recarry")
TRIVIAL = "differs only in punctuation/spacing"
OMEGA = "ω"


def fitted(bank, en):
    """The PS1 `en` on the Saturn's rows, as satcarry fits an exact record."""
    if not en:
        return en
    width = satcarry.width_for(bank, en)
    if satcarry.is_terminal(bank, en):
        return satcarry.terminal_rebreak(en, width)
    return satcarry.fit_rows(en, width)[0]


def carried_long(bank, en, long):
    if not long:
        return None
    return satcarry.terminal_rebreak(long) if satcarry.is_terminal(bank, en or long) else long


def classify(r, src):
    note = r.get("note", "")
    if r["carry"] == "candidate_ok" and (note == TRIVIAL or not note):
        return "ok-same"
    if r["carry"] == "candidate_edit" and note == TRIVIAL:
        return "edit-same"
    old = r.get("en", "")
    if (r["carry"] == "candidate_edit" and old.endswith(OMEGA) and OMEGA not in old[:-1]
            and not src["long"] and OMEGA not in src["en"]):
        return "omega"
    return "review"


def records():
    ps1 = {(b, x["off"]): x for b, recs in satcarry.load_ps1().items() for x in recs}
    for path in sorted(glob.glob(os.path.join(TR, "SAT_*.json"))):
        name = os.path.basename(path)[8:12]
        d = json.load(open(path, encoding="utf-8"))
        for r in d["strings"]:
            if r.get("carry") not in ("candidate_ok", "candidate_edit") or not r.get("src"):
                continue
            b, o = r["src"].split(":")
            yield path, d, name, r, ps1[(b, int(o))]


def new_values(name, r, src, cls):
    en = fitted(name, src["en"])
    long = carried_long(name, src["en"], src["long"])
    if cls == "omega":
        en = en + OMEGA
    return en, long


def main(argv):
    cmd = argv[0] if argv else "report"
    import collections
    counts, changed = collections.Counter(), collections.Counter()
    touched = {}
    review = []
    refs = {}
    for path, d, name, r, src in records():
        cls = classify(r, src)
        counts[cls] += 1
        if cls == "review":
            if cmd == "review":
                refp = next(iter(glob.glob(os.path.join(REF, f"SAT_*_{name}.json"))), None)
                if refp and refp not in refs:
                    refs[refp] = {x["off"]: x for x in json.load(open(refp, encoding="utf-8"))["strings"]}
                jp = refs.get(refp, {}).get(r["off"], {}).get("jp", "") if refp else ""
                review.append({"bank": name, "off": r["off"], "budget": r["budget"], "carry": r["carry"],
                               "note": r.get("note", ""), "jp_saturn": jp, "jp_ps1": src["jp"],
                               "ps1_en": src["en"], "ps1_long": src["long"],
                               "saturn_en_old": r.get("en", ""), "saturn_long_old": r.get("long", ""),
                               "src": r["src"]})
            continue
        en, long = new_values(name, r, src, cls)
        if en != r.get("en") or long != r.get("long"):
            changed[cls] += 1
            if cmd == "apply":
                r["en"] = en
                r["en_candidate"] = src["en"]
                if long:
                    r["long"] = long
                else:
                    r.pop("long", None)
                touched[path] = d
    print("classes:", dict(counts))
    print("would change" if cmd != "apply" else "changed", dict(changed))
    if cmd == "apply":
        for path, d in touched.items():
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)     # satcarry's format: no newline at the end
        print(f"wrote {len(touched)} files")
    if cmd == "review":
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "review.json"), "w", encoding="utf-8") as f:
            json.dump(review, f, ensure_ascii=False, indent=1)
        print(f"{len(review)} records -> {os.path.join(OUT, 'review.json')}")


if __name__ == "__main__":
    main(sys.argv[1:])
