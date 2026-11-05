# -*- coding: utf-8 -*-
"""Mint a memory card per scene bank from the bookmarks, for the MiSTer.

    python ps1/harness/mint_cards.py                 # every bank without a card yet
    python ps1/harness/mint_cards.py B0D0 B1A0       # these banks (re-minted)
    python ps1/harness/mint_cards.py --all           # every bank, cards re-minted
    python ps1/harness/mint_cards.py --list          # what each bank would try

For each bank: its bookmarks in work/states/ (<bank>_auto first, then
<bank>_start, <bank>, then the rest newest first), each restored by
scripted.py with a one-step route {"mcard": "<bank>_auto"} - the game's own
Use Metal Gear > Save from the verb menu the bookmark sits at - until one
writes the card (mcard.py list shows it; mcard.py push NAME for the MiSTer).
A bank whose bookmarks all sit in rooms without Metal Gear (no Save on the
menu) or mid-dialogue is reported, not invented. Bookmarks older than the
image are fine here: a save loads no scene (the memory-card bank is
resident), so nothing reads a moved sector.

Results per bank go to work/mint/<bank>/ (the scripted.py run) and the
summary to work/mint/summary.txt.
"""
import argparse, glob, json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import mcard
from explore import signatures

STATES = os.path.join(WORK, 'states')
OUT = os.path.join(WORK, 'mint')
MAX_TRIES = int(os.environ.get('MINT_TRIES', '4'))    # bookmarks per bank
FRAMES = int(os.environ.get('MINT_FRAMES', '6000'))


def banks():
    return sorted(set(signatures().values()))


def candidates(bank):
    names = []
    for p in glob.glob(os.path.join(STATES, f'{bank}*.state.gz')):
        n = os.path.basename(p)[:-9]
        if n.endswith('.prev') or n.endswith('.broken') or n.endswith('_fight'):
            continue
        names.append((n, os.path.getmtime(p)))
    order = {f'{bank}_auto': 0, f'{bank}_start': 1, bank: 2}
    names.sort(key=lambda x: (order.get(x[0], 3), -x[1]))
    return [n for n, _ in names]


def sidecar_ok(name):
    p = os.path.join(STATES, name + '.json')
    try:
        m = json.load(open(p))
        return m.get('ok', 'circle') if isinstance(m, dict) else 'circle'
    except (OSError, ValueError):
        return 'circle'


def note_ok(name, ok):
    """A save that took under swapped buttons tells the bookmark's key config:
    write it into the sidecar so every later run starts right."""
    p = os.path.join(STATES, name + '.json')
    try:
        m = json.load(open(p))
    except (OSError, ValueError):
        m = None
    m = {'image': m} if not isinstance(m, dict) else m
    if m.get('ok', 'circle') != ok:
        m['ok'] = ok
        json.dump(m, open(p, 'w'))
        print(f'  {name}.json: ok = {ok}')


def mint(bank, name, ok=None):
    out = os.path.join(OUT, bank)
    os.makedirs(out, exist_ok=True)
    route = os.path.join(out, 'route.json')
    json.dump({'scene': bank, 'note': f'mint a card from {name}',
               'actions': [{'mcard': f'{bank}_auto', 'patience': 2500}]},
              open(route, 'w'))
    env = dict(os.environ, AUTOSAVE='0')
    if ok:
        env['PILOT_OK'] = ok
    cmd = [sys.executable, os.path.join(HERE, 'scripted.py'), '--scene', bank, '--state', name,
           '--route', route, '--frames', str(FRAMES), '--shot-every', '0', '--out', out]
    t = time.time()
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    log = open(os.path.join(out, 'log.txt'), encoding='utf-8', errors='replace').read() \
        if os.path.exists(os.path.join(out, 'log.txt')) else r.stdout
    verdict = 'crashed' if r.returncode and 'Traceback' in r.stderr else 'no verb menu'
    for line in log.splitlines():
        if 'mcard: save written' in line:
            verdict = 'saved'
        elif 'mcard: save NOT written' in line:
            verdict = 'NOT written'
        elif 'mcard: no Save' in line:
            verdict = 'no Save: ' + line.split('mcard: ', 1)[1]
        elif 'no verb menu here' in line:
            verdict = 'no verb menu: ' + line.split('here ', 1)[1]
    if verdict == 'crashed':
        open(os.path.join(out, 'stderr.txt'), 'w', encoding='utf-8').write(r.stderr)
    if verdict == 'saved':
        # the card says which bank was live (a bookmark named for a bank can
        # hold its neighbour: B0F0_masked_v07 sat in B0D0) - a card of another
        # bank keeps that bank's name and this bank stays unminted
        ix = mcard.load_index()
        e = ix['snapshots'].get(f'{bank}_auto')
        if e and e.get('bank') and e['bank'] != bank:
            other = e['bank']
            newname = f'{other}_via_{name}'
            newpath = mcard.snap_path(newname)
            os.replace(e['path'], newpath)
            e['path'] = newpath
            ix['snapshots'][newname] = ix['snapshots'].pop(f'{bank}_auto')
            mcard.write_index(ix)
            verdict = f'saved, but that bookmark is in {other} (kept as {newname})'
    return verdict, time.time() - t


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('bank', nargs='*')
    ap.add_argument('--all', action='store_true', help='re-mint banks that already have a card')
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    have = mcard.load_index()['snapshots']
    todo = [b.upper() for b in a.bank] or banks()
    if a.list:
        for b in todo:
            c = candidates(b)
            print(f'{b}: {"card " + ("ok" if have.get(b + "_auto", {}).get("saved") else "-"):8} '
                  f'{len(c)} bookmark(s): {", ".join(c[:MAX_TRIES]) or "-"}')
        return
    os.makedirs(OUT, exist_ok=True)
    summary = []
    for b in todo:
        if not a.bank and not a.all and have.get(b + '_auto', {}).get('saved'):
            summary.append((b, 'kept', ''))
            print(f'{b}: card already there', flush=True)
            continue
        c = candidates(b)
        if not c:
            summary.append((b, 'no bookmark', ''))
            print(f'{b}: no bookmark', flush=True)
            continue
        result = None
        for name in c[:MAX_TRIES]:
            # the sidecar's buttons first, then the other way round: a
            # bookmark from a swapped-buttons card with no sidecar confirms
            # its way out of the room on the pilot's first cancel
            first = sidecar_ok(name)
            for ok in (first, 'cross' if first == 'circle' else 'circle'):
                verdict, dt = mint(b, name, ok)
                print(f'{b}: {name} [{ok}]: {verdict} ({dt:.0f}s)', flush=True)
                result = (b, verdict, f'{name} [{ok}]')
                if verdict == 'saved':
                    note_ok(name, ok)
                    break
            if verdict == 'saved':
                break
        summary.append(result)
    with open(os.path.join(OUT, 'summary.txt'), 'w', encoding='utf-8') as fh:
        for b, v, n in summary:
            fh.write(f'{b:5} {v:40} {n}\n')
    print()
    print(open(os.path.join(OUT, 'summary.txt'), encoding='utf-8').read())


if __name__ == '__main__':
    main()
