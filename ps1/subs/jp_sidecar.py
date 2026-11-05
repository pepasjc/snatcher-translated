# -*- coding: utf-8 -*-
"""The Japanese under every subtitle card, beside its English, for review.

    python ps1/subs/jp_sidecar.py            # every bank
    python ps1/subs/jp_sidecar.py B230 B220  # these

Writes, per bank, work/subs_ref/<bank>.json ({cue id: Japanese}) and
work/subs_ref/<bank>.txt - one line per card:

    B230_h_01      Harry      | ああ、ギリアンか。 わしも歳をとってしまった。 | Ah... Gillian, is it. ...

The Japanese is the ASR transcript (work/ts_cache.json, faster-whisper
medium with the game vocabulary - a transcript, not the script: names
and rare words come out wrong now and then) of the stream's segments
that overlap the card's sector span (the stream and its rate from
work/master_lines.json). Fix the English in ps1/translation/subs_<bank>.json
(the `en` field - the JSON is the shipped data); work/subs_ref/ is scratch
and never committed (Japanese text).
"""
import argparse, glob, json, os, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
TR = os.path.join(ROOT, 'ps1', 'translation')
OUT = os.path.join(WORK, 'subs_ref')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('banks', nargs='*')
    a = ap.parse_args()
    census = json.load(open(os.path.join(WORK, 'master_lines.json'), encoding='utf-8'))
    ts = json.load(open(os.path.join(WORK, 'ts_cache.json'), encoding='utf-8'))
    os.makedirs(OUT, exist_ok=True)
    paths = sorted(glob.glob(os.path.join(TR, 'subs_B*.json')))
    if a.banks:
        paths = [p for p in paths if os.path.basename(p)[5:9] in a.banks]
    for p in paths:
        bank = os.path.basename(p)[5:9]
        cues = json.load(open(p, encoding='utf-8'))['cues']
        ref, lines = {}, []
        for c in cues:
            jp = ''
            for x in census:
                if x['ch'] == c['chan'] and x['file'] == c['file'] and x['start'] <= c['start'] <= x['end']:
                    rate = (x['end'] - x['start']) / x['dur'] if x.get('dur') else (150 if x.get('stereo') else 75)
                    segs = ts.get(x['key'], [])
                    segs = segs if isinstance(segs, list) else segs.get('segments', [])
                    t0, t1 = (c['start'] - x['start']) / rate, (c['end'] - x['start']) / rate
                    jp = ' '.join(s['text'].strip() for s in segs if s['end'] > t0 + 0.2 and s['start'] < t1 - 0.2)
                    break
            ref[c['id']] = jp
            lines.append(f"{c['id']:16s} {str(c.get('speaker', '')):10s} | {jp} | {c['en']}")
        json.dump(ref, open(os.path.join(OUT, f'{bank}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        open(os.path.join(OUT, f'{bank}.txt'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
        print(f'{bank}: {len(cues)} cards, {sum(1 for v in ref.values() if v)} with Japanese')


if __name__ == '__main__':
    main()
