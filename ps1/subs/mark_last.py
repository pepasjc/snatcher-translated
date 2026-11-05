# -*- coding: utf-8 -*-
"""Mark each conversation's final cue from a real playthrough log.

A conversation boundary is a PAUSE - the player picks the next menu item -
and that is invisible on disc: the autopsy's hair, flesh and stomach blocks
are contiguous sectors, so sector gaps cannot find them. Frame gaps between
draws in work/subs_watch.txt can.

  python ps1/subs/mark_last.py B020 [gap_frames]

Reads the watcher log, finds the frame each cue was drawn, and flags a cue
`last` when the next cue drew more than gap_frames later (default 240 = 4 s).
"""
import json, sys

scene = sys.argv[1]
gap = int(sys.argv[2]) if len(sys.argv) > 2 else 240

draws = []
for line in open('work/subs_watch.txt', encoding='utf-8', errors='replace'):
    if not line.startswith('D,'):
        continue
    p = line.strip().split(',')
    try:
        f, cue = int(p[1]), int(p[2].split('=')[1])
    except (IndexError, ValueError):
        continue
    if cue == 0xFFFFFFFF:
        continue
    draws.append((f, cue))

p = f'ps1/translation/subs_{scene}.json'
d = json.load(open(p, encoding='utf-8'))
cues = [c for c in d['cues'] if c.get('enabled', True)]
blank = len(cues)                      # the builder appends the blank cue

# the last real line before each pause (a draw of the blank cue is a clear,
# so it marks a boundary too, but the line before it is what we flag)
marks, prev = set(), None
for f, cue in draws:
    if cue == blank:
        if prev is not None:
            marks.add(prev)
        prev = None
        continue
    if prev is not None and prev != cue:
        pass
    prev_f = f
    prev = cue
for i in range(len(draws) - 1):
    f, cue = draws[i]
    nf, ncue = draws[i + 1]
    if cue != blank and nf - f > gap:
        marks.add(cue)
if draws:
    marks.add(max(c for _, c in draws if c != blank))

seen = 0
for c in d['cues']:
    c.pop('last', None)
for i, c in enumerate(cues):
    if i in marks:
        c['last'] = True
        seen += 1
json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'{scene}: {len(draws)} draws, {seen} conversation ends marked:',
      [c['id'] for c in cues if c.get('last')])
