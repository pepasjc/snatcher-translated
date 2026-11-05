# -*- coding: utf-8 -*-
"""Which bank plays which XA voice line, and does that bank card it?

The payload only ever sees the cue blob of the bank that is LOADED, so a
stream that plays under bank Y needs cards under Y even when bank X already
cards it. That has cost three scenes so far: Outer Heaven's interior
(BUG-030, carded under B0F0 while B100 was live), the disarm exchange at
Ivan's door (BUG-035) and the Act 2 arrival's replay of Metal's Act 1 report
(BUG-037, carded under B080 only), which played bare for two and a half
minutes.

Nothing here is guessed. Every harness run logs the live bank (`scene BXXX`,
by the sha1 of the bank's first 256 bytes) and every Setfilter the stub
captures (`stream file= chan= lba=`). This walks every log, attributes each
stream to the bank that was live when it started, identifies it against the
voice census (work/master_lines.json) by its position - a Setfilter names
only file and channel, and those repeat between XAS_M000 and XAS_S000, so
the LBA is what tells the two apart and what says whether the stream is
speech at all - and reports the ones the live bank does not card.

    python ps1/subs/reel_audit.py                  # the report
    python ps1/subs/reel_audit.py --all            # music and effects too
    python ps1/subs/reel_audit.py --logs A/log.txt B/log.txt
    python ps1/subs/reel_audit.py --min-frames 300 # only streams that really ran

A stream is evidence only where the harness has been: a clean report means
"nothing in what we have played", never "nothing anywhere".

The other blind spot is the chain cue (chan 254): it fires a fixed number of
frames after an anchor instead of matching a stream, so it carries no stream
identity and cannot be checked by position. Those cues are listed under the
report - the JUNKER card line was written that way and read as a hole here
until Luiz recognised it.
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
SCENE_RE = re.compile(r'^(\d+): scene (B[0-9A-F]{3})')
STREAM_RE = re.compile(r'^(\d+): stream file=(\d+) chan=(\d+) lba=(\d+)')
NO_STREAM = (0, 0)          # the driver's own "nothing is playing"
# XAS_M000.XA starts at LBA 2408, XAS_S000.XA at 64888. File and channel
# numbers repeat between the two, so a capture's position cannot say WHICH
# line is playing (the poll lags a stream switch by a read-ahead) but it does
# say which of the two files it is - and that is what separates a mono line
# from the stereo one wearing the same numbers. Attributing "Yes! Door 3
# opened!" (M ch7 f6, the hospital basement) to the factory ruins came from
# counting captures of the stereo twin S ch7 f6 that lives there.
S_XA_LBA = 64888
SLACK = 4500                # the drive reads ahead; the poll lags behind
# faster-whisper's stock hallucinations on music and silence: a line whose
# transcript is one of these said nothing, and is a census artefact.
HALLUCINATION = ('ご視聴ありがとうございました', 'ありがとうございました',
                 'おやすみなさい', 'チャンネル登録')


def census():
    """(chan, file) -> [(start, end, xa)], and (xa, ch, file, start) -> ja."""
    path = os.path.join(ROOT, 'work', 'master_lines.json')
    m = json.load(open(path, encoding='utf-8'))
    lines = m['lines'] if isinstance(m, dict) else m
    out = collections.defaultdict(list)
    text = {}
    for l in lines:
        out[(l['ch'], l['file'])].append((l['start'], l['end'], l['xa']))
        text[(l['xa'], l['ch'], l['file'], l['start'])] = (l.get('ja') or '').strip()
    return out, text


def xa_of(lba):
    """Which XA file a capture position falls in."""
    return 'S' if lba >= S_XA_LBA else 'M'


def speech_at(cen, ch, fi, lba):
    """The voice line a capture at this position belongs to, or None."""
    best = None
    for start, end, xa in cen.get((ch, fi), ()):
        if xa != xa_of(lba):
            continue
        if start - SLACK <= lba <= end + SLACK:
            d = 0 if start <= lba <= end else min(abs(lba - start), abs(lba - end))
            if best is None or d < best[0]:
                best = (d, (start, end, xa))
    return best[1] if best else None


def chain_cues():
    """The chan-254 cues: text that exists but is keyed to no stream."""
    out = collections.defaultdict(list)
    for p in glob.glob(os.path.join(ROOT, 'ps1/translation', 'subs_*.json')):
        bank = os.path.basename(p)[5:-5]
        for c in json.load(open(p, encoding='utf-8'))['cues']:
            if c.get('chan') == 254:
                out[bank].append(c)
    return out


def cue_index():
    """(bank, chan, file) -> [(start, end)] from the shipped cue data."""
    idx = collections.defaultdict(list)
    for p in glob.glob(os.path.join(ROOT, 'ps1/translation', 'subs_*.json')):
        bank = os.path.basename(p)[5:-5]
        for c in json.load(open(p, encoding='utf-8'))['cues']:
            if c.get('chan') == 254:        # chain cue: fires off an anchor
                continue
            idx[(bank, c['chan'], c['file'])].append((c['start'], c['end']))
    return idx


def cards(idx, bank, ch, fi, span):
    """True when the bank has a cue inside the line's own sectors."""
    if span is None:
        return bool(idx.get((bank, ch, fi)))
    lo, hi, _xa = span
    return any(lo <= s <= hi or lo <= e <= hi or (s <= lo and hi <= e)
               for s, e in idx.get((bank, ch, fi), ()))


def walk(paths, min_frames):
    """[(bank, chan, file, frames, lba, log)] - one row per stream run."""
    rows = []
    for p in paths:
        try:
            lines = open(p, encoding='utf-8', errors='replace').read().splitlines()
        except OSError:
            continue
        bank = None
        live = None                          # (chan, file, frame, lba)

        def close(f):
            if live and (live[0], live[1]) != NO_STREAM and bank:
                rows.append((bank, live[0], live[1], f - live[2], live[3], p))

        for ln in lines:
            m = SCENE_RE.match(ln)
            if m:
                close(int(m.group(1)))
                bank, live = m.group(2), None
                continue
            m = STREAM_RE.match(ln)
            if m:
                f, fi, ch, lba = (int(x) for x in m.groups())
                close(f)
                live = (ch, fi, f, lba)
        if live:
            close(live[2] + min_frames)      # still playing when the log ended
    return [r for r in rows if r[3] >= min_frames]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--logs', nargs='*')
    ap.add_argument('--min-frames', type=int, default=120,
                    help='a stream must run this long to count (default 120)')
    ap.add_argument('--all', action='store_true',
                    help='report music and effects too, not just speech')
    a = ap.parse_args()
    paths = a.logs or (sorted(glob.glob(os.path.join(ROOT, 'work', 's_*', 'log.txt')))
                       + sorted(glob.glob(os.path.join(ROOT, 'temp', '*.log'))))

    idx, (cen, ja) = cue_index(), census()
    rows = walk(paths, a.min_frames)

    seen = collections.defaultdict(lambda: [0, 0, set()])
    music = 0
    for bank, ch, fi, frames, lba, log in rows:
        span = speech_at(cen, ch, fi, lba)
        if span is None and not a.all:
            music += 1
            continue
        e = seen[(bank, ch, fi, span)]
        e[0] += 1
        e[1] = max(e[1], frames)
        e[2].add(os.path.basename(os.path.dirname(log)) or os.path.basename(log))

    holes = []
    for (bank, ch, fi, span), (runs, frames, logs) in seen.items():
        if cards(idx, bank, ch, fi, span):
            continue
        elsewhere = sorted({b for (b, c, f) in idx
                            if (c, f) == (ch, fi) and cards(idx, b, c, f, span)})
        holes.append((bank, ch, fi, span, frames, runs, elsewhere, sorted(logs)[:2]))

    print(f'logs {len(paths)}   stream runs {len(rows)}   '
          f'not speech {music}   bank/line pairs {len(seen)}   holes {len(holes)}')
    print()
    known, silent = [], []
    for h in sorted(holes, key=lambda h: -h[4]):
        span, ch, fi = h[3], h[1], h[2]
        t = ja.get((span[2], ch, fi, span[0]), '') if span else ''
        (silent if not t or any(t.startswith(x) for x in HALLUCINATION)
         else known).append(h + (t,))

    def table(rows, head):
        print(head)
        print(f'{"bank":<6}{"ch":>3}{"file":>5}{"xa":>3}{"frames":>8}  '
              f'{"carded in":<12}{"log":<20}text')
        for bank, ch, fi, span, frames, runs, elsewhere, logs, t in rows:
            print(f'{bank:<6}{ch:>3}{fi:>5}{(span[2] if span else "-"):>3}{frames:>8}  '
                  f'{(",".join(elsewhere) or "-"):<12}{logs[0][:19]:<20}{t[:46]}')
        print()

    table(known, 'SPEECH THE LIVE BANK DOES NOT CARD - the BUG-037 pattern '
                 'wherever "carded in" names a bank:')
    table(silent, 'NO TRANSCRIPT - music and effects, EXCEPT where the ASR pass '
                  'dropped the speech:')
    chains = chain_cues()
    if chains:
        print('CHAIN CUES - text keyed to no stream, so a line they cover still '
              'reports as a hole above:')
        for bank, cs in sorted(chains.items()):
            for c in cs:
                print(f'  {bank:<6}{c["id"]:<16}{c["speaker"]:<9}{c["en"][:52]}')
        print()
    print('The census transcript is the evidence for "this is speech". An empty '
          'one is NOT proof of\nmusic - VAD has dropped a whole conversation '
          'before - so long silent reels want a NOVAD pass.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
