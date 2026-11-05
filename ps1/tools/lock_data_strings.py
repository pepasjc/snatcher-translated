"""Mark engine data strings in ps1/translation/*.json as untranslatable, and
prescribe the typed-puzzle matcher targets.

Some entries in the string region are not dialogue but data the engine matches
against. The videophone dial table is the clear case: entries begin with the
marker `数` followed by fullwidth digits (`数３９３４４４` = 39-3444), and in
B0C0 with `★`/`☆` wildcards for prefix patterns.

Dialled digits arrive one glyph code per digit. Pair-encoded ASCII packs two
characters per code, so a translated entry can never match what the player
dials — every number silently fails to connect. That shipped: 125 of these
were rewritten as "No.393444" and the videophone stopped taking numbers.

This sets "lock": true on every such entry and clears any English on it.
apply_translation.py refuses to write locked entries, so the original bytes
survive. Re-run after dump_strings.py.

Typed-puzzle targets are different: with the keyboard rewritten to Latin
(patch_keyboard.py) the player types fullwidth Latin, so the matcher targets
are translated — but they must be stored as FULLWIDTH characters (one glyph
code per letter, exactly what the keyboard emits), never as pair-encoded
ASCII. PUZZLE_TARGETS below prescribes the exact text per entry:

  - fits its slot  -> "en" carries the fullwidth text, written in place
  - over budget    -> "long" carries it; repoint.py appends it to the bank
                      and the runtime remap redirects the reference, which
                      covers the matcher too (all string reads funnel through
                      the three hooked sites)

The `以外` suffix on the catch-all records (`ＱＵＥＥＮ以外` = "other than
Queen") is engine matcher config, kept verbatim — the one sanctioned use of
non-colour-code Japanese in committed files, alongside the untouched kana
markers below. verify_build.py fails the build if any entry drifts from this
prescription.
"""
import json, glob, os, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REF = os.path.join(ROOT, "work", "ref")
TR = os.path.join(ROOT, "ps1/translation")

MARKERS = ("数",)          # engine data prefixes found so far
# The marker alone is not enough: 数 also opens ordinary prose (数種の虫,
# 数本の切り口, 数百体 - "several kinds / several cuts / hundreds"), and three
# such lines sat untranslated behind the lock until a play-test caught 数種.
# Data records follow the marker with a fullwidth digit or the ☆ wildcard.
DATA_TAIL = "０１２３４５６７８９☆★"

# Catch-all "miss" records: `ハズレ` heads the wrong-answer branch of the
# Napoleon password matcher. It is a keyword the engine recognises, not text
# the player types or reads, so it keeps its original bytes.
INPUT_TARGETS = {
    "ISZ_B060.json": [123],
    "ISZ_B070.json": [105],
}

# Typed-puzzle matcher targets, prescribed as fullwidth text. The reply lines
# around each entry quote these words, so a change here needs the matching
# dialogue edits too.
PUZZLE_TARGETS = {
    # Napoleon's password. He picks one question per call, each with its own
    # matcher set (play-tested): `Revolt?` expects ＯＶＥＲ (the revolution
    # is over), `Days?` expects ＲＥＩＧＮ (the Hundred Days' reign); Metal's
    # hints at 159/161 quote both. The rest are joke guesses with canned
    # replies ("Just repeating", "A stale slogan", ...).
    "ISZ_B060.json": {
        127: "ＲＥＶＯＬＴ",
        129: "ＮＯＩＤＥＡ",
        130: "ＤＵＮＮＯ",
        131: "ＮＯＣＬＵＥ",
        132: "ＭＥＭＯＲＩＡＬ",
        134: "ＴＯＧＥＴＨＥＲ",
        136: "ＨＯＮＯＵＲ",       # reply: "About England?"
        138: "ＡＭＥＲＩＣＡ",
        140: "ＦＲＡＮＣＥ",
        142: "ＥＮＤＳ",           # reply: "So close..."
        144: "ＯＶＥＲ",           # correct: the revolution is over
        147: "ＷＡＲ",
        149: "ＨＡＣＫ",           # cough — reply: "Mind your health."
        151: "ＷＥＥＤ",           # reply: "A daisy annual?"
        153: "ＳＬＥＥＰＥＲ",     # reply: "That's 'three year'."
        155: "ＲＥＩＮ",           # reply: "Go look it up properly."
        157: "ＲＥＩＧＮ",         # correct: the Hundred Days' reign
    },
    # The same puzzle on the Act 1 revisit bank.
    "ISZ_B070.json": {
        109: "ＲＥＶＯＬＴ",
        111: "ＮＯＩＤＥＡ",
        112: "ＤＵＮＮＯ",
        113: "ＮＯＣＬＵＥ",
        114: "ＭＥＭＯＲＩＡＬ",
        116: "ＴＯＧＥＴＨＥＲ",
        118: "ＨＯＮＯＵＲ",
        120: "ＡＭＥＲＩＣＡ",
        122: "ＦＲＡＮＣＥ",
        124: "ＥＮＤＳ",
        126: "ＯＶＥＲ",
        129: "ＷＡＲ",
        131: "ＨＡＣＫ",
        133: "ＷＥＥＤ",
        135: "ＳＬＥＥＰＥＲ",
        137: "ＲＥＩＮ",
        139: "ＲＥＩＧＮ",
    },
    # The hospital-name puzzle at Gillian's flat. ＱＵＥＥＮ advances the act;
    # ＯＬＥＥＮ is the pet clinic the broken neon sign spells (B1B0); the
    # rest are near-misses whose replies quote them (Orlin, Olean + the
    # Jolene song, Olina/Olino/Oline, the Orin novel, the chess pieces).
    "ISZ_B1A0.json": {
        263: "ＱＵＥＥＮ以外",
        265: "ＱＵＥＥＮ",
        276: "ＣＲＡＮＥ",
        283: "ＯＷＥＮ",
        285: "ＯＲＬＩＮ",
        287: "ＯＬＥＥＮ",
        290: "ＯＬＥＡＮ",
        297: "ＯＬＩＥＮ",
        299: "ＯＬＩＮＡ",
        301: "ＯＬＩＮＯ",
        303: "ＯＬＩＮＥ",
        309: "ＯＲＩＮ",
        315: "ＫＩＮＧ",
        317: "ＢＩＳＨＯＰ",
        319: "ＫＮＩＧＨＴ",
    },
    # The BENSON chart cipher at Outer Heaven. The wrong guesses are typo
    # shapes of BENSON; ＢＮＳＯＮ has its own reply ("That's it! BNSON!"),
    # ＢＵＮＳＥＮ and ＢＥＮＺＥＮＥ are the chemistry jokes, and the S/N
    # swaps (ＢＥＮＳＯＳＯ, ＢＥＮＮＳＯ...) carry the advice at 202/203
    # about watching the S and N keys.
    "ISZ_B1D0.json": {
        135: "ＢＥＮＳＯＮ以外",
        137: "ＢＥＮＳＯＮ",
        138: "ＢＥＮＳＯ",
        139: "ＢＮＳＯＮ",
        140: "ＢＡＮＳＯＮ",
        141: "ＢＩＮＳＯＮ",
        142: "ＢＵＮＳＯＮ",
        144: "ＢＯＮＳＯＮ",
        147: "ＢＵＮＳＥＮ",
        149: "ＢＥＮＺＥＮＥ",
        151: "ＢＥＮＮＮＮ",
        152: "ＢＥＮＳＯＳＯ",
        153: "ＢＥＮＮＳＯ",
        154: "ＢＥＴＳＯＮ",
    },
}


def is_data(jp):
    return jp.startswith(MARKERS) and len(jp) > 1 and jp[1] in DATA_TAIL


def encoded_len(text):
    from textcodec import encode_string
    return len(encode_string(text)) + 1          # terminator


if __name__ == "__main__":
    locked = cleared = prescribed = 0
    for jpath in sorted(glob.glob(os.path.join(TR, "ISZ_*.json"))):
        name = os.path.basename(jpath)
        rpath = os.path.join(REF, name)
        if not os.path.exists(rpath):
            print(f"skip {name}: no work/ref dump")
            continue
        ref = json.load(open(rpath, encoding="utf-8"))
        spec = json.load(open(jpath, encoding="utf-8"))
        touched = False
        targets = set(INPUT_TARGETS.get(name, ()))
        puzzles = PUZZLE_TARGETS.get(name, {})
        for i, (r, e) in enumerate(zip(ref["strings"], spec["strings"])):
            if i in puzzles:
                text = puzzles[i]
                fits = encoded_len(text) <= e["budget"]
                want = {"lock": False,
                        "en": text if fits else "",
                        "long": "" if fits else text}
                for k, v in want.items():
                    if e.get(k, "" if k != "lock" else False) != v:
                        e[k] = v
                        touched = True
                if not want["long"]:
                    e.pop("long", None)
                prescribed += 1
                continue
            if not is_data(r["jp"]) and i not in targets:
                continue
            if not e.get("lock"):
                e["lock"] = True
                locked += 1
                touched = True
            for f in ("en", "long"):
                if e.get(f):
                    print(f"{name[4:8]} off={e['off']:#x}: clearing {f} "
                          f"{e[f]!r} (engine data {r['jp']!r})")
                    e[f] = ""
                    cleared += 1
                    touched = True
            e.pop("long", None)
        if touched:
            json.dump(spec, open(jpath, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
    print(f"\n{locked} entries locked, {cleared} translations cleared, "
          f"{prescribed} puzzle targets prescribed")
