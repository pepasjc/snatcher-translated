"""Dump and re-insert Snatcher CD-ROMantic's dialogue (pcetext codec).

A scene module on the disc is [bytecode][menu word list][text]. The bytecode
shows a message with `12 0N 00 lo hi` (N = 2..5, the box mode) where lo|hi<<8
is the string's offset from the module start; there is no pointer table, and
every string decodes sequentially from the lowest referenced offset to the
end of the file. So a module is rebuilt by re-encoding the strings in order
and rewriting each reference word - the text block is the file's tail and may
grow up to the record's sector count.

  python pce/tools/pcescript.py dump              # every module -> work/pce/script/<rec>.json (JP, uncommitted)
  python pce/tools/pcescript.py apply [rec ...]   # pce/translation/dialogue.json -> patched/pce image
  python pce/tools/pcescript.py lint              # rows over 18 cells, missing lines

pce/translation/dialogue.json maps `key(jp)` (12 hex of the line's sha1 -
no Japanese is committed) -> English (tags <nl>, <wait>, <end>, <cmdN>
kept); one entry serves every module carrying the line.
dialogue_hand.json is the same map for lines the PS1 has no counterpart for
(the PCE's save system, the shooting range, the staff quiz...); it is
written by hand and wins over the seeded file.

A rebuilt module's tail (every module is padded to 16 sectors): the text,
the speaker names (NAMES_PTR 0x7FFE), the dictionary when the text needs
one (DICT_PTR 0x7FFC), ALL_EN 0x7FFB, the name search's table in module
254 (SEARCH_PTR 0x7FF9), the voiced lines' subtitle table when
pce/translation/subs_<rec>.json exists (SUBS_PTR 0x7FF7 behind the
module's checksum at 0x7FF5; the stub itself lives in the resident file,
pcesubs), and the halfwidth font at pcepair.FONT_OFF (0x7B5C).
"""
import hashlib, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import pcetext as T
import patch_pce as P

T2 = 4174                                  # track 2's first sector
TABLE = os.path.join(WORK, "pce", "filetable.json")
SCRIPT = os.path.join(WORK, "pce", "script")
DIALOGUE = os.path.join(ROOT, "pce", "translation", "dialogue.json")
HAND = os.path.join(ROOT, "pce", "translation", "dialogue_hand.json")
WORDS = os.path.join(ROOT, "pce", "translation", "words.json")
NAMES = os.path.join(ROOT, "pce", "translation", "names.json")
NAME_LIST = 0x6D47            # stage 2: the 73 speaker names, {attr, SJIS.., FF} with FF between
# the say opcode: 12 <mode> 00 lo hi. Modes 2-5 are the dialogue box proper
# and locate the text block (strings_of); every mode (1, 6, 7 = Metal's
# lines, 8, 10, the terminals' 30-74...) references a string and is
# remapped when the block moves. Until the Gaudi terminal hung, only 2-5
# were: a mode-7 line pointed at a stale offset in every English build.
REF = re.compile(rb"\x12[\x02-\x05]\x00(..)", re.S)
REF_ANY = re.compile(rb"\x12.\x00(..)", re.S)
COLS = 18
WRAP = COLS - 1               # wrap here: see layout()
MAX_SECTORS = 16        # a module lives in RAM banks $7E-$81; sector 17 lands
                        # on the act's voice table at $82 (resident, seen live)


def key(jp):
    return hashlib.sha1(jp.encode("utf-8")).hexdigest()[:12]


def modules():
    """The scene modules: group 1 of the file table."""
    return {f["rec"] for f in json.load(open(TABLE))["1"]}


def records():
    """Every distinct (rec, sectors) in the file table."""
    seen = {}
    for group in json.load(open(TABLE)).values():
        for f in group:
            seen[f["rec"]] = max(seen.get(f["rec"], 0), f["n"])
    return sorted(seen.items())


def read_file(img, rec, n):
    off = (T2 + rec) * P.DATA
    return bytes(img.data[off:off + n * P.DATA])


def strings_of(mod):
    """[(offset, text)] for the module's text block, or [] if it has none."""
    refs = [m.start(1) for m in REF.finditer(mod)]
    offs = [int.from_bytes(mod[r:r + 2], "little") for r in refs]
    offs = [o for o in offs if 0 < o < len(mod)]
    if not offs:
        return [], []
    start = min(offs)
    # a string referenced only through another mode may sit just before the
    # box-mode block (Gaudi's mode-1 introduction in 222): an earlier offset
    # counts when decoding from it lands exactly on the block's start
    for o in sorted({int.from_bytes(m.group(1), "little") for m in REF_ANY.finditer(mod[:start])}):
        if 0 < o < start:
            pos, clean = o, True
            while pos < start:
                text, nxt = T.decode(mod, pos)
                if not text or nxt <= pos:
                    break
                if re.search(r"<[0-9a-f]{2,4}>", text):     # bytes the codec cannot read: code, not text
                    clean = False                  # (462 and 542 have a pointer to 0x1c00 that
                    break                          # "decodes" through 3 KB of bytecode)
                pos = nxt
            if pos == start and clean:
                start = o
                break
    out, pos = [], start
    while pos < len(mod) - 1:
        text, nxt = T.decode(mod, pos)
        if not text:
            break
        out.append((pos, text))
        pos = nxt
    known = {o for o, _ in out}
    bad = [o for o in offs if o not in known]
    return out, bad


def dump(img):
    os.makedirs(SCRIPT, exist_ok=True)
    total = 0
    for rec, n in records():
        mod = read_file(img, rec, n)
        strings, bad = strings_of(mod)
        if len(strings) < 8 or bad:
            continue            # the pattern also occurs in picture data
        total += len(strings)
        json.dump({"rec": rec, "sectors": n, "text_start": strings[0][0],
                   "strings": [{"off": o, "jp": t} for o, t in strings]},
                  open(os.path.join(SCRIPT, f"{rec}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        flag = f"  {len(bad)} refs off a string boundary" if bad else ""
        print(f"rec {rec:5} x{n:3}: {len(strings):4} strings from {strings[0][0]:#06x}{flag}")
    print(f"{total} strings")


def width(text):
    """Cells of a tagged string, tags themselves costing nothing."""
    import pcepair
    return sum(pcepair.cells(p) for p in re.split(r"(<[^>]*>)", text)
               if p and not p.startswith("<"))


def cells(text):
    """Cells per row of a tagged string (rows split at <nl>); measured with a scratch pair
    table, so a candidate row never takes a slot in the module's."""
    import pcepair
    rows = [0]
    with pcepair.using(pcepair.PairTable()):
        toks = list(T.tokens(text))
    for hi, lo in toks:
        if hi == 0x82 and lo >= 0xF2:
            if lo < 0xF8:          # row break, page wait and message end
                rows.append(0)
            continue
        if hi == 0x84:                  # the English marker, no cell
            continue
        rows[-1] += 1
    return rows


TERMINAL = "<cmd6>"           # Gaudi's terminal: green text in a 14-cell box
TERMINAL_COLS = 14


def layout(text):
    """Text as the encoder should see it.

    Dialogue: rows are wrapped at WRAP (one cell short of the box). A row
    of exactly COLS cells wraps by itself and the explicit <nl> after it
    leaves an empty row; dropping that <nl> instead ran the words together
    ("It'sJapan"). So a page holding such a row (not its last) is
    re-wrapped by words at WRAP (`fit_rows`). Gaudi's terminal (a string
    opening with <cmd6>) is 14 cells wide and cuts a longer row mid-word,
    so its rows are re-broken here at 14 (the PS1 does the same for its
    ＠緑 strings)."""
    if text.startswith(TERMINAL):
        return align_colours(terminal_wrap(text))
    return align_colours(fit_rows(text))


def fit_rows(text):
    """Every page with a non-last row of exactly COLS cells re-wrapped by
    words at WRAP, an old <nl> counting as a space. Kept as it was when the
    new wrap needs more rows than the page drew (its empty row counted)."""
    out = []
    for page in re.split(r"(<wait>|<end>)", text):
        rows = page.split("<nl>")
        full = [r for r in rows[:-1] if cells(r)[0] == COLS]
        if not full:
            out.append(page)
            continue
        words = [w for w in page.replace("<nl>", " ").split(" ") if w]
        new, row = [], ""
        for w in words:
            cand = w if not row else row + " " + w
            if row and cells(cand)[0] > WRAP:
                new.append(row)
                row = w
            else:
                row = cand
        if row:
            new.append(row)
        out.append("<nl>".join(new) if len(new) <= len(rows) + len(full) else page)
    return "".join(out)


COLOUR = re.compile(r"<cmd\d>")
STRETCH = re.compile(r"(<[^>]*>|[^\x00-\x7f])")


def align_colours(text):
    """Keep the letter pairs whole across a colour change. A colour code sits between two
    cells, so a run of an odd number of characters before one ends in a half-blank cell -
    a hole before the coloured word ("the  JUNKER") or after it ("OLEEN' ,"). When the run
    before a colour code is odd, one character crosses the code: its trailing space moves
    after it, or the next run's leading space moves before it, or else the next run's first
    character joins the run before (a comma after a red name is drawn red). No row gets
    wider (pcepair)."""
    parts = [p for p in STRETCH.split(text) if p]
    ascii_run = lambda p: bool(p) and not p.startswith("<") and ord(p[0]) < 0x80
    for i, a in enumerate(parts):
        if not ascii_run(a) or len(a) % 2 == 0:
            continue
        j = i + 1
        while j < len(parts) and COLOUR.fullmatch(parts[j]):
            j += 1
        if j == i + 1 or j >= len(parts) or not ascii_run(parts[j]):
            continue
        b = parts[j]
        if a.endswith(" "):
            parts[i], parts[j] = a[:-1], " " + b
        elif b.startswith(" "):
            parts[i], parts[j] = a + " ", b[1:]
        else:
            parts[i], parts[j] = a + b[0], b[1:]
    return "".join(p for p in parts if p)


def terminal_wrap(text):
    """The string's rows re-broken by words one cell short of TERMINAL_COLS
    (a row of exactly 14 cells wraps by itself and the <nl> after it drew an
    empty row, as in the dialogue box): every page (between <wait>/<end>)
    wraps by words, an old <nl> counting as a space except before a ▽
    bullet, which starts a row of its own."""
    out = []
    for page in re.split(r"(<wait>|<end>)", text):
        if page in ("<wait>", "<end>", ""):
            out.append(page)
            continue
        words = [w for w in page.replace("<nl>", " ").split(" ") if w]
        rows, row = [], ""
        for w in words:
            cand = w if not row else row + " " + w
            if row and (w.startswith("▽") or cells(cand)[0] > TERMINAL_COLS - 1):
                rows.append(row)
                row = w
            else:
                row = cand
        if row:
            rows.append(row)
        out.append("<nl>".join(rows))
    return "".join(out)


def english_bytes(en, frags=None, marker=True):
    import pcedict
    text = layout(en)
    if frags:
        return pcedict.line_bytes(text, frags, marker)
    return T.encode(text, english=marker)


def rebuild(mod, strings, english, limit=None, frags=None, marker=True, start=None, evict=(), longs=None,
            longs_base=None, longs_room=None, longs_holes=None):
    """New module bytes with the text block re-encoded and refs rewritten.

    `start` is where the text block goes (it moves when the word list before
    it grows); the strings keep their ORIGINAL offsets, which are the keys
    the references are remapped from. The strings whose offset is in `evict`
    go into `longs` (a bytearray) instead of the block, referenced from
    `longs_base` (pcelongs.base(rec): the blob's place, read beside the module)."""
    import pcelongs
    start = strings[0][0] if start is None else start
    limit = len(mod) if limit is None else limit
    body, remap, pos = bytearray(), {}, start
    for off, jp in strings:
        en = english.get(key(jp))
        enc = english_bytes(en, frags, marker) if en is not None else T.encode(jp)
        if off in evict:
            for a, b, keep in longs_holes or ():
                if len(longs) < b and len(longs) + len(enc) > a:     # it would run into a hole:
                    longs += bytes(max(0, a - len(longs)))          # (pad to it,) the hole's own
                    longs[a:b] = keep                               # bytes, the string after it
            remap[off] = longs_base + len(longs)
            longs += enc
            continue
        remap[off] = pos
        body += enc
        pos += len(enc)
    if len(body) > limit - start:
        e = OverflowError(f"text block {len(body)}B exceeds the {limit - start}B slot")
        e.over = len(body) - (limit - start)
        raise e
    if longs is not None and longs_room is not None and len(longs) > longs_room:
        raise OverflowError(f"longs blob {len(longs)}B exceeds its {longs_room}B place")
    head = bytearray(mod[:start])
    for m in text_refs(bytes(head), strings):
        o = int.from_bytes(m.group(1), "little")
        if o in remap:
            head[m.start(1):m.start(1) + 2] = remap[o].to_bytes(2, "little")
    return bytes(head + body + bytes(len(mod) - start - len(body)))


def text_refs(code, strings):
    """Direct dialogue references and the blank messages used by graphic pages."""
    yield from REF_ANY.finditer(code)
    # Opcode 62 presents a blank message while Gibson's diary picture is up.
    # Its thirteen pointers must follow the text block when it moves too.
    blanks = {off for off, text in strings if not text.strip()}
    for match in re.finditer(rb"\x62(..)", code, re.S):
        if int.from_bytes(match.group(1), "little") in blanks:
            yield match
    # `1c 62 lo hi` shows any string that way, not only a blank one: Ivan's "Who is it?"
    # through the door (446), Freddy's (462), the quiz's 80 questions and answers (206),
    # 382, 398, 414 - left at the Japanese offset, the game decoded whatever text had moved
    # there (the garbled blue rows at room 301's door)
    offs = {off for off, _ in strings}
    for match in re.finditer(rb"\x1c\x62(..)", code, re.S):
        o = int.from_bytes(match.group(1), "little")
        if o in offs and o not in blanks:
            yield match


def load_english():
    """The seeded map with the hand-written one layered on top."""
    out = {}
    for path in (DIALOGUE, HAND):
        if os.path.exists(path):
            out.update(json.load(open(path, encoding="utf-8")))
    return out


def word_list(mod, text_start):
    """(start, end, [records]) of the 0xFF-delimited word list that ends just
    before the text block - the verb menus, the Ask topics, the quiz answers.
    No bytecode reference points into it (items are found by scanning), so
    the records may change length as long as their number stays the same."""
    end = mod.rfind(bytes([0xFF]), 0, text_start) + 1
    start = end - 1
    while start > 0:
        prev = mod.rfind(bytes([0xFF]), 0, start)
        if prev < 0:
            break
        rec = mod[prev + 1:start]
        try:
            text = rec.decode("cp932")
        except UnicodeDecodeError:
            break
        if not rec or len(rec) > 40 or any(ord(c) < 0x20 for c in text):
            break
        start = prev
    if end - start < 8:
        return None, None, []
    # the list's first record has no 0xFF before it (あたり, "Around", the Look target every
    # scene has, sat untranslated in every build until 2026-09-13): text bytes right before
    # the first 0xFF that the bytecode references are that record
    i = start - 1
    while i > 0 and mod[i] >= 0x20 and mod[i] != 0xFF and start - i <= 40:
        i -= 1
    if mod[start] == 0xFF:
        refs = {int.from_bytes(m.group(1), "little") for m in LABEL_REF.finditer(mod[:start])}
        for j in range(i + 1, start - 1):                  # the referenced start that decodes
            if j not in refs:
                continue
            try:
                text = mod[j:start].decode("cp932")
            except UnicodeDecodeError:
                continue
            if not any(ord(c) < 0x20 for c in text):
                start = j
                break
    first = mod[start:end - 1] if mod[start] != 0xFF else mod[start + 1:end - 1]
    return start, end, [r.decode("cp932") for r in first.split(bytes([0xFF]))]


def speaker_names(img):
    """[(attr, jp)] from the pristine stage-2 list (an empty jp = a free slot)."""
    base = (T2 + P.STAGE2) * P.DATA - 0x2000 + NAME_LIST
    out, p = [], base
    while len(out) < 73:
        assert img.data[p] == 0xFF, hex(p)
        q = img.data.index(0xFF, p + 1)
        ent = bytes(img.data[p + 1:q])
        out.append((ent[0], ent[1:].decode("cp932")) if ent else (0x32, ""))
        p = q
    return out


# lists that hold data beside their labels: the Gaudi name search with its
# kana keyboard (254), the videophone dial tables (174, 190), the ★ wildcard
# matchers (382), the quiz answers (206) and Konami's debug scene picker
# (158, 270, 286, 302). Every record in them is named by an `f1` reference
# like any label (checked), so they are rebuilt like the others; pce_words
# just gives no English to what the engine matches against.
DATA_LISTS = {254, 158, 270, 286, 302, 174, 190, 382, 206}


def label_bytes(en):
    """A menu label as pair codes (two letters a cell)."""
    import pcepair
    out = bytearray()
    for c in pcepair.split(en):
        if isinstance(c, tuple):
            out += bytes(pcepair.pair_code(*c))
        elif ord(c) < 0x80:
            out += chr(T.FULLWIDTH[ord(c)]).encode("cp932")
        else:
            out += c.encode("cp932")
    return bytes(out)


def word_block(recs, words, exact=False, rec=None, lead_ff=True):
    """The rebuilt word list: every record English where words.json has it.

    The bytecode names an item by its module offset (`f1 lo hi`, see
    LABEL_REF), so a record may change length as long as every reference is
    remapped - apply() does that from the offsets returned here. In `exact`
    mode (the data lists) each record keeps its byte length instead: two
    letters share a cell, so the English gets as many letters as the
    Japanese had bytes, and what is left over is padded with a cell of two
    spaces.

    A record the engine matches against player input keeps its bytes unless
    words.json spells it (the typed answers in fullwidth Latin, 以外 kept).
    Returns (bytes, done, over, offsets) with the offset of every record's
    text inside the block."""
    out, done, over, offs = bytearray(), 0, [], []
    for k, r in enumerate(recs):
        jp = r.encode("cp932")
        en = words.get(f"{rec}:{r}", words.get(r))    # "254:ミカ" is the typed key, "ミカ" the label
        enc = None
        if en:                                    # pce_words gives none to a matcher
            enc = label_bytes(en)
            if exact and len(enc) > len(jp):
                over.append((len(enc) - len(jp), r, en))
                enc = None
        if enc is None:
            enc = jp
        else:
            if exact:
                enc += label_bytes("  ") * ((len(jp) - len(enc)) // 2)
            done += 1
        if k or lead_ff:
            out += bytes([0xFF])
        offs.append(len(out))
        out += enc
    out += bytes([0xFF])
    return bytes(out), done, over, offs


LABEL_REF = re.compile(rb"(?=\xf1(..))", re.S)     # a lookahead: `20 f1 17 f1 31 2b` (a jump to $17f1, then
                                                   # a ref) must not eat the ref's f1 - 478's computer-room
                                                   # Look list drew 've 2' (the tail of Save 2) for Computer
SEARCH_MODULE = 254           # Gaudi's name search
SEARCH_PTR = 0x7FF9           # module-relative: u16 offset of the search table (pcesearch)


SEARCH_ROWS = {"ア", "イウエオ", "カキクケコ", "ガギグゲゴ", "サシスセソ", "ザジズゼゾ", "タチツテト", "ダヂヅデド",
               "ナニヌネノ", "ハヒフヘホ", "バビブベボ", "パピプペポ", "マミムメモ", "ヤユヨワン", "ラリルレロ"}   # the fifteen kana row records


def search_table(mod, wstart, wrecs, remap):
    """The name search's index for pcesearch: `{row u16, name u16}` pairs in
    module offsets (rebuilt), 0xFFFF after the last. The script files the
    names under fifteen kana row records - in the bytecode each row's `f1`
    reference is followed by 該当者なし's and then its names' - and the
    engine picks the row by the typed name's first kana; with Latin names
    the stub compares the typed name with the row's names instead."""
    offs = record_offsets(mod, wstart, wrecs)
    by_off = dict(zip(offs, wrecs))
    rows = {jp for jp in wrecs if jp in SEARCH_ROWS}      # (any 5-kana NAME - メタルギア, ナポレオン - looked like a row
                                                          # until 2026-09-15 and swallowed the names after it: NAPOLEON was
                                                          # never found, #42)
    out, row = bytearray(), None
    for m in LABEL_REF.finditer(mod[:wstart]):
        o = int.from_bytes(m.group(1), "little")
        jp = by_off.get(o)
        if jp in rows:
            row = o
        elif row is not None and jp is not None and jp != "ガイトウシャナシ":
            out += remap.get(row, row).to_bytes(2, "little") + remap.get(o, o).to_bytes(2, "little")
    return bytes(out) + bytes([0xFF, 0xFF])


def record_offsets(mod, wstart, wrecs):
    """The module offset of every record's text in the pristine list."""
    offs, p = [], wstart + (1 if mod[wstart] == 0xFF else 0)      # (a first record without its 0xFF)
    for r in wrecs:
        offs.append(p)
        p += len(r.encode("cp932")) + 1
    return offs


def remap_labels(code, remap):
    """Every `f1 lo hi` in `code` whose offset the list rebuild moved."""
    code = bytearray(code)
    n = 0
    for m in LABEL_REF.finditer(bytes(code)):
        o = int.from_bytes(m.group(1), "little")
        if o in remap:
            code[m.start(1):m.start(1) + 2] = remap[o].to_bytes(2, "little")
            n += 1
    return bytes(code), n


def name_block(names, english, at):
    """The module's name table: entries then the 74-entry offset table.
    Index 0 is "no name" (the engine's $3604 is 1-based), so slot k holds
    name k-1. Returns (bytes, table offset)."""
    entries, offs = bytearray(), [at]
    entries += bytes([0xFF])
    for i, (attr, jp) in enumerate(names[:73]):
        en = english.get(str(i))
        text = en if en is not None else jp
        offs.append(at + len(entries))
        if text:
            # pair-coded like the menus: a fullwidth name beside halfwidth
            # dialogue is the wrong typeface and twice the width
            entries += bytes([attr]) + (label_bytes(text) if en else T.encode_raw(text)) + bytes([0xFF])
        else:
            entries += bytes([0xFF])
    table = b"".join(o.to_bytes(2, "little") for o in offs)
    return bytes(entries) + table, at + len(entries)


def apply(img, only=None):
    """Every module: English text, the halfwidth font at FONT_OFF, padded to
    MAX_SECTORS and relocated when it grew; then the engine stubs."""
    import pcepair, pceengine, pcedict, pcesubs, pcelongs
    english = load_english()
    menu = json.load(open(WORDS, encoding="utf-8")) if os.path.exists(WORDS) else {}
    names = speaker_names(img)
    en_names = json.load(open(NAMES, encoding="utf-8")) if os.path.exists(NAMES) else {}
    font = pcepair.modfont()
    done, placed = 0, {}        # original rec -> [rec, sectors] as built (for pceverify)
    for rec, n in records():
        if only and rec not in only:
            continue
        if n > MAX_SECTORS:
            continue            # a scene block, not a module
        # every pair code this module's text, labels, names, dictionary, longs and
        # subtitles use gets a slot in ITS table (pcepair), written behind its data
        pcepair.use(pcepair.table_for(rec))
        mod = read_file(img, rec, n)
        strings, bad = strings_of(mod)
        if not strings and not bad and rec in modules():
            # a module with no text of its own (670, the ending: voice, then
            # the credit roll) still gets the font and the English flag, so
            # the pair codes rec 130's roll is written in compose whatever
            # sat in the window before it
            new = bytearray(mod) + bytes(MAX_SECTORS * P.DATA - len(mod))
            block, table = name_block(names, en_names, len(mod))
            new[len(mod):len(mod) + len(block)] = block
            new[pceengine.NAMES_PTR:pceengine.NAMES_PTR + 2] = table.to_bytes(2, "little")
            new[pceengine.ALL_EN] = 1
            new[pcesubs.MAGIC:pcesubs.MAGIC + 2] = bytes(2)         # no subtitle table
            new[SEARCH_PTR:SEARCH_PTR + 2] = bytes(2)              # no search table
            at = len(mod) + len(block)
            subs, sptr, cptr = pcesubs.module_blocks(rec, at, pcesubs.magic(new))
            new[pcesubs.CUES_PTR:pcesubs.CUES_PTR + 2] = cptr.to_bytes(2, "little")
            if subs or sptr or cptr:
                # the voiced lines' table after the names, and - with no resident file under
                # the ending - the stub itself in the module's fourth bank
                new[at:at + len(subs)] = subs
                new[pcesubs.MAGIC:pcesubs.MAGIC + 2] = pcesubs.magic(new)
                new[pcesubs.SUBS_PTR:pcesubs.SUBS_PTR + 2] = sptr.to_bytes(2, "little")
                if rec in pcesubs.NO_RESIDENT:
                    # (the stub alone: the ending's 23 KB table leaves no room for a face block of
                    # its own, and rec 110 - with the resident one - was there when it was played)
                    if at + len(subs) > pcesubs.MODULE_STUB_OFF:
                        raise OverflowError(f"rec {rec}: the subtitle table ends at {at + len(subs):#06x}, into the module's stub")
                    code, _ = pcesubs.stub(pcesubs.MODULE_STUB)
                    new[pcesubs.MODULE_STUB_OFF:pcesubs.MODULE_STUB_OFF + len(code)] = code
            new[pcepair.FONT_OFF:pcepair.FONT_OFF + len(font)] = font
            # the pair table: the credit roll's rows (rec 130, pceending) are drawn with this
            # module's table, so they take their slots here; after the subtitle table, clear
            # of the module stub
            import pceending, pcescene
            pceending.build(bytes(pcescene.block(*pceending.BLOCK)))
            tab = pcepair.current().blob()
            tat = at + len(subs)
            top = pcesubs.MODULE_STUB_OFF if rec in pcesubs.NO_RESIDENT else pcepair.FONT_OFF
            if tat + len(tab) > top:
                raise OverflowError(f"rec {rec}: the pair table ends at {tat + len(tab):#06x}, past {top:#06x}")
            new[tat:tat + len(tab)] = tab
            new[pcepair.PAIRS_PTR:pcepair.PAIRS_PTR + 2] = (tat + 2).to_bytes(2, "little")
            new_rec = img.alloc(MAX_SECTORS)
            img.retable(rec, n, new_rec, MAX_SECTORS)
            img.write((T2 + new_rec) * P.DATA, bytes(new))
            placed[rec] = [new_rec, MAX_SECTORS]
            print(f"rec {rec}: no text, the font and the English flag -> rec {new_rec}")
            done += 1
            continue
        if len(strings) < 8 or bad:
            continue
        lines = [english[key(jp)] for _, jp in strings if key(jp) in english]
        # The word list sits just before the text. Its records may change
        # length: every `f1` reference into it is remapped here, and the text
        # block behind it moves with rebuild() remapping the say references.
        # a string of nothing but fullwidth spaces (382's answer slots) is English already: it
        # must not keep a module's English flag off (its names then draw as kanji)
        for _, jp in strings:
            if jp and not jp.strip("　 ") and key(jp) not in english:
                english[key(jp)] = jp
        wstart, wend, wrecs = word_list(mod, strings[0][0])
        wdone, nref, search = 0, 0, None
        subs = any(pcesubs.table(rec))         # the voiced lines' rows (pce/translation/subs_<rec>.json; placed below)
        if wrecs:
            wblock, wdone, wover, rel = word_block(wrecs, menu, rec=rec, lead_ff=mod[wstart] == 0xFF)
            for nb, jp, en in wover:
                print(f"  rec {rec}: {en!r} is {nb}B over the slot for {jp}")
            remap = {o: wstart + r for o, r in zip(record_offsets(mod, wstart, wrecs), rel) if o != wstart + r}
            if rec == SEARCH_MODULE:
                search = search_table(mod, wstart, wrecs, remap)
            code, nref = remap_labels(mod[:wstart], remap)
            tail, nref2 = remap_labels(mod[wend:strings[0][0]], remap)
            nref += nref2
            head = code + wblock + tail
        else:
            head = mod[:strings[0][0]]
        text_start = len(head)
        full = head + bytes(MAX_SECTORS * P.DATA - len(head))

        all_en = all(key(jp) in english for _, jp in strings)

        def enc_len(jp, frags):
            return len(english_bytes(english[key(jp)], frags, not all_en)) if key(jp) in english else len(T.encode(jp))

        def build(frags, evict=()):
            longs = bytearray()
            new = bytearray(rebuild(full, strings, english, limit=pcepair.FONT_OFF,
                                    frags=frags, marker=not all_en, start=text_start, evict=evict, longs=longs,
                                    longs_base=pcelongs.base(rec) if evict else None,
                                    longs_room=pcelongs.room(rec) if evict else None,
                                    longs_holes=pcelongs.holes(rec) if evict else None))
            end = text_start + sum(enc_len(jp, frags) for off, jp in strings if off not in evict)
            block, table = name_block(names, en_names, end)
            new[end:end + len(block)] = block
            new[pceengine.NAMES_PTR:pceengine.NAMES_PTR + 2] = table.to_bytes(2, "little")
            new[pceengine.ALL_EN] = int(all_en)
            end += len(block)
            if frags:
                blob, offs = pcedict.entries(frags, end)
                new[end:end + len(blob)] = blob
                end += len(blob)
                tab = pcedict.table(offs)
                new[end:end + len(tab)] = tab
                new[pceengine.DICT_PTR:pceengine.DICT_PTR + 2] = end.to_bytes(2, "little")
                end += len(tab)
            if search:
                new[end:end + len(search)] = search
                new[SEARCH_PTR:SEARCH_PTR + 2] = end.to_bytes(2, "little")
                end += len(search)
            else:
                new[SEARCH_PTR:SEARCH_PTR + 2] = bytes(2)     # no table: the stub keeps the engine's scan
            new[pcesubs.MAGIC:pcesubs.MAGIC + 2] = bytes(2)         # no subtitle table
            new[pcesubs.CUES_PTR:pcesubs.CUES_PTR + 2] = bytes(2)
            if subs:
                # the voiced lines' table and its CD-DA cue block (the stub that draws them is in
                # the resident file, pcesubs); with no room in the window (OVERFLOW) they go
                # into rec 54's bank (pcesubs.apply) and the pointers read them through FETCH's
                # bank arithmetic
                t, sptr, cptr = pcesubs.module_blocks(rec, end, pcesubs.magic(new))
                new[end:end + len(t)] = t
                new[pcesubs.MAGIC:pcesubs.MAGIC + 2] = pcesubs.magic(new)
                new[pcesubs.SUBS_PTR:pcesubs.SUBS_PTR + 2] = sptr.to_bytes(2, "little")
                new[pcesubs.CUES_PTR:pcesubs.CUES_PTR + 2] = cptr.to_bytes(2, "little")
                end += len(t)
            # last, the pair table: every code encoded above has its slot by now
            tab = pcepair.current().blob()
            new[end:end + len(tab)] = tab
            new[pcepair.PAIRS_PTR:pcepair.PAIRS_PTR + 2] = (end + 2).to_bytes(2, "little")
            end += len(tab)
            if end > pcepair.FONT_OFF:
                e = OverflowError(f"module data ends at {end:#06x}")
                e.over = end - pcepair.FONT_OFF
                raise e
            return new, end, longs

        def evictions(frags, need):
            """The largest strings first until `need` bytes leave the block (pcelongs)."""
            sizes = sorted(((enc_len(jp, frags), off) for off, jp in strings), reverse=True)
            out, got = set(), 0
            for n, off in sizes:
                if got >= need:
                    break
                out.add(off)
                got += n
            return out, got

        frags, evict, longs = None, set(), bytearray()
        try:
            if os.environ.get("PCE_DICT"):
                raise OverflowError("forced")     # PCE_DICT=1: dictionary everywhere (a test)
            new, end, longs = build(None)
        except OverflowError:
            frags = pcedict.build([layout(en) for en in lines])
            try:
                new, end, longs = build(frags)
            except OverflowError as e:
                # the longest strings leave the module for its longs blob (pcelongs): what the
                # module is over by (the text slot's or the data end's excess), plus a margin
                need = getattr(e, "over", 0) + pcelongs.MARGIN
                if os.environ.get("LONGS_IN_MODULE") or not need:
                    print(f"rec {rec}: SKIPPED even with a {len(frags)}-entry dictionary, {e}")
                    continue
                # a second round when the first excess hid another (478: the text slot's,
                # then the data end's)
                for _ in range(4):
                    evict, got = evictions(frags, need)
                    try:
                        new, end, longs = build(frags, evict)
                        if os.environ.get("LONGS_DEBUG"):
                            print(f"  rec {rec}: {len(evict)} evicted, {got} B for {need} B needed")
                        break
                    except OverflowError as e2:
                        if os.environ.get("LONGS_DEBUG"):
                            print(f"  rec {rec}: {len(evict)} evicted for {need} B: {e2}")
                        need = max(need + getattr(e2, "over", 0), got + 1)     # at least one string more
                else:
                    print(f"rec {rec}: SKIPPED even with {len(evict)} strings evicted, {need} B needed")
                    continue
        new[pcepair.FONT_OFF:pcepair.FONT_OFF + len(font)] = font
        where = ""
        orig_rec = rec
        if n != MAX_SECTORS:
            new_rec = img.alloc(MAX_SECTORS)
            img.retable(rec, n, new_rec, MAX_SECTORS)
            where = f" -> rec {new_rec}"
            rec = new_rec
        lng = ""
        if longs:
            nsec = (len(longs) + P.DATA - 1) // P.DATA
            lrec = img.alloc(nsec)
            img.write((T2 + lrec) * P.DATA, bytes(longs) + bytes(nsec * P.DATA - len(longs)))
            new[pcelongs.DESC:pcelongs.DESC + 9] = pcelongs.descriptor(lrec, len(longs), orig_rec)
            lng = f", {len(evict)} strings ({len(longs)} B) in longs rec {lrec} x{nsec}"
        if pcelongs.needs_restore(orig_rec, bytes(full)):
            new[pcelongs.REST:pcelongs.REST + 8] = pcelongs.restore()     # 318's blob never outlives 318
        img.write((T2 + rec) * P.DATA, bytes(new))
        placed[orig_rec] = [rec, MAX_SECTORS]
        used = sum(1 for _, jp in strings if key(jp) in english)
        dic = f", {len(frags)}-entry dictionary" if frags else ""
        menus = f", {wdone}/{len(wrecs)} labels ({nref} refs moved)" if wrecs else ""
        print(f"rec {rec}: {used}/{len(strings)} lines English{menus}, data to {end:#06x}{dic}{lng}{where}")
        done += 1
    pcepair.use(None)
    pcepair.save_registry()
    stub = pceengine.install(img)
    json.dump(placed, open(os.path.join(WORK, "pce", "build_map.json"), "w"), indent=1)
    print(f"{img.flush()} sectors rewritten, {done} modules, {stub}B of engine stubs")


def lint():
    import pcepair
    english = load_english()
    for k, en in english.items():
        rows = cells(en)
        if max(rows) > COLS:
            print(f"{max(rows)} cells: {en}")
        try:
            with pcepair.using(pcepair.PairTable()):
                T.encode(en)
        except ValueError as e:
            print(f"{e}: {en}")


def main():
    cmd = sys.argv[1]
    if cmd == "lint":
        return lint()
    if cmd == "apply":
        P.fresh_copy()
    img = P.Image(P.OUT if cmd == "apply" else P.SRC, P.T3 + P.RESERVE if cmd == "apply" else 12000)
    if cmd == "dump":
        dump(img)
    elif cmd == "apply":
        apply(img, {int(x) for x in sys.argv[2:]} or None)


if __name__ == "__main__":
    main()
