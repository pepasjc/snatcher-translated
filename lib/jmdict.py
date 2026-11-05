"""JMdict as a word -> glosses lookup for the review tool's hover dictionary.

The EDRDG's JMdict (http://www.edrdg.org/jmdict/j_jmdict.html, CC BY-SA
4.0) is read once from `work/JMdict_e.gz` (fetched from
http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz - 10 MB) into a compact
`work/jmdict.json`: every kanji form and every reading of an entry keys a
list of `[headword, reading, priority, [sense, ...]]` records, a sense being
`"(pos) gloss; gloss; gloss"`. Neither file is committed (work/ is
scratch; the dictionary is the EDRDG's to distribute).

  python lib/jmdict.py build            # JMdict_e.gz -> jmdict.json (~30 s)
  python lib/jmdict.py 見る 気にする      # look words up

`lookup(word)` returns the records for the exact form, common entries
(a `ke_pri`/`re_pri` tag) first, then by entry order.
"""
import gzip, json, os, sys, re
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WORK = os.path.join(ROOT, "work")

SRC = os.path.join(WORK, "JMdict_e.gz")
OUT = os.path.join(WORK, "jmdict.json")
MAX_SENSES = 4
MAX_GLOSSES = 4

_POS_SHORT = {                           # the entity text -> a short tag
    "noun (common) (futsuumeishi)": "n", "adverb (fukushi)": "adv",
    "adjective (keiyoushi)": "adj-i", "adjectival nouns or quasi-adjectives (keiyodoshi)": "adj-na",
    "noun or participle which takes the aux. verb suru": "vs", "suru verb - included": "vs",
    "expressions (phrases, clauses, etc.)": "exp", "interjection (kandoushi)": "int",
    "pronoun": "pn", "conjunction": "conj", "particle": "prt", "auxiliary verb": "aux-v",
    "prefix": "pref", "suffix": "suf", "counter": "ctr", "numeric": "num",
    "adverb taking the 'to' particle": "adv-to", "noun, used as a suffix": "n-suf",
    "noun, used as a prefix": "n-pref", "pre-noun adjectival (rentaishi)": "adj-pn",
    "'taru' adjective": "adj-t", "noun or verb acting prenominally": "adj-f",
    "unclassified": "unc", "copula": "cop",
}


def _pos(text):
    if text in _POS_SHORT:
        return _POS_SHORT[text]
    m = re.match(r"(Ichidan|Godan|Kuru|Suru|Nidan|Yodan) verb", text)
    if m:
        tr = " vt" if "transitive" in text else (" vi" if "intransitive" in text else "")
        return {"Ichidan": "v1", "Godan": "v5", "Kuru": "vk", "Suru": "vs-i", "Nidan": "v2", "Yodan": "v4"}[m.group(1)] + tr
    if text.startswith("transitive"):
        return "vt"
    if text.startswith("intransitive"):
        return "vi"
    return text[:12]


def build():
    """Parse the XML (entities resolved to their text by ElementTree) into OUT."""
    table = {}
    with gzip.open(SRC, "rb") as f:
        n = 0
        for _ev, el in ET.iterparse(f):
            if el.tag != "entry":
                continue
            n += 1
            kforms = [(k.findtext("keb"), k.find("ke_pri") is not None) for k in el.findall("k_ele")]
            rforms = [(r.findtext("reb"), r.find("re_pri") is not None) for r in el.findall("r_ele")]
            senses = []
            for s in el.findall("sense"):
                glosses = [g.text for g in s.findall("gloss") if g.text][:MAX_GLOSSES]
                if not glosses:
                    continue
                pos = sorted({_pos(p.text) for p in s.findall("pos") if p.text})
                misc = [m.text for m in s.findall("misc") if m.text]
                tag = ",".join(pos)
                if any("usually kana" in m for m in misc):
                    tag += (", " if tag else "") + "uk"
                senses.append((f"({tag}) " if tag else "") + "; ".join(glosses))
                if len(senses) >= MAX_SENSES:
                    break
            if not senses:
                el.clear()
                continue
            head = kforms[0][0] if kforms else rforms[0][0]
            read = rforms[0][0] if rforms else ""
            pri = int(any(p for _, p in kforms) or any(p for _, p in rforms))
            rec = [head, read, pri, senses]
            for key in {k for k, _ in kforms} | {r for r, _ in rforms}:
                table.setdefault(key, []).append(rec)
            el.clear()
    for key, recs in table.items():
        recs.sort(key=lambda r: -r[2])
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{n} entries, {len(table)} keys -> {OUT} ({os.path.getsize(OUT) // 1024} KB)")


_table = None


def load():
    global _table
    if _table is None:
        _table = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    return _table


def lookup(word):
    return load().get(word, [])


def available():
    return os.path.exists(OUT)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["build"]:
        build()
    else:
        for w in sys.argv[1:]:
            for head, read, pri, senses in lookup(w)[:3]:
                print(f"{head}【{read}】{'*' if pri else ''}")
                for i, s in enumerate(senses, 1):
                    print(f"  {i}. {s}")
