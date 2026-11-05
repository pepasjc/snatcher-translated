# -*- coding: utf-8 -*-
"""Mint a backup-RAM save per scene bank from the bookmarks, for the MiSTer.

    python saturn/harness/mint_saves.py                 # every bank without a save yet
    python saturn/harness/mint_saves.py B020 B080       # these banks (re-minted)
    python saturn/harness/mint_saves.py --all           # every bank, saves re-minted
    python saturn/harness/mint_saves.py --list          # what each bank would try

For each bank: its bookmarks in work/saturn/states/ (<bank>_auto first, then
<bank>_start, <bank>, then the rest newest first), each restored by
satplay.py with a one-step route {"bsave": "<bank>_auto"} - the game's own
Use Metal Gear > Save from the verb menu the bookmark sits at - and the
save then CHECKED (satsave_check.py: a headless boot with it in work/emu,
CONTINUE, the file loaded, the bank in RAM and its verb menu live). The
first candidate whose save passes is kept; the check matters: a save taken
at a scene's arrival menu (B020_auto, B080_auto, 2026-09-15) loads its
bank and then sits on the JUNKER panel for ever - the loader's 'vag file
change' for the resumed room carries id 0x8140 and never completes - while
saves from B0B0_auto / B0C0_auto resume at their verb menu. A bank whose
bookmarks all sit in rooms without Metal Gear (no Save on the menu) or
whose saves never pass is reported, not invented.

Results per bank go to work/saturn/saves/mint/<bank>/ (the satplay and
check runs) and the summary to work/saturn/saves/mint/summary.txt.
"""
import argparse, glob, json, os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import satsave

STATES = satsave.STATES
OUT = os.path.join(satsave.STORE, 'mint')
MAX_TRIES = int(os.environ.get('MINT_TRIES', '4'))    # bookmarks per bank
FRAMES = int(os.environ.get('MINT_FRAMES', '12000'))
CHECK_FRAMES = int(os.environ.get('MINT_CHECK_FRAMES', '9000'))
BANKS = ['B%03X' % (i * 0x10) for i in range(39)]


def candidates(bank):
    names = []
    for p in glob.glob(os.path.join(STATES, f'{bank}*.state.gz')):
        n = os.path.basename(p)[:-9]
        if n.endswith('.prev') or n.endswith('.broken') or n.endswith('.bad_dense') or '_fight' in n:
            continue
        if re.search(r'_f\d+$', n) or n.startswith('stall_'):
            continue                # --dump-at frame dumps and the wedge dumps sit mid-scene, not at a verb menu
        names.append((n, os.path.getmtime(p)))
    order = {f'{bank}_auto': 0, f'{bank}_start': 1, bank: 2}
    names.sort(key=lambda x: (order.get(x[0], 3), -x[1]))
    return [n for n, _ in names]


def note(name, key, value):
    """Record in the bookmark's sidecar whether its save loads (bsave: ok / stalls)."""
    p = os.path.join(STATES, name + '.json')
    try:
        m = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        m = {}
    if not isinstance(m, dict):
        m = {'meta': m}
    if m.get(key) != value:
        m[key] = value
        json.dump(m, open(p, 'w', encoding='utf-8'), ensure_ascii=False)


def mint(bank, name, image):
    out = os.path.join(OUT, bank, name)
    os.makedirs(out, exist_ok=True)
    route = os.path.join(out, 'route.json')
    json.dump({'scene': bank, 'note': f'mint a save from {name}',
               'actions': [{'bsave': f'{bank}_auto'}, {'idle': 60}]}, open(route, 'w'))
    cmd = [sys.executable, os.path.join(HERE, 'satplay.py'), '--route', route, '--state', name,
           '--frames', str(FRAMES), '--no-autosave', '--out', out]
    if image:
        cmd += ['--image', image]
    t = time.time()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    log = open(os.path.join(out, 'log.txt'), encoding='utf-8', errors='replace').read() \
        if os.path.exists(os.path.join(out, 'log.txt')) else r.stdout
    verdict = 'crashed' if r.returncode and 'Traceback' in r.stderr else 'no verb menu'
    for line in log.splitlines():
        if 'bsave: backup RAM changed' in line:
            verdict = 'saved'
        elif 'bsave: backup RAM UNCHANGED' in line:
            verdict = 'NOT written'
        elif 'bsave: no Save' in line:
            verdict = 'no Save: ' + line.split('bsave: ', 1)[1]
    if verdict == 'crashed':
        open(os.path.join(out, 'stderr.txt'), 'w', encoding='utf-8').write(r.stderr)
    return verdict, time.time() - t


def check(bank, name, image):
    out = os.path.join(OUT, bank, name, 'check')
    cmd = [sys.executable, os.path.join(HERE, 'satsave_check.py'), f'{bank}_auto', '--frames', str(CHECK_FRAMES), '--out', out]
    if image:
        cmd += ['--image', image]
    t = time.time()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    verdict = next((l.split('verdict: ', 1)[1] for l in r.stdout.splitlines() if l.startswith('verdict:')), 'check crashed')
    return r.returncode == 0, verdict, time.time() - t


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('bank', nargs='*')
    ap.add_argument('--all', action='store_true', help='re-mint banks that already have a save')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--image', help='the cue to play (default: satplay\'s play image)')
    ap.add_argument('--no-check', action='store_true', help='keep the first save written, unchecked')
    a = ap.parse_args()
    have = satsave.load_index()['snapshots']
    todo = [b.upper() for b in a.bank] or BANKS
    if a.list:
        for b in todo:
            c = candidates(b)
            e = have.get(b + '_auto', {})
            print(f'{b}: {"save " + ("ok" if e.get("checked") else "-" if not e.get("saved") else "unchecked"):16} '
                  f'{len(c)} bookmark(s): {", ".join(c[:MAX_TRIES]) or "-"}')
        return
    os.makedirs(OUT, exist_ok=True)
    summary = []
    for b in todo:
        if not a.bank and not a.all and have.get(b + '_auto', {}).get('saved'):
            summary.append((b, 'kept', '')); print(f'{b}: save already there', flush=True); continue
        c = candidates(b)
        if not c:
            summary.append((b, 'no bookmark', '')); print(f'{b}: no bookmark', flush=True); continue
        result = None
        for name in c[:MAX_TRIES]:
            verdict, dt = mint(b, name, a.image)
            print(f'{b}: {name}: {verdict} ({dt:.0f}s)', flush=True)
            result = (b, verdict, name)
            if verdict != 'saved':
                continue
            ix = satsave.load_index()
            e = ix['snapshots'].get(f'{b}_auto', {})
            if e.get('bank') and e['bank'] != b:
                # the bookmark sits in another bank: keep the save under that
                # bank's name and go on looking for this one
                other = e['bank']; newname = f'{other}_via_{name}'
                os.replace(e['path'], satsave.snap_path(newname)); e['path'] = satsave.snap_path(newname)
                ix['snapshots'][newname] = ix['snapshots'].pop(f'{b}_auto'); satsave.write_index(ix)
                result = (b, f'saved, but that bookmark is in {other} (kept as {newname})', name)
                print(f'{b}: {result[1]}', flush=True)
                continue
            if a.no_check:
                break
            ok, cv, dt = check(b, name, a.image)
            print(f'{b}: {name}: check {cv} ({dt:.0f}s)', flush=True)
            note(name, 'bsave', 'ok' if ok else 'stalls')
            ix = satsave.load_index(); e = ix['snapshots'][f'{b}_auto']
            e['checked'] = ok; e['check'] = cv; e['bookmark'] = name; satsave.write_index(ix)
            result = (b, 'saved and checked' if ok else f'saved but the load stalls ({cv})', name)
            if ok:
                break
        summary.append(result)
    with open(os.path.join(OUT, 'summary.txt'), 'w', encoding='utf-8') as fh:
        for b, v, n in summary:
            fh.write(f'{b:5} {v:60} {n}\n')
    print()
    print(open(os.path.join(OUT, 'summary.txt'), encoding='utf-8').read())


if __name__ == '__main__':
    main()
