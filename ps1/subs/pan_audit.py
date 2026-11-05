# -*- coding: utf-8 -*-
"""Audit speaker labels on the stereo reels by where each voice is panned.

    python ps1/subs/pan_audit.py                 # every subtitled bank
    python ps1/subs/pan_audit.py B200 B230       # some banks
    python ps1/subs/pan_audit.py --all           # print every cue, not just the suspects

The XAS_S000 reels mix each voice to the side of the screen its face sits
on: in B200's morgue Metal (right slot) reads at an L/R rms ratio of
0.5-0.7, Randam (centre) at ~1.0 and Gillian (left) at 1.7-2.9, and that
map put a dozen mislabelled cards right (BUG-049). Whisper cannot tell the
voices apart, so the labels were guessed from the words.

Per reel, each cue's balance is measured over its sector span (half-second
windows, quiet ones dropped) and classed L / C / R; then every speaker's
majority class in that reel is taken as that speaker's seat, and a cue
whose class disagrees with its speaker's seat is a suspect. A reel where
two speakers share a seat, or a speaker has no clear seat, is reported as
unresolved rather than judged. Mono lines carry no information and are
skipped.
"""
import argparse, glob, json, os, re, sys, wave
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

IDX = os.path.join(WORK, 'snatcher_jp.idx')
WAVS = os.path.join(WORK, 'xa_all', 'SND', 'XAS')
RATE = 150                         # sectors per second, stereo reels
QUIET = 800                        # rms below this: no voice in the window
LEFT, RIGHT = 1.35, 0.8            # L/R ratio thresholds (B200 morgue)


def reels():
    """(chan, file) -> (jpsxdec index, first sector, last sector) for XAS_S000."""
    out = {}
    for line in open(IDX, encoding='utf-8', errors='replace'):
        m = re.match(r'#:\d+\|ID:SND/XAS/XAS_S000\.XA\[(\d+)\]\|Sectors:(\d+)-(\d+)\|.*\|File:(\d+)\|Channel:(\d+)\|', line)
        if m:
            out[(int(m.group(5)), int(m.group(4)))] = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return out


def load(i):
    w = wave.open(os.path.join(WAVS, f'XAS_S000.XA[{i}].wav'))
    if w.getnchannels() != 2:
        return None, None
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2).astype(float)
    return w.getframerate(), x


def classes(x, r, t0, t1):
    """Per half-second L/R class string over [t0, t1) seconds."""
    s = ''
    for t in np.arange(t0, t1, 0.5):
        a, b = int(t * r), int(min(t + 0.5, t1) * r)
        if b - a < r // 10 or b > len(x):
            break
        l = np.sqrt((x[a:b, 0] ** 2).mean()); rr = np.sqrt((x[a:b, 1] ** 2).mean())
        if l < QUIET and rr < QUIET:
            s += '.'
        else:
            k = l / (rr + 1)
            s += 'L' if k > LEFT else ('R' if k < RIGHT else 'C')
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('scenes', nargs='*')
    ap.add_argument('--all', action='store_true', help='print every cue, not only the suspects')
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(ROOT, 'ps1', 'translation', 'subs_*.json')))
    if a.scenes:
        files = [f for f in files if os.path.basename(f)[5:-5] in a.scenes]
    idx = reels()
    suspects = 0
    for f in files:
        scene = os.path.basename(f)[5:-5]
        cues = json.load(open(f, encoding='utf-8'))['cues']
        groups = {}
        for c in cues:
            if c.get('enabled', True) and (c['chan'], c['file']) in idx and c['chan'] != 254:
                groups.setdefault((c['chan'], c['file']), []).append(c)
        for key, cs in sorted(groups.items()):
            i, first, last = idx[key]
            r, x = load(i)
            if x is None:
                continue
            rows = []
            for c in cs:
                t0, t1 = (c['start'] - first) / RATE, (c['end'] - first) / RATE
                s = classes(x, r, t0, t1)
                voiced = s.replace('.', '')
                cls = max('LCR', key=voiced.count) if voiced else '?'
                if voiced and voiced.count(cls) < 0.6 * len(voiced):
                    cls = '~'                        # mixed: the cue straddles two voices
                rows.append((c, t0, t1, s, cls))
            seats = {}
            for c, t0, t1, s, cls in rows:
                if cls in 'LCR':
                    seats.setdefault(c['speaker'], []).append(cls)
            seat = {sp: max('LCR', key=v.count) for sp, v in seats.items()}
            clear = {sp for sp, v in seats.items() if v.count(seat[sp]) >= 0.6 * len(v) and len(v) >= 2}
            shared = len(set(seat[sp] for sp in clear)) < len(clear)
            head = f'{scene} S000 ch{key[0]} f{key[1]} [{i}] {len(cs)} cues  seats ' + \
                   ' '.join(f'{sp}={seat[sp]}{"" if sp in clear else "?"}' for sp in seat) + \
                   ('  (shared seat: unresolved)' if shared else '')
            printed = False
            for c, t0, t1, s, cls in rows:
                sp = c['speaker']
                bad = (not shared) and sp in clear and cls in 'LCR' and cls != seat[sp]
                if bad:
                    suspects += 1
                if bad or a.all:
                    if not printed:
                        print(head); printed = True
                    print(f"  {'!!' if bad else '  '} {c['id']:16s} {t0:6.1f}-{t1:6.1f} {sp:8s} {cls} {s:20s} {c['en'][:48]}")
            if not printed and (shared or a.all):
                print(head)
    print(f'{suspects} suspect cue(s)')


if __name__ == '__main__':
    main()
