"""Bridge the gaps between consecutive cards of one voice line.

The cue windows come from the ASR segments, and whisper leaves a pause
between sentences: card k ends at b1 and card k+1 starts at a later b0, so
the payload closes the card (the plain box slides down, the band rows go)
and reopens it a few frames later - Ivan's apartment read as text jumping
on and off (Luiz, 2026-09-16, B110). Consecutive cues on the SAME line
(same act, sector, offset - or the same reel - sorted by b0) get b1 := the
next cue's b0 when the gap is under MAX_GAP_S, so a line's cards hand over
without a gap; a reel's real pauses stay (the ending holds 29 s of
silence between two cards, which would otherwise hold a card over
nothing). Mono lines run at 11,025 B/s, a reel at its AIFF rate x frame
bytes. Nothing else in the JSON moves.

    python saturn/subs/bridge_cues.py [--write] [SCENE...]
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ("lib", "saturn/tools", "saturn/subs")]

TRANS = os.path.join(ROOT, "saturn", "translation")
MAX_GAP_S = 1.5
MONO_BPS = 11025
SSND_DATA = 54


def bytes_per_s(c):
    if "reel" in c:
        return c["rate"] * (c["size"] - SSND_DATA) // max(1, c["frames"])     # rate x bytes per frame
    return MONO_BPS


def bridge(cues, max_gap=MAX_GAP_S):
    """Returns [(id, old b1, new b1, gap seconds)] for the cues whose b1 was pulled up."""
    changed = []
    by_line = {}
    for c in cues:
        if not c.get("enabled", True):
            continue
        key = ("reel", c["sdaif"]) if "reel" in c else (c.get("act"), c.get("sector"), c.get("offset"))
        by_line.setdefault(key, []).append(c)
    for key, group in by_line.items():
        group.sort(key=lambda c: c["b0"])
        for a, b in zip(group, group[1:]):
            gap = (b["b0"] - a["b1"]) / bytes_per_s(a)
            if b["b0"] > a["b1"] and gap <= max_gap:
                changed.append((a["id"], a["b1"], b["b0"], gap))
                a["b1"] = b["b0"]
    return changed


def main(argv):
    write = "--write" in argv
    scenes = [a for a in argv if not a.startswith("--")]
    files = sorted(f for f in os.listdir(TRANS) if f.startswith("subs_") and f.endswith(".json"))
    if scenes:
        files = [f for f in files if f[5:-5] in scenes]
    total = 0
    for f in files:
        path = os.path.join(TRANS, f)
        with open(path, encoding="utf-8") as fh:
            spec = json.load(fh)
        changed = bridge(spec["cues"])
        total += len(changed)
        if changed:
            print(f"{f}: {len(changed)} gaps bridged")
            for cid, old, new, gap in changed:
                print(f"  {cid:14} b1 {old} -> {new} (+{gap:.2f} s)")
        if changed and write:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(spec, fh, ensure_ascii=False, indent=1)
    print(f"{total} gaps in {len(files)} files{' written' if write else ' (dry run: --write)'}")


if __name__ == "__main__":
    main(sys.argv[1:])
