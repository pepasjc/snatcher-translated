# -*- coding: utf-8 -*-
"""What the harness runs have and have not exercised.

    python ps1/harness/coverage.py                # every bank
    python ps1/harness/coverage.py B200 B210      # these banks, with the missing ids
    python ps1/harness/coverage.py --speakers     # data speaker vs the engine's named column
    python ps1/harness/coverage.py --logs work/faces  # extra log roots

Reads every run log it can find (work/*/log.txt, work/**/*.out written by
scripted.py) and, per subtitled bank, lists the cue ids that have never
been drawn in any run. The basement's face reconstruction (202 cards,
BUG-050) sat unreachable for months because no route ever played past the
morgue reel; this is the list that would have shown it.

Cue lines are keyed on the id the harness prints since 2026-09-11
(`cue 48 (B200_c7f18_0)`); older logs carry the index only, which shifts
whenever a cue file is re-cut, so they count for nothing here.

--speakers: the verdicts of scripted.py's speaker gate (`speaker <id>
... verdict=` lines, every run since 2026-09-12) aggregated per cue id:
`DATA?` = the engine animated another character's mouth although the cue's
speaker has a face in the room (a mislabelled cue), `FACE!` = our layout
showed the wrong face (a payload bug). A card is `unverifiable` where its
speaker has no face in the room (the script animates a listener - Metal's
lines in B010) or the engine named nobody; those never count. Cards whose
verdicts disagree between runs are printed with all of them.

Bank loads with no cue file are listed too: a stretch of the game that
cannot be subtitled at all until it gets one (B210 was that).
"""
import argparse, collections, glob, json, os, re, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TRANSLATION = os.path.join(ROOT, 'ps1', 'translation')
CUE_RE = re.compile(r'^(\d+): cue (\d+)(?: of (B[0-9A-F]{3}))? \(([A-Za-z0-9_]+)(?:, not scored)?\)')
SCENE_RE = re.compile(r'^(\d+): scene (B[0-9A-F]{3})')
SPEAKER_RE = re.compile(r'^(\d+): speaker (\S+) data=(.*?) engine=(\S+) face=(\S+) room=(\[.*?\]) verdict=(\S+)')
STREAM_RE = re.compile(r'^(\d+): stream file=(\d+) chan=(\d+) lba=(\d+)')


def cue_files():
    out = {}
    for p in sorted(glob.glob(os.path.join(TRANSLATION, 'subs_B*.json'))):
        d = json.load(open(p, encoding='utf-8'))
        out[os.path.basename(p)[5:9]] = d
    return out


def logs(roots):
    for root in roots:
        for p in glob.glob(os.path.join(root, '**', 'log.txt'), recursive=True):
            yield p
        for p in glob.glob(os.path.join(root, '**', '*.out'), recursive=True):
            yield p


def scan(roots, cues):
    """drawn[bank] = {cue id: runs}, banks_seen = Counter of bank loads,
    verdicts[(bank, id)] = Counter of the speaker gate's verdict per run,
    streams[bank] = {(file, chan): runs}."""
    drawn = collections.defaultdict(collections.Counter)
    banks_seen = collections.Counter()
    verdicts = collections.defaultdict(collections.Counter)
    details = {}
    streams = collections.defaultdict(collections.Counter)
    for p in logs(roots):
        try:
            f = open(p, encoding='utf-8', errors='replace')
        except OSError:
            continue
        # the run's own scene (the cue file its indices and ids are scored
        # against) is the --scene argument, echoed on the log's first line
        # as `B010: N scripted actions`; `scene BXXX` lines track the bank
        # in RAM (the run may cross into the next one)
        first = f.readline()
        m = re.match(r'^(B[0-9A-F]{3}): \d+ scripted actions', first)
        run_scene = m[1] if m else None
        scene = run_scene
        for line in f:
            m = SCENE_RE.match(line)
            if m:
                banks_seen[m[2]] += 1
                scene = m[2]
                continue
            m = STREAM_RE.match(line)
            if m and scene and (int(m[2]) or int(m[3])):
                streams[scene][(int(m[2]), int(m[3]))] += 1
                continue
            m = SPEAKER_RE.match(line)
            if m and run_scene:
                verdicts[(run_scene, m[2])][m[7]] += 1
                details.setdefault((run_scene, m[2]), []).append((m[3], m[4], m[5], m[7], p))
                continue
            m = CUE_RE.match(line)
            if not m:
                continue
            bank = m[3] or run_scene or scene
            cid = m[4]
            if not bank or cid in ('blank', '?'):
                continue
            drawn[bank][cid] += 1
    return drawn, banks_seen, verdicts, details, streams


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('banks', nargs='*')
    ap.add_argument('--logs', action='append', default=[], help='extra log roots (default work/)')
    ap.add_argument('--speakers', action='store_true')
    ap.add_argument('--all-missing', action='store_true', help='print every missing id, not the first ten')
    a = ap.parse_args()
    cues = cue_files()
    roots = [WORK] + a.logs
    drawn, banks_seen, verdicts, details, streams = scan(roots, cues)

    if a.speakers:
        n = bad = 0
        for (bank, cid), v in sorted(verdicts.items()):
            if a.banks and bank not in a.banks:
                continue
            c = next((c for c in cues.get(bank, {}).get('cues', []) if c['id'] == cid), None)
            if not c:
                continue
            checked = sum(n for k, n in v.items() if k != 'unverifiable')
            if not checked:
                continue
            n += 1
            flagged = {k: n for k, n in v.items() if k not in ('ok', 'ear', 'unverifiable')}
            if flagged:
                bad += 1
                print(f'{bank} {cid:16s} data={c.get("speaker")!r:14s} {dict(v)}  {c["en"][:44]}')
                for data, eng, face, verdict, p in details[(bank, cid)]:
                    if verdict not in ('ok', 'ear', 'unverifiable'):
                        print(f'      {verdict:6s} engine={eng} face={face}  {os.path.relpath(p, WORK)}')
        print(f'{n} cards with a verifiable speaker in some run, {bad} flagged')
        return

    banks = a.banks or sorted(cues)
    tot_cues = tot_drawn = 0
    for bank in banks:
        d = cues.get(bank)
        if not d:
            print(f'{bank}: no cue file')
            continue
        ids = [c['id'] for c in d['cues'] if c.get('enabled', True)]
        seen = drawn.get(bank, {})
        missing = [i for i in ids if i not in seen]
        tot_cues += len(ids); tot_drawn += len(ids) - len(missing)
        print(f'{bank}: {len(ids) - len(missing):4d}/{len(ids):<4d} drawn in some run, {len(missing):4d} never'
              + (f'  loads seen {banks_seen[bank]}' if banks_seen[bank] else '  NEVER LOADED in a run'))
        if a.banks or a.all_missing:
            for i in (missing if a.all_missing else missing[:10]):
                print(f'    {i}')
            if not a.all_missing and len(missing) > 10:
                print(f'    ... {len(missing) - 10} more')
    print(f'\n{tot_drawn}/{tot_cues} cues drawn in some run')
    # streams the filter stub logged under a bank that has no cue on that
    # file/channel: music and effects mostly, but every uncarded voice line
    # is in this list too (the census works from it)
    for bank in banks:
        d = cues.get(bank)
        if not d or bank not in streams:
            continue
        carded = {(c['file'], c.get('chan')) for c in d['cues']}
        un = sorted(k for k in streams[bank] if k not in carded)
        if un:
            print(f'{bank}: streams with no cue: ' + ' '.join(f'f{f}/c{c}' for f, c in un[:24]) + (' ...' if len(un) > 24 else ''))
    nocue = sorted(b for b in banks_seen if b not in cues)
    if nocue:
        print('banks loaded in runs with NO cue file:', ', '.join(nocue),
              '- voiced lines there cannot be subtitled until one exists (BUG-050)')


if __name__ == '__main__':
    main()
