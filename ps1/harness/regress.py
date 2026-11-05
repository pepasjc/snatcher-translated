# -*- coding: utf-8 -*-
"""The regression set as one command, with one verdict table at the end.

    python ps1/harness/regress.py                 # everything (~15 min: --jobs 8)
    python ps1/harness/regress.py harry basement  # these runs only
    python ps1/harness/regress.py --jobs 1        # one at a time (~53 min at 300 fps)
    python ps1/harness/regress.py --list

Runs the scripted harness over the set below - `--jobs` emulators at once
(default: half the CPUs; the image is only read, each Beetle instance is
its own process and single-threaded, and the harness counts frames, not
seconds, so runs side by side change no verdict; the wall time is the
longest run's, b010 at ~14 min) - into work/regress/<key>/, and reads
each run's log.txt for the four things a build must get right. The image
has no lock: never build while this runs. Runs that share a bank (b010p
and harry beside b010) write their bookmarks into their own out dir
(STATES_DIR, scripted.py) - b010's are the ones that land in work/states.

  cues      cards drawn (against the run's expectation), per bank the run
            passed through - a bank that drew nothing is a dead payload
  text      subs_validate: rows found in the settled captures (FAIL lines
            are worth a look; the validator has known misses, BUG-003)
  speakers  the speaker gate (scripted.py): DATA? = the engine animated
            another character's mouth although the cue's speaker has a face
            in the room (a mislabelled cue), FACE! = our layout showed the
            wrong face. These are the errors play-testing kept finding by
            hand (the morgue's ten, the basement's three) - until 2026-09-12
            no run checked them at all
  panel     panel_check: frame geometry drift
  geometry  menuread.geometry: a list label wider than its column on the
            renderer's 4 x 2 grid (right column 8 cells, left 10 beside a
            neighbour) - it paints over the next row's label

  sync      scripted.py's sync gate: UNSHOWN = a line the payload's matcher
            heard for half a second that never got its card, LATE = a card
            1.5 s or more behind its line, FROZEN = our card held in WAIT
            with nothing playing and no menu (the Saturn v1.0 softlock),
            HANG = the game's frame counter stopped
  lint      the cue files offline: check_cues errors, a card plan
            consolidate.py would still re-cut (lib/cardplan.py's rules:
            greedy rows, whole sentences a card, no widow, an item number
            opens its card), check_strings errors

The whole game (2026-11-05): `wgNN` runs replay ps1/harness/plays/
whole_game.route.json one checkpoint stretch each, on the dev-test image
(shots always hit - the regression tests the translation, not the
pilot's aim: B250's real fights killed Gillian and its run read 'Continue
/ Quit game' for 30 000 frames), from the chain's checkpoint states
(wholegame.py run; `regress.py --mint` copies them to work/states/wg/ and
writes work/regress/segments.json). raminject refreshes bank, payload and
exec into each, from work/devfights/patched (devfights.py apply stages it).

Coverage gate: after a full set (no keys given, or --coverage), every
scene bank must have loaded in some run and every enabled cue of every
cue file must have drawn, except what ps1/harness/coverage_exempt.json
names with its reason. A drop fails the set.

Exit status 1 when any run has a FACE!, a DATA?, a text FAIL (the validator
is exact since 2026-11-05; --lenient drops text FAILs), an UNSHOWN / LATE /
FROZEN / HANG, a bank under its minimum, a panel or geometry problem, a
lint error, or did not finish, or when coverage drops. The table and every
flagged line go to work/regress/summary.txt.
"""
import argparse, glob, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
import subprocess
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PY = sys.executable
S = os.path.join(HERE, 'scripted.py')
LENIENT = False
R = lambda name: os.path.join(HERE, 'routes', name)

DEV_CUE = 'patched/Snatcher (Japan) [dev-test].cue'
DEV_PATCHED = os.path.join(WORK, 'devfights', 'patched')
DEV_ENV = {'SNATCHER_PATCHED': DEV_PATCHED, 'BLIND_FIGHT': '1'}
ROUTE_WG = os.path.join(HERE, 'plays', 'whole_game.route.json')
SEGMENTS = os.path.join(WORK, 'regress', 'segments.json')
EXEMPT = os.path.join(HERE, 'coverage_exempt.json')
ALL_BANKS = [f'B{i:02X}0' for i in range(0x27)]          # ISZ_B000..ISZ_B260

# key, title, argv (scripted.py unless noted), env, {bank: min cues expected}
# OWN_STATES: runs whose bookmarks would collide with another run's under
# --jobs (same route or bank) - their saves go to work/regress/<key>/states.
OWN_STATES = {'b010p', 'harry'}
SET = [
    ('b010', 'B010 New Game, patient',
     [PY, S, '--scene', 'B010', '--new', '--frames', '200000'], {}, {'B010': 60}),
    ('b010p', 'B010 New Game, impatient (HOLD_AFTER_CUE=100)',
     [PY, S, '--scene', 'B010', '--new', '--frames', '200000'], {'HOLD_AFTER_CUE': '100'}, {'B010': 60}),
    ('b020', 'B020 the ride and the factory',
     [PY, S, '--scene', 'B020', '--from-state', '--frames', '130000'], {}, {'B020': 60}),
    ('b0c0', "B0C0 Gillian's home",
     # from the whole-game chain's Gillian's-home checkpoint through the
     # B0C0 stretch of whole_game.route.json: the old B0C0_start bookmark
     # carried an older disc's CD buffer and hung the load after the disk
     # (2026-11-06; the chain from New Game passes there)
     [PY, S, '--scene', 'B0B0', '--state', 'wg/wg04_B0B0', '--route', ROUTE_WG, '--start', '62', '--end', '89',
      # at 101 % CPU clock: at the native clock the load after Gibson's
      # disk hangs on Beetle (BUG-078's shape, with NOSUBS=1 too) - the
      # bug078_b0c0 key keeps that hang in view
      '--frames', '90000', '--image', DEV_CUE],
     dict(DEV_ENV, HOLD_AFTER_CUE='0', RETRO_OPTIONS=os.path.join(HERE, 'cpu101.opt')), {'B0C0': 50}),
    ('b250', 'B250 the church and the culture room, into B260 (the church door)',
     # B250_arrive is the route's own bookmark (B240.json action 10, the
     # tricycle at the church); --start 11 plays the rest of that route:
     # the culture room, Jamie's door, and ~10000 frames of B260 - the
     # bank handover BUG-053 missed. The old B250_culture bookmark predates
     # the pair-table rebuild (its menu read 'Caeck', 'swa iotaomGeha').
     # on the dev-test image: the church's fights killed Gillian on the
     # normal one and the run idled on 'Continue / Quit game'
     [PY, S, '--scene', 'B250', '--state', 'B250_arrive', '--route', R('B240.json'), '--start', '11', '--frames', '90000',
      '--image', DEV_CUE], DEV_ENV, {'B250': 80, 'B260': 25}),
    ('harry', "B010 Harry's call from the Chief's room (impatient)",
     # 8000: the run used to end 24 frames after Harry's 'Hey, Metal Gear!'
     # drew, before any settled capture of it
     [PY, S, '--scene', 'B010', '--state', 'B010_chief', '--route', R('B010_harry.json'), '--frames', '8000'], {'HOLD_AFTER_CUE': '100'}, {'B010': 6}),
    ('basement', 'B200 the morgue reel, Restore and the whole reconstruction (B210)',
     [PY, S, '--scene', 'B200', '--state', 'B200_pre_both', '--route', R('B200_basement.json'), '--frames', '100000'], {}, {'B200': 34, 'B210': 150}),
    ('intro', 'the opening (intro_run.py)',
     [PY, os.path.join(HERE, 'intro_run.py'), '27000'], {}, {'INTRO': 23}),
    ('build', 'verify_build.py',
     [PY, os.path.join(ROOT, 'ps1', 'tools', 'verify_build.py')], {}, {}),
    ('lint', 'cue files and strings offline (check_cues, consolidate, check_strings)',
     [PY, os.path.join(HERE, 'regress.py'), '--lint-only'], {}, {}),
]


# Per-bank routes from their bookmarks, for the stretches the whole-game
# chain does not reach on its own (its Act 2 ran off the route after B1D0;
# Joy Division's and Altamira's conversations need the per-bank paths).
# (key, scene the state holds, bookmark, route, frames, extra env)
GAPS = [
    ('g_b080', 'B080', 'B080_start', 'B080.json', 70000, {}),
    ('g_b080j', 'B080', 'B080_start', 'B080_jamie.json', 40000, {}),
    ('g_b0d0', 'B0D0', 'B0D0_start', 'B0D0_napoleon.json', 90000, {}),
    ('g_b190', 'B190', 'B190_start', 'B190.json', 80000, {}),
    ('g_b1f0', 'B1F0', 'B1F0_car', 'B1F0.json', 60000, {'PILOT_OK': 'cross'}),
    ('g_b230', 'B230', 'B230_start', 'B230.json', 90000, {}),
    # 2026-11-07 coverage pass (cov_* routes and bookmarks):
    # HQ sealed from the taxi at the front: Mika's booth, Harry's death, the
    # ceiling fight and the blood trail (B230_f20-f52, B230_h_*)
    ('g_b230hq', 'B230', 'cov_B230_arrive', 'cov_B230_hq.json', 100000, {}),
    # New Game with the Squad room picked first: Mika's 'the Chief asked me
    # to show you around' (B010_005-007)
    ('g_b010m', 'B010', 'cov_B010_front', 'cov_B010_mika.json', 25000, {}),
    # a number the bank does not know, all ten digits + confirm: the 'not in
    # service' recording (B060_006, B070_005/006), and the lab in Act 2
    ('g_b060wrong', 'B060', 'cov_B060_call', 'cov_B060_wrongnum.json', 5000, {}),
    ('g_b070lab', 'B170', 'cov_B170_pre', 'cov_B070_lab.json', 25000, {}),
]
# Bookmarks tried and dropped 2026-11-06 (no card drawn: a stale menu, a
# game-over screen, a story state the route does not fit): B080_napoleon,
# B0E0_start/B0E0_video, B100_arrive/B100_isabella, B1D0_arrive,
# B1E0_arrive, B160_arrive, B200_fight, B220_auto, B220_taxi, B230_front.


# Coverage runs from the harness-minted card saves (work/saves/<bank>_auto.mcd,
# the game's own Save at the bank's first verb menu): a card holds only game
# flags, so unlike a bookmark it survives every rebuild (2026-11-06).
# (key, scene, card, route, start, end, frames, extra env)
CARDS = [
    ('c_b0e0', 'B0E0', 'B0E0_auto', R('B0E0_cover.json'), 0, None, 90000, {}),
    ('c_b0d0', 'B0D0', 'B0D0_auto', R('B0D0_teller3.json'), 0, None, 150000, {}),
    ('c_b1f0', 'B160', 'B160_auto', R('B1F0_cover.json'), 0, None, 140000, {}),
    ('c_b1d0', 'B1D0', 'B1D0_auto', ROUTE_WG, 473, 487, 120000, {}),
    ('c_b230', 'B230', 'B230_auto', ROUTE_WG, 601, None, 400000,
     {'RETRO_OPTIONS': os.path.join(HERE, 'cpu101.opt')}),
    # Outer Heaven's master and the thug (B100_002-003b; the census route)
    ('c_b100', 'B100', 'B100_auto', R('B100_census.json'), 0, None, 40000, {}),
    # the Chief's expenses scolding after the Outer Heaven binge, under B080
    # (B080_f1_0-f6_0: carded only in the videophone banks until 2026-11-07)
    ('c_chief', 'B100', 'B100_auto', R('cov_B100_binge_hq.json'), 0, None, 40000, {}),
    # the duct, the maze, Freddy's bathroom and the black taxi (B220)
    # (PANEL_EMPTY_OK: the maze's own direction box sits empty between moves)
    ('c_b220', 'B220', 'B220_i95_maze', R('cov_B220_duct.json'), 0, None, 110000, {'PANEL_EMPTY_OK': '1'}),
]


def cards():
    out = []
    for k, sc, card, route, st, en, fr, env in CARDS:
        argv = [PY, S, '--scene', sc, '--slot', '1', '--card', os.path.join(WORK, 'saves', card + '.mcd'),
                '--route', route, '--frames', str(fr), '--stop-after', '1200', '--image', DEV_CUE]
        if st:
            argv += ['--start', str(st)]
        if en is not None:
            argv += ['--end', str(en)]
        out.append((k, f'{sc} from the {card} card', argv, dict(DEV_ENV, HOLD_AFTER_CUE='0', WATCHDOG='0', **env), {}))
    return out


def gaps():
    return [(k, f'{sc} {r} from {st}',
             [PY, S, '--scene', sc, '--state', st, '--route', R(r), '--frames', str(fr), '--stop-after', '1200',
              '--image', DEV_CUE], dict(DEV_ENV, **env), {})
            for k, sc, st, r, fr, env in GAPS]


# Act 3 from the B240 quiz (the chain's route from action 581: the church,
# the Kremlin, the ending), stopped before BUG-078's hang; the rest of the
# ending from the state just before it at 101 % CPU clock (the hang needs
# the native clock); and BUG-078 itself, which must still hang at the
# native clock - the day it stops hanging this key says so.
ACT3 = [
    ('act3', 'Act 3: the B240 quiz, the church, the Kremlin, the ending to BUG-078',
     # from route action 618 (the debrief's second question: B240_auto is
     # there); from 581 the run spent ~45000 frames on B230's leftover
     # actions and never reached B260. 178000 stops ~500 frames after
     # B260_c14f1 (at 177484 on 2026-11-07), before the hang ~1500 after it
     [PY, S, '--scene', 'B240', '--state', 'B240_auto', '--start', '618', '--route', ROUTE_WG,
      '--frames', '178000', '--image', DEV_CUE], dict(DEV_ENV, HOLD_AFTER_CUE='0', WATCHDOG='0'),
     {'B240': 60, 'B250': 90, 'B260': 170}),
    ('ending', 'the rest of the ending (B260) past BUG-078, at 101 % CPU clock',
     [PY, S, '--scene', 'B260', '--state', 'dbgb_180500', '--route', R('generic.json'),
      '--frames', '160000', '--image', DEV_CUE],
     dict(DEV_ENV, WATCHDOG='0', RETRO_OPTIONS=os.path.join(HERE, 'cpu101.opt')), {'B260': 150}),
    ('bug078', 'BUG-078 repro: the ending hangs at the native clock (expected)',
     [PY, S, '--scene', 'B260', '--state', 'dbgb_179500', '--route', R('generic.json'),
      '--frames', '6000', '--image', DEV_CUE], dict(DEV_ENV, WATCHDOG='0'), {}),
    ('bug078_b0c0', 'BUG-078 repro: B0C0 after the disk hangs at the native clock (expected)',
     [PY, S, '--scene', 'B0B0', '--state', 'wg/wg04_B0B0', '--route', ROUTE_WG, '--start', '62', '--end', '89',
      '--frames', '56000', '--image', DEV_CUE], dict(DEV_ENV, HOLD_AFTER_CUE='0'), {}),
]
SEGMENT_DUPES = {'wg03'}        # = the b0c0 key's stretch


def segments():
    """The whole game's checkpoint stretches as regress keys (--mint writes them)."""
    if not os.path.exists(SEGMENTS):
        return []
    out = []
    for g in json.load(open(SEGMENTS)):
        if g['key'] in SEGMENT_DUPES:
            continue
        argv = [PY, S, '--scene', g['scene'], '--route', ROUTE_WG, '--image', DEV_CUE,
                '--frames', str(g['frames']), '--stop-after', '1200']
        argv += ['--state', g['state'], '--start', str(g['start'])] if g.get('state') else ['--new']
        if g.get('end') is not None:
            argv += ['--end', str(g['end'])]
        out.append((g['key'], f"whole game: {g['title']}", argv,
                    dict(DEV_ENV, HOLD_AFTER_CUE='0'), {}))
    return out


def mint():
    """Copy the whole-game chain's checkpoints (work/mplay/states, wholegame.py
    run) to work/states/wg/ and write segments.json: one key per stretch,
    New Game to the first checkpoint, each checkpoint to the next, the last
    one to the route's end. Frames per stretch: what the chain took, x1.5,
    plus 20 000."""
    import shutil
    route = json.load(open(ROUTE_WG, encoding='utf-8'))['actions']
    cks = [(i, a['checkpoint']) for i, a in enumerate(route) if 'checkpoint' in a]
    src = os.path.join(WORK, 'mplay', 'states')
    dst = os.path.join(WORK, 'states', 'wg')
    os.makedirs(dst, exist_ok=True)
    # frame at which the chain wrote each checkpoint, and the log it is in
    at = {}
    for lp in glob.glob(os.path.join(WORK, 'mplay', 'run_*', 'out', 'log.txt')):
        for line in open(lp, encoding='utf-8', errors='replace'):
            m = re.match(r'^(\d+): checkpoint (\S+) slot', line)
            if m:
                at[m[2]] = (lp, int(m[1]))
    segs, prev = [], None          # prev = (name, scene, start action, frame, log)
    for k, (i, name) in enumerate(cks + [(len(route), None)]):
        missing = name is not None and not os.path.exists(os.path.join(src, name + '.state.gz'))
        if missing and prev is None:
            break
        if prev is None:
            seg = {'key': 'wg00', 'title': 'New Game to ' + (name or 'the end'), 'scene': 'B010',
                   'start': 0, 'end': i}
            span = at.get(name, (None, 150000))[1] if name else 600000
        else:
            pname, pscene, pstart, pframe, plog = prev
            seg = {'key': f'wg{k:02d}', 'title': f'{pname} to {name or "the end"}', 'scene': pscene,
                   'state': 'wg/' + pname, 'start': pstart, 'end': i if name else None}
            if name and at.get(name, (None,))[0] == plog:
                span = at[name][1] - pframe
            else:
                span = 200000 if name else 400000
        seg['frames'] = int(span * 1.5) + 20000
        segs.append(seg)
        if missing:
            # the stretch up to a checkpoint the chain never wrote still
            # runs (it ends where that checkpoint sits); nothing after it
            print(f'mint: no state for {name} - the chain has not reached it; the segments stop there')
            break
        if name is None:
            break
        meta = json.load(open(os.path.join(src, name + '.json')))
        for ext in ('.state.gz', '.json', '.card'):
            if os.path.exists(os.path.join(src, name + ext)):
                shutil.copyfile(os.path.join(src, name + ext), os.path.join(dst, name + ext))
        prev = (name, meta['scene'], meta['action'], at.get(name, (None, 0))[1], at.get(name, (None,))[0])
    json.dump(segs, open(SEGMENTS, 'w'), indent=1)
    for g in segs:
        print(f"{g['key']}: {g['title']} ({g['scene']}, actions {g['start']}..{g.get('end')}, {g['frames']} frames)")
    print(f'{len(segs)} segment(s) -> {SEGMENTS}')


def lint():
    """The offline checks: exit 1 on any problem."""
    bad = []
    files = sorted(glob.glob(os.path.join(ROOT, 'ps1', 'translation', 'subs_*.json')))
    r = subprocess.run([PY, os.path.join(ROOT, 'ps1', 'subs', 'check_cues.py'), '--quiet'] + files,
                       cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(r.stdout.strip())
    if r.returncode:
        bad.append('check_cues: ' + (r.stderr.strip().splitlines() or ['errors'])[-1])
    r = subprocess.run([PY, os.path.join(ROOT, 'ps1', 'subs', 'consolidate.py')], cwd=ROOT,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(r.stdout.strip())
    m = re.search(r'(\d+) chains re-cut', r.stdout)
    if not m or int(m[1]):
        bad.append(f'consolidate: {m[1] if m else "?"} chain(s) the card planner would re-cut')
    r = subprocess.run([PY, os.path.join(ROOT, 'ps1', 'tools', 'check_strings.py'), '--all', '--quiet'], cwd=ROOT,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(r.stdout.strip()[-400:])
    m = re.search(r'(\d+) errors', r.stdout)
    if not m or int(m[1]):
        bad.append(f'check_strings: {m[1] if m else "?"} error(s)')
    for b in bad:
        print('LINT! ' + b)
    sys.exit(1 if bad else 0)


def coverage_gate(base):
    """([problems], cues drawn, enabled cues, banks loaded): banks never
    loaded and enabled cues never drawn across the runs under `base`, less
    the exempt list."""
    import coverage as COV
    cues = COV.cue_files()
    drawn, banks_seen, *_ = COV.scan([base], cues)
    ex = json.load(open(EXEMPT, encoding='utf-8')) if os.path.exists(EXEMPT) else {}
    ex_banks, ex_cues = ex.get('banks', {}), ex.get('cues', {})
    out, tot, got = [], 0, 0
    for b in ALL_BANKS:
        if not banks_seen.get(b) and b not in ex_banks:
            out.append(f'bank {b} never loaded')
    for b, d in sorted(cues.items()):
        ids = [c['id'] for c in d['cues'] if c.get('enabled', True)]
        miss = [i for i in ids if i not in drawn.get(b, {}) and i not in ex_cues]
        tot += len(ids)
        got += sum(1 for i in ids if i in drawn.get(b, {}))
        if miss:
            out.append(f'{b}: {len(miss)} cue(s) never drawn: ' + ' '.join(miss[:12]) + (' ...' if len(miss) > 12 else ''))
    known = {c['id'] for d in cues.values() for c in d['cues']}
    stale = [i for i in ex_cues if i not in known]
    if stale:
        out.append('coverage_exempt.json names cues that no longer exist: ' + ' '.join(stale[:8]))
    return out, got, tot, sum(1 for b in ALL_BANKS if banks_seen.get(b))


def parse_log(path):
    """The verdict lines of a scripted.py log."""
    r = {'cues': {}, 'text': [], 'speak': None, 'flags': [], 'panel': None, 'end': None, 'misses': 0, 'geom': None,
         'sync': None, 'hang': 0}
    if not os.path.exists(path):
        return r
    scene = None
    for line in open(path, encoding='utf-8', errors='replace'):
        m = re.match(r'^(B[0-9A-F]{3}): \d+ scripted actions', line)
        if m:
            scene = m[1]
        m = re.match(r'^end: (\d+)/(\d+) actions, (\d+) distinct cues, (\d+) miss', line)
        if m:
            r['end'] = (int(m[1]), int(m[2])); r['misses'] = int(m[4])
            r['cues'][scene] = int(m[3])
            for b, n in re.findall(r'; (B[0-9A-F]{3}): (\d+) cues', line):
                r['cues'][b] = int(n)
        m = re.match(r'^speakers: (\d+) cards, ok (\d+), unverifiable (\d+), DATA\? (\d+), FACE! (\d+)', line)
        if m:
            r['speak'] = tuple(int(x) for x in m.groups())
        if re.match(r'^  (DATA\?|FACE!|DATA\?/FACE!|GEOMETRY!|UNSHOWN|LATE|FROZEN) ', line):
            r['flags'].append(line.rstrip())
        m = re.match(r'^sync: (\d+) lines heard, UNSHOWN (\d+), LATE (\d+), FROZEN (\d+)', line)
        if m:
            r['sync'] = tuple(int(x) for x in m.groups())
        if re.match(r'^\d+: HANG', line):
            r['hang'] += 1
            r['flags'].append('  ' + line.rstrip())
        m = re.match(r'^geometry: (\d+) problem', line)
        if m:
            r['geom'] = int(m[1])
        m = re.match(r'^panel check: (\d+) problem', line)
        if m:
            r['panel'] = int(m[1])
        m = re.match(r'^(?:(B[0-9A-F]{3}): )?(\d+) pass, (\d+) FAIL, (\d+) no screenshot of (\d+)(?: enabled cues, (\d+) hidden)?', line)
        if m:
            r['text'].append((m[1] or scene, int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6] or 0)))
    return r


def run_one(key, title, argv, env, expect, out):
    os.makedirs(out, exist_ok=True)
    e = dict(os.environ, **env)
    if key in OWN_STATES or key.startswith(('g_', 'c_', 'wg', 'bug', 'act', 'ending', 'b0c0')):
        e['STATES_DIR'] = os.path.join(out, 'states')
    t0 = time.time()
    if os.path.basename(argv[1]) == 'scripted.py':
        argv = argv + ['--out', out]
    proc = subprocess.run(argv, cwd=ROOT, env=e, capture_output=True, text=True, encoding='utf-8', errors='replace')
    open(os.path.join(out, 'stdout.txt'), 'w', encoding='utf-8').write(proc.stdout + '\n--- stderr ---\n' + proc.stderr)
    took = time.time() - t0
    bad = []
    if os.path.basename(argv[1]) == 'scripted.py':
        r = parse_log(os.path.join(out, 'log.txt'))
        if r['end'] is None:
            bad.append('did not finish' + (f' (exit {proc.returncode})' if proc.returncode else ''))
        for b, n in expect.items():
            if r['cues'].get(b, 0) < n:
                bad.append(f'{b}: {r["cues"].get(b, 0)} cues, expected >= {n}')
        if r['speak']:
            if r['speak'][3]:
                bad.append(f'DATA? {r["speak"][3]}')
            if r['speak'][4]:
                bad.append(f'FACE! {r["speak"][4]}')
        if r['panel']:
            bad.append(f'panel {r["panel"]}')
        if r['geom']:
            bad.append(f'geometry {r["geom"]}')
        if r['sync']:
            for k, name in ((1, 'UNSHOWN'), (2, 'LATE'), (3, 'FROZEN')):
                if r['sync'][k]:
                    bad.append(f'{name} {r["sync"][k]}')
        if key.startswith('bug078'):
            if not r['hang']:
                bad.append('BUG-078 no longer hangs: re-test the ending at the native clock and close it')
        elif r['hang']:
            bad.append(f'HANG {r["hang"]}')
        fails = sum(t[2] for t in r['text'])
        if fails and not LENIENT:
            bad.append(f'text FAIL {fails}')
        cells = {'cues': ' '.join(f'{b}:{n}' for b, n in sorted(r['cues'].items())) or '-',
                 'text': ' '.join(f'{b}:{p}/{p + f}' + (f' FAIL {f}' if f else '') + (f' hid {h}' if h else '') for b, p, f, m, _, h in r['text']) or '-',
                 'speakers': (f'{r["speak"][1]} ok, {r["speak"][2]} unverifiable' + (f', DATA? {r["speak"][3]}' if r['speak'][3] else '') + (f', FACE! {r["speak"][4]}' if r['speak'][4] else '')) if r['speak'] else '-',
                 'panel': str(r['panel']) if r['panel'] is not None else '-',
                 'flags': r['flags'], 'text_fails': fails,
                 'sync': (f'{r["sync"][0]} heard' + ''.join(f', {n} {v}' for n, v in zip(('UNSHOWN', 'LATE', 'FROZEN'), r['sync'][1:]) if v)) if r['sync'] else '-',
                 'validate': [l.rstrip() for p in glob.glob(os.path.join(out, 'validate*.txt')) for l in open(p, encoding='utf-8') if l.startswith(('FAIL', 'HIDDEN'))]}
    elif os.path.basename(argv[1]) == 'intro_run.py':
        # intro_run.py logs every change of the payload's shown index and
        # captures the screen 90 frames after it: each opening card is
        # scored by the same exact-match validator as the banks' cards
        import subs_validate as V
        doc = json.load(open(os.path.join(ROOT, 'ps1', 'translation', 'subs_INTRO.json'), encoding='utf-8'))
        icues = [c for c in doc['cues'] if c.get('enabled', True)]
        rows = doc.get('options', {}).get('rows', 3)
        shots = {}
        try:
            for line in open(os.path.join(WORK, 'intro_run.txt'), encoding='utf-8'):
                m = re.match(r'^(\d+): magic=53554253 shown=([0-9a-f]{8})', line)
                if m and int(m[2], 16) < len(icues):
                    p = os.path.join(WORK, f'intro_cue_{int(m[1]) + 90:06d}.png')
                    shots.setdefault(int(m[2], 16), [])
                    if os.path.exists(p):
                        shots[int(m[2], 16)].append(p)
        except OSError:
            pass
        if len(shots) < expect.get('INTRO', 0):
            bad.append(f'INTRO: {len(shots)} cues, expected >= {expect["INTRO"]}')
        passed, fails = 0, []
        for i, ps in sorted(shots.items()):
            c = icues[i]
            if c.get('noband'):
                continue        # the diagram still draws over its rows (its narration is baked in)
            best = max(((min((s for _, s, _ in r), default=1.0) - x, min((s for _, s, _ in r), default=1.0), x)
                        for r, x, _ in (V.validate_box(p, c, rows, 18) for p in ps)), default=(0, 0, 1))
            if best[1] >= V.PASS_SCORE and best[2] <= V.EXTRA_MAX:
                passed += 1
            else:
                fails.append(f'FAIL   {c["id"]}  best score {best[1]:.2f}, extra ink {best[2]:.2f} over {len(ps)} capture(s)')
        if fails and not LENIENT:
            bad.append(f'text FAIL {len(fails)}')
        cells = {'cues': f'INTRO:{len(shots)}', 'text': f'INTRO:{passed}/{passed + len(fails)}' + (f' FAIL {len(fails)}' if fails else ''),
                 'speakers': '-', 'panel': '-', 'sync': '-', 'flags': [], 'text_fails': len(fails), 'validate': fails}
    else:
        if proc.returncode:
            bad.append(f'exit {proc.returncode}: ' + (proc.stdout.strip().splitlines() or ['?'])[-1])
        cells = {'cues': '-', 'text': '-', 'speakers': '-', 'panel': '-', 'sync': '-', 'flags': [], 'text_fails': 0,
                 'validate': [l for l in proc.stdout.splitlines() if l.startswith(('FAIL', 'LINT!', '  ERROR'))]}
    return {'key': key, 'title': title, 'took': took, 'bad': bad, **cells}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('keys', nargs='*')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--lenient', action='store_true', help='text FAILs do not fail the set')
    ap.add_argument('--strict', action='store_true', help='(the default since the exact validator; kept for old command lines)')
    ap.add_argument('--mint', action='store_true', help='copy the whole-game checkpoints into work/states/wg and write segments.json')
    ap.add_argument('--lint-only', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--coverage', action='store_true', help='apply the coverage gate even to a subset')
    ap.add_argument('--no-coverage', action='store_true', help='skip the coverage gate')
    ap.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) // 2),
                    help='emulators at once (default half the CPUs; 1 = the old sequential set)')
    a = ap.parse_args()
    global LENIENT
    LENIENT = a.lenient
    if a.lint_only:
        lint()
    if a.mint:
        mint()
        return
    full = SET + gaps() + cards() + ACT3 + segments()
    if a.list:
        for key, title, argv, env, expect in full:
            print(f'{key:10s} {title}')
        return
    todo = [s for s in full if not a.keys or s[0] in a.keys]
    unknown = set(a.keys) - {s[0] for s in full}
    if unknown:
        sys.exit(f'unknown: {sorted(unknown)} (see --list)')
    base = os.path.join(WORK, 'regress')
    os.makedirs(base, exist_ok=True)
    t0 = time.time()

    def go(item):
        key, title, argv, env, expect = item
        print(f'== {key}: {title}', flush=True)
        r = run_one(key, title, argv, env, expect, os.path.join(base, key))
        print(f'-- {key}: {r["took"] / 60:.1f} min  cues {r["cues"]}  text {r["text"]}  speakers {r["speakers"]}  panel {r["panel"]}'
              + (f'\n   ** ' + '; '.join(r['bad']) if r['bad'] else ''), flush=True)
        for l in r['flags']:
            print('   ' + l.strip(), flush=True)
        return r

    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        results = list(ex.map(go, todo))      # SET order kept; runs overlap
    wall = f'wall {(time.time() - t0) / 60:.1f} min, {a.jobs} job(s)'
    print('\n' + wall, flush=True)

    lines = [f'regression {time.strftime("%Y-%m-%d %H:%M")}  image {os.path.join(ROOT, "patched", "Snatcher (Japan).bin")}  {wall}', '']
    lines.append(f'{"run":10s} {"min":>5s}  {"cues":24s} {"text":34s} {"speakers":40s} {"panel":5s} {"sync":22s} verdict')
    for r in results:
        verdict = 'FAIL: ' + '; '.join(r['bad']) if r['bad'] else ('text FAIL %d' % r['text_fails'] if r['text_fails'] else 'ok')
        lines.append(f'{r["key"]:10s} {r["took"] / 60:5.1f}  {r["cues"]:24s} {r["text"]:34s} {r["speakers"]:40s} {r["panel"]:5s} {r.get("sync", "-"):22s} {verdict}')
    for r in results:
        for l in r['flags'] + r['validate']:
            lines.append(f'  {r["key"]}: {l.strip()}')
    failed = any(r['bad'] for r in results)
    if (not a.keys or a.coverage) and not a.no_coverage:
        problems, got, tot, nb = coverage_gate(base)
        lines.append('')
        nex = len(json.load(open(EXEMPT, encoding='utf-8')).get('cues', {})) if os.path.exists(EXEMPT) else 0
        lines.append(f'coverage: {nb}/{len(ALL_BANKS)} banks loaded, {got}/{tot} enabled cues drawn, '
                     f'{nex} exempt (ps1/harness/coverage_exempt.json)')
        for p in problems:
            lines.append('  COVERAGE! ' + p)
        failed = failed or bool(problems)
    text = '\n'.join(lines) + '\n'
    print('\n' + text)
    open(os.path.join(base, 'summary.txt'), 'w', encoding='utf-8').write(text)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
