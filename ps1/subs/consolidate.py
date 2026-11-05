# -*- coding: utf-8 -*-
"""Re-cut each spoken line's cards so that as much as fits shares one card,
and what does not fit is cut at a sentence or clause end.

    python ps1/subs/consolidate.py                # every bank, report only
    python ps1/subs/consolidate.py --write        # rewrite the cue files
    python ps1/subs/consolidate.py B220 -v --write

split_long.py cut every card that overran rows x cols into timed pieces
at the last word that fit, measuring cells with the old pair table where
a rare pair cost two - so the player saw 'For that too, we mustn't let
the Chief reach the summit' and then 'venue.' on a card of its own, and
"If creatures like these take over the town, there'll be" / "nothing
left to do." (Luiz, 2026-09-12: one card holding more text for longer is
better "as long as it fits nicely in the dialog and is part of the same
conversation").

A CHAIN is a run of consecutive cards with the same speaker and stream
(file, channel), both enabled, under GAP sectors apart, up to and
including a `last` card. Its text is joined and re-cut: whole if it fits
rows x cols at the cue's width AND at 18 (the plain layout's wrap; only
the bank's width when it is not `fullwidth`); otherwise the longest
card that fits, broken where lib/cardplan.py says (whole sentences a card,
then clause, phrase, word; no widow). Cells are
counted as they will be once every pair has a glyph (rebuild_pairs.py
after this). Ids are the first card's with b, c... suffixes; `by_ear` and
`last` carry over (last on the final piece). Timing: a new piece starts
where its first character sat in the original piece that held it, so the
ASR's per-sentence times survive a re-cut.
"""
import argparse, glob, json, os, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from subs_cue import CODES_PER_ROW

TR = os.path.join(ROOT, 'ps1', 'translation')
GAP = 60                 # sectors between the pieces (0.4 s stereo, 0.8 s mono)
SENTENCE = ('.', '!', '?', '…')
CLAUSE = (',', ';', ':', '-')


def ideal_cells(text):
    """Cells a row takes once EVERY pair has a glyph: two ASCII characters
    a cell, a lone one padded, a fullwidth character one."""
    cells, run = 0, 0
    for ch in text:
        if ord(ch) < 0x80:
            run += 1
        else:
            cells += (run + 1) // 2 + 1
            run = 0
    return cells + (run + 1) // 2


def wrap(text, cols):
    out = []
    for para in text.split(chr(10)):
        words, line = para.split(), ""
        for w in words:
            cand = (line + " " + w).strip()
            if ideal_cells(cand) <= cols:
                line = cand
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def fits(text, rows, widths):
    return all(len(wrap(text, w)) <= rows and all(ideal_cells(r) <= w for r in wrap(text, w)) for w in widths)


def ends_with(word, marks):
    return word.rstrip("'\")").endswith(marks)


def cut(text, rows, widths):
    """Pieces that each fit, broken where lib/cardplan.py says (whole sentences a card,
    then clause, phrase, word; no widow) - the same rule as the PC Engine's cards."""
    import cardplan
    words = text.split()
    cards = cardplan.plan(words, lambda a, b: fits(' '.join(words[a:b]), rows, widths))
    return [' '.join(words[a:b]) for a, b in cards]


def chains(cues):
    out, cur = [], []
    for c in cues:
        if cur:
            a = cur[-1]
            joinable = (a.get('speaker') == c.get('speaker') and a['chan'] == c['chan'] and a['file'] == c['file']
                        and a.get('enabled', True) and c.get('enabled', True) and not a.get('last')
                        and a['chan'] != 254 and c['chan'] != 254 and a.get('cols') == c.get('cols')
                        and 0 <= c['start'] - a['end'] <= GAP)
            if not joinable:
                out.append(cur)
                cur = []
        cur.append(c)
    if cur:
        out.append(cur)
    return out


def recut(chain, rows, bank_cols, fullwidth):
    cols = min(chain[0].get('cols', bank_cols), CODES_PER_ROW)
    widths = {cols} | ({CODES_PER_ROW} if fullwidth else set())
    text = ' '.join(c['en'].strip() for c in chain)
    pieces = cut(text, rows, widths)
    if len(pieces) == len(chain) and all(p == c['en'].strip() for p, c in zip(pieces, chain)):
        return None                                    # nothing changes
    start, end = chain[0]['start'], chain[-1]['end']
    # Timing stays anchored to the ORIGINAL pieces: each of them is an ASR
    # segment with its own start, and the joined text's character offsets
    # map onto them. A new piece starts where its first character sat in
    # the old piece that held it (interpolated inside that piece). The
    # first cut of this tool shared the chain's span out in proportion to
    # text length instead, and a chain ending in silence pushed every
    # later sentence seconds late (Madnar's 'I have Dr. Lorraine in my
    # keeping...' in B230, Luiz).
    spans, at_char = [], 0
    for c in chain:
        t = c['en'].strip()
        spans.append((at_char, at_char + len(t), c['start'], c['end']))
        at_char += len(t) + 1
    def sector_at(o):
        for a, b, s0, s1 in spans:
            if a <= o <= b:
                return s0 + round((s1 - s0) * (o - a) / max(1, b - a))
        return end
    out, o = [], 0
    for i, p in enumerate(pieces):
        at = start if i == 0 else sector_at(o)
        o_next = o + len(p) + 1
        nxt = end if i == len(pieces) - 1 else sector_at(o_next)
        c = dict(chain[0])
        c['id'] = chain[0]['id'] + ('' if i == 0 else chr(ord('a') + i) if i < 26 else f'x{i}')
        c['start'], c['end'], c['en'] = at, nxt, p
        c['dur'] = round(sum(x.get('dur', 0) for x in chain) * len(p) / max(1, sum(len(q) for q in pieces)), 1)
        o = o_next
        c.pop('last', None)
        if i == len(pieces) - 1 and any(x.get('last') for x in chain):
            c['last'] = True
        if any(x.get('by_ear') for x in chain):
            c['by_ear'] = True
        out.append(c)
        at = nxt
    return out


def consolidate(doc, report):
    opts = doc.get('options', {})
    rows = opts.get('rows', 3)
    bank_cols = min(opts.get('cols', CODES_PER_ROW), CODES_PER_ROW)
    fullwidth = opts.get('fullwidth', True)
    out, changed = [], 0
    for chain in chains(doc['cues']):
        new = recut(chain, rows, bank_cols, fullwidth)
        if new is None:
            out.extend(chain)
            continue
        changed += 1
        report.append(([c['id'] for c in chain], [c['en'] for c in new]))
        out.extend(new)
    seen = set()
    for c in out:                                      # a re-cut chain's suffix ids must stay unique
        while c['id'] in seen:
            c['id'] += '2'
        seen.add(c['id'])
    doc['cues'] = out
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('banks', nargs='*')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()
    paths = sorted(glob.glob(os.path.join(TR, 'subs_B*.json')))
    if a.banks:
        paths = [p for p in paths if os.path.basename(p)[5:9] in a.banks]
    total = 0
    for p in paths:
        raw = open(p, encoding='utf-8', newline='').read()
        nl = '\r\n' if '\r\n' in raw else '\n'
        doc = json.loads(raw)
        before = len(doc['cues'])
        report = []
        n = consolidate(doc, report)
        total += n
        if n:
            print(f'{os.path.basename(p)[5:9]}: {before} -> {len(doc["cues"])} cues ({n} chains re-cut)')
            for ids, texts in (report if a.verbose else report[:3]):
                print(f'    {"+".join(ids)} -> ' + ' | '.join(repr(t[:60]) for t in texts))
            if a.write:
                open(p, 'w', encoding='utf-8', newline='').write((json.dumps(doc, ensure_ascii=False, indent=1) + '\n').replace('\n', nl))
    print(f'{total} chains re-cut' + ('' if a.write else ' (dry run; --write to apply)'))


if __name__ == '__main__':
    main()
