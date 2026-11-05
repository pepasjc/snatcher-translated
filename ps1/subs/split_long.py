# -*- coding: utf-8 -*-
"""Split any cue whose text needs more rows than the scene's box has into
sequential timed sub-cues at word boundaries (sentence-end preferred).

  python ps1/subs/split_long.py B0C0 B0D0 ...
"""
import json, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
from subs_cue import wrap_only, CODES_PER_ROW as COLS


def fits(t, rows, cols=COLS):
    try:
        wrap_only(t, rows, cols)
        return True
    except SystemExit:
        return False


def split_text(t, rows, cols=COLS):
    """Return a list of pieces that each fit."""
    if fits(t, rows, cols):
        return [t]
    words = t.split()
    best = None
    for cut in range(len(words) - 1, 1, -1):
        a = ' '.join(words[:cut])
        if fits(a, rows, cols):
            if a.endswith(('.', '!', '?', '-', ':')):
                best = cut
                break
            if best is None:
                best = cut
    a = ' '.join(words[:best])
    rest = ' '.join(words[best:])
    return [a] + split_text(rest, rows, cols)


for scene in sys.argv[1:]:
    p = f'ps1/translation/subs_{scene}.json'
    d = json.load(open(p, encoding='utf-8'))
    rows = d.get('options', {}).get('rows', 3)
    cols = d.get('options', {}).get('cols', COLS)   # cells; narrower layouts wrap sooner
    out = []
    for c in d['cues']:
        pieces = split_text(c['en'], rows, cols)
        if len(pieces) == 1:
            out.append(c)
            continue
        n = len(pieces)
        for i, piece in enumerate(pieces):
            cc = dict(c)
            cc['en'] = piece
            cc['start'] = c['start'] + (c['end'] - c['start']) * i // n
            cc['end'] = c['start'] + (c['end'] - c['start']) * (i + 1) // n
            if i:
                # suffix from the ORIGINAL id, so re-splitting an already
                # split cue cannot mint a duplicate (B020_022b twice)
                base = c['id'].rstrip('abcdefghijklmnopqrstuvwxyz')
                tail = c['id'][len(base):]
                cc['id'] = base + tail + chr(ord('b') + i - 1)
            out.append(cc)
        print(f"{scene} {c['id']}: split into {n}")
    d['cues'] = out
    json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
