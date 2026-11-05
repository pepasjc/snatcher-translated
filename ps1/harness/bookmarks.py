# -*- coding: utf-8 -*-
"""The bookmark store: what exists per bank, how stale it is, and whether
it still responds.

    python ps1/harness/bookmarks.py list            # per bank: names, image match, routes
    python ps1/harness/bookmarks.py check B210_auto B0C0_start   # restore each, confirm a live menu
    python ps1/harness/bookmarks.py check --all-auto             # every <bank>_auto

A bookmark is work/states/<name>.state.gz with a <name>.json stamp naming
the image it was taken against (scripted.image_stamp). Stale ones still
work inside their own scene (raminject refreshes bank, blob and exec) but
the next scene load may hang - the drive state is the old image's.
scripted.py takes <bank>_auto for every bank a run passes through
(AUTOSAVE, on by default), so any long run refreshes the set.
"""
import argparse, ctypes as C, glob, gzip, json, os, sys, time
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

STATES = os.path.join(WORK, 'states')
IMAGE = os.path.join(ROOT, 'patched', 'Snatcher (Japan).cue')


def image_stamp(cue=IMAGE):
    bins = sorted(glob.glob(os.path.join(os.path.dirname(cue) or '.', '*.bin')))
    return [[os.path.basename(b), os.path.getsize(b), int(os.path.getmtime(b))] for b in bins]


def bookmarks():
    out = {}
    for p in sorted(glob.glob(os.path.join(STATES, '*.state.gz'))):
        name = os.path.basename(p)[:-9]
        if name.endswith('.prev') or name.endswith('.broken'):
            continue
        stamp = p[:-9] + '.json'
        meta = json.load(open(stamp)) if os.path.exists(stamp) else None
        img = meta.get('image') if isinstance(meta, dict) else meta
        out[name] = {'path': p, 'size': os.path.getsize(p), 'mtime': os.path.getmtime(p),
                     'image': img, 'ok': meta.get('ok', 'circle') if isinstance(meta, dict) else 'circle'}
    return out


def freshness(bm, now_stamp):
    if bm['image'] is None:
        return 'no stamp'
    # the main image entry only: other .bin files in patched/ come and go
    mine = {tuple(x) for x in bm['image'] if x[0] == 'Snatcher (Japan).bin'}
    cur = {tuple(x) for x in now_stamp if x[0] == 'Snatcher (Japan).bin'}
    return 'current' if mine == cur else 'stale'


def cmd_list(a):
    now = image_stamp()
    bms = bookmarks()
    banks = sorted(os.path.basename(p)[5:9] for p in glob.glob(os.path.join(ROOT, 'ps1', 'translation', 'subs_B*.json')))
    for bank in banks:
        mine = {n: b for n, b in bms.items() if n.startswith(bank)}
        routes = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(HERE, 'routes', f'{bank}*.json')))
        cur = [n for n, b in mine.items() if freshness(b, now) == 'current']
        print(f'{bank}: {len(mine):3d} bookmarks, {len(cur):2d} against the current image'
              f'{"  (none)" if not mine else ""}  routes: {", ".join(routes) or "-"}')
        if a.verbose:
            for n, b in sorted(mine.items(), key=lambda kv: -kv[1]["mtime"]):
                print(f'      {n:28s} {freshness(b, now):8s} {time.strftime("%m-%d %H:%M", time.localtime(b["mtime"]))} {b["size"] // 1024:5d} KB ok={b["ok"]}')


def cmd_check(a):
    import emurun, menustate
    from explore import restore_scene
    from menuread import read_menu
    names = a.names
    if a.all_auto:
        names = sorted(n for n in bookmarks() if n.endswith('_auto'))
    emu = emurun.Emu()
    emu.load(IMAGE)
    for _ in range(60):
        emu.run()
    core = emu.core
    core.retro_get_memory_data.restype = C.c_void_p
    for name in names:
        p = os.path.join(STATES, f'{name}.state.gz')
        if not os.path.exists(p):
            print(f'{name}: missing'); continue
        blob = gzip.decompress(open(p, 'rb').read())
        scene = name[:4]
        try:
            restore_scene(emu, scene, blob)
        except Exception as e:
            print(f'{name}: restore failed: {e}'); continue
        ram = core.retro_get_memory_data(2)
        live_at = None
        for f in range(a.frames):
            emu.run()
            live, idx, n = menustate.read(ram)
            if live and live_at is None:
                live_at = f
                labels = read_menu(ram)
                break
        if live_at is None:
            print(f'{name}: NO live menu within {a.frames} frames (a bookmark taken mid-text or mid-fade)')
        else:
            print(f'{name}: menu live at +{live_at}: {labels}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    l = sub.add_parser('list'); l.add_argument('-v', '--verbose', action='store_true')
    c = sub.add_parser('check'); c.add_argument('names', nargs='*'); c.add_argument('--all-auto', action='store_true')
    c.add_argument('--frames', type=int, default=600)
    a = ap.parse_args()
    {'list': cmd_list, 'check': cmd_check}[a.cmd](a)


if __name__ == '__main__':
    main()
