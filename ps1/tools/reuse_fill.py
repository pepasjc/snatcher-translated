"""Fill entries whose Japanese exactly matches an already-translated line.

Every scene repeats whole blocks — the item descriptions, menu labels and stock
replies. Filling those from the finished scenes keeps wording identical and cuts
about a quarter of each bank before any hand translation starts.

Only fills when the existing English still fits this entry's budget, prefers the
rendering used most often elsewhere, and never touches an entry marked `lock`
(engine data, see lock_data_strings.py).

Usage: python reuse_fill.py ISZ_B130 [ISZ_B140 ...]
Writes work/<scene>_todo.txt listing what still needs translating.
"""
import json, glob, os, sys, collections
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
from pairfont import PairFont

REF = os.path.join(ROOT, "work", "ref")
TR = os.path.join(ROOT, "ps1/translation")


def corpus(exclude):
    by_jp = collections.defaultdict(collections.Counter)
    for f in sorted(glob.glob(os.path.join(TR, "ISZ_*.json"))):
        name = os.path.basename(f).replace(".json", "")
        if name in exclude:
            continue
        rpath = os.path.join(REF, name + ".json")
        if not os.path.exists(rpath):
            continue
        ref = json.load(open(rpath, encoding="utf-8"))
        tr = json.load(open(f, encoding="utf-8"))
        for r, e in zip(ref["strings"], tr["strings"]):
            if e.get("en") and not e.get("lock"):
                by_jp[r["jp"]][e["en"]] += 1
    return by_jp


if __name__ == "__main__":
    targets = sys.argv[1:]
    if not targets:
        sys.exit(__doc__)
    pf = PairFont()
    by_jp = corpus(set(targets))
    for target in targets:
        ref = json.load(open(os.path.join(REF, target + ".json"), encoding="utf-8"))
        p = os.path.join(TR, target + ".json")
        spec = json.load(open(p, encoding="utf-8"))
        filled, todo = 0, []
        for i, (r, e) in enumerate(zip(ref["strings"], spec["strings"])):
            if e.get("en") or e.get("lock"):
                continue
            for en, _ in by_jp.get(r["jp"], collections.Counter()).most_common():
                if len(pf.encode(en)) + 1 <= e["budget"]:
                    e["en"] = en
                    filled += 1
                    break
            else:
                todo.append(i)
        json.dump(spec, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        out = os.path.join(ROOT, "work", target[4:].lower() + "_todo.txt")
        open(out, "w", encoding="utf-8").write("\n".join(
            f"{i}|{ref['strings'][i]['budget']}|{ref['strings'][i]['jp']}" for i in todo))
        print(f"{target}: {filled} filled from existing scenes, "
              f"{len(todo)} need translation -> {os.path.relpath(out, ROOT)}")
