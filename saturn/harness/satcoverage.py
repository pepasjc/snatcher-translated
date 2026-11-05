# -*- coding: utf-8 -*-
"""Coverage of the Saturn regression: which scene banks were loaded, which subtitle cues
were read back on screen, which voice lines were heard - across every run given.

    python saturn/harness/satcoverage.py RUN_DIR... [--json OUT] [--gate] [--write-baseline]
    python saturn/harness/satcoverage.py work/reg/final/*     (any satplay / satwhole / regress run dirs)

Reads each run's log.txt (satplay's own log, finished or not; satwhole and regress_saves
write the same lines) - `bank N (Bxxx) in RAM`, `card N ... (cue ID, ...)`, `voice line L`,
`voice reel R`, `PROBLEM KIND ...` - so a run that died still counts for what it saw.

The report (stdout, and --json): per bank, loaded or not and by which run; cues read /
enabled, the ids never read; voice lines heard; problems by kind. The UNREACHABLE table
below names every cue no headless run can read, with the reason - the coverage target is
everything else.

--gate exits 1 when a bank was never loaded, a cue not listed in UNREACHABLE was never
read, or coverage is below the committed floor (saturn/harness/coverage_floor.json -
`--write-baseline` records the current numbers there): the regression fails when its
coverage drops.
"""
import argparse, collections, glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'saturn/tools', 'saturn/harness', 'saturn/subs')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TRANS = os.path.join(ROOT, "saturn", "translation")
FLOOR = os.path.join(HERE, "coverage_floor.json")
BANKS = [f"B{i:02X}0" for i in range(39)]
# Banks with no scene of their own to reach: B140 lives in chunk 42 with B150 (the Saturn
# packs B150 then B140 there; the Act 1 recap runs under it); B000 is the title/opening.
BANK_ALIAS = {}
# banks no scene loads, with the reason (the gate does not ask for them)
BANK_UNREACHABLE = {"B090": "chunk 30 is a 56-byte dummy bank ('I'm a dummy file. Oh, my!'); no scene loads it"}

# cue id (or id prefix ending in '*') -> why no headless run reads it. Keep it short and exact.
# (2026-11-06: the whole game from New Game, every scene save twice - its route and the deep
# sweep -, the coverage routes and the explorer did not bring these up.)
_DUP_REEL96 = ("the Saturn plays Chin's 'That's far enough' and 'It's them! Snatchers! Get them!' as reel 96 "
               "under B210 (B200_c_00/c_01, read); voice lines 553-557, which the PS1 carding follows, never play")
_TV = ("the Kyoto Summit TV news plays as Act 3 opens, under B240 (B240_c5f24..24d, read); "
       "lines 626/627 never play under B230")
UNREACHABLE = {
    # alternate takes and branches the routes do not take
    "B020_047a": "reel 48, a second take of Metal Gear's 'It's no use. I can't move.' (reel 46 = B020_043, read): "
                 "Little John's grip played through again; the story routes free Metal Gear at once",
    "B060_f*": "lines 0-5, the Chief's expense scolding: it plays in his office under B080 after a heavy "
               "binge at Outer Heaven (B080_f1_0..f6_0, read by cov_B100_binge_hq); the videophone bank's "
               "copy never plays",
    "B070_f*": "as B060_f*: the Act 2 phone bank's copy of the Chief's expense scolding",
    "B060_jcall_*": "line 1033, Jamie's urgent call ('my memory's back!'): the Saturn plays her call as reel 102 "
                    "under B1F0 (B1F0_j_*, read); the mono line never played in any run",
    "B070_jcall_*": "as B060_jcall_*",
    "B0E0_0*": "the videotape found on Joy Division's floor, played by Metal Gear (lines 112-135): the find never "
               "turned up - not in Act 1's street and shop sweeps (whole game, deep sweep, explorer), and the "
               "shop is not on the tricycle map from the Act 2 saves",
    "B0E0_123": "line 110, after the videotape (see B0E0_0*)",
    "B0E0_124": "line 111, after the videotape (see B0E0_0*)",
    "B190_c4f6*": "the fortune teller again at Christmas (lines 296-316): she does not appear in the B190 save's "
                  "crowd (the Santa scene comes first); the Act 1 teller (B0D0_10*) is read",
    "B190_c4f7*": "as B190_c4f6*", "B190_c5f*": "as B190_c4f6*",
    "B200_c7f67_0": _DUP_REEL96, "B220_c8f1": _DUP_REEL96, "B220_c8f2": _DUP_REEL96, "B220_c8f3": _DUP_REEL96,
    "B220_c8f4": _DUP_REEL96,
    "B230_f70": _TV, "B230_f70b": _TV, "B230_f71": _TV, "B230_f71b": _TV,
    "B170_r_00": "reel 62 (the motorcycle) plays under B1F0, carded there by ear (B1F0_t_00..04, read); B170's "
                 "copy is the PS1's carding and its first card sits on the reel's silent lead-in (no B1F0 card overlaps it)",
    "B260_f62_0": "line 1029, Gillian's 'Metal!' after Randam's 'So long!' (line 1028, read): never played - the "
                  "ending ran from 'So long!' straight on in every run",
}

LINE_RE = {
    "bank": re.compile(r"^(\d+): bank (\d+) \((B[0-9A-F]{3})\) in RAM"),
    "card": re.compile(r"^(\d+): card (\d+) .*\(cue ([A-Za-z0-9_]+),"),
    "subcue": re.compile(r"^(\d+): subcue ([A-Za-z0-9_]+) up"),
    "string": re.compile(r"^(\d+): card (\d+) .*\(off ([0-9+]+),"),
    "line": re.compile(r"^(\d+): voice line (\d+|None) \(sector (\d+), key (0x[0-9a-f]+)\) in (B[0-9A-F]{3})"),
    "reel": re.compile(r"^(\d+): voice reel (\d+) in (B[0-9A-F]{3})"),
    "over": re.compile(r"^(\d+): voice line (\d+) over: (\d+) bytes \(([0-9.]+)s\)"),
    "problem": re.compile(r"^(\d+): PROBLEM (\S+) (.*?): (.*)$"),
    "face": re.compile(r"(WRONG-FACE|PORTRAIT-PARKED|TEXT-OVER-FACE|SPRITE-OFF-WINDOW)"),
}


def load_cues():
    out = {}
    for path in sorted(glob.glob(os.path.join(TRANS, "subs_*.json"))):
        name = os.path.basename(path)[5:-5]
        out[name] = [c for c in json.load(open(path, encoding="utf-8"))["cues"] if c.get("enabled", True)]
    return out


def unreachable(cid):
    if cid in UNREACHABLE:
        return UNREACHABLE[cid]
    for k, v in UNREACHABLE.items():
        if k.endswith("*") and cid.startswith(k[:-1]):
            return v
    return None


def squash(t):
    return "".join(ch for ch in t.lower() if ch.isalnum())


TEXT = {}


def scan(dirs):
    for cues in load_cues().values():
        for c in cues:
            TEXT[c["id"]] = squash("".join(c.get("rows") or [c.get("en", "")]))
    banks = collections.defaultdict(set)      # bank -> runs
    cues = collections.defaultdict(set)       # cue id -> runs
    lines = collections.defaultdict(set)      # line index -> runs
    reels = collections.defaultdict(set)
    strings = collections.defaultdict(set)    # bank -> string offsets read
    heard = collections.defaultdict(float)    # line index -> the longest play heard (s)
    raised = collections.defaultdict(set)     # cue id -> runs where the payload put it up (`subcue X up`)
    problems = []
    runs = []
    for d in dirs:
        logs = [os.path.join(d, "log.txt")] if os.path.isfile(os.path.join(d, "log.txt")) else \
            sorted(glob.glob(os.path.join(d, "**", "log.txt"), recursive=True))
        for log in logs:
            run = os.path.relpath(os.path.dirname(log), ROOT)
            runs.append(run)
            cur = None
            up = {}                                   # cue text -> the frame the payload last raised it
            for raw in open(log, encoding="utf-8", errors="replace"):
                m = LINE_RE["subcue"].match(raw)
                if m:
                    up[TEXT.get(m.group(2), m.group(2))] = int(m.group(1))
                    raised[m.group(2)].add(run); continue
                m = LINE_RE["bank"].match(raw)
                if m:
                    banks[m.group(3)].add(run); cur = m.group(3); continue
                m = LINE_RE["string"].match(raw)
                if m and cur:
                    strings[cur].update(int(x) for x in m.group(3).split("+")); continue
                m = LINE_RE["card"].match(raw)
                if m:
                    # a plain card counts only when the payload raised that text (the engine's own
                    # strings can read like a cue); band cards and logs from before the subcue
                    # lines (no `up` at all) count as read
                    f, cid = int(m.group(1)), m.group(3)
                    if "[band]" in raw or not up or f - up.get(TEXT.get(cid), -10 ** 9) <= 600:
                        cues[cid].add(run)
                    continue
                m = LINE_RE["over"].match(raw)
                if m:
                    heard[m.group(2)] = max(heard[m.group(2)], float(m.group(4))); continue
                m = LINE_RE["line"].match(raw)
                if m:
                    lines[m.group(2)].add(run); continue
                m = LINE_RE["reel"].match(raw)
                if m:
                    reels[m.group(2)].add(run); continue
                m = LINE_RE["problem"].match(raw)
                if m:
                    problems.append(dict(run=run, frame=int(m.group(1)), kind=m.group(2), where=m.group(3),
                                         detail=m.group(4)[:300]))
                    continue
                m = LINE_RE["face"].search(raw)
                if m and "verdict" in raw.lower() or (m and "speaker" in raw):
                    problems.append(dict(run=run, frame=int(raw.split(":")[0]) if raw.split(":")[0].isdigit() else 0,
                                         kind=m.group(1), where="", detail=raw.strip()[:300]))
    scan.heard = heard
    scan.raised = raised
    return banks, cues, lines, reels, problems, runs, strings


def load_strings():
    """bank -> offsets of the strings with English a player can be shown."""
    out = {}
    for path in glob.glob(os.path.join(TRANS, "SAT_*_B*.json")):
        b = os.path.basename(path)[8:12]
        d = json.load(open(path, encoding="utf-8"))
        out.setdefault(b, set()).update(x["off"] for x in d["strings"]
                                        if (x.get("en") or x.get("long")) and x.get("carry") != "control"
                                        and not x.get("lock") and not x.get("key"))
    return out


def report(dirs, as_json=None, gate=False, write_baseline=False):
    files = load_cues()
    banks, seen, lines, reels, problems, runs, strings = scan(dirs)
    total = sum(len(v) for v in files.values())
    out = dict(runs=runs, banks={}, cues={}, problems=collections.Counter(p["kind"] for p in problems))
    lines_out = []
    w = lines_out.append
    w(f"coverage over {len(runs)} run(s)")
    missing_banks = [b for b in BANKS if b not in banks and b not in BANK_UNREACHABLE]
    w(f"banks loaded: {sum(1 for b in BANKS if b in banks)}/{len(BANKS)}" +
      (f"  never: {' '.join(missing_banks)}" if missing_banks else "") +
      "".join(f"  ({b} unreachable: {r})" for b, r in BANK_UNREACHABLE.items() if b not in banks))
    got = blocked = twins = flashes = 0
    allflash = []
    gaps = {}

    def key(c):
        return ("reel", c["reel"]) if "reel" in c else ("line", c.get("line"))
    # the same audio carded in more than one bank's file (a line the game plays from one bank or
    # another, by the order a player takes): one read covers the voice line; the twin cue that
    # never came up is listed as such, not as missing - the voice line itself was subtitled
    by_audio = collections.defaultdict(list)
    for name, cues in files.items():
        for c in cues:
            by_audio[key(c)].append((name, c))

    def twin_read(c):
        for name, o in by_audio[key(c)]:
            if o["id"] != c["id"] and o["id"] in seen and o["b0"] < c["b1"] and c["b0"] < o["b1"]:
                return o["id"]
        return None
    for name, cues in files.items():
        ids = [c["id"] for c in cues]
        hit = [i for i in ids if i in seen]
        twin = {c["id"]: twin_read(c) for c in cues if c["id"] not in seen}
        twin = {k: v for k, v in twin.items() if v}
        why = {c["id"]: unreachable(c["id"]) for c in cues if c["id"] not in seen and c["id"] not in twin}
        # put up by the payload but gone before satplay's 12-frame settle: a card for a line
        # shorter than half a second (B020's 'What?!') - on screen, too briefly to be read back
        flash = [i for i in ids if i not in seen and i not in twin and i in getattr(scan, "raised", {})]
        unr = [i for i, r in why.items() if r]
        miss = [i for i, r in why.items() if not r and i not in twin and i not in flash]
        got += len(hit); blocked += len(unr); twins += len(twin); flashes += len(flash)
        allflash += flash
        gaps[name] = miss
        out["cues"][name] = dict(total=len(ids), read=len(hit), unreachable=unr, twin=twin, missing=miss)
        w(f"  {name:6} {len(hit):4}/{len(ids):<4} read" + (f", {len(twin)} twin read elsewhere" if twin else "")
          + (f", {len(flash)} flash" if flash else "")
          + (f", {len(unr)} unreachable" if unr else "") +
          (f", MISSING {len(miss)}: {' '.join(miss[:40])}{' ...' if len(miss) > 40 else ''}" if miss else ""))
    w(f"cues read: {got}/{total} ({100.0 * got / max(total, 1):.1f}%), {twins} more whose audio was read through "
      f"another bank's twin cue, {flashes} put up for under the 12-frame settle (flash: {' '.join(allflash[:30])}), "
      f"{blocked} documented unreachable, {total - got - blocked - twins - flashes} missing")
    audio = {k for k, v in by_audio.items()}
    audio_read = {k for k, v in by_audio.items() if any(c["id"] in seen for _, c in v)}
    w(f"voice lines / reels with a cue: {len(audio_read)}/{len(audio)} subtitled on screen at least once")
    w(f"voice lines heard: {len([k for k in lines if k != 'None'])} distinct; reels heard: {len(reels)}")
    carded = {c.get("line") for cues in files.values() for c in cues if "line" in c}
    nocue = sorted((int(k), v) for k, v in getattr(scan, "heard", {}).items() if int(k) not in carded and v >= 1.0)
    w(f"voice lines heard >= 1s with no cue in any file: {len(nocue)}" +
      (": " + " ".join(f"{k}({v:.1f}s)" for k, v in nocue) if nocue else ""))
    out["nocue_lines"] = nocue
    allstr = load_strings()
    sread = sum(len(strings.get(b, set()) & v) for b, v in allstr.items())
    stot = sum(len(v) for v in allstr.values())
    w(f"script strings read (informational): {sread}/{stot} ({100.0 * sread / max(stot, 1):.1f}%); per bank: " +
      " ".join(f"{b}:{len(strings.get(b, set()) & v)}/{len(v)}" for b, v in sorted(allstr.items())))
    out["strings"] = {b: dict(read=len(strings.get(b, set()) & v), total=len(v)) for b, v in sorted(allstr.items())}
    w(f"problems: {dict(out['problems'])}")
    for b in BANKS:
        out["banks"][b] = sorted(banks.get(b, []))
    out["summary"] = dict(banks=sum(1 for b in BANKS if b in banks), cues_read=got, cues_total=total, twins=twins,
                          unreachable=blocked, flash=flashes, missing=total - got - blocked - twins - flashes,
                          audio_read=len(audio_read), audio_total=len(audio))
    print("\n".join(lines_out))
    if as_json:
        json.dump(dict(out, problems=dict(out["problems"]), problem_list=problems), open(as_json, "w", encoding="utf-8"),
                  indent=1, ensure_ascii=False)
    if write_baseline:
        json.dump(dict(banks=out["summary"]["banks"], cues_read=got), open(FLOOR, "w", encoding="utf-8"), indent=1)
        print(f"floor written: {FLOOR}")
    if gate:
        bad = []
        if missing_banks:
            bad.append(f"banks never loaded: {missing_banks}")
        if total - got - blocked - twins - flashes:
            bad.append(f"{total - got - blocked - twins - flashes} cues never read and not documented unreachable")
        if os.path.exists(FLOOR):
            fl = json.load(open(FLOOR, encoding="utf-8"))
            if got < fl.get("cues_read", 0):
                bad.append(f"cues read {got} below the floor {fl['cues_read']}")
            if out["summary"]["banks"] < fl.get("banks", 0):
                bad.append(f"banks {out['summary']['banks']} below the floor {fl['banks']}")
        if bad:
            print("COVERAGE GATE FAILED: " + "; ".join(bad))
            return 1
        print("coverage gate: pass")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args()
    dirs = [d for p in a.dirs for d in (glob.glob(p) or [p])]
    sys.exit(report(dirs, a.json, a.gate, a.write_baseline))


if __name__ == "__main__":
    main()
