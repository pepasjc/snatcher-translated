"""Census of the holes in the PCE's English: every place a character is drawn
alone in a cell (half of it blank) inside a word or before punctuation, and
every character the pair font cannot draw at all (a fullwidth BIOS cell).

A cell holds two letters (pcepair). A cell ends up half blank when
  single   - its character has no pair code (pcepair.EXTRA: drawn left, blank right)
             and something visible follows it;
  pad      - a pair character is paired with a space the text does not have,
             because the next character cannot pair (an EXTRA one, a fullwidth
             one) or the ASCII stretch ends at a tag while the row goes on
             (a colour change);
  full     - the character is in neither alphabet: a fullwidth BIOS glyph, 12 px.
A space, a row end (<nl>, <wait>, <end>) or the string's end after a half cell
is not a hole. The sources are the texts as the build encodes them: dialogue
(pcescript.layout of every English line), menu labels, speaker names, and the
subtitle chunks (pcesubs.chunks, one word a chunk).

  python pce/tools/pcegaps.py            # counts by cause and character, worst strings
  python pce/tools/pcegaps.py -v         # every hole
"""
import json, os, re, sys
from collections import Counter
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import pcepair
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROW_END = {"<nl>", "<wait>", "<end>", "<page>"}
TAG = re.compile(r"(<[^>]*>|[^\x00-\x7f])")      # tags and non-ASCII end an ASCII stretch


def holes(text):
    """[(cause, char, context)] for one encoded text (tags as pcetext takes them)."""
    parts = [p for p in TAG.split(text) if p]
    out = []
    for k, part in enumerate(parts):
        if part.startswith("<") or ord(part[0]) >= 0x80:
            continue
        # what follows this ASCII stretch on the same row: visible text after
        # colour/dictionary tags, or nothing (a row end, the string's end)
        after = ""
        for q in parts[k + 1:]:
            if q.startswith("<"):
                if q in ROW_END:
                    break
                continue
            after = q          # ASCII text, or a non-ASCII glyph (visible too)
            break
        i = 0
        for t in pcepair.split(part):
            if isinstance(t, tuple):
                a, b = t
                if b == " " and (i + 1 >= len(part) or part[i + 1] != " "):
                    nxt = part[i + 1] if i + 1 < len(part) else (after[:1] if after else "")
                    if nxt and nxt != " ":
                        cause = "pad-before-tag" if i + 1 >= len(part) else "pad"
                        out.append((cause, f"{a}|{nxt}", part[max(0, i - 8):i + 9]))
                    i += 1
                else:
                    i += 2
            else:
                nxt = part[i + 1] if i + 1 < len(part) else (after[:1] if after else "")
                if t in pcepair.EXTRA:
                    if nxt and nxt != " ":
                        out.append(("single", t, part[max(0, i - 8):i + 9]))
                else:
                    out.append(("full", t, part[max(0, i - 8):i + 9]))
                i += 1
    return out


def sources():
    """(where, text) as the build encodes them."""
    import pcescript as S
    english = S.load_english()
    for k, en in english.items():
        try:
            yield "dialogue", S.layout(en)
        except Exception:
            yield "dialogue", en
    if os.path.exists(S.WORDS):
        for k, en in json.load(open(S.WORDS, encoding="utf-8")).items():
            yield "label", en
    if os.path.exists(S.NAMES):
        for k, en in json.load(open(S.NAMES, encoding="utf-8")).items():
            if isinstance(en, str):
                yield "name", en
    import pcesubs
    tdir = os.path.join(ROOT, "pce", "translation")
    for fn in sorted(os.listdir(tdir)):
        if re.match(r"(subs|cdda)_.*\.json$", fn):
            data = json.load(open(os.path.join(tdir, fn), encoding="utf-8"))
            cues = data.get("cues", data) if isinstance(data, dict) else data
            for c in cues:
                if isinstance(c, dict) and c.get("en") and c.get("enabled", True):
                    for w, _ in pcesubs.chunks(c["en"]):
                        yield f"subs:{fn}", w


def census(verbose=False):
    by_cause, by_char, where = Counter(), Counter(), Counter()
    worst = []
    seen = set()
    for src, text in sources():
        key = (src.split(":")[0], text)
        if key in seen:
            continue
        seen.add(key)
        h = holes(text)
        for cause, ch, ctx in h:
            by_cause[cause] += 1
            by_char[(cause, ch)] += 1
            where[src.split(":")[0]] += 1
            if verbose:
                print(f"{src:12} {cause:15} {ch!r:8} ...{ctx}...")
        if h:
            worst.append((len(h), src, text[:70]))
    return by_cause, by_char, where, worst


def main():
    by_cause, by_char, where, worst = census("-v" in sys.argv)
    print("holes by cause:", dict(by_cause), "total", sum(by_cause.values()))
    print("by source:", dict(where))
    print("by character:", ", ".join(f"{c}:{ch}={n}" for (c, ch), n in by_char.most_common(60)))
    print(f"{len(worst)} distinct texts with a hole")
    return sum(by_cause.values())


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
