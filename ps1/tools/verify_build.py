"""Check that every file in patched/ was encoded against the current pair table.

rebuild_pairs.py reassigns which glyph slot each letter pair owns, so bytes
written under an older table decode as different pairs — the text looks like a
patching bug but is really a stale file. This re-encodes each translated string
with the table on disk and compares it against the bytes actually sitting in
patched/, and decodes the speaker name table the same way.

patch_disc.py calls check() and refuses to build an image that fails, so the
class of bug cannot reach a disc. Run standalone for a report:

    python verify_build.py
"""
import sys, os, json, glob
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
import pairfont
from pairfont import PairFont
import translate_names
import lock_data_strings

TR = os.path.join(ROOT, "ps1/translation")
OUT = os.path.join(ROOT, "patched")


def check(verbose=True):
    """Return a list of problem strings; empty means the build is consistent."""
    pf = PairFont()
    problems = []

    for jpath in sorted(glob.glob(os.path.join(TR, "ISZ_*.json"))):
        name = os.path.basename(jpath).replace(".json", "")
        spec = json.load(open(jpath, encoding="utf-8"))
        todo = [e for e in spec["strings"] if e.get("en") and not e.get("lock")]
        if not todo:
            continue
        path = os.path.join(OUT, spec["file"])
        if not os.path.exists(path):
            problems.append(f"{name}: {spec['file']} missing from patched/")
            continue
        d = open(path, "rb").read()
        moved = {}
        if name == "ISZ_B040":
            kt = os.path.join(ROOT, "work", "keytable_remaps.json")
            if os.path.exists(kt):
                moved = {int(k): v for k, v in
                         json.load(open(kt))["moved"].items()}
        for e in spec["strings"]:
            if e.get("lock") and (e.get("en") or e.get("long")):
                problems.append(f"{name} off={e['off']:#x}: engine data is locked "
                                f"but carries English {e['en']!r} — the videophone "
                                f"cannot match dialled numbers")
        # Typed-puzzle targets must match the prescription exactly: fullwidth
        # text (one glyph code per letter, matching what the keyboard emits),
        # in "en" when it fits the slot, in "long" when repoint must carry it.
        for i, text in lock_data_strings.PUZZLE_TARGETS.get(
                os.path.basename(jpath), {}).items():
            e = spec["strings"][i]
            fits = lock_data_strings.encoded_len(text) <= e["budget"]
            want_en, want_long = (text, "") if fits else ("", text)
            if (e.get("lock") or e.get("en", "") != want_en
                    or e.get("long", "") != want_long):
                problems.append(f"{name} idx {i}: puzzle target drifted from "
                                f"prescription {text!r} — run "
                                f"lock_data_strings.py")
        stale = 0
        for e in todo:
            eb = pf.encode(e["en"]) + b"\x00"
            if len(eb) > e["budget"]:            # over budget, never written
                continue
            off = moved.get(spec["strings"].index(e), e["off"])
            if d[off:off+len(eb)] != eb:
                stale += 1
        if stale:
            problems.append(f"{name}: {stale} of {len(todo)} strings do not match "
                            f"the current pair table (stale patched file?)")
        elif verbose:
            print(f"{name}: {len(todo)} strings verified")

    # Speaker names: the file that actually went wrong once, so decode it back
    # to text rather than just comparing bytes.
    npath = os.path.join(OUT, "NSZ_B000.BIN")
    if not os.path.exists(npath):
        problems.append("NSZ_B000.BIN missing from patched/")
    else:
        rev = {c: p for p, (s, c) in pf.table.items()}
        got = []
        d = open(npath, "rb").read()
        i = 0
        while i < len(d):
            ln = d[i]
            if ln == 0 or i + 1 + ln > len(d):
                break
            rec = d[i+1:i+1+ln]
            got.append("".join(rev.get((rec[k] << 8) | rec[k+1], "<?>")
                               for k in range(0, len(rec), 2)).strip())
            i += 1 + ln
        want = [n.strip() for n in translate_names.NAMES]
        if got != want:
            bad = [f"{w!r} reads {g!r}" for w, g in zip(want, got) if w != g]
            problems.append(f"NSZ_B000.BIN: {len(bad)} speaker names garbled "
                            f"(re-run apply_translation.py): " + "; ".join(bad[:3]))
        elif verbose:
            print(f"NSZ_B000: {len(got)} speaker names verified")

    # Pair glyphs: every exec-side stub (subs_cue.py) lives in font slots,
    # and one landed on live pairs once - `ep` and `n?` drew as garbage
    # game-wide, and the headless validator, which renders its expected
    # rows from the patched exec, matched the garbage against itself. Read
    # each pair's 18 bytes back and compare with the renderer.
    epath = os.path.join(OUT, "SLPS_001.54")
    if not os.path.exists(epath):
        problems.append("SLPS_001.54 missing from patched/")
    else:
        exe = open(epath, "rb").read()
        bad = []
        for pair, (slot, code) in pf.table.items():
            off = pairfont.FONT_BASE + slot * 18
            if exe[off:off + 18] != pairfont.render_pair(pair):
                bad.append(f"{pair!r}@{slot}")
        if bad:
            problems.append(f"SLPS_001.54: {len(bad)} pair glyph(s) overwritten in the "
                            f"exec (a stub in a live font slot?): " + ", ".join(bad[:6]))
        elif verbose:
            print(f"SLPS_001.54: {len(pf.table)} pair glyphs verified")

    return problems


if __name__ == "__main__":
    probs = check()
    for p in probs:
        print("FAIL " + p)
    print(f"\n{len(probs)} problems" if probs else "\nbuild is consistent")
    sys.exit(1 if probs else 0)
