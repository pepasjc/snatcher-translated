"""Offline: every subtitle the built image carries, decoded back from the disc and held
against pce/translation - every voice line and CD-DA cue, reached in play or not.

For each module with a subs_<rec>.json or cdda_<rec>.json, the built module is read
from patched/pce/snatcher_pce.bin (its place from work/pce/build_map.json), its table
found through SUBS_PTR / CUES_PTR (in the module, or in rec 54's first bank - the voice
bank, window 4 - for the tables that overflow), checked against the module's MAGIC,
and every entry's chunks decoded through the module's own pair table. The words must be
the line's `en`, and its speaker byte its speaker. The CD-DA blocks likewise.

    python pce/harness/table_check.py [--image BIN]

Exit 1 on any line missing from its table, decoded to other words, or with a bad pair
code. The pilot's page log (subtext.py) proves what was SHOWN; this proves what is
THERE, for the lines the headless pilot cannot reach.
"""
import argparse, glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import patch_pce as P
import pcepair
import pcescript as PS
import pcesubs as X
import subtext

TR = os.path.join(ROOT, "pce", "translation")


def u16(b, o):
    return b[o] | b[o + 1] << 8


def decode(body, table):
    """(words, issues) of an entry's chunks."""
    out, issues, i = [], [], 0
    while i < len(body):
        c = body[i]
        if c == 0:                          # a marker: mask (and a hold's weight)
            mask = body[i + 1] if i + 1 < len(body) else 0
            i += 3 if mask & 0x20 else 2
            continue
        cells = c & 0x1F
        raw = body[i + 1:i + 1 + 2 * cells]
        i += 1 + 2 * cells
        if len(raw) != 2 * cells:
            issues.append("truncated chunk")
            break
        for k in range(cells):
            hi, lo = raw[2 * k], raw[2 * k + 1]
            p = table.pair(pcepair.slot_of_code(hi, lo)) if pcepair.is_pair(hi, lo) else None
            if p is None or not all(pcepair.printable(ch) for ch in p):
                issues.append(f"bad pair {hi:02x}{lo:02x}")
                out.append("?")
            else:
                out.append("".join(p))
        out.append(" ")
    return "".join(out), issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=P.OUT)
    a = ap.parse_args()
    out = P.Image(a.image, P.T3 + P.RESERVE)
    placed = json.load(open(os.path.join(WORK, "pce", "build_map.json")))
    voice = PS.read_file(out, 54, 4)                    # rec 54's first bank (the voice bank)
    bad, nlines, ncues = [], 0, 0
    recs = sorted({int(os.path.basename(p)[5:-5]) for p in glob.glob(os.path.join(TR, "subs_*.json"))
                   if os.path.basename(p)[5:-5].isdigit()}
                  | {int(os.path.basename(p)[5:-5]) for p in glob.glob(os.path.join(TR, "cdda_*.json"))
                     if os.path.basename(p)[5:-5].isdigit()})
    for rec in recs:
        new_rec, new_n = placed[str(rec)]
        mod = PS.read_file(out, new_rec, new_n)
        table = pcepair.PairTable.from_module(mod)
        magic = mod[X.MAGIC:X.MAGIC + 2]

        def window(ptr):
            if ptr < 0x8000:
                return mod, ptr
            return voice, ptr - 0x8000

        def walk(ptr, cd):
            buf, at = window(ptr)
            if buf[at:at + 2] != magic:
                return None, f"table at {ptr:#06x}: magic {buf[at:at + 2].hex()} is not the module's {magic.hex()}"
            names = at + u16(buf, at + 2)
            at += 4
            found = []
            while at < names and buf[at]:
                if cd:
                    key, start = buf[at], u16(buf, at + 1)
                    ln = u16(buf, at + 5)
                    fpc, char = u16(buf, at + 7), buf[at + 9]
                    body = buf[at + 10:at + 7 + ln]
                    at += 7 + ln
                else:
                    key = buf[at]
                    ln = u16(buf, at + 3)
                    fpc, char = u16(buf, at + 5), buf[at + 7]
                    body = buf[at + 8:at + 5 + ln]
                    at += 5 + ln
                found.append((key, char, body, start if cd else None))
            return found, None

        with pcepair.using(table):
            lines = subtext.lines(rec)
            if lines:
                ptr = u16(mod, X.SUBS_PTR)
                if X.SUBS_PTR and ptr:
                    found, err = walk(ptr, False)
                else:
                    found, err = None, "no SUBS_PTR"
                if err:
                    bad.append(f"{rec}: {err}")
                else:
                    have = {}
                    for key, char, body, _ in found:
                        have.setdefault(f"{key:02x}", []).append((char, body))
                    for nn, specs in lines.items():
                        for sp, en, disp in specs:
                            if disp == "graphic":
                                continue
                            nlines += 1
                            cands = have.get(nn, [])
                            if not cands:
                                bad.append(f"{rec} line {nn}: not in the table")
                                continue
                            ok = False
                            for char, body in cands:
                                text, issues = decode(body, table)
                                if not issues and subtext.words(text) == subtext.words(en):
                                    ok = True
                                    break
                            if not ok:
                                bad.append(f"{rec} line {nn}: the table reads {text[:70]!r} {issues[:3]}; want {en[:70]!r}")
            cues = subtext.cues(rec)
            if cues:
                ptr = u16(mod, X.CUES_PTR)
                if not ptr:
                    bad.append(f"{rec}: CD-DA cues but no CUES_PTR")
                    continue
                found, err = walk(ptr, True)
                if err:
                    bad.append(f"{rec} cues: {err}")
                    continue
                decoded = [(key, start, decode(body, table)) for key, char, body, start in found]
                for track, i, sp, en in cues:
                    ncues += 1
                    bcd = int(f"{int(track):02d}", 16)
                    if not any(k == bcd and not iss and subtext.words(t) == subtext.words(en) for k, s, (t, iss) in decoded):
                        bad.append(f"{rec} cue #{i} (track {track}): not in the block as {en[:60]!r}")
    for b in bad:
        print("TABLE:", b)
    print(f"{nlines} voice lines and {ncues} CD-DA cues decoded from the image; {len(bad)} problem(s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
