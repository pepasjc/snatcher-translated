"""Dump every ISZ scene file into:

  work/ref/ISZ_*.json   - local reference (Japanese source text), NOT committed
  ps1/translation/ISZ_*.json - our work product: off/budget/en only, committed

Requires a Japanese Snatcher PS1 disc extracted via extract_ps1.py.
Existing "en" values are preserved on re-run.
"""
import sys, os, json, glob, struct
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
from textcodec import decode_stream

SRC = os.path.join(ROOT, "discs/extracted_ps1", "PLN", "ISZ")
TR = os.path.join(ROOT, "ps1/translation")
REF = os.path.join(ROOT, "work", "ref")

def dump(path):
    d = open(path, "rb").read()
    base = struct.unpack(">H", d[0:2])[0]
    entries = []
    i = base
    while i < len(d):
        j = d.find(b"\x00", i)
        if j < 0:
            j = len(d)
        s = d[i:j]
        if s:
            entries.append({"off": i, "budget": (j - i) + 1, "jp": decode_stream(s)})
        i = j + 1
    return base, entries

if __name__ == "__main__":
    os.makedirs(TR, exist_ok=True)
    os.makedirs(REF, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(SRC, "*.BIN"))):
        fname = os.path.basename(path)
        name = fname.replace(".BIN", "")
        base, entries = dump(path)
        # reference (with Japanese) - local only
        with open(os.path.join(REF, name + ".json"), "w", encoding="utf-8") as f:
            json.dump({"file": fname, "text_base": base, "strings": entries},
                      f, ensure_ascii=False, indent=1)
        # translation file - preserve existing English
        tpath = os.path.join(TR, name + ".json")
        prev = {}
        if os.path.exists(tpath):
            old = json.load(open(tpath, encoding="utf-8"))
            prev = {e["off"]: e.get("en", "") for e in old["strings"]}
        out = [{"off": e["off"], "budget": e["budget"], "en": prev.get(e["off"], "")}
               for e in entries]
        with open(tpath, "w", encoding="utf-8") as f:
            json.dump({"file": fname, "text_base": base, "strings": out},
                      f, ensure_ascii=False, indent=1)
        print(f"{name}: {len(entries)} strings, text base {base:#x}")
