"""Choose subtitle page boundaries without changing dialogue words.

The renderer's word chunks include pair-cell padding. Plan with those exact
costs, the actual row count, and the first-page speaker label. Minimize the
number of pages before improving phrase boundaries and reading balance.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [HERE, os.path.join(ROOT, "lib")]

ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "mk.", "jr.", "st."}
DEPENDENT = set("a an the to of in on at for from with by into onto and or but if as than that whose your my his her our their its this these those I you he she we they I'll you'll he'll she'll we'll they'll I've you've we've they've it's there's don't doesn't didn't won't can't can could would should must".lower().split())


def boundary_penalty(words, index):
    """Prefer complete sentences/clauses; keep small dependent words attached."""
    previous = words[index - 1][0].rstrip()
    following = words[index][0].strip()
    if previous.endswith((".", "?", "!")) and previous.lower() not in ABBREVIATIONS:
        return 0
    if previous.endswith((",", ";", ":", "--")):
        return 12
    if previous.lower() in DEPENDENT:
        return 160
    if following.lower() in {"and", "but", "or", "if", "when", "because", "while", "although", "unless",
                             "to", "where", "who", "which", "so", "until", "before", "after"}:
        return 25
    return 55


# words a ROW should not end on (an object pronoun may: "I'll show you / around inside.")
ROW_DEPENDENT = set("a an the to of in on at for from with by into onto and or but if as than that "
                    "whose your my his her our their its this these those".split())


BULLET = re.compile(r"^\(?\d{1,2}[.)]$")


def bullet_starts(words):
    """Word indices that open a numbered item ("1. Skull size. 2. ..."): a lone number token
    after a finished sentence or a colon, never after "number" (a button called 1). Each one
    opens its own card, so a list reads item by item (Metal Gear's examinations). The numbers
    must count 1, 2, 3...: "Hair index: 65." is a value, not an item."""
    out, expected = set(), 1
    for i in range(len(words)):
        token = words[i][0].strip()
        if not BULLET.match(token):
            continue
        value = int(token.strip("().").rstrip(")"))
        previous = words[i - 1][0].strip() if i else ""
        opens = i == 0 or (previous.endswith((".", ":", "!", "?"))
                           and previous.lower().rstrip(".") not in {"number", "no"})
        if opens and value in (1, expected):
            if i:
                out.add(i)
            expected = value + 1
    return out


def page_ends(words, cost, width, rows, name_cost=0, preferred=None):
    """Return exclusive word indices, including the final end of the text.

    The lexicographic objective prevents an attractive sentence boundary
    creating an extra, shorter card. Among equally few cards, avoid orphan
    words, unfinished phrases and an uneven division of reading time.
    """
    count = len(words)
    if not count:
        return []
    sizes = [cost(*word) for word in words]
    bullets = bullet_starts(words)
    lengths = [len(word[0].strip()) for word in words]
    # A suffix solution is independent of earlier pages: only page zero has
    # a name. Squared page lengths minimize imbalance at fixed page count.
    best = [None] * (count + 1)
    best[count] = ((0, 0), [])
    for start in range(count - 1, -1, -1):
        row, used = 1, name_cost if start == 0 else 0
        letters = 0
        choices = []
        for end in range(start + 1, count + 1):
            if end - 1 > start and end - 1 in bullets:
                break                      # a numbered item opens the next card
            size = sizes[end - 1]
            if used + size > width:
                row, used = row + 1, 0
            if row > rows:
                break
            used += size
            letters += lengths[end - 1]
            suffix = best[end]
            if suffix is None:
                continue
            penalty = 0 if end == count else boundary_penalty(words, end)
            if preferred == end:
                penalty = 0
            orphan = max(0, 12 - letters) ** 2 * 8
            # Phrase choice dominates small balance differences; a one-word
            # final card remains expensive even when it completes a sentence.
            score = (suffix[0][0] + 1,
                     suffix[0][1] + letters * letters + penalty * 16 + orphan)
            choices.append((score, [end] + suffix[1]))
        if choices:
            best[start] = min(choices, key=lambda choice: choice[0])
    if best[0] is None:
        raise ValueError("A subtitle word cannot fit in the selected layout")
    return best[0][1]


def merge_cues(cues, fits, max_duration=12):
    """Group contiguous CD cues that fit one card, retaining their full span.

    Speaker changes, track changes and audible gaps are hard boundaries.
    `fits` checks both possible display widths for the target module.
    """
    count = len(cues)
    best = [None] * (count + 1)
    best[count] = ((0, 0), [])
    for start in range(count - 1, -1, -1):
        first = cues[start]
        text = first["en"]
        choices = []
        for end in range(start + 1, count + 1):
            last = cues[end - 1]
            if end > start + 1:
                previous = cues[end - 2]
                if (last["track"] != first["track"] or last.get("speaker") != first.get("speaker")
                        or not -0.02 <= last["start"] - previous["end"] <= 0.08
                        or last["end"] - first["start"] > max_duration):
                    break
                text += " " + last["en"]
                if not fits(first.get("speaker"), text):
                    break
                # Do not lengthen a card by attaching the start of a phrase
                # that still has to finish in the next cue.
                if not text.rstrip().endswith((".", "?", "!", ":")):
                    continue
            suffix = best[end]
            penalty = 0
            if end < count and cues[end].get("speaker") == first.get("speaker"):
                boundary_words = [(w, 0) for w in text.split() + cues[end]["en"].split()]
                if text.split() and cues[end]["en"].split():
                    penalty = boundary_penalty(boundary_words, len(text.split()))
            score = (suffix[0][0] + 1, suffix[0][1] + len(text) ** 2 + penalty * 16)
            choices.append((score, [(start, end)] + suffix[1]))
        best[start] = min(choices, key=lambda choice: choice[0])
    merged = []
    for start, end in best[0][1]:
        group = cues[start:end]
        item = dict(group[0])
        if len(group) > 1:
            item["en"] = " ".join(cue["en"] for cue in group)
            item["end"] = group[-1]["end"]
            ids = []
            for cue in group:
                ids.extend([cue["ps1"]] + cue.get("ps1_more", []))
            item["ps1_more"] = ids[1:]
        merged.append(item)
    return merged


# ---------------------------------------------------------------- rows and pages, planned

def plan_pages(texts, cells, width, rows, first=0, forced=(), preferred=None, reserve=None, split=None):
    """Pages and their rows for a line of words, planned whole (the stub follows the plan:
    a marker at every row break - pcesubs ROW_FACE / ROW_PLAIN).

    `texts` the words; `cells(a, b)` the cells words a..b-1 take in one row; `first` the cells
    the first row of every page already holds (the plain layout's name; `reserve` the cells
    held on each row of a page by its index, `(first,)` by default - a plain card's third row
    keeps room for the name too, as the two-row fallback opens a page there; `split` the row
    index a fallback layout opens a page at - the break before it scored as a page break,
    the four-row face card's third row); `forced` word
    indices that must open a page (numbered items); `preferred` a page break that costs
    nothing. Returns [[(a, b), ...], ...] - pages of rows.

    One score, the sum of: PAGE a page; where pages break (sentences first, a clause cut
    costing more than a page more); rows that break after a dependent word; a lone word on
    a row of a page that has more; short pages; uneven rows within a page."""
    n = len(texts)
    forced = set(forced)
    words = [(t + " ", 0) for t in texts]

    def row_cost(a, b, last_of_page):
        """A row break's cost by what it cuts: a sentence nothing, a clause a little, a
        phrase more, the words after an article, preposition or conjunction most."""
        if last_of_page or b >= n:
            return 0
        prev = texts[b - 1].rstrip()
        nxt = texts[b].strip().lower()
        if prev.endswith((".", "?", "!")) and prev.lower() not in ABBREVIATIONS:
            return 0
        if prev.endswith((",", ";", ":", "--")):
            return 5
        if prev.lower() in ROW_DEPENDENT:
            return 40
        if prev[:1].isupper() and texts[b][:1].isupper() and b - 1 > a:
            return 40                                   # a name: "Freddy / Nielsen"
        if nxt in {"and", "but", "or", "if", "when", "because", "while", "to", "where", "who",
                   "which", "so", "until", "before", "after", "that"}:
            return 10
        return 18

    import functools

    reserve = tuple(reserve) if reserve is not None else (first,)
    held = lambda i: reserve[i] if i < len(reserve) else 0

    @functools.lru_cache(maxsize=None)
    def page_from(s, k, i):
        """{end: [(cost, rows), ...]} - every split of one page from word s into at most k
        rows (the first being the page's row i), with the rows' own costs; the page's
        score (balance, lone words) is the caller's, so no split is dropped before it."""
        out = {}
        b = s + 1
        while b <= n:
            if b - 1 > s and (b - 1) in forced:
                break
            if held(i) + cells(s, b) > width:
                break
            last = b == n
            out.setdefault(b, []).append((row_cost(s, b, True), ((s, b),)))   # the page ends here
            if k > 1 and not last and b not in forced:
                for e, opts in page_from(b, k - 1, i + 1).items():
                    for c2, rws in opts:
                        rc = boundary_penalty(words, b) * 0.5 if split == i + 1 else row_cost(s, b, False)
                        out.setdefault(e, []).append((rc + c2, ((s, b),) + rws))
            b += 1
        return out

    def page_score(rws, end, first_page):
        widths = [cells(a, b) + held(i) for i, (a, b) in enumerate(rws)]   # (the name on every card's first row)
        c = 0
        if len(rws) > 1:
            mean = sum(widths) / len(widths)
            c += sum((x - mean) ** 2 for x in widths) * 0.5
            for a, b in rws:
                if b - a == 1:
                    c += 60 if len(texts[a]) < 8 else 20   # a lone word on a row of its own
        letters = sum(len(" ".join(texts[a:b])) for a, b in rws)
        if rws[-1][1] - rws[0][0] == 1 and n > 1:
            c += 150                               # a page of one word
        if end < n:
            c += 0 if preferred == end else boundary_penalty(words, end) * 3
            if texts[end - 1][:1].isupper() and texts[end][:1].isupper() and not texts[end - 1].endswith((".", "?", "!", ",")):
                c += 150                                # a name cut between two cards
            if letters < 12:
                c += (12 - letters) ** 2 * 6     # a page of a word or two
        return c

    # the fewest pages first (Luiz, 2026-10-18: the fewest and fullest cues - a phrase is never
    # given a page of its own to keep it whole), then the score: where pages and rows break,
    # balance, lone words
    PAGE = 50
    best = [None] * (n + 1)
    best[n] = ((0, 0.0), [])
    for s in range(n - 1, -1, -1):
        choices = []
        for e, opts in page_from(s, rows, 0).items():
            if best[e] is None:
                continue
            if any(f in forced for f in range(s + 1, e)):
                continue
            rc, rws = min(((rc + page_score(rws, e, s == 0), rws) for rc, rws in opts), key=lambda x: x[0])
            score = (best[e][0][0] + 1, best[e][0][1] + PAGE + rc)
            choices.append((score, [list(rws)] + best[e][1]))
        if choices:
            best[s] = min(choices, key=lambda x: x[0])
    if best[0] is None:
        raise ValueError("a word does not fit the row")
    return best[0][1]


def regroup(rows_flat, rows, texts, forced=(), preferred=None):
    """Pages of at most `rows` rows over a fixed row sequence (the plain three-row layout over
    the two-row one's rows): fewest pages, then page breaks at sentence ends."""
    words = [(t + " ", 0) for t in texts]
    m = len(rows_flat)
    forced = set(forced)
    best = [None] * (m + 1)
    best[m] = ((0, 0), [])
    for s in range(m - 1, -1, -1):
        ch = []
        for e in range(s + 1, min(m, s + rows) + 1):
            if any(rows_flat[j][0] in forced for j in range(s + 1, e)):
                break
            if best[e] is None:
                continue
            end = rows_flat[e - 1][1]
            pen = 0 if (e == m or preferred == end) else boundary_penalty(words, end)
            ch.append(((best[e][0][0] + 1, best[e][0][1] + pen), [rows_flat[s:e]] + best[e][1]))
        if ch:
            best[s] = min(ch, key=lambda x: x[0])
    return best[0][1]
