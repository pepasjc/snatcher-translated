"""Where a subtitle's text breaks into cards (pages), the same on every port.

    import cardplan
    cards = cardplan.plan(words, fits)         # [(a, b), ...] word ranges, one per card

`fits(a, b)` answers whether words[a:b] fit one card (rows filled greedily inside
it: the caller lays the rows). The rules (Luiz, 2026-11-05):

- a card holds as many whole sentences as fit;
- a sentence that does not fit in what is left of the card opens the next card
  ("...training. I want|you to put those talents..." was the bug: never end a card
  with the first words of the next sentence);
- a sentence longer than a card splits into the fewest cards, as even in length as
  possible, preferring a clause end (, ; : -), then a phrase opener ("and", "that",
  "to", "in"... never right after "the", "a", "of"), then any word;
- no widow: a sentence that would leave one word alone on the next card moves the
  break back a few words, to a phrase start when there is one;
- `forced` word indices (a numbered item) open a card.
"""

import re

BULLET = re.compile(r"^\(?\d{1,2}[.)]$")
ABBREV = {"mr.", "mrs.", "ms.", "dr.", "mk.", "st.", "jr.", "sr.", "vs.", "no.", "lt.", "sgt.", "capt.", "prof."}
QUOTES = "\"')" + chr(0x2019) + chr(0x201d)
OPENERS = {"and", "but", "or", "nor", "so", "yet", "that", "which", "who", "whom", "whose", "where",
           "when", "while", "because", "if", "unless", "until", "after", "before", "since", "though",
           "although", "as", "than", "to", "in", "on", "at", "for", "with", "without", "from", "of",
           "by", "about", "into", "through", "over", "under", "between", "during", "using", "like"}
BINDERS = {"the", "a", "an", "of", "to", "in", "on", "at", "for", "with", "from", "by", "my", "your",
           "his", "her", "its", "our", "their", "this", "that", "these", "those", "and", "or", "but"}


def sentence_end(word):
    w = word.rstrip(QUOTES)
    return (w.endswith((".", "!", "?", "…")) and w.lower() not in ABBREV
            and not (len(w) == 2 and w[0].isalpha()))          # an initial ("J.")


def clause_end(word):
    return sentence_end(word) or word.rstrip(QUOTES).endswith((",", ";", ":", "-", "—"))


def phrase_start(prev, word):
    """A word a card may open with: a phrase opener after a word that does not bind
    to what follows."""
    return word.lower() in OPENERS and prev.lower().strip(",") not in BINDERS


def bullets(words):
    """Indices of the numbers that open a numbered item ("1. Skull size. 2. ..."): a lone
    number after a finished sentence or a colon, counting on from the last one (a list
    can start mid-text when a cue chain picks it up), never after "number"/"no"."""
    out, expected = set(), None
    for i, w in enumerate(words):
        if not BULLET.match(w):
            continue
        value = int(w.strip("().").rstrip(")"))
        prev = words[i - 1] if i else ""
        if (i == 0 or (prev.endswith((".", ":", "!", "?")) and prev.lower().rstrip(".") not in {"number", "no"}))                 and (expected is None or value in (1, expected)):
            if i:
                out.add(i)
            expected = value + 1
    return out


def plan(words, fits, forced=()):
    n = len(words)
    nums = bullets(words)
    if words and BULLET.match(words[0]):
        nums.add(0)          # a chain that opens on its item number ("3. The height...")
    forced = set(forced) | (nums - {0})

    def spans(a, b, ends):
        out, s = [], a
        for i in range(a, b):
            if i + 1 == b or ends(i) or (i + 1) in forced:
                out.append((s, i + 1))
                s = i + 1
        return out

    def length(a, b):
        return len(" ".join(words[a:b]))

    def units(a, b):
        """[a, b) as card-sized pieces. A sentence that fits is one piece; a longer one
        splits into the fewest pieces that fit, as even in length as the breaks allow
        (sum of squared lengths), a break costing nothing after a clause end, a little
        before a phrase opener and most anywhere else - so "...a full-scale invasion|
        of the world." becomes "Our experiment in this city will|become a full-scale
        invasion of the world."."""
        if fits(a, b) or b - a == 1:
            return [(a, b)]
        total = length(a, b) ** 2

        def penalty(k):                        # a break before word k
            if k in forced or clause_end(words[k - 1]):
                return 0
            if phrase_start(words[k - 1], words[k]):
                return total * 0.1
            return total * 0.25

        best = {a: (0, 0.0, None)}             # end -> (cards, cost, previous end)
        for j in range(a + 1, b + 1):
            for i in range(a, j):
                if i not in best or not fits(i, j):
                    continue
                cards, cost, _ = best[i]
                cand = (cards + 1, cost + length(i, j) ** 2 + (penalty(i) if i > a else 0), i)
                if j not in best or cand[:2] < best[j][:2]:
                    best[j] = cand
        if b not in best:                      # a single word wider than a card
            return [(w, w + 1) for w in range(a, b)]
        out, j = [], b
        while j != a:
            i = best[j][2]
            out.append((i, j))
            j = i
        return out[::-1]

    pieces, opens = [], set()
    # an item number is never a sentence of its own: "3." at a chain's start
    # ended a 'sentence', the item's long sentence then opened a card of its
    # own and the player got "3." alone on a card for a quarter second (B210)
    for s in spans(0, n, lambda i: sentence_end(words[i]) and i not in forced and i not in nums):   # "4." opens its item
        us = units(*s)
        if len(us) > 1:
            opens.add(us[0][0])          # a sentence split over cards starts on a card of its own
        pieces += us
    cards = []
    for a, b in pieces:
        if cards and a not in forced and a not in opens and fits(cards[-1][0], b):
            cards[-1] = (cards[-1][0], b)
        else:
            cards.append((a, b))
    for i in range(len(cards) - 1):                       # no widow
        (a, b), (_, e) = cards[i], cards[i + 1]
        if e - b > 1 or b - a < 3 or clause_end(words[b - 1]) or b in forced:
            continue
        ks = sorted(range(max(a + 1, b - 3), b), key=lambda k: (not phrase_start(words[k - 1], words[k]), b - k))
        for k in ks:
            if fits(a, k) and fits(k, e):
                cards[i], cards[i + 1] = (a, k), (k, e)
                break
    return cards
