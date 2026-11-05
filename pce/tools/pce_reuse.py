"""Seed pce/translation/dialogue.json from the PS1 translation.

The PS1 port carries the same lines: work/ref/ISZ_*.json has the Japanese per
offset and ps1/translation/ISZ_*.json the English. A PCE line whose Japanese
matches a PS1 line (breaks, colour codes and in-text commands ignored) takes
that English, re-broken for the PCE box: 18 fullwidth cells per row, rows
paged by the engine three at a time. Existing entries in dialogue.json win.

  python pce/tools/pce_reuse.py            # writes dialogue.json, prints coverage
  python pce/tools/pce_reuse.py --missing  # also lists the unmatched PCE lines
  python pce/tools/pce_reuse.py --todo     # the unmatched lines as a JSON stub
                                           # for hand translation (work/pce/todo.json)
  python pce/tools/pce_reuse.py --refresh <commit>
        # the PS1 translation moved on: every dialogue.json entry that still
        # equals what the PS1 data at <commit> seeded (nothing hand-edited in
        # place) takes the current PS1 English; the rest are listed for a hand
        # decision (dialogue_hand.json entries are never touched)

A PS1 string's `long` (the full wording behind a budget-shortened `en`) is
what the PCE takes: its box has no such budget.
"""
import collections, glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import pcescript as S
import pcepair

COLOUR = re.compile("＠(.)")
# the PS1's colour codes and the PCE's in-text commands, paired by counting
# the lines that carry both (163 白/cmd1, 133 赤/cmd3, 31 緑/cmd6, 27 黄/cmd2,
# 13 水/cmd5); anything else loses its colour rather than guess
CMD = {"白": 1, "赤": 3, "緑": 6, "黄": 2, "水": 5}
TAG = re.compile(r"<[^>]*>")
# characters the two ports punctuate differently (the PCE writes ？ where the
# PS1 wrote 。, uses a different dash in phone numbers, spaces its ellipses):
# a line that matches once these are removed can reuse the PS1 English.
# Punctuation differences still need editorial review, not a suffix copy. Digits
# stay in the key - the videophone numbers differ between ports.
PUNCT = re.compile("[。、，．？！・…「」『』（）〈〉　 ＿−－~〜゛゜]")
# The PS1 dump mis-decodes a handful of glyphs (work/ref is produced by the
# PS1 textcodec): every ム reads as メ, 死 as 氏, 操 as 早, 準 as 潤, 項 as 香.
# Folding both sides onto one form only ever merges lines that are the same
# line - the mis-read spellings are not words.
CONFUSE = str.maketrans("メ氏早潤香", "ム死操準項")


def norm(jp):
    """The bare Japanese: no breaks, colour codes, commands or padding."""
    s = TAG.sub("", jp).replace("￥", "").replace("　", "").replace("＠Ｃ", "")
    s = COLOUR.sub("", s)
    return re.sub(r"<[0-9a-f]{2}>", "", s).strip()


def ps1_map(commit=None):
    """{bare Japanese: English} from ps1/translation (the working tree, or a commit's)."""
    import subprocess
    out = {}
    for ref in sorted(glob.glob(os.path.join(WORK, "ref", "ISZ_*.json"))):
        name = os.path.basename(ref)
        tr = os.path.join(ROOT, "ps1", "translation", name)
        if commit:
            try:
                data = json.loads(subprocess.check_output(["git", "show", f"{commit}:ps1/translation/{name}"], cwd=ROOT).decode("utf-8"))
            except subprocess.CalledProcessError:
                continue
        elif os.path.exists(tr):
            data = json.load(open(tr, encoding="utf-8"))
        else:
            continue
        jp = {s["off"]: s["jp"] for s in json.load(open(ref, encoding="utf-8"))["strings"]}
        for s in data["strings"]:
            en = s.get("long") or s.get("en", "")
            if en and s["off"] in jp and not s.get("lock"):
                out.setdefault(norm(jp[s["off"]]), en)
    return out


def seed(ps1):
    """{PCE key: wrapped English} for every PCE line the PS1 map covers."""
    loose = {}
    for k, v in ps1.items():
        bare = loose_key(k)
        if len(bare) >= 2:
            loose.setdefault(bare, v)
    out = {}
    for f in glob.glob(os.path.join(S.SCRIPT, "*.json")):
        for st in json.load(open(f, encoding="utf-8"))["strings"]:
            jp = st["jp"]
            n = norm(jp)
            en = ps1.get(n)
            if en:
                out[S.key(jp)] = wrap(en)
                continue
            bare = loose_key(n)
            en = loose.get(bare) if len(bare) >= 2 else None
            if en:
                out[S.key(jp)] = wrap(repunct(en, n))
    return out


def refresh(base):
    """dialogue.json brought up to the current PS1 translation (see the docstring)."""
    cur = json.load(open(S.DIALOGUE, encoding="utf-8"))
    hand = json.load(open(S.HAND, encoding="utf-8")) if os.path.exists(S.HAND) else {}
    old, new = seed(ps1_map(base)), seed(ps1_map())
    taken, kept, listed = 0, 0, []
    for k, v in cur.items():
        if k in hand or k not in new or new[k] == v:
            continue
        if k not in old or old[k] == v:        # the seed as it was: the PS1 moved, follow it
            cur[k] = new[k]
            taken += 1
        else:                                  # edited in place on the PCE side
            kept += 1
            listed.append((k, v, new[k]))
    json.dump(cur, open(S.DIALOGUE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"refresh from {base}: {taken} lines take the PS1's new English, {kept} hand-edited in place kept")
    for k, v, n in listed:
        print(f"  {k}\n    PCE: {v}\n    PS1: {n}")


def loose_key(s):
    return PUNCT.sub("", s).translate(CONFUSE)


def repunct(en, jp):
    """Keep revised English punctuation; source-specific tone is reviewed by hand.

    A Japanese terminal mark can belong to a soft imperative, or follow a
    command/quotation. Copying it onto English produces false questions and
    duplicated punctuation after closing quotes or colour resets.
    """
    return en


def wrap(en, cols=S.WRAP):
    """PS1 English -> PCE rows: colour codes dropped, ￥ = space, greedy wrap."""
    text = en.replace("＠Ｃ", "").replace("￥", " ")
    text = COLOUR.sub(lambda m: f"<cmd{CMD[m.group(1)]}>" if m.group(1) in CMD else "", text)
    # the PS1 wrote coloured initials fullwidth; halfwidth letters pair up
    text = "".join(chr(ord(c) - 0xFEE0) if "！" <= c <= "～" else c for c in text)
    words, rows, cur = text.split(), [], ""
    for w in words:
        if cur and S.width(cur + " " + w) > cols:
            rows.append(cur)
            cur = w
        else:
            cur = (cur + " " + w) if cur else w
    if cur:
        rows.append(cur)
    return "<nl>".join(rows)


def main():
    if "--refresh" in sys.argv:
        refresh(sys.argv[sys.argv.index("--refresh") + 1])
        return
    have = S.load_english()
    ps1 = ps1_map()
    lines = {}
    for f in glob.glob(os.path.join(S.SCRIPT, "*.json")):
        for s in json.load(open(f, encoding="utf-8"))["strings"]:
            lines[s["jp"]] = lines.get(s["jp"], 0) + 1
    loose = {}
    for k, v in ps1.items():
        bare = loose_key(k)
        if len(bare) >= 2:          # punctuation-only lines are not evidence
            loose.setdefault(bare, v)
    out, hit, fuzzy, miss = dict(have), 0, 0, []
    for jp in lines:
        if S.key(jp) in out:
            hit += 1
            continue
        n = norm(jp)
        en = ps1.get(n)
        if en:
            out[S.key(jp)] = wrap(en)
            hit += 1
            continue
        bare = loose_key(n)
        en = loose.get(bare) if len(bare) >= 2 else None
        if en:
            out[S.key(jp)] = wrap(repunct(en, n))
            fuzzy += 1
            continue
        miss.append(jp)
    hand = json.load(open(S.HAND, encoding="utf-8")) if os.path.exists(S.HAND) else {}
    out = {k: v for k, v in out.items() if k not in hand}      # hand file owns its lines
    json.dump(out, open(S.DIALOGUE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(lines)} distinct PCE lines, {hit} exact + {fuzzy} punctuation-only "
          f"({len(ps1)} PS1 lines indexed), {len(miss)} missing")
    if "--missing" in sys.argv:
        for jp in miss:
            print("  " + jp)
    if "--todo" in sys.argv:
        path = os.path.join(WORK, "pce", "todo.json")
        counts = collections.Counter()
        for f in glob.glob(os.path.join(S.SCRIPT, "*.json")):
            m = json.load(open(f, encoding="utf-8"))
            for st in m["strings"]:
                if st["jp"] in set(miss):
                    counts[st["jp"]] += 1
        json.dump([{"key": S.key(jp), "uses": counts[jp], "jp": jp, "en": ""} for jp in
                   sorted(miss, key=lambda j: -counts[j])],
                  open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{len(miss)} lines -> {path}")


if __name__ == "__main__":
    main()
