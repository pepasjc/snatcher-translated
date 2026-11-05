# -*- coding: utf-8 -*-
"""Lint a scene's cue file before spending an emulator run on it.

    python ps1/subs/check_cues.py ps1/translation/subs_B0C0.json
    python ps1/subs/check_cues.py ps1/translation/subs_*.json --quiet

Catches, offline, the mistakes that otherwise cost a play-test:

  * a card that does not fit rows x cols - measured in CELLS, not
    characters, because packed pairs cost one cell for two letters and the
    rare fallback pairs cost one each. A row that overflows makes the
    engine wrap it itself and pushes the row after it out of the box.
  * two cues overlapping on the same (chan, file): the matcher takes the
    first, so the second silently never draws.
  * cues out of order inside a stream, or a zero/negative span.
  * a chain cue (chan 254) whose anchor id does not exist.
  * a speaker name too long for the nameplate.
  * a cue whose sector range falls outside its stream's range, or names a
    (chan, file) no stream has - checked against the census when
    work/master_lines.json is present.
  * a blob whose string data will not fit the 48 KB HIRAM budget.
  * a card that repeats the previous card's text, or runs past ~25
    characters a second: whisper's repetition loop leaves a sentence
    carded two or three times, the repeats 0.4-1 s long, and the player
    sees cards flash by (the morgue reel, 2026-09-12). Needs the census
    for the stream's rate.

Exit status is non-zero when anything is reported as an error, so it can
sit in a build script. Warnings alone exit 0.
"""
import argparse, glob, json, os, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
CHAIN_CHAN = 254                 # frame-timed cue on a VAG line, no stream
MASTER = os.path.join(ROOT, 'work', 'master_lines.json')


def load_subs_cue(scene):
    """subs_cue picks its scene off argv at import time."""
    sys.argv = [sys.argv[0], 'on', 'x', '--scene', scene]
    import subs_cue
    return subs_cue


def census():
    if not os.path.exists(MASTER):
        return None
    return json.load(open(MASTER, encoding='utf-8'))


def check(path, streams, quiet=False):
    doc = json.load(open(path, encoding='utf-8'))
    scene = doc.get('scene') or os.path.basename(path)[5:-5]
    S = load_subs_cue(scene)
    opts = doc.get('options', {})
    rows = opts.get('rows', 3)
    cols = min(opts.get('cols', S.CODES_PER_ROW), S.CODES_PER_ROW)
    cues = doc.get('cues', [])
    errs, warns = [], []

    def fit(text, r, c):
        try:
            S.wrap_only(text, r, c)
            return None
        except SystemExit as e:
            return str(e)

    if 'menu_word' not in opts and not opts.get('intro'):
        warns.append('no menu_word: the build falls back to 0x8701 (B010\'s). '
                     'Fine if the scene really uses that window; otherwise read '
                     'the scene\'s verb-menu window low16 off the running game - '
                     'guessing it lost B020\'s text twice')

    if opts.get('intro'):
        # the opening's per-card placement (gen_intro.py place): rows move
        # down by `y` from 173/189/205, and the last row's cell must end by
        # line 228 (overscan). A card re-worded to more rows after it was
        # placed keeps its old y and runs off the screen (news_03/news_07,
        # 2026-11-05: 'continent.' and 'biohazard,' cut in half)
        for c in cues:
            if 'y' not in c or c.get('enabled', True) is False:
                continue
            try:
                n = S.wrap_only(c.get('en', ''), rows, 18).count(chr(10)) + 1
            except SystemExit:
                continue
            bottom = 173 + c['y'] + 16 * (n - 1) + 12
            if bottom > 228:
                errs.append(f'{c.get("id")}: {n} rows at y {c["y"]} end on line {bottom} - past 228, '
                            f'off the bottom of the screen; y at most {228 - 173 - 16 * (n - 1) - 12}')

    ids, by_stream = {}, {}
    for i, c in enumerate(cues):
        cid = c.get('id', f'#{i}')
        for k in ('id', 'file', 'chan', 'start', 'end', 'speaker', 'en'):
            if k not in c:
                errs.append(f'{cid}: missing field {k!r}')
        if cid in ids:
            errs.append(f'{cid}: duplicate id (also cue #{ids[cid]})')
        ids[cid] = i

        ccols = min(c.get('cols', cols), S.CODES_PER_ROW)
        bad = fit(c.get('en', ''), rows, ccols)
        if bad:
            errs.append(f'{cid}: {bad} - split it into more cards, do not condense')
        for ln in S.wrap_only(c.get('en', ''), rows, ccols).split('\n') if not bad else []:
            if S.cellw(ln) > ccols:
                errs.append(f'{cid}: row {ln!r} is {S.cellw(ln)} cells > {ccols}')
        sp = c.get('speaker', '')
        if len(sp) > S.COLS_NAME:
            errs.append(f'{cid}: speaker {sp!r} is {len(sp)} chars > {S.COLS_NAME}')

        start, end = c.get('start', 0), c.get('end', 0)
        if c.get('chan') == CHAIN_CHAN:
            if c.get('anchor') not in [x.get('id') for x in cues]:
                errs.append(f'{cid}: chain cue anchor {c.get("anchor")!r} does not exist')
            if end <= start:
                errs.append(f'{cid}: chain window {start}..{end} is empty (frames)')
            continue
        if end <= start:
            errs.append(f'{cid}: sector range {start}..{end} is empty')
        by_stream.setdefault((c.get('chan'), c.get('file')), []).append(c)

    for (ch, f), group in sorted(by_stream.items()):
        ordered = sorted(group, key=lambda c: c['start'])
        if [c['id'] for c in ordered] != [c['id'] for c in group]:
            warns.append(f'chan {ch} file {f}: cues are not in sector order')
        # The payload scans the cue table in FILE order and stops at the first
        # cue whose range holds the polled position, so an earlier entry wins
        # every sector the two share. A cue whose whole range is claimed by
        # earlier entries can never draw.
        for i, c in enumerate(group):
            free = [(c['start'], c['end'])]
            for prev in group[:i]:
                cut = []
                for lo, hi in free:
                    if prev['end'] <= lo or prev['start'] >= hi:
                        cut.append((lo, hi))
                        continue
                    if lo < prev['start']:
                        cut.append((lo, prev['start']))
                    if prev['end'] < hi:
                        cut.append((prev['end'], hi))
                free = cut
            if not free:
                owners = ', '.join(p['id'] for p in group[:i]
                                   if p['start'] < c['end'] and p['end'] > c['start'])
                errs.append(f'{c["id"]}: {c["start"]}..{c["end"]} is entirely '
                            f'claimed by earlier cues ({owners}) - it never draws')
            elif free != [(c['start'], c['end'])]:
                spans = ', '.join('%d..%d' % r for r in free)
                warns.append(f'{c["id"]}: {c["start"]}..{c["end"]} overlaps an '
                             f'earlier cue; it can only draw in {spans}')
        if streams is not None:
            # Per cue, not per group: one (chan, file) legitimately covers
            # several streams in different parts of the disc.
            near = [s for s in streams if s['ch'] == ch and s['file'] == f]
            if not near:
                errs.append(f'chan {ch} file {f}: no such stream in the census')
                continue
            for c in ordered:
                hits = [s for s in near
                        if s['start'] <= c['start'] and c['end'] <= s['end'] + 1]
                if not hits:
                    have = ', '.join('%d..%d' % (s['start'], s['end']) for s in near[:4])
                    errs.append(f'{c["id"]}: {c["start"]}..{c["end"]} lies outside '
                                f'every chan {ch} file {f} stream ({have})')
                elif len(hits) > 1:
                    warns.append(f'{c["id"]}: {len(hits)} streams contain '
                                 f'{c["start"]}..{c["end"]} - identity is ambiguous')
                # Reading speed. A card of a full sentence over 0.4 s is not a
                # timing choice, it is whisper's repetition loop: the morgue
                # reel carried the same Metal line three times (4.8 s, then
                # 0.76 s and 1.1 s repeats) and the player saw two cards
                # flash by unreadably (2026-09-12). ~25 chars/s is the top
                # of what a player can follow; a duplicate of the previous
                # card's text is the loop's signature.
                if hits:
                    x = hits[0]              # the stream's own rate: sectors per wall-clock second
                    rate = (x['end'] - x['start']) / x['dur'] if x.get('dur') else (150 if x.get('stereo') else 75)
                    secs = (c['end'] - c['start']) / rate
                    n = len(c.get('en', ''))
                    k = cues.index(c)
                    dup = k and cues[k - 1].get('en') == c.get('en')
                    # a `noband` card is the second half of one card split
                    # where the opening's diagram still starts (STILL_LBA):
                    # the same text on both sides is the design, and the
                    # two spans read as one
                    if dup and c.get('noband'):
                        continue
                    nxt = cues[k + 1] if k + 1 < len(cues) else None
                    if nxt and nxt.get('noband') and nxt.get('en') == c.get('en'):
                        secs += (nxt['end'] - nxt['start']) / rate
                    if dup and n >= 20:
                        errs.append(f'{c["id"]}: same text as the card before it ({c.get("en", "")[:40]!r}) - '
                                    f'an ASR repeat; merge the span into one card')
                    elif dup:
                        warns.append(f'{c["id"]}: same text as the card before it ({c.get("en", "")!r}) - '
                                     f'a real repeat (a shout) or an ASR one')
                    elif n >= 20 and secs > 0 and n / secs > 25:
                        warns.append(f'{c["id"]}: {n} chars in {secs:.1f} s ({n / secs:.0f} chars/s) - unreadable; '
                                     f'an ASR repeat or a mis-cut span')

    # rough blob budget: interned padded blocks, 24 B per cue entry, and
    # whatever the payload code costs (~6 KB at the current revision)
    from sjis_enc import encode
    blob = 24 * len(cues) + 6144
    seen = set()
    for c in cues:
        for text, r, cw in ((c.get('en', ''), rows, min(c.get('cols', cols), S.CODES_PER_ROW)),
                            (c.get('speaker', ''), S.ROWS_NAME, S.COLS_NAME)):
            if text in seen:
                continue
            seen.add(text)
            try:
                blob += len(encode(S.pad_block(text, r, cw))) + 2
            except SystemExit:
                pass
    if blob > S.HIRAM_MAX:
        errs.append(f'blob ~{blob} B exceeds the {S.HIRAM_MAX} B HIRAM budget')
    elif blob > S.HIRAM_MAX * 0.85:
        warns.append(f'blob ~{blob} B of {S.HIRAM_MAX} B - close to the HIRAM budget')

    off = sum(1 for c in cues if not c.get('enabled', True))
    lasts = sum(1 for c in cues if c.get('last'))
    if not quiet or errs or warns:
        print(f'{os.path.basename(path)}: {len(cues)} cues, {len(by_stream)} streams, '
              f'{rows}x{cols}, {lasts} marked last'
              + (f', {off} disabled' if off else ''))
    for w in warns:
        print(f'  warn  {w}')
    for e in errs:
        print(f'  ERROR {e}')
    return len(errs)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('files', nargs='+', help='ps1/translation/subs_*.json')
    ap.add_argument('--quiet', action='store_true', help='print only problems')
    a = ap.parse_args()
    paths = [p for pat in a.files for p in (glob.glob(pat) or [pat])]
    streams = census()
    if streams is None:
        print('note: work/master_lines.json absent - skipping stream cross-checks')
    bad = sum(check(p, streams, a.quiet) for p in sorted(paths))
    if bad:
        raise SystemExit(f'{bad} error(s)')


if __name__ == '__main__':
    main()
