"""Grep the English script (ps1/translation/ISZ_*.json) with the Japanese source
beside each hit.  Usage: python ps1/tools/names_grep.py <regex> [out.txt]"""
import io, json, glob, os, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

pat = re.compile(sys.argv[1])
out = open(sys.argv[2], "w", encoding="utf-8") if len(sys.argv) > 2 else sys.stdout
n = 0
for f in sorted(glob.glob("ps1/translation/ISZ_*.json")):
    name = os.path.basename(f)
    ref = {s["off"]: s["jp"] for s in json.load(open(os.path.join("work/ref", name), encoding="utf-8"))["strings"]}
    for s in json.load(open(f, encoding="utf-8"))["strings"]:
        for key in ("en", "long"):
            if key in s and pat.search(s[key]):
                print(name[4:8], s["off"], key, "|", ref.get(s["off"], "?"), "|", s[key], file=out)
                n += 1
print(n, "hits", file=sys.stderr)
