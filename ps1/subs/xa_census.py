# -*- coding: utf-8 -*-
"""Build the XA stream census from a jPSXdec index.

Voice-line identity on this disc is `chan<<8 | file` PLUS the absolute
sector range: the same (file, channel) pair is reused all over the disc, so
the range is not optional. jPSXdec's index already knows every stream's
range, so the census is a parse rather than a scan.

    java -jar jpsxdec.jar -f "Snatcher (Japan).bin" -x snatcher_jp.idx
    java -jar jpsxdec.jar -x snatcher_jp.idx -a audio -dir work/xa_all
    python ps1/subs/xa_census.py work/snatcher_jp.idx -o work/master_lines.json

Each entry is {xa, ch, file, start, end, dur, stereo, rate, stride, key},
where `key` is the jPSXdec stream name - which is also the basename of the
WAV it extracts, so the census and the audio join on it.

`dur` is honest wall-clock seconds (span / sectors-per-second at the disc
speed the index reports). The hand-built work/master_lines.json this
replaces carried a `dur` that was 2x too long for every stream; nothing
reads it for timing (subgen measures the WAV), but do not compare the two.
"""
import argparse, json, os, re, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# #:90|ID:SND/XAS/XAS_M000.XA[0]|Sectors:2408-2904|Type:XA|File:1|Channel:0|
# Stereo?:No|Samples/Sec:37800|Bits/Sample:4|Sector stride:16|Disc speed:2x
FIELD = re.compile(r'([^:|]+):([^|]*)')


def parse(path):
    out = []
    for line in open(path, encoding='utf-8', errors='replace'):
        line = line.strip()
        if not line.startswith('#:') or '|Type:XA|' not in line:
            continue
        f = {}
        for part in line.split('|'):
            k, _, v = part.partition(':')
            f[k.strip()] = v.strip()
        sid = f.get('ID', '')
        lo, _, hi = f.get('Sectors', '').partition('-')
        speed = 2 if f.get('Disc speed', '2x').startswith('2') else 1
        start, end = int(lo), int(hi or lo)
        # container = the file the stream lives in, e.g. XAS_M000.XA; `xa` is
        # the letter that tells XAS_M000 from XAS_S000, which is part of a
        # line's identity because the same (file, channel) exists in both.
        container = os.path.basename(sid).partition('[')[0]
        stem = os.path.splitext(container)[0]
        out.append({
            'xa': stem.split('_')[-1][0] if '_' in stem else stem[:1],
            'container': container,
            'ch': int(f.get('Channel', -1)),
            'file': int(f.get('File', -1)),
            'start': start,
            'end': end,
            'dur': round((end - start + 1) / (75.0 * speed), 1),
            'stereo': f.get('Stereo?', 'No').lower().startswith('y'),
            'rate': int(f.get('Samples/Sec', 0)),
            'stride': int(f.get('Sector stride', 0)),
            'key': os.path.basename(sid),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('index', help='jPSXdec .idx file')
    ap.add_argument('-o', '--out', default='work/master_lines.json')
    ap.add_argument('--wav-dir', help='check every stream has an extracted WAV')
    ap.add_argument('--min-dur', type=float, default=0.0,
                    help='drop streams shorter than this (jingles, effects)')
    ap.add_argument('--container', default='',
                    help='keep only streams whose container matches, e.g. XAS_ '
                         '(drops the audio tracks inside the .STR movies)')
    a = ap.parse_args()

    streams = [s for s in parse(a.index)
               if s['dur'] >= a.min_dur and a.container in s['container']]
    if not streams:
        raise SystemExit('no XA streams in the index - is it a jPSXdec index?')

    missing = []
    if a.wav_dir:
        have = set()
        for root, _, files in os.walk(a.wav_dir):
            have.update(os.path.splitext(f)[0] for f in files if f.endswith('.wav'))
        missing = [s['key'] for s in streams if s['key'] not in have]

    by_xa = {}
    for s in streams:
        by_xa.setdefault(s['xa'], []).append(s)
    for xa, group in sorted(by_xa.items()):
        st = sum(1 for s in group if s['stereo'])
        print(f'  {xa}: {len(group)} streams ({st} stereo), '
              f'sectors {min(s["start"] for s in group)}-{max(s["end"] for s in group)}')
    if missing:
        print(f'  WARNING: {len(missing)} streams have no WAV, e.g. {missing[:3]}')

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(streams, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'wrote {a.out}: {len(streams)} streams')


if __name__ == '__main__':
    main()
