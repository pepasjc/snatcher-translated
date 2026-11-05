# -*- coding: utf-8 -*-
"""Merge auto-split cue fragments back into their original cues.

split_long.py cuts an over-long cue into timed sub-cues (id + b, bb, ...).
When the text is then reworded, the old cut points are wrong - and a second
split pass compounds them into bad breaks. This undoes the splitting so a
rewrite starts from whole lines; run split_long.py again afterwards.

  python ps1/subs/merge_cues.py B020
"""
import json, re, sys

for scene in sys.argv[1:]:
    p = f'ps1/translation/subs_{scene}.json'
    d = json.load(open(p, encoding='utf-8'))
    out = []
    for c in d['cues']:
        base = re.sub(r'[b-z]+$', '', c['id'])
        if out and re.sub(r'[b-z]+$', '', out[-1]['id']) == base and c['id'] != base:
            prev = out[-1]
            prev['en'] = (prev['en'] + ' ' + c['en']).strip()
            prev['end'] = c['end']
            prev['id'] = base
            continue
        out.append(dict(c))
    print(f'{scene}: {len(d["cues"])} -> {len(out)} cues')
    d['cues'] = out
    json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
