# -*- coding: utf-8 -*-
"""Append cues for newly transcribed streams to an existing scene JSON.

Usage: import and call add(bank, spec) where spec is
    [(xa, chan, file, [(t0, t1, speaker, ja, en, *flags), ...]), ...]

Timestamps are seconds inside the stream; they are converted with that
stream's own sector rate (span / true wav duration), never a constant - a
mono/stereo rate mix-up put a whole B080 reel at half its offsets once.
Existing cues are preserved and the file is re-sorted by stream then sector.
"""
import json, os, wave
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

_idx = None


def _index():
    global _idx
    if _idx is None:
        _idx = {}
        for line in open(os.path.join(ROOT, 'work/snatcher_jp.idx'),
                         encoding='utf-8', errors='replace'):
            if '|Type:XA|' not in line:
                continue
            p = dict(kv.split(':', 1) for kv in line.strip().split('|') if ':' in kv)
            name = p['ID'].split('/')[-1]
            xa = 'M' if 'M000' in name else 'S'
            a, b = p['Sectors'].split('-')
            _idx[(xa, int(p['Channel']), int(p['File']))] = {
                'wav': os.path.join(ROOT, 'work/xa_all/SND/XAS', name + '.wav'),
                'start': int(a), 'end': int(b)}
    return _idx


def rate_of(xa, ch, f):
    e = _index()[(xa, ch, f)]
    w = wave.open(e['wav'])
    dur = w.getnframes() / w.getframerate()
    return (e['end'] - e['start']) / dur, e['start'], e['end']


def add(bank, spec, options=None):
    p = os.path.join(ROOT, f'ps1/translation/subs_{bank}.json')
    d = json.load(open(p, encoding='utf-8'))
    ja_p = os.path.join(ROOT, f'work/subs_ref/{bank}.json')
    ja = json.load(open(ja_p, encoding='utf-8')) if os.path.exists(ja_p) else {}
    have = {(c['chan'], c['file'], c['start']) for c in d['cues']}
    n = 0
    used = {c['id'] for c in d['cues']}
    for (xa, ch, fi, rows) in spec:
        rate, base, limit = rate_of(xa, ch, fi)
        for i, row in enumerate(rows):
            t0, t1, sp, jp, en = row[:5]
            flags = row[5:]
            start = min(base + round(t0 * rate), limit)
            end = min(base + round(t1 * rate), limit)
            if (ch, fi, start) in have:
                continue
            k = 0
            while f'{bank}_f{fi}_{i}{chr(97+k) if k else ""}' in used:
                k += 1
            cid = f'{bank}_f{fi}_{i}{chr(97+k) if k else ""}'
            used.add(cid)
            c = {'id': cid, 'file': fi, 'chan': ch, 'start': start, 'end': end,
                 'dur': round(t1 - t0, 1), 'speaker': sp, 'en': en,
                 'enabled': True}
            if 'last' in flags:
                c['last'] = True
            d['cues'].append(c)
            ja[cid] = jp
            n += 1
    d['cues'].sort(key=lambda c: (c['chan'], c['file'], c['start']))
    if options:
        d.setdefault('options', {}).update(options)
    json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.makedirs(os.path.dirname(ja_p), exist_ok=True)
    json.dump(ja, open(ja_p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'{bank}: +{n} cues, {len(d["cues"])} total')
    return n
