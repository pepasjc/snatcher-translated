"""Report translation lines that exceed their byte budget.

Usage: python fit_report.py ISZ_B030 [...]
Prints: index | budget | encoded size | English
so over-length lines can be trimmed in bulk.
"""
import sys, os, json, glob
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
from pairfont import PairFont

TR = os.path.join(ROOT, "ps1/translation")

if __name__ == "__main__":
    wanted = sys.argv[1:]
    pf = PairFont()
    for jpath in sorted(glob.glob(os.path.join(TR, "ISZ_*.json"))):
        name = os.path.basename(jpath).replace(".json", "")
        if wanted and name not in wanted:
            continue
        spec = json.load(open(jpath, encoding="utf-8"))
        bad = 0
        for i, e in enumerate(spec["strings"]):
            if not e.get("en"):
                continue
            size = len(pf.encode(e["en"])) + 1
            if size > e["budget"]:
                bad += 1
                print(f"{i}|{e['budget']}|{size}|{e['en']}")
        if bad:
            print(f"# {name}: {bad} over budget")
