# -*- coding: utf-8 -*-
"""The translation review tool: a local web page over the English data.

    python ps1/review/server.py            # http://127.0.0.1:8765/
    python ps1/review/server.py --port 9000 --no-browser

Left: every scene bank. Right, per bank: the voice lines (the subtitle
cues of ps1/translation/subs_<S>.json - speaker, the Japanese ASR
transcript, the English, a play button that decodes the line off the
pristine image with lib/xadec.py) and the dialogue-box text (the strings
of ps1/translation/ISZ_<S>.json beside work/ref/ISZ_<S>.json's Japanese,
with the byte budget). Edits go back into the same JSON files, one field
at a time: the file is re-read right before each write, so a save never
overwrites what another tool changed meanwhile, and the file keeps its
indent and line endings so the diff is the one line.

Every fit rule the build enforces is shown live: a cue is wrapped with
subs_cue.cellw against the bank's rows x cols (the same call check_cues
makes), a string is encoded with PairFont and measured against its budget
(fit_report's rule), a locked string is read-only (verify_build refuses
English there). Nothing here touches the built image or patched/.
"""
import argparse, glob, json, os, re, sys, threading, urllib.parse, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import xadec
from pairfont import PairFont
import subs_cue as S                       # cellw / wrap; imports with no bank present
import rewrap                              # the data's ￥ re-broken on save
import check_strings                       # the colour codes and the rows of a saved line

try:
    import pykakasi                        # pip install pykakasi: furigana over the kanji
    _kks = pykakasi.kakasi()
except ImportError:
    _kks = None
try:
    import fugashi                         # pip install fugashi unidic-lite: the tokenizer
    _tagger = fugashi.Tagger()             # (lemma + reading per word) behind the hover
except Exception:                          # dictionary; pykakasi alone gives furigana only
    _tagger = None
import jmdict                              # lib/jmdict.py: work/jmdict.json (jmdict.py build)

TR = os.path.join(ROOT, "ps1", "translation")
REF = os.path.join(WORK, "ref")
STATIC = os.path.join(HERE, "static")
SCENE_NAMES = os.path.join(HERE, "scenes.json")

_lock = threading.Lock()
_pf = None


def pf():
    global _pf
    if _pf is None:
        _pf = PairFont()
    return _pf


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    return json.load(open(path, encoding="utf-8"))


def save_json_like(path, doc):
    """Write `doc` back in the file's own style: its indent, its newline,
    its trailing newline (or not). ensure_ascii=False as every writer here."""
    raw = open(path, "rb").read()
    nl = "\r\n" if b"\r\n" in raw else "\n"
    m = re.search(rb"\n( +)\"", raw)
    indent = len(m.group(1)) if m else 2
    text = json.dumps(doc, ensure_ascii=False, indent=indent)
    if raw.endswith(b"\n"):
        text += "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace("\n", nl))
    os.replace(tmp, path)


# --- the data ---------------------------------------------------------------

_census = None
_ts = None


def census():
    global _census
    if _census is None:
        _census = load_json(os.path.join(WORK, "master_lines.json"), [])
    return _census


def transcripts():
    global _ts
    if _ts is None:
        _ts = load_json(os.path.join(WORK, "ts_cache.json"), {})
    return _ts


def stream_of(cue):
    for x in census():
        if x["ch"] == cue["chan"] and x["file"] == cue["file"] and x["start"] <= cue["start"] <= x["end"]:
            return x
    return None


def japanese_of(cue, stream):
    """The ASR segments overlapping the card's span (jp_sidecar's rule)."""
    if not stream:
        return ""
    rate = (stream["end"] - stream["start"]) / stream["dur"] if stream.get("dur") else (150 if stream.get("stereo") else 75)
    segs = transcripts().get(stream["key"], [])
    segs = segs if isinstance(segs, list) else segs.get("segments", [])
    t0 = (cue["start"] - stream["start"]) / rate
    t1 = (cue["end"] - stream["start"]) / rate
    return " ".join(s["text"].strip() for s in segs if s["end"] > t0 + 0.2 and s["start"] < t1 - 0.2)


# --- furigana ---------------------------------------------------------------

_KANJI = re.compile(r"[\u4e00-\u9fff\u3005]")
_SPLIT = re.compile(r"(￥|＠.|<[0-9a-f]{2}>)")


def ruby(text):
    """The Japanese as tokens for the page: `[{"p": [[text, reading|None], ...],
    "g": gloss|None}, ...]`. A token is one word of fugashi's (MeCab, unidic),
    its pieces the okurigana peeled off so the reading sits over the kanji
    alone (食べて -> 食/た + べて plain), its gloss the JMdict entry of the
    lemma (見た -> 見る) - the hover dictionary (Luiz, 2026-09-18). Particles,
    auxiliaries and punctuation carry no gloss. Engine codes pass through.
    Without fugashi, pykakasi's tokens and no glosses."""
    if not text:
        return []
    if not _tagger and not _kks:
        return [{"p": [[text, None]], "g": None}]
    out = []
    for chunk in _SPLIT.split(text):
        if not chunk:
            continue
        if _SPLIT.fullmatch(chunk):
            out.append({"p": [[chunk, None]], "g": None})
            continue
        for orig, hira, gloss in _tokens(chunk):
            out.append({"p": _peel(orig, hira), "g": gloss})
    return out


_NOGLOSS = {"助詞", "助動詞", "補助記号", "空白", "記号"}
_LATIN = re.compile(r"[A-Za-z]")


def _kata2hira(s):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


CAST = {                                  # the game's names: one token each, glossed with
    "ギリアン": "Gillian", "ミカ": "Mika", "メタルギア": "Metal Gear", "メタル": "Metal",   # the English
    "ハリー": "Harry", "ランダム": "Randam", "ハジル": "Hajile", "カトリーヌ": "Catherine",
    "ジェミー": "Jamie", "ナポレオン": "Napoleon", "ガウディ": "Gaudi", "ペトロビッチ": "Petrovich",
    "マッドナー": "Madnar", "ギブソン": "Gibson", "イワン": "Ivan", "リサ": "Lisa", "フレディ": "Freddy",
    "ベンソン": "Benson", "カニンガム": "Cunningham", "チン": "Chin", "イザベラ": "Isabella",
    "エリヤ": "Elijah", "ムーンサルト": "Moonsalt", "リトルジョン": "Little John", "ジャンカー": "JUNKER",
    "スナッチャー": "Snatcher", "ネオコウベ": "Neo Kobe", "ネオ・コウベ": "Neo Kobe", "アルタミラ": "Altamira",
    "アウターヘブン": "Outer Heaven", "ジョイディビジョン": "Joy Division", "クイーン": "Queen (Hospital)",
    "オリーン": "Oleen (Hospital)", "ブラスター": "Blaster", "アルファビル": "Alphaville",
    "ジャンカーアイ": "Junker Eye", "インセクター": "insector", "ランナー": "Runner", "シード": "Seed",
    "ライトインナー": "Little John", "ホモ・サピエンス": "Homo sapiens",
}
_CAST_RE = re.compile("|".join(re.escape(k) for k in sorted(CAST, key=len, reverse=True)))


def _tokens(chunk):
    """[(surface, hiragana reading|None, gloss|None), ...] for one run of text;
    a cast name is one token whatever the tokenizer would make of it."""
    pos = 0
    for m in _CAST_RE.finditer(chunk):
        if m.start() > pos:
            yield from _tokens_plain(chunk[pos:m.start()])
        yield m.group(0), None, m.group(0) + chr(10) + CAST[m.group(0)]
        pos = m.end()
    if pos < len(chunk):
        yield from _tokens_plain(chunk[pos:])


def _tokens_plain(chunk):
    if not _tagger:
        for it in _kks.convert(chunk):
            yield it["orig"], it["hira"], None
        return
    for w in _tagger(chunk):
        f = w.feature
        kana = _kata2hira(f.kana or "") if _KANJI.search(w.surface) else None
        if _KANJI.search(w.surface) and not kana and _kks:      # unidic did not know it
            kana = "".join(it["hira"] for it in _kks.convert(w.surface))
        gloss = None
        if f.pos1 not in _NOGLOSS and w.surface.strip() and not (len(w.surface) == 1 and not _KANJI.match(w.surface)):
            lemma = f.lemma or ""
            if "-" in lemma and _LATIN.search(lemma):            # unidic's 'スナッチャー-snatcher'
                lemma = lemma.split("-", 1)[0]
            gloss = _gloss([lemma, f.orthBase or "", w.surface], _kata2hira(f.kana or ""), f.pos1)
        yield w.surface, kana, gloss


_POS_TAG = {"代名詞": "pn", "名詞": "n", "動詞": "v", "形容詞": "adj-i", "形状詞": "adj-na",
            "副詞": "adv", "感動詞": "int", "接続詞": "conj", "連体詞": "adj-pn", "接頭辞": "pref",
            "接尾辞": "suf"}


def _has_tag(sense, tag):
    """Does a sense's leading "(v1,vt,uk)" group carry the tag? `v` = any verb class."""
    m = re.match(r"\(([^)]*)\)", sense)
    if not m:
        return False
    for item in m.group(1).split(","):
        item = item.strip()
        if item == tag or item.startswith(tag + "-"):
            return True
        if tag == "v" and item.startswith("v") and item not in ("vt", "vi"):
            return True
    return False


def _gloss(candidates, reading, pos1):
    """The JMdict entry of the first candidate form found; among the forms'
    entries the one whose sense tags carry the tokenizer's part of speech
    (わし the pronoun, not 和紙 the paper), then the one whose reading is the
    token's, else the common one."""
    tag = _POS_TAG.get(pos1)
    for cand in candidates:
        if not cand:
            continue
        recs = jmdict.lookup(cand)
        if not recs:
            continue
        pool = [r for r in recs if tag and any(_has_tag(x, tag) for x in r[3])] or recs
        rec = next((r for r in pool if r[1] == reading), pool[0])
        head, read, _pri, senses = rec
        title = head if head == read or not read else f"{head}【{read}】"
        return title + chr(10) + chr(10).join(f"{i}. {x}" for i, x in enumerate(senses[:3], 1))
    return None


def _peel(orig, hira):
    """[[text, reading|None], ...]: the reading over the kanji core only."""
    if not _KANJI.search(orig) or not hira or hira == orig:
        return [[orig, None]]
    i, j = 0, 0
    while i < len(orig) - 1 and i < len(hira) - 1 and orig[i] == hira[i] and not _KANJI.match(orig[i]):
        i += 1
    while j < len(orig) - 1 - i and j < len(hira) - 1 - i and orig[-1 - j] == hira[-1 - j] and not _KANJI.match(orig[-1 - j]):
        j += 1
    head, tail = orig[:i], orig[len(orig) - j:] if j else ""
    core, read = orig[i:len(orig) - j], hira[i:len(hira) - j]
    out = []
    if head:
        out.append([head, None])
    out.append([core, read])
    if tail:
        out.append([tail, None])
    return out


# --- what kind of string ----------------------------------------------------------

_SENTENCE = re.compile(r"[。！？…‥]|・・・|￥")


def string_kind(sid, idx, rec, jp):
    """dialogue / menu / control / debug / lock - the page's 'dialogue only'
    filter hides everything but the first. Heuristic: a line with sentence
    punctuation, a line break or 12+ characters is prose; the rest are verb
    and topic labels, room names and item names (the 1-2 character menu
    items and their `long`s among them)."""
    if rec.get("lock"):
        return "lock"
    if "<" in jp:
        return "control"
    if sid == "B000" and 4 <= idx <= 238:
        return "debug"
    if rec.get("long"):
        return "menu"
    if _SENTENCE.search(jp) or len(jp) >= 12:
        return "dialogue"
    return "menu"


def wrap_rows(text, cols):
    """subs_cue.wrap_only without the SystemExit: every row, however many."""
    out = []
    budget = min(cols, S.CODES_PER_ROW)
    for para in text.split("\n"):
        words, line = para.split(), ""
        for w in words:
            cand = (line + " " + w).strip()
            if S.cellw(cand) <= budget:
                line = cand
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def cue_fit(text, rows, cols):
    rws = wrap_rows(text, cols)
    over = [r for r in rws if S.cellw(r) > cols]
    return {"rows": rws, "cells": [S.cellw(r) for r in rws], "max_rows": rows, "cols": cols,
            "ok": len(rws) <= rows and not over}


def string_size(en):
    try:
        return len(pf().encode(en)) + 1
    except ValueError as e:
        return None


def string_fit(en, budget):
    size = string_size(en) if en else 0
    return {"size": size, "budget": budget, "ok": size is not None and size <= budget}


BANK_CEILING = 0x80118000 - 0x8010D000 - 4     # the scene slot, less subs_cue's BLOBPTR word
_LBA = None


def bank_slack(sid, strings):
    """Bytes the bank's longs take and what is left under the RAM slot: the
    pristine bank plus every `long` (repoint appends each with a zero) and
    the remap group (2 + 4 per entry). Relocation lifts the sector limit,
    the slot ceiling stays."""
    global _LBA
    if _LBA is None:
        _LBA = load_json(os.path.join(WORK, "lba_map.json"), {})
    base = _LBA.get(f"ISZ_{sid}.BIN", [0, 0])[1]
    longs = [x["long"] for x in strings if x.get("long") and not x.get("lock")]
    used = sum((string_size(l) or 0) + 1 for l in longs) + (2 + 4 * len(longs) if longs else 0)
    return {"base": base, "longs": used, "count": len(longs), "free": BANK_CEILING - base - used}


def scene_ids():
    return sorted(os.path.basename(p)[4:8] for p in glob.glob(os.path.join(TR, "ISZ_B*.json")))


def scene_summary(sid):
    names = load_json(SCENE_NAMES, {})
    isz = load_json(os.path.join(TR, f"ISZ_{sid}.json"), {"strings": []})
    subs = load_json(os.path.join(TR, f"subs_{sid}.json"), {"cues": []})
    strings = isz["strings"]
    total = sum(1 for s in strings if not s.get("lock"))
    done = sum(1 for s in strings if s.get("en") and not s.get("lock"))
    return {"id": sid, "name": names.get(sid, ""), "cues": len(subs["cues"]),
            "strings": total, "translated": done,
            "note": subs.get("options", {}).get("_note", "")}


# --- one payload per scene, kept until a file under it changes -------------------
#
# A phone that gives up on a slow page retries, and every retry used to render
# the scene again in its own thread - four requests deep the page took a minute
# and looked like a crash (2026-09-22). The payload is built once per state of
# the scene's files; a save moves an mtime and the next
# request rebuilds it.

_payloads = {}
_payload_lock = threading.Lock()


def _scene_stamp(sid):
    paths = [os.path.join(TR, f"ISZ_{sid}.json"), os.path.join(TR, f"subs_{sid}.json"),
             os.path.join(WORK, "pair_table.json"),
             os.path.join(REF, f"ISZ_{sid}.json")]
    return tuple(os.path.getmtime(x) if os.path.exists(x) else 0 for x in paths)


def cached(kind, sid, make):
    """`make()` for this scene, remembered under its files' mtimes. The build
    runs under the lock: the retries of a phone that timed out wait for the
    first one instead of starting their own."""
    with _payload_lock:
        stamp = _scene_stamp(sid)
        hit = _payloads.get((kind, sid))
        if hit and hit[0] == stamp:
            return hit[1]
        val = make()
        _payloads[(kind, sid)] = (_scene_stamp(sid), val)
        return val


def scene_detail(sid):
    isz = load_json(os.path.join(TR, f"ISZ_{sid}.json"), {"strings": []})
    ref = load_json(os.path.join(REF, f"ISZ_{sid}.json"), {"strings": []})
    subs = load_json(os.path.join(TR, f"subs_{sid}.json"), {"options": {}, "cues": []})
    opts = subs.get("options", {})
    rows = opts.get("rows", 3)
    cols = min(opts.get("cols", S.CODES_PER_ROW), S.CODES_PER_ROW)
    jp_by_off = {s["off"]: s.get("jp", "") for s in ref.get("strings", [])}
    # The Sega CD line paired with each string / cue (ps1/tools/segacd_align.py),
    # shown as reference beside ours; absent when the bank was never aligned.
    al = load_json(os.path.join(WORK, "segacd", f"align_{sid}.json"), {})
    if isinstance(al, list):
        al = {"strings": al, "cues": []}
    sc_by_off = {r["off"]: r for r in al.get("strings", []) if r.get("sc")}
    sc_by_id = {r["id"]: r for r in al.get("cues", []) if r.get("sc")}

    cues = []
    for i, c in enumerate(subs["cues"]):
        st = stream_of(c)
        ccols = min(c.get("cols", cols), S.CODES_PER_ROW)
        cues.append({
            "idx": i, "id": c.get("id", f"#{i}"), "speaker": c.get("speaker", ""),
            "jp": japanese_of(c, st), "en": c.get("en", ""),
            "file": c["file"], "chan": c["chan"], "start": c["start"], "end": c["end"],
            "dur": c.get("dur"), "enabled": c.get("enabled", True), "last": c.get("last", False),
            "by_ear": c.get("by_ear", False),
            "stream": st and {"key": st["key"], "start": st["start"], "end": st["end"], "dur": st.get("dur"),
                              "has_ts": st["key"] in transcripts()},
            "fit": cue_fit(c.get("en", ""), rows, ccols),
            "sc": sc_by_id.get(c.get("id"), {}).get("sc", ""),
            "sc_score": sc_by_id.get(c.get("id"), {}).get("score"),
        })
        cues[-1]["ruby"] = ruby(cues[-1]["jp"])
    strings = []
    for i, s in enumerate(isz["strings"]):
        jp = jp_by_off.get(s["off"], "")
        strings.append({
            "idx": i, "off": s["off"], "budget": s["budget"], "en": s.get("en", ""),
            "jp": jp, "ruby": ruby(jp), "lock": bool(s.get("lock")), "long": s.get("long", ""),
            "kind": string_kind(sid, i, s, jp),
            "fit": string_fit(s.get("en", ""), s["budget"]),
            "sc": sc_by_off.get(s["off"], {}).get("sc", ""),
            "sc_score": sc_by_off.get(s["off"], {}).get("score"),
        })
    return {"id": sid, "options": opts, "rows": rows, "cols": cols, "cues": cues, "strings": strings,
            "slack": bank_slack(sid, isz["strings"]),
            "have_ref": bool(ref.get("strings")), "have_sc": bool(sc_by_off or sc_by_id), "have_ts": bool(transcripts()),
            "furigana": _kks is not None or _tagger is not None, "gloss": _tagger is not None and jmdict.available(),
            "asr": _have_whisper()}


# --- saving ---------------------------------------------------------------------


TERMINAL_SCENES = ("B030", "B040")        # Gaudi's database and the person file: 14-cell rows


def rebreak(sid, kind, field, value, budget=None):
    """The line breaks of a saved text are the tool's job, not the reviewer's
    (Luiz, 2026-09-18). A bank string (en or long) is re-broken by
    `rewrap.rewrap`: its soft `￥` stripped (a break at a sentence end, before
    `▽` or before an indent stays hard), the words re-flowed at 18 cells - 14
    for the `＠緑` terminal strings of B030/B040 - and `￥` put back where the
    rows end, so every row starts on a pair boundary and the runtime wrap
    never indents a row by half a cell. A re-break that no longer fits the
    byte budget is dropped and the text saved as typed (the runtime wraps it
    at a word anyway). A cue's `￥` become spaces: the payload wraps cards
    itself. Control bytes (`<xx>`) are left alone."""
    if not value or "<" in value:
        return value
    if kind == "cue":
        return re.sub(r"\s*￥\s*", " ", value).strip()
    width = 14 if sid in TERMINAL_SCENES and value.startswith("＠緑") else 18
    rewrap.TABLE = pf().table
    new = rewrap.rewrap(value, width)
    if new is None:
        return value
    if budget is not None and field == "en":
        size = string_size(new)
        if size is None or size > budget:
            return value
    return new


def save_field(sid, kind, idx, key, field, value):
    """One field of one record, re-read from disk right before the write."""
    if field not in ("en", "speaker", "long", "enabled"):
        raise ValueError(f"field {field!r} is not editable here")
    with _lock:
        if kind == "cue":
            path = os.path.join(TR, f"subs_{sid}.json")
            doc = load_json(path)
            cues = doc["cues"]
            if idx >= len(cues) or cues[idx].get("id") != key:
                raise ValueError("the cue moved on disk - reload the scene")
            rec = cues[idx]
            if field == "enabled":
                rec["enabled"] = bool(value)
            else:
                if field == "en":
                    value = rebreak(sid, kind, field, value)
                rec[field] = value
            save_json_like(path, doc)
            opts = doc.get("options", {})
            rows = opts.get("rows", 3)
            cols = min(rec.get("cols", opts.get("cols", S.CODES_PER_ROW)), S.CODES_PER_ROW)
            return {"fit": cue_fit(rec.get("en", ""), rows, cols), "text": rec.get(field, value)}
        elif kind == "string":
            path = os.path.join(TR, f"ISZ_{sid}.json")
            doc = load_json(path)
            strings = doc["strings"]
            if idx >= len(strings) or strings[idx]["off"] != key:
                raise ValueError("the string moved on disk - reload the scene")
            rec = strings[idx]
            if rec.get("lock"):
                raise ValueError("locked: the engine reads this string back as data")
            if field == "long":
                if value:
                    value = rebreak(sid, kind, field, value)
                    rec["long"] = value
                else:
                    rec.pop("long", None)
            elif field == "en":
                value = rebreak(sid, kind, field, value, rec["budget"])
                rec["en"] = value
            else:
                raise ValueError(f"field {field!r} is not a string field")
            save_json_like(path, doc)
            return {"fit": string_fit(rec.get("en", ""), rec["budget"]), "text": value}
        raise ValueError(f"kind {kind!r}")


def check_field(sid, kind, idx, value, budget=None, rows=None, cols=None):
    if kind == "cue":
        return {"fit": cue_fit(value, rows or 3, min(cols or S.CODES_PER_ROW, S.CODES_PER_ROW))}
    return {"fit": string_fit(value, budget or 0)}


def text_warnings(sid, kind, rec):
    """What ps1/tools/check_strings.py has to say about the line as saved: a
    colour code of the Japanese gone, a row wider than the box, a control byte
    dropped. The page shows them under the line: an edit easily drops a `＠赤`
    or lengthens a row without noticing."""
    if kind != "string":
        return []
    ref = load_json(os.path.join(REF, f"ISZ_{sid}.json"), {"strings": []})
    jp = next((x.get("jp", "") for x in ref["strings"] if x["off"] == rec["off"]), "")
    return [f"{tag}: {detail}" for level, tag, detail in check_strings.check_string(sid, rec, jp)
            if level == "error"]


# --- transcription (the same call as lib/asr/transcribe_xa.py) ------------------------

TS_PATH = os.path.join(WORK, "ts_cache.json")
FLAT_PATH = os.path.join(WORK, "all_transcripts.json")
PROMPT = os.path.join(ROOT, "lib", "asr", "asr_prompt.txt")
_model = None
_job = {"running": False, "total": 0, "done": 0, "current": "", "log": [], "error": ""}


_asr_ok = None


def _have_whisper():
    """Is faster-whisper installed? Located, never imported: the import
    drags ctranslate2, numpy and torch in (60 s of stat calls on the first
    scene opened - it sat on the page's request path until 2026-09-14).
    The real import happens in `_whisper()`, in the transcription thread."""
    global _asr_ok
    if _asr_ok is None:
        import importlib.util
        _asr_ok = importlib.util.find_spec("faster_whisper") is not None
    return _asr_ok


def _whisper():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _job["current"] = "loading the medium model"
        _model = WhisperModel("medium", device="cpu", compute_type="int8")
    return _model


def transcribe_streams(keys, novad=False):
    """Decode each stream off the image, run whisper with the vocabulary
    prompt, write ts_cache.json and all_transcripts.json (re-read before each
    write, as transcribe_xa.py keeps them resumable)."""
    global _ts
    prompt = open(PROMPT, encoding="utf-8").read().strip() if os.path.exists(PROMPT) else None
    by_key = {x["key"]: x for x in census()}
    _job.update(running=True, total=len(keys), done=0, log=[], error="")
    try:
        model = _whisper()
        for key in keys:
            st = by_key.get(key)
            if not st:
                _job["log"].append(f"{key}: not in the census")
                _job["done"] += 1
                continue
            _job["current"] = key
            wav_path = os.path.join(xadec.CACHE, "stream_" + re.sub(r"[^\w.]+", "_", key) + ".wav")
            if not os.path.exists(wav_path):
                os.makedirs(xadec.CACHE, exist_ok=True)
                with open(wav_path, "wb") as fh:
                    fh.write(xadec.wav(xadec.IMAGE, st["start"], st["end"], st["file"], st["ch"]))
            segs, _ = model.transcribe(wav_path, language="ja", beam_size=5,
                                       initial_prompt=prompt, vad_filter=not novad)
            segs = [{"start": round(g.start, 2), "end": round(g.end, 2), "text": g.text.strip()} for g in segs]
            with _lock:
                ts = load_json(TS_PATH, {})
                flat = load_json(FLAT_PATH, {})
                ts[key] = segs
                flat[key] = "".join(g["text"] for g in segs).strip()
                for path, obj in ((TS_PATH, ts), (FLAT_PATH, flat)):
                    tmp = path + ".tmp"
                    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                    os.replace(tmp, path)
                _ts = ts
            _job["log"].append(f"{key}: {len(segs)} segments" + ("" if segs else " (empty - try again without VAD)"))
            _job["done"] += 1
    except Exception as e:
        _job["error"] = f"{type(e).__name__}: {e}"
    finally:
        _job["running"] = False
        _job["current"] = ""


def start_transcription(sid, ids=None, novad=False, redo=False):
    if _job["running"]:
        raise ValueError("a transcription is already running")
    if not _have_whisper():
        raise ValueError("faster_whisper is not installed (pip install faster-whisper)")
    if not os.path.exists(xadec.IMAGE):
        raise ValueError(f"no pristine image at {xadec.IMAGE}")
    subs = load_json(os.path.join(TR, f"subs_{sid}.json"), {"cues": []})
    keys = []
    for c in subs["cues"]:
        if ids is not None and c.get("id") not in ids:
            continue
        st = stream_of(c)
        if not st or st["key"] in keys:
            continue
        if not redo and transcripts().get(st["key"]):
            continue
        keys.append(st["key"])
    if not keys:
        raise ValueError("nothing to transcribe (every stream here has a transcript)")
    threading.Thread(target=transcribe_streams, args=(keys, novad), daemon=True).start()
    return {"queued": keys}


# --- HTTP ----------------------------------------------------------------------------

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=STATIC, **k)

    def log_message(self, fmt, *args):
        if os.environ.get("REVIEW_LOG"):
            super().log_message(fmt, *args)

    def _page(self, name):
        """An HTML page with every local .css/.js link stamped with the file's mtime
        (`style.css?v=...`): a phone's reload re-fetches only the page itself and ran
        the new page on yesterday's cached stylesheet - the column chips stayed hidden
        (2026-09-23). A changed file is a new URL, so it is always fetched."""
        path = os.path.join(STATIC, name)
        html = open(path, encoding="utf-8").read()

        def stamp(m):
            f = os.path.join(STATIC, m.group(2))
            v = int(os.path.getmtime(f)) if os.path.exists(f) else 0
            return f'{m.group(1)}="{m.group(2)}?v={v}"'
        body = re.sub(r'\b(href|src)="([\w.-]+\.(?:css|js))"', stamp, html).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # the page's own files: revalidated on every load (a 304 when unchanged), or a phone
        # keeps running yesterday's script after an update
        if not self.path.startswith(("/api/", "/audio/")):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        try:
            if not parts:
                return self._page("index.html")
            if len(parts) == 1 and parts[0].endswith(".html") and os.path.exists(os.path.join(STATIC, parts[0])):
                return self._page(parts[0])
            if parts[0] == "api":
                if parts[1] == "scenes":
                    return self._json([scene_summary(s) for s in scene_ids()])
                if parts[1] == "job":
                    return self._json(_job)
                if parts[1] == "scene" and len(parts) == 3:
                    sid = parts[2]
                    if sid not in scene_ids():
                        return self._json({"error": f"no scene {sid}"}, 404)
                    return self._json(cached("scene", sid, lambda: scene_detail(sid)))
                return self._json({"error": "unknown api"}, 404)
            if parts[0] == "audio" and len(parts) == 2:
                m = re.fullmatch(r"f(\d+)_c(\d+)_(\d+)_(\d+)\.wav", parts[1])
                if not m:
                    return self._json({"error": "bad audio name"}, 400)
                file, chan, a, b = (int(x) for x in m.groups())
                if b < a or b - a > 40000:
                    return self._json({"error": "span"}, 400)
                if not os.path.exists(xadec.IMAGE):
                    return self._json({"error": f"no pristine image at {xadec.IMAGE}"}, 404)
                path = xadec.cached_wav(file, chan, a, b)
                data = open(path, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(data)
                return
            return super().do_GET()
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length", "0"))
        try:
            req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if u.path == "/api/save":
                out = save_field(req["scene"], req["kind"], int(req["idx"]), req["key"],
                                 req["field"], req["value"])
                live = load_json(os.path.join(TR, f"ISZ_{req['scene']}.json"), {"strings": []})
                live = live["strings"][int(req["idx"])] if req["kind"] == "string" else None
                return self._json({"ok": True, "warn": text_warnings(req["scene"], req["kind"], live) if live else [], **out})
            if u.path == "/api/check":
                out = check_field(req["scene"], req["kind"], int(req.get("idx", 0)), req["value"],
                                  req.get("budget"), req.get("rows"), req.get("cols"))
                return self._json({"ok": True, **out})
            if u.path == "/api/transcribe":
                out = start_transcription(req["scene"], req.get("ids"), bool(req.get("novad")), bool(req.get("redo")))
                return self._json({"ok": True, **out})
            if u.path == "/api/scene_name":
                names = load_json(SCENE_NAMES, {})
                names[req["scene"]] = req["name"]
                json.dump(names, open(SCENE_NAMES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                return self._json({"ok": True})
            return self._json({"error": "unknown api"}, 404)
        except Exception as e:
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 400)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{a.host}:{a.port}/"
    print(f"review tool at {url}  (Ctrl-C stops it)")
    if a.host == "0.0.0.0":
        import socket
        try:
            ips = sorted({i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)})
        except OSError:
            ips = []
        for ip in ips:
            print(f"  on the LAN: http://{ip}:{a.port}/")
        print("  (Windows Firewall must allow the port once)")
    if not os.path.exists(xadec.IMAGE):
        print(f"  no pristine image at {xadec.IMAGE}: audio buttons will fail")
    if not os.path.exists(REF):
        print(f"  no {REF}: run ps1/tools/dump_strings.py for the Japanese beside the text")
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
