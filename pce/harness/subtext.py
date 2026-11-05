"""The subtitle pages the stub draws, read back as text and judged against the English
they should carry.

The resident stub lays each page out as a renderer message in its own buffer
($3A66, pcesubs.MSG_RES): `fc 00`, then per row `f8 lo hi` (the row's tile base),
`fb col row`, `fe colour` and pair codes, `f8 00 70` (the game's base back) and `ff`.
`rows(raw, table)` parses that properly (commands and their parameters are never
glyphs) and decodes the pair codes through the loaded module's pair table.

The pilot (pcemenu, LINELOG=1) logs each new page as

    <frame>: subpage mod <rec> line <nn>|cd <track>|- rows ['..', '..'] [issues]

and `check(log)` judges every one: the page's words, joined, must be a run of the
words of the line (subs_<rec>.json `en`) or of one of the track's cues
(cdda_<rec>.json) - the speaker's name may open a plain page. A page that is not is
WRONG TEXT (a garbled, foreign or stale page); an invalid code is BAD GLYPH. The
same reading gives the coverage of the CD-DA cues (a cue is shown when a page of
its words was drawn) - voice_coverage.py prints both.
"""
import glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'pce/tools', 'pce/harness')]
import pcepair

TR = os.path.join(ROOT, "pce", "translation")
PARAMS = {0xFC: 1, 0xF9: 1, 0xFE: 1, 0xFB: 2, 0xF8: 2}


def rows(raw, table):
    """(rows of text, issues) of a renderer message (`fc ..` up to `ff`)."""
    out, issues, at, cur = [], [], 0, None
    if not raw or raw[0] != 0xFC:
        return [], ["no message"]
    while at < len(raw):
        b = raw[at]
        if b == 0xFF:
            break
        if b in PARAMS:
            if b == 0xFB:
                cur = []
                out.append(cur)
            at += PARAMS[b] + 1
            continue
        if at + 1 >= len(raw):
            issues.append("truncated")
            break
        hi, lo = b, raw[at + 1]
        at += 2
        if cur is None:
            cur = []
            out.append(cur)
        if pcepair.is_pair(hi, lo):
            slot = pcepair.slot_of_code(hi, lo)
            p = table.pair(slot) if table is not None and 0 <= slot < pcepair.SLOTS else None
            if p is None or not all(pcepair.printable(c) for c in p):
                issues.append(f"bad pair {hi:02x}{lo:02x}")
                cur.append("?")
            else:
                cur.append("".join(p))
        else:
            try:
                ch = bytes((hi, lo)).decode("cp932")
            except UnicodeDecodeError:
                ch = None
            if ch is None or not (0x81 <= hi <= 0x84):
                issues.append(f"bad code {hi:02x}{lo:02x}")
                cur.append("?")
            else:
                cur.append(ch)
    else:
        issues.append("no terminator")
    return ["".join(r).rstrip() for r in out], issues


# ---------------------------------------------------------------- the intended English

def words(text):
    """Comparable words: tags and row breaks out, case and spacing ignored."""
    text = re.sub(r"<[^>]*>", " ", text or "").replace("|", " ")
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return text.lower().split()


_LINES, _CUES, _NAMES = {}, {}, set()


def lines(rec):
    """{nn: (speaker, en)} of subs_<rec>.json, NN as two hex digits."""
    if rec not in _LINES:
        path = os.path.join(TR, f"subs_{rec}.json")
        d = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        _LINES[rec] = {}
        for k, v in d.items():
            if k.startswith("_") or not isinstance(v, dict) or not v.get("en"):
                continue
            nn = k.split(".")[0].lower().zfill(2)
            _LINES[rec].setdefault(nn, []).append((v.get("speaker") or "", v["en"], v.get("display")))
    return _LINES[rec]


def cdda_files():
    return sorted(glob.glob(os.path.join(TR, "cdda_*.json")))


def cues(rec):
    """[(track, idx, speaker, en)] of cdda_<rec>.json (rec may be 'opening')."""
    if rec not in _CUES:
        path = os.path.join(TR, f"cdda_{rec}.json")
        out = []
        if os.path.exists(path):
            d = json.load(open(path, encoding="utf-8"))
            items = d.get("cues", d) if isinstance(d, dict) else d
            for i, c in enumerate(items):
                if isinstance(c, dict) and c.get("en") and c.get("display") != "graphic":
                    out.append((c.get("track"), i, c.get("speaker") or "", c["en"]))
        _CUES[rec] = out
    return _CUES[rec]


def speakers():
    if not _NAMES:
        for p in glob.glob(os.path.join(TR, "subs_*.json")) + cdda_files():
            d = json.load(open(p, encoding="utf-8"))
            items = d.values() if isinstance(d, dict) and "cues" not in d else (d.get("cues", []) if isinstance(d, dict) else d)
            for v in items:
                if isinstance(v, dict) and v.get("speaker"):
                    _NAMES.add(v["speaker"])
    return _NAMES


def contains(seq, sub):
    n = len(sub)
    return n == 0 or any(seq[i:i + n] == sub for i in range(len(seq) - n + 1))


def fits(page, speaker, en):
    """The page's words are a run of the line's (a plain page may open with 'Name:')."""
    w, line = words(" ".join(page)), words(en)
    if contains(line, w):
        return True
    for name in {speaker} | speakers():
        nw = words(name + ":")
        if name and w[:len(nw)] == nw and contains(line, w[len(nw):]):
            return True
    return False


# ---------------------------------------------------------------- the log

SUBPAGE = re.compile(r"^(\d+): subpage mod (\S+) (line ([0-9a-f]{2})|cd ([0-9a-f]{2})|-) rows (\[.*?\])(?: issues (\[.*\]))?$")


def parse_log(path):
    import ast
    out = []
    for ln in open(path, encoding="utf-8", errors="replace"):
        m = SUBPAGE.match(ln.strip())
        if not m:
            continue
        mod = m.group(2)
        out.append(dict(frame=int(m.group(1)), mod=int(mod) if mod.isdigit() else mod,
                        nn=m.group(4), track=m.group(5), rows=ast.literal_eval(m.group(6)),
                        issues=ast.literal_eval(m.group(7)) if m.group(7) else [], log=path))
    return out


def judge(page):
    """(verdict, what it matched): ok / WRONG TEXT / BAD GLYPH / unjudged."""
    if page["issues"]:
        return "BAD GLYPH", None
    text = [r for r in page["rows"] if r.strip()]
    if not text:
        return "ok", None                       # a blank page (the stub's clear)
    mod = page["mod"]
    if page["nn"] and isinstance(mod, int):
        cands = lines(mod).get(page["nn"], [])
        for sp, en, disp in cands:
            if fits(text, sp, en):
                return "ok", ("line", mod, page["nn"])
        # a line the stub showed from another module's table, or a cue over a line
        for rec in [r for r in _all_recs() if r != mod]:
            for sp, en, disp in lines(rec).get(page["nn"], []):
                if fits(text, sp, en):
                    return "ok", ("line", rec, page["nn"])
        # the stub can lay the next line's page out a few frames before the pilot reads the
        # chip playing (the ending's module stub): another line of the module whose words it
        # carries is that line's page (sync_live times it from that line's start)
        for nn, specs in lines(mod).items():
            for sp, en, disp in specs:
                if nn != page["nn"] and fits(text, sp, en):
                    return "ok", ("line", mod, nn)
    if page["track"] or page["nn"] is None:
        # a cue whose words the page holds whole first (a short cue, 'Jamie.', is also a run of
        # a longer one before it), then any cue the page is a run of
        for whole in (True, False):
            for f in cdda_files():
                rec = os.path.basename(f)[5:-5]
                rec = int(rec) if rec.isdigit() else rec
                for track, i, sp, en in cues(rec):
                    if not (page["track"] is None or track is None or f"{int(track):02d}" == page["track"]
                            or f"{int(track):02x}" == page["track"]):
                        continue
                    if whole:
                        w, cw = words(" ".join(text)), words(en)
                        nw = words((sp or "") + ":")
                        if w == cw or (sp and w[:len(nw)] == nw and w[len(nw):] == cw):
                            return "ok", ("cue", rec, i)
                    elif fits(text, sp, en):
                        return "ok", ("cue", rec, i)
        if page["nn"] is None:
            return "unjudged", None
    return "WRONG TEXT", None


def _all_recs():
    return sorted(int(os.path.basename(p)[5:-5]) for p in glob.glob(os.path.join(TR, "subs_*.json"))
                  if os.path.basename(p)[5:-5].isdigit())


SCREEN = re.compile(r"^(\d+): screen (GARBLED ON SCREEN|NOT ON SCREEN) mod (\S+) (line ([0-9a-f]{2})|cd ([0-9a-f]{2})|-) rows (\[.*?\]) seen (\[.*?\]) capture (.*)$")


# pages known not to read whole on screen, with why (mod, line NN or "cd TT") - printed, not failed
KNOWN_SCREEN = {
    (334, "77"): "Gillian's 'A time bomb!' beside her screaming face (#92): that portrait is drawn from two "
                 "face regions, 80 px wide from x 32, and covers the text's first cell at x 104 ('A ' hidden); "
                 "a plain card would hide the scream. Save: mod334 (factory ruins, Look > Little John).",
}


def picture_up(capture):
    """Whether a capture shows the scene's picture lit (rows 20-140): a page never seen there
    went missing; a black screen is a fade, the scene changing under it."""
    try:
        from PIL import Image
        im = Image.open(capture.strip()).convert("L")
    except Exception:
        return False
    w = im.size[0]
    return sum(1 for y in range(20, 140, 8) for x in range(0, w, 8) if im.getpixel((x, y)) > 40) > 20


def screen_problems(path):
    import ast
    out = []
    for ln in open(path, encoding="utf-8", errors="replace"):
        m = SCREEN.match(ln.strip())
        if m:
            mod = m.group(3)
            out.append((m.group(2), dict(frame=int(m.group(1)), mod=int(mod) if mod.isdigit() else mod,
                                         nn=m.group(5), track=m.group(6), rows=ast.literal_eval(m.group(7)),
                                         issues=[f"seen {ast.literal_eval(m.group(8))}", m.group(9)], log=path)))
    return out


def check(logs):
    """(problems, shown cues {(rec, idx)}, pages judged) over the logs: the buffer's pages
    against the English, and the screen's (pcemenu screen_judge) against the buffer's."""
    problems, shown, n = [], set(), 0
    for path in logs:
        # a page never seen whole on screen is a failure when the picture was up meanwhile
        # (a dark band or a cut page under a lit scene: the missing subtitles); not over a fade
        # (the whole screen dark - a scene changing)
        for x in screen_problems(path):
            if x[0] == "NOT ON SCREEN" and (x[1]["mod"], x[1]["nn"] or f"cd {x[1]['track']}") in KNOWN_SCREEN:
                continue
            if x[0] == "GARBLED ON SCREEN" or (x[0] == "NOT ON SCREEN" and picture_up(x[1]["issues"][1])):
                problems.append(x)
        for page in parse_log(path):
            n += 1
            v, what = judge(page)
            if what and what[0] == "cue":
                rec, i = what[1:]
                if (rec, i) in shown:           # the same words twice on a track ('Jamie.'): the next
                    cs = {k: (t, en) for t, k, sp, en in cues(rec)}
                    same = [k for k, (t, en) in sorted(cs.items())
                            if k != i and t == cs[i][0] and words(en) == words(cs[i][1]) and (rec, k) not in shown]
                    if same:
                        i = same[0]
                shown.add((rec, i))
            if v not in ("ok", "unjudged"):
                problems.append((v, page))
    return problems, shown, n


LINE = re.compile(r"^(\d+): line ([0-9a-f]{2}) (?:sub|no subtitle).*? mod (\d+)(?:.*\| sec (\d+))?")
GAMEPAGE = re.compile(r"^(\d+): page ")
_SECTORS = {}


def sectors(rec, nn):
    """The start sectors of the voice records subs_<rec>.json subtitles under NN (one per act it
    is keyed for), or None when they cannot be read."""
    if (rec, nn) not in _SECTORS:
        try:
            import pcesubs as S, pcevoice as V
            path = os.path.join(TR, f"subs_{rec}.json")
            keys = [k for k in json.load(open(path, encoding="utf-8")) if not k.startswith("_") and k.split(".")[0] == nn]
            _SECTORS[(rec, nn)] = {V.record(*S.line_key(rec, k))["sector"] & 0xFFFF for k in keys}
        except Exception:
            _SECTORS[(rec, nn)] = None
    return _SECTORS[(rec, nn)]


def spec_of(rec, nn):
    path = os.path.join(TR, f"subs_{rec}.json")
    if not os.path.exists(path):
        return None
    for k, v in json.load(open(path, encoding="utf-8")).items():
        if not k.startswith("_") and k.split(".")[0].lower().zfill(2) == nn and isinstance(v, dict):
            return v
    return None


def card_starts(spec):
    """The word index each card of the line starts at."""
    out, at = [], 0
    for c in spec.get("cards") or []:
        out.append(at)
        at += len(words(c))
    return out


LATE = 1.5          # seconds from a line's start to its first page (a face awaited for GRACE frames: 3.3)


def sync_live(logs, limit=0.75):
    """The pages as the pilot SAW them come up against their line's voice: each page is the
    page of the line whose words it carries (judge), timed from that line's start (the
    nearest start of that NN at most EARLY frames after the page - the stub may lay a page
    out just before the pilot reads the chip playing). A line's first page more than LATE
    seconds after its voice is a LATE PAGE; each later page that opens a card (a face page
    may hold two cards, the plain fallback splits one) is held against that card's `turn`
    (LATE TURN past `limit`). [(rec, nn, card, expected s, seen s, log)], and the count."""
    EARLY = 20
    bad, n = [], 0
    for path in logs:
        starts, pageframes = {}, []
        for ln in open(path, encoding="utf-8", errors="replace"):
            g = GAMEPAGE.match(ln)
            if g:
                pageframes.append(int(g.group(1)))
            m = LINE.match(ln.strip())
            if m and m.group(2) != "00" and int(m.group(1)) >= 60:   # (a line under way when a state was restored: no start)
                rec, nn = int(m.group(3)), m.group(2)
                secs = sectors(rec, nn) if m.group(4) else None
                if secs is not None and int(m.group(4)) not in secs:
                    continue            # the same NN in another act's table: not this line (670's)
                starts.setdefault((rec, nn), []).append(int(m.group(1)))
        per_line = {}
        for p in parse_log(path):
            if p["track"] or not any(r.strip() for r in p["rows"]) or not isinstance(p["mod"], int):
                continue
            v, what = judge(p)
            if v != "ok" or not what or what[0] != "line":
                continue
            # of the module's lines whose words the page carries (a short page, "Jamie!", fits
            # several), the one that started last before it
            rec, text = p["mod"], [r for r in p["rows"] if r.strip()]
            best = None
            for nn, specs in lines(rec).items():
                if not any(fits(text, sp, en) for sp, en, disp in specs):
                    continue
                f0 = max((f for f in starts.get((rec, nn), []) if f <= p["frame"] + EARLY), default=None)
                if f0 is not None and (best is None or f0 > best[1]):
                    best = (nn, f0)
            if best is None:
                continue
            nn, f0 = best
            per_line.setdefault((rec, nn, f0), []).append(p)
        # a line that played and showed no page of its own at all (a face card waiting GRACE for
        # a portrait that never came, cut off by the next line): NO PAGE
        ours = sorted(p["frame"] for p in parse_log(path))
        import bisect
        def ours_near(f):
            i = bisect.bisect_left(ours, f - 8)
            return i < len(ours) and ours[i] <= f + 8
        game = [f for f in pageframes if not ours_near(f)]       # a message of the game's own
        for (rec, nn), fs in starts.items():
            specs = [x for x in lines(rec).get(nn, []) if x[2] != "graphic"]
            if not specs:
                continue
            for f0 in fs:
                if any(f0 - 10 <= f <= f0 + 120 for f in game):
                    continue            # the game's own message had the window: ours yields (by design)
                if not any(k[0] == rec and k[1] == nn and abs(k[2] - f0) <= EARLY for k in per_line):
                    n += 1
                    bad.append((rec, nn, 0, 0.0, -1.0, path))
        for (rec, nn, f0), pages in per_line.items():
            first = min(p["frame"] for p in pages)
            n += 1
            if (first - f0) / 60 > LATE:          # the words came up well after the voice
                bad.append((rec, nn, 1, 0.0, round((first - f0) / 60, 2), path))
            spec = spec_of(rec, nn)
            turns = spec.get("turns") if spec else None
            if not turns:
                continue
            starts_w = card_starts(spec)
            en = words(spec["en"])
            sp = words((spec.get("speaker") or "") + ":")
            done = set()
            for p in pages:
                w = words(" ".join(p["rows"]))
                if w[:len(sp)] == sp:
                    w = w[len(sp):]
                if not w:
                    continue
                at = next((i for i in range(len(en)) if en[i:i + len(w)] == w), None)
                if at is None or at not in starts_w:
                    continue
                k = starts_w.index(at)
                if k == 0 or k in done or k - 1 >= len(turns):
                    continue
                done.add(k)
                n += 1
                got = (p["frame"] - f0) / 60
                if abs(got - turns[k - 1]) > limit:
                    bad.append((rec, nn, k + 1, turns[k - 1], round(got, 2), path))
    return bad, n


def main():
    logs = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if not logs:
        logs = glob.glob(os.path.join(WORK, "pce", "**", "*.log"), recursive=True)
    problems, shown, n = check(logs)
    seen = set()
    for v, p in problems:
        key = (v, p["mod"], p["nn"], p["track"], tuple(p["rows"]))
        if key in seen:
            continue
        seen.add(key)
        what = f"line {p['nn']}" if p["nn"] else f"cd {p['track']}"
        print(f"{v}: mod {p['mod']} {what} frame {p['frame']}: {p['rows']} {p['issues'] or ''}  ({os.path.relpath(p['log'], ROOT)})")
    bad, nt = sync_live(logs)
    for rec, nn, card, want, got, path in bad:
        what = "NO PAGE" if card == 0 else "LATE PAGE" if card == 1 else "LATE TURN"
        print(f"{what}: mod {rec} line {nn} card {card} up at {got:.2f} s, the voice at {want:.2f} s  ({os.path.relpath(path, ROOT)})")
    for key, why in KNOWN_SCREEN.items():
        print(f"known: mod {key[0]} {key[1]}: {why}")
    print(f"\n{n} subtitle pages read, {len(seen)} distinct problem page(s); {nt} page starts and turns timed on screen, {len(bad)} late")
    sys.exit(1 if problems or bad else 0)


if __name__ == "__main__":
    main()
