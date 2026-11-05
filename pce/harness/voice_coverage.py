"""What the PC Engine harness has actually reached: the scene modules, the subtitled voice
lines and the CD-DA cues - and, with --gate, a failure when anything is missing.

    python pce/harness/voice_coverage.py                    # every run log under work/pce
    python pce/harness/voice_coverage.py LOG|DIR [...]      # these logs (a DIR: its *.log, recursively)
    python pce/harness/voice_coverage.py --module 494       # one module's lines, played or not
    python pce/harness/voice_coverage.py DIR ... --gate     # exit 1 unless everything is reached

A regression that never reaches a scene cannot find what is wrong in it: the scene
saves' generic sweep plays few voiced lines, and a glitch there goes out unseen (the
Santa Napoleon line in 494 shipped garbled that way). The pilot logs (`LINELOG=1`)
every module it loads (`module RRR`), every voice line it hears (`line NN sub ... mod
RRR`) and every subtitle page the stub draws (`subpage ...`, judged by subtext.py);
this lists, per module, the lines of pce/translation/subs_<rec>.json no run played,
the cues of cdda_<rec>.json no page showed, and the modules never loaded.

`--gate` fails (exit 1) on any of those that pce/harness/coverage_known.json does not
excuse: each entry there names a line, cue or module the headless pilot cannot reach
and why. An excuse for something that WAS reached is reported too (stale - remove it).
The opening's cues (cdda_opening.json) are drawn by their own stub straight into VRAM,
with no buffer to read; regress.py checks them on screen (opening_check.py).
"""
import glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'pce/tools', 'pce/harness')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LINE = re.compile(r"line ([0-9a-f]{2}) (?:sub|no subtitle).*? mod (\d+)")
MODULE = re.compile(r"^\d+: (?:module (\d+)|loaded module (\d+))", re.M)
TR = os.path.join(ROOT, "pce", "translation")
KNOWN = os.path.join(HERE, "coverage_known.json")


def find_logs(args):
    logs = []
    for a in args:
        if os.path.isdir(a):
            logs += glob.glob(os.path.join(a, "**", "*.log"), recursive=True)
        elif os.path.isfile(a):
            logs.append(a)
    return logs


def heard(logs):
    out, mods = set(), set()
    for path in logs:
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in LINE.finditer(text):
            out.add((int(m.group(2)), m.group(1)))
            mods.add(int(m.group(2)))
        for m in MODULE.finditer(text):
            mods.add(int(m.group(1) or m.group(2)))
    return out, mods


def all_modules():
    return [e["rec"] for e in json.load(open(os.path.join(WORK, "pce", "filetable.json")))["1"]]


def main():
    args = sys.argv[1:]
    only = int(args[args.index("--module") + 1]) if "--module" in args else None
    gate = "--gate" in args
    logs = find_logs([a for a in args if not a.startswith("--") and not a.isdigit()])
    if not logs:
        logs = glob.glob(os.path.join(WORK, "pce", "**", "*.log"), recursive=True)
    got, mods = heard(logs)
    import subtext
    problems, shown, npages = subtext.check(logs)
    known = json.load(open(KNOWN, encoding="utf-8")) if os.path.exists(KNOWN) else {}
    excused = {k for sect in ("lines", "cues", "modules") for k in known.get(sect, {})}
    missing_all, stale = [], []

    total = played = 0
    for path in sorted(glob.glob(os.path.join(TR, "subs_*.json"))):
        stem = os.path.basename(path)[5:-5]
        if not stem.isdigit():
            continue
        rec = int(stem)
        if only is not None and rec != only:
            continue
        lines = {k.split(".")[0]: v for k, v in json.load(open(path, encoding="utf-8")).items()
                 if not k.startswith("_") and isinstance(v, dict) and v.get("en")}
        missing = sorted(nn for nn in lines if (rec, nn) not in got)
        total += len(lines)
        played += len(lines) - len(missing)
        for nn in lines:
            key = f"{rec}:{nn}"
            if nn in missing and key not in excused:
                missing_all.append(f"line {key}")
            elif nn not in missing and key in excused:
                stale.append(key)
        if missing:
            print(f"{rec:3d}: {len(lines) - len(missing)}/{len(lines)} played; never: "
                  + ", ".join(f"{nn} ({lines[nn].get('speaker', '')}: {lines[nn]['en'][:30]})" for nn in missing[:6])
                  + (f" ... +{len(missing) - 6}" if len(missing) > 6 else ""))

    ctotal = cshown = 0
    for path in subtext.cdda_files():
        stem = os.path.basename(path)[5:-5]
        rec = int(stem) if stem.isdigit() else stem
        if only is not None and rec != only:
            continue
        if rec == "opening":            # its own VRAM stub: opening_check.py
            continue
        cs = subtext.cues(rec)
        never = [(i, t, en) for t, i, sp, en in cs if (rec, i) not in shown]
        ctotal += len(cs)
        cshown += len(cs) - len(never)
        for t, i, sp, en in cs:
            key = f"cdda_{rec}:{i}"
            if (rec, i) not in shown and key not in excused:
                missing_all.append(f"cue {key}")
            elif (rec, i) in shown and key in excused:
                stale.append(key)
        if never:
            print(f"cdda_{rec}: {len(cs) - len(never)}/{len(cs)} cues shown; never: "
                  + ", ".join(f"#{i} t{t} ({en[:28]})" for i, t, en in never[:5])
                  + (f" ... +{len(never) - 5}" if len(never) > 5 else ""))

    allm = all_modules()
    nomod = [m for m in allm if m not in mods]
    for m in allm:
        key = f"module {m}"
        if m in nomod and key not in excused:
            missing_all.append(key)
        elif m not in nomod and key in excused:
            stale.append(key)
    if only is None:
        print(f"modules never loaded: {', '.join(map(str, nomod)) or 'none'}")
    print(f"\n{played}/{total} subtitled voice lines played, {cshown}/{ctotal} CD-DA cues shown, "
          f"{len(allm) - len(nomod)}/{len(allm)} modules loaded, in {len(logs)} log(s); "
          f"{npages} subtitle pages read, {len(problems)} wrong")
    if gate:
        for p in missing_all:
            print(f"NOT COVERED: {p}")
        for k in stale:
            print(f"STALE EXCUSE (reached now): {k}")
        print(f"coverage gate: {len(missing_all)} unexcused gap(s), {len(excused)} excused, {len(stale)} stale")
        sys.exit(1 if missing_all else 0)


if __name__ == "__main__":
    main()
