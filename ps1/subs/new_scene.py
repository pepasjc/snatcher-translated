# -*- coding: utf-8 -*-
"""Scaffold a scene's subtitle generator from its ASR segments.

    python ps1/subs/new_scene.py B0C0
    python ps1/subs/new_scene.py B0C0 --streams M:0:7 M:0:8 S:1:3

Writes work/gen_<scene>.py: a LINES table with one entry per stream and one
empty string per ASR segment, timestamps in comments. Fill in the English
and run it; ps1/subs/subgen.py does the timing, the wrapping and the writing of
ps1/translation/subs_<scene>.json.

The segment count is asserted at build time, so the placeholders must stay
one-per-segment. Three ways out when a segment is wrong for the card:

    ['first half', 'second half']   split one segment into timed pieces
    ''                              merge this segment's time into the one before
    (re-transcribe)                 if the ASR itself split badly

The Japanese is printed to the terminal to translate from, and never
written into the generator: generators are committed, and this repository
carries English only.

Prerequisites: work/master_lines.json (ps1/subs/xa_census.py) and
work/ts_cache.json (lib/asr/transcribe_xa.py --words).
"""
import argparse, os, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
TEMPLATE = '''# -*- coding: utf-8 -*-
"""{scene} subtitles: one entry per voice stream, one text per ASR segment.

English only - the Japanese lives in work/ts_cache.json and the sidecar
work/subs_ref/{scene}.json, neither of which is committed.

    python work/gen_{lower}.py        # -> ps1/translation/subs_{scene}.json
"""
import os, sys
import subgen

# ((xa, chan, file), cue id, speaker, [one text per ASR segment])
# A text may be a list of pieces (timed by length) or '' to fold the
# segment's time into the piece before it.
LINES = [
{lines}]

# cue ids whose last card ends a conversation (clears the box)
LAST = []

subgen.build('{scene}', LINES, options={{'menu_word': 0x0000, 'rows': 3}},
             last=LAST)
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('scene', help='bank name, e.g. B0C0')
    ap.add_argument('--streams', nargs='*', default=[],
                    help='extra streams as XA:CHAN:FILE, e.g. M:0:7')
    ap.add_argument('--speaker', default='Gillian', help='placeholder speaker')
    ap.add_argument('-o', '--out', help='default work/gen_<scene>.py')
    ap.add_argument('--force', action='store_true', help='overwrite an existing file')
    a = ap.parse_args()

    import subgen
    extra = []
    for s in a.streams:
        xa, ch, f = s.split(':')
        extra.append((xa, int(ch), int(f)))
    st = subgen.streams(a.scene, extra)
    if not st:
        raise SystemExit(f'no streams for {a.scene}: pass them with --streams, or '
                         f'build an empty ps1/translation/subs_{a.scene}.json first and '
                         f'census the scene under the harness')
    ts = subgen.ensure_ts([it['key'] for _, _, _, it in st])

    out = a.out or os.path.join(ROOT, 'work', f'gen_{a.scene.lower()}.py')
    if os.path.exists(out) and not a.force:
        raise SystemExit(f'{out} exists (use --force to overwrite)')

    body, n = [], 0
    for xa, ch, f, it in st:
        segs = ts.get(it['key'], [])
        dur = subgen.wav_dur(it['key']) if it['key'] else 0
        cid = f'{a.scene}_{n:03d}'
        n += 1
        print(f"\n('{xa}', {ch}, {f})  sectors {it['start']}-{it['end']}  "
              f"wav {dur:.1f}s  -> {cid}")
        body.append(f"    (('{xa}', {ch}, {f}), '{cid}', '{a.speaker}', [")
        if not segs:
            print('    (no segments - re-run the transcriber with NOVAD=1 '
                  'before deciding this stream is silent)')
            body.append("        '',      # NO ASR SEGMENTS - check with NOVAD=1")
        for g in segs:
            print(f"    {g['start']:6.2f}-{g['end']:6.2f}  {g['text']}")
            body.append(f"        '',      # {g['start']:6.2f}-{g['end']:6.2f}")
        body.append('    ]),')
    src = TEMPLATE.format(scene=a.scene, lower=a.scene.lower(),
                          lines='\n'.join(body) + '\n')
    open(out, 'w', encoding='utf-8').write(src)
    print(f'\nwrote {out}: {n} streams, '
          f'{sum(len(ts.get(it["key"], [])) for *_, it in st)} segments to translate')
    print('set menu_word to the scene\'s verb-menu window word before building')


if __name__ == '__main__':
    main()
